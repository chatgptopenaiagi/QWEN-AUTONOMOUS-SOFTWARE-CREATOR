"""Persistent project state, validated paths, and immutable source revisions."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import tempfile
import uuid


class ProjectError(ValueError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".tmp-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def read_json(path: Path) -> dict:
    try:
        result = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise ProjectError(f"Cannot read {path}: {exc}") from exc
    if not isinstance(result, dict):
        raise ProjectError(f"Expected JSON object: {path}")
    return result


def atomic_source(path: Path, data: bytes) -> None:
    """Replace a directory entry rather than writing through a hardlink."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".tmp-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def linked(path: Path) -> bool:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    # Python 3.11 does not expose Path.is_junction. Check reparse attributes
    # directly so junctions cannot alias a second project within the same root.
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def safe_path(root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative or len(relative) > 200:
        raise ProjectError("File path must be a nonempty relative path of at most 200 characters")
    if "\\" in relative or ":" in relative or any(ord(c) < 32 for c in relative):
        raise ProjectError(f"Unsafe file path: {relative!r}")
    parts = relative.split("/")
    if any(p in ("", ".", "..") or p.startswith(".") or p.endswith((" ", ".")) for p in parts):
        raise ProjectError(f"Unsafe file path: {relative!r}")
    reserved = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(10)), *(f"LPT{i}" for i in range(10))}
    if any(p.split(".")[0].upper() in reserved or re.search(r'[<>"|?*]', p) for p in parts):
        raise ProjectError(f"Nonportable file path: {relative!r}")
    root = root.resolve()
    path = root.joinpath(*PurePosixPath(relative).parts)
    if not path.resolve().is_relative_to(root):
        raise ProjectError(f"File escapes project: {relative!r}")
    cursor = root
    for part in parts:
        cursor = cursor / part
        if linked(cursor):
            raise ProjectError(f"Linked paths are not managed: {relative!r}")
    return path


def validate_files(files: object, root: Path) -> list[dict]:
    if not isinstance(files, list) or not 1 <= len(files) <= 40:
        raise ProjectError("Response must contain 1 to 40 files")
    result, seen, total = [], set(), 0
    for item in files:
        if not isinstance(item, dict) or not isinstance(item.get("content"), str):
            raise ProjectError("Each file needs path and string content")
        path = item.get("path")
        target = safe_path(root, path)
        if target.suffix.lower() not in {".py", ".md", ".txt", ".json", ".toml", ".cfg", ".ini", ".csv"}:
            raise ProjectError(f"Unsupported generated file type: {path}")
        key = path.casefold()
        if key in seen:
            raise ProjectError(f"Duplicate file: {path}")
        seen.add(key)
        total += len(item["content"].encode("utf-8"))
        result.append({"path": path, "content": item["content"]})
    if total > 256_000:
        raise ProjectError("Generated source exceeds 256 KB project limit")
    for name in seen:
        if any(parent in seen for parent in [str(p).replace('\\', '/') for p in PurePosixPath(name).parents] if parent != "."):
            raise ProjectError("A generated file cannot also be a directory")
    return result


def validate_acceptance(value: dict | None) -> dict | None:
    if value is None:
        return None
    cases = value.get("cases")
    if not isinstance(cases, list) or not 1 <= len(cases) <= 40:
        raise ProjectError("Acceptance needs 1 to 40 cases")
    normalized = []
    for index, case in enumerate(cases):
        if not isinstance(case, dict) or set(case) - {"name", "args", "stdin", "stdout", "stderr", "exit_code"}:
            raise ProjectError("Invalid acceptance case fields")
        args = case.get("args", [])
        if not isinstance(args, list) or not all(isinstance(a, str) and "\x00" not in a for a in args):
            raise ProjectError("Acceptance args must be strings")
        if "stdout" not in case or not isinstance(case["stdout"], str):
            raise ProjectError("Every acceptance case needs exact expected stdout")
        for key in ("name", "stderr", "stdin"):
            if key in case and not isinstance(case[key], str):
                raise ProjectError(f"Acceptance {key} must be a string")
        code = case.get("exit_code", 0)
        if type(code) is not int:
            raise ProjectError("Acceptance exit_code must be an integer")
        normalized.append({**case, "name": case.get("name", f"case-{index + 1}"), "args": args, "exit_code": code})
    if len(json.dumps(normalized)) > 32_000:
        raise ProjectError("Acceptance specification exceeds 32 KB")
    return {"cases": normalized, "provenance": "operator_supplied_verification"}


