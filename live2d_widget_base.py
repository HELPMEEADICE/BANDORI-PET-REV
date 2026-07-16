import ctypes
import os
import sys
import time
from PySide6.QtCore import Qt, QPoint, QElapsedTimer, QTimer, Signal
from PySide6.QtGui import QCursor, QGuiApplication
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from process_utils import interaction_trace
from qt_gl import gl


DEFAULT_HIT_ALPHA_THRESHOLD = 8
DEFAULT_LIP_SYNC_MAX_OPEN = 0.55
HIT_STABILITY_GRACE_MS = 120
HIT_STABILITY_DISTANCE = 12
MAX_CONSECUTIVE_DRAW_FAILURES = 3
DRAW_FAILURE_LOG_INTERVAL_SECONDS = 5.0


def _apply_windows_swap_interval(enabled: bool) -> bool:
    if os.name != "nt":
        return False
    try:
        from OpenGL.WGL.EXT.swap_control import wglSwapIntervalEXT

        return bool(wglSwapIntervalEXT(1 if enabled else 0))
    except Exception:
        return False


class DirectRenderPipeline:
    """Default framebuffer path shared by models without extra post-processing."""

    def prepare_model(self, model):
        del model

    def ssaa_scale(self, quality_profile: str) -> int:
        del quality_profile
        return 1

    def create_framebuffer(self):
        return None


DIRECT_RENDER_PIPELINE = DirectRenderPipeline()


class _Live2DPerfProbe:
    def __init__(self):
        self.enabled = os.environ.get("BANDORI_LIVE2D_PROFILE", "").strip().lower() in {"1", "true", "yes", "on"}
        self.interval = max(1.0, self._float_env("BANDORI_LIVE2D_PROFILE_INTERVAL", 5.0))
        self._last_report = time.perf_counter()
        self._stats = {}
        self._frames = 0

    @staticmethod
    def _float_env(name: str, default: float) -> float:
        try:
            return float(os.environ.get(name, default))
        except (TypeError, ValueError):
            return default

    def now(self) -> float:
        return time.perf_counter() if self.enabled else 0.0

    def add(self, name: str, elapsed: float):
        if not self.enabled:
            return
        total, count, max_elapsed = self._stats.get(name, (0.0, 0, 0.0))
        self._stats[name] = (total + elapsed, count + 1, max(max_elapsed, elapsed))

    def frame(self):
        if not self.enabled:
            return
        self._frames += 1
        now = time.perf_counter()
        elapsed = now - self._last_report
        if elapsed < self.interval:
            return
        fps = self._frames / elapsed if elapsed > 0 else 0.0
        parts = [f"fps={fps:.1f}"]
        for name in sorted(self._stats):
            total, count, max_elapsed = self._stats[name]
            avg_ms = (total / count * 1000.0) if count else 0.0
            max_ms = max_elapsed * 1000.0
            parts.append(f"{name}=avg:{avg_ms:.2f}ms max:{max_ms:.2f}ms n:{count}")
        print("[Live2DPerf] " + " | ".join(parts), file=sys.stderr, flush=True)
        self._stats.clear()
        self._frames = 0
        self._last_report = now


