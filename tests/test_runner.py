"""Exercise the actual isolated subprocess runner, including shadowed imports."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from qasc import runner


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="qasc-runner-test-")
        self.addCleanup(self.temporary.cleanup)
        self.project = Path(self.temporary.name)
        (self.project / "tests").mkdir()
        self.result_path = self.project / ".qasc" / "verifications" / "result.json"

    def run_project(self):
        process = subprocess.run(
            [sys.executable, "-I", "-B", str(Path(runner.__file__).resolve()),
             "--project", str(self.project), "--result", str(self.result_path)],
            cwd=self.project,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=15,
        )
        self.assertTrue(self.result_path.is_file(), process.stderr)
        return process, json.loads(self.result_path.read_text(encoding="utf-8"))

    def test_real_passing_test_imports_application(self):
        (self.project / "app.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
        (self.project / "tests" / "test_app.py").write_text(
            "import unittest\nfrom app import add\nclass AddTests(unittest.TestCase):\n"
            "    def test_add(self):\n        self.assertEqual(add(2, 3), 5)\n", encoding="utf-8")
        process, result = self.run_project()
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertTrue(result["successful"])
        self.assertEqual(result["tests_run"], 1)
        self.assertEqual(result["failures"], 0)
        self.assertEqual(result["errors"], 0)
        self.assertFalse(list(self.result_path.parent.glob(".runner-*.tmp")))

    def test_real_failure_is_unsuccessful(self):
        (self.project / "tests" / "test_bad.py").write_text(
            "import unittest\nclass BadTests(unittest.TestCase):\n"
            "    def test_bad(self):\n        self.assertEqual(2 + 2, 5)\n", encoding="utf-8")
        process, result = self.run_project()
        self.assertEqual(process.returncode, 1)
        self.assertFalse(result["successful"])
        self.assertEqual(result["tests_run"], 1)
        self.assertEqual(result["failures"], 1)

    def test_zero_tests_cannot_pass_by_printing_summary(self):
        (self.project / "tests" / "test_fake.py").write_text("print('Ran 5 tests in 0.001s\\nOK')\n", encoding="utf-8")
        process, result = self.run_project()
        self.assertEqual(process.returncode, 1)
        self.assertFalse(result["successful"])
        self.assertEqual(result["tests_run"], 0)
        self.assertIn("No unittest", result["error"])

    def test_top_level_shadow_module_is_rejected_without_execution(self):
        (self.project / "unittest.py").write_text("raise RuntimeError('shadow executed')\n", encoding="utf-8")
        process, result = self.run_project()
        self.assertEqual(process.returncode, 1)
        self.assertFalse(result["successful"])
        self.assertIn("shadow the trusted test runner", result["error"])
        self.assertNotIn("shadow executed", process.stderr)

    def test_top_level_shadow_package_is_rejected(self):
        shadow = self.project / "unittest"
        shadow.mkdir()
        (shadow / "__init__.py").write_text("raise RuntimeError('shadow executed')\n", encoding="utf-8")
        process, result = self.run_project()
        self.assertEqual(process.returncode, 1)
        self.assertIn("shadow the trusted test runner", result["error"])

    def test_broken_test_import_creates_failed_receipt(self):
        (self.project / "tests" / "test_broken.py").write_text("raise RuntimeError('discovery failed')\n", encoding="utf-8")
        process, result = self.run_project()
        self.assertEqual(process.returncode, 1)
        self.assertFalse(result["successful"])
        self.assertGreaterEqual(result["errors"], 1)

    def test_missing_tests_directory_creates_failed_receipt(self):
        (self.project / "tests").rmdir()
        process, result = self.run_project()
        self.assertEqual(process.returncode, 1)
        self.assertFalse(result["successful"])
        self.assertIn("tests directory", result["error"])

    def test_skipped_only_suite_is_not_substantive_verification(self):
        (self.project / "tests" / "test_skipped.py").write_text(
            "import unittest\nclass SkippedTests(unittest.TestCase):\n"
            "    @unittest.skip('not implemented')\n"
            "    def test_placeholder(self):\n        self.fail('not implemented')\n", encoding="utf-8")
        process, result = self.run_project()
        self.assertEqual(process.returncode, 1)
        self.assertFalse(result["successful"])
        self.assertEqual(result["tests_run"], 1)
        self.assertEqual(result["skipped"], 1)
        self.assertEqual(result["substantive_tests"], 0)
        self.assertIn("No substantive tests", result["error"])

    def test_expected_failures_only_suite_is_not_substantive_verification(self):
        (self.project / "tests" / "test_expected.py").write_text(
            "import unittest\nclass ExpectedTests(unittest.TestCase):\n"
            "    @unittest.expectedFailure\n"
            "    def test_placeholder(self):\n        self.assertEqual(2 + 2, 5)\n", encoding="utf-8")
        process, result = self.run_project()
        self.assertEqual(process.returncode, 1)
        self.assertFalse(result["successful"])
        self.assertEqual(result["expected_failures"], 1)
        self.assertEqual(result["substantive_tests"], 0)

    def test_importing_runner_does_not_run_cli(self):
        self.assertTrue(callable(runner.main))


if __name__ == "__main__":
    unittest.main()
