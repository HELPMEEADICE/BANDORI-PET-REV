def configure_live2d_surface_format(vsync: bool | None = None) -> None:
    """Configure the shared OpenGL surface without importing the renderer."""
    from PySide6.QtGui import QSurfaceFormat

    fmt = QSurfaceFormat(QSurfaceFormat.defaultFormat())
    fmt.setAlphaBufferSize(8)
    fmt.setSamples(0)
    fmt.setDepthBufferSize(0)
    fmt.setStencilBufferSize(8)
    if vsync is not None:
        fmt.setSwapInterval(1 if bool(vsync) else 0)
    fmt.setVersion(2, 1)
    fmt.setRenderableType(QSurfaceFormat.RenderableType.OpenGL)
    fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CompatibilityProfile)
    QSurfaceFormat.setDefaultFormat(fmt)
