# Working on QASC

QASC is a local-first software creation platform. Keep the distinction between the human's requirements, model-authored application code, Codex-authored infrastructure, test fixtures, and automatically produced artifacts explicit.

## Scope and neighboring projects

- Work inside `I:\QWEN-AUTONOMOUS-SOFTWARE-CREATOR` unless the user explicitly authorizes another location.
- Do not modify, move, delete, restructure, or restart anything in `I:\LocalAI`. Another engineering session owns that installation. Read-only inspection and requests to its existing local inference API are allowed.
- Do not install or replace Codex CLI as part of QASC work.
- Inspect existing local and remote repository state before publishing changes. Do not overwrite unrelated work or replace an existing repository.

## Engineering rules

- Prefer Python's standard library for the initial orchestrator. Keep external AI services optional; the initial workflow must support the local llama.cpp API.
- Validate model output before writing files. Reject paths that escape the project or target QASC's control records.
- Preserve project isolation, source snapshots, original requests, model exchanges, execution receipts, and verified versions.
- Keep test execution bounded by a timeout and scoped to the intended working directory. Use argument arrays with `shell=False`; do not interpolate model text into shell commands.
- Do not describe a working directory, path checks, or a timeout as an operating system sandbox.
- Preserve independent acceptance cases during model corrections. Do not weaken checks merely to obtain a successful status.
- Preserve the trusted runner's standard-library import boundary and structured test counts. Zero tests or incomplete execution evidence cannot establish verification.
- Keep source-revision recovery checks and atomic replacement intact. Refuse conflicting edits instead of overwriting them during resume.
- Use actual process results to determine execution and verification status. A model's claim that its code works is not evidence.
- Keep resume prompts based on persisted, bounded project context rather than full conversation history.
- Keep changes focused on the user's software creation mission. Do not add speculative dependencies or unrelated integrations.

## Evidence and documentation

- Run checks appropriate to changed behavior and record failures accurately.
- Keep the CLI help, examples, architecture, and status documentation consistent with the implementation.
- Report unavailable tools, endpoint failures, and unimplemented features plainly.
- Distinguish a source archive, executable, and installer. Claim only the artifact actually produced and verified.
- Historical findings from `I:\LocalAI` are reference information, not tests performed by QASC.
- Do not commit secrets, local model weights, generated application workspaces, or raw private model exchanges. Publish only deliberately selected, reviewed evidence.

See [DEVELOPMENT.md](DEVELOPMENT.md) for the development workflow and [PROJECT_STATUS.md](PROJECT_STATUS.md) for current evidence.
