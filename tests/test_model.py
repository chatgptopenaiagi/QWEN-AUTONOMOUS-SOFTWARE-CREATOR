"""Adapter contract tests with an HTTP fixture, never the user's live model."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import unittest
from unittest.mock import patch
from urllib.error import URLError

from qasc.model import ModelAdapter, ModelError, OpenAICompatibleAdapter, parse_json_response


class ModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                self.send_fixture()

            def do_POST(self):
                content = self.rfile.read(int(self.headers["Content-Length"]))
                cls.requests.append((self.path, json.loads(content)))
                self.send_fixture()

            def send_fixture(self):
                status, body = cls.routes.get(self.path, (404, {"error": "missing"}))
                encoded = body if isinstance(body, bytes) else json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def setUp(self):
        self.__class__.requests = []
        self.__class__.routes = {
            "/health": (200, {"status": "ok"}),
            "/v1/models": (200, {"data": [{"id": "local-test-model"}]}),
            "/props": (200, {"default_generation_settings": {"n_ctx": 16384}}),
            "/v1/chat/completions": (200, {
                "model": "local-test-model",
                "choices": [{"finish_reason": "stop", "message": {"content": '{"files": []}'}}],
                "usage": {"prompt_tokens": 20, "completion_tokens": 8, "total_tokens": 28},
                "timings": {"predicted_per_second": 12.5},
            }),
        }
        self.adapter = OpenAICompatibleAdapter(self.base_url, timeout=2)

    def test_info_reports_real_response_fields(self):
        result = self.adapter.info()
        self.assertTrue(result["available"])
        self.assertEqual(result["model_ids"], ["local-test-model"])
        self.assertEqual(result["context_size"], 16384)
        self.assertEqual(result["errors"], {})
        self.assertIsInstance(self.adapter, ModelAdapter)

    def test_optional_routes_not_required_for_generic_server(self):
        del self.routes["/props"]
        del self.routes["/health"]
        result = self.adapter.info()
        self.assertTrue(result["available"])
        self.assertIsNone(result["context_size"])
        self.assertIn("/props", result["errors"])

    def test_loading_server_is_unavailable(self):
        self.routes["/health"] = (503, {"error": {"message": "Loading model"}})
        self.assertFalse(self.adapter.info()["available"])

    def test_unknown_configured_model_is_unavailable(self):
        adapter = OpenAICompatibleAdapter(self.base_url, model="not-loaded")
        self.assertFalse(adapter.info()["available"])

    def test_explicit_context_and_v1_url(self):
        adapter = OpenAICompatibleAdapter(self.base_url + "/v1/", context_size=4096)
        self.assertEqual(adapter.info()["context_size"], 4096)

    def test_generation_sends_schema_and_preserves_receipt(self):
        schema = {"type": "object", "properties": {"files": {"type": "array"}}}
        generation = self.adapter.generate([{"role": "user", "content": "write code"}], schema)
        self.assertEqual(parse_json_response(generation.content), {"files": []})
        self.assertEqual(generation.usage["total_tokens"], 28)
        self.assertEqual(generation.timings["predicted_per_second"], 12.5)
        self.assertGreaterEqual(generation.timings["request_seconds"], 0)
        self.assertEqual(self.requests[0][0], "/v1/chat/completions")
        self.assertEqual(self.requests[0][1]["response_format"], {"type": "json_object", "schema": schema})
        self.assertFalse(self.requests[0][1]["stream"])

    def test_truncation_is_error_and_retains_raw_response(self):
        self.routes["/v1/chat/completions"][1]["choices"][0]["finish_reason"] = "length"
        with self.assertRaisesRegex(ModelError, "incomplete") as caught:
            self.adapter.generate([{"role": "user", "content": "write code"}])
        self.assertEqual(caught.exception.raw["choices"][0]["finish_reason"], "length")

    def test_tool_request_is_returned_never_executed(self):
        calls = [{"id": "1", "type": "function", "function": {"name": "do_something", "arguments": "{}"}}]
        self.routes["/v1/chat/completions"] = (200, {"choices": [{"finish_reason": "tool_calls", "message": {"content": None, "tool_calls": calls}}]})
        generation = self.adapter.generate([{"role": "user", "content": "tools"}])
        self.assertEqual(generation.tool_calls, calls)
        self.assertEqual(generation.content, "")

    def test_http_failure_is_actionable(self):
        self.routes["/v1/chat/completions"] = (400, {"error": "bad schema"})
        with self.assertRaisesRegex(ModelError, "HTTP 400.*bad schema"):
            self.adapter.generate([{"role": "user", "content": "write code"}])

    def test_invalid_and_empty_completion_protocol(self):
        for body in (b"this is not JSON", [], {}, {"choices": []}, {"choices": [{"message": {"content": ""}}]}):
            with self.subTest(body=body):
                self.routes["/v1/chat/completions"] = (200, body)
                with self.assertRaises(ModelError):
                    self.adapter.generate([{"role": "user", "content": "write code"}])

    def test_no_models_is_error(self):
        self.routes["/v1/models"] = (200, {"data": []})
        with self.assertRaisesRegex(ModelError, "did not advertise"):
            self.adapter.generate([{"role": "user", "content": "write code"}])
        self.assertEqual(self.requests, [])

    def test_unreachable_server_info_and_generation(self):
        with patch("qasc.model.urlopen", side_effect=URLError("connection refused")):
            self.assertFalse(self.adapter.info()["available"])
            with self.assertRaisesRegex(ModelError, "connection refused"):
                self.adapter.generate([{"role": "user", "content": "write code"}])

    def test_timeout_is_wrapped(self):
        with patch("qasc.model.urlopen", side_effect=TimeoutError("timed out")):
            with self.assertRaisesRegex(ModelError, "timed out"):
                self.adapter.generate([{"role": "user", "content": "write code"}])

    def test_response_size_limit(self):
        self.adapter.max_response_bytes = 10
        with self.assertRaisesRegex(ModelError, "exceeds"):
            self.adapter.generate([{"role": "user", "content": "write code"}])

    def test_configuration_rejects_bad_values(self):
        for config in ({"base_url": "file:///tmp/model"}, {"timeout": 0}, {"timeout": float("inf")}, {"max_tokens": 0}, {"model": ""}, {"context_size": -1}, {"base_url": "https://user:secret@example.com"}):
            with self.subTest(config=config), self.assertRaises(ValueError):
                OpenAICompatibleAdapter(**config)


class JsonParsingTests(unittest.TestCase):
    def test_object_and_single_fence(self):
        for value in ('{"ok":true}', '```json\n{"ok":true}\n```', '```\n{"ok":true}\n```'):
            self.assertEqual(parse_json_response(value), {"ok": True})

    def test_rejects_ambiguous_or_invalid_json(self):
        values = ['[]', '{broken}', 'prefix {"ok":true}', '```json\n{}\n```\n```json\n{}\n```', '{"a":1,"a":2}', '{"value":NaN}', '{} {}']
        for value in values:
            with self.subTest(value=value), self.assertRaises(ModelError):
                parse_json_response(value)


if __name__ == "__main__":
    unittest.main()
