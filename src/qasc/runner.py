"""Trusted unittest entry point launched with Python's ``-I -B`` switches.

Import the standard library test runner before admitting the generated project
to the module search path. Structured results replace parsing arbitrary stdout.
This isolates runner imports; it is not a sandbox for the generated tests.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
import traceback
import unittest


def _write_result(destination: Path, result: dict) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".runner-", suffix=".tmp", dir=destination.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def run_tests(project: Path, destination: Path) -> dict:
    """Discover actual tests and persist their result even if discovery fails."""
    result = {"tests_run": 0, "failures": 0, "errors": 0, "skipped": 0, "successful": False}
    try:
        project = project.resolve(strict=True)
        if not project.is_dir():
            raise ValueError("Project must be an existing directory")
        # Case-insensitive checks also enforce portability when run on POSIX.
        if any(child.name.casefold() in {"unittest", "unittest.py"} for child in project.iterdir()):
            raise ValueError("Project cannot contain top-level unittest.py or unittest/; these shadow the trusted test runner")
        tests = project / "tests"
        if not tests.is_dir():
            raise ValueError("Project does not contain a tests directory")
        # unittest and all of this runner's dependencies are already imported.
        sys.path.insert(0, str(project))
        suite = unittest.TestLoader().discover(str(tests), pattern="test_*.py")
        count = suite.countTestCases()
        result["tests_discovered"] = count
        if count == 0:
            result["error"] = "No unittest test cases were discovered"
        else:
            observed = unittest.TextTestRunner(stream=sys.stderr, verbosity=2).run(suite)
            substantive_tests = observed.testsRun - len(observed.skipped) - len(observed.expectedFailures)
            result.update({
                "tests_run": observed.testsRun,
                "substantive_tests": substantive_tests,
                "failures": len(observed.failures),
                "errors": len(observed.errors),
                "skipped": len(observed.skipped),
                "expected_failures": len(observed.expectedFailures),
                "unexpected_successes": len(observed.unexpectedSuccesses),
                "successful": substantive_tests > 0 and observed.wasSuccessful(),
            })
            if substantive_tests == 0:
                result["error"] = "No substantive tests ran; every test was skipped or an expected failure"
    except BaseException as exc:
        # Tests can raise SystemExit/KeyboardInterrupt during module import.
        # The process still emits a failed receipt rather than silently omitting it.
        result["errors"] = max(1, result["errors"])
        result["successful"] = False
        result["error"] = f"{type(exc).__name__}: {exc}"
        traceback.print_exc(file=sys.stderr)
    _write_result(destination, result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run QASC project tests with a trusted unittest import")
    parser.add_argument("--project", required=True, type=Path)
    parser.add_argument("--result", required=True, type=Path)
    args = parser.parse_args(argv)
    result = run_tests(args.project, args.result)
    return 0 if result["successful"] and result["tests_run"] > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
