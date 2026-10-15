import subprocess
import sys
import unittest
from unittest.mock import patch

from qasc.discovery import _probe, discover_tools


class DiscoveryTests(unittest.TestCase):
    def test_python_probe_executes_actual_interpreter(self):
        name, result = _probe("python", (("python",), ("--version",)))
        self.assertEqual(name, "python")
        self.assertTrue(result["available"])
        self.assertEqual(result["path"], sys.executable)
        self.assertIn("Python", result["version"])
        self.assertIsNone(result["error"])

    def test_missing_tool_is_not_reported_available(self):
        with patch("qasc.discovery.shutil.which", return_value=None), patch("qasc.discovery._known_candidates", return_value=[]):
            _, result = _probe("missing", (("nonexistent-qasc-test-command",), ("--version",)))
        self.assertFalse(result["available"])
        self.assertIsNone(result["version"])
        self.assertIn("Not found", result["error"])

    def test_timeout_is_recorded_separately_from_location(self):
        with patch("qasc.discovery.shutil.which", return_value="/fake/tool"), patch("qasc.discovery.subprocess.run", side_effect=subprocess.TimeoutExpired("tool", 5)):
            _, result = _probe("tool", (("tool",), ("--version",)))
        self.assertTrue(result["available"])
        self.assertIn("timed out", result["error"])

    def test_nonzero_probe_preserves_diagnostics(self):
        completed = subprocess.CompletedProcess(["tool"], 3, "", "not usable")
        with patch("qasc.discovery.shutil.which", return_value="/fake/tool"), patch("qasc.discovery.subprocess.run", return_value=completed) as run:
            _, result = _probe("tool", (("tool",), ("--version",)))
        self.assertEqual(result["version"], "not usable")
        self.assertEqual(result["probe_exit_code"], 3)
        self.assertIn("3", result["error"])
        self.assertFalse(run.call_args.kwargs["shell"])
        self.assertEqual(run.call_args.kwargs["timeout"], 5)

    def test_inventory_contract(self):
        def fake_probe(name, spec):
            return name, {"available": False, "path": None, "version": None, "error": "fixture"}

        with patch("qasc.discovery._probe", side_effect=fake_probe):
            inventory = discover_tools()
        self.assertEqual(inventory["python"]["executable"], sys.executable)
        self.assertIn("system", inventory["platform"])
        for required in ("python", "anaconda", "powershell", "node", "git", "github_cli", "gcc", "clang", "msvc", "cmake", "ninja", "rust", "dotnet", "pyinstaller", "wix", "inno_setup", "windows_sdk"):
            self.assertIn(required, inventory["tools"])


if __name__ == "__main__":
    unittest.main()
