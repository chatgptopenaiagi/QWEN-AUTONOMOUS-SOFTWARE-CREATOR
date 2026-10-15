# QWEN AUTONOMOUS SOFTWARE CREATOR

**QASC** is a local-first platform for turning human software requests into generated projects with real execution results, bounded AI corrections, and persistent development history.

The human defines the desired software. The model proposes requirements, a design, and source files. QASC writes the project, runs checks, returns failures to the model, and preserves the evidence. Its purpose is to reduce repetitive technical work between an idea and a usable application.

The initial implementation supports **Python 3.11+ applications using the standard library**, with multiple source files and unittest checks. Its first model adapter uses the existing local llama.cpp OpenAI-compatible API at `http://127.0.0.1:8080`. The engine does not require an external AI service.

## Current capabilities

- Discover local development tools and inspect the configured model endpoint.
- Generate structured requirements, architecture, and project files from a natural-language request.
- Execute tests and optional independent acceptance cases with captured outputs and timeouts.
- Send failures back to the model for a bounded number of corrections while preserving the original tests.
- Resume work from project state, model exchanges, execution receipts, and source snapshots on disk.
- Produce a source ZIP with artifact provenance.

Source generation, actual execution, and passed verification are separate states. Packaging currently means a source archive; executable builds and installers remain planned. Tool discovery covers more environments than the initial generation workflow supports. See [PROJECT_STATUS.md](PROJECT_STATUS.md) for this repository's recorded results and limitations.

## Start from PowerShell 7

Use an installed Python 3.11+ interpreter. From this repository:

```powershell
Set-Location I:\QWEN-AUTONOMOUS-SOFTWARE-CREATOR
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\qasc.exe doctor
.\.venv\Scripts\qasc.exe models
```

The package has no runtime dependencies outside the Python standard library. Installation uses setuptools as a build dependency. To run directly from source without installing the package:

```powershell
$env:PYTHONPATH = Join-Path $PWD 'src'
python -m qasc --help
python -m qasc doctor
```

The following examples assume `qasc` is on `PATH`, for example after activating the virtual environment. Use `.\.venv\Scripts\qasc.exe` or `python -m qasc` instead if preferred.

## Create and verify an application

```powershell
qasc create 'Build a Python CLI that takes one name and prints Hello, <name>! followed by a newline. Include unittest tests.' --name hello-demo --run --max-corrections 2
qasc status hello-demo
qasc test hello-demo
qasc resume hello-demo --max-corrections 2
qasc package hello-demo
```

`create` without `--run` saves generated source without executing it. `resume` continues an existing project from disk; it may contact the model if generation or correction is needed. Use a new name for a different application. QASC refuses to create over an existing project.

For independent checks, create an acceptance JSON file before generation:

```powershell
@'
{
  "cases": [
    {"name": "named-greeting", "args": ["Ada"], "stdout": "Hello, Ada!\n", "exit_code": 0}
  ]
}
'@ | Set-Content -LiteralPath acceptance.json -Encoding utf8

qasc create 'Build a Python CLI that accepts one name and prints Hello, <name>! followed by a newline. Include unittest tests.' --name accepted-greeting --acceptance acceptance.json --run
```

Acceptance cases run the project's declared Python entrypoint. Each case requires expected `stdout`, compared exactly after normalizing Windows line endings; it may also supply `name`, `args`, `stdin`, `stderr`, and `exit_code`. Arguments default to an empty list and exit code defaults to zero. QASC records these as `operator_supplied_verification`. Both these cases and the initial model-authored tests remain fixed during model corrections. Passing checks establish the tested behavior, not every possible behavior of the application.

QASC runs generated unittest tests through its own runner and reads structured test counts. Zero discovered tests, failed checks, incomplete capture, and inventory errors cannot produce a verified result. Projects must not contain a top-level `unittest.py` file or `unittest` directory that shadows the standard-library runner.

## Commands

Operational commands return JSON suitable for PowerShell inspection or saving as evidence. Help, version output, and argument-parser errors use normal CLI text.

