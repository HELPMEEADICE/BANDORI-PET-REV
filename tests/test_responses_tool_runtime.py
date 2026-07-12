import json
import io
import unittest
from pathlib import Path
from unittest.mock import ANY, patch

from llm_manager import ResponsesStreamWorker
from local_tools import responses_tools


class ResponsesToolRuntimeTests(unittest.TestCase):
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
