use crate::{
    FrameInput, Live2dFormat, Live2dRuntime, ModelResourceLoader, ParameterValue, ResourceRoots,
    TextureQuality,
};
use std::cell::RefCell;
use std::collections::BTreeMap;
use std::ffi::{CStr, CString, c_char, c_void};
use std::panic::{AssertUnwindSafe, catch_unwind};
use std::path::{Path, PathBuf};
use std::ptr;
use std::sync::Arc;

pub type BandoriGlProcResolver =
    Option<unsafe extern "C" fn(name: *const c_char, user_data: *mut c_void) -> usize>;

pub struct BandoriLive2dHost {
    runtime: Live2dRuntime,
    frame_number: u64,
    parameters: BTreeMap<String, ParameterValue>,
}

thread_local! {
    static LAST_ERROR: RefCell<CString> = RefCell::new(CString::default());
}

#[unsafe(no_mangle)]
pub extern "C" fn bandori_live2d_last_error() -> *const c_char {
    LAST_ERROR.with(|error| error.borrow().as_ptr())
}

#[unsafe(no_mangle)]
/// Creates an isolated Live2D host while the caller's GL context is current.
///
/// # Safety
/// String arguments must be valid NUL-terminated UTF-8. The resolver and its
/// opaque value must remain callable until the returned host is destroyed.
pub unsafe extern "C" fn bandori_live2d_create(
    project_root: *const c_char,
    user_models_root: *const c_char,
    format: u32,
    width: u32,
    height: u32,
    resolver: BandoriGlProcResolver,
    resolver_user_data: *mut c_void,
) -> *mut BandoriLive2dHost {
    let result = catch_unwind(AssertUnwindSafe(|| {
        // SAFETY: validated below before converting either pointer to `CStr`.
        let project_root = unsafe { required_path(project_root, "project_root") }?;
        // SAFETY: validated below before converting either pointer to `CStr`.
        let user_models_root = unsafe { required_path(user_models_root, "user_models_root") }?;
        let format = match format {
            2 => Live2dFormat::Moc,
            3 => Live2dFormat::Moc3,
            value => return Err(format!("unsupported Live2D format: {value}")),
        };
        let resolver = resolver.ok_or_else(|| "GL procedure resolver is required".to_owned())?;
        let user_data = resolver_user_data as usize;
        let gl_resolver = Arc::new(move |name: &str| {
            let name = CString::new(name).ok()?;
            // SAFETY: the callback and opaque value are supplied by the C++
            // owner and are invoked only while its QOpenGLContext is current.
            let address = unsafe { resolver(name.as_ptr(), user_data as *mut c_void) };
            (address != 0).then_some(address)
        });
        let runtime = Live2dRuntime::new(
            format,
            project_root.join("third_party/Live2D-v2-Lua"),
            ModelResourceLoader::new(ResourceRoots {
                bundled_models: project_root.join("models"),
                user_models: user_models_root,
            }),
            gl_resolver,
            width,
            height,
        )
        .map_err(|error| error.to_string())?;
        Ok(Box::into_raw(Box::new(BandoriLive2dHost {
            runtime,
            frame_number: 0,
            parameters: BTreeMap::new(),
        })))
    }));
    match result {
        Ok(Ok(host)) => {
            clear_error();
            host
        }
        Ok(Err(error)) => {
            set_error(error);
            ptr::null_mut()
        }
        Err(_) => {
            set_error("panic while creating Live2D runtime");
            ptr::null_mut()
        }
    }
}

#[unsafe(no_mangle)]
/// Loads a model into an existing host.
///
/// # Safety
/// `host` must be live and uniquely owned by the caller; `model_path` must be
/// valid NUL-terminated UTF-8. The owning GL context must be current.
pub unsafe extern "C" fn bandori_live2d_load_model(
    host: *mut BandoriLive2dHost,
    model_path: *const c_char,
    width: u32,
    height: u32,
    quality: u32,
) -> bool {
    ffi_bool(|| {
        // SAFETY: `ffi_bool` validates the host; the string pointer is checked.
        let host = unsafe { required_host(host) }?;
        // SAFETY: pointer validity is checked before `CStr` conversion.
        let model_path = unsafe { required_string(model_path, "model_path") }?;
        let quality = match quality {
            0 => TextureQuality::Performance,
            1 => TextureQuality::Balanced,
            value => return Err(format!("unsupported texture quality: {value}")),
        };
        host.runtime
            .load_model_with_quality(&model_path, width, height, quality)
            .map_err(|error| error.to_string())?;
        Ok(())
    })
}

