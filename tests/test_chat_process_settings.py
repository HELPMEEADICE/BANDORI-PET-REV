import unittest

import chat_process


class _WindowStub:
    def __init__(self):
        self.payloads = []

    def apply_runtime_settings(self, payload):
        self.payloads.append(payload)


class ChatProcessSettingsTests(unittest.TestCase):
    def test_settings_line_is_forwarded_to_chat_window(self):
        window = _WindowStub()

        handled = chat_process._apply_settings_line(
            window,
            'SETTINGS\t{"llm_web_search_enabled": true}',
        )

        self.assertTrue(handled)
        self.assertEqual([{"llm_web_search_enabled": True}], window.payloads)

    def test_invalid_settings_line_is_ignored(self):
        window = _WindowStub()

        handled = chat_process._apply_settings_line(window, "SETTINGS\t{")

        self.assertFalse(handled)
        self.assertFalse(window.payloads)


if __name__ == "__main__":
    unittest.main()
