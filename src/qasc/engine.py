"""Bounded creation/correction workflow. Model proposals never become shell commands."""
from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
import sys
import uuid
import zipfile

from .execution import execute
from .model import ModelAdapter, parse_json_response
from .project import Project, ProjectError, atomic_json, digest, read_json, safe_path, utc_now, validate_files

FILE_SCHEMA = {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
               "required": ["path", "content"], "additionalProperties": False}
PROJECT_SCHEMA = {
    "type": "object", "properties": {
        "requirements": {"type": "array", "items": {"type": "string"}, "minItems": 1},
        "acceptance_criteria": {"type": "array", "items": {"type": "string"}, "minItems": 1},
        "architecture": {"type": "string"}, "entrypoint": {"type": "string"},
        "files": {"type": "array", "items": FILE_SCHEMA, "minItems": 2}},
    "required": ["requirements", "acceptance_criteria", "architecture", "entrypoint", "files"],
    "additionalProperties": False,
}
CORRECTION_SCHEMA = {"type": "object", "properties": {"diagnosis": {"type": "string"},
                     "changes": {"type": "array", "items": FILE_SCHEMA, "minItems": 1}},
                     "required": ["diagnosis", "changes"], "additionalProperties": False}
SYSTEM = """You are the software designer for QASC. Return only the requested JSON object.
Implement a small, usable Python 3.11+ standard-library application with multiple files.
Use only relative portable file paths. Include an executable Python entrypoint and
real unittest tests in tests/test_*.py. The engine uses a trusted isolated unittest
runner with discovery in tests/. It rejects zero-test success and unittest.py shadowing.
Use no dependencies, network access, installers, external commands, or writes outside the project.
Tests must use temporary directories for output. Do not create or edit .qasc or engine metadata.
The operator acceptance cases specify exact stdout, stderr when supplied, and exit codes.
Implement requirements, not a test-specific shortcut. Keep source concise for a local model.
"""


def is_test(path: str) -> bool:
    return path.casefold().startswith("tests/") or Path(path).name.casefold().startswith("test_")


def clean_receipt(receipt: dict) -> bool:
    inventory = receipt.get("inventory_errors") or {}
    inventory_failed = any(inventory.values()) if isinstance(inventory, dict) else bool(inventory)
    return not inventory_failed and not any(receipt.get(key) for key in ("timed_out", "error", "capture_incomplete", "capture_errors", "termination_error"))


