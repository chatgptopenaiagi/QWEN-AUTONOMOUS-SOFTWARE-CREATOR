# Project continuity

Project memory belongs on disk. QASC can continue an interrupted creation task without access to the chat that started it.

## Storage boundaries

Generated applications live in dedicated project directories, normally under `projects/<slug>`. QASC refuses to create over an existing target. Application source and tests belong to that project; control records live under its `.qasc` directory.

The continuity record includes:

| Record | Purpose |
| --- | --- |
| `.qasc/state.json` | Current project state and pointers to its history |
| Original request | Preserve human intent without replacing it with a model paraphrase |
| Structured requirements and architecture | Preserve the model's interpretation and design |
| Model requests and responses | Explain the source of generated files and correction proposals |
| Execution receipts | Preserve real commands, outputs, exit codes, and timeouts |
| Failure and correction history | Explain unresolved work and attempts already made |
| Source snapshots | Preserve prior source versions, including verified versions |
| Acceptance specification | Keep independent expected behavior stable during corrections |
| Artifact records | Identify produced files and their verification provenance |

The initial layout is:

```text
projects/<slug>/
  <application source and tests>
  .qasc/
    state.json
    operation.lock                 # present while a mutation is active
    model/<call-id>/                # request.json, response.json or error.json
    revisions/<revision>/          # source/ snapshot and manifest.json
    executions/<receipt-id>.json
    verifications/<verification-id>.json
    verifications/runner-<id>.json  # actual unittest counts and outcomes
    verified/<verified-id>.json
    deliveries/                    # source ZIP and artifact receipt
    runtime/tmp/                   # project-local temporary files
```

The original request and acceptance specification are stored in `state.json`. Use `qasc status` and the project records when diagnosing a particular run. `verification_matches_current_source` distinguishes the latest receipt from later manual source edits.

## Resume

Resume loads the persisted request, current source, last relevant execution results, and correction history. It builds a bounded model context rather than replaying the entire conversation. Depending on the saved state, it can retry generation or execute the existing project and continue bounded corrections.

An interrupted or failed operation must remain distinguishable from a verified result. If the endpoint or a required tool is unavailable, QASC preserves the state and reports the limitation. The next resume can retry when that resource is available.

Current states include `requested`, `generating`, `applying`, `generated`, `testing`, `test_failed`, `correcting`, `verified`, `stalled`, and `blocked`. `blocked` means an operation recorded an error; `stalled` means a correction repeated an ineffective source result. Status is evidence about the latest operation, and older receipts remain available.

## Version history

QASC preserves snapshots so a failed correction does not erase the evidence of an earlier working version. Numbered history and execution receipts make changes inspectable. A snapshot marked verified is tied to the checks that passed for that version, not automatically to later edits.

An operation lock prevents simultaneous QASC mutations of the same project. A terminated process can leave a stale `.qasc/operation.lock`; remove it only after confirming that no QASC operation is still running for that project. Atomic state writes and pending revision records support recovery from interrupted file application.

Each revision manifest records the previous source hashes and candidate file hashes. Recovery first validates the stored snapshot, then checks all affected destinations before changing them. A destination must match its recorded previous state or its already-applied candidate state. Conflicting edits, including new unmanaged content, stop recovery so the operator's files remain available for reconciliation. Source application uses atomic file replacement, avoiding writes through an existing hardlink to another file.

Automatic rollback, branching application evolution, and conflict resolution between simultaneous writers are not complete version-control features in the initial release. The QASC source repository and a generated application's development history are separate concerns.

## Provenance

- Human-authored request and acceptance cases define intended behavior.
- Codex-authored QASC infrastructure coordinates the process.
- Model-authored application source and tests are preserved as generated output.
- QASC-generated receipts, snapshots, and archives document machine operations.
- Repository test fixtures validate infrastructure and are not presented as live Qwen output.

Local exchanges and project files may contain private requirements or source. Generated workspaces are not part of the repository's public evidence by default. Any evidence selected for version control should be reviewed and retain its true provenance.
