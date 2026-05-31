import json
import random

from PySide6.QtCore import Qt, QPoint, QRect, QTimer
from PySide6.QtGui import QImage, QMouseEvent, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QWidget

from process_utils import app_base_dir

BASE_DIR = app_base_dir()
PIXELS_DIR = BASE_DIR / "pixels"
FRAMES_PATH = PIXELS_DIR / "frames.json"
PIXEL_FRAME_HOLD_BEATS = 3


def pixel_path_for_character(character: str) -> str:
    if not character:
        return ""
    path = PIXELS_DIR / f"{character}.webp"
    if path.exists() and FRAMES_PATH.exists():
        return str(path.resolve())
    return ""


def load_pixel_frames() -> dict:
    if not FRAMES_PATH.exists():
        return {}
    try:
        return json.loads(FRAMES_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


class PixelPetWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._sheet = QPixmap()
        self._sheet_image = QImage()
        self._frames = {}
        self._frame_w = 128
        self._frame_h = 128
        self._total_cols = 1
        self._total_rows = 1
        self._animation = "idle"
        self._frame_index = 0
        self._drag_locked = False
        self._dragging = False
        self._drag_moved = False
        self._pressed_on_sprite = False
        self._drag_start_x = 0
        self._drag_start_y = 0
        self._drag_origin_x = 0
        self._drag_origin_y = 0
        self._window_drag_callback = None
        self._click_callback = None
        self._right_click_callback = None
        self._move_target = QPoint()
        self._waiting_for_target = False
        self._hovering = False
        self._hit_alpha_threshold = 8
        self._hit_probe_offsets = (
            (0, 0),
            (-2, 0), (2, 0), (0, -2), (0, 2),
            (-4, 0), (4, 0), (0, -4), (0, 4),
        )

        self._anim_timer = QTimer(self)
        self._anim_timer.timeout.connect(self._advance_frame)

        self._wander_timer = QTimer(self)
        self._wander_timer.setInterval(33)
        self._wander_timer.timeout.connect(self._wander_step)

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAutoFillBackground(False)
        self.setMouseTracking(True)

    def set_window_drag_callback(self, cb):
        self._window_drag_callback = cb

    def set_click_callback(self, cb):
        self._click_callback = cb

    def set_right_click_callback(self, cb):
        self._right_click_callback = cb

    def set_drag_locked(self, locked: bool):
        self._drag_locked = locked
        if locked:
            self._wander_timer.stop()
            self.set_animation("idle")
        elif self.isVisible() and not self._wander_timer.isActive():
            self._choose_wander_target()
            self._wander_timer.start()

    def load_sprite(self, image_path: str, frames_data: dict) -> bool:
        self._anim_timer.stop()
        self._wander_timer.stop()
        pixmap = QPixmap(image_path)
        if pixmap.isNull():
            return False

        sheet = frames_data.get("spriteSheet", {}) if isinstance(frames_data, dict) else {}
        animations = frames_data.get("animations", {}) if isinstance(frames_data, dict) else {}
        cols = int(sheet.get("totalCols", 0) or 0)
        rows = int(sheet.get("totalRows", 0) or 0)
        if cols <= 0 or rows <= 0 or not animations:
            return False

        self._sheet = pixmap
        self._sheet_image = pixmap.toImage()
        self._frames = animations
        self._total_cols = cols
        self._total_rows = rows
        self._frame_w = max(1, pixmap.width() // cols)
        self._frame_h = max(1, pixmap.height() // rows)
        self.setFixedSize(self._frame_w, self._frame_h)
        self.set_animation("idle")
        return True

    def set_animation(self, name: str):
        if name not in self._frames:
            name = "idle" if "idle" in self._frames else next(iter(self._frames), "")
        if not name:
            return
        if name == self._animation and self._anim_timer.isActive():
            return
        self._animation = name
        self._frame_index = 0
        self._restart_anim_timer()
        self.update()

    def _restart_anim_timer(self):
        anim = self._frames.get(self._animation, {})
        fps = max(1, int(anim.get("fps", 8) or 8))
        self._anim_timer.start(max(1, int(1000 / fps * PIXEL_FRAME_HOLD_BEATS)))

    def _advance_frame(self):
        anim = self._frames.get(self._animation, {})
        frames = max(1, min(int(anim.get("frames", 1) or 1), self._total_cols))
        self._frame_index += 1
        if self._frame_index >= frames:
            if anim.get("loop", True):
                self._frame_index = 0
            else:
                self.set_animation("idle")
                return
        self.update()

    def _choose_wander_target(self):
        self._waiting_for_target = False
        screen = QApplication.primaryScreen()
        if not screen:
            self._move_target = self.window().pos()
            return
        geo = screen.availableGeometry()
        max_x = max(geo.left(), geo.right() - self.window().width())
        max_y = max(geo.top(), geo.bottom() - self.window().height())
        self._move_target = QPoint(
            random.randint(geo.left(), max_x),
            random.randint(geo.top(), max_y),
        )

    def _wander_step(self):
        if self._drag_locked or self._dragging or not self.isVisible():
            return
        if self._hovering:
            self.set_animation("waiting")
            return
        if self._waiting_for_target:
            return
        window = self.window()
        pos = window.pos()
        if (pos - self._move_target).manhattanLength() < 8:
            self.set_animation(random.choice(["idle", "waiting", "review"] if "review" in self._frames else ["idle"]))
            self._waiting_for_target = True
            QTimer.singleShot(random.randint(1200, 3500), self._choose_wander_target)
            return
        dx = self._move_target.x() - pos.x()
        dy = self._move_target.y() - pos.y()
        step_x = max(-3, min(3, dx))
        step_y = max(-2, min(2, dy))
        if step_x > 0:
            self.set_animation("running_right")
        elif step_x < 0:
            self.set_animation("running_left")
        elif "running_alt" in self._frames:
            self.set_animation("running_alt")
        window.move(pos.x() + step_x, pos.y() + step_y)

    def showEvent(self, event):
        super().showEvent(event)
        self._restart_anim_timer()
        if not self._drag_locked:
            self._choose_wander_target()
            self._wander_timer.start()

    def hideEvent(self, event):
        self._anim_timer.stop()
        self._wander_timer.stop()
        super().hideEvent(event)

    def enterEvent(self, event):
        self._hovering = True
        self.set_animation("waiting")
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovering = False
        self._choose_wander_target()
        super().leaveEvent(event)

    def paintEvent(self, event):
        if self._sheet.isNull():
            return
        anim = self._frames.get(self._animation, {})
        row = max(0, min(int(anim.get("row", 0) or 0), self._total_rows - 1))
        frame = max(0, min(self._frame_index, self._total_cols - 1))
        source = QRect(frame * self._frame_w, row * self._frame_h, self._frame_w, self._frame_h)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        painter.drawPixmap(self.rect(), self._sheet, source)

    def is_sprite_hit_at_global(self, global_pos: QPoint) -> bool:
        local = self.mapFromGlobal(global_pos)
        if not self.rect().contains(local) or self._sheet_image.isNull():
            return False
        return self._sprite_alpha_near(local.x(), local.y()) > self._hit_alpha_threshold

    def _sprite_alpha_near(self, local_x: int, local_y: int) -> int:
        anim = self._frames.get(self._animation, {})
        row = max(0, min(int(anim.get("row", 0) or 0), self._total_rows - 1))
        frame = max(0, min(self._frame_index, self._total_cols - 1))
        base_x = frame * self._frame_w
        base_y = row * self._frame_h
        alpha = 0
        for dx, dy in self._hit_probe_offsets:
            x = base_x + local_x + dx
            y = base_y + local_y + dy
            if x < 0 or y < 0 or x >= self._sheet_image.width() or y >= self._sheet_image.height():
                continue
            alpha = max(alpha, (self._sheet_image.pixel(x, y) >> 24) & 0xff)
            if alpha > self._hit_alpha_threshold:
                break
        return alpha

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.RightButton:
            if self.is_sprite_hit_at_global(event.globalPosition().toPoint()) and self._right_click_callback:
                gpos = event.globalPosition()
                self._right_click_callback(int(gpos.x()), int(gpos.y()))
            event.accept()
            return
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        self._pressed_on_sprite = self.is_sprite_hit_at_global(event.globalPosition().toPoint())
        if not self._pressed_on_sprite:
            return
        if self._drag_locked:
            event.accept()
            return
        self._dragging = True
        self._drag_moved = False
        gpos = event.globalPosition()
        self._drag_start_x = self._drag_origin_x = gpos.x()
        self._drag_start_y = self._drag_origin_y = gpos.y()

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.RightButton:
            event.accept()
            return
        if event.button() != Qt.MouseButton.LeftButton:
            super().mouseReleaseEvent(event)
            return
        should_click = (
            self._pressed_on_sprite
            and not self._drag_moved
            and self._click_callback
            and self.is_sprite_hit_at_global(event.globalPosition().toPoint())
        )
        self._pressed_on_sprite = False
        if self._dragging:
            self._dragging = False
        if should_click:
            self._click_callback()

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