class Engine:
    def __init__(self, adapter: ModelAdapter, *, prompt_char_limit: int = 18_000):
        self.adapter = adapter
        self.prompt_char_limit = prompt_char_limit

    def _ask(self, project: Project, state: dict, stage: str, payload: dict, schema: dict) -> tuple[dict, dict]:
        messages = [{"role": "system", "content": SYSTEM},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}]
        size = sum(len(m["content"]) for m in messages)
        if size > self.prompt_char_limit:
            raise ProjectError(f"Compact prompt is {size} characters; limit is {self.prompt_char_limit}. Split this project into smaller requirements.")
        call_id = f"{stage}-{uuid.uuid4().hex[:12]}"
        directory = project.meta / "model" / call_id
        adapter_settings = {key: getattr(self.adapter, key) for key in ("base_url", "model", "timeout", "max_tokens") if hasattr(self.adapter, key)}
        atomic_json(directory / "request.json", {"at": utc_now(), "stage": stage, "messages": messages, "adapter_settings": adapter_settings,
                    "response_schema": schema, "prompt_characters": size, "provenance": "qasc_orchestration"})
        state["status"] = stage
        self._event(state, stage, {"call_id": call_id})
        project.save(state)
        try:
            result = self.adapter.generate(messages, response_schema=schema)
            atomic_json(directory / "response.json", {"at": utc_now(), **asdict(result), "provenance": "ai_model_response"})
            parsed = parse_json_response(result.content)
        except Exception as exc:
            atomic_json(directory / "error.json", {"at": utc_now(), "error": str(exc), "raw": getattr(exc, "raw", None)})
            raise
        state["adapter"].update(adapter_settings)
        state["adapter"]["model"] = result.model
        return parsed, {"kind": "ai_generated_application", "model": result.model, "call_id": call_id}

    @staticmethod
    def _event(state: dict, kind: str, data: dict) -> None:
        state.setdefault("decisions", []).append({"at": utc_now(), "kind": kind, **data})

    def generate(self, project: Project, state: dict) -> None:
        payload = {"task": "Interpret the request, design the application, and implement all files using the response schema.",
                   "human_request": state["request"], "operator_acceptance": state["acceptance"],
                   "stack": "python-stdlib", "required_output_keys": list(PROJECT_SCHEMA["properties"])}
        response, provenance = self._ask(project, state, "generating", payload, PROJECT_SCHEMA)
        for key in ("requirements", "acceptance_criteria"):
            if not isinstance(response.get(key), list) or not response[key] or not all(isinstance(x, str) and x.strip() for x in response[key]):
                raise ProjectError(f"Model response needs nonempty {key}")
        if not isinstance(response.get("architecture"), str) or not response["architecture"].strip():
            raise ProjectError("Model response needs architecture")
        files = validate_files(response.get("files"), project.path)
        names = {item["path"] for item in files}
        entrypoint = response.get("entrypoint")
        safe_path(project.path, entrypoint)
        if entrypoint not in names or not entrypoint.endswith(".py") or is_test(entrypoint):
            raise ProjectError("Entrypoint must be a generated application Python file")
        if not any(n.startswith("tests/test_") and n.endswith(".py") for n in names):
            raise ProjectError("Model must supply tests/test_*.py")
        for key in ("requirements", "acceptance_criteria", "architecture", "entrypoint"):
            state[key] = response[key]
        state["stack"] = "python-stdlib"
        state["test_policy"] = {"command": ["{python}", "-I", "-B", "-X", "utf8", "-X", "pycache_prefix={unique_cache}", "{qasc_runner}", "--project", "{project}", "--result", "{result_json}"],
                                "origin": "qasc_fixed_runner", "model_tests_frozen": True}
        project.apply_revision(state, files, provenance)

    def verify(self, project: Project, state: dict, timeout: float = 30) -> dict:
        if not state["files"]:
            raise ProjectError("No generated files; run resume")
        before = project.fingerprint(state)
        state["status"] = "testing"
        project.save(state)
        receipt_dir = project.meta / "executions"
        runner_result = project.meta / "verifications" / f"runner-{uuid.uuid4().hex}.json"
        cache_option = f"pycache_prefix={project.meta / 'runtime' / uuid.uuid4().hex}"
        unit = execute(project.path, [sys.executable, "-I", "-B", "-X", "utf8", "-X", cache_option, str(Path(__file__).with_name("runner.py")),
                       "--project", str(project.path), "--result", str(runner_result)], timeout, receipt_dir)
        result = read_json(runner_result) if runner_result.is_file() else {}
        count = result.get("tests_run", 0)
        unit_passed = unit["exit_code"] == 0 and clean_receipt(unit) and result.get("successful") is True and type(count) is int and count > 0
        cases = []
        for case in (state.get("acceptance") or {}).get("cases", []):
            receipt = execute(project.path, [sys.executable, "-B", "-X", "utf8", "-X", cache_option, str(safe_path(project.path, state["entrypoint"])) , *case["args"]],
                              timeout, receipt_dir, stdin=case.get("stdin"))
            mismatches = []
            for key in ("stdout", "stderr", "exit_code"):
                # Normalize platform line endings only; no stripping significant whitespace.
                actual, expected = receipt.get(key), case.get(key)
                if isinstance(actual, str):
                    actual = actual.replace("\r\n", "\n")
                if isinstance(expected, str):
                    expected = expected.replace("\r\n", "\n")
                if key in case and actual != expected:
                    mismatches.append({"field": key, "expected": expected, "actual": actual})
            passed = not mismatches and clean_receipt(receipt) and not receipt.get("stdout_truncated") and not receipt.get("stderr_truncated")
            cases.append({"name": case["name"], "passed": passed, "receipt_id": receipt["id"], "mismatches": mismatches})
        try:
            after = project.fingerprint(state)
        except OSError:
            after = None
        source_unchanged = before == after
        passed = unit_passed and all(c["passed"] for c in cases) and source_unchanged
        verification = {"id": uuid.uuid4().hex[:12], "at": utc_now(), "revision": state["revision"],
                        "passed": passed, "unit_tests_passed": unit_passed, "unit_test_count": count,
                        "unit_receipt_id": unit["id"], "acceptance_cases": cases,
                        "independent_acceptance_passed": bool(cases) and all(c["passed"] for c in cases),
                        "source_unchanged": source_unchanged, "source_fingerprint": after,
                        "scope": "operator_acceptance_and_model_tests" if cases else "model_generated_tests_only",
                        "unit_feedback": {k: unit.get(k) for k in ("stdout", "stderr", "exit_code", "timed_out", "error")}}
        atomic_json(project.meta / "verifications" / f"{verification['id']}.json", verification)
        state["executions"].extend([unit["id"], *(c["receipt_id"] for c in cases)])
        state["last_verification"] = verification
        state["status"] = "verified" if passed else "test_failed"
        if passed:
            # Snapshot the exact files that passed, including operator edits since generation.
            verified_id = f"{state['revision']}-{verification['id']}"
            atomic_json(project.meta / "verified" / f"{verified_id}.json",
                        {"verification": verification, "files": project.source_files(state), "acceptance": state["acceptance"]})
            state["verified_revisions"].append({"id": verified_id, "revision": state["revision"],
                                                "verification_id": verification["id"], "scope": verification["scope"]})
        else:
            state["failures"].append({"at": utc_now(), "stage": "verification", "verification_id": verification["id"],
                                       "error": "Configured tests failed, no tests ran, or managed sources changed during execution"})
        project.save(state)
        return verification

    def correct(self, project: Project, state: dict) -> bool:
        previous = project.fingerprint(state)
        feedback = state["last_verification"]
        # Bounded failure tail; complete outputs remain in the execution receipts.
        compact_feedback = dict(feedback)
        compact_feedback["unit_feedback"] = {k: v[-3500:] if isinstance(v, str) else v
                                             for k, v in feedback["unit_feedback"].items()}
        payload = {"task": "Diagnose the actual failure and return targeted replacement source files in changes. Do not change tests or acceptance criteria.",
                   "human_request": state["request"], "requirements": state["requirements"],
                   "architecture": state["architecture"], "entrypoint": state["entrypoint"],
                   "operator_acceptance": state["acceptance"], "files": project.source_files(state),
                   "execution_feedback": compact_feedback}
        response, provenance = self._ask(project, state, "correcting", payload, CORRECTION_SCHEMA)
        if not isinstance(response.get("diagnosis"), str) or not response["diagnosis"].strip():
            raise ProjectError("Correction requires a diagnosis")
        changes = validate_files(response.get("changes"), project.path)
        files = {item["path"]: item for item in project.source_files(state)}
        for change in changes:
            if is_test(change["path"]):
                raise ProjectError("Correction cannot modify frozen verification tests")
            files[change["path"]] = change
        # Compare contents before creating a candidate revision.
        changed = any(files[c["path"]]["content"] != safe_path(project.path, c["path"]).read_text(encoding="utf-8")
                      if safe_path(project.path, c["path"]).exists() else True for c in changes)
        if not changed:
            state["status"] = "stalled"
            state["limitations"].append("Model returned an identical correction; stopped without repeating execution")
            project.save(state)
            return False
        revision = project.apply_revision(state, list(files.values()), provenance)
        candidate = project.fingerprint(state)
        prior = [c["before_fingerprint"] for c in state["corrections"]]
        state["corrections"].append({"at": utc_now(), "revision": revision, "diagnosis": response["diagnosis"],
                                     "paths": [c["path"] for c in changes], "before_fingerprint": previous,
                                     "after_fingerprint": candidate, "feedback_id": feedback["id"]})
        if candidate in prior:
            state["status"] = "stalled"
            state["limitations"].append("Repeated source version detected in correction cycle")
            project.save(state)
            return False
        project.save(state)
        return True

    def run(self, project: Project, *, generate_only: bool = False, max_corrections: int = 2, timeout: float = 30) -> dict:
        if not 0 <= max_corrections <= 10:
            raise ProjectError("max_corrections must be between 0 and 10")
        with project.lock():
            state = project.load()
            try:
                project.finish_pending(state)
                if not state["files"]:
                    self.generate(project, state)
                if generate_only:
                    return state
                for attempt in range(max_corrections + 1):
                    if self.verify(project, state, timeout)["passed"]:
                        return state
                    if attempt == max_corrections:
                        state["limitations"].append(f"Correction budget exhausted ({max_corrections} this run)")
                        project.save(state)
                        return state
                    if not self.correct(project, state):
                        return state
            except (Exception, KeyboardInterrupt) as exc:
                project.record_failure(state, state["status"], str(exc) or "Interrupted by operator; resume from persisted state")
                raise
        return state


