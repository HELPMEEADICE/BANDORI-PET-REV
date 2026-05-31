import ctypes
import os

if os.name == "nt":
    import ctypes.wintypes


DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWA_BORDER_COLOR = 34
DWMWCP_DONOTROUND = 1
DWMWA_COLOR_NONE = 0xFFFFFFFE

SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_FRAMECHANGED = 0x0020

if os.name == "nt":
    _dwmapi = ctypes.windll.dwmapi
    _dwm_set_window_attribute = _dwmapi.DwmSetWindowAttribute
    _dwm_set_window_attribute.argtypes = [
        ctypes.wintypes.HWND,
        ctypes.wintypes.DWORD,
        ctypes.c_void_p,
        ctypes.wintypes.DWORD,
    ]
    _dwm_set_window_attribute.restype = ctypes.c_long

    _user32 = ctypes.windll.user32
    _set_window_pos = _user32.SetWindowPos
    _set_window_pos.argtypes = [
        ctypes.wintypes.HWND,
        ctypes.wintypes.HWND,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_uint,
    ]
    _set_window_pos.restype = ctypes.wintypes.BOOL

    _rtl_get_version = ctypes.windll.ntdll.RtlGetVersion

    class _OSVERSIONINFOEXW(ctypes.Structure):
        _fields_ = [
            ("dwOSVersionInfoSize", ctypes.wintypes.DWORD),
            ("dwMajorVersion", ctypes.wintypes.DWORD),
            ("dwMinorVersion", ctypes.wintypes.DWORD),
            ("dwBuildNumber", ctypes.wintypes.DWORD),
            ("dwPlatformId", ctypes.wintypes.DWORD),
            ("szCSDVersion", ctypes.wintypes.WCHAR * 128),
            ("wServicePackMajor", ctypes.wintypes.WORD),
            ("wServicePackMinor", ctypes.wintypes.WORD),
            ("wSuiteMask", ctypes.wintypes.WORD),
            ("wProductType", ctypes.wintypes.BYTE),
            ("wReserved", ctypes.wintypes.BYTE),
        ]

    _rtl_get_version.argtypes = [ctypes.POINTER(_OSVERSIONINFOEXW)]
    _rtl_get_version.restype = ctypes.wintypes.LONG
else:
    _dwm_set_window_attribute = None
    _set_window_pos = None
    _rtl_get_version = None


def is_windows_11_or_later() -> bool:
    if os.name != "nt":
        return False
    version = _OSVERSIONINFOEXW()
    version.dwOSVersionInfoSize = ctypes.sizeof(version)
    if _rtl_get_version(ctypes.byref(version)) != 0:
        return False
    return version.dwMajorVersion >= 10 and version.dwBuildNumber >= 22000


def set_window_attribute(hwnd: int, attr: int, value: int) -> None:
    if os.name != "nt" or _dwm_set_window_attribute is None or not hwnd:
        return
    value_ref = ctypes.c_int(value)
    try:
        _dwm_set_window_attribute(hwnd, attr, ctypes.byref(value_ref), ctypes.sizeof(value_ref))
    except Exception:
        pass


def apply_no_rounding(hwnd: int, *, windows_11_only: bool = False) -> None:
    if windows_11_only and not is_windows_11_or_later():
        return
    set_window_attribute(hwnd, DWMWA_WINDOW_CORNER_PREFERENCE, DWMWCP_DONOTROUND)


def apply_no_border(hwnd: int) -> None:
    set_window_attribute(hwnd, DWMWA_BORDER_COLOR, DWMWA_COLOR_NONE)


def apply_windows_11_border_fix(hwnd: int) -> None:
    apply_no_rounding(hwnd)
    apply_no_border(hwnd)


def frame_changed(hwnd: int) -> None:
    if os.name != "nt" or _set_window_pos is None or not hwnd:
        return
    _set_window_pos(
        hwnd,
        None,
        0,
        0,
        0,
        0,
        SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED,
    )
