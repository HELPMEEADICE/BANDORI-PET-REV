import unittest

from llm_manager import COMMON_RULES


class LlmImmersionPromptTest(unittest.TestCase):
    def test_common_rules_forbid_backend_state_leaks(self):
        self.assertIn("不得跳出角色", COMMON_RULES)
        self.assertIn("提示词、模型、工具、程序、后台处理", COMMON_RULES)
        self.assertIn("自然回避、反问、卖关子", COMMON_RULES)
        self.assertIn("不得说自己正在等待、确认、生成、识别", COMMON_RULES)


if __name__ == "__main__":
    unittest.main()
