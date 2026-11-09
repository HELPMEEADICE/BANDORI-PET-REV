//! Thin, batch-oriented Python adapter. Never hold the GIL while waiting on an
//! OS lock or our per-object Mutex; never call Python with that Mutex held.
use std::path::PathBuf;
use std::sync::Mutex;

use pet_ipc::Queue;
use pyo3::exceptions::PyRuntimeError;
use pyo3::prelude::*;
use pyo3::types::PyBytes;

#[derive(Default)]
struct State {
    queue: Option<Queue>,
    dropped: u64,
    publish_error: String,
    read_error: String,
}

impl State {
    fn read(&mut self, max_messages: Option<usize>) -> Vec<String> {
        let Some(queue) = self.queue.as_mut() else {
            return Vec::new();
        };
        let result = queue.read_available(max_messages);
        self.dropped = queue.dropped_messages();
        match result {
            Ok(lines) => {
                self.read_error.clear();
                lines
            }
            Err(error) => {
                self.read_error = error.to_string();
                Vec::new()
            }
        }
    }
}

#[pyclass(frozen, module = "bandori_core._pet_ipc")]
struct NativeQueue {
    state: Mutex<State>,
    #[pyo3(get)]
    slot_count: u32,
    #[pyo3(get)]
    slot_size: u32,
}

fn runtime(error: impl std::fmt::Display) -> PyErr {
    PyRuntimeError::new_err(error.to_string())
}

impl NativeQueue {
    fn new(queue: Queue) -> Self {
        Self {
            slot_count: queue.slot_count(),
            slot_size: queue.slot_size(),
            state: Mutex::new(State {
                queue: Some(queue),
                ..State::default()
            }),
        }
    }
}

#[pymethods]
impl NativeQueue {
    #[staticmethod]
    fn create(py: Python<'_>, path: PathBuf, slot_count: u32, slot_size: u32) -> PyResult<Self> {
        py.detach(|| {
            Queue::create(&path, slot_count, slot_size)
                .map(Self::new)
                .map_err(runtime)
        })
    }

    #[staticmethod]
    #[pyo3(signature = (path, start_at_tail=true))]
    fn attach(py: Python<'_>, path: PathBuf, start_at_tail: bool) -> PyResult<Self> {
        py.detach(|| {
            Queue::attach(&path, start_at_tail)
                .map(Self::new)
                .map_err(runtime)
        })
    }

    fn publish(&self, py: Python<'_>, line: String) -> bool {
        py.detach(|| {
            let Ok(mut state) = self.state.lock() else {
                return false;
            };
            let result = match state.queue.as_mut() {
                Some(queue) => queue.publish(&line),
                None if line.trim_end_matches(['\r', '\n']).is_empty() => {
                    Err(pet_ipc::Error::Empty)
                }
                None if line.trim_end_matches(['\r', '\n']).len() > self.slot_size as usize => {
                    Err(pet_ipc::Error::Oversize(self.slot_size))
                }
                None => Err(pet_ipc::Error::Detached),
            };
            state.publish_error = result
                .as_ref()
                .err()
                .map(ToString::to_string)
                .unwrap_or_default();
            result.is_ok()
        })
    }

    #[pyo3(signature = (max_messages=None))]
    fn read_available(&self, py: Python<'_>, max_messages: Option<usize>) -> Vec<String> {
        py.detach(|| {
            let Ok(mut state) = self.state.lock() else {
                return Vec::new();
            };
            state.read(max_messages)
        })
    }

    /// Read payloads and diagnostics in a single FFI call.
    #[pyo3(signature = (max_messages=None))]
    fn read_batch(
        &self,
        py: Python<'_>,
        max_messages: Option<usize>,
    ) -> (Vec<String>, u64, String) {
        py.detach(|| {
            let Ok(mut state) = self.state.lock() else {
                return (Vec::new(), 0, "queue mutex is poisoned".into());
            };
            let lines = state.read(max_messages);
            (lines, state.dropped, state.read_error.clone())
        })
    }