#[unsafe(no_mangle)]
/// Updates the renderer's logical size.
///
/// # Safety
/// `host` must be a live handle and its owning GL context must be current.
pub unsafe extern "C" fn bandori_live2d_resize(
    host: *mut BandoriLive2dHost,
    width: u32,
    height: u32,
) -> bool {
    ffi_bool(|| {
        // SAFETY: pointer ownership remains with the C++ caller.
        unsafe { required_host(host) }?
            .runtime
            .resize(width, height)
            .map_err(|error| error.to_string())
    })
}

#[unsafe(no_mangle)]
/// Updates the physical render target without changing logical gaze space.
///
/// # Safety
/// `host` must be a live handle and its owning GL context must be current.
pub unsafe extern "C" fn bandori_live2d_resize_renderer(
    host: *mut BandoriLive2dHost,
    width: u32,
    height: u32,
) -> bool {
    ffi_bool(|| {
        // SAFETY: pointer ownership remains with the C++ caller.
        unsafe { required_host(host) }?
            .runtime
            .resize_renderer(width, height)
            .map_err(|error| error.to_string())
    })
}

#[unsafe(no_mangle)]
/// Advances and renders one frame.
///
/// # Safety
/// `host` must be a live handle and its owning GL context must be current.
pub unsafe extern "C" fn bandori_live2d_draw(
    host: *mut BandoriLive2dHost,
    time_msec: f64,
    delta_seconds: f64,
) -> bool {
    ffi_bool(|| {
        // SAFETY: pointer ownership remains with the C++ caller.
        let host = unsafe { required_host(host) }?;
        host.frame_number = host.frame_number.wrapping_add(1);
        host.runtime
            .draw(&FrameInput {
                time_msec,
                delta_seconds: Some(delta_seconds.clamp(0.0, 0.1)),
                frame_number: host.frame_number,
                parameters: host.parameters.values().cloned().collect(),
                ..FrameInput::default()
            })
            .map_err(|error| error.to_string())
    })
}

#[unsafe(no_mangle)]
/// Sets a persistent host parameter that is applied on every frame.
///
/// # Safety
/// `host` must be live and uniquely owned. `parameter_id` must be valid
/// NUL-terminated UTF-8. The owning GL context must be current.
pub unsafe extern "C" fn bandori_live2d_set_parameter(
    host: *mut BandoriLive2dHost,
    parameter_id: *const c_char,
    value: f64,
    weight: f64,
) -> bool {
    ffi_bool(|| {
        // SAFETY: pointer ownership remains with the C++ caller.
        let host = unsafe { required_host(host) }?;
        // SAFETY: string validity is part of the C ABI contract.
        let id = unsafe { required_string(parameter_id, "parameter_id") }?;
        host.parameters
            .insert(id.clone(), ParameterValue { id, value, weight });
        Ok(())
    })
}

#[unsafe(no_mangle)]
/// Resolves and triggers a host action tag against model metadata.
///
/// # Safety
/// `host` must be live and uniquely owned. Both string pointers must contain
/// valid NUL-terminated UTF-8. The owning GL context must be current.
pub unsafe extern "C" fn bandori_live2d_trigger_action(
    host: *mut BandoriLive2dHost,
    action: *const c_char,
    character: *const c_char,
) -> bool {
    ffi_bool(|| {
        // SAFETY: pointer ownership remains with the C++ caller.
        let host = unsafe { required_host(host) }?;
        // SAFETY: string validity is part of the C ABI contract.
        let action = unsafe { required_string(action, "action") }?;
        // SAFETY: string validity is part of the C ABI contract.
        let character = unsafe { required_string(character, "character") }?;
        if host
            .runtime
            .trigger_action(&action, &character)
            .map_err(|error| error.to_string())?
        {
            Ok(())
        } else {
            Err(format!(
                "Live2D action did not match model metadata: {action}"
            ))
        }
    })
}

#[unsafe(no_mangle)]
/// Renders the current Cubism 3 state without advancing its simulation.
///
/// # Safety
/// `host` must be a live Cubism 3 handle and its owning GL context must be
/// current.
pub unsafe extern "C" fn bandori_live2d_render_only(host: *mut BandoriLive2dHost) -> bool {
    ffi_bool(|| {
        // SAFETY: pointer ownership remains with the C++ caller.
        unsafe { required_host(host) }?
            .runtime
            .render_only(&FrameInput::default())
            .map_err(|error| error.to_string())
    })
}

