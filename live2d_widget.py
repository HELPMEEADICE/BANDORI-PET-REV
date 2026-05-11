import math
import ctypes
import OpenGL.GL as gl
from PySide6.QtCore import Qt, QTimerEvent, QPoint, QElapsedTimer
from PySide6.QtGui import QMouseEvent, QCursor, QGuiApplication, QSurfaceFormat, QOpenGLContext, QMoveEvent, QResizeEvent
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from live2d_quality import LIVE2D_QUALITY_PROFILES, normalize_live2d_quality
from platform_patch import set_live2d_texture_quality


def _get_display_refresh():
    try:
        screen = QGuiApplication.primaryScreen()
        if screen:
            rr = screen.refreshRate()
            if rr > 0:
                return rr
    except Exception:
        pass
    return 60


class Live2DWidget(QOpenGLWidget):
    @staticmethod
    def configure_default_surface_format():
        """Apply the OpenGL surface format Live2D requires.

        Must be called before QApplication is constructed so the global shared
        GL context (created when AA_ShareOpenGLContexts is set) gets the
        correct alpha/stencil buffers. Otherwise shader linking can fail with
        GL_INVALID_OPERATION on glGetAttribLocation.
        """
        fmt = QSurfaceFormat()
        fmt.setAlphaBufferSize(8)
        fmt.setSamples(0)
        fmt.setDepthBufferSize(0)
        fmt.setStencilBufferSize(8)
        fmt.setSwapInterval(0)
        fmt.setVersion(2, 1)
        fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CompatibilityProfile)
        QSurfaceFormat.setDefaultFormat(fmt)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._model = None
        self._live2d = None
        self._model_path = ""
        self._pending_model = ""
        self._quality_profile = "balanced"
        self._system_scale = 1.0
        
        self._dragging = False
        self._drag_start_x = 0
        self._drag_start_y = 0
        self._window_drag_callback = None
        self._click_callback = None
        self._right_click_callback = None
        self._drag_locked = False
        self._initialized_gl = False
        
        self._fps = 120
        self._vsync = True
        self._timer_id = None
        self._static_render = False
        self._static_render_done = False
        self._clear_color = (0.0, 0.0, 0.0, 0.0)
        self._hit_alpha_threshold = 8
        self._hit_probe_offsets = (
            (0, 0),
            (-3, 0), (3, 0), (0, -3), (0, 3),
            (-6, 0), (6, 0), (0, -6), (0, 6),
        )
        self._hit_framebuffer_image = None
        self._hit_framebuffer_time = -10000
        self._hit_framebuffer_ttl_ms = 33
        self._hit_clock = QElapsedTimer()
        self._hit_clock.start()

        # 性能优化：缓存属性
        self._cache_w = 1
        self._cache_h = 1
        self._cache_w_half = 0.5
        self._cache_h_half = 0.5
        self._cache_global_x = 0
        self._cache_global_y = 0

        # 性能优化：鼠标脏标记
        self._last_cursor_x = -1
        self._last_cursor_y = -1
        self._head_track_counter = 0

        # 极限优化：预分配底层 C 内存
        self._pixel_buf = (ctypes.c_ubyte * 4)()

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, False)
        self.setAutoFillBackground(False)
        self.setMouseTracking(True)

    def _safe_make_current(self):
        if QOpenGLContext.currentContext() != self.context():
            self.makeCurrent()

    def _effective_fps(self):
        if self._vsync:
            return _get_display_refresh()
        return max(10, self._fps)

    def _restart_timer(self):
        if self._timer_id is not None:
            self.killTimer(self._timer_id)
        target_ms = max(1, int(1000.0 / self._effective_fps()) - 1)
        self._timer_id = self.startTimer(target_ms, Qt.TimerType.PreciseTimer)

    def set_fps(self, fps: int):
        self._fps = max(10, min(fps, 240))
        refresh = _get_display_refresh()
        if self._vsync and self._fps > refresh:
            self._vsync = False
        if self._timer_id is not None:
            self._restart_timer()

    def set_vsync(self, enabled: bool):
        self._vsync = enabled
        if self._vsync and self._fps > _get_display_refresh():
            self._vsync = False
        if not self._initialized_gl:
            return
        self._safe_make_current()
        try:
            from OpenGL.WGL.EXT.swap_control import wglSwapIntervalEXT
            wglSwapIntervalEXT(1 if self._vsync else 0)
        except Exception:
            pass
        self._restart_timer()

    def set_render_quality(self, profile: str):
        profile = normalize_live2d_quality(profile)
        if profile == self._quality_profile:
            return
        self._quality_profile = profile
        if self._model_path:
            self._load_model_internal(self._model_path)
            self.update()

    def set_static_render(self, enabled: bool):
        self._static_render = enabled
        self._static_render_done = False
        if enabled and self._timer_id is not None:
            self.killTimer(self._timer_id)
            self._timer_id = None

    def set_clear_color(self, r: float, g: float, b: float, a: float):
        self._clear_color = (r, g, b, a)
        self._static_render_done = False
        self.update()

    def set_live2d_module(self, module):
        self._live2d = module

    def set_window_drag_callback(self, cb):
        self._window_drag_callback = cb

    def set_click_callback(self, cb):
        self._click_callback = cb

    def set_right_click_callback(self, cb):
        self._right_click_callback = cb

    def set_drag_locked(self, locked: bool):
        self._drag_locked = locked

    def set_model_path(self, model_json_path: str):
        self._pending_model = model_json_path
        self._static_render_done = False
        self._clear_hit_framebuffer_cache()
        if self._initialized_gl:
            self._load_model_internal(model_json_path)
            if self._static_render:
                self.update()

    def _load_model_internal(self, model_json_path: str):
        if not model_json_path or not self._live2d:
            return
        self._safe_make_current()
        try:
            set_live2d_texture_quality(self._quality_profile)
            disable_precision = LIVE2D_QUALITY_PROFILES[self._quality_profile]["disable_precision"]
            self._model = self._live2d.LAppModel()
            self._model.LoadModelJson(model_json_path, disable_precision=disable_precision)
            self._model.Resize(self._cache_w, self._cache_h)
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

    def moveEvent(self, event: QMoveEvent):
        global_pos = self.mapToGlobal(QPoint(0, 0))
        self._cache_global_x = global_pos.x()
        self._cache_global_y = global_pos.y()
        super().moveEvent(event)

    def resizeEvent(self, event: QResizeEvent):
        size = event.size()
        self._cache_w = size.width()
        self._cache_h = size.height()
        self._cache_w_half = self._cache_w * 0.5
        self._cache_h_half = self._cache_h * 0.5
        super().resizeEvent(event)

    def initializeGL(self):
        if self._live2d:
            self._live2d.glInit()
        self._system_scale = QGuiApplication.primaryScreen().devicePixelRatio()
        self._initialized_gl = True
        
        self._cache_w = self.width()
        self._cache_h = self.height()
        self._cache_w_half = self._cache_w * 0.5
        self._cache_h_half = self._cache_h * 0.5
        pos = self.mapToGlobal(QPoint(0, 0))
        self._cache_global_x = pos.x()
        self._cache_global_y = pos.y()

        if self._pending_model:
            self._load_model_internal(self._pending_model)
        if not self._static_render:
            self._restart_timer()
        else:
            self.update()

    def resizeGL(self, w: int, h: int):
        self._clear_hit_framebuffer_cache()
        gl.glViewport(0, 0, int(w * self._system_scale), int(h * self._system_scale))
        if self._model:
            self._model.Resize(w, h)

    def paintGL(self):
        self._clear_hit_framebuffer_cache()
        if self._static_render and self._static_render_done:
            return

        model = self._model
        if not self._live2d or not model:
            return

        try:
            gl.glEnable(gl.GL_MULTISAMPLE)
        except Exception:
            pass
        
        gl.glDisable(gl.GL_DEPTH_TEST)
        gl.glDisable(gl.GL_DITHER)

        gl.glClearColor(*self._clear_color)
        gl.glClear(gl.GL_COLOR_BUFFER_BIT | gl.GL_STENCIL_BUFFER_BIT)

        gl.glEnable(gl.GL_BLEND)
        gl.glBlendEquationSeparate(gl.GL_FUNC_ADD, gl.GL_FUNC_ADD)

        self._live2d.clearBuffer()
        gl.glClearColor(*self._clear_color)
        gl.glClear(gl.GL_COLOR_BUFFER_BIT | gl.GL_STENCIL_BUFFER_BIT)
        model.Update()
        model.Draw()
        if self._static_render:
            self._static_render_done = True

    def timerEvent(self, event: QTimerEvent):
        if self._static_render:
            return
        if not self.isVisible():
            return

        model = self._model
        if not self._dragging and model is not None:
            self._head_track_counter += 1
            if self._head_track_counter >= 3:
                self._head_track_counter = 0
                
                g_pos = QCursor.pos()
                gx, gy = g_pos.x(), g_pos.y()
                widget_pos = self.mapToGlobal(QPoint(0, 0))
                self._cache_global_x = widget_pos.x()
                self._cache_global_y = widget_pos.y()

                if gx != self._last_cursor_x or gy != self._last_cursor_y:
                    self._last_cursor_x = gx
                    self._last_cursor_y = gy
                    
                    cx = self._cache_global_x + self._cache_w_half
                    cy = self._cache_global_y + self._cache_h_half
                    dx = gx - cx
                    dy = gy - cy
                    
                    dist = math.hypot(dx, dy)
                    if dist > 0:
                        max_dist = 600.0
                        norm = 1.0 if dist > max_dist else dist / max_dist
                        factor = norm / dist
                        ux = dx * factor
                        uy = dy * factor
                        
                        local_x = cx + ux * max_dist - self._cache_global_x
                        local_y = cy + uy * max_dist - self._cache_global_y
                        model.Drag(local_x, local_y)

        self.update()

    def mousePressEvent(self, event: QMouseEvent):
        if self._drag_locked:
            super().mousePressEvent(event)
            return
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        x = event.scenePosition().x()
        y = event.scenePosition().y()
        if self._is_model_hit_at(x, y):
            self._dragging = True
            gpos = event.globalPosition()
            self._drag_start_x = gpos.x()
            self._drag_start_y = gpos.y()

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.RightButton:
            x = event.scenePosition().x()
            y = event.scenePosition().y()
            if self._is_model_hit_at(x, y) and self._right_click_callback:
                gpos = event.globalPosition()
                self._right_click_callback(int(gpos.x()), int(gpos.y()))
            return
        if self._dragging:
            self._dragging = False
        elif self._click_callback:
            self._click_callback()

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._drag_locked:
            return
        if self._dragging and self._window_drag_callback:
            gpos = event.globalPosition()
            dx = int(gpos.x() - self._drag_start_x)
            dy = int(gpos.y() - self._drag_start_y)
            if dx != 0 or dy != 0:
                self._window_drag_callback(dx, dy)
                self._drag_start_x = gpos.x()
                self._drag_start_y = gpos.y()

    def alpha_at_global(self, global_pos: QPoint) -> int:
        local = self.mapFromGlobal(global_pos)
        if not self.rect().contains(local):
            return 0
        return self._get_alpha_fast(local.x(), local.y())

    def is_model_hit_at_global(self, global_pos: QPoint) -> bool:
        local = self.mapFromGlobal(global_pos)
        if not self.rect().contains(local):
            return False
        return self._is_model_hit_at(local.x(), local.y())

    def _is_model_hit_at(self, x: float, y: float) -> bool:
        if not self._model:
            return False
        return self._alpha_near(x, y) > self._hit_alpha_threshold

    def _clear_hit_framebuffer_cache(self):
        self._hit_framebuffer_image = None
        self._hit_framebuffer_time = -10000

    def _alpha_near(self, x: float, y: float) -> int:
        alpha = 0
        for dx, dy in self._hit_probe_offsets:
            px = x + dx
            py = y + dy
            alpha = max(alpha, self._get_alpha_fast(px, py))
            if alpha <= self._hit_alpha_threshold:
                alpha = max(alpha, self._get_alpha_from_framebuffer(px, py))
            if alpha > self._hit_alpha_threshold:
                break
        return alpha

    def _get_alpha_from_framebuffer(self, x: float, y: float) -> int:
        if x < 0 or y < 0 or x >= self._cache_w or y >= self._cache_h:
            return 0
        try:
            now = self._hit_clock.elapsed()
            if (
                self._hit_framebuffer_image is None
                or now - self._hit_framebuffer_time > self._hit_framebuffer_ttl_ms
            ):
                self._hit_framebuffer_image = self.grabFramebuffer()
                self._hit_framebuffer_time = now
            image = self._hit_framebuffer_image
            if image is None or image.isNull():
                return 0
            scale_x = image.width() / max(1, self._cache_w)
            scale_y = image.height() / max(1, self._cache_h)
            ix = max(0, min(image.width() - 1, int(x * scale_x)))
            iy = max(0, min(image.height() - 1, int(y * scale_y)))
            return image.pixelColor(ix, iy).alpha()
        except Exception:
            return 0

    def _get_alpha_fast(self, x: float, y: float) -> int:
        if not self._initialized_gl or not self._model:
            return 0
        if x < 0 or y < 0 or x >= self._cache_w or y >= self._cache_h:
            return 0
            
        try:
            self._safe_make_current()
            sx = int(x * self._system_scale)
            sy = int((self._cache_h - 1 - y) * self._system_scale)
            
            gl.glReadPixels(sx, sy, 1, 1, gl.GL_RGBA, gl.GL_UNSIGNED_BYTE, self._pixel_buf)
            return self._pixel_buf[3]
        except Exception:
            return 0
