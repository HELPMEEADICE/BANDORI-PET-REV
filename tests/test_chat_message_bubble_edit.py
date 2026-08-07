import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from chat_window.message_bubble import MessageBubble
from chat_window.chat_window import ChatWindow


class MessageBubbleEditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_saved_message_exposes_actions_and_inline_edit_controls(self):
        bubble = MessageBubble("original", "user", message_id=7)
        self.assertEqual(3, len(bubble._message_context_actions()))
        saved = []
        bubble.edit_saved.connect(lambda source, text: saved.append((source.message_id(), text)))

        bubble.start_edit()
        self.assertTrue(bubble._editing)
        bubble._edit_text.setPlainText("edited")
        bubble._confirm_edit()
        self.assertEqual([(7, "edited")], saved)

        bubble.finish_edit("edited")
        self.assertFalse(bubble._editing)
        self.assertEqual("edited", bubble._label.text())

    def test_unsaved_or_streaming_message_has_no_mutation_actions(self):
        bubble = MessageBubble("draft", "assistant")
        self.assertEqual([], bubble._message_context_actions())
        bubble.set_message_id(8)
        bubble.set_streaming(True)
        self.assertEqual([], bubble._message_context_actions())

    def test_starting_another_editor_cancels_and_restores_the_previous_one(self):
        class EditCoordinator:
            _active_edit_bubble = None
            _on_message_edit_started = ChatWindow._on_message_edit_started
            _on_message_edit_closed = ChatWindow._on_message_edit_closed

        coordinator = EditCoordinator()
        first = MessageBubble("first original", "user", message_id=1)
        second = MessageBubble("second original", "assistant", message_id=2)
        for bubble in (first, second):
            bubble.edit_started.connect(coordinator._on_message_edit_started)
            bubble.edit_closed.connect(coordinator._on_message_edit_closed)

        first.start_edit()
        first._edit_text.setPlainText("unsaved change")
        second.start_edit()

        self.assertFalse(first._editing)
        self.assertEqual("first original", first._label.text())
        self.assertTrue(second._editing)
        self.assertIs(second, coordinator._active_edit_bubble)


if __name__ == "__main__":
    unittest.main()
