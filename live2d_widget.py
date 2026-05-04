import OpenGL.GL as gl
from PySide6.QtCore import Qt, QTimerEvent, QPoint
from PySide6.QtGui import QMouseEvent, QCursor, QGuiApplication, QSurfaceFormat
from PySide6.QtOpenGLWidgets import QOpenGLWidget


class Live2DWidget(QOpenGLWidget):
    def __init__(self, parent=None):
        fmt = QSurfaceFormat()
        fmt.setAlphaBufferSize(8)
        fmt.setSamples(0)
        QSurfaceFormat.setDefaultFormat(fmt)

        super().__init__(parent)
        self._model = None
        self._live2d = None
        self._model_path = ""
        self._pending_model = ""
        self._system_scale = 1.0
        self._dragging = False
        self._drag_start_x = 0
        self._drag_start_y = 0
        self._window_drag_callback = None
        self._click_callback = None
        self._initialized_gl = False
        self._fps = 120
        self._timer_id = None

        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMouseTracking(True)

    def set_fps(self, fps: int):
        self._fps = max(10, min(fps, 240))
        if self._timer_id is not None:
            self.killTimer(self._timer_id)
            self._timer_id = self.startTimer(int(1000 / self._fps))

    def set_live2d_module(self, module):
        self._live2d = module

    def set_window_drag_callback(self, cb):
        self._window_drag_callback = cb

    def set_click_callback(self, cb):
        self._click_callback = cb

    def set_model_path(self, model_json_path: str):
        self._pending_model = model_json_path
        if self._initialized_gl:
            self._load_model_internal(model_json_path)

    def _load_model_internal(self, model_json_path: str):
        if not model_json_path or not self._live2d:
            return
        self.makeCurrent()
        try:
            self._model = self._live2d.LAppModel()
            self._model.LoadModelJson(model_json_path)
            self._model.Resize(self.width(), self.height())
            self._model_path = model_json_path
        except Exception as e:
            print(f"Failed to load model: {e}")
            self._model = None
            self._model_path = ""

    @property
    def model(self):
        return self._model

    @property
    def model_path(self):
        return self._model_path

    def initializeGL(self):
        if self._live2d:
            self._live2d.glInit()
        self._system_scale = QGuiApplication.primaryScreen().devicePixelRatio()
        self._initialized_gl = True
        if self._pending_model:
            self._load_model_internal(self._pending_model)
        self._timer_id = self.startTimer(int(1000 / self._fps))

    def resizeGL(self, w: int, h: int):
        gl.glViewport(0, 0, int(w * self._system_scale), int(h * self._system_scale))
        if self._model:
            self._model.Resize(w, h)

    def paintGL(self):
        if not self._live2d or not self._model:
            return
        self._live2d.clearBuffer()
        self._model.Update()
        self._model.Draw()

    def timerEvent(self, event: QTimerEvent):
        if not self.isVisible():
            return
        if not self._dragging and self._model:
            global_pos = QCursor.pos()
            widget_origin = self.mapToGlobal(QPoint(0, 0))
            local_x = global_pos.x() - widget_origin.x()
            local_y = global_pos.y() - widget_origin.y()
            self._model.Drag(local_x, local_y)
        self.update()

    def mousePressEvent(self, event: QMouseEvent):
        x = event.scenePosition().x()
        y = event.scenePosition().y()
        alpha = self._get_alpha_at(x, y)
        if alpha > 0:
            self._dragging = True
            gpos = event.globalPosition()
            self._drag_start_x = gpos.x()
            self._drag_start_y = gpos.y()

    def mouseReleaseEvent(self, event: QMouseEvent):
        if self._dragging:
            self._dragging = False
        elif self._click_callback:
            self._click_callback()

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._dragging and self._window_drag_callback:
            gpos = event.globalPosition()
            dx = int(gpos.x() - self._drag_start_x)
            dy = int(gpos.y() - self._drag_start_y)
            if dx != 0 or dy != 0:
                self._window_drag_callback(dx, dy)
                self._drag_start_x = gpos.x()
                self._drag_start_y = gpos.y()

    def _get_alpha_at(self, x: float, y: float) -> int:
        try:
            sx = int(x * self._system_scale)
            sy = int((self.height() - y) * self._system_scale)
            pixel = gl.glReadPixels(sx, sy, 1, 1, gl.GL_RGBA, gl.GL_UNSIGNED_BYTE)
            return pixel[3] if len(pixel) >= 4 else 0
        except Exception:
            return 0
