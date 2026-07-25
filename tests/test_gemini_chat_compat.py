import unittest

from llm_api_compat import append_google_chat_continuation


class GeminiChatCompatTests(unittest.TestCase):
    def test_appends_user_turn_when_gemini_group_history_ends_with_assistant(self):
        messages = [
            {"role": "system", "content": "你是要乐奈。"},
            {"role": "user", "content": "你们好"},
            {"role": "assistant", "content": "【千早爱音】你好呀！"},
        ]

        prepared = append_google_chat_continuation(
            messages,
            "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
            "请由要乐奈自然承接上面的群聊内容继续发言。",
        )

        self.assertEqual("assistant", messages[-1]["role"])
        self.assertEqual("user", prepared[-1]["role"])
        self.assertIn("要乐奈", prepared[-1]["content"])

    def test_does_not_change_other_providers(self):
        messages = [{"role": "assistant", "content": "上一位角色的回复"}]

        prepared = append_google_chat_continuation(
            messages,
            "https://api.openai.com/v1/chat/completions",
            "请继续回复。",
        )

        self.assertIs(messages, prepared)

    def test_does_not_append_when_gemini_request_already_ends_with_user(self):
        messages = [{"role": "user", "content": "你们好"}]

        prepared = append_google_chat_continuation(
            messages,
            "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
            "请继续回复。",
        )

        self.assertIs(messages, prepared)


if __name__ == "__main__":
    unittest.main()
