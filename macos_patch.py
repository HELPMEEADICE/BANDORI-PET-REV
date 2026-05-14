import ctypes
import sys

_AVAILABLE = False
_PRELOADED_SELECTORS = {}
_OBJC = None


def _init_objc():
    global _AVAILABLE, _OBJC
    if _AVAILABLE or _OBJC is not None:
        return _AVAILABLE
    if sys.platform != "darwin":
        return False
    try:
        lib = ctypes.cdll.LoadLibrary("/usr/lib/libobjc.dylib")
        lib.objc_getClass.restype = ctypes.c_void_p
        lib.objc_getClass.argtypes = [ctypes.c_char_p]
        lib.sel_registerName.restype = ctypes.c_void_p
        lib.sel_registerName.argtypes = [ctypes.c_char_p]
        _OBJC = lib
        _AVAILABLE = True
    except Exception:
        _AVAILABLE = False
    return _AVAILABLE


def _sel(name: str):
    if name in _PRELOADED_SELECTORS:
        return _PRELOADED_SELECTORS[name]
    sel = _OBJC.sel_registerName(name.encode("utf-8"))
    _PRELOADED_SELECTORS[name] = sel
    return sel


def _send_id(receiver: int, selector: str) -> int:
    f = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)
    sender = ctypes.cast(_OBJC.objc_msgSend, f)
    return sender(receiver, _sel(selector))


def _get_ns_window(view_ptr: int) -> int:
    if not view_ptr:
        return 0
    return _send_id(view_ptr, "window")


def set_ignores_mouse_events(widget, enabled: bool):
    if not _init_objc() or widget is None:
        return
    try:
        win_id = int(widget.winId())
    except (TypeError, ValueError):
        return
    if not win_id:
        return
    window = _get_ns_window(win_id)
    if not window:
        return
    f = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_bool)
    sender = ctypes.cast(_OBJC.objc_msgSend, f)
    sender(window, _sel("setIgnoresMouseEvents:"), ctypes.c_bool(enabled))


def set_window_level_floating(widget) -> bool:
    return _set_window_level(widget, 3)


def set_window_level_above_menu_bar(widget) -> bool:
    return _set_window_level(widget, 101)


def _set_window_level(widget, level: int) -> bool:
    if not _init_objc() or widget is None:
        return False
    try:
        win_id = int(widget.winId())
    except (TypeError, ValueError):
        return False
    if not win_id:
        return False
    window = _get_ns_window(win_id)
    if not window:
        return False
    f = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_long)
    sender = ctypes.cast(_OBJC.objc_msgSend, f)
    sender(window, _sel("setLevel:"), level)
    return True


def set_window_no_shadow(widget) -> bool:
    if not _init_objc() or widget is None:
        return False
    try:
        win_id = int(widget.winId())
    except (TypeError, ValueError):
        return False
    if not win_id:
        return False
    window = _get_ns_window(win_id)
    if not window:
        return False
    f = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_bool)
    sender = ctypes.cast(_OBJC.objc_msgSend, f)
    sender(window, _sel("setHasShadow:"), ctypes.c_bool(False))
    return True


def hide_dock_icon():
    if sys.platform != "darwin":
        return
    try:
        from AppKit import NSApp, NSApplicationActivationPolicyAccessory
        NSApp.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
        return
    except Exception:
        pass
    if not _init_objc():
        return
    try:
        app_class = _OBJC.objc_getClass(b"NSApplication")
        if not app_class:
            return
        app = _send_id(app_class, "sharedApplication")
        if not app:
            return
        f = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_long)
        sender = ctypes.cast(_OBJC.objc_msgSend, f)
        sender(app, _sel("setActivationPolicy:"), 1)
    except Exception:
        pass


def is_available() -> bool:
    return _init_objc()
