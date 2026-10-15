# QASC project status

Recorded on 2026-10-15. Local root: `I:\QWEN-AUTONOMOUS-SOFTWARE-CREATOR`.

The initial foundation is implemented and tested. It supports local Qwen generation of Python applications, actual execution and independent acceptance checks, bounded correction, persisted development state, and verified source archive delivery. It is not a general-purpose autonomous engineering platform yet.

| Area | Actual result |
| --- | --- |
| Repository | [chatgptopenaiagi/QWEN-AUTONOMOUS-SOFTWARE-CREATOR](https://github.com/chatgptopenaiagi/QWEN-AUTONOMOUS-SOFTWARE-CREATOR) created as **PRIVATE**; initial commit `ef15627` successfully pushed to `main`; GitHub API confirmed the repository and visibility |
| Python package | QASC 0.1.0, Python >=3.11, no third-party runtime dependencies; editable installation, wheel build, and offline wheel installation into a separate virtual environment succeeded |
| CLI | `doctor`, `models`, `create`, `test`, `status`, `resume`, `package` implemented |
| Model connectivity | Existing `http://127.0.0.1:8080` responded healthy; served model `qwen3-coder-local`; context 8192 |
| Discovery | 24 tool entries inspected; 19 found; 5 not found in searched locations |
| Generation | Real Qwen generated `app.py`, `greeting.py`, and `tests/test_greeting.py` from the demonstration requirement |
| Verification | Four generated unit tests and three separately authored CLI acceptance cases passed |
| Correction | A recorded intentional uppercase fault failed verification; a fresh `resume` invocation obtained one Qwen correction and passed the same checks |
| Continuity | Two source revisions and two verified snapshots preserved; model exchanges, failure details, and execution receipts retained |
| Delivery | Source ZIP created and checked using archive integrity and per-file hashes; extracted copy printed the expected `HELLO, ADA!`; no native executable or installer claimed |
| Infrastructure checks | **89 tests passed**, exit code 0, Windows / CPython 3.15.0 / PowerShell 7.6.6; includes a real Windows junction isolation regression |

See [evidence/README.md](evidence/README.md), [test summary](evidence/infrastructure-tests.json), and [full test output](evidence/infrastructure-tests.txt). These results were produced by QASC in this repository. The earlier seven-language, CUDA, Anaconda bridge, and other `I:\LocalAI` findings are reference history and are not claimed as QASC tests. No changes or server restarts were made in `I:\LocalAI`.

The actual GitHub creation response is preserved in [github-publication.json](evidence/github-publication.json). The initial commit's [hosted Windows/Linux Python 3.11/3.13 matrix](https://github.com/chatgptopenaiagi/QWEN-AUTONOMOUS-SOFTWARE-CREATOR/actions/runs/38734653908) passed all four jobs. The subsequent Python 3.11 junction hardening has passed local validation; its hosted rerun is recorded separately when complete.

## Implemented architecture

The human request and optional acceptance specification enter a project-specific state store. A model adapter obtains structured requirements, architecture, and multiple source files. The engine validates paths, saves model provenance and an immutable revision, and invokes local Python through an execution supervisor. A trusted isolated unittest runner produces actual counts. Separate acceptance processes exercise the application entrypoint. Failures return to the model in compact persisted context; corrections cannot replace the original tests or acceptance criteria. Verified snapshots survive later failure. Source packaging requires the current files to match a passing verification.

Modules are in `src/qasc/`: `cli.py`, `model.py`, `discovery.py`, `project.py`, `engine.py`, `execution.py`, and `runner.py`, plus package entrypoints. The documented model protocol is independent of Qwen. Initial generation deliberately uses Python's standard library; inventory of other tools is not evidence that those stacks have been integrated.

## Tool inventory

Found: Python, Anaconda/Conda, PowerShell, Node.js, npm, Git, GitHub CLI, Clang, Clang++, CMake, Ninja, Rust, Cargo, .NET, PyInstaller, Nuitka, WiX, NSIS, and 7-Zip. GCC, G++, MSVC, Windows SDK, and Inno Setup were not found on PATH or in the checked locations. This is not an exhaustive machine-wide absence claim. Version-probe details are preserved in [doctor.json](evidence/doctor.json).

## Boundaries and unresolved work

- Generation currently supports small Python standard-library applications. Other stacks, dependency provisioning, and compiler integration remain future work.
- Execution has project working directories, local temporary storage, output limits, process timeouts and receipts, but no OS sandbox. Generated code has the current user's file and network permissions. Metadata and test evidence are not protected against deliberately hostile code.
- The correction prompt is capped by characters, not exact rendered token accounting. Large requests can exceed the server's context; errors are recorded. The observed greeting generation took about 109 seconds on the shared local server; timeouts can be configured without changing that server.
- Hard termination may leave an operation lock. Recovery currently requires checking that no QASC operation is active before removing the stale lock. Stored state schema migration and an explicit rollback command remain planned.
- Independent acceptance is optional. Without operator cases, a passing result is explicitly scoped to model-generated tests only. Even supplied cases cover only their stated behavior.
- Source ZIP delivery is implemented. Executable builds, installers, installation verification, additional model backends, software resource discovery, and SCE integration are planned.
- No numerical human-time-savings claim has been measured. Productivity instrumentation belongs to later work.

Foundations from phases 1–4 are present; the broader objectives in [ROADMAP.md](ROADMAP.md) remain open. Source ZIP delivery does not complete phase 5.
