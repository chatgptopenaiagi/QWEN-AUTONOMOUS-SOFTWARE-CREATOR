# Developing QASC

The primary development platform is Windows 10/11 with PowerShell 7 and Python 3.11 or newer. QASC's runtime uses the Python standard library. Keep orchestration code in `src/qasc`, infrastructure tests in `tests`, and generated applications in the configured projects directory.

## Local setup

```powershell
Set-Location I:\QWEN-AUTONOMOUS-SOFTWARE-CREATOR
python --version
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m qasc --help
```

Use the actual Python executable installed on the machine if `python` is not on `PATH`. QASC uses the interpreter running the package for its initial Python execution workflow. A virtual environment is recommended for predictable installation; activation is optional when using the executable's full path.

The convenience script `./scripts/bootstrap.ps1` creates the same local virtual environment and installs the package. `./scripts/validate.ps1` runs the infrastructure tests with `src` on `PYTHONPATH`, using the virtual environment when present.

For source-only development:

```powershell
$env:PYTHONPATH = Join-Path $PWD 'src'
python -m qasc --help
python -m unittest discover -s tests -v
```

Do not install or replace Codex CLI. The neighboring `I:\LocalAI` installation is owned by a separate active session and must remain unchanged.

## Validate infrastructure

Run the repository tests using the installed package or `PYTHONPATH=src`:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Infrastructure tests use deterministic fixtures and mock model transport where appropriate. They establish engine behavior; they are not claims that Qwen generated a working application. Preserve that distinction in evidence and status documentation. The commands above run QASC's infrastructure suite. Generated application tests use the separate trusted `src/qasc/runner.py` entrypoint described in [docs/EXECUTION_ENGINE.md](docs/EXECUTION_ENGINE.md).

Useful validation targets include structured response parsing, path traversal and collision rejection, independent project creation, execution outputs and timeouts, trusted runner imports and actual test counts, acceptance checks, correction limits, stale bytecode avoidance, conflicting-edit recovery, preserved revisions, and archive contents. Add tests for changed behavior rather than duplicating implementation details.

## Validate the actual local model

```powershell
.\.venv\Scripts\qasc.exe doctor
.\.venv\Scripts\qasc.exe models
.\.venv\Scripts\qasc.exe create 'Build a Python CLI that adds two integer arguments, prints their sum, and includes unittest tests.' --name addition-check --run --max-corrections 2
.\.venv\Scripts\qasc.exe status addition-check
```

Use a fresh project name for each independent example. Add an external acceptance JSON file when verifying specific expected outputs. Save the resulting status, model metadata, and execution receipts as the evidence for that run.

The default endpoint is `http://127.0.0.1:8080`. If it is unavailable or busy, record the limitation and retry when appropriate. Do not restart its server to make a test pass. Do not claim historical `I:\LocalAI` tests as QASC test results.

## Changes and evidence

1. Inspect the existing implementation and project instructions.
2. Make a focused change that preserves the model, project, and execution boundaries.
3. Run the checks relevant to the changed behavior.
4. Inspect actual outputs and artifact contents before declaring success.
5. Update documentation and [PROJECT_STATUS.md](PROJECT_STATUS.md) when supported capabilities or recorded evidence change.

Keep local model weights, virtual environments, generated projects, raw private exchanges, and secrets out of version control. Deliberately selected evidence may be committed after review. Label it by provenance: infrastructure fixture, actual model output, human requirement, or machine-produced execution record.

## Extending a capability

Additional adapters should implement the model boundary in [docs/MODEL_ADAPTERS.md](docs/MODEL_ADAPTERS.md). New execution stacks need a concrete command contract, dependency strategy, timeout behavior, artifact definition, and real verification. Do not turn model text into an unrestricted shell command as a shortcut.

Packaging backends should distinguish source archives, executables, installers, and successful installation. A build command returning zero is only one part of artifact verification. SCE integration remains planned until its actual contract is known.

## GitHub workflow

Inspect the current repository and authenticated account before changing remotes or publishing. The intended initial repository is private under `chatgptopenaiagi/QWEN-AUTONOMOUS-SOFTWARE-CREATOR`. An existing remote must be inspected and preserved rather than replaced.

For an already committed local repository with no existing remote repository, the intended initial command is:

```powershell
gh repo create chatgptopenaiagi/QWEN-AUTONOMOUS-SOFTWARE-CREATOR --private --source . --remote origin --push
```

This command is creation guidance, not evidence that publication occurred. Confirm the actual URL, visibility, and pushed commit with successful GitHub responses. [PROJECT_STATUS.md](PROJECT_STATUS.md) records the outcome of the initial engineering session.
