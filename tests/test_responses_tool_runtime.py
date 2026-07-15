import json
import io
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import ANY, patch

from llm_manager import (
    LLMStreamWorker,
    ResponsesStreamWorker,
    _normalize_stream_tool_calls,
    _tool_support_is_required,
)
from local_tools import responses_tools


class ResponsesToolRuntimeTests(unittest.TestCase):
    def test_chat_tool_call_negative_index_does_not_overwrite_previous_call(self):
        worker = LLMStreamWorker("https://example.com/v1", "key", "model", [])
        worker._collect_tool_call_delta({"tool_calls": [{
            "index": 0,
            "id": "call-first",
            "function": {"name": "first", "arguments": "{}"},
        }]})
        worker._collect_tool_call_delta({"tool_calls": [{
            "index": -1,
            "id": "call-second",
            "function": {"name": "second", "arguments": "{}"},
        }]})

        self.assertEqual(
            ["first", "second"],
            [call["function"]["name"] for call in worker._stream_tool_calls],
        )

    def test_chat_tool_call_oversized_index_does_not_allocate_sparse_entries(self):
        worker = LLMStreamWorker("https://example.com/v1", "key", "model", [])
        worker._collect_tool_call_delta({"tool_calls": [{
            "index": 10000,
            "id": "call-first",
            "function": {"name": "first", "arguments": "{}"},
        }]})

        self.assertEqual(1, len(worker._stream_tool_calls))
        self.assertEqual("call-first", worker._stream_tool_calls[0]["id"])

    def test_responses_invalid_output_indexes_do_not_merge_distinct_calls(self):
        worker = ResponsesStreamWorker(
            "https://example.com/v1/responses", "key", "model", []
        )

        first = worker._function_call_target("fc-first", -1)
        second = worker._function_call_target("fc-second", -1)

        self.assertIsNot(first, second)
        self.assertEqual(2, len(worker._stream_tool_calls))

    def test_missing_tool_call_ids_are_unique_across_calls_and_rounds(self):
        calls = [
            {"function": {"name": "first", "arguments": "{}"}},
            {"function": {"name": "second", "arguments": "{}"}},
        ]

        first_round = _normalize_stream_tool_calls(calls, id_prefix="call_0_")
        second_round = _normalize_stream_tool_calls(calls, id_prefix="call_1_")

        self.assertEqual(["call_0_0", "call_0_1"], [call["id"] for call in first_round])
        self.assertEqual(["call_1_0", "call_1_1"], [call["id"] for call in second_round])
        self.assertEqual(4, len({call["id"] for call in first_round + second_round}))

    def test_provider_tool_call_id_is_preserved(self):
        calls = [{
            "id": "provider_call_id",
            "function": {"name": "first", "arguments": "{}"},
        }]

        normalized = _normalize_stream_tool_calls(calls, id_prefix="call_3_")

        self.assertEqual("provider_call_id", normalized[0]["id"])

    def test_gemini_thought_signature_is_preserved_during_normalization(self):
        calls = [{
            "id": "function-call-1",
            "function": {"name": "poke_user", "arguments": "{}"},
            "extra_content": {
                "google": {"thought_signature": "encrypted-signature"},
            },
        }]

        normalized = _normalize_stream_tool_calls(calls)

        self.assertEqual(
            "encrypted-signature",
            normalized[0]["extra_content"]["google"]["thought_signature"],
        )

    def test_gemini_stream_collects_signature_without_tool_call_index(self):
        worker = LLMStreamWorker(
            "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
            "key",
            "gemini-3.5-flash",
            [],
        )
        worker._process_line(
            'data: {"choices":[{"delta":{"tool_calls":[{'
            '"extra_content":{"google":{"thought_signature":"signature-a"}},'
            '"function":{"name":"poke_user","arguments":"{}"},'
            '"id":"function-call-1","type":"function"}]}}]}'
        )

        self.assertEqual(1, len(worker._stream_tool_calls))
        self.assertEqual(
            "signature-a",
            worker._stream_tool_calls[0]["extra_content"]["google"]["thought_signature"],
        )

    def test_gemini_signature_is_returned_with_tool_result_follow_up(self):
        first_stream = "\n".join([
            'data: {"choices":[{"delta":{"tool_calls":[{'
            '"extra_content":{"google":{"thought_signature":"signature-a"}},'
            '"function":{"name":"poke_user","arguments":"{}"},'
            '"id":"function-call-1","type":"function"}]}}]}',
            'data: {"choices":[{"delta":{},"finish_reason":"tool_calls"}]}',
            'data: [DONE]',
            "",
        ]).encode("utf-8")
        second_stream = "\n".join([
            'data: {"choices":[{"delta":{"content":"戳回来啦"}}]}',
            'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}',
            'data: [DONE]',
            "",
        ]).encode("utf-8")
        worker = LLMStreamWorker(
            "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
            "key",
            "gemini-3.5-flash",
            [{"role": "user", "content": "（你戳了戳香澄）"}],
        )
        bodies = []
        streams = iter((first_stream, second_stream))

        def fake_open(request, _timeout):
            bodies.append(json.loads(request.data.decode("utf-8")))
            return io.BytesIO(next(streams))

        worker._open_response = fake_open
        with patch(
            "llm_manager.run_local_tool_call",
            return_value={"content": "已戳了戳用户。", "extra_messages": []},
        ) as run_tool:
            worker.run()

        self.assertEqual(2, len(bodies))
        returned_call = bodies[1]["messages"][-2]["tool_calls"][0]
        self.assertEqual(
            "signature-a",
            returned_call["extra_content"]["google"]["thought_signature"],
        )
        self.assertEqual("function-call-1", bodies[1]["messages"][-1]["tool_call_id"])
        run_tool.assert_called_once()

    def test_user_facing_tool_features_require_tool_support(self):
        self.assertTrue(_tool_support_is_required(False, {}))
        self.assertTrue(_tool_support_is_required(True, {}))
        for config in (
            {"llm_web_fetch_enabled": True},
            {"llm_reminder_tools_enabled": True},
            {"llm_mcp_enabled": True},
            {"computer_use_enabled": True},
        ):
            self.assertTrue(_tool_support_is_required(False, config), config)
        self.assertTrue(_tool_support_is_required(
            False,
            {"llm_auto_continue_enabled": True},
        ))

    def test_always_available_tools_do_not_silently_fallback(self):
        worker = LLMStreamWorker(
            "https://example.com/v1",
            "key",
            "model",
            [{"role": "user", "content": "hello"}],
            tool_config={"llm_auto_continue_enabled": True},
        )
        requests = []
        errors = []

        def fake_stream_once(_messages, use_tools):
            requests.append(use_tools)
            raise urllib.error.HTTPError(
                "https://example.com/v1/chat/completions",
                400,
                "bad request",
                {},
                io.BytesIO(b'{"error":{"message":"tools unsupported"}}'),
            )

        worker._stream_once = fake_stream_once
        worker.error.connect(errors.append)
        worker.run()

        self.assertEqual([True], requests)
        self.assertEqual(1, len(errors))
        self.assertIn("不支持 Chat Completions 工具调用", errors[0])

    def test_required_tool_feature_does_not_silently_fallback(self):
        worker = LLMStreamWorker(
            "https://example.com/v1",
            "key",
            "model",
            [{"role": "user", "content": "search"}],
            tool_config={"llm_mcp_enabled": True},
        )
        requests = []
        errors = []

        def fake_stream_once(_messages, use_tools):
            requests.append(use_tools)
            raise urllib.error.HTTPError(
                "https://example.com/v1/chat/completions",
                400,
                "bad request",
                {},
                io.BytesIO(b'{"error":{"message":"tools unsupported"}}'),
            )

        worker._stream_once = fake_stream_once
        worker.error.connect(errors.append)
        worker.run()

        self.assertEqual([True], requests)
        self.assertEqual(1, len(errors))
        self.assertIn("不支持 Chat Completions 工具调用", errors[0])

    def test_responses_tools_flatten_local_function_schemas(self):
        tools = responses_tools(True, {})

        functions = {
            item.get("name"): item
            for item in tools
            if item.get("type") == "function"
        }
        self.assertIn("web_search", functions)
        self.assertIn("create_alarm", functions)
        self.assertIn("poke_user", functions)
        self.assertNotIn("function", functions["web_search"])
        self.assertEqual("object", functions["web_search"]["parameters"]["type"])

    def test_function_call_events_are_collected(self):
        worker = ResponsesStreamWorker(
            "https://api.openai.com/v1/responses",
            "key",
            "model",
            [],
        )
        worker._process_line(
            'data: {"type":"response.output_item.added","output_index":0,'
            '"item":{"id":"fc_1","call_id":"call_1","type":"function_call",'
            '"name":"web_search","arguments":""}}'
        )
        worker._process_line(
            'data: {"type":"response.function_call_arguments.delta",'
            '"item_id":"fc_1","output_index":0,"delta":"{\\"query\\":\\"news"}'
        )
        worker._process_line(
            'data: {"type":"response.function_call_arguments.delta",'
            '"item_id":"fc_1","output_index":0,"delta":"\\"}"}'
        )

        self.assertEqual(1, len(worker._stream_tool_calls))
        call = worker._stream_tool_calls[0]
        self.assertEqual("call_1", call["id"])
        self.assertEqual("web_search", call["function"]["name"])
        self.assertEqual({"query": "news"}, json.loads(call["function"]["arguments"]))

    def test_malformed_sse_json_is_not_silently_ignored(self):
        for worker in (
            LLMStreamWorker("https://example.com/v1", "key", "model", []),
            ResponsesStreamWorker("https://example.com/v1/responses", "key", "model", []),
        ):
            with self.subTest(worker=type(worker).__name__):
                with self.assertRaisesRegex(RuntimeError, "Invalid JSON"):
                    worker._process_line('data: {"broken":')

    def test_incomplete_tool_stream_is_rejected_before_execution(self):
        chat = LLMStreamWorker("https://example.com/v1", "key", "model", [])
        chat._open_response = lambda *_args: io.BytesIO(
            b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,'
            b'"function":{"name":"poke_user","arguments":"{}"}}]}}]}\n'
        )
        with self.assertRaisesRegex(RuntimeError, "completion marker"):
            chat._stream_once([], True)

        responses = ResponsesStreamWorker(
            "https://example.com/v1/responses", "key", "model", []
        )
        responses._open_response = lambda *_args: io.BytesIO(
            b'data: {"type":"response.output_item.added","output_index":0,'
            b'"item":{"id":"fc_1","call_id":"call_1",'
            b'"type":"function_call","name":"poke_user","arguments":"{}"}}\n'
        )
        with self.assertRaisesRegex(RuntimeError, "completion event"):
            responses._stream_once([], "", [], "")

    def test_tool_trace_records_arguments_results_and_failure_context(self):
        worker = LLMStreamWorker("https://example.com/v1", "key", "model", [])
        tool_call = {
            "id": "call_1",
            "function": {"name": "create_alarm", "arguments": '{"time":"08:00"}'},
        }

        worker._record_tool_call(tool_call, "alarm created")

        self.assertEqual("create_alarm", worker.tool_trace[0]["name"])
        self.assertEqual('{"time":"08:00"}', worker.tool_trace[0]["arguments"])
        self.assertEqual("alarm created", worker.tool_trace[0]["result"])
        error = worker._error_with_tool_context("follow-up failed")
        self.assertIn("create_alarm", error)
        self.assertIn("not rolled back", error)

    def test_local_function_result_is_sent_in_follow_up_response(self):
        worker = ResponsesStreamWorker(
            "https://api.openai.com/v1/responses",
            "key",
            "model",
            [{"role": "user", "content": "search"}],
            web_search=True,
        )
        requests = []

        def fake_stream_once(input_items, instructions, tools, previous_response_id=""):
            requests.append((input_items, instructions, tools, previous_response_id))
            if len(requests) == 1:
                worker._response_id = "resp_1"
                worker._stream_tool_calls = [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "web_search",
                            "arguments": '{"query":"news"}',
                        },
                    }
                ]
            else:
                worker._response_id = "resp_2"
                worker._full_text = "answer"

        worker._stream_once = fake_stream_once
        with patch(
            "llm_manager.run_local_tool_call",
            return_value={"content": "search result", "extra_messages": []},
        ) as run_tool:
            worker.run()

        self.assertEqual(2, len(requests))
        self.assertEqual("resp_1", requests[1][3])
        self.assertEqual(
            [{"type": "function_call_output", "call_id": "call_1", "output": "search result"}],
            requests[1][0],
        )
        run_tool.assert_called_once()

    def test_streamed_function_call_drives_a_second_responses_request(self):
        first_stream = "\n".join([
            'data: {"type":"response.created","response":{"id":"resp_1"}}',
            'data: {"type":"response.output_item.added","output_index":0,'
            '"item":{"id":"fc_1","call_id":"call_1","type":"function_call",'
            '"name":"web_search","arguments":""}}',
            'data: {"type":"response.function_call_arguments.done",'
            '"item_id":"fc_1","output_index":0,"name":"web_search",'
            '"arguments":"{\\"query\\":\\"news\\"}"}',
            'data: {"type":"response.completed","response":{"id":"resp_1",'
            '"output":[{"id":"fc_1","call_id":"call_1",'
            '"type":"function_call","name":"web_search",'
            '"arguments":"{\\"query\\":\\"news\\"}"}],'
            '"usage":{"input_tokens":10,"output_tokens":2,"total_tokens":12}}}',
            "",
        ]).encode("utf-8")
        second_stream = "\n".join([
            'data: {"type":"response.created","response":{"id":"resp_2"}}',
            'data: {"type":"response.output_text.delta","delta":"answer"}',
            'data: {"type":"response.completed","response":{"id":"resp_2",'
            '"output":[],"usage":{"input_tokens":4,"output_tokens":1,'
            '"total_tokens":5}}}',
            "",
        ]).encode("utf-8")
        worker = ResponsesStreamWorker(
            "https://api.openai.com/v1/responses",
            "key",
            "model",
            [{"role": "user", "content": "search"}],
            web_search=True,
        )
        bodies = []
        streams = iter((first_stream, second_stream))

        def fake_open(request, _timeout):
            bodies.append(json.loads(request.data.decode("utf-8")))
            return io.BytesIO(next(streams))

        worker._open_response = fake_open
        with patch(
            "llm_manager.run_local_tool_call",
            return_value={"content": "search result", "extra_messages": []},
        ) as run_tool:
            worker.run()

        self.assertEqual(2, len(bodies))
        self.assertNotIn("previous_response_id", bodies[0])
        self.assertEqual("resp_1", bodies[1]["previous_response_id"])
        self.assertEqual("function_call_output", bodies[1]["input"][0]["type"])
        self.assertEqual("search result", bodies[1]["input"][0]["output"])
        self.assertEqual(17, worker.token_usage["total_tokens"])
        run_tool.assert_called_once_with(
            "web_search",
            '{"query":"news"}',
            ANY,
        )

    def test_chat_surfaces_do_not_fallback_when_local_tools_are_enabled(self):
        root = Path(__file__).resolve().parents[1]
        full_chat = (root / "chat_window" / "chat_window.py").read_text(encoding="utf-8")
        compact_chat = (root / "compact_ai_window.py").read_text(encoding="utf-8")
        old_condition = (
            "self._use_responses_api(api_url) and not web_search "
            "and not web_fetch and not use_reminder_tools"
        )

        self.assertNotIn(old_condition, full_chat)
        self.assertNotIn(old_condition, compact_chat)


if __name__ == "__main__":
    unittest.main()
