"""CLI contracts exercised against a loopback fixture, never a live model."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from qasc import __version__, cli


class CliTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                self.respond()

            def do_POST(self):
                self.rfile.read(int(self.headers.get("Content-Length", "0")))
                self.respond()

            def respond(self):
                cls.requests.append((self.command, self.path))
                status, payload = cls.routes.get(self.path, (503, {"error": {"message": "fixture server offline"}}))
                body = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.endpoint = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="qasc-cli-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.projects = self.root / "projects"
        self.__class__.routes = {}
        self.__class__.requests = []

    def command(self, *args):
        environment = os.environ.copy()
        for name in ("QASC_ENDPOINT", "QASC_MODEL", "QASC_PROJECTS_DIR"):
            environment.pop(name, None)
        environment["PYTHONPATH"] = str(Path(cli.__file__).resolve().parents[1])
        environment["PYTHONIOENCODING"] = "utf-8"
        return subprocess.run(
            [sys.executable, "-m", "qasc", "--endpoint", self.endpoint,
             "--model-timeout", "2", "--projects-dir", str(self.projects), *args],
            cwd=self.root,
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
        )

    def json_command(self, *args):
        process = self.command(*args)
        try:
            value = json.loads(process.stdout)
        except ValueError:
            self.fail(f"CLI did not return JSON: {process.stdout!r}; stderr={process.stderr!r}")
        return process, value

    def configure_generation(self):
        proposal = {
            "requirements": ["Print hello from an executable Python CLI"],
            "acceptance_criteria": ["Output equals hello followed by newline"],
            "architecture": "A simple CLI and unittest behavior check",
            "entrypoint": "app.py",
            "files": [
                {"path": "app.py", "content": "def message():\n    return 'hello'\n\nif __name__ == '__main__':\n    print(message())\n"},
                {"path": "tests/test_app.py", "content": "import unittest\nfrom app import message\nclass MessageTests(unittest.TestCase):\n    def test_message(self):\n        self.assertEqual(message(), 'hello')\n"},
            ],
        }
        self.routes.update({
            "/health": (200, {"status": "ok"}),
            "/v1/models": (200, {"data": [{"id": "cli-fixture-model"}]}),
            "/props": (200, {"default_generation_settings": {"n_ctx": 8192}}),
            "/v1/chat/completions": (200, {"model": "cli-fixture-model", "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(proposal)}}]}),
        })

    def create_fixture(self, name="hello-app", run=False):
        self.configure_generation()
        args = ["create", "Create a command-line program that prints hello.", "--name", name]
        if run:
            args += ["--run", "--max-corrections", "0"]
        process, value = self.json_command(*args)
        self.assertEqual(process.returncode, 0, value)
        return value

    def test_offline_models_exits_one_with_json(self):
        process, value = self.json_command("models")
        self.assertEqual(process.returncode, 1)
        self.assertFalse(value["adapters"][0]["available"])
        self.assertEqual(value["adapters"][0]["base_url"], self.endpoint)
        self.assertIn("/v1/models", value["adapters"][0]["errors"])

    def test_offline_doctor_exits_one_and_includes_discovery(self):
        process, value = self.json_command("doctor")
        self.assertEqual(process.returncode, 1)
        self.assertFalse(value["adapters"][0]["available"])
        self.assertIn("python", value["discovery"])
        self.assertIn("tools", value["discovery"])
        self.assertIn("no OS sandbox", value["execution_policy"])

    def test_offline_create_preserves_request_and_failure_for_resume(self):
        process, value = self.json_command("create", "Create a greeting CLI.", "--name", "offline-app")
        self.assertEqual(process.returncode, 2)
        self.assertEqual(value["type"], "ModelError")
        state_path = self.projects / "offline-app" / ".qasc" / "state.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        self.assertEqual(state["request"], "Create a greeting CLI.")
        self.assertEqual(state["status"], "blocked")
        self.assertEqual(state["files"], [])
        self.assertIn("fixture server offline", state["failures"][-1]["error"])
        self.assertEqual(state["adapter"]["base_url"], self.endpoint)
        self.assertFalse((state_path.parent / "operation.lock").exists())
        self.assertEqual(len(list((state_path.parent / "model").glob("*/error.json"))), 1)

    def test_status_lists_and_details_generated_project_without_inference(self):
        created = self.create_fixture()
        requests_before_status = len(self.requests)
        process, listing = self.json_command("status")
        self.assertEqual(process.returncode, 0)
        self.assertEqual([project["name"] for project in listing["projects"]], ["hello-app"])
        self.assertEqual(listing["projects"][0]["status"], "generated")
        process, details = self.json_command("status", "hello-app")
        self.assertEqual(process.returncode, 0)
        self.assertEqual(details["revision"], created["revision"])
        self.assertIn("app.py", details["files"])
        self.assertIsNone(details["last_verification"])
        self.assertEqual(len(self.requests), requests_before_status)

    def test_status_missing_directory_is_empty(self):
        process, listing = self.json_command("status")
        self.assertEqual(process.returncode, 0)
        self.assertEqual(listing["projects"], [])
        self.assertEqual(self.requests, [])

    def test_create_run_executes_actual_generated_tests(self):
        created = self.create_fixture(run=True)
        self.assertEqual(created["status"], "verified")
        self.assertTrue(created["last_verification"]["passed"])
        self.assertEqual(created["last_verification"]["unit_test_count"], 1)
        self.assertEqual(created["last_verification"]["scope"], "model_generated_tests_only")

    def test_existing_project_name_is_rejected_without_overwrite_or_inference(self):
        self.create_fixture()
        state_path = self.projects / "hello-app" / ".qasc" / "state.json"
        original = state_path.read_bytes()
        requests_before = len(self.requests)
        process, value = self.json_command("create", "Replace everything.", "--name", "hello-app")
        self.assertEqual(process.returncode, 2)
        self.assertEqual(value["type"], "ProjectError")
        self.assertIn("already exists", value["error"])
        self.assertEqual(state_path.read_bytes(), original)
        self.assertEqual(len(self.requests), requests_before)

    def test_invalid_max_corrections_is_json_error_before_project_creation(self):
        for value in ("-1", "11"):
            with self.subTest(value=value):
                process, result = self.json_command("create", "Print hello.", "--name", "invalid-app", "--max-corrections", value)
                self.assertEqual(process.returncode, 2)
                self.assertEqual(result["type"], "ProjectError")
                self.assertIn("between 0 and 10", result["error"])
                self.assertFalse((self.projects / "invalid-app").exists())

    def test_invalid_name_and_missing_project_return_json_errors(self):
        for args in (("create", "Print hello.", "--name", "../escape"), ("status", "missing-app")):
            with self.subTest(args=args):
                process, value = self.json_command(*args)
                self.assertEqual(process.returncode, 2)
                self.assertEqual(value["type"], "ProjectError")
                self.assertTrue(value["error"])

    def test_help_and_version_work_without_model_requests(self):
        version = self.command("--version")
        self.assertEqual(version.returncode, 0)
        self.assertEqual(version.stdout.strip(), f"qasc {__version__}")
        help_result = self.command("--help")
        self.assertEqual(help_result.returncode, 0)
        self.assertIn("resume", help_result.stdout)
        self.assertIn("doctor", help_result.stdout)
        self.assertEqual(self.requests, [])


class SavedAdapterTests(unittest.TestCase):
    def parse(self, *args):
        with patch.dict(os.environ, {}, clear=True):
            return cli.parser().parse_args([*args, "resume", "saved-app"])

    def test_resume_uses_saved_endpoint_model_and_limits(self):
        state = {"adapter": {"base_url": "http://127.0.0.1:18555", "model": "saved-model", "timeout": 75, "max_tokens": 1500}}
        adapter = cli.make_adapter(self.parse(), state)
        self.assertEqual(adapter.base_url, "http://127.0.0.1:18555")
        self.assertEqual(adapter.model, "saved-model")
        self.assertEqual(adapter.timeout, 75)
        self.assertEqual(adapter.max_tokens, 1500)

    def test_explicit_configuration_overrides_saved_settings(self):
        state = {"adapter": {"base_url": "http://127.0.0.1:18555", "model": "saved-model", "timeout": 75, "max_tokens": 1500}}
        args = self.parse("--endpoint", "http://127.0.0.1:18556", "--model", "override", "--model-timeout", "10", "--max-tokens", "200")
        adapter = cli.make_adapter(args, state)
        self.assertEqual(adapter.base_url, "http://127.0.0.1:18556")
        self.assertEqual(adapter.model, "override")
        self.assertEqual(adapter.timeout, 10)
        self.assertEqual(adapter.max_tokens, 200)

    def test_defaults_remain_local_when_no_saved_configuration_exists(self):
        adapter = cli.make_adapter(self.parse())
        self.assertEqual(adapter.base_url, "http://127.0.0.1:8080")
        self.assertIsNone(adapter.model)
        self.assertEqual(adapter.max_tokens, 3000)


if __name__ == "__main__":
    unittest.main()
