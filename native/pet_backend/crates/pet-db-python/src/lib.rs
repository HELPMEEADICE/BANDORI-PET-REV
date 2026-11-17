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
        return Ok(Value::from(v.extract::<f64>()?));
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
    let name = match &e {
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
        Ok(value) => PyErr::from_value(value),
        Err(e) => e,
    }
}

#[pyclass(frozen, module = "bandori_core._pet_db")]
struct NativeDatabase {
    db: Database,
}

#[pymethods]
impl NativeDatabase {
    #[new]
    fn new(py: Python<'_>, path: PathBuf) -> PyResult<Self> {
        py.detach(|| Database::open(&path))
            .map(|db| Self { db })
            .map_err(|e| error(py, e))
    }
    fn call(&self, py: Python<'_>, op: &str, args: &Bound<'_, PyAny>) -> PyResult<Py<PyAny>> {
        let args = from_python(args)?;
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
    m.add_class::<NativeDatabase>()?;
    Ok(())
}
