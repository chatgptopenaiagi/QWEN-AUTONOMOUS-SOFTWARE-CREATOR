"""Execute explicit argument vectors and record observable project changes.

The working directory and temporary files are scoped to a project. This is not
an operating-system sandbox: executed code retains the current user's access.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import signal
import stat
import subprocess
import threading
import time
from datetime import datetime, timezone
from uuid import uuid4


OUTPUT_LIMIT_BYTES = 64 * 1024
EXCLUDED_DIRECTORIES = frozenset({".qasc", ".git", "__pycache__"})


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root)
        return True
    except (OSError, ValueError):
        return False


def _snapshot(root: Path) -> tuple[dict, list[str]]:
    """Inventory regular files without following links or Windows reparse points."""
    files: dict = {}
    errors: list[str] = []

    def visit(directory: Path) -> None:
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    path = Path(entry.path)
                    relative = path.relative_to(root).as_posix()
                    try:
                        info = entry.stat(follow_symlinks=False)
                        attributes = getattr(info, "st_file_attributes", 0)
                        if entry.is_symlink() or attributes & getattr(
                            stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400
                        ):
                            continue
                        if not _inside(path, root):
                            continue
                        if stat.S_ISDIR(info.st_mode):
                            if entry.name not in EXCLUDED_DIRECTORIES:
                                visit(path)
                        elif stat.S_ISREG(info.st_mode):
                            digest = hashlib.sha256()
                            with path.open("rb") as source:
                                for block in iter(lambda: source.read(1024 * 1024), b""):
                                    digest.update(block)
                            files[relative] = {"sha256": digest.hexdigest(), "size": info.st_size}
                    except OSError as exc:
                        errors.append(f"{relative}: {type(exc).__name__}: {exc}")
        except OSError as exc:
            errors.append(f"{directory.relative_to(root).as_posix()}: {type(exc).__name__}: {exc}")

    visit(root)
    return files, errors


def _changes(before: dict, after: dict) -> dict:
    changes: dict = {"added": [], "modified": [], "deleted": []}
    for name in sorted(before.keys() | after.keys()):
        old, new = before.get(name), after.get(name)
        if old == new:
            continue
        kind = "added" if old is None else "deleted" if new is None else "modified"
        changes[kind].append({"path": name, "before": old, "after": new})
    return changes


class _Capture:
    """Drain a pipe while retaining a bounded beginning and end of its output."""

    def __init__(self, pipe) -> None:
        self.pipe = pipe
        self.head = bytearray()
        self.tail = bytearray()
        self.total = 0
        self.error: str | None = None
        self.lock = threading.Lock()
        self.thread = threading.Thread(target=self._read, daemon=True)

    def _read(self) -> None:
        try:
            while chunk := self.pipe.read(8192):
                with self.lock:
                    self.total += len(chunk)
                    head_room = OUTPUT_LIMIT_BYTES // 2 - len(self.head)
                    if head_room:
                        self.head.extend(chunk[:head_room])
                        chunk = chunk[head_room:]
                    if chunk:
                        self.tail.extend(chunk)
                        del self.tail[: max(0, len(self.tail) - OUTPUT_LIMIT_BYTES // 2)]
        except (OSError, ValueError) as exc:
            self.error = f"{type(exc).__name__}: {exc}"

    def result(self) -> tuple[str, bool, int]:
        with self.lock:
            truncated = self.total > OUTPUT_LIMIT_BYTES
            separator = b"\n... QASC OUTPUT TRUNCATED ...\n" if truncated else b""
            output = bytes(self.head) + separator + bytes(self.tail)
            return output.decode("utf-8", errors="replace"), truncated, self.total


def _terminate_tree(process: subprocess.Popen) -> str | None:
    if os.name == "nt":
        # Resolve a system executable explicitly instead of trusting project PATH.
        taskkill = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "taskkill.exe"
        try:
            result = subprocess.run(
                [str(taskkill), "/PID", str(process.pid), "/T", "/F"],
                capture_output=True, timeout=10, check=False,
            )
            if result.returncode == 0 or process.poll() is not None:
                return None
            problem = f"taskkill exited {result.returncode}"
        except (OSError, subprocess.TimeoutExpired) as exc:
            problem = f"taskkill failed: {exc}"
        try:
            process.kill()
        except OSError:
            pass
        return problem
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except OSError as exc:
        process.kill()
        return f"Process-group termination failed: {exc}"
    return None


def _atomic_json(path: Path, value: dict) -> None:
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as output:
            json.dump(value, output, indent=2, ensure_ascii=False)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def execute(
    project_dir: Path,
    command: list[str],
    timeout: float = 60,
    receipt_dir: Path | None = None,
    *,
    stdin: str | None = None,
) -> dict:
    """Execute a command with no implicit shell, returning an execution receipt.

    Invalid inputs raise ValueError. Spawn errors and timeouts are recorded in
    the returned receipt. When supplied, receipt_dir must be inside project_dir.
    Receipts exclude .qasc, .git, __pycache__, symlinks and Windows junctions
    from the before/after inventory. File changes outside the project cannot be
    observed or prevented by this engine.
    """
    if not isinstance(command, list) or not command or any(
        not isinstance(part, str) or "\0" in part for part in command
    ) or not command[0].strip():
        raise ValueError("command must be a nonempty list of strings without NUL bytes")
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be a finite positive number of seconds")
    if stdin is not None and not isinstance(stdin, str):
        raise ValueError("stdin must be a string or None")
    root = Path(project_dir).resolve()
    if not root.is_dir():
        raise ValueError(f"Project directory does not exist: {root}")
    destination = None
    if receipt_dir is not None:
        destination = Path(receipt_dir)
        if not destination.is_absolute():
            destination = root / destination
        destination = destination.resolve()
        if not _inside(destination, root):
            raise ValueError("receipt_dir must be inside the project directory")
        destination.mkdir(parents=True, exist_ok=True)
    temporary = root / ".qasc" / "runtime" / "tmp"
    if not _inside(temporary, root):
        raise ValueError("Project runtime directory resolves outside the project")
    temporary.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    environment.update({"TEMP": str(temporary), "TMP": str(temporary), "TMPDIR": str(temporary)})
    environment.setdefault("PYTHONIOENCODING", "utf-8")
    executable = shutil.which(command[0], path=environment.get("PATH")) or command[0]
    if os.name == "nt" and Path(executable).suffix.lower() in {".bat", ".cmd"}:
        raise ValueError("Windows batch files require an explicit shell command")

    before, before_errors = _snapshot(root)
    receipt_id = uuid4().hex
    receipt = {
        "schema_version": 1,
        "receipt_id": receipt_id,
        "id": receipt_id,
        "command": list(command),
        "cwd": str(root),
        "started_at": _utc_now(),
        "finished_at": None,
        "elapsed_seconds": 0.0,
        "timeout_seconds": timeout,
        "stdin": stdin,
        "stdout": "",
        "stderr": "",
        "stdout_truncated": False,
        "stderr_truncated": False,
        "stdout_bytes": 0,
        "stderr_bytes": 0,
        "exit_code": None,
        "timed_out": False,
        "interrupted": False,
        "error": None,
        "capture_errors": [],
        "capture_incomplete": False,
        "termination_error": None,
        "changes": {},
        "inventory_errors": {"before": before_errors, "after": []},
        "receipt_path": str(destination / f"{receipt_id}.json") if destination else None,
    }
    started = time.monotonic()
    try:
        options = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
        process = subprocess.Popen(
            command, cwd=root, env=environment,
            stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False, bufsize=0,
            **options,
        )
        captures = [_Capture(process.stdout), _Capture(process.stderr)]
        for capture in captures:
            capture.thread.start()
        if stdin is not None:
            def write_input() -> None:
                try:
                    with process.stdin:
                        pending = memoryview(stdin.encode("utf-8"))
                        while pending:
                            written = process.stdin.write(pending)
                            if not written:
                                break
                            pending = pending[written:]
                except (BrokenPipeError, OSError, ValueError):
                    # A command may deliberately close stdin without consuming it.
                    pass
            threading.Thread(target=write_input, daemon=True).start()
        try:
            process.wait(timeout=timeout)
        except (subprocess.TimeoutExpired, KeyboardInterrupt) as exc:
            receipt["interrupted"] = isinstance(exc, KeyboardInterrupt)
            receipt["timed_out"] = not receipt["interrupted"]
            receipt["error"] = "Interrupted by operator" if receipt["interrupted"] else f"Command exceeded {timeout:g} seconds"
            receipt["termination_error"] = _terminate_tree(process)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                receipt["termination_error"] = "Process did not exit after forced termination"
        receipt["exit_code"] = process.poll()
        for name, capture in zip(("stdout", "stderr"), captures):
            capture.thread.join(timeout=1)
            if capture.thread.is_alive():
                receipt["capture_incomplete"] = True
            receipt[name], receipt[f"{name}_truncated"], receipt[f"{name}_bytes"] = capture.result()
            if capture.error:
                receipt["capture_errors"].append(f"{name}: {capture.error}")
            capture.pipe.close()
    except OSError as exc:
        receipt["error"] = f"{type(exc).__name__}: {exc}"
    receipt["finished_at"] = _utc_now()
    receipt["elapsed_seconds"] = round(time.monotonic() - started, 6)
    after, after_errors = _snapshot(root)
    receipt["changes"] = _changes(before, after)
    receipt["inventory_errors"]["after"] = after_errors
    if destination:
        _atomic_json(Path(receipt["receipt_path"]), receipt)
    if receipt["interrupted"]:
        raise KeyboardInterrupt()
    return receipt