| Command | Purpose |
| --- | --- |
| `qasc doctor` | Probe the model endpoint and inventory local development tools |
| `qasc models` | Report the configured adapter, advertised models, and availability |
| `qasc create 'request' --name slug` | Generate a new independent project |
| `qasc create --request-file request.txt --name slug` | Read the human request from a file |
| `qasc test slug` | Execute the project's fixed tests and acceptance cases |
| `qasc status` | List projects in the configured projects directory |
| `qasc status slug` | Report one project's state, verification, and unresolved failures |
| `qasc resume slug` | Continue generation or verification from saved state |
| `qasc package slug` | Create a source ZIP of currently verified files under `.qasc/deliveries` |

Project selectors are names in the configured project root, not arbitrary paths. Names match `[a-z][a-z0-9-]{0,63}`. `create`, `test`, and `resume` accept `--timeout` for supervised checks; the default is 30 seconds per execution. Creation with `--run` and resume accept `--max-corrections`, defaulting to two per invocation, with a range of zero to ten.

Exit code `0` means command success, `1` means unavailable model connectivity or a creation/verification result that did not pass, `2` means a command error, and `130` means interruption. `status` reports the saved state and returns zero even when the project has unresolved problems. `doctor` reports missing tools separately; its exit code reflects model availability.

Global options go **before** the command:

```powershell
qasc --endpoint http://127.0.0.1:8080 --projects-dir I:\QASC-Applications doctor
qasc --model qwen3-coder-local --max-tokens 3000 create 'Build a small temperature conversion CLI with tests.' --name temperatures --run
```

| Setting | Environment variable | Default |
| --- | --- | --- |
| `--endpoint` | `QASC_ENDPOINT` | `http://127.0.0.1:8080` |
| `--model` | `QASC_MODEL` | Discover the endpoint's advertised model |
| `--projects-dir` | `QASC_PROJECTS_DIR` | `./projects`, relative to the current directory |
| `--model-timeout` | — | 180 seconds |
| `--max-tokens` | — | 3000 generated tokens |

The model name must match the identifier served by the endpoint. The reference model is Qwen3-Coder-30B-A3B-Instruct-Q4_K_M; its served identifier may differ from its filename.

## Execution and continuity

Generated projects stay separate from QASC's source. Each project keeps `.qasc/state.json`, model requests and responses, execution receipts, and numbered source revisions. Verified revisions remain preserved when later work fails. Interrupted revision recovery checks recorded hashes before writing and stops if files contain conflicting edits. Packaging requires a passing verification whose source fingerprint still matches the files on disk; editing source requires another `qasc test` before packaging.

Execution uses explicit arguments, `shell=False`, a project working directory, bounded output capture, and a timeout. **This is not an operating system sandbox.** Generated Python runs with the current user's permissions. Path checks and working-directory scope do not prevent executed code from accessing other files or the network.

QASC uses the existing server when available. It does not alter `I:\LocalAI`, move its files, install models there, or restart its inference server. Findings from earlier sessions are reference information; QASC's own evidence is recorded separately.

## Repository guide

| Document | Contents |
| --- | --- |
| [VISION.md](VISION.md) | Human-centered purpose and practical value measures |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Engine boundaries, interfaces, and diagrams |
| [ROADMAP.md](ROADMAP.md) | Remaining phases and acceptance criteria |
| [DEVELOPMENT.md](DEVELOPMENT.md) | Setup, validation, and contribution workflow |
| [PROJECT_STATUS.md](PROJECT_STATUS.md) | Actual connectivity, test results, and limitations |
| [AGENTS.md](AGENTS.md) | Instructions for engineering agents |
| [Creation workflow](docs/CREATION_WORKFLOW.md) | Generation, verification, correction, and delivery |
| [Model adapters](docs/MODEL_ADAPTERS.md) | Initial backend and extension contract |
| [Execution engine](docs/EXECUTION_ENGINE.md) | Process behavior, receipts, and isolation limits |
| [Project continuity](docs/PROJECT_CONTINUITY.md) | Persistent records, snapshots, and resume |
| [SCE integration](docs/INTEGRATION_WITH_SCE.md) | Planned integration boundary and open contracts |

Repository identity: `chatgptopenaiagi/QWEN-AUTONOMOUS-SOFTWARE-CREATOR`. Publication and initial private visibility must be confirmed by the successful GitHub result recorded in [PROJECT_STATUS.md](PROJECT_STATUS.md).
