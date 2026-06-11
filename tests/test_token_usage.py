import os
import tempfile
import unittest

from chat_commands import handle_command
from database_manager import DatabaseManager
from llm_manager import LLMStreamWorker, ResponsesStreamWorker
from token_usage import (
    estimate_messages_tokens,
    estimate_untracked_history_usage,
    history_message_limit_from_slider,
    history_message_limit_to_slider,
    history_message_query_limit,
    merge_token_usage,
    normalize_history_message_limit,
    normalize_token_usage,
)


class TokenUsageTests(unittest.TestCase):
    def test_history_message_limit_is_clamped(self):
        self.assertEqual(normalize_history_message_limit(None, 40), 40)
        self.assertEqual(normalize_history_message_limit(1, 40), 2)
        self.assertEqual(normalize_history_message_limit(120, 40), 100)
        self.assertEqual(normalize_history_message_limit(0, 40), 0)
        self.assertEqual(history_message_limit_to_slider(0, 40), 101)
        self.assertEqual(history_message_limit_from_slider(101), 0)
        self.assertIsNone(history_message_query_limit(0, 40))

    def test_normalizes_both_api_usage_shapes(self):
        chat = normalize_token_usage({
            "prompt_tokens": 120,
            "completion_tokens": 30,
            "total_tokens": 150,
        })
        responses = normalize_token_usage({
            "input_tokens": 80,
            "output_tokens": 20,
            "total_tokens": 100,
        })

        self.assertEqual(chat["input_tokens"], 120)
        self.assertEqual(chat["output_tokens"], 30)
        self.assertEqual(responses["input_tokens"], 80)
        self.assertEqual(responses["output_tokens"], 20)

    def test_merges_exact_and_estimated_usage(self):
        merged = merge_token_usage(
            {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120},
            {"input_tokens": 50, "output_tokens": 10, "estimated": True},
        )

        self.assertEqual(merged["total_tokens"], 180)
        self.assertTrue(merged["estimated"])

    def test_message_estimate_grows_with_context(self):
        short = estimate_messages_tokens([{"role": "user", "content": "你好"}])
        long = estimate_messages_tokens([
            {"role": "system", "content": "你是一个助手。"},
            {"role": "user", "content": "请详细解释这个问题，并给出三个例子。"},
        ])

        self.assertGreater(long, short)

    def test_reconstructs_untracked_history_with_rolling_context(self):
        messages = [
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "answer one", "tool_trace_json": ""},
            {"role": "user", "content": "second"},
            {"role": "assistant", "content": "answer two", "tool_trace_json": ""},
        ]

        usage = estimate_untracked_history_usage(
            messages,
            input_overhead=100,
            history_limit=3,
        )

        self.assertEqual(usage["request_count"], 2)
        self.assertGreater(usage["input_tokens"], 200)
        self.assertGreater(usage["output_tokens"], 0)
        self.assertTrue(usage["estimated"])

    def test_reconstruction_skips_replies_with_recorded_usage(self):
        messages = [
            {"role": "user", "content": "first"},
            {
                "role": "assistant",
                "content": "tracked",
                "tool_trace": {"llm_usage": {"total_tokens": 10}},
            },
            {"role": "user", "content": "second"},
            {"role": "assistant", "content": "legacy"},
        ]

        usage = estimate_untracked_history_usage(
            messages,
            input_overhead=100,
            history_limit=3,
        )

        self.assertEqual(usage["request_count"], 1)

    def test_database_aggregates_current_conversation_usage(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db = DatabaseManager(os.path.join(temp_dir, "usage.db"))
            conversation_id = db.create_conversation("test")
            db.add_message(conversation_id, "assistant", "one", tool_trace={
                "llm_usage": {
                    "input_tokens": 100,
                    "output_tokens": 25,
                    "total_tokens": 125,
                    "estimated": False,
                }
            })
            db.add_message(conversation_id, "assistant", "two", tool_trace={
                "llm_usage": {
                    "input_tokens": 150,
                    "output_tokens": 40,
                    "total_tokens": 190,
                    "estimated": True,
                }
            })
            db.add_message(conversation_id, "assistant", "legacy")

            usage = db.get_conversation_token_usage(conversation_id)
            db.close()

        self.assertEqual(usage["input_tokens"], 250)
        self.assertEqual(usage["output_tokens"], 65)
        self.assertEqual(usage["total_tokens"], 315)
        self.assertEqual(usage["request_count"], 2)
        self.assertEqual(usage["untracked_count"], 1)
        self.assertTrue(usage["estimated"])

    def test_tokens_command_uses_resolver(self):
        result = handle_command(
            object(),
            "@tokens",
            token_usage_resolver=lambda: {
                "input_tokens": 1200,
                "output_tokens": 300,
                "total_tokens": 1500,
                "next_input_tokens": 1350,
                "request_count": 2,
                "untracked_count": 1,
                "estimated": True,
                "message_count": 46,
                "next_history_message_count": 46,
                "history_message_limit": 0,
                "next_history_tokens": 350,
                "next_context_tokens": 1000,
            },
            publish=False,
        )

        self.assertIsNotNone(result)
        self.assertIn("1,500", result["message"])
        self.assertIn("1,350", result["message"])
        self.assertIn("350", result["message"])
        self.assertIn("1,000", result["message"])
        self.assertIn("46", result["message"])
        self.assertTrue(
            any(
                label in result["message"]
                for label in ("不限", "Unlimited", "無制限")
            )
        )

    def test_chat_stream_worker_reads_usage_chunk(self):
        worker = LLMStreamWorker("https://example.com/v1", "key", "model", [])
        worker._process_line(
            'data: {"choices":[],"usage":{"prompt_tokens":12,'
            '"completion_tokens":3,"total_tokens":15}}'
        )
        worker._usage = merge_token_usage(worker._usage, worker._round_usage)

        self.assertEqual(worker.token_usage["total_tokens"], 15)

    def test_responses_worker_reads_completed_usage(self):
        worker = ResponsesStreamWorker(
            "https://api.openai.com/v1/responses",
            "key",
            "model",
            [],
        )
        worker._process_line(
            'data: {"type":"response.completed","response":{"usage":'
            '{"input_tokens":20,"output_tokens":5,"total_tokens":25}}}'
        )

        self.assertEqual(worker.token_usage["input_tokens"], 20)


if __name__ == "__main__":
    unittest.main()
