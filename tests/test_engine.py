"""Workflow integration tests using scripted model responses and real Python apps.

The model is a deterministic fixture; every application test and acceptance case
still runs as a real child process through the execution engine.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import zipfile

from qasc.engine import Engine, package_project
from qasc.execution import execute as real_execute
from qasc.model import Generation, ModelAdapter, ModelError
from qasc.project import Project, ProjectError, read_json


GOOD_CALCULATOR = "def add(left, right):\n    return left + right\n"
BAD_CALCULATOR = "def add(left, right):\n    return left - right\n"
APPLICATION = (
    "import sys\nfrom calculator import add\n"
    "if __name__ == '__main__':\n"
    "    print(add(int(sys.argv[1]), int(sys.argv[2])))\n"
)
TESTS = (
    "import unittest\nfrom calculator import add\n\n"
    "class CalculatorTests(unittest.TestCase):\n"
    "    def test_positive(self):\n        self.assertEqual(add(2, 3), 5)\n"
    "    def test_cancel(self):\n        self.assertEqual(add(-4, 4), 0)\n"
)


def proposal(calculator: str = GOOD_CALCULATOR, tests: str = TESTS) -> dict:
    return {
        "requirements": ["Add two integer command-line arguments"],
        "acceptance_criteria": ["Printing the sum followed by a newline"],
        "architecture": "The CLI imports a separately testable arithmetic function.",
        "entrypoint": "app.py",
        "files": [
            {"path": "app.py", "content": APPLICATION},
            {"path": "calculator.py", "content": calculator},
            {"path": "tests/test_calculator.py", "content": tests},
        ],
    }


def correction(content: str = GOOD_CALCULATOR, path: str = "calculator.py") -> dict:
    return {"diagnosis": "The arithmetic operation must add both operands.",
            "changes": [{"path": path, "content": content}]}


class FakeAdapter:
    adapter_id = "scripted-test-fixture"
    capabilities = {"structured_responses": True}

    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []

    def info(self):
        return {"adapter": self.adapter_id, "model": "fixture-model", "available": True}

    def generate(self, messages, response_schema=None):
        self.requests.append({"messages": copy.deepcopy(messages), "schema": response_schema})
        if not self.responses:
            raise AssertionError("Unexpected model call; a resumed project should use its saved files")
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        content = json.dumps(response)
        return Generation(content=content, model="fixture-model", usage={"completion_tokens": 1},
                          timings={"request_seconds": 0.001}, tool_calls=[],
                          raw={"fixture": True, "content": content})


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.project = Project(Path(self.temporary.name), "sample-app")

    def initialize(self, adapter, *, acceptance=True):
        cases = {"cases": [{"name": "sum", "args": ["2", "3"], "stdout": "5\n", "stderr": ""}]} if acceptance else None
        self.project.initialize("Create an integer addition command-line program.", adapter.info(), cases)
        return Engine(adapter)

    def test_create_real_multifile_app_and_independent_acceptance(self):
        adapter = FakeAdapter(proposal())
        self.assertIsInstance(adapter, ModelAdapter)
        state = self.initialize(adapter).run(self.project, max_corrections=0)
        self.assertEqual(state["status"], "verified")
        verification = state["last_verification"]
        self.assertTrue(verification["independent_acceptance_passed"])
        self.assertEqual(verification["unit_test_count"], 2)
        self.assertEqual(verification["scope"], "operator_acceptance_and_model_tests")
        self.assertEqual(len(state["executions"]), 2)
        self.assertEqual(state["request_provenance"], "human_requirement")
        self.assertEqual(state["history"][0]["provenance"]["kind"], "ai_generated_application")
        recorded = list((self.project.meta / "model").glob("*/response.json"))
        self.assertEqual(len(recorded), 1)
        self.assertTrue(read_json(recorded[0])["raw"]["fixture"])

    def test_real_failure_feedback_drives_targeted_correction(self):
        adapter = FakeAdapter(proposal(BAD_CALCULATOR), correction())
        state = self.initialize(adapter).run(self.project, max_corrections=1)
        self.assertEqual(state["status"], "verified")
        self.assertEqual(len(state["corrections"]), 1)
        self.assertEqual(len(state["history"]), 2)
        self.assertEqual(len(state["executions"]), 4)
        self.assertEqual(len(state["failures"]), 1)
        feedback = json.loads(adapter.requests[1]["messages"][1]["content"])["execution_feedback"]
        self.assertIn("AssertionError", feedback["unit_feedback"]["stderr"])
        self.assertNotEqual(feedback["unit_feedback"]["exit_code"], 0)
        self.assertEqual(feedback["acceptance_cases"][0]["mismatches"][0]["actual"], "-1\n")
        self.assertEqual((self.project.path / "tests/test_calculator.py").read_text(), TESTS)
        original = self.project.meta / "revisions" / state["history"][0]["revision"] / "source/calculator.py"
        self.assertEqual(original.read_text(), BAD_CALCULATOR)

    def test_resume_uses_saved_files_without_regeneration(self):
        adapter = FakeAdapter(proposal())
        generated = self.initialize(adapter).run(self.project, generate_only=True)
        self.assertEqual(generated["status"], "generated")
        self.assertFalse(generated["executions"])
        new_adapter = FakeAdapter()
        state = Engine(new_adapter).run(Project(self.project.root, self.project.name), max_corrections=0)
        self.assertEqual(state["status"], "verified")
        self.assertEqual(new_adapter.requests, [])
        self.assertEqual(state["revision"], generated["revision"])

    def test_frozen_tests_cannot_be_replaced_by_a_correction(self):
        adapter = FakeAdapter(proposal(BAD_CALCULATOR), correction("# remove tests\n", "tests/test_calculator.py"))
        with self.assertRaisesRegex(ProjectError, "frozen"):
            self.initialize(adapter).run(self.project, max_corrections=1)
        state = self.project.load()
        self.assertEqual(state["status"], "blocked")
        self.assertEqual((self.project.path / "tests/test_calculator.py").read_text(), TESTS)
        self.assertEqual(len(state["history"]), 1)
        self.assertFalse(state["verified_revisions"])

    def test_failed_python_execution_never_becomes_verified(self):
        adapter = FakeAdapter(proposal("raise RuntimeError('fixture execution failure')\n"))
        state = self.initialize(adapter).run(self.project, max_corrections=0)
        self.assertEqual(state["status"], "test_failed")
        self.assertFalse(state["last_verification"]["passed"])
        self.assertIn("fixture execution failure", state["last_verification"]["unit_feedback"]["stderr"])
        self.assertFalse(state["verified_revisions"])
        self.assertIn("budget exhausted", state["limitations"][-1])

    def test_zero_discovered_tests_is_a_failure(self):
        adapter = FakeAdapter(proposal(tests="# No executable test methods.\n"))
        state = self.initialize(adapter, acceptance=False).run(self.project, max_corrections=0)
        self.assertEqual(state["last_verification"]["unit_test_count"], 0)
        self.assertEqual(state["status"], "test_failed")

    def test_model_tests_without_operator_cases_have_limited_scope(self):
        state = self.initialize(FakeAdapter(proposal()), acceptance=False).run(self.project, max_corrections=0)
        self.assertTrue(state["last_verification"]["passed"])
        self.assertFalse(state["last_verification"]["independent_acceptance_passed"])
        self.assertEqual(state["last_verification"]["scope"], "model_generated_tests_only")

    def test_operator_acceptance_can_fail_even_when_model_tests_pass(self):
        wrong_tests = TESTS.replace("add(2, 3), 5", "add(2, 3), -1").replace("add(-4, 4), 0", "add(-4, 4), -8")
        state = self.initialize(FakeAdapter(proposal(BAD_CALCULATOR, wrong_tests))).run(self.project, max_corrections=0)
        verification = state["last_verification"]
        self.assertTrue(verification["unit_tests_passed"])
        self.assertFalse(verification["independent_acceptance_passed"])
        self.assertFalse(verification["passed"])
        self.assertEqual(state["acceptance"]["cases"][0]["stdout"], "5\n")
        self.assertFalse(state["verified_revisions"])

    def test_identical_correction_stops_without_repeated_execution(self):
        adapter = FakeAdapter(proposal(BAD_CALCULATOR), correction(BAD_CALCULATOR))
        state = self.initialize(adapter).run(self.project, max_corrections=5)
        self.assertEqual(state["status"], "stalled")
        self.assertEqual(len(state["executions"]), 2)
        self.assertEqual(len(state["history"]), 1)
        self.assertIn("identical correction", state["limitations"][-1])

    def test_cycle_of_ineffective_versions_is_detected(self):
        other_bad = "def add(left, right):\n    return left * right\n"
        adapter = FakeAdapter(proposal(BAD_CALCULATOR), correction(other_bad), correction(BAD_CALCULATOR))
        state = self.initialize(adapter).run(self.project, max_corrections=5)
        self.assertEqual(state["status"], "stalled")
        self.assertEqual(len(adapter.requests), 3)
        self.assertIn("Repeated source version", state["limitations"][-1])

    def test_verified_snapshot_survives_later_failure(self):
        engine = self.initialize(FakeAdapter(proposal()))
        first = engine.run(self.project, max_corrections=0)
        snapshot_path = self.project.meta / "verified" / (first["verified_revisions"][0]["id"] + ".json")
        snapshot_before = snapshot_path.read_bytes()
        (self.project.path / "calculator.py").write_text(BAD_CALCULATOR)
        second = Engine(FakeAdapter()).run(self.project, max_corrections=0)
        self.assertEqual(second["status"], "test_failed")
        self.assertEqual(len(second["verified_revisions"]), 1)
        self.assertEqual(snapshot_path.read_bytes(), snapshot_before)
        preserved = {item["path"]: item["content"] for item in read_json(snapshot_path)["files"]}
        self.assertEqual(preserved["calculator.py"], GOOD_CALCULATOR)

    def test_package_matches_verified_files_and_refuses_stale_sources(self):
        state = self.initialize(FakeAdapter(proposal())).run(self.project, max_corrections=0)
        receipt = package_project(self.project)
        self.assertTrue(receipt["archive_verified"])
        self.assertFalse(receipt["executable_created"])
        self.assertFalse(receipt["installer_created"])
        with zipfile.ZipFile(receipt["path"]) as archive:
            self.assertEqual(archive.read("sample-app/calculator.py").decode(), GOOD_CALCULATOR)
            self.assertEqual(json.loads(archive.read("QASC-DELIVERY.json"))["verification_id"], state["last_verification"]["id"])
        with self.assertRaisesRegex(ProjectError, "already exists"):
            package_project(self.project)
        (self.project.path / "calculator.py").write_text(BAD_CALCULATOR)
        with self.assertRaisesRegex(ProjectError, "current source"):
            package_project(self.project)

    def test_package_requires_execution_first(self):
        self.initialize(FakeAdapter(proposal())).run(self.project, generate_only=True)
        with self.assertRaisesRegex(ProjectError, "pass qasc test"):
            package_project(self.project)

    def test_interrupted_model_call_preserves_request_and_can_resume(self):
        engine = self.initialize(FakeAdapter(KeyboardInterrupt()))
        with self.assertRaises(KeyboardInterrupt):
            engine.run(self.project)
        interrupted = self.project.load()
        self.assertEqual(interrupted["status"], "blocked")
        self.assertEqual(interrupted["files"], [])
        self.assertIn("Interrupted", interrupted["failures"][-1]["error"])
        self.assertFalse((self.project.meta / "operation.lock").exists())
        resumed = Engine(FakeAdapter(proposal())).run(self.project, max_corrections=0)
        self.assertEqual(resumed["status"], "verified")
        self.assertEqual(resumed["request"], interrupted["request"])

    def test_interrupted_revision_application_resumes_without_another_model_call(self):
        engine = self.initialize(FakeAdapter(proposal()))
        with mock.patch.object(self.project, "finish_pending", side_effect=[None, KeyboardInterrupt()]):
            with self.assertRaises(KeyboardInterrupt):
                engine.run(self.project)
        interrupted = self.project.load()
        self.assertTrue(interrupted["pending_revision"])
        adapter = FakeAdapter()
        resumed = Engine(adapter).run(self.project, max_corrections=0)
        self.assertEqual(resumed["status"], "verified")
        self.assertEqual(adapter.requests, [])
        self.assertNotIn("pending_revision", resumed)

    def test_model_failure_is_saved_with_raw_error_details(self):
        engine = self.initialize(FakeAdapter(ModelError("Fixture endpoint disconnected", raw={"fixture_error": True})))
        with self.assertRaises(ModelError):
            engine.run(self.project)
        errors = list((self.project.meta / "model").glob("*/error.json"))
        self.assertEqual(len(errors), 1)
        self.assertTrue(read_json(errors[0])["raw"]["fixture_error"])
        self.assertEqual(self.project.load()["status"], "blocked")

    def test_incomplete_capture_cannot_verify_success(self):
        engine = self.initialize(FakeAdapter(proposal()), acceptance=False)
        def incomplete(*args, **kwargs):
            receipt = real_execute(*args, **kwargs)
            receipt["capture_incomplete"] = True
            return receipt
        with mock.patch("qasc.engine.execute", side_effect=incomplete):
            state = engine.run(self.project, max_corrections=0)
        self.assertEqual(state["status"], "test_failed")

    def test_application_mutating_managed_source_cannot_verify_success(self):
        modified = proposal()
        modified["files"][0]["content"] = APPLICATION + "\nfrom pathlib import Path\nPath('calculator.py').write_text('def add(a,b): return 99\\n')\n"
        state = self.initialize(FakeAdapter(modified)).run(self.project, max_corrections=0)
        self.assertFalse(state["last_verification"]["source_unchanged"])
        self.assertEqual(state["status"], "test_failed")


if __name__ == "__main__":
    unittest.main()
