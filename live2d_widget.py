import ctypes
import sys
import OpenGL.GL as gl
from PySide6.QtCore import Qt, QPoint, QElapsedTimer, QTimer, Signal
from PySide6.QtGui import QMouseEvent, QCursor, QGuiApplication, QSurfaceFormat, QOpenGLContext, QMoveEvent, QResizeEvent, QContextMenuEvent
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from live2d_quality import LIVE2D_QUALITY_PROFILES, normalize_live2d_quality
from lua_hit_area_projection import LuaCustomHitAreaState
from platform_patch import set_live2d_texture_quality
from zst_model_archive import clear_virtual_byte_cache, is_virtual_path, prefetch_virtual_model_resources

class Live2DWidget(QOpenGLWidget):
    model_loaded = Signal()

    @staticmethod
    def configure_default_surface_format():
        """Apply the OpenGL surface format Live2D requires."""
        fmt = QSurfaceFormat()
        fmt.setAlphaBufferSize(8)
        fmt.setSamples(0)
        fmt.setDepthBufferSize(0)
        fmt.setStencilBufferSize(8)
        fmt.setSwapInterval(1)
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
        self._drag_moved = False
        self._pressed_on_model = False
        self._drag_start_x = 0
        self._drag_start_y = 0
        self._drag_origin_x = 0
        self._drag_origin_y = 0
        self._window_drag_callback = None
        self._click_callback = None
        self._right_click_callback = None
        self._right_press_handled = False
        self._suppress_next_context_menu = False
        self._drag_locked = False
        self._initialized_gl = False
        
        self._fps = 120
        self._vsync = True
        self._static_render = False
        self._static_render_done = False
        self._clear_color = (0.0, 0.0, 0.0, 0.0)
        self._lip_sync_level = 0.0
        self._lip_sync_target = 0.0
        self._lip_sync_form = 0.0
        self._lip_sync_form_target = 0.0
        self._lip_sync_last_ms = -1000
        self._hit_alpha_threshold = 8
        self._hit_probe_offsets = (
            (0, 0),
            (-3, 0), (3, 0), (0, -3), (0, 3),
            (-6, 0), (6, 0), (0, -6), (0, 6),
        )
        self._hit_alpha_cache = {}
        self._visible_bounds_cache = None
        self._visible_bounds_cache_at = -1000
        self._visible_bounds_cache_ttl_ms = 500
        self._hit_alpha_cache_ttl_ms = 100
        self._hit_test_interval_ms = round(1000 / 30)
        self._last_hit_test_ms = -1000
        self._last_hit_state = False
        
        # PBO (Pixel Buffer Object) 属性
        self._hit_pbo_ids = []
        self._hit_pbo_next = 0
        self._hit_pbo_pending = []
        self._hit_pbo_supported = None
        self._hit_pbo_size = 4
        
        self._hit_clock = QElapsedTimer()
        self._hit_clock.start()
        self._custom_hit_areas = LuaCustomHitAreaState()
        
        # 定时器设置
        self._render_timer = QTimer(self)
        self._render_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._render_timer.timeout.connect(self.update)
        
        self._head_track_timer = QTimer(self)
        self._head_track_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._head_track_timer.setInterval(self._hit_test_interval_ms)
        self._head_track_timer.timeout.connect(self._poll_head_tracking)

        # 性能优化：缓存属性
        self._cache_w = 1
        self._cache_h = 1
        self._cache_w_half = 0.5
        self._cache_h_half = 0.5
        self._cache_global_x = 0
        self._cache_global_y = 0
        self._last_cursor_x = -1
        self._last_cursor_y = -1
        self._head_track_min_delta_sq = 16

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, False)
        self.setAutoFillBackground(False)
        self.setMouseTracking(True)

    # --------------------------------------------------------------------------
    # 基础与公共接口
    # --------------------------------------------------------------------------

    @property
    def model(self):
        return self._model

    @property
    def model_path(self):
        return self._model_path

    def _safe_make_current(self):
        if QOpenGLContext.currentContext() != self.context():
            self.makeCurrent()

    def set_fps(self, fps: int):
        self._fps = max(10, min(fps, 240))
        self._update_render_timer()

    def set_vsync(self, enabled: bool):
        self._vsync = enabled
        if not self._initialized_gl:
            return
        self._safe_make_current()
        try:
            from OpenGL.WGL.EXT.swap_control import wglSwapIntervalEXT
            wglSwapIntervalEXT(1 if self._vsync else 0)
        except Exception:
            pass
        if not self._static_render:
            self.update()

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
        self._update_render_timer()
        self.update()

    def set_clear_color(self, r: float, g: float, b: float, a: float):
        self._clear_color = (r, g, b, a)
        self._static_render_done = False
        self.update()

    def set_lip_sync_level(self, level: float):
        self.set_lip_sync_pose(level, self._lip_sync_form_target)

    def set_lip_sync_pose(self, level: float, form: float = 0.0):
        self._lip_sync_target = max(0.0, min(float(level), 0.55))
        self._lip_sync_form_target = max(-1.0, min(float(form), 1.0))
        self._lip_sync_last_ms = self._hit_clock.elapsed() if self._hit_clock.isValid() else 0
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
            self.update()

    # --------------------------------------------------------------------------
    # 模型加载与区域解析
    # --------------------------------------------------------------------------

    def _load_model_internal(self, model_json_path: str):
        if not model_json_path or not self._live2d:
            return
        self._safe_make_current()
        try:
            if is_virtual_path(model_json_path):
                clear_virtual_byte_cache()
                prefetch_virtual_model_resources(model_json_path)
                
            set_live2d_texture_quality(self._quality_profile)
            disable_precision = LIVE2D_QUALITY_PROFILES[self._quality_profile]["disable_precision"]
            
            self._model = self._live2d.LAppModel()
            if is_virtual_path(model_json_path):
                try:
                    self._model.LoadModelJson(model_json_path, disable_precision=disable_precision)
                finally:
                    clear_virtual_byte_cache()
            else:
                self._model.LoadModelJson(model_json_path, disable_precision=disable_precision)
            self._custom_hit_areas.set_scene_areas(self._prepare_custom_hit_areas(self._model))
            self._model.Resize(self._cache_w, self._cache_h)
            self._update_custom_hit_area_projection()
            
            self._model_path = model_json_path
            self._update_render_timer()
            self.model_loaded.emit()
        except Exception as e:
            print(f"Failed to load model: {e}", file=sys.stderr)
            self._model = None
            self._model_path = ""
            self._custom_hit_areas.clear()
            self._update_render_timer()

    def _prepare_custom_hit_areas(self, model):
        try:
            setting = getattr(model, "modelSetting", None)
            config = getattr(setting, "json", {}) if setting is not None else {}
            areas = config.get("hit_areas_custom") or {}
            if not isinstance(areas, dict):
                return ()

            prepared = []
            for name, x_range in areas.items():
                if not name.endswith("_x") or not isinstance(x_range, list) or len(x_range) != 2:
                    continue
                y_range = areas.get(f"{name[:-2]}_y")
                if not isinstance(y_range, list) or len(y_range) != 2:
                    continue
                x0, x1, y0, y1 = float(x_range[0]), float(x_range[1]), float(y_range[0]), float(y_range[1])
                area_name = name[:-2].strip().lower()
                prepared.append((area_name, min(x0, x1), max(x0, x1), min(y0, y1), max(y0, y1)))
                
            priority = {"head": 0, "face": 0, "body": 10}
            prepared.sort(key=lambda item: (priority.get(item[0], 5), item[0]))
            return tuple(prepared)
        except Exception:
            return ()

    def _update_custom_hit_area_projection(self):
        model = self._model
        if not model or not self._custom_hit_areas.has_scene_areas():
            self._custom_hit_areas.clear_projected()
            return
        try:
            matrix = model.matrixManager
            if not self._custom_hit_areas.project(
                matrix.screenToScene(0.0, 0.0),
                matrix.screenToScene(float(self._cache_w), 0.0),
                matrix.screenToScene(0.0, float(self._cache_h)),
                self._cache_w,
                self._cache_h,
            ):
                self._custom_hit_areas.clear_projected()
        except Exception:
            self._custom_hit_areas.clear_projected()

    # --------------------------------------------------------------------------
    # 渲染与定时器更新
    # --------------------------------------------------------------------------

    def _frame_interval_ms(self) -> int:
        return max(1, round(1000 / self._fps))

    def _update_render_timer(self):
        if not self._initialized_gl or self._static_render or not self._model or not self.isVisible():
            self._render_timer.stop()
            self._head_track_timer.stop()
            return
        self._render_timer.start(self._frame_interval_ms())
        self._head_track_timer.start()

    def showEvent(self, event):
        super().showEvent(event)
        self._update_render_timer()

    def hideEvent(self, event):
        self._render_timer.stop()
        self._head_track_timer.stop()
        super().hideEvent(event)

    # --------------------------------------------------------------------------
    # 事件处理与交互
    # --------------------------------------------------------------------------

    def moveEvent(self, event: QMoveEvent):
        self._update_global_pos_cache()
        super().moveEvent(event)

    def resizeEvent(self, event: QResizeEvent):
        size = event.size()
        self._cache_w, self._cache_h = size.width(), size.height()
        self._cache_w_half = self._cache_w * 0.5
        self._cache_h_half = self._cache_h * 0.5
        super().resizeEvent(event)

    def _update_global_pos_cache(self) -> bool:
        global_pos = self.mapToGlobal(QPoint(0, 0))
        x, y = global_pos.x(), global_pos.y()
        moved = x != self._cache_global_x or y != self._cache_global_y
        self._cache_global_x, self._cache_global_y = x, y
        return moved

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.RightButton:
            pos = event.scenePosition()
            gpos = event.globalPosition()
            self._right_press_handled = self._emit_right_click(pos.x(), pos.y(), gpos.x(), gpos.y())
            if self._right_press_handled:
                self._suppress_next_context_menu = True
                event.accept()
                return
            return super().mousePressEvent(event)

        if (
            sys.platform == "darwin"
            and event.button() == Qt.MouseButton.LeftButton
            and event.modifiers() & Qt.KeyboardModifier.ControlModifier
        ):
            pos = event.scenePosition()
            gpos = event.globalPosition()
            if self._emit_right_click(pos.x(), pos.y(), gpos.x(), gpos.y()):
                self._suppress_next_context_menu = True
                event.accept()
                return

        if event.button() != Qt.MouseButton.LeftButton:
            return super().mousePressEvent(event)
            
        pos = event.scenePosition()
        self._pressed_on_model = self._is_model_hit_at(pos.x(), pos.y())
        if self._drag_locked:
            return super().mousePressEvent(event)
            
        if self._pressed_on_model:
            self._dragging = True
            self._drag_moved = False
            gpos = event.globalPosition()
            self._drag_start_x = self._drag_origin_x = gpos.x()
            self._drag_start_y = self._drag_origin_y = gpos.y()

    def mouseReleaseEvent(self, event: QMouseEvent):
        pos = event.scenePosition()
        x, y = pos.x(), pos.y()

        if event.button() == Qt.MouseButton.RightButton:
            if self._right_press_handled:
                self._right_press_handled = False
                event.accept()
                return
            if self._right_click_callback and self._is_model_hit_at(x, y, sync=True):
                gpos = event.globalPosition()
                self._right_click_callback(int(gpos.x()), int(gpos.y()))
                event.accept()
            return

        should_click = False
        if event.button() == Qt.MouseButton.LeftButton:
            should_click = (
                self._pressed_on_model and 
                not self._drag_moved and 
                self._click_callback and 
                self._is_model_hit_at(x, y)
            )
            self._pressed_on_model = False

        self._dragging = False
        if should_click:
            self._click_callback(x, y, self.hit_area_name_at(x, y))

    def contextMenuEvent(self, event: QContextMenuEvent):
        if self._suppress_next_context_menu:
            self._suppress_next_context_menu = False
            event.accept()
            return
        pos = event.pos()
        gpos = event.globalPos()
        if self._emit_right_click(pos.x(), pos.y(), gpos.x(), gpos.y()):
            event.accept()
            return
        super().contextMenuEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._drag_locked or not (self._dragging and self._window_drag_callback):
            return
            
        gpos = event.globalPosition()
        if not self._drag_moved:
            total_dx = gpos.x() - self._drag_origin_x
            total_dy = gpos.y() - self._drag_origin_y
            if total_dx * total_dx + total_dy * total_dy < 16:
                return
            self._drag_moved = True
            
        dx = int(gpos.x() - self._drag_start_x)
        dy = int(gpos.y() - self._drag_start_y)
        if dx != 0 or dy != 0:
            self._window_drag_callback(dx, dy)
            self._drag_start_x = gpos.x()
            self._drag_start_y = gpos.y()

    def _track_head_at_global(self, gx: float, gy: float):
        if self._dragging or not self._model:
            return
            
        widget_moved = self._update_global_pos_cache()
        cursor_dx = gx - self._last_cursor_x
        cursor_dy = gy - self._last_cursor_y
        
        if not widget_moved and (cursor_dx * cursor_dx + cursor_dy * cursor_dy < self._head_track_min_delta_sq):
            return
            
        self._last_cursor_x, self._last_cursor_y = gx, gy

        cx = self._cache_global_x + self._cache_w_half
        cy = self._cache_global_y + self._cache_h_half
        dx, dy = gx - cx, gy - cy
        dist_sq = dx * dx + dy * dy
        if dist_sq <= 0:
            return

        max_dist = 600.0
        max_dist_sq = max_dist * max_dist
        if dist_sq <= max_dist_sq:
            local_x, local_y = gx - self._cache_global_x, gy - self._cache_global_y
        else:
            factor = max_dist / (dist_sq ** 0.5)
            local_x = self._cache_w_half + dx * factor
            local_y = self._cache_h_half + dy * factor
            
        self._model.Drag(local_x, local_y)

    def _poll_head_tracking(self):
        pos = QCursor.pos()
        self._track_head_at_global(pos.x(), pos.y())

    # --------------------------------------------------------------------------
    # OpenGL 渲染流程
    # --------------------------------------------------------------------------

    def initializeGL(self):
        if self._live2d:
            self._live2d.glInit()
        try:
            gl.glEnable(gl.GL_MULTISAMPLE)
        except Exception:
            pass
        gl.glDisable(gl.GL_DEPTH_TEST)
        gl.glDisable(gl.GL_DITHER)
        
        self._system_scale = QGuiApplication.primaryScreen().devicePixelRatio()
        self._initialized_gl = True
        self._cache_w, self._cache_h = self.width(), self.height()
        self._cache_w_half, self._cache_h_half = self._cache_w * 0.5, self._cache_h * 0.5
        self._update_global_pos_cache()

        if self._pending_model:
            self._load_model_internal(self._pending_model)
            
        self._init_hit_pbos()
        self._update_render_timer()
        self.update()

    def resizeGL(self, w: int, h: int):
        self._cache_w, self._cache_h = w, h
        self._cache_w_half, self._cache_h_half = w * 0.5, h * 0.5
        self._clear_hit_framebuffer_cache()
        gl.glViewport(0, 0, int(w * self._system_scale), int(h * self._system_scale))
        if self._model:
            self._model.Resize(w, h)
            self._update_custom_hit_area_projection()

    def paintGL(self):
        if (self._static_render and self._static_render_done) or not self._live2d or not self._model:
            return

        gl.glClearColor(*self._clear_color)
        gl.glClear(gl.GL_COLOR_BUFFER_BIT | gl.GL_STENCIL_BUFFER_BIT)

        gl.glEnable(gl.GL_BLEND)
        gl.glBlendEquationSeparate(gl.GL_FUNC_ADD, gl.GL_FUNC_ADD)

        self._live2d.clearBuffer()
        gl.glClearColor(*self._clear_color)
        gl.glClear(gl.GL_COLOR_BUFFER_BIT | gl.GL_STENCIL_BUFFER_BIT)
        
        self._model.Update()
        self._apply_lip_sync()
        self._model.Draw()
        if self._static_render:
            self._static_render_done = True

    def _apply_lip_sync(self):
        if not self._model:
            return
        now = self._hit_clock.elapsed() if self._hit_clock.isValid() else 0
        target = self._lip_sync_target if now - self._lip_sync_last_ms <= 180 else 0.0
        form_target = self._lip_sync_form_target if now - self._lip_sync_last_ms <= 180 else 0.0
        self._lip_sync_level += (target - self._lip_sync_level) * 0.55
        self._lip_sync_form += (form_target - self._lip_sync_form) * 0.45
        if self._lip_sync_level < 0.01:
            self._lip_sync_level = 0.0
        if abs(self._lip_sync_form) < 0.01:
            self._lip_sync_form = 0.0
        try:
            self._model.SetParameterValue("PARAM_MOUTH_OPEN_Y", self._lip_sync_level, 1.0)
            self._model.SetParameterValue("PARAM_MOUTH_FORM", self._lip_sync_form, 1.0)
        except Exception:
            pass

    # --------------------------------------------------------------------------
    # 碰撞检测 & Alpha 抓取逻辑
    # --------------------------------------------------------------------------

    def _get_valid_local_pos(self, global_pos: QPoint):
        local = self.mapFromGlobal(global_pos)
        return local if self.rect().contains(local) else None

    def alpha_at_global(self, global_pos: QPoint) -> int:
        local = self._get_valid_local_pos(global_pos)
        if not local: return 0
        alpha = self._get_alpha_fast(local.x(), local.y())
        return 0 if alpha is None else alpha

    def is_model_hit_at_global(self, global_pos: QPoint, *, sync: bool = False) -> bool:
        local = self._get_valid_local_pos(global_pos)
        return self._is_model_hit_at(local.x(), local.y(), sync=sync) if local else False

    def model_hit_state_at_global(self, global_pos: QPoint):
        local = self._get_valid_local_pos(global_pos)
        return self._hit_state_at(local.x(), local.y()) if local else False

    def hit_area_name_at(self, x: float, y: float) -> str:
        if not self._model: return ""
        return self._custom_hit_area_name_at(x, y) or self._sdk_hit_area_name_at(x, y)

    def hit_area_bounds(self, area_name: str):
        area_name = str(area_name or "").strip().lower()
        if not area_name: return None
        try:
            return self._custom_hit_areas.bounds_for(area_name)
        except Exception:
            return None

    def hit_area_union_bounds(self):
        try:
            return self._custom_hit_areas.union_bounds()
        except Exception:
            return None

    def _is_model_hit_at(self, x: float, y: float, *, sync: bool = False) -> bool:
        if not self._model: return False
        state = None if sync else self._hit_state_at(x, y)
        if state is None:
            state = self._hit_state_at_sync(x, y)
        return state is True

    def _emit_right_click(self, x: float, y: float, gx: float, gy: float) -> bool:
        if self._right_click_callback and self._is_model_hit_at(x, y, sync=True):
            self._right_click_callback(int(gx), int(gy))
            return True
        return False

    def _hit_state_at_sync(self, x: float, y: float) -> bool:
        if not self._model:
            self._last_hit_state = False
            return False
        alpha = self._alpha_near(x, y, sync=True)
        self._last_hit_test_ms = self._hit_clock.elapsed()
        self._last_hit_state = (alpha or 0) > self._hit_alpha_threshold
        return self._last_hit_state

    def _hit_state_at(self, x: float, y: float):
        if not self._model:
            self._last_hit_state = False
            return False
            
        now = self._hit_clock.elapsed()
        if now - self._last_hit_test_ms < self._hit_test_interval_ms:
            return self._last_hit_state
            
        self._last_hit_test_ms = now
        alpha = self._alpha_near(x, y, sync=False)
        
        if alpha is None:
            self._last_hit_state = None
            return None
            
        self._last_hit_state = alpha > self._hit_alpha_threshold
        return self._last_hit_state

    def _is_in_model_hit_area(self, x: float, y: float) -> bool:
        if not self._has_model_hit_areas(): return True
        return self._is_in_sdk_hit_area(x, y) or self._is_in_custom_hit_area(x, y)

    def _has_model_hit_areas(self) -> bool:
        return self._has_sdk_hit_areas() or self._custom_hit_areas.has_projected_areas()

    def _has_sdk_hit_areas(self) -> bool:
        try:
            setting = getattr(self._model, "modelSetting", None)
            return setting is not None and setting.getHitAreaNum() > 0
        except Exception:
            return False

    def _is_in_sdk_hit_area(self, x: float, y: float) -> bool:
        return bool(self._sdk_hit_area_name_at(x, y))

    def _sdk_hit_area_name_at(self, x: float, y: float) -> str:
        try:
            if not self._has_sdk_hit_areas(): return ""
            return str(self._model.HitTest("", x, y) or "").strip().lower()
        except Exception:
            return ""

    def _is_in_custom_hit_area(self, x: float, y: float) -> bool:
        return bool(self._custom_hit_area_name_at(x, y))

    def _custom_hit_area_name_at(self, x: float, y: float) -> str:
        try:
            return self._custom_hit_areas.hit_test_name(x, y).strip().lower()
        except Exception:
            return ""

    # --------------------------------------------------------------------------
    # PBO & 像素读取核心
    # --------------------------------------------------------------------------

    def _clear_hit_framebuffer_cache(self):
        self._hit_alpha_cache.clear()
        self._visible_bounds_cache = None
        self._visible_bounds_cache_at = -1000
        self._last_hit_test_ms = -1000
        self._last_hit_state = False
        self._clear_pending_hit_pbos()

    def _safe_unbind_pbo(self):
        try:
            gl.glBindBuffer(gl.GL_PIXEL_PACK_BUFFER, 0)
        except Exception:
            pass

    def visible_model_bounds(self):
        if not self._initialized_gl or not self._model: return None
        now = self._hit_clock.elapsed()
        if self._visible_bounds_cache is not None and (now - self._visible_bounds_cache_at <= self._visible_bounds_cache_ttl_ms):
            return self._visible_bounds_cache
        bounds = self._read_visible_model_bounds()
        self._visible_bounds_cache = bounds
        self._visible_bounds_cache_at = now
        return bounds

    def _read_visible_model_bounds(self):
        width, height = int(self._cache_w * self._system_scale), int(self._cache_h * self._system_scale)
        if width <= 0 or height <= 0: return None
        
        try:
            self._safe_make_current()
            self._process_hit_pbo_results()
            self._safe_unbind_pbo()
            data = gl.glReadPixels(0, 0, width, height, gl.GL_RGBA, gl.GL_UNSIGNED_BYTE)
        except Exception:
            return None

        if not data: return None

        raw = bytes(data)
        min_x, max_x = width, -1
        min_y, max_y = height, -1
        stride, threshold = width * 4, self._hit_alpha_threshold
        step = 1 if width * height <= 600000 else 2
        
        for y_gl in range(0, height, step):
            row_offset = y_gl * stride
            hit_in_row = False
            for x in range(0, width, step):
                if raw[row_offset + x * 4 + 3] > threshold:
                    hit_in_row = True
                    if x < min_x: min_x = x
                    if x > max_x: max_x = x
            if hit_in_row:
                qt_y = height - 1 - y_gl
                if qt_y < min_y: min_y = qt_y
                if qt_y > max_y: max_y = qt_y

        if max_x < min_x or max_y < min_y: return None
        scale = self._system_scale or 1.0
        return (min_x / scale, (max_x + step) / scale, min_y / scale, (max_y + step) / scale)

    def _init_hit_pbos(self):
        if self._hit_pbo_supported is not None: return
        try:
            required_funcs = ("glGenBuffers", "glBindBuffer", "glBufferData", "glFenceSync", 
                              "glClientWaitSync", "glDeleteSync", "glMapBuffer", "glUnmapBuffer")
            if not all(hasattr(gl, name) for name in required_funcs):
                raise RuntimeError("PBO sync functions are unavailable")
                
            self._hit_pbo_ids = []
            for _ in self._hit_probe_offsets:
                pbo = gl.glGenBuffers(1)
                pbo = int(pbo[0] if isinstance(pbo, (list, tuple)) else pbo)
                self._hit_pbo_ids.append(pbo)
                gl.glBindBuffer(gl.GL_PIXEL_PACK_BUFFER, pbo)
                gl.glBufferData(gl.GL_PIXEL_PACK_BUFFER, self._hit_pbo_size, None, gl.GL_STREAM_READ)
                
            self._safe_unbind_pbo()
            self._hit_pbo_supported = True
        except Exception:
            self._safe_unbind_pbo()
            self._hit_pbo_ids = []
            self._hit_pbo_pending = []
            self._hit_pbo_supported = False

    def _clear_pending_hit_pbos(self):
        pending = self._hit_pbo_pending
        self._hit_pbo_pending = []
        for request in pending:
            fence = request.get("fence")
            if fence:
                try: gl.glDeleteSync(fence)
                except Exception: pass

    def _process_hit_pbo_results(self):
        if not self._hit_pbo_supported or not self._hit_pbo_pending: return
        
        ready, still_pending = [], []
        for request in self._hit_pbo_pending:
            try:
                status = gl.glClientWaitSync(request.get("fence"), 0, 0)
                if status in (gl.GL_ALREADY_SIGNALED, gl.GL_CONDITION_SATISFIED):
                    ready.append(request)
                else:
                    still_pending.append(request)
            except Exception:
                still_pending.append(request)
                
        self._hit_pbo_pending = still_pending
        now = self._hit_clock.elapsed()
        
        for request in ready:
            fence = request.get("fence")
            try:
                gl.glBindBuffer(gl.GL_PIXEL_PACK_BUFFER, request["pbo"])
                ptr = gl.glMapBuffer(gl.GL_PIXEL_PACK_BUFFER, gl.GL_READ_ONLY)
                if ptr:
                    data = ctypes.string_at(ptr, self._hit_pbo_size)
                    self._hit_alpha_cache[request["key"]] = (data[3], now)
                    gl.glUnmapBuffer(gl.GL_PIXEL_PACK_BUFFER)
            except Exception:
                pass
            finally:
                self._safe_unbind_pbo()
                if fence:
                    try: gl.glDeleteSync(fence)
                    except Exception: pass
                    
        # 缓存清理机制
        if len(self._hit_alpha_cache) > 128:
            expired = [k for k, (_, ts) in self._hit_alpha_cache.items() if now - ts > self._hit_alpha_cache_ttl_ms]
            for k in expired: self._hit_alpha_cache.pop(k, None)

    def _queue_hit_pbo_read(self, key: tuple[int, int], sx: int, sy: int):
        if not self._hit_pbo_supported or not self._hit_pbo_ids: return
        if any(r["key"] == key for r in self._hit_pbo_pending) or len(self._hit_pbo_pending) >= len(self._hit_pbo_ids):
            return
            
        pending_pbos = {r["pbo"] for r in self._hit_pbo_pending}
        pbo = None
        for _ in self._hit_pbo_ids:
            candidate = self._hit_pbo_ids[self._hit_pbo_next]
            self._hit_pbo_next = (self._hit_pbo_next + 1) % len(self._hit_pbo_ids)
            if candidate not in pending_pbos:
                pbo = candidate
                break
        if pbo is None: return
        
        try:
            gl.glBindBuffer(gl.GL_PIXEL_PACK_BUFFER, pbo)
            gl.glReadPixels(sx, sy, 1, 1, gl.GL_RGBA, gl.GL_UNSIGNED_BYTE, ctypes.c_void_p(0))
            fence = gl.glFenceSync(gl.GL_SYNC_GPU_COMMANDS_COMPLETE, 0)
            if not fence: raise RuntimeError("PBO fence creation failed")
            self._hit_pbo_pending.append({"pbo": pbo, "key": key, "fence": fence})
        except Exception:
            self._hit_pbo_supported = False
            self._clear_pending_hit_pbos()
        finally:
            self._safe_unbind_pbo()

    def _alpha_near(self, x: float, y: float, sync: bool = False):
        alpha, known = 0, False
        fetch_method = self._get_alpha_sync if sync else self._get_alpha_fast
        
        for dx, dy in self._hit_probe_offsets:
            sample_alpha = fetch_method(x + dx, y + dy)
            if sample_alpha is None: continue
            
            known = True
            alpha = max(alpha, sample_alpha)
            if alpha > self._hit_alpha_threshold:
                break
                
        return alpha if (known or sync) else None

    def _get_alpha_read_context(self, x: float, y: float):
        """通用：检查坐标合法性，获取GL坐标并尝试从缓存取值，减少重复代码"""
        if not self._initialized_gl or not self._model: return None
        if not (0 <= x < self._cache_w and 0 <= y < self._cache_h): return None
        
        self._safe_make_current()
        if self._hit_pbo_supported is not False:
            self._init_hit_pbos()
            self._process_hit_pbo_results()
            
        sx = int(x * self._system_scale)
        sy = int((self._cache_h - 1 - y) * self._system_scale)
        key = (sx, sy)
        now = self._hit_clock.elapsed()
        
        cached = self._hit_alpha_cache.get(key)
        if cached and now - cached[1] <= self._hit_alpha_cache_ttl_ms:
            return sx, sy, key, now, cached[0]
            
        return sx, sy, key, now, None

    def _get_alpha_sync(self, x: float, y: float) -> int:
        ctx = self._get_alpha_read_context(x, y)
        if not ctx: return 0
        sx, sy, key, now, cached_alpha = ctx
        if cached_alpha is not None: return cached_alpha

        try:
            pixel = (ctypes.c_ubyte * 4)()
            self._safe_unbind_pbo()
            gl.glReadPixels(sx, sy, 1, 1, gl.GL_RGBA, gl.GL_UNSIGNED_BYTE, pixel)
            alpha = int(pixel[3])
            self._hit_alpha_cache[key] = (alpha, now)
            return alpha
        except Exception:
            return 0

    def _get_alpha_fast(self, x: float, y: float):
        ctx = self._get_alpha_read_context(x, y)
        if not ctx: return 0
        sx, sy, key, _, cached_alpha = ctx
        if cached_alpha is not None: return cached_alpha

        try:
            self._queue_hit_pbo_read(key, sx, sy)
            # 由于是异步列队，当前帧可能拿不到结果，检查队列是否立即命中了现有缓存机制
            cached = self._hit_alpha_cache.get(key)
            return cached[0] if cached else None
        except Exception:
            return 0
