"""Real subprocess validation for QASC's execution receipts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import subprocess
import tempfile
import time
import unittest
from unittest import mock

from qasc.execution import OUTPUT_LIMIT_BYTES, execute


class ExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def run_python(self, code: str, **options):
        return execute(self.root, [sys.executable, "-c", code], **options)

    def test_success_and_atomic_receipt(self):
        result = self.run_python(
            "import os,sys; print(os.getcwd()); print('problem',file=sys.stderr)",
            receipt_dir=Path(".qasc") / "executions",
        )
        self.assertEqual(result["exit_code"], 0)
        self.assertIn(str(self.root.resolve()), result["stdout"])
        self.assertIn("problem", result["stderr"])
        self.assertFalse(result["timed_out"])
        self.assertIsNone(result["error"])
        self.assertEqual(json.loads(Path(result["receipt_path"]).read_text(encoding="utf-8")), result)
        self.assertEqual(len(list(Path(result["receipt_path"]).parent.iterdir())), 1)

    def test_failed_program(self):
        result = self.run_python("import sys; print('bad',file=sys.stderr); sys.exit(7)")
        self.assertEqual(result["exit_code"], 7)
        self.assertIn("bad", result["stderr"])
        self.assertFalse(result["timed_out"])

    def test_stdin_is_supplied_and_eof_is_closed(self):
        result = self.run_python("import sys; print(sys.stdin.read().upper())", stdin="hello\nworld")
        self.assertEqual(result["exit_code"], 0)
        self.assertEqual(result["stdout"].replace("\r\n", "\n"), "HELLO\nWORLD\n")
        self.assertEqual(result["id"], result["receipt_id"])

    def test_spawn_error_is_recorded(self):
        result = execute(self.root, [str(self.root / "nonexistent-qasc-command.exe")])
        self.assertIsNone(result["exit_code"])
        self.assertIn("Error", result["error"])
        self.assertEqual(result["changes"], {"added": [], "modified": [], "deleted": []})

    def test_timeout_terminates_descendant(self):
        marker = self.root / "descendant-finished.txt"
        child = "import pathlib,time; time.sleep(3); pathlib.Path('descendant-finished.txt').write_text('leaked')"
        code = f"import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',{child!r}]); print('started',flush=True); time.sleep(30)"
        result = self.run_python(code, timeout=0.5)
        self.assertTrue(result["timed_out"])
        self.assertIsNotNone(result["exit_code"])
        self.assertIn("started", result["stdout"])
        self.assertLess(result["elapsed_seconds"], 10)
        time.sleep(3)
        self.assertFalse(marker.exists(), "Timed-out descendant survived the process tree termination")

    def test_interruption_terminates_process_and_preserves_receipt(self):
        original_popen = subprocess.Popen
        launched = []
        def launch(*args, **kwargs):
            child = original_popen(*args, **kwargs)
            if not launched:
                launched.append(child)
                original_wait = child.wait
                def interrupt_wait(*args, **kwargs):
                    child.wait = original_wait
                    raise KeyboardInterrupt()
                child.wait = interrupt_wait
            return child
        try:
            with mock.patch("qasc.execution.subprocess.Popen", side_effect=launch):
                with self.assertRaises(KeyboardInterrupt):
                    self.run_python("import time; time.sleep(30)", receipt_dir=Path(".qasc/executions"))
            self.assertIsNotNone(launched[0].poll())
            receipts = list((self.root / ".qasc/executions").glob("*.json"))
            self.assertEqual(len(receipts), 1)
            saved = json.loads(receipts[0].read_text(encoding="utf-8"))
            self.assertTrue(saved["interrupted"])
            self.assertFalse(saved["timed_out"])
            self.assertIn("Interrupted", saved["error"])
        finally:
            for child in launched:
                if child.poll() is None:
                    child.kill()
                    child.wait(timeout=5)

    def test_changed_files_include_before_and_after_hashes(self):
        (self.root / "changed.txt").write_text("old", encoding="utf-8")
        (self.root / "deleted.txt").write_text("gone", encoding="utf-8")
        result = self.run_python(
            "from pathlib import Path; Path('changed.txt').write_text('new'); "
            "Path('deleted.txt').unlink(); Path('added.txt').write_text('created'); "
            "Path('__pycache__').mkdir(); Path('__pycache__/ignored.pyc').write_text('cache')"
        )
        self.assertEqual([item["path"] for item in result["changes"]["added"]], ["added.txt"])
        modified = result["changes"]["modified"][0]
        self.assertEqual(modified["path"], "changed.txt")
        self.assertEqual(modified["before"]["sha256"], hashlib.sha256(b"old").hexdigest())
        self.assertEqual(modified["after"]["sha256"], hashlib.sha256(b"new").hexdigest())
        self.assertEqual(result["changes"]["deleted"][0]["path"], "deleted.txt")

    def test_metacharacters_are_literal_arguments(self):
        argument = "hello & echo exploited > injected.txt; $(echo unsafe)"
        result = execute(self.root, [sys.executable, "-c", "import sys; print(sys.argv[1])", argument])
        self.assertEqual(result["stdout"].strip(), argument)
        self.assertFalse((self.root / "injected.txt").exists())

    def test_output_is_bounded_and_streams_are_drained(self):
        result = self.run_python(
            "import sys; print('x'*200000); print('y'*200000,file=sys.stderr)"
        )
        self.assertEqual(result["exit_code"], 0)
        for stream in ("stdout", "stderr"):
            self.assertTrue(result[f"{stream}_truncated"])
            self.assertGreater(result[f"{stream}_bytes"], 200000)
            self.assertLess(len(result[stream]), OUTPUT_LIMIT_BYTES + 100)

    def test_temporary_directory_is_project_local(self):
        result = self.run_python("import tempfile; print(tempfile.gettempdir())")
        self.assertEqual(Path(result["stdout"].strip()), self.root.resolve() / ".qasc" / "runtime" / "tmp")

    def test_symlinks_are_not_followed(self):
        with tempfile.TemporaryDirectory() as outside_name:
            outside = Path(outside_name)
            (outside / "secret.txt").write_text("original")
            try:
                (self.root / "outside").symlink_to(outside, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"Symlink creation unavailable: {exc}")
            result = self.run_python("from pathlib import Path; Path('outside/secret.txt').write_text('modified')")
            self.assertEqual(result["exit_code"], 0)
            self.assertEqual(result["changes"], {"added": [], "modified": [], "deleted": []})

    def test_validation(self):
        for command in ([], "echo hello", [1], [""], ["python", "a\0b"]):
            with self.subTest(command=command), self.assertRaises(ValueError):
                execute(self.root, command)
        for timeout in (0, -1, float("inf"), float("nan"), True):
            with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                self.run_python("pass", timeout=timeout)
        with self.assertRaises(ValueError):
            self.run_python("pass", receipt_dir=self.root.parent)


if __name__ == "__main__":
    unittest.main()
