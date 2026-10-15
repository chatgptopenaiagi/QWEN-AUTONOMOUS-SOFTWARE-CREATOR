"""Deliberately break the example's uppercase branch to exercise real correction.

Only use with the greeting validation fixture. The previously verified snapshot
is preserved. This is a Codex-authored validation operation, not a model defect.
"""
from pathlib import Path
import argparse

from qasc.project import Project, ProjectError, atomic_json, atomic_source, digest, utc_now


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--projects-dir", type=Path, default=Path("projects"))
    parser.add_argument("--name", default="qwen-greeting")
    args = parser.parse_args()
    project = Project(args.projects_dir, args.name)
    with project.lock():
        state = project.load()
        last = state.get("last_verification")
        if not last or not last["passed"] or project.fingerprint(state) != last["source_fingerprint"]:
            raise ProjectError("Fault injection requires an unchanged, verified demo")
        source = project.path / "greeting.py"
        before = source.read_bytes()
        if before.count(b"greeting.upper()") != 1:
            raise ProjectError("Expected exactly one greeting.upper() expression; no edit performed")
        after = before.replace(b"greeting.upper()", b"greeting.lower()")
        record = {"at": utc_now(), "provenance": "codex_validation_fault_injection", "path": "greeting.py",
                  "reason": "Exercise failed execution, persisted state, live Qwen diagnosis and targeted repair",
                  "before_sha256": digest(before), "after_sha256": digest(after),
                  "original_source": before.decode("utf-8"), "injected_source": after.decode("utf-8"),
                  "prior_verification_id": last["id"]}
        atomic_json(project.meta / "validation" / "injected-fault.json", record)
        atomic_source(source, after)
        state["request_provenance"] = "codex_authored_validation_fixture"
        state["acceptance"]["provenance"] = "codex_authored_independent_validation_fixture"
        state.setdefault("decisions", []).append(record)
        project.save(state)
        print("Injected recorded lowercase fault; original verified source remains preserved. Run qasc resume.")


if __name__ == "__main__":
    main()
