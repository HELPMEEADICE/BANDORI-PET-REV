use crate::config::{ConfigDocument, PetWindowState};
use crate::legacy_migration::migrate_legacy_data;
use std::cell::RefCell;
use std::ffi::{CStr, CString, c_char};
use std::panic::{AssertUnwindSafe, catch_unwind};
use std::path::Path;

thread_local! {
    static LAST_ERROR: RefCell<CString> = RefCell::new(CString::default());
}

#[unsafe(no_mangle)]
pub extern "C" fn bandori_config_last_error() -> *const c_char {
    LAST_ERROR.with(|error| error.borrow().as_ptr())
}

#[unsafe(no_mangle)]
/// Merges one pet's final window state into the compatible configuration file.
///
/// # Safety
/// Both arguments must point to valid NUL-terminated UTF-8 strings for the
/// duration of the call.
pub unsafe extern "C" fn bandori_config_save_pet_state(
    config_path: *const c_char,
    payload_json: *const c_char,
) -> bool {
    let result = catch_unwind(AssertUnwindSafe(|| {
        // SAFETY: pointers are checked before conversion and owned by caller.
        let config_path = unsafe { required_string(config_path, "config_path") }?;
        // SAFETY: pointers are checked before conversion and owned by caller.
        let payload = unsafe { required_string(payload_json, "payload_json") }?;
        let state: PetWindowState =
            serde_json::from_str(&payload).map_err(|error| error.to_string())?;
        let path = Path::new(&config_path);
        let mut config = ConfigDocument::load(path).map_err(|error| error.to_string())?;
        if !config.apply_pet_window_state(&state) {
            return Err("pet state did not match a configurable model".to_owned());
        }
        config.save(path).map_err(|error| error.to_string())
    }));
    match result {
        Ok(Ok(())) => {
            clear_error();
            true
        }
        Ok(Err(error)) => {
            set_error(error);
            false
        }
        Err(_) => {
            set_error("panic while saving pet window state");
            false
        }
    }
}

#[unsafe(no_mangle)]
/// Copies a legacy Python data root into the native writable data root.
///
/// # Safety
/// Both arguments must point to valid NUL-terminated UTF-8 strings for the
/// duration of the call.
pub unsafe extern "C" fn bandori_config_migrate_legacy_data(
    legacy_root: *const c_char,
    native_root: *const c_char,
) -> bool {
    let result = catch_unwind(AssertUnwindSafe(|| {
        // SAFETY: pointers are checked before conversion and owned by caller.
        let legacy_root = unsafe { required_string(legacy_root, "legacy_root") }?;
        // SAFETY: pointers are checked before conversion and owned by caller.
        let native_root = unsafe { required_string(native_root, "native_root") }?;
        migrate_legacy_data(Path::new(&legacy_root), Path::new(&native_root))
            .map(|_| ())
            .map_err(|error| error.to_string())
    }));
    match result {
        Ok(Ok(())) => {
            clear_error();
            true
        }
        Ok(Err(error)) => {
            set_error(error);
            false
        }
        Err(_) => {
            set_error("panic while migrating legacy data");
            false
        }
    }
}

unsafe fn required_string(value: *const c_char, label: &str) -> Result<String, String> {
    if value.is_null() {
        return Err(format!("{label} pointer is null"));
    }
    // SAFETY: the C ABI requires a valid NUL-terminated string.
    unsafe { CStr::from_ptr(value) }
        .to_str()
        .map(str::to_owned)
        .map_err(|error| format!("{label} is not UTF-8: {error}"))
}

fn set_error(error: impl AsRef<str>) {
    let sanitized = error.as_ref().replace('\0', " ");
    LAST_ERROR.with(|slot| {
        *slot.borrow_mut() = CString::new(sanitized).unwrap_or_default();
    });
}

fn clear_error() {
    LAST_ERROR.with(|slot| *slot.borrow_mut() = CString::default());
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;
    use tempfile::tempdir;

    #[test]
    fn c_abi_persists_pet_state_without_losing_unrelated_configuration() {
        let temp = tempdir().unwrap();
        let path = temp.path().join("config.json");
        fs::write(
            &path,
            br#"{"fps":60,"models":[{"character":"ran","path":"ran/model.json"}]}"#,
        )
        .unwrap();
        let path = CString::new(path.to_string_lossy().as_bytes()).unwrap();
        let payload = CString::new(
            r#"{"character":"ran","model_path":"ran/model.json","x":10,"y":20,"width":400,"height":500,"drag_locked":true}"#,
        )
        .unwrap();
        // SAFETY: both C strings remain live for the entire call.
        assert!(unsafe { bandori_config_save_pet_state(path.as_ptr(), payload.as_ptr()) });
        let saved = ConfigDocument::load(Path::new(path.to_str().unwrap())).unwrap();
        assert_eq!(saved.get("fps"), Some(&serde_json::json!(60)));
        assert_eq!(saved.get("window_x"), Some(&serde_json::json!(10)));
        assert_eq!(saved.get("drag_locked"), Some(&serde_json::json!(true)));
        assert_eq!(saved.get("models").unwrap()[0]["window_y"], 20);
    }

    #[test]
    fn c_abi_migrates_legacy_data_and_reports_invalid_roots() {
        let temp = tempdir().unwrap();
        let legacy = temp.path().join("legacy");
        let native = temp.path().join("native");
        fs::create_dir(&legacy).unwrap();
        fs::write(legacy.join("config.json"), b"{}").unwrap();
        let legacy = CString::new(legacy.to_string_lossy().as_bytes()).unwrap();
        let native = CString::new(native.to_string_lossy().as_bytes()).unwrap();
        // SAFETY: both C strings remain live for the entire call.
        assert!(unsafe { bandori_config_migrate_legacy_data(legacy.as_ptr(), native.as_ptr()) });
        assert!(
            Path::new(native.to_str().unwrap())
                .join("config.json")
                .is_file()
        );

        let missing =
            CString::new(temp.path().join("missing").to_string_lossy().as_bytes()).unwrap();
        // SAFETY: both C strings remain live for the entire call.
        assert!(!unsafe { bandori_config_migrate_legacy_data(missing.as_ptr(), native.as_ptr()) });
        // SAFETY: the error pointer remains owned by the thread-local slot.
        let error = unsafe { CStr::from_ptr(bandori_config_last_error()) }
            .to_str()
            .unwrap();
        assert!(!error.is_empty());
    }
}
