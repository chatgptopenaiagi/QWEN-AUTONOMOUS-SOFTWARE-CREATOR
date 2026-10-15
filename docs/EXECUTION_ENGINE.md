# Execution engine

QASC determines whether checks ran successfully from actual process results. It never substitutes a model's description of execution for a receipt.

## Initial execution contract

The first supported application stack is Python using the standard library. QASC launches its own `src/qasc/runner.py` by absolute path with a fixed argument array. The runner imports standard-library unittest and its own dependencies before adding the project to its import path. It then discovers `tests/test_*.py` and writes structured test counts and outcomes. Top-level `unittest.py` or `unittest` paths in a generated project are rejected because they would shadow the runner.

The actual test invocation has this shape; placeholders are resolved by the engine:

```text
<python> -I -B -X utf8 -X pycache_prefix=<fresh-path> <absolute-runner.py> --project <project> --result <result.json>
```

Its test discovery semantics correspond to the conventional `python -m unittest discover -s tests -v` command, but QASC does not execute that command for generated projects. `-I` isolates the runner's initial imports, `-X utf8` gives predictable text encoding, and `-B` disables bytecode writes. A fresh cache prefix for each verification also prevents loading older cached modules after rapid same-sized source corrections.

Optional independent acceptance cases invoke the declared application entrypoint using the same Python interpreter, UTF-8 setting, disabled bytecode writes, and fresh cache prefix. They omit `-I` so the entrypoint can import its application modules. Generated text does not become a shell command.

Each process has:

- An explicit argument vector and project working directory.
- `shell=False` execution.
- A finite timeout.
- Captured stdout and stderr.
- A real exit code, or an explicit timeout or launch error.
- Start and duration information in the persisted receipt.
- Before and after file hashes recording observed additions, modifications, and deletions inside the project.

Output capture retains a bounded beginning and end of stdout and stderr, with explicit truncation flags. File inventories exclude `.qasc`, `.git`, `__pycache__`, symbolic links, and Windows junctions. They cannot observe changes outside the project. Inventory errors, capture errors, incomplete capture, timeouts, and termination errors prevent a passing verification. Truncated acceptance-case output also fails comparison; bounded unit-test logs remain diagnostic while structured runner results supply the counts.

Test failures, missing tests, process launch failures, and timeouts must remain visible to the user and correction engine. A discovered compiler or runtime is not evidence that a project built with it succeeded.

## Isolation boundary

Each generated application has its own project directory. Path validation prevents generated file entries from escaping that directory or overwriting QASC's control records. An existing unrelated project is not a valid creation target.

These controls are not an operating system sandbox. Python processes run with the user's permissions and may read or modify resources outside the working directory, use the network, or launch children. Timeout handling limits the supervised invocation; it is not a guarantee that every detached descendant is terminated.

Hardened process isolation, resource quotas, dependency provisioning policies, and controlled arbitrary build commands are future work. The first implementation keeps the executable interface deliberately narrow.

## Verification semantics

The process result answers whether a command completed and what it returned. Verification additionally requires a successful structured runner result with a positive number of tests, passing acceptance cases when supplied, clean execution receipts, and unchanged managed source hashes during execution. Printing an apparent unittest summary does not supply the test count. The project records the distinction between source produced, checks executed, checks failed, and checks passed.

Model-authored unit tests are recorded as model output. Human-provided acceptance cases add an independent specification of expected behavior and are preserved during corrections. Both can be incomplete; a passing status covers the checks that actually ran.

## Correction feedback

The correction engine receives persisted errors and selected source context. It can propose project file changes, but cannot rewrite the independent acceptance specification or the initial model-authored tests through the normal generated-file interface. New files and replacements receive the same validation as initial generation.

The next attempt produces a new receipt. Old failures remain part of project history. The loop is bounded, and repeated ineffective attempts are reported rather than retried indefinitely.

## Artifacts

Snapshots and source ZIPs are QASC-generated artifacts. They are distinct from model-authored application source and from test output. The initial engine does not claim executable compilation, installer creation, installation, or verification on another machine.
