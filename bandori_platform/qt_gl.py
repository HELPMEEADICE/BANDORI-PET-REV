import ctypes
import os

import OpenGL.GL as _gl
from OpenGL.error import GLError


_INVALID_PTRS = {0, 1, 2, 3, ctypes.c_void_p(-1).value}
_PROC_ALIASES = {
    "glBindFramebuffer": ("glBindFramebuffer", "glBindFramebufferEXT"),
    "glBlitFramebuffer": ("glBlitFramebuffer", "glBlitFramebufferEXT"),
}
_FUNC_CACHE = {}


def uses_qt_software_opengl() -> bool:
    return os.environ.get("QT_OPENGL", "").strip().lower() == "software"


def _current_qt_context():
    try:
        from PySide6.QtGui import QOpenGLContext
    except Exception:
        return None
    return QOpenGLContext.currentContext()


def _require_qt_context(call_name: str):
    ctx = _current_qt_context()
    if ctx is None:
        raise RuntimeError(f"OpenGL call requires a current Qt OpenGL context: {call_name}")
    return ctx


def qt_gl_proc_address(name: str | bytes) -> int:
    if isinstance(name, bytes):
        raw_name = name
        cache_name = name.decode("ascii", errors="ignore")
    else:
        cache_name = str(name)
        raw_name = cache_name.encode("ascii", errors="ignore")
    if not raw_name:
        return 0

    ctx = _current_qt_context()
    if ctx is None:
        return 0

    for proc_name in _PROC_ALIASES.get(cache_name, (cache_name,)):
        try:
            ptr = ctx.getProcAddress(proc_name.encode("ascii", errors="ignore"))
        except Exception:
            ptr = 0
        if ptr and int(ptr) not in _INVALID_PTRS:
            return int(ptr)
    return 0


def _qt_func(name: str, restype, argtypes):
    ctx = _require_qt_context(name)
    key = (id(ctx), name, restype, tuple(argtypes))
    cached = _FUNC_CACHE.get(key)
    if cached is not None:
        cached_ctx, fn = cached
        if cached_ctx is ctx:
            return fn
        _FUNC_CACHE.pop(key, None)

    ptr = qt_gl_proc_address(name)
    if not ptr:
        raise RuntimeError(f"OpenGL function is unavailable in the current Qt context: {name}")

    fn = ctypes.CFUNCTYPE(restype, *argtypes)(ptr)
    _FUNC_CACHE[key] = (ctx, fn)
    return fn


def _should_fallback(exc: Exception) -> bool:
    if uses_qt_software_opengl():
        return True
    return isinstance(exc, GLError) and getattr(exc, "err", None) == 1282


def _call(name: str, restype, argtypes, *args):
    _require_qt_context(name)
    if not uses_qt_software_opengl():
        try:
            return getattr(_gl, name)(*args)
        except Exception as exc:
            if not _should_fallback(exc):
                raise
    return _qt_func(name, restype, argtypes)(*args)


def _buffer_data_ptr(data):
    if data is None:
        return None, None
    if isinstance(data, ctypes.c_void_p):
        return data, None
    if isinstance(data, int):
        return ctypes.c_void_p(data), None

    try:
        return ctypes.cast(data, ctypes.c_void_p), data
    except (ctypes.ArgumentError, TypeError):
        pass

    view = memoryview(data)
    if view.readonly:
        owner = ctypes.create_string_buffer(view.tobytes())
    else:
        owner = ctypes.c_char.from_buffer(view)
    return ctypes.c_void_p(ctypes.addressof(owner)), owner


class _QtGLProxy:
    def __getattr__(self, name):
        return getattr(_gl, name)

    def glGetString(self, name):
        _require_qt_context("glGetString")
        if not uses_qt_software_opengl():
            try:
                return _gl.glGetString(name)
            except Exception as exc:
                if not _should_fallback(exc):
                    raise
        return _qt_func("glGetString", ctypes.c_char_p, [ctypes.c_uint])(name)

    def glDisable(self, cap):
        return _call("glDisable", None, [ctypes.c_uint], cap)

    def glEnable(self, cap):
        return _call("glEnable", None, [ctypes.c_uint], cap)

    def glBlendEquationSeparate(self, mode_rgb, mode_alpha):
        return _call("glBlendEquationSeparate", None, [ctypes.c_uint, ctypes.c_uint], mode_rgb, mode_alpha)

    def glClearColor(self, red, green, blue, alpha):
        return _call(
            "glClearColor",
            None,
            [ctypes.c_float, ctypes.c_float, ctypes.c_float, ctypes.c_float],
            float(red),
            float(green),
            float(blue),
            float(alpha),
        )

    def glClear(self, mask):
        return _call("glClear", None, [ctypes.c_uint], mask)

    def glViewport(self, x, y, width, height):
        return _call(
            "glViewport",
            None,
            [ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int],
            int(x),
            int(y),
            int(width),
            int(height),
        )

    def glBindFramebuffer(self, target, framebuffer):
        return _call("glBindFramebuffer", None, [ctypes.c_uint, ctypes.c_uint], target, int(framebuffer))

    def glBlitFramebuffer(
        self,
        src_x0,
        src_y0,
        src_x1,
        src_y1,
        dst_x0,
        dst_y0,
        dst_x1,
        dst_y1,
        mask,
        filter_,
    ):
        return _call(
            "glBlitFramebuffer",
            None,
            [
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_uint,
                ctypes.c_uint,
            ],
            int(src_x0),
            int(src_y0),
            int(src_x1),
            int(src_y1),
            int(dst_x0),
            int(dst_y0),
            int(dst_x1),
            int(dst_y1),
            mask,
            filter_,
        )

    def glBindBuffer(self, target, buffer):
        return _call("glBindBuffer", None, [ctypes.c_uint, ctypes.c_uint], target, int(buffer))

    def glBufferData(self, target, size, data, usage):
        ptr, _owner = _buffer_data_ptr(data)
        return _call(
            "glBufferData",
            None,
            [ctypes.c_uint, ctypes.c_ssize_t, ctypes.c_void_p, ctypes.c_uint],
            target,
            int(size),
            ptr,
            usage,
        )

    def glReadPixels(self, x, y, width, height, format_, type_, pixels=None):
        _require_qt_context("glReadPixels")
        if not uses_qt_software_opengl():
            if pixels is None:
                return _gl.glReadPixels(x, y, width, height, format_, type_)
            return _gl.glReadPixels(x, y, width, height, format_, type_, pixels)

        byte_count = max(0, int(width) * int(height) * 4)
        owns_buffer = pixels is None
        if owns_buffer:
            pixels = (ctypes.c_ubyte * byte_count)()
        ptr = ctypes.cast(pixels, ctypes.c_void_p)
        _qt_func(
            "glReadPixels",
            None,
            [ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p],
        )(int(x), int(y), int(width), int(height), format_, type_, ptr)
        if owns_buffer:
            return bytes(pixels)
        return None


gl = _QtGLProxy()
