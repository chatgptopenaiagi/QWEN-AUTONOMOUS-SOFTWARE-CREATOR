# Model adapters

The model engine isolates QASC from a particular model or inference server. The initial adapter talks to the OpenAI-compatible HTTP API exposed by the existing local llama.cpp server. No external AI service is required.

Default endpoint: `http://127.0.0.1:8080`.

The expected reference model is `Qwen3-Coder-30B-A3B-Instruct-Q4_K_M`. QASC obtains the serving model's actual identifier from the endpoint rather than assuming that a model file path proves it is loaded.

## Responsibilities

| Capability | Contract |
| --- | --- |
| Identification | Adapter name, endpoint, and actual model identifier when available |
| Availability | A real endpoint probe with actionable error reporting |
| Context | Report available context metadata when exposed; preserve unknown values as unknown |
| Generation | Accept bounded messages and generation settings; return response text |
| Structured output | Request JSON and validate it against the project's expected shape |
| Tool requests | Represent tool-call responses if supplied; never execute arbitrary calls implicitly |
| Accounting | Preserve server-reported token usage when available |
| Performance | Preserve request duration and inference metrics when available |
| Errors | Report transport, HTTP, malformed response, and validation failures |

Structured response support is not a guarantee that every local model will produce valid JSON. The engine validates output, retains the raw exchange, and reports the failure. It does not silently treat malformed content as a verified project.

The concrete Python protocol in `src/qasc/model.py` has `adapter_id`, `capabilities`, `info() -> dict`, and `generate(messages, response_schema=None) -> Generation`. `Generation` contains `content`, `model`, `usage`, `timings`, `tool_calls`, and the raw server response. `ModelError` carries an actionable message and the raw response when available. The creation engine consumes structured text; tool-call requests are preserved but not dispatched.

## Initial protocol

Model enumeration uses the server's `/v1/models` interface. Read-only `/health` and `/props` probes add llama.cpp health and context information when available. Generation uses `/v1/chat/completions` with non-streaming responses and an optional JSON response schema. QASC asks for `requirements`, `acceptance_criteria`, `architecture`, `entrypoint`, and `files` containing `path` and `content`. Corrections return `diagnosis` and a `changes` list of replacement files.

Correction requests contain relevant failure receipts and compact source context. The engine enforces an 18,000-character prompt limit and reports when a project exceeds it; this is a conservative character bound, not an exact tokenizer-aware context allocator. The human's entire conversation is not required. Completion truncation is treated as an incomplete-generation error.

The existing inference installation remains external to QASC. Endpoint access does not authorize QASC to alter `I:\LocalAI`, change its model, or restart its server. A failed probe is reported as unavailable.

## Extending the engine

Add another adapter behind the same model boundary rather than adding server-specific calls throughout project creation. Preserve the same response and error semantics, distinguish unknown metadata from zero, and add deterministic transport tests before a real integration run.

A future adapter may use a different local HTTP protocol or inference runtime. Its implementation should document model selection, context limits, structured output behavior, tool-call representation, usage accounting, timeouts, and error recovery. A second production adapter is planned; a generic interface alone is not evidence that additional backends have been tested.

## Evidence and privacy

Project records retain model requests and responses so source provenance and correction decisions can be inspected. Those records can contain the human's request and application source. They stay in the local project workspace and should not be committed or published accidentally.

See [PROJECT_STATUS.md](../PROJECT_STATUS.md) for the endpoint and model actually observed in this repository's validation.
