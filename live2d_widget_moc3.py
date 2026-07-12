import sys
from PySide6.QtOpenGL import QOpenGLFramebufferObject, QOpenGLFramebufferObjectFormat
from qt_gl import gl


DEFAULT_MOC3_RENDER_SCALE = 1.35
MOC3_BALANCED_SSAA_SCALE = 2


class Live2DSSAAFramebuffer:
    def __init__(self):
        self._fbo = None
        self._size = (0, 0)

    def dispose(self):
        self._fbo = None
        self._size = (0, 0)

    def bind(self, width: int, height: int) -> bool:
        width = max(int(width), 1)
        height = max(int(height), 1)
        if self._fbo is None or self._size != (width, height):
            fmt = QOpenGLFramebufferObjectFormat()
            fmt.setAttachment(QOpenGLFramebufferObject.Attachment.CombinedDepthStencil)
            self._fbo = QOpenGLFramebufferObject(width, height, fmt)
            self._size = (width, height)
        if not self._fbo.isValid():
            self.dispose()
            return False
        return self._fbo.bind()

    def release(self):
        if self._fbo is not None:
            self._fbo.release()

    def blit_to_default(self, default_fbo: int, width: int, height: int, clear_color) -> bool:
        if self._fbo is None:
            return False
        width = max(int(width), 1)
        height = max(int(height), 1)
        source_w, source_h = self._size
        try:
            gl.glBindFramebuffer(gl.GL_READ_FRAMEBUFFER, int(self._fbo.handle()))
            gl.glBindFramebuffer(gl.GL_DRAW_FRAMEBUFFER, default_fbo)
            gl.glViewport(0, 0, width, height)
            gl.glClearColor(*clear_color)
            gl.glClear(gl.GL_COLOR_BUFFER_BIT | gl.GL_STENCIL_BUFFER_BIT)
            gl.glBlitFramebuffer(
                0,
                0,
                source_w,
                source_h,
                0,
                0,
                width,
                height,
                gl.GL_COLOR_BUFFER_BIT,
                gl.GL_LINEAR,
            )
            gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, default_fbo)
            return True
        except Exception as exc:
            print(f"Live2D SSAA blit failed, falling back: {exc}", file=sys.stderr)
            gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, default_fbo)
            self.dispose()
            return False

    @staticmethod
    def draw_direct_to_default(model, default_fbo: int, width: int, height: int, clear_color):
        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, default_fbo)
        gl.glViewport(0, 0, max(int(width), 1), max(int(height), 1))
        gl.glClearColor(*clear_color)
        gl.glClear(gl.GL_COLOR_BUFFER_BIT | gl.GL_STENCIL_BUFFER_BIT)
        # The model was already updated and rendered into the SSAA target.
        # A fallback is a second render of that exact state, not a second
        # simulation tick (which can reset physics outputs at zero delta).
        model.Render()


class Moc3RenderPipeline:
    def prepare_model(self, model):
        model.SetScale(DEFAULT_MOC3_RENDER_SCALE)

    def ssaa_scale(self, quality_profile: str) -> int:
        return MOC3_BALANCED_SSAA_SCALE if quality_profile == "balanced" else 1

    def create_framebuffer(self):
        return Live2DSSAAFramebuffer()


MOC3_RENDER_PIPELINE = Moc3RenderPipeline()
