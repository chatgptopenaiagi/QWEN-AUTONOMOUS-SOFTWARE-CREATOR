# QASC vision

QWEN AUTONOMOUS SOFTWARE CREATOR (QASC) exists to reduce the technical labor between a human idea and usable software. Human time is limited. Repeated environment setup, boilerplate, compilation, debugging, testing, and packaging should consume less of it.

The human determines what should exist, why it matters, and what makes the result acceptable. Artificial intelligence interprets the request and proposes a design and implementation. The machine engine supplies tools, executes the work, and returns actual results. The model uses those results to improve the application.

QASC is intended to produce software that has been executed and checked. Source generation is one step. A response that looks plausible is not delivery evidence.

## Three intelligence layers

| Layer | Responsibility | Explicit interface |
| --- | --- | --- |
| Human | Purpose, requirements, acceptance criteria | Request text and independently supplied acceptance cases |
| Artificial intelligence | Interpretation, design, source generation, diagnosis | Model adapter requests and structured responses |
| Machine execution | Discovery, project storage, execution, verification, artifacts | Tool reports, execution receipts, project state |

The engine must remain useful when the model changes. Qwen is the initial model, accessed through a local llama.cpp server. The orchestration, records, and delivery workflow belong to QASC rather than to a particular model vendor or server.

## Practical value

The intended measures are human time saved, functional applications produced, repetitive operations automated, human interventions required, verified quality, and reuse across projects. The first release records execution and correction evidence; it does not yet measure time saved or claim a quantified productivity gain.

Future measurement should preserve a clear baseline: what the human would otherwise have done, elapsed machine time, human intervention time, the acceptance criteria exercised, and the artifacts delivered. More generated code is not by itself evidence of greater value.

## Direction and boundaries

QASC should progressively discover development tools, choose suitable stacks, create and correct applications, preserve working versions, and deliver verified artifacts. Future packaging includes executables and installers where the platform and project permit them.

The initial implementation intentionally concentrates on local Python projects using the standard library. It establishes the feedback loop before broader language support, automated environment provisioning, hardened isolation, and installers. See [PROJECT_STATUS.md](PROJECT_STATUS.md) for actual evidence and [ROADMAP.md](ROADMAP.md) for work that remains.

QASC supports human creativity by reducing repetitive software work. Humans remain responsible for defining the desired result and deciding whether the delivered behavior meets their needs.
