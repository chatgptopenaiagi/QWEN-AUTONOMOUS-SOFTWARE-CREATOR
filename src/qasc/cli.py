"""PowerShell-friendly JSON CLI. Exit 0 means command success, 1 failed verification, 2 error."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

from . import __version__
from .discovery import discover_tools
from .engine import Engine, package_project
from .model import OpenAICompatibleAdapter
from .project import Project, ProjectError, read_json


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="qasc", description="Local-first autonomous software creation")
    root.add_argument("--version", action="version", version=f"qasc {__version__}")
    root.add_argument("--endpoint", default=os.environ.get("QASC_ENDPOINT"), help="Local inference URL (default http://127.0.0.1:8080)")
    root.add_argument("--model", default=os.environ.get("QASC_MODEL"), help="Model ID; default discovered from endpoint")
    root.add_argument("--projects-dir", type=Path, default=Path(os.environ.get("QASC_PROJECTS_DIR", "projects")))
    root.add_argument("--model-timeout", type=float, default=None, help="Inference HTTP timeout in seconds (default 180)")
    root.add_argument("--max-tokens", type=int, default=None, help="Maximum model output tokens (default 3000)")
    sub = root.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor", help="Inspect local tools and model connectivity")
    sub.add_parser("models", help="Report configured adapter availability")
    create = sub.add_parser("create", help="Generate a new isolated Python project")
    create.add_argument("request", nargs="?")
    create.add_argument("--request-file", type=Path)
    create.add_argument("--name", required=True)
    create.add_argument("--acceptance", type=Path, help="External acceptance JSON file")
    create.add_argument("--run", action="store_true", help="Execute tests and bounded corrections after generation")
    create.add_argument("--max-corrections", type=int, default=2)
    create.add_argument("--timeout", type=float, default=30)
    test = sub.add_parser("test", help="Execute existing project tests and acceptance cases")
    test.add_argument("name")
    test.add_argument("--timeout", type=float, default=30)
    resume = sub.add_parser("resume", help="Resume generation, testing and bounded correction from disk")
    resume.add_argument("name")
    resume.add_argument("--max-corrections", type=int, default=2)
    resume.add_argument("--timeout", type=float, default=30)
    status = sub.add_parser("status", help="Inspect project state and latest actual verification")
    status.add_argument("name", nargs="?")
    package = sub.add_parser("package", help="Create a checked source ZIP of currently passing files")
    package.add_argument("name")
    return root


def make_adapter(args, state: dict | None = None) -> OpenAICompatibleAdapter:
    saved = (state or {}).get("adapter", {})
    return OpenAICompatibleAdapter(
        base_url=args.endpoint or saved.get("base_url") or "http://127.0.0.1:8080",
        model=args.model or saved.get("model"), timeout=args.model_timeout if args.model_timeout is not None else saved.get("timeout", 180),
        max_tokens=args.max_tokens if args.max_tokens is not None else saved.get("max_tokens", 3000))


def status_summary(project: Project, state: dict) -> dict:
    last = state.get("last_verification")
    current = None
    if last:
        try:
            current = project.fingerprint(state) == last["source_fingerprint"]
        except (OSError, ProjectError):
            current = False
    unresolved = [] if last and last["passed"] and current else state["failures"][-3:] + state["limitations"][-3:]
    if last and current is False:
        unresolved.append("Managed source differs from the last verification; run qasc test")
    return {"name": state["name"], "path": str(project.path), "status": "source_changed" if last and current is False else state["status"],
            "revision": state["revision"], "requirements": state["requirements"], "entrypoint": state["entrypoint"],
            "files": state["files"], "last_verification": last, "verification_matches_current_source": current,
            "corrections": len(state["corrections"]), "verified_versions": len(state["verified_revisions"]),
            "unresolved_problems": unresolved,
            "metadata_path": str(project.meta), "updated_at": state["updated_at"]}


def emit(value: object) -> None:
    print(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False))


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command in {"doctor", "models"}:
            info = make_adapter(args).info()
            result = {"qasc_version": __version__, "adapters": [info]}
            if args.command == "doctor":
                result["discovery"] = discover_tools()
                result["execution_policy"] = "Project cwd and local temp, no shell, bounded timeout; current user permissions, no OS sandbox"
            emit(result)
            return 0 if info["available"] else 1
        if args.command == "status" and args.name is None:
            projects = []
            if args.projects_dir.exists():
                for path in sorted(args.projects_dir.iterdir()):
                    if (path / ".qasc" / "state.json").is_file():
                        project = Project(args.projects_dir, path.name)
                        projects.append(status_summary(project, project.load()))
            emit({"projects_dir": str(args.projects_dir.resolve()), "projects": projects})
            return 0
        project = Project(args.projects_dir, args.name)
        if args.command == "create":
            if bool(args.request) == bool(args.request_file):
                raise ProjectError("Supply either a request argument or --request-file")
            if not 0 <= args.max_corrections <= 10:
                raise ProjectError("max-corrections must be between 0 and 10")
            request = args.request or args.request_file.read_text(encoding="utf-8-sig")
            adapter = make_adapter(args)
            settings = {"id": adapter.adapter_id, "base_url": adapter.base_url, "model": adapter.model,
                        "timeout": adapter.timeout, "max_tokens": adapter.max_tokens}
            project.initialize(request, settings, read_json(args.acceptance) if args.acceptance else None)
            state = Engine(adapter).run(project, generate_only=not args.run,
                                        max_corrections=args.max_corrections, timeout=args.timeout)
        elif args.command == "resume":
            state = Engine(make_adapter(args, project.load())).run(project, max_corrections=args.max_corrections, timeout=args.timeout)
        elif args.command == "test":
            with project.lock():
                state = project.load()
                try:
                    Engine(make_adapter(args, state)).verify(project, state, args.timeout)
                except (Exception, KeyboardInterrupt) as exc:
                    project.record_failure(state, "testing", str(exc) or "Interrupted")
                    raise
        elif args.command == "package":
            emit(package_project(project))
            return 0
        else:
            state = project.load()
        emit(status_summary(project, state))
        return 0 if args.command == "status" or state["status"] in {"generated", "verified"} else 1
    except KeyboardInterrupt:
        emit({"error": "Interrupted. Project state is preserved; use qasc status/resume.", "type": "KeyboardInterrupt"})
        return 130
    except (Exception,) as exc:
        emit({"error": str(exc), "type": type(exc).__name__})
        return 2


if __name__ == "__main__":
    sys.exit(main())