def package_project(project: Project) -> dict:
    """Create and verify a source archive, never claim a native executable/installer."""
    with project.lock():
        state = project.load()
        last = state.get("last_verification")
        if not last or not last["passed"] or project.fingerprint(state) != last["source_fingerprint"]:
            raise ProjectError("Packaging requires current source to pass qasc test")
        output = project.meta / "deliveries" / f"{project.name}-{last['id']}.zip"
        output.parent.mkdir(parents=True, exist_ok=True)
        if output.exists():
            raise ProjectError(f"Delivery already exists: {output}")
        manifest = {"kind": "source_archive", "created_at": utc_now(), "project": project.name,
                    "revision": state["revision"], "verification_id": last["id"], "verification_scope": last["scope"],
                    "entrypoint": state["entrypoint"], "runtime": "Python >=3.11", "files": [],
                    "provenance": "automatically_generated_delivery_artifact"}
        with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED) as archive:
            for name in state["files"]:
                source = safe_path(project.path, name)
                data = source.read_bytes()
                archive.writestr(f"{project.name}/{name}", data)
                manifest["files"].append({"path": name, "sha256": digest(data)})
            archive.writestr("QASC-DELIVERY.json", json.dumps(manifest, indent=2))
        with zipfile.ZipFile(output) as archive:
            if archive.testzip() is not None:
                raise ProjectError("Source archive integrity check failed")
            for item in manifest["files"]:
                if digest(archive.read(f"{project.name}/{item['path']}")) != item["sha256"]:
                    raise ProjectError("Delivery file checksum mismatch")
        receipt = {**manifest, "path": str(output), "sha256": digest(output.read_bytes()), "archive_verified": True,
                   "executable_created": False, "installer_created": False}
        atomic_json(output.with_suffix(".json"), receipt)
        state.setdefault("deliveries", []).append(receipt)
        project.save(state)
        return receipt
