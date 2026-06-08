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
    _cancel_pending_scroll_to_bottom = ChatWindow._cancel_pending_scroll_to_bottom
    _scroll_to_bottom_for_generation = ChatWindow._scroll_to_bottom_for_generation
    _finish_scroll_to_bottom_for_generation = ChatWindow._finish_scroll_to_bottom_for_generation

    def __init__(self):
        super().__init__()
        self.resize(420, 320)
        self._scroll_to_bottom_generation = 0
        self._pending_scroll_to_bottom_generation = 0

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

    def _relayout_message_bubbles(self, force=False):
        pass


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


if __name__ == "__main__":
    unittest.main()
