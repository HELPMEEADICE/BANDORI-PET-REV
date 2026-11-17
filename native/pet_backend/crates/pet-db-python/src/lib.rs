//! Owned value conversion precedes detaching. Locks are gone before errors or
//! results become Python objects; no Python callback can run under a DB lock.
use pet_db::{Database, Error};
use pyo3::{
    exceptions::{PyRuntimeError, PyValueError},
    prelude::*,
    types::{PyBool, PyBytes, PyDict, PyFloat, PyInt, PyList, PyString, PyTuple},
};
use serde_json::Value;
use std::path::PathBuf;

fn from_python(v: &Bound<'_, PyAny>) -> PyResult<Value> {
    if v.is_none() {
        return Ok(Value::Null);
    }
    if v.is_instance_of::<PyBool>() {
        return Ok(Value::Bool(v.extract()?));
    }
    if v.is_instance_of::<PyInt>() {
        return Ok(Value::from(v.extract::<i64>()?));
    }
    if v.is_instance_of::<PyFloat>() {
        let number = v.extract::<f64>()?;
        return Ok(if number.is_finite() {
            Value::from(number)
        } else {
            Value::String(number.to_string())
        });
    }
    if v.is_instance_of::<PyString>() {
        return Ok(Value::String(v.extract()?));
    }
    if let Ok(d) = v.cast::<PyDict>() {
        let mut m = serde_json::Map::new();
        for (k, v) in d.iter() {
            m.insert(k.extract()?, from_python(&v)?);
        }
        return Ok(Value::Object(m));
    }
    if let Ok(l) = v.cast::<PyList>() {
        return l
            .iter()
            .map(|v| from_python(&v))
            .collect::<PyResult<Vec<_>>>()
            .map(Value::Array);
    }
    if let Ok(t) = v.cast::<PyTuple>() {
        return t
            .iter()
            .map(|v| from_python(&v))
            .collect::<PyResult<Vec<_>>>()
            .map(Value::Array);
    }
    Err(PyValueError::new_err("unsupported database argument"))
}
fn to_python(py: Python<'_>, v: Value) -> PyResult<Py<PyAny>> {
    Ok(match v {
        Value::Null => py.None(),
        Value::Bool(v) => v.into_pyobject(py)?.to_owned().into_any().unbind(),
        Value::Number(v) => {
            if let Some(i) = v.as_i64() {
                i.into_pyobject(py)?.into_any().unbind()
            } else if let Some(i) = v.as_u64() {
                i.into_pyobject(py)?.into_any().unbind()
            } else {
                v.as_f64()
                    .ok_or_else(|| PyValueError::new_err("invalid number"))?
                    .into_pyobject(py)?
                    .into_any()
                    .unbind()
            }
        }
        Value::String(v) => v.into_pyobject(py)?.into_any().unbind(),
        Value::Array(v) => {
            let values = v
                .into_iter()
                .map(|v| to_python(py, v))
                .collect::<PyResult<Vec<_>>>()?;
            PyList::new(py, values)?.into_any().unbind()
        }
        Value::Object(v) => {
            let d = PyDict::new(py);
            for (k, v) in v {
                d.set_item(k, to_python(py, v)?)?;
            }
            d.into_any().unbind()
        }
    })
}
fn error(py: Python<'_>, e: Error) -> PyErr {
    let details = if let Error::Sql(pet_db::SqlError::SqliteFailure(code, _)) = &e {
        Some((
            code.extended_code,
            match code.extended_code {
                5 => "SQLITE_BUSY",
                6 => "SQLITE_LOCKED",
                9 => "SQLITE_INTERRUPT",
                11 => "SQLITE_CORRUPT",
                19 => "SQLITE_CONSTRAINT",
                26 => "SQLITE_NOTADB",
                275 => "SQLITE_CONSTRAINT_CHECK",
                787 => "SQLITE_CONSTRAINT_FOREIGNKEY",
                1299 => "SQLITE_CONSTRAINT_NOTNULL",
                1555 => "SQLITE_CONSTRAINT_PRIMARYKEY",
                2067 => "SQLITE_CONSTRAINT_UNIQUE",
                _ => "SQLITE_ERROR",
            },
        ))
    } else {
        None
    };
    let name = match &e {
        Error::Sql(
            pet_db::SqlError::InvalidParameterCount(..)
            | pet_db::SqlError::InvalidParameterName(..)
            | pet_db::SqlError::MultipleStatement,
        ) => "ProgrammingError",
        Error::Sql(e) => match e.sqlite_error_code() {
            Some(pet_db::SqlErrorCode::ConstraintViolation) => "IntegrityError",
            Some(pet_db::SqlErrorCode::DatabaseCorrupt | pet_db::SqlErrorCode::NotADatabase) => {
                "DatabaseError"
            }
            _ => "OperationalError",
        },
        Error::Closed | Error::Process => "ProgrammingError",
        Error::Invalid(_) => return PyValueError::new_err(e.to_string()),
        Error::Io(e) => return pyo3::exceptions::PyOSError::new_err(e.to_string()),
        _ => return PyRuntimeError::new_err(e.to_string()),
    };
    match py
        .import("sqlite3")
        .and_then(|m| m.getattr(name))
        .and_then(|cls| cls.call1((e.to_string(),)))
    {
        Ok(value) => {
            if let Some((code, name)) = details {
                let _ = value.setattr("sqlite_errorcode", code);
                let _ = value.setattr("sqlite_errorname", name);
            }
            PyErr::from_value(value)
        }
        Err(e) => e,
    }
}

