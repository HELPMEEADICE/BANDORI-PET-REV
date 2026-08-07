import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtWidgets import QApplication, QWidget

from chat_window.chat_window import ChatWindow
from chat_window.widgets import ChatAttachmentDropOverlay


class _Mime:
    pass


class _DragEvent:
    def __init__(self, event_type, position=(0, 0)):
        self._event_type = event_type
        self._position = QPointF(*position)
        self.accepted = False
        self.ignored = False

    def type(self):
        return self._event_type

    def mimeData(self):
        return _Mime()

    def position(self):
        return self._position

    def acceptProposedAction(self):
        self.accepted = True

    def accept(self):
        self.accepted = True

    def ignore(self):
        self.ignored = True


class AttachmentDropOverlayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_overlay_covers_only_chat_content_and_accepts_the_final_drop(self):
        content = QWidget()
        content.resize(800, 600)
        overlay = ChatAttachmentDropOverlay(content)

        class Coordinator:
            _chat_content = content
            _attachment_drop_overlay = overlay
            _position_attachment_drop_overlay = ChatWindow._position_attachment_drop_overlay

        Coordinator()._position_attachment_drop_overlay()
        self.assertEqual((10, 10, 780, 580), overlay.geometry().getRect())
        self.assertTrue(overlay.acceptDrops())
        self.assertFalse(overlay.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents))
        self.assertTrue(overlay._title.text())

    def test_supported_drag_shows_overlay_and_drop_hides_it(self):
        content = QWidget()
        content.resize(640, 480)
        overlay = ChatAttachmentDropOverlay(content)

        class Coordinator:
            _composer_drag_active = False
            _composer_drag_leave_token = 0
            _chat_content = content
            _attachment_drop_overlay = overlay
            _composer_hint = None
            _position_attachment_drop_overlay = ChatWindow._position_attachment_drop_overlay
            _set_composer_drag_active = ChatWindow._set_composer_drag_active
            _handle_composer_drag_event = ChatWindow._handle_composer_drag_event

            def _update_composer_focus_style(self):
                pass

            def _mime_has_chat_attachments(self, mime_data):
                return True

            def _add_chat_attachments_from_mime(self, mime_data):
                return 1

        coordinator = Coordinator()
        enter = _DragEvent(QEvent.Type.DragEnter)
        self.assertTrue(coordinator._handle_composer_drag_event(enter))
        self.assertTrue(enter.accepted)
        self.assertFalse(overlay.isHidden())

        drop = _DragEvent(QEvent.Type.Drop)
        self.assertTrue(coordinator._handle_composer_drag_event(drop))
        self.assertTrue(drop.accepted)
        self.assertFalse(overlay.isVisible())

    def test_native_top_level_drop_site_tracks_only_the_right_chat_pane(self):
        class DropHost(QWidget):
            _drag_event_hits_chat_content = ChatWindow._drag_event_hits_chat_content
            dragEnterEvent = ChatWindow.dragEnterEvent
            dragMoveEvent = ChatWindow.dragMoveEvent
            dropEvent = ChatWindow.dropEvent
            _set_composer_drag_active = ChatWindow._set_composer_drag_active
            _handle_composer_drag_event = ChatWindow._handle_composer_drag_event
            _position_attachment_drop_overlay = ChatWindow._position_attachment_drop_overlay

            def __init__(self):
                super().__init__()
                self.resize(800, 600)
                self._composer_drag_active = False
                self._composer_drag_leave_token = 0
                self._chat_content = QWidget(self)
                self._chat_content.setGeometry(260, 0, 540, 600)
                self._attachment_drop_overlay = ChatAttachmentDropOverlay(self._chat_content)
                self._attachment_drop_overlay.hide()
                self.added = 0
                self.setAcceptDrops(True)

            def _update_composer_focus_style(self):
                pass

            def _mime_has_chat_attachments(self, mime_data):
                return True

            def _add_chat_attachments_from_mime(self, mime_data):
                self.added += 1
                return 1

        host = DropHost()
        host.show()
        self.app.processEvents()
        self.assertTrue(host.acceptDrops())

        host.dragEnterEvent(_DragEvent(QEvent.Type.DragEnter, (100, 100)))
        self.assertTrue(host._attachment_drop_overlay.isHidden())
        inside = _DragEvent(QEvent.Type.DragMove, (500, 100))
        host.dragMoveEvent(inside)
        self.assertTrue(inside.accepted)
        self.assertFalse(host._attachment_drop_overlay.isHidden())

        dropped = _DragEvent(QEvent.Type.Drop, (500, 100))
        host.dropEvent(dropped)
        self.assertEqual(1, host.added)
        self.assertTrue(dropped.accepted)
        self.assertTrue(host._attachment_drop_overlay.isHidden())
        host.close()


if __name__ == "__main__":
    unittest.main()
