import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from chat_window.widgets import SlidingStatusLabel
from chat_window.chat_window import ChatWindow


class SlidingStatusLabelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_notice_and_restore_both_push_upward(self):
        label = SlidingStatusLabel("就绪")
        label.resize(320, 18)
        label.show()

        label.slide_to("当前会话临时背景已启用。", duration=40)
        self.assertTrue(label._sliding)
        self.assertLess(label._animation.endValue().y(), 0)
        QTest.qWait(70)
        self.assertEqual("当前会话临时背景已启用。", label.text())
        self.assertEqual(0, label._track.y())

        label.slide_to("就绪", duration=40)
        self.assertTrue(label._sliding)
        self.assertLess(label._animation.endValue().y(), 0)
        QTest.qWait(70)
        self.assertEqual("就绪", label.text())
        self.assertEqual(0, label._track.y())
        label.close()

    def test_immediate_status_change_cancels_an_in_progress_slide(self):
        label = SlidingStatusLabel("就绪")
        label.resize(320, 18)
        label.slide_to("临时提示", duration=500)
        label.setText("正在回复")
        self.assertFalse(label._sliding)
        self.assertEqual("正在回复", label.text())
        self.assertEqual(0, label._track.y())

    def test_temporary_background_notice_uses_five_second_restore_timer(self):
        class Coordinator(QObject):
            _show_temporary_background_notice = ChatWindow._show_temporary_background_notice
            _restore_temporary_background_notice = ChatWindow._restore_temporary_background_notice

            def __init__(self):
                super().__init__()
                self._composer_hint = SlidingStatusLabel("就绪")
                self._composer_hint.resize(320, 18)
                self._temporary_background_notice_text = ""
                self._temporary_background_notice_timer = QTimer(self)
                self._temporary_background_notice_timer.setSingleShot(True)
                self._temporary_background_notice_timer.timeout.connect(
                    self._restore_temporary_background_notice
                )

            def _idle_status_text(self):
                return "就绪"

        coordinator = Coordinator()
        coordinator._show_temporary_background_notice("临时背景已关闭。")
        self.assertTrue(coordinator._temporary_background_notice_timer.isActive())
        self.assertEqual(5000, coordinator._temporary_background_notice_timer.interval())
        QTest.qWait(260)
        self.assertEqual("临时背景已关闭。", coordinator._composer_hint.text())
        coordinator._temporary_background_notice_timer.stop()
        coordinator._restore_temporary_background_notice()
        QTest.qWait(260)
        self.assertEqual("就绪", coordinator._composer_hint.text())


if __name__ == "__main__":
    unittest.main()
