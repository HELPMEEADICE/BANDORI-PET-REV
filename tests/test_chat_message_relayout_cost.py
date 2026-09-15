import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget

from chat_window.chat_window import ChatWindow
from chat_window.message_bubble import MessageBubble


class _ViewportStub:
    def __init__(self, width: int):
        self._width = width

    def width(self) -> int:
        return self._width


class _ScrollStub:
    """Just enough scroll area for ``ChatWindow._relayout_message_bubbles``."""

    def __init__(self, width: int):
        self._viewport = _ViewportStub(width)

    def viewport(self) -> _ViewportStub:
        return self._viewport


class MessageRelayoutHarness(QWidget):
    _relayout_message_bubbles = ChatWindow._relayout_message_bubbles
    _message_bubbles = ChatWindow._message_bubbles

    def __init__(self, viewport_width: int = 420):
        super().__init__()
        self._group_sidebar_animating = False
        self._scroll = _ScrollStub(viewport_width)
        self.bubbles: list[MessageBubble] = []
        self.measure_calls: list[MessageBubble] = []

        layout = QVBoxLayout(self)
        self._msg_area = QWidget(self)
        self._msg_layout = QVBoxLayout(self._msg_area)
        self._msg_layout.addStretch()
        layout.addWidget(self._msg_area)

    def set_viewport_width(self, width: int):
        self._scroll.viewport()._width = int(width)

    def add_bubble(self, text: str) -> MessageBubble:
        bubble = MessageBubble(text, "assistant")
        original = MessageBubble.update_bubble_width

        def counting_update(viewport_width=0):
            self.measure_calls.append(bubble)
            return original(bubble, viewport_width)

        bubble.update_bubble_width = counting_update
        self.bubbles.append(bubble)
        self._msg_layout.insertWidget(self._msg_layout.count() - 1, bubble)
        return bubble


class MessageRelayoutCostTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _measured_harness(self, count: int) -> MessageRelayoutHarness:
        """A harness whose bubbles all have an up-to-date layout."""
        harness = MessageRelayoutHarness()
        for index in range(count):
            harness.add_bubble("message %d" % index)
        harness._relayout_message_bubbles()
        self.assertEqual(count, len(harness.measure_calls))
        harness.measure_calls.clear()
        return harness

    def test_repeated_relayout_skips_bubbles_that_are_still_valid(self):
        harness = self._measured_harness(4)

        harness._relayout_message_bubbles()
        harness._relayout_message_bubbles()

        self.assertEqual([], harness.measure_calls)

    def test_inserting_a_message_only_measures_the_new_bubble(self):
        harness = self._measured_harness(3)

        newest = harness.add_bubble("brand new message")
        harness._relayout_message_bubbles()

        self.assertEqual([newest], harness.measure_calls)

    def test_viewport_width_change_measures_every_bubble(self):
        harness = self._measured_harness(3)

        harness.set_viewport_width(560)
        harness._relayout_message_bubbles()

        self.assertEqual(3, len(harness.measure_calls))

    def test_forced_relayout_measures_every_bubble(self):
        harness = self._measured_harness(3)

        harness._relayout_message_bubbles(force=True)

        self.assertEqual(3, len(harness.measure_calls))

    def test_font_change_invalidates_the_measured_layout(self):
        harness = self._measured_harness(1)
        bubble = harness.bubbles[0]
        font = bubble._label.font()
        font.setPointSize(font.pointSize() + 6)
        bubble._label.setFont(font)

        harness._relayout_message_bubbles()

        self.assertEqual([bubble], harness.measure_calls)


if __name__ == "__main__":
    unittest.main()