#[unsafe(no_mangle)]
/// Updates the gaze target in logical widget coordinates.
///
/// # Safety
/// `host` must be a live handle and its owning GL context must be current.
pub unsafe extern "C" fn bandori_live2d_drag(host: *mut BandoriLive2dHost, x: f64, y: f64) -> bool {
    ffi_bool(|| {
        // SAFETY: pointer ownership remains with the C++ caller.
        unsafe { required_host(host) }?
            .runtime
            .drag(x, y)
            .map_err(|error| error.to_string())
    })
}

#[unsafe(no_mangle)]
/// Applies the model projection scale.
///
/// # Safety
/// `host` must be a live handle and its owning GL context must be current.
pub unsafe extern "C" fn bandori_live2d_set_scale(
    host: *mut BandoriLive2dHost,
    scale: f64,
) -> bool {
    ffi_bool(|| {
        // SAFETY: pointer ownership remains with the C++ caller.
        unsafe { required_host(host) }?
            .runtime
            .set_scale(scale)
            .map_err(|error| error.to_string())
    })
}

#[unsafe(no_mangle)]
/// Disposes a host and releases all LuaJIT/GL resources.
///
/// # Safety
/// `host` must either be null or the sole live pointer returned by `create`.
/// Its owning GL context must be current and the pointer must not be reused.
pub unsafe extern "C" fn bandori_live2d_destroy(host: *mut BandoriLive2dHost) {
    if host.is_null() {
        return;
    }
    let result = catch_unwind(AssertUnwindSafe(|| {
        // SAFETY: this is the sole consuming call for a handle returned by
        // `bandori_live2d_create`; C++ clears its pointer immediately after.
        let mut host = unsafe { Box::from_raw(host) };
        host.runtime.dispose().map_err(|error| error.to_string())
    }));
    match result {
        Ok(Ok(())) => clear_error(),
        Ok(Err(error)) => set_error(error),
        Err(_) => set_error("panic while disposing Live2D runtime"),
    }
}

fn ffi_bool(operation: impl FnOnce() -> Result<(), String>) -> bool {
    match catch_unwind(AssertUnwindSafe(operation)) {
        Ok(Ok(())) => {
            clear_error();
            true
        }
        Ok(Err(error)) => {
            set_error(error);
            false
        }
        Err(_) => {
            set_error("panic inside Live2D FFI call");
            false
        }
    }
}

unsafe fn required_host<'a>(
    host: *mut BandoriLive2dHost,
) -> Result<&'a mut BandoriLive2dHost, String> {
    // SAFETY: caller guarantees that any non-null handle originated from
    // `bandori_live2d_create` and has not been destroyed.
    unsafe { host.as_mut() }.ok_or_else(|| "Live2D host pointer is null".to_owned())
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

unsafe fn required_path(value: *const c_char, label: &str) -> Result<PathBuf, String> {
    // SAFETY: delegated to the checked string converter.
    unsafe { required_string(value, label) }.map(|value| Path::new(&value).to_path_buf())
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

    extern "C" fn no_gl_proc(_name: *const c_char, _user_data: *mut c_void) -> usize {
        0
    }

    #[test]
    fn null_handles_fail_without_unwinding_across_ffi() {
        // SAFETY: null is an explicitly supported error input for this test.
        assert!(!unsafe { bandori_live2d_resize(ptr::null_mut(), 1, 1) });
        // SAFETY: the thread-local pointer remains valid until the next FFI call.
        let error = unsafe { CStr::from_ptr(bandori_live2d_last_error()) };
        assert!(error.to_string_lossy().contains("pointer is null"));
        // SAFETY: destroy explicitly accepts null.
        unsafe { bandori_live2d_destroy(ptr::null_mut()) };
    }

    #[test]
    fn invalid_formats_are_rejected_before_lua_initialization() {
        let temp = tempdir().unwrap();
        let project = temp.path().join("project");
        let user_models = temp.path().join("user-models");
        fs::create_dir_all(&project).unwrap();
        fs::create_dir_all(&user_models).unwrap();
        let project = CString::new(project.to_string_lossy().as_bytes()).unwrap();
        let user_models = CString::new(user_models.to_string_lossy().as_bytes()).unwrap();

        // SAFETY: both strings and the callback remain valid for the call.
        let host = unsafe {
            bandori_live2d_create(
                project.as_ptr(),
                user_models.as_ptr(),
                99,
                1,
                1,
                Some(no_gl_proc),
                ptr::null_mut(),
            )
        };
        assert!(host.is_null());
        // SAFETY: the thread-local pointer remains valid until the next FFI call.
        let error = unsafe { CStr::from_ptr(bandori_live2d_last_error()) };
        assert!(
            error
                .to_string_lossy()
                .contains("unsupported Live2D format")
        );
    }
}