class Live2DWidgetBase(QOpenGLWidget):
    model_loaded = Signal()

    @staticmethod
    def configure_default_surface_format(vsync: bool | None = None):
        from live2d_surface_format import configure_live2d_surface_format

        configure_live2d_surface_format(vsync)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._model = None
        self._live2d = None
        self._model_path = ""
        self._pending_model = ""
        self._quality_profile = "balanced"
        self._ssaa_fbo = None
        self._render_pipeline = DIRECT_RENDER_PIPELINE
        self._renderer_target_size = None
        self._model_logical_size = None
        self._system_scale = 1.0
        
        self._dragging = False
        self._drag_moved = False
        self._pressed_on_model = False
        self._drag_start_x = 0
        self._drag_start_y = 0
        self._drag_origin_x = 0
        self._drag_origin_y = 0
        self._window_drag_callback = None
        self._window_drag_start_callback = None
        self._window_drag_end_callback = None
        self._click_callback = None
        self._double_click_callback = None
        self._right_click_callback = None
        self._right_press_handled = False
        self._suppress_next_context_menu = False
        self._drag_locked = False
        self._initialized_gl = False
        self._head_tracking_enabled = True
        self._gaze_target = None
        
        self._fps = 120
        self._vsync = True
        self._static_render = False
        self._static_render_done = False
        self._consecutive_draw_failures = 0
        self._render_failure_suspended = False
        self._last_draw_failure_log_at = 0.0
        self._clear_color = (0.0, 0.0, 0.0, 0.0)
        self._lip_sync_level = 0.0
        self._lip_sync_target = 0.0
        self._lip_sync_form = 0.0
        self._lip_sync_form_target = 0.0
        self._lip_sync_last_ms = -1000
        self._hit_alpha_threshold = DEFAULT_HIT_ALPHA_THRESHOLD
        self._lip_sync_max_open = DEFAULT_LIP_SYNC_MAX_OPEN
        self._last_confirmed_hit_ms = -1000
        self._last_confirmed_hit_pos = None
        
        self._hit_clock = QElapsedTimer()
        self._hit_clock.start()
        self._custom_hit_areas = None
        self._perf_probe = _Live2DPerfProbe()
        
        self._render_timer = QTimer(self)
        self._render_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._render_timer.timeout.connect(self.update)
        
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
    # Subclass hook for model-format-specific rendering
    # --------------------------------------------------------------------------

    def _render_pipeline_for_model(self, model):
        del model
        return DIRECT_RENDER_PIPELINE

    def _render_ssaa_scale(self) -> int:
        if not self._model:
            return 1
        return self._render_pipeline.ssaa_scale(self._quality_profile)

    def _sync_renderer_target_size(self, *, force: bool = False):
        model = self._model
        if not model or self._render_pipeline is DIRECT_RENDER_PIPELINE:
            self._renderer_target_size = None
            return
        scale = self._render_ssaa_scale()
        target_size = (
            max(1, int(self._cache_w * self._system_scale) * scale),
            max(1, int(self._cache_h * self._system_scale) * scale),
        )
        if force or target_size != self._renderer_target_size:
            model.ResizeRenderer(*target_size)
            self._renderer_target_size = target_size

    def _sync_model_logical_size(self, *, force: bool = False) -> bool:
        model = self._model
        if not model:
            self._model_logical_size = None
            return False
        logical_size = (max(1, int(self._cache_w)), max(1, int(self._cache_h)))
        if not force and logical_size == self._model_logical_size:
            return False
        model.Resize(*logical_size)
        self._model_logical_size = logical_size
        self._update_custom_hit_area_projection()
        return True

    # --------------------------------------------------------------------------
    # Base and public interface
    # --------------------------------------------------------------------------

    @property
    def model(self):
        return self._model

    @property
    def model_path(self):
        return self._model_path

    def _safe_make_current(self):
        from PySide6.QtGui import QOpenGLContext

        if QOpenGLContext.currentContext() != self.context():
            self.makeCurrent()

    def set_fps(self, fps: int):
        self._fps = max(10, min(fps, 240))
        self._update_render_timer()

    def set_vsync(self, enabled: bool):
        self._vsync = bool(enabled)
        if not self._initialized_gl:
            return
        if os.name == "nt":
            self._safe_make_current()
            _apply_windows_swap_interval(self._vsync)
        self._update_render_timer()
        if not self._static_render:
            self.update()

    def set_render_quality(self, profile: str):
        from live2d_quality import normalize_live2d_quality
        from platform_patch import set_live2d_texture_quality
        profile = normalize_live2d_quality(profile)
        if profile == self._quality_profile:
            return
        self._quality_profile = profile
        set_live2d_texture_quality(profile)
        if self._model:
            self._safe_make_current()
            self._model.ApplyTextureQuality(profile)
            if self._render_ssaa_scale() <= 1 and self._ssaa_fbo is not None:
                self._ssaa_fbo.dispose()
            self._sync_renderer_target_size(force=True)
            self._reset_render_failure_state()
            self._update_render_timer()
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

    def set_lip_sync_pose(self, level: float, form: float = 0.0):
        self._lip_sync_target = max(0.0, min(float(level), self._lip_sync_max_open))
        self._lip_sync_form_target = max(-1.0, min(float(form), 1.0))
        self._lip_sync_last_ms = self._hit_clock.elapsed() if self._hit_clock.isValid() else 0
        self._update_render_timer()
        self.update()

    def set_hit_alpha_threshold(self, threshold: int):
        self._hit_alpha_threshold = max(0, min(int(threshold), 255))
        self._reset_hit_stability()

    def set_lip_sync_max_open(self, value: float):
        self._lip_sync_max_open = max(0.0, min(float(value), 1.0))
        self._lip_sync_target = max(0.0, min(self._lip_sync_target, self._lip_sync_max_open))

    def set_live2d_module(self, module):
        self._live2d = module

    def dispose(self):
        if self._initialized_gl:
            self._initialized_gl = False
            self._safe_make_current()
            if self._ssaa_fbo is not None:
                self._ssaa_fbo.dispose()
            self._dispose_model_renderer()
        if self._custom_hit_areas is not None:
            self._custom_hit_areas.dispose()
            self._custom_hit_areas = None

    def release_model(self):
        """Release model CPU/GPU state while keeping the widget reusable."""

        self._render_timer.stop()
        if self._initialized_gl:
            self._safe_make_current()
        self._dispose_model_renderer()
        if self._live2d is not None:
            try:
                self._live2d.dispose()
            except Exception:
                pass
        self._model_path = ""
        self._pending_model = ""
        if self._custom_hit_areas is not None:
            self._custom_hit_areas.clear()
        try:
            from zst_model_archive import clear_virtual_byte_cache

            clear_virtual_byte_cache()
        except Exception:
            pass
        self._reset_render_failure_state()

    def _dispose_model_renderer(self):
        model = self._model
        self._model = None
        self._render_pipeline = DIRECT_RENDER_PIPELINE
        self._renderer_target_size = None
        self._model_logical_size = None
        if self._ssaa_fbo is not None:
            self._ssaa_fbo.dispose()
            self._ssaa_fbo = None
        if model is None:
            return
        dispose = getattr(model, "_dispose_renderer", None)
        if callable(dispose):
            try:
                dispose()
            except Exception:
                pass

    def closeEvent(self, event):
        self.dispose()
        super().closeEvent(event)

    def set_window_drag_callback(self, cb):
        self._window_drag_callback = cb

    def set_window_drag_lifecycle_callbacks(self, start_cb, end_cb):
        self._window_drag_start_callback = start_cb
        self._window_drag_end_callback = end_cb

    def set_click_callback(self, cb):
        self._click_callback = cb

    def set_double_click_callback(self, cb):
        self._double_click_callback = cb

    def set_right_click_callback(self, cb):
        self._right_click_callback = cb

    def set_drag_locked(self, locked: bool):
        self._finish_window_drag()
        self._drag_locked = locked
        self._drag_moved = False
        self._pressed_on_model = False

    def _finish_window_drag(self):
        was_dragging = self._dragging
        self._dragging = False
        if was_dragging and self._window_drag_end_callback:
            self._window_drag_end_callback()

    def set_head_tracking_enabled(self, enabled: bool):
        self._head_tracking_enabled = bool(enabled)
        if not self._head_tracking_enabled:
            self._last_cursor_x = -1
            self._last_cursor_y = -1
        self._sync_timer_type()

    def set_gaze_target(self, global_x: float, global_y: float):
        self._gaze_target = (global_x, global_y)
        self._sync_timer_type()

    def clear_gaze_target(self):
        self._gaze_target = None
        self._sync_timer_type()

    def set_model_path(self, model_json_path: str):
        self._pending_model = model_json_path
        self._static_render_done = False
        self._reset_hit_stability()
        if self._initialized_gl:
            self._load_model_internal(model_json_path)
            self.update()

    # --------------------------------------------------------------------------
    # Model loading
    # --------------------------------------------------------------------------

    def _load_model_internal(self, model_json_path: str):
        from lua_hit_area_projection import LuaCustomHitAreaState
        from platform_patch import set_live2d_texture_quality
        from zst_model_archive import clear_virtual_byte_cache, is_virtual_path, prefetch_virtual_model_resources
        if not model_json_path or not self._live2d:
            return
        self._safe_make_current()
        try:
            if self._custom_hit_areas is None:
                self._custom_hit_areas = LuaCustomHitAreaState()
            if is_virtual_path(model_json_path):
                clear_virtual_byte_cache()
                prefetch_virtual_model_resources(model_json_path)
                
            set_live2d_texture_quality(self._quality_profile)
            
            self._dispose_model_renderer()
            self._model = self._live2d.LAppModel()
            if is_virtual_path(model_json_path):
                try:
                    self._model.LoadModelJson(model_json_path)
                finally:
                    clear_virtual_byte_cache()
            else:
                self._model.LoadModelJson(model_json_path)
            self._render_pipeline = self._render_pipeline_for_model(self._model)
            self._render_pipeline.prepare_model(self._model)
            if self._render_ssaa_scale() <= 1 and self._ssaa_fbo is not None:
                self._ssaa_fbo.dispose()
            self._custom_hit_areas.set_scene_areas(self._prepare_custom_hit_areas(self._model))
            self._sync_model_logical_size(force=True)
            self._sync_renderer_target_size(force=True)
            self._apply_physical_viewport(self._cache_w, self._cache_h)
            
            self._model_path = model_json_path
            self._reset_render_failure_state()
            self._update_render_timer()
            self.model_loaded.emit()
        except Exception as e:
            print(f"Failed to load model: {e}", file=sys.stderr)
            self._dispose_model_renderer()
            self._model_path = ""
            if self._custom_hit_areas is not None:
                self._custom_hit_areas.clear()
            self._update_render_timer()
        finally:
            if self._pending_model == model_json_path:
                self._pending_model = ""

    def _prepare_custom_hit_areas(self, model):
        areas = model.modelSetting.getCustomHitAreas()
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

    def _update_custom_hit_area_projection(self):
        model = self._model
        if not model or self._custom_hit_areas is None or not self._custom_hit_areas.has_scene_areas():
            if self._custom_hit_areas is not None:
                self._custom_hit_areas.clear_projected()
            return
        matrix = model.matrixManager
        if not self._custom_hit_areas.project(
            matrix.screenToScene(0.0, 0.0),
            matrix.screenToScene(float(self._cache_w), 0.0),
            matrix.screenToScene(0.0, float(self._cache_h)),
            self._cache_w,
            self._cache_h,
        ):
            self._custom_hit_areas.clear_projected()

    # --------------------------------------------------------------------------
    # Render timer
    # --------------------------------------------------------------------------

    def _frame_interval_ms(self) -> int:
        return max(1, round(1000 / self._fps))

    def _sync_timer_type(self):
        timer_type = (
            Qt.TimerType.PreciseTimer
            if (
                self._fps > 75
                or self._lip_sync_level > 0.01
                or self._lip_sync_target > 0.01
                or self._head_tracking_enabled
                or self._gaze_target is not None
            )
            else Qt.TimerType.CoarseTimer
        )
        if self._render_timer.timerType() != timer_type:
            self._render_timer.setTimerType(timer_type)

    def _update_render_timer(self):
        if (
            not self._initialized_gl
            or self._static_render
            or not self._model
            or not self.isVisible()
            or self._render_failure_suspended
        ):
            self._render_timer.stop()
            return
        self._sync_timer_type()
        self._render_timer.start(self._frame_interval_ms())

    def _reset_render_failure_state(self):
        self._consecutive_draw_failures = 0
        self._render_failure_suspended = False

    def showEvent(self, event):
        super().showEvent(event)
        self._reset_render_failure_state()
        self._update_render_timer()

    def hideEvent(self, event):
        self._render_timer.stop()
        super().hideEvent(event)

    # --------------------------------------------------------------------------
    # Events
    # --------------------------------------------------------------------------

    def moveEvent(self, event):
        self._update_global_pos_cache()
        super().moveEvent(event)

    def resizeEvent(self, event):
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

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton:
            pos = event.scenePosition()
            gpos = event.globalPosition()
            interaction_trace(
                "live2d",
                "right_press",
                x=round(pos.x(), 2),
                y=round(pos.y(), 2),
                gx=round(gpos.x(), 2),
                gy=round(gpos.y(), 2),
            )
            self._right_press_handled = self._emit_right_click(pos.x(), pos.y(), gpos.x(), gpos.y())
            interaction_trace(
                "live2d",
                "right_press_result",
                handled=self._right_press_handled,
            )
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
        if self._pressed_on_model:
            event.accept()
        if self._drag_locked:
            return
            
        if self._pressed_on_model:
            self._dragging = True
            self._drag_moved = False
            gpos = event.globalPosition()
            self._drag_start_x = self._drag_origin_x = gpos.x()
            self._drag_start_y = self._drag_origin_y = gpos.y()
            if self._window_drag_start_callback:
                self._window_drag_start_callback()

    def mouseReleaseEvent(self, event):
        pos = event.scenePosition()
        x, y = pos.x(), pos.y()

        if event.button() == Qt.MouseButton.RightButton:
            if self._right_press_handled:
                self._right_press_handled = False
                event.accept()
                return
            if self._right_click_callback and self._is_model_hit_at(x, y):
                gpos = event.globalPosition()
                self._right_click_callback(int(gpos.x()), int(gpos.y()))
                event.accept()
            return

        should_click = False
        if event.button() == Qt.MouseButton.LeftButton:
            should_click = (
                self._pressed_on_model
                and not self._drag_moved
                and self._click_callback
            )
            self._pressed_on_model = False

        self._finish_window_drag()
        if should_click:
            self._click_callback(x, y, self.hit_area_name_at(x, y))
            event.accept()

    def mouseDoubleClickEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return super().mouseDoubleClickEvent(event)
        pos = event.scenePosition()
        x, y = pos.x(), pos.y()
        if self._double_click_callback and self._is_model_hit_at(x, y):
            self._pressed_on_model = False
            self._finish_window_drag()
            self._drag_moved = False
            self._double_click_callback(x, y, self.hit_area_name_at(x, y))
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def contextMenuEvent(self, event):
        if self._suppress_next_context_menu:
            self._suppress_next_context_menu = False
            interaction_trace("live2d", "context_suppressed")
            event.accept()
            return
        pos = event.pos()
        gpos = event.globalPos()
        handled = self._emit_right_click(pos.x(), pos.y(), gpos.x(), gpos.y())
        interaction_trace(
            "live2d",
            "context_menu",
            handled=handled,
            x=pos.x(),
            y=pos.y(),
            gx=gpos.x(),
            gy=gpos.y(),
        )
        if handled:
            event.accept()
            return
        super().contextMenuEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_locked or not (self._dragging and self._window_drag_callback):
            return
            
        gpos = event.globalPosition()
        if not self._drag_moved:
            total_dx = gpos.x() - self._drag_origin_x
            total_dy = gpos.y() - self._drag_origin_y
            if total_dx * total_dx + total_dy * total_dy < 16:
                return
            self._drag_moved = True
            
        dx = round(gpos.x() - self._drag_start_x)
        dy = round(gpos.y() - self._drag_start_y)
        self._drag_start_x = gpos.x()
        self._drag_start_y = gpos.y()
        if dx != 0 or dy != 0:
            self._window_drag_callback(dx, dy)

    def _track_head_at_global(self, gx: float, gy: float):
        t0 = self._perf_probe.now()
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
        self._perf_probe.add("head_track", self._perf_probe.now() - t0)

    def _track_current_head_target(self):
        if self._gaze_target is not None:
            self._track_head_at_global(*self._gaze_target)
            return
        if not self._head_tracking_enabled:
            return
        pos = QCursor.pos()
        self._track_head_at_global(pos.x(), pos.y())

    # --------------------------------------------------------------------------
    # OpenGL
    # --------------------------------------------------------------------------

    def initializeGL(self):
        from gpu_acceleration import log_opengl_renderer_once

        try:
            if self._live2d:
                self._live2d.glInit()
            gl.glDisable(gl.GL_DEPTH_TEST)
            gl.glDisable(gl.GL_DITHER)
            log_opengl_renderer_once(gl)

            self._system_scale = self._current_device_pixel_ratio()
            self._initialized_gl = True
            self._reset_render_failure_state()
            self._cache_w, self._cache_h = self.width(), self.height()
            self._cache_w_half, self._cache_h_half = self._cache_w * 0.5, self._cache_h * 0.5
            self._update_global_pos_cache()

            if self._pending_model:
                self._load_model_internal(self._pending_model)

            self._update_render_timer()
            self.update()
        except Exception as exc:
            import traceback

            print(f"Live2D OpenGL initialization failed: {exc}", file=sys.stderr, flush=True)
            traceback.print_exc(file=sys.stderr)
            self._initialized_gl = False
            self._update_render_timer()

    def resizeGL(self, w: int, h: int):
        self._system_scale = self._current_device_pixel_ratio()
        self._cache_w, self._cache_h = w, h
        self._cache_w_half, self._cache_h_half = w * 0.5, h * 0.5
        self._reset_hit_stability()
        if self._model:
            self._sync_model_logical_size()
            self._sync_renderer_target_size()
        self._apply_physical_viewport(w, h)

    def refresh_screen_scale(self):
        scale = self._current_device_pixel_ratio()
        if abs(scale - (self._system_scale or 1.0)) < 0.001:
            return
        self._system_scale = scale
        self._reset_hit_stability()
        if not self._initialized_gl:
            return
        self._safe_make_current()
        if self._model:
            # Moving between screens changes only the physical render target.
            # Reapplying the unchanged logical size can accumulate transforms in
            # some Live2D runtimes when Qt reports several DPI transitions.
            self._sync_renderer_target_size()
        self._apply_physical_viewport(self._cache_w, self._cache_h)
        self.update()

    def _apply_physical_viewport(self, w: int, h: int):
        gl.glViewport(0, 0, int(w * self._system_scale), int(h * self._system_scale))

    def _current_device_pixel_ratio(self) -> float:
        # This is the DPR of the actual QOpenGLWidget backing store. During a
        # cross-screen transition it is more authoritative than looking up a
        # screen from the window geometry.
        try:
            widget_scale = float(self.devicePixelRatioF())
            if widget_scale > 0:
                return max(1.0, widget_scale)
        except Exception:
            pass
        screen = None
        try:
            handle = self.window().windowHandle() if self.window() is not None else None
            screen = handle.screen() if handle is not None else None
        except Exception:
            screen = None
        if screen is None:
            try:
                screen = QGuiApplication.screenAt(self.mapToGlobal(self.rect().center()))
            except Exception:
                screen = None
        if screen is None:
            screen = QGuiApplication.primaryScreen()
        try:
            return max(1.0, float(screen.devicePixelRatio())) if screen is not None else 1.0
        except Exception:
            return 1.0

    def paintGL(self):
        if (
            self._render_failure_suspended
            or (self._static_render and self._static_render_done)
            or not self._live2d
            or not self._model
        ):
            return

        self._track_current_head_target()

        t0 = self._perf_probe.now()
        draw_start = 0.0
        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, self.defaultFramebufferObject())
        gl.glEnable(gl.GL_BLEND)
        gl.glBlendEquationSeparate(gl.GL_FUNC_ADD, gl.GL_FUNC_ADD)

        target_w = max(1, int(self._cache_w * self._system_scale))
        target_h = max(1, int(self._cache_h * self._system_scale))
        gl.glViewport(0, 0, target_w, target_h)
        ssaa_scale = self._render_ssaa_scale()
        using_ssaa = False
        if ssaa_scale > 1:
            if self._ssaa_fbo is None:
                self._ssaa_fbo = self._render_pipeline.create_framebuffer()
            if self._ssaa_fbo is not None:
                using_ssaa = self._ssaa_fbo.bind(target_w * ssaa_scale, target_h * ssaa_scale)

        if using_ssaa:
            gl.glViewport(0, 0, target_w * ssaa_scale, target_h * ssaa_scale)
        gl.glClearColor(*self._clear_color)
        gl.glClear(gl.GL_COLOR_BUFFER_BIT | gl.GL_STENCIL_BUFFER_BIT)

        try:
            self._apply_lip_sync()
            draw_start = self._perf_probe.now()
            self._model.Draw()
            if using_ssaa:
                self._ssaa_fbo.release()
                if not self._ssaa_fbo.blit_to_default(self.defaultFramebufferObject(), target_w, target_h, self._clear_color):
                    self._ssaa_fbo.draw_direct_to_default(
                        self._model,
                        self.defaultFramebufferObject(),
                        target_w,
                        target_h,
                        self._clear_color,
                    )
        except Exception as exc:
            if using_ssaa:
                try:
                    self._ssaa_fbo.release()
                except Exception:
                    pass
            self._consecutive_draw_failures += 1
            now = time.monotonic()
            if (
                self._consecutive_draw_failures == 1
                and now - self._last_draw_failure_log_at >= DRAW_FAILURE_LOG_INTERVAL_SECONDS
            ):
                self._last_draw_failure_log_at = now
                print(f"Live2D draw failed: {exc}", file=sys.stderr)
            if self._consecutive_draw_failures >= MAX_CONSECUTIVE_DRAW_FAILURES:
                self._render_failure_suspended = True
                self._render_timer.stop()
                print(
                    "Live2D rendering suspended after "
                    f"{self._consecutive_draw_failures} consecutive draw failures",
                    file=sys.stderr,
                )
            gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, self.defaultFramebufferObject())
            gl.glDisable(gl.GL_DEPTH_TEST)
            gl.glEnable(gl.GL_BLEND)
            gl.glBlendEquationSeparate(gl.GL_FUNC_ADD, gl.GL_FUNC_ADD)
            return
        self._consecutive_draw_failures = 0
        if self._perf_probe.enabled:
            draw_elapsed = self._perf_probe.now() - draw_start
            self._perf_probe.add("draw_py", draw_elapsed)
            self._perf_probe.add("lua_update_draw", self._model.last_lua_update_draw_seconds)
            self._perf_probe.add("lua_gc", self._model.last_lua_gc_seconds)
        if self._static_render:
            self._static_render_done = True
        if self._perf_probe.enabled:
            paint_elapsed = self._perf_probe.now() - t0
            self._perf_probe.add("paintGL", paint_elapsed)
            self._perf_probe.add("qt_gl_overhead_est", max(0.0, paint_elapsed - draw_elapsed))
            self._perf_probe.frame()

    def _apply_lip_sync(self):
        now = self._hit_clock.elapsed() if self._hit_clock.isValid() else 0
        target = self._lip_sync_target if now - self._lip_sync_last_ms <= 180 else 0.0
        form_target = self._lip_sync_form_target if now - self._lip_sync_last_ms <= 180 else 0.0
        self._lip_sync_level += (target - self._lip_sync_level) * 0.55
        self._lip_sync_form += (form_target - self._lip_sync_form) * 0.45
        if self._lip_sync_level < 0.01:
            self._lip_sync_level = 0.0
        if abs(self._lip_sync_form) < 0.01:
            self._lip_sync_form = 0.0
        self._model.SetParameterValue("PARAM_MOUTH_OPEN_Y", self._lip_sync_level, 1.0)
        self._model.SetParameterValue("PARAM_MOUTH_FORM", self._lip_sync_form, 1.0)

    # --------------------------------------------------------------------------
    # Hit testing
    # --------------------------------------------------------------------------

    def _get_valid_local_pos(self, global_pos: QPoint):
        local = self.mapFromGlobal(global_pos)
        return local if self.rect().contains(local) else None

    def is_model_hit_at_global(self, global_pos: QPoint) -> bool:
        local = self._get_valid_local_pos(global_pos)
        return self._is_model_hit_at(local.x(), local.y()) if local else False

    def is_model_opaque_at_global(self, global_pos: QPoint) -> bool:
        local = self._get_valid_local_pos(global_pos)
        return self.is_model_opaque_at_local(local.x(), local.y()) if local else False

    def is_model_opaque_at_local(self, x: float, y: float) -> bool:
        if not self._model:
            return False
        alpha = self._read_alpha_at(x, y)
        return bool(alpha is not None and alpha > self._hit_alpha_threshold)

    def hit_area_name_at(self, x: float, y: float) -> str:
        if not self._model: return ""
        return self._custom_hit_area_name_at(x, y) or self._sdk_hit_area_name_at(x, y)

    def hit_area_bounds(self, area_name: str):
        area_name = (area_name or "").strip().lower()
        if not area_name or self._custom_hit_areas is None: return None
        return self._custom_hit_areas.bounds_for(area_name)

    def hit_area_union_bounds(self):
        if self._custom_hit_areas is None: return None
        return self._custom_hit_areas.union_bounds()

    def _is_model_hit_at(self, x: float, y: float) -> bool:
        if not self._model: return False
        t0 = self._perf_probe.now()
        try:
            state = self._hit_state_at(x, y)
            now = self._hit_clock.elapsed()
            if state is True:
                self._last_confirmed_hit_ms = now
                self._last_confirmed_hit_pos = (float(x), float(y))
                return True
            last_pos = self._last_confirmed_hit_pos
            if (
                last_pos is not None
                and now - self._last_confirmed_hit_ms < HIT_STABILITY_GRACE_MS
            ):
                dx = float(x) - last_pos[0]
                dy = float(y) - last_pos[1]
                if dx * dx + dy * dy <= HIT_STABILITY_DISTANCE ** 2:
                    return True
            return False
        finally:
            self._perf_probe.add("hit_test", self._perf_probe.now() - t0)

    def _emit_right_click(self, x: float, y: float, gx: float, gy: float) -> bool:
        hit = bool(self._right_click_callback) and self._is_model_hit_at(x, y)
        interaction_trace(
            "live2d",
            "right_hit_test",
            hit=hit,
            x=round(x, 2),
            y=round(y, 2),
        )
        if hit:
            self._right_click_callback(int(gx), int(gy))
            return True
        return False

    def _hit_state_at(self, x: float, y: float) -> bool:
        alpha = self._read_alpha_at(x, y)
        return bool(alpha is not None and alpha > self._hit_alpha_threshold)

    def _has_sdk_hit_areas(self) -> bool:
        return self._model and self._model.modelSetting.getHitAreaNum() > 0

    def _sdk_hit_area_name_at(self, x: float, y: float) -> str:
        if not self._has_sdk_hit_areas(): return ""
        return (self._model.HitTest("", x, y) or "").strip().lower()

    def _custom_hit_area_name_at(self, x: float, y: float) -> str:
        if self._custom_hit_areas is None: return ""
        return self._custom_hit_areas.hit_test_name(x, y).strip().lower()

    def _reset_hit_stability(self):
        self._last_confirmed_hit_ms = -1000
        self._last_confirmed_hit_pos = None

    def _read_alpha_at(self, x: float, y: float):
        if not self._initialized_gl or not self._model:
            return None
        if not (0 <= x < self._cache_w and 0 <= y < self._cache_h):
            return None

        t0 = self._perf_probe.now()
        self._safe_make_current()
        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, self.defaultFramebufferObject())
        scale = self._system_scale or 1.0
        sx = int(x * scale)
        sy = int((self._cache_h - 1 - y) * scale)
        pixel = (ctypes.c_ubyte * 4)()
        gl.glReadPixels(sx, sy, 1, 1, gl.GL_RGBA, gl.GL_UNSIGNED_BYTE, pixel)
        self._perf_probe.add("alpha_point_sync", self._perf_probe.now() - t0)
        return int(pixel[3])
