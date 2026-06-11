import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QScrollArea, QVBoxLayout, QWidget

from chat_window.chat_window import ChatWindow


class ChatScrollHarness(QWidget):
    _scroll_to_bottom = ChatWindow._scroll_to_bottom
    _schedule_scroll_to_bottom_after_load = ChatWindow._schedule_scroll_to_bottom_after_load
    _on_message_scroll_range_changed = ChatWindow._on_message_scroll_range_changed
    _on_message_scroll_value_changed = ChatWindow._on_message_scroll_value_changed
    _cancel_pending_scroll_to_bottom = ChatWindow._cancel_pending_scroll_to_bottom
    _scroll_to_bottom_for_stream = ChatWindow._scroll_to_bottom_for_stream
    _pause_stream_output_follow = ChatWindow._pause_stream_output_follow
    _scroll_to_bottom_for_generation = ChatWindow._scroll_to_bottom_for_generation
    _finish_scroll_to_bottom_for_generation = ChatWindow._finish_scroll_to_bottom_for_generation

    def __init__(self):
        super().__init__()
        self.resize(420, 320)
        self._scroll_to_bottom_generation = 0
        self._pending_scroll_to_bottom_generation = 0
        self._follow_stream_output = True
        self._current_bubble = object()
        self._history_pagination_ready = False
        self._history_loading = False

        layout = QVBoxLayout(self)
        self._scroll = QScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._msg_area = QWidget(self._scroll)
        self._msg_area.setMinimumHeight(1800)
        self._scroll.setWidget(self._msg_area)
        layout.addWidget(self._scroll)

        scrollbar = self._scroll.verticalScrollBar()
        scrollbar.rangeChanged.connect(self._on_message_scroll_range_changed)
        scrollbar.actionTriggered.connect(self._cancel_pending_scroll_to_bottom)
        scrollbar.valueChanged.connect(self._on_message_scroll_value_changed)
        scrollbar.sliderPressed.connect(self._pause_stream_output_follow)

    def _relayout_message_bubbles(self, force=False):
        pass

    def _load_older_messages(self):
        return False


class ChatScrollPositionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_loaded_chat_stays_at_bottom_when_layout_grows_late(self):
        harness = ChatScrollHarness()
        harness.show()
        QTest.qWait(50)

        harness._schedule_scroll_to_bottom_after_load()
        QTest.qWait(1300)
        harness._msg_area.setMinimumHeight(2600)
        harness._msg_area.updateGeometry()
        QTest.qWait(100)

        scrollbar = harness._scroll.verticalScrollBar()
        self.assertGreater(scrollbar.maximum(), 0)
        self.assertEqual(scrollbar.maximum(), scrollbar.value())

        harness.close()

    def test_user_scroll_cancels_pending_bottom_tracking(self):
        harness = ChatScrollHarness()
        harness.show()
        QTest.qWait(50)

        harness._schedule_scroll_to_bottom_after_load()
        QTest.qWait(100)
        scrollbar = harness._scroll.verticalScrollBar()
        scrollbar.setValue(scrollbar.minimum())
        harness._cancel_pending_scroll_to_bottom()
        harness._msg_area.setMinimumHeight(2600)
        harness._msg_area.updateGeometry()
        QTest.qWait(100)

        self.assertLess(scrollbar.value(), scrollbar.maximum())

        harness.close()

    def test_stream_growth_does_not_override_user_scroll_position(self):
        harness = ChatScrollHarness()
        harness.show()
        QTest.qWait(50)

        scrollbar = harness._scroll.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
        harness._scroll_to_bottom_for_stream()
        scrollbar.setValue(scrollbar.maximum() - 1)
        user_position = scrollbar.value()

        harness._msg_area.setMinimumHeight(2600)
        harness._msg_area.updateGeometry()
        QTest.qWait(100)

        self.assertFalse(harness._follow_stream_output)
        self.assertEqual(user_position, scrollbar.value())
        self.assertLess(scrollbar.value(), scrollbar.maximum())

        harness.close()

    def test_stream_growth_follows_again_after_user_returns_to_bottom(self):
        harness = ChatScrollHarness()
        harness.show()
        QTest.qWait(50)

        scrollbar = harness._scroll.verticalScrollBar()
        scrollbar.setValue(scrollbar.minimum() + 200)
        self.assertFalse(harness._follow_stream_output)
        scrollbar.setValue(scrollbar.maximum())
        self.assertTrue(harness._follow_stream_output)

        harness._msg_area.setMinimumHeight(2600)
        harness._msg_area.updateGeometry()
        QTest.qWait(100)

        self.assertEqual(scrollbar.maximum(), scrollbar.value())

        harness.close()


if __name__ == "__main__":
    unittest.main()