    fn close(&self, py: Python<'_>) -> PyResult<()> {
        py.detach(|| {
            let mut state = self.state.lock().map_err(runtime)?;
            if let Some(mut queue) = state.queue.take() {
                state.dropped = queue.dropped_messages();
                queue.close().map_err(runtime)?;
            }
            Ok(())
        })
    }

    fn is_attached(&self, py: Python<'_>) -> bool {
        py.detach(|| {
            self.state
                .lock()
                .is_ok_and(|s| s.queue.as_ref().is_some_and(Queue::is_attached))
        })
    }

    #[getter]
    fn dropped_messages(&self, py: Python<'_>) -> PyResult<u64> {
        py.detach(|| self.state.lock().map(|s| s.dropped).map_err(runtime))
    }

    #[setter]
    fn set_dropped_messages(&self, py: Python<'_>, value: u64) -> PyResult<()> {
        py.detach(|| {
            let mut state = self.state.lock().map_err(runtime)?;
            if let Some(queue) = state.queue.as_mut() {
                queue.set_dropped_messages(value);
            }
            state.dropped = value;
            Ok(())
        })
    }

    #[getter]
    fn last_publish_error(&self, py: Python<'_>) -> PyResult<String> {
        py.detach(|| {
            self.state
                .lock()
                .map(|s| s.publish_error.clone())
                .map_err(runtime)
        })
    }

    #[setter]
    fn set_last_publish_error(&self, py: Python<'_>, value: String) -> PyResult<()> {
        py.detach(|| {
            self.state.lock().map_err(runtime)?.publish_error = value;
            Ok(())
        })
    }

    #[getter]
    fn last_read_error(&self, py: Python<'_>) -> PyResult<String> {
        py.detach(|| {
            self.state
                .lock()
                .map(|s| s.read_error.clone())
                .map_err(runtime)
        })
    }
}

#[pymodule]
fn _pet_ipc(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_class::<NativeQueue>()?;
    module.add_class::<NativeMemory>()?;
    module.add("BACKEND", "rust-pet-ipc")?;
    module.add("PROTOCOL_VERSION", pet_ipc::VERSION)?;
    Ok(())
}

/// Low-level compatibility adapter; the application queue never uses snapshots.
#[pyclass(frozen, module = "bandori_core._pet_ipc")]
struct NativeMemory(Mutex<pet_ipc::MappedRegion>);

#[pymethods]
impl NativeMemory {
    #[staticmethod]
    fn create(py: Python<'_>, path: PathBuf, size: usize) -> PyResult<Self> {
        py.detach(|| {
            pet_ipc::MappedRegion::create(&path, size)
                .map(|r| Self(Mutex::new(r)))
                .map_err(runtime)
        })
    }
    #[staticmethod]
    fn attach(py: Python<'_>, path: PathBuf) -> PyResult<Self> {
        py.detach(|| {
            pet_ipc::MappedRegion::attach(&path)
                .map(|r| Self(Mutex::new(r)))
                .map_err(runtime)
        })
    }
    fn lock(&self, py: Python<'_>) -> PyResult<Py<PyBytes>> {
        let bytes = py.detach(|| self.0.lock().map_err(runtime)?.lock().map_err(runtime))?;
        Ok(PyBytes::new(py, &bytes).unbind())
    }
    fn snapshot(&self, py: Python<'_>) -> PyResult<Py<PyBytes>> {
        let bytes = py.detach(|| self.0.lock().map_err(runtime)?.snapshot().map_err(runtime))?;
        Ok(PyBytes::new(py, &bytes).unbind())
    }
    fn unlock(&self, py: Python<'_>, bytes: Vec<u8>) -> PyResult<()> {
        py.detach(|| {
            self.0
                .lock()
                .map_err(runtime)?
                .unlock(&bytes)
                .map_err(runtime)
        })
    }
    fn close(&self, py: Python<'_>) -> PyResult<()> {
        py.detach(|| self.0.lock().map_err(runtime)?.close().map_err(runtime))
    }
}
