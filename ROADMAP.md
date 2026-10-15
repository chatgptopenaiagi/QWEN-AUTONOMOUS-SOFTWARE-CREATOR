# Development roadmap

QASC is being developed as a sequence of verifiable capabilities. A phase is complete only when its required behavior has implementation and recorded evidence. [PROJECT_STATUS.md](PROJECT_STATUS.md) records the current tested state; this roadmap describes direction and exit criteria.

| Phase | Foundation in this repository | Remaining objectives and exit criteria |
| --- | --- | --- |
| 1. Repository and connectivity | Python CLI, architecture documentation, initial local model adapter | Maintain reproducible setup, endpoint diagnostics, and current repository publication evidence |
| 2. Discovery and generation | Tool inventory, structured Python source generation, independent project directories | Validate broader stack choices, dependency manifests, resource discovery, and safe provisioning |
| 3. Execution and correction | Actual test execution, receipts, bounded AI correction, optional independent acceptance checks | Broaden behavioral verification, improve correction targeting, and establish hardened execution isolation |
| 4. Persistent development | Local state, model exchanges, source snapshots, resumable work, operation locks, multi-file projects | Add controlled feature evolution, deliberate rollback, robust stale-lock recovery, and migration of stored state |
| 5. Packaging and installation | Source ZIP packaging | Build executable artifacts, create installers, verify installation, and test delivered behavior on a clean target |
| 6. Models and environments | Adapter boundary and tool discovery | Validate additional adapters, languages, build environments, dependency installation, and knowledge sources |
| 7. Broader autonomy and SCE | Documented integration boundary | Define SCE's actual contract, implement integration tests, and coordinate longer projects with measurable human intervention |

The existence of foundations in phases 1–4 does not mean every objective in those phases is complete. Source packaging does not complete phase 5.

## Next engineering priorities

1. Preserve a repeatable local Qwen demonstration: human request, generated files, real execution, a failure and correction when one occurs, and independent acceptance evidence.
2. Improve the reliability of structured responses and resumable failures across different local model configurations.
3. Introduce stronger execution isolation before allowing unrestricted commands or automatic dependency provisioning.
4. Add a tested packaging backend for a specific application type, then verify the resulting artifact separately from its source tests.
5. Validate another model adapter and another development stack through the same evidence pipeline.

## Acceptance of future capabilities

Each extension should state its supported input, tools used, output artifact, execution constraints, failure behavior, and verification procedure. A new backend is ready when the repository includes reproducible checks and a real execution receipt, not merely an interface stub.

Longer-term value metrics include human intervention time, successful acceptance criteria, correction effectiveness, repeatability, and reuse. Baselines and measurement methods must be established before reporting numerical productivity gains.
