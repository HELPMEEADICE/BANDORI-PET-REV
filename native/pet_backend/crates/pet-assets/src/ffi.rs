//! Small versioned C ABI, independent of Python's version and allocator.
//! Request: UTF-8 JSON. Response: little-endian u32 JSON length, JSON metadata,
//! then concatenated resource bytes. Buffers are freed by their Rust allocator.

use std::collections::BTreeMap;
use std::path::Path;
use std::sync::{Mutex, OnceLock};

use serde::Deserialize;
use serde_json::{json, Value};

use crate::virtual_path::ModelPath;
use crate::{ArchiveCache, ArchiveRevision, CacheError};

static CACHE: OnceLock<Mutex<ArchiveCache>> = OnceLock::new();

#[derive(Deserialize)]
#[serde(tag = "op", rename_all = "snake_case")]
enum Request {
    List {
        archive: String,
    },
    Scan {
        archive: String,
    },
    Revision {
        path: String,
    },
    Read {
        path: String,
        cache: bool,
    },
    ReadBatch {
        archive: String,
        members: Vec<String>,
        cache: bool,
    },
    PrefetchPaths {
        paths: Vec<String>,
    },
    Clear,
}

#[repr(C)]
pub struct AssetBuffer {
    data: *mut u8,
    len: usize,
}

fn dispatch(request: Request) -> Result<(Value, Vec<u8>), CacheError> {
    let path_error =
        |error: crate::virtual_path::VirtualPathError| CacheError::Path(error.to_string());
    if let Request::Revision { path } = &request {
        let path = ModelPath::parse(path).map_err(path_error)?;
        let revision = ArchiveRevision::read(Path::new(&path.archive))?;
        return Ok((
            json!(format!("{}:{}", revision.size, revision.mtime_ns)),
            vec![],
        ));
    }
    let mut cache = CACHE
        .get_or_init(|| Mutex::new(ArchiveCache::default()))
        .lock()
        .map_err(|e| CacheError::Io(e.to_string()))?;
    let batch = match request {
        Request::List { archive } => {
            return Ok((json!(cache.list_files(Path::new(&archive))?), vec![]))
        }
        Request::Scan { archive } => {
            return Ok((
                json!(cache.scan_model_archive(Path::new(&archive))?),
                vec![],
            ))
        }
        Request::Clear => {
            cache.clear();
            return Ok((Value::Null, vec![]));
        }
        Request::Read {
            path,
            cache: retain,
        } => {
            let path = ModelPath::parse(&path).map_err(path_error)?;
            cache.read_batch(Path::new(&path.archive), &[path.member], retain)?
        }
        Request::ReadBatch {
            archive,
            members,
            cache: retain,
        } => cache.read_batch(Path::new(&archive), &members, retain)?,
        Request::PrefetchPaths { paths } => {
            let mut archives: BTreeMap<String, Vec<String>> = BTreeMap::new();
            for spec in paths {
                let path = ModelPath::parse(&spec).map_err(path_error)?;
                archives.entry(path.archive).or_default().push(path.member);
            }
            for (archive, members) in archives {
                cache.prefetch(Path::new(&archive), &members)?;
            }
            return Ok((Value::Null, vec![]));
        }
        Request::Revision { .. } => unreachable!(),
    };
    let mut body = Vec::new();
    let mut members = Vec::new();
    for (member, data) in batch {
        members.push(json!({ "member": member, "size": data.len() }));
        body.extend_from_slice(&data);
    }
    Ok((json!(members), body))
}

#[no_mangle]
pub extern "C" fn pet_assets_abi_version() -> u32 {
    1
}

/// # Safety
/// `data` must point to `len` readable bytes for the duration of this call.
#[no_mangle]
pub unsafe extern "C" fn pet_assets_request(data: *const u8, len: usize) -> AssetBuffer {
    let result = if data.is_null() || len > 8 * 1024 * 1024 {
        Err(CacheError::Path("invalid bridge request".into()))
    } else {
        serde_json::from_slice(std::slice::from_raw_parts(data, len))
            .map_err(|e| CacheError::Path(e.to_string()))
            .and_then(dispatch)
    };
    let (meta, body) = match result {
        Ok((value, body)) => (json!({ "ok": true, "value": value }), body),
        Err(error) => {
            let kind = match &error {
                CacheError::Path(_) | CacheError::TooLarge(_) => "value",
                CacheError::MissingMember { .. } => "missing",
                CacheError::Io(_) => "io",
                _ => "archive",
            };
            (
                json!({ "ok": false, "kind": kind, "error": error.to_string() }),
                vec![],
            )
        }
    };
    let metadata = serde_json::to_vec(&meta).unwrap();
    let mut output = Vec::with_capacity(4 + metadata.len() + body.len());
    output.extend_from_slice(&(metadata.len() as u32).to_le_bytes());
    output.extend_from_slice(&metadata);
    output.extend_from_slice(&body);
    let mut output = output.into_boxed_slice();
    let buffer = AssetBuffer {
        data: output.as_mut_ptr(),
        len: output.len(),
    };
    std::mem::forget(output);
    buffer
}

/// # Safety
/// `buffer` must be returned by `pet_assets_request` and freed exactly once.
#[no_mangle]
pub unsafe extern "C" fn pet_assets_free(buffer: AssetBuffer) {
    if !buffer.data.is_null() {
        drop(Box::from_raw(std::ptr::slice_from_raw_parts_mut(
            buffer.data,
            buffer.len,
        )));
    }
}
