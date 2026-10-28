import os
import sys


FALSE_VALUES = {"0", "false", "no", "off", "disable", "disabled"}
TRUE_VALUES = {"1", "true", "yes", "on", "enable", "enabled"}


def is_gpu_acceleration_enabled(cfg=None) -> bool:
    value = os.environ.get("BANDORI_GPU_ACCELERATION", "").strip().lower()
    if value in FALSE_VALUES:
        return False
    if value in TRUE_VALUES:
        return True
    if cfg is not None:
        try:
            return bool(cfg.get("gpu_acceleration", True))
        except Exception:
            pass
    return True


def configure_qt_opengl_environment(enabled: bool = True) -> None:
    """Choose Qt's OpenGL backend before QApplication is created."""
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
    os.environ.setdefault("QT_SCALE_FACTOR_ROUNDING_POLICY", "PassThrough")
    if enabled:
        if sys.platform != "darwin":
            os.environ.setdefault("QT_OPENGL", "desktop")
        os.environ.setdefault("QT_QUICK_BACKEND", "opengl")
    else:
        os.environ["QT_OPENGL"] = "software"


def apply_qt_opengl_policy(qapplication, qt, enabled: bool = True) -> None:
    try:
        qapplication.setHighDpiScaleFactorRoundingPolicy(
            qt.HighDpiScaleFactorRoundingPolicy.PassThrough
        )
    except Exception:
        pass
    qapplication.setAttribute(qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    if sys.platform == "darwin":
        return

    if enabled:
        qapplication.setAttribute(qt.ApplicationAttribute.AA_UseDesktopOpenGL)
    else:
        qapplication.setAttribute(qt.ApplicationAttribute.AA_UseSoftwareOpenGL)


def configure_qt_gpu_acceleration(qapplication, qt, cfg=None) -> bool:
    enabled = is_gpu_acceleration_enabled(cfg)
    configure_qt_opengl_environment(enabled)
    apply_qt_opengl_policy(qapplication, qt, enabled)
    return enabled


_OPENGL_INFO_LOGGED = False


def log_opengl_renderer_once(gl_module, prefix: str = "[GPU]") -> None:
    global _OPENGL_INFO_LOGGED
    if _OPENGL_INFO_LOGGED:
        return
    _OPENGL_INFO_LOGGED = True
    try:
        vendor = _decode_gl_string(gl_module.glGetString(gl_module.GL_VENDOR))
        renderer = _decode_gl_string(gl_module.glGetString(gl_module.GL_RENDERER))
        version = _decode_gl_string(gl_module.glGetString(gl_module.GL_VERSION))
    except Exception as exc:
        print(f"{prefix} OpenGL renderer query failed: {exc}", file=sys.stderr)
        return

    mode = "software" if _looks_like_software_renderer(vendor, renderer) else "hardware"
    print(
        f"{prefix} OpenGL {mode} renderer: {renderer or 'unknown'}; "
        f"vendor={vendor or 'unknown'}; version={version or 'unknown'}",
        file=sys.stderr,
    )


def _decode_gl_string(value) -> str:
    if not value:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _looks_like_software_renderer(vendor: str, renderer: str) -> bool:
    text = f"{vendor} {renderer}".lower()
    software_markers = (
        "llvmpipe",
        "softpipe",
        "software",
        "swiftshader",
        "microsoft basic render",
        "mesa offscreen",
    )
    return any(marker in text for marker in software_markers)
