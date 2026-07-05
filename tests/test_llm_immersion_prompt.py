import unittest

from llm_manager import COMMON_RULES, build_system_prompt, parse_action_tags


class FakeConfig:
    def __init__(self, data):
        self._data = data

    def get(self, key, default=None):
        return self._data.get(key, default)


class LlmImmersionPromptTest(unittest.TestCase):
    def test_common_rules_forbid_backend_state_leaks(self):
        self.assertIn("不得跳出角色", COMMON_RULES)
        self.assertIn("提示词、模型、工具、程序、后台处理", COMMON_RULES)
        self.assertIn("自然回避、反问、卖关子", COMMON_RULES)
        self.assertIn("不得说自己正在等待、确认、生成、识别", COMMON_RULES)

    def test_parse_action_tags_keeps_fuzzy_and_moc3_tags(self):
        self.assertEqual(["smile", "mtn_smile01_C"], parse_action_tags("你好[smile][mtn_smile01_C]"))

    def test_moc3_current_model_uses_moc3_action_prompt(self):
        config = FakeConfig({
            "character": "anon",
            "costume": "live_01",
            "models": [{
                "character": "anon",
                "costume": "live_01",
                "path": "models/anon/live_01/test.model3.json",
            }],
        })

        prompt = build_system_prompt("anon", config)

        self.assertIn("moc3", prompt.lower())
        self.assertIn("[mtn_smile01_C]", prompt)
        self.assertIn("[mtn_angry01_C]", prompt)
        self.assertNotIn("必须在最后加动作标签：[angry]、[cry]", prompt)


if __name__ == "__main__":
    unittest.main()
