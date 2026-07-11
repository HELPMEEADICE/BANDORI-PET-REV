import unittest
from unittest.mock import patch

from chat_commands import handle_command
from reminder_core import ALARM_CONFIG_KEY, POMODORO_CONFIG_KEY


class _ConfigStub:
    def __init__(self, data=None, save_result=True):
        self.data = dict(data or {})
        self.save_result = save_result

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        self.data[key] = value

    def save(self):
        return self.save_result


class ChatCommandSaveSemanticsTests(unittest.TestCase):
    def test_toggle_save_false_restores_value_and_does_not_publish(self):
        cfg = _ConfigStub({"llm_show_reasoning": True}, save_result=False)

        with patch("chat_commands._publish") as publish:
            result = handle_command(cfg, "@cot off")

        self.assertTrue(cfg.get("llm_show_reasoning"))
        publish.assert_not_called()
        self.assertTrue(result.get("save_failed"))

    def test_pomodoro_save_false_restores_lists_and_does_not_publish(self):
        alarms = [{"id": "existing-alarm"}]
        pomodoros = [{"id": "existing-pomodoro"}]
        cfg = _ConfigStub({
            ALARM_CONFIG_KEY: alarms,
            POMODORO_CONFIG_KEY: pomodoros,
        }, save_result=False)

        with patch("chat_commands._publish") as publish:
            result = handle_command(cfg, "@pomodoro 2 focus")

        self.assertEqual(alarms, cfg.get(ALARM_CONFIG_KEY))
        self.assertEqual(pomodoros, cfg.get(POMODORO_CONFIG_KEY))
        publish.assert_not_called()
        self.assertTrue(result.get("save_failed"))


if __name__ == "__main__":
    unittest.main()