class Project:
    def __init__(self, projects_dir: Path, name: str):
        if not re.fullmatch(r"[a-z][a-z0-9-]{0,63}", name):
            raise ProjectError("Project name must match [a-z][a-z0-9-]{0,63}")
        self.root = projects_dir.resolve()
        self.path = self.root / name
        if linked(self.path) or not self.path.resolve().is_relative_to(self.root):
            raise ProjectError("Project directory must not be a symlink or junction")
        self.meta = self.path / ".qasc"
        if linked(self.meta):
            raise ProjectError("Project metadata must not be a symlink or junction")
        self.name = name

    def initialize(self, request: str, adapter: dict, acceptance: dict | None = None) -> dict:
        if not request.strip() or len(request) > 8_000:
            raise ProjectError("Request must contain 1 to 8000 characters")
        acceptance = validate_acceptance(acceptance)
        self.root.mkdir(parents=True, exist_ok=True)
        try:
            self.path.mkdir()
        except FileExistsError as exc:
            raise ProjectError(f"Project already exists; use status/resume: {self.path}") from exc
        self.meta.mkdir()
        state = {"schema_version": 1, "name": self.name, "created_at": utc_now(), "updated_at": utc_now(),
                 "status": "requested", "request": request, "request_provenance": "human_requirement",
                 "adapter": adapter, "requirements": [], "acceptance_criteria": [], "architecture": None,
                 "entrypoint": None, "files": [], "revision": None, "history": [], "executions": [],
                 "failures": [], "corrections": [], "verified_revisions": [], "last_verification": None,
                 "acceptance": acceptance, "limitations": []}
        self.save(state)
        return state

    def load(self) -> dict:
        state = read_json(self.meta / "state.json")
        if state.get("schema_version") != 1 or state.get("name") != self.name:
            raise ProjectError("Unsupported or inconsistent project state")
        return state

    def save(self, state: dict) -> None:
        state["updated_at"] = utc_now()
        atomic_json(self.meta / "state.json", state)

    def record_failure(self, state: dict, stage: str, error: str) -> None:
        state["status"] = "blocked"
        state["failures"].append({"at": utc_now(), "stage": stage, "error": error})
        self.save(state)

    @contextmanager
    def lock(self):
        lock_path = self.meta / "operation.lock"
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            raise ProjectError(f"Project is locked. If no QASC operation is running, remove {lock_path} to recover.") from exc
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump({"pid": os.getpid(), "created_at": utc_now()}, stream)
        try:
            yield
        finally:
            lock_path.unlink(missing_ok=True)

    def source_files(self, state: dict) -> list[dict]:
        return [{"path": name, "content": safe_path(self.path, name).read_text(encoding="utf-8")}
                for name in state["files"]]

    def fingerprint(self, state: dict) -> str:
        data = [{"path": name, "sha256": digest(safe_path(self.path, name).read_bytes())}
                for name in sorted(state["files"])]
        return digest(json.dumps(data, sort_keys=True).encode())

    def apply_revision(self, state: dict, files: list[dict], provenance: dict) -> str:
        files = validate_files(files, self.path)
        current = set(state["files"])
        for item in files:
            target = safe_path(self.path, item["path"])
            if target.exists() and item["path"] not in current:
                raise ProjectError(f"Refusing to overwrite unmanaged file: {item['path']}")
        revision = f"{len(state['history']) + 1:04d}-{uuid.uuid4().hex[:8]}"
        directory = self.meta / "revisions" / revision
        directory.mkdir(parents=True)
        before = {name: digest(safe_path(self.path, name).read_bytes()) for name in state["files"]}
        manifest = {"revision": revision, "created_at": utc_now(), "provenance": provenance, "files": [],
                    "before_hashes": before}
        for item in files:
            target = safe_path(directory / "source", item["path"])
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(item["content"], encoding="utf-8", newline="\n")
            manifest["files"].append({"path": item["path"], "sha256": digest(target.read_bytes())})
        atomic_json(directory / "manifest.json", manifest)
        state["pending_revision"] = revision
        state["status"] = "applying"
        self.save(state)
        self.finish_pending(state)
        return revision

    def finish_pending(self, state: dict) -> None:
        revision = state.get("pending_revision")
        if not revision:
            return
        directory = self.meta / "revisions" / revision
        manifest = read_json(directory / "manifest.json")
        new_files = {f["path"] for f in manifest["files"]}
        for item in manifest["files"]:
            source = safe_path(directory / "source", item["path"])
            if digest(source.read_bytes()) != item["sha256"]:
                raise ProjectError("Revision snapshot checksum mismatch")
        before = manifest["before_hashes"]
        intended = {item["path"]: item["sha256"] for item in manifest["files"]}
        for name in set(before) | new_files:
            target = safe_path(self.path, name)
            actual = digest(target.read_bytes()) if target.exists() else None
            if actual not in {before.get(name), intended.get(name)}:
                raise ProjectError(f"Revision recovery conflict; preserve operator file: {name}")
        for name in set(state["files"]) - new_files:
            safe_path(self.path, name).unlink(missing_ok=True)
        for item in manifest["files"]:
            target = safe_path(self.path, item["path"])
            target.parent.mkdir(parents=True, exist_ok=True)
            atomic_source(target, safe_path(directory / "source", item["path"]).read_bytes())
        state["files"] = sorted(new_files)
        state["revision"] = revision
        state["history"].append(manifest)
        state.pop("pending_revision", None)
        state["status"] = "generated"
        state["last_verification"] = None
        self.save(state)
