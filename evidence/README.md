# Recorded QASC validation

These are actual executions by this repository on 2026-10-15, separate from the historical findings in `I:\LocalAI`.

- `infrastructure-tests.json` and `.txt`: 88 infrastructure tests, exit code 0. Model calls in these tests use deterministic fixtures or a loopback HTTP server; generated application execution uses real child processes.
- `doctor.json` and `models.json`: read-only inventory and healthy local Qwen endpoint, model `qwen3-coder-local`, context 8192.
- `live-create.json`: real Qwen generation of three source files; four model-generated tests and three separate acceptance cases passed.
- `live-fault-status.json`: status after a deliberate, recorded change from `greeting.upper()` to `greeting.lower()`.
- `live-resume.json`: a fresh CLI invocation captured the failure, obtained one real Qwen correction, and passed the unchanged tests and acceptance cases.
- `live-final-status.json`: final saved project state summary.
- `live-package.json`: actual source ZIP receipt, including its SHA256 and archive verification. This is not a native executable or installer.
- `live-qwen/`: selected reviewed model exchanges, execution receipts, verifications, state, source revisions, and final application source from this synthetic demonstration.
- `delivery-smoke.json`: execution of the delivered source after extracting it to a separate directory.
- `wheel-install.json`: QASC wheel installation into a separate virtual environment with `--no-index --no-deps`, followed by a successful installed CLI version check.
- `github-publication.json`: actual GitHub repository response after successful publication (added only after publication succeeds).

The demonstration requirement and acceptance examples were authored by Codex as validation fixtures under the user's platform-building mission. They are not a separate human-authored application request. The original create receipt predates explicit fixture provenance annotation; final state and the fault-injection record identify their origin. The application's source and unit tests were produced by the local Qwen model. The injected defect is an intentional Codex validation fault, not a defect attributed to the original Qwen generation. QASC infrastructure, test fixtures, and this evidence selection were authored by Codex.

Full working projects stay in ignored `projects/` directories. These selected fixture records contain no credentials or private application requirements. Timing and discovered tools describe this machine and run; they are not cross-machine performance claims. A checked source archive establishes archive integrity and the specific executed behavior, not installer readiness or unrestricted autonomous engineering.