#[pyclass(frozen, module = "bandori_core._pet_db")]
struct NativeDatabase {
    db: Database,
}

#[pymethods]
impl NativeDatabase {
    /// Benchmark-only conversion probe: no database or lock is involved.
    #[staticmethod]
    fn _conversion_probe(py: Python<'_>, value: &Bound<'_, PyAny>) -> PyResult<Py<PyAny>> {
        to_python(py, from_python(value)?)
    }
    #[staticmethod]
    fn migrate_legacy(py: Python<'_>, source: PathBuf, target: PathBuf) -> PyResult<()> {
        py.detach(|| pet_db::maintenance::migrate_legacy(&source, &target))
            .map_err(|e| error(py, e))
    }
    #[staticmethod]
    fn summary(py: Python<'_>, path: PathBuf) -> PyResult<Py<PyAny>> {
        to_python(
            py,
            py.detach(|| pet_db::maintenance::summary_file(&path))
                .map_err(|e| error(py, e))?,
        )
    }
    #[staticmethod]
    #[pyo3(signature=(source,destination,check=true))]
    fn snapshot(
        py: Python<'_>,
        source: PathBuf,
        destination: PathBuf,
        check: bool,
    ) -> PyResult<()> {
        py.detach(|| pet_db::maintenance::snapshot(&source, &destination, check))
            .map_err(|e| error(py, e))
    }
    fn restore(&self, py: Python<'_>, source: PathBuf) -> PyResult<()> {
        py.detach(|| self.db.restore(&source))
            .map_err(|e| error(py, e))
    }
    #[new]
    fn new(py: Python<'_>, path: PathBuf) -> PyResult<Self> {
        py.detach(|| Database::open(&path))
            .map(|db| Self { db })
            .map_err(|e| error(py, e))
    }
    fn call(&self, py: Python<'_>, op: &str, args: &Bound<'_, PyAny>) -> PyResult<Py<PyAny>> {
        let args = from_python(args)?;
        if !args.is_object() {
            return Err(PyValueError::new_err(
                "database arguments must be an object",
            ));
        }
        if matches!(op, "get_messages" | "get_group_messages") {
            let messages = py
                .detach(|| self.db.history(&args, op == "get_group_messages"))
                .map_err(|e| error(py, e))?;
            let out = PyList::empty(py);
            for message in messages {
                let d = PyDict::new(py);
                d.set_item(pyo3::intern!(py, "id"), message.id)?;
                match message.conversation_id {
                    pet_db::history::ConversationId::Private(i) => {
                        d.set_item(pyo3::intern!(py, "conversation_id"), i)?
                    }
                    pet_db::history::ConversationId::Group(s) => {
                        d.set_item(pyo3::intern!(py, "conversation_id"), s)?
                    }
                };
                if let Some(group) = message.group_key {
                    d.set_item(pyo3::intern!(py, "group_key"), group)?;
                }
                d.set_item(pyo3::intern!(py, "role"), message.role)?;
                d.set_item(pyo3::intern!(py, "content"), message.content)?;
                d.set_item(
                    pyo3::intern!(py, "reasoning_content"),
                    message.reasoning_content,
                )?;
                d.set_item(
                    pyo3::intern!(py, "attachments_json"),
                    message.attachments_json,
                )?;
                d.set_item(
                    pyo3::intern!(py, "tool_trace_json"),
                    message.tool_trace_json,
                )?;
                d.set_item(pyo3::intern!(py, "created_at"), message.created_at)?;
                out.append(d)?;
            }
            return Ok(out.into_any().unbind());
        }
        let value = py
            .detach(|| self.db.call(op, &args))
            .map_err(|e| error(py, e))?;
        to_python(py, value)
    }
    fn close(&self, py: Python<'_>) -> PyResult<()> {
        py.detach(|| self.db.close()).map_err(|e| error(py, e))
    }
    fn interrupt(&self) {
        self.db.interrupt();
    }
    fn control(&self, py: Python<'_>, action: &str) -> PyResult<Py<PyAny>> {
        to_python(
            py,
            py.detach(|| self.db.control(action))
                .map_err(|e| error(py, e))?,
        )
    }
    fn raw_execute(
        &self,
        py: Python<'_>,
        sql: &str,
        parameters: &Bound<'_, PyAny>,
    ) -> PyResult<Py<PyAny>> {
        let parameters = parameters
            .try_iter()?
            .map(|v| {
                let v = v?;
                Ok(if v.is_none() {
                    pet_db::SqlValue::Null
                } else if v.is_instance_of::<PyInt>() || v.is_instance_of::<PyBool>() {
                    pet_db::SqlValue::Integer(v.extract()?)
                } else if v.is_instance_of::<PyFloat>() {
                    pet_db::SqlValue::Real(v.extract()?)
                } else if let Ok(b) = v.cast::<PyBytes>() {
                    pet_db::SqlValue::Blob(b.as_bytes().to_vec())
                } else {
                    pet_db::SqlValue::Text(v.extract()?)
                })
            })
            .collect::<PyResult<Vec<_>>>()?;
        let out = py
            .detach(|| self.db.raw_execute(sql, &parameters))
            .map_err(|e| error(py, e))?;
        let rows = PyList::empty(py);
        for row in out.rows {
            let mut values = vec![];
            for v in row {
                values.push(match v {
                    pet_db::SqlValue::Null => py.None(),
                    pet_db::SqlValue::Integer(i) => i.into_pyobject(py)?.into_any().unbind(),
                    pet_db::SqlValue::Real(f) => f.into_pyobject(py)?.into_any().unbind(),
                    pet_db::SqlValue::Text(s) => s.into_pyobject(py)?.into_any().unbind(),
                    pet_db::SqlValue::Blob(b) => PyBytes::new(py, &b).into_any().unbind(),
                });
            }
            rows.append(PyTuple::new(py, values)?)?;
        }
        let d = PyDict::new(py);
        d.set_item("rows", rows)?;
        d.set_item("columns", out.columns)?;
        d.set_item("rowcount", out.rowcount)?;
        d.set_item("lastrowid", out.lastrowid)?;
        Ok(d.into_any().unbind())
    }
}

#[pymodule]
fn _pet_db(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add("BACKEND", "rust-pet-db")?;
    m.add("SQLITE_VERSION", pet_db::sqlite_version())?;
    m.add_class::<NativeDatabase>()?;
    Ok(())
}
