import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

from chat_window.chat_window import ChatWindow


class _InputStub:
    def __init__(self):
        self.text = ""
        self.focused = False

    def setPlainText(self, text):
        self.text = text

    def textCursor(self):
        return SimpleNamespace(movePosition=lambda *_args, **_kwargs: None)

    def setTextCursor(self, _cursor):
        pass

    def setFocus(self):
        self.focused = True


class _HintStub:
    def __init__(self):
        self.text = ""

    def setText(self, text):
        self.text = text


class _BubbleStub(QWidget):
    def __init__(self):
        super().__init__()
        self.deleted = False

    def deleteLater(self):
        self.deleted = True
        super().deleteLater()


class _SaveFailureHarness(QWidget):
    _handle_user_message_save_failed = ChatWindow._handle_user_message_save_failed
    _handle_assistant_message_save_failed = ChatWindow._handle_assistant_message_save_failed
    _cleanup_unsent_pending_attachments = ChatWindow._cleanup_unsent_pending_attachments
    _delete_pending_attachment_copy = ChatWindow._delete_pending_attachment_copy
    _restore_unsaved_user_draft = ChatWindow._restore_unsaved_user_draft

    def __init__(self, attachment_root=None):
        super().__init__()
        self._input = _InputStub()
        self._composer_hint = _HintStub()
        self._pending_attachments = []
        self._pending_vision_send = None
        self._last_user_message_id = 1
        self._last_group_user_message_id = 2
        self._last_user_text = "old"
        self._pending_interaction_context = "context"
        self._raw_image_inline_message_id = 3
        self._raw_image_inline_group_message_id = 4
        self._response_save_error_message = ""
        self._attachment_root = Path(attachment_root) if attachment_root else None
        self.busy_values = []
        self.refreshed_previews = 0
        self.updated_hints = 0
        self.hidden_dividers = 0
        self.group_refreshes = 0
        layout = QVBoxLayout(self)
        layout.addStretch()
        self._msg_layout = layout

    def _hide_plan_divider(self):
        self.hidden_dividers += 1

    def _remove_message_bubble(self, bubble):
        ChatWindow._remove_message_bubble(self, bubble)

    def _clear_raw_image_inline_state(self):
        self._raw_image_inline_message_id = None
        self._raw_image_inline_group_message_id = None

    def _set_busy(self, busy, planning=False):
        self.busy_values.append((busy, planning))

    def _refresh_attachment_previews(self):
        self.refreshed_previews += 1

    def _update_attachment_hint(self):
        self.updated_hints += 1

    def _relayout_message_bubbles(self, force=False):
        pass

    def _refresh_group_list(self):
        self.group_refreshes += 1

    def _chat_attachment_dir(self):
        return self._attachment_root


class ChatWindowSaveFailureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_user_message_save_failure_restores_draft_and_removes_visible_bubble(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            attachment = {"path": str(Path(temp_dir) / "pending.png"), "type": "image"}
            harness = _SaveFailureHarness(temp_dir)
            bubble = _BubbleStub()
            harness._msg_layout.insertWidget(0, bubble)

            harness._handle_user_message_save_failed(RuntimeError("disk full"), "hello", [attachment], bubble)

            self.assertEqual("hello", harness._input.text)
            self.assertEqual([attachment], harness._pending_attachments)
            self.assertIsNone(harness._last_user_message_id)
            self.assertIsNone(harness._last_group_user_message_id)
            self.assertEqual("", harness._last_user_text)
            self.assertEqual("", harness._pending_interaction_context)
            self.assertIsNone(harness._raw_image_inline_message_id)
            self.assertIsNone(harness._raw_image_inline_group_message_id)
            self.assertIn((False, False), harness.busy_values)
            self.assertIn("disk full", harness._composer_hint.text)
            self.assertTrue(bubble.deleted)

    def test_assistant_message_save_failure_preserves_visible_reply_hint(self):
        harness = _SaveFailureHarness()

        harness._handle_assistant_message_save_failed(RuntimeError("readonly"))

        self.assertIn("readonly", harness._response_save_error_message)
        self.assertEqual(harness._response_save_error_message, harness._composer_hint.text)
        self.assertEqual(1, harness.group_refreshes)

    def test_cleanup_unsent_pending_attachments_deletes_only_local_pending_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first = root / "first.png"
            second = root / "second.png"
            outside = root.parent / f"{root.name}-outside.png"
            first.write_bytes(b"first")
            second.write_bytes(b"second")
            outside.write_bytes(b"outside")
            try:
                harness = _SaveFailureHarness(root)
                harness._pending_attachments = [{"path": str(first)}, {"path": str(outside)}]
                harness._pending_vision_send = ("text", [{"path": str(second)}], None)

                harness._cleanup_unsent_pending_attachments()

                self.assertFalse(first.exists())
                self.assertFalse(second.exists())
                self.assertTrue(outside.exists())
                self.assertEqual([], harness._pending_attachments)
                self.assertIsNone(harness._pending_vision_send)
            finally:
                if outside.exists():
                    outside.unlink()

    def test_cleanup_extra_attachments_does_not_clear_current_pending_when_requested(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            current = root / "current.png"
            extra = root / "extra.png"
            current.write_bytes(b"current")
            extra.write_bytes(b"extra")
            harness = _SaveFailureHarness(root)
            harness._pending_attachments = [{"path": str(current)}]

            harness._cleanup_unsent_pending_attachments(
                [{"path": str(extra)}],
                include_current=False,
                include_vision_pending=False,
            )

            self.assertTrue(current.exists())
            self.assertFalse(extra.exists())
            self.assertEqual([{"path": str(current)}], harness._pending_attachments)


if __name__ == "__main__":
    unittest.main()
