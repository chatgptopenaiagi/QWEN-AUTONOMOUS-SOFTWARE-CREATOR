"""Project isolation, persistent revision recovery, and path validation tests."""

from __future__ import annotations

from pathlib import Path
import os
import tempfile
import unittest
from unittest import mock

from qasc.project import Project, ProjectError, atomic_source, safe_path, validate_files


PROVENANCE = {"kind": "test_fixture", "author": "QASC validation"}


class ProjectTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.project = Project(self.root, "sample")
        self.state = self.project.initialize("Create a sample application.", {"adapter": "fixture"})

    def test_existing_project_and_unrelated_project_are_preserved(self):
        marker = self.project.path / "operator-notes.txt"
        marker.write_text("keep")
        with self.assertRaisesRegex(ProjectError, "already exists"):
            self.project.initialize("Another project", {})
        other = Project(self.root, "another")
        other.initialize("Independent project", {})
        other.apply_revision(other.load(), [{"path": "main.py", "content": "print('other')\n"}], PROVENANCE)
        self.assertEqual(marker.read_text(), "keep")
        self.assertEqual(self.project.load()["files"], [])

    def test_path_escape_metadata_and_windows_reserved_names_rejected(self):
        paths = ["../outside.py", "/absolute.py", "C:/outside.py", "a\\b.py", ".qasc/state.json",
                 ".git/config", "folder/../main.py", "folder//main.py", "NUL.py", "aux.txt",
                 "com1.py", "folder/end. /main.py", "trailing./main.py", "main.py:stream", "bad?.py", "a\x00.py"]
        for path in paths:
            with self.subTest(path=path), self.assertRaises(ProjectError):
                safe_path(self.project.path, path)
        self.assertEqual(safe_path(self.project.path, "lib/main.py"), self.project.path / "lib/main.py")

    def test_file_validation_rejects_duplicates_conflicts_and_executable_payloads(self):
        cases = [
            [{"path": "main.py", "content": "a"}, {"path": "MAIN.py", "content": "b"}],
            [{"path": "main.py", "content": "a"}, {"path": "main.py/child.py", "content": "b"}],
            [{"path": "install.ps1", "content": "Write-Host unexpected"}],
            [{"path": "large.txt", "content": "x" * 256001}],
        ]
        for files in cases:
            with self.subTest(paths=[f["path"] for f in files]), self.assertRaises(ProjectError):
                validate_files(files, self.project.path)

    def test_unmanaged_existing_file_cannot_be_overwritten(self):
        target = self.project.path / "main.py"
        target.write_text("operator version")
        with self.assertRaisesRegex(ProjectError, "unmanaged"):
            self.project.apply_revision(self.state, [{"path": "main.py", "content": "generated"}], PROVENANCE)
        self.assertEqual(target.read_text(), "operator version")
        self.assertEqual(self.project.load()["history"], [])

    def test_revisions_preserve_previous_source_and_delete_only_managed_files(self):
        first = self.project.apply_revision(self.state, [{"path": "main.py", "content": "first\n"},
                                                         {"path": "obsolete.txt", "content": "remove"}], PROVENANCE)
        (self.project.path / "operator.txt").write_text("keep")
        second = self.project.apply_revision(self.state, [{"path": "main.py", "content": "second\n"}], PROVENANCE)
        self.assertNotEqual(first, second)
        self.assertEqual((self.project.meta / "revisions" / first / "source/main.py").read_text(), "first\n")
        self.assertEqual((self.project.path / "main.py").read_text(), "second\n")
        self.assertFalse((self.project.path / "obsolete.txt").exists())
        self.assertEqual((self.project.path / "operator.txt").read_text(), "keep")
        self.assertEqual(len(self.project.load()["history"]), 2)

    def test_interrupted_pending_revision_is_recoverable(self):
        with mock.patch.object(self.project, "finish_pending", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.project.apply_revision(self.state, [{"path": "main.py", "content": "print('recovered')\n"}], PROVENANCE)
        saved = self.project.load()
        pending = saved["pending_revision"]
        self.assertFalse((self.project.path / "main.py").exists())
        self.project.finish_pending(saved)
        self.assertEqual((self.project.path / "main.py").read_text(), "print('recovered')\n")
        self.assertEqual(self.project.load()["revision"], pending)
        self.assertNotIn("pending_revision", self.project.load())

    def test_resume_refuses_new_unmanaged_file_created_during_interruption(self):
        with mock.patch.object(self.project, "finish_pending", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.project.apply_revision(self.state, [{"path": "main.py", "content": "model version"}], PROVENANCE)
        (self.project.path / "main.py").write_text("operator version created after interruption")
        with self.assertRaises(ProjectError):
            self.project.finish_pending(self.project.load())
        self.assertEqual((self.project.path / "main.py").read_text(), "operator version created after interruption")

    def test_corrupted_pending_snapshot_cannot_be_applied(self):
        with mock.patch.object(self.project, "finish_pending", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.project.apply_revision(self.state, [{"path": "main.py", "content": "original"}], PROVENANCE)
        saved = self.project.load()
        snapshot = self.project.meta / "revisions" / saved["pending_revision"] / "source/main.py"
        snapshot.write_text("tampered")
        with self.assertRaisesRegex(ProjectError, "checksum"):
            self.project.finish_pending(saved)
        self.assertFalse((self.project.path / "main.py").exists())

    def test_partial_application_replays_without_losing_original_revision(self):
        old = [{"path": "first.py", "content": "first old"},
               {"path": "second.py", "content": "second old"},
               {"path": "obsolete.txt", "content": "old artifact"}]
        original = self.project.apply_revision(self.state, old, PROVENANCE)
        new = [{"path": "first.py", "content": "first new"},
               {"path": "second.py", "content": "second new"}]
        calls = 0
        def interrupted_write(path, content):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise KeyboardInterrupt()
            return atomic_source(path, content)
        with mock.patch("qasc.project.atomic_source", side_effect=interrupted_write):
            with self.assertRaises(KeyboardInterrupt):
                self.project.apply_revision(self.state, new, PROVENANCE)
        self.assertEqual((self.project.path / "first.py").read_text(), "first new")
        self.assertEqual((self.project.path / "second.py").read_text(), "second old")
        self.assertFalse((self.project.path / "obsolete.txt").exists())
        saved = self.project.load()
        self.project.finish_pending(saved)
        self.assertEqual((self.project.path / "second.py").read_text(), "second new")
        self.assertEqual(len(self.project.load()["history"]), 2)
        self.assertEqual((self.project.meta / "revisions" / original / "source/first.py").read_text(), "first old")

    def test_resume_preserves_operator_edit_of_managed_file_scheduled_for_deletion(self):
        self.project.apply_revision(self.state, [{"path": "main.py", "content": "original"},
                                                {"path": "remove.txt", "content": "old"}], PROVENANCE)
        with mock.patch.object(self.project, "finish_pending", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.project.apply_revision(self.state, [{"path": "main.py", "content": "replacement"}], PROVENANCE)
        (self.project.path / "remove.txt").write_text("operator edit after interruption")
        with self.assertRaises(ProjectError):
            self.project.finish_pending(self.project.load())
        self.assertEqual((self.project.path / "remove.txt").read_text(), "operator edit after interruption")
        self.assertEqual((self.project.path / "main.py").read_text(), "original")

    def test_atomic_replacement_does_not_write_through_an_external_hardlink(self):
        self.project.apply_revision(self.state, [{"path": "main.py", "content": "first"}], PROVENANCE)
        outside_link = self.root / "outside-project.py"
        try:
            os.link(self.project.path / "main.py", outside_link)
        except OSError as exc:
            self.skipTest(f"Hardlinks unavailable: {exc}")
        self.project.apply_revision(self.state, [{"path": "main.py", "content": "second"}], PROVENANCE)
        self.assertEqual(outside_link.read_text(), "first")
        self.assertEqual((self.project.path / "main.py").read_text(), "second")

    def test_symlink_project_and_generated_path_are_rejected(self):
        with tempfile.TemporaryDirectory() as external_name:
            external = Path(external_name)
            (external / "outside.py").write_text("outside")
            try:
                (self.root / "linked-project").symlink_to(external, target_is_directory=True)
                (self.project.path / "linked-dir").symlink_to(external, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"Symlink creation unavailable: {exc}")
            with self.assertRaises(ProjectError):
                Project(self.root, "linked-project")
            with self.assertRaises(ProjectError):
                safe_path(self.project.path, "linked-dir/outside.py")
            self.assertEqual((external / "outside.py").read_text(), "outside")

    def test_operation_lock_prevents_concurrent_mutation_and_releases_on_exception(self):
        with self.assertRaisesRegex(RuntimeError, "fixture interruption"):
            with self.project.lock():
                with self.assertRaisesRegex(ProjectError, "locked"):
                    with self.project.lock():
                        self.fail("A second writer acquired the project")
                raise RuntimeError("fixture interruption")
        self.assertFalse((self.project.meta / "operation.lock").exists())
        with self.project.lock():
            self.assertTrue((self.project.meta / "operation.lock").exists())


if __name__ == "__main__":
    unittest.main()
