"""Model-independent generation contract and the local llama.cpp adapter.

The adapter never starts or reconfigures the inference server and never falls
back to another endpoint. A different URL must be supplied explicitly.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
import re
import time
from typing import Any, Protocol, runtime_checkable
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


class ModelError(RuntimeError):
    """An inference transport, protocol, or incomplete-generation failure."""

    def __init__(self, message: str, *, raw: dict | None = None):
        super().__init__(message)
        self.raw = raw


@dataclass
class Generation:
    content: str
    model: str
    usage: dict
    timings: dict
    tool_calls: list
    raw: dict


@runtime_checkable
class ModelAdapter(Protocol):
    """Boundary used by the creation engine; implementations own transport."""

    adapter_id: str
    capabilities: dict[str, bool]

    def info(self) -> dict: ...

    def generate(
        self, messages: list[dict], response_schema: dict | None = None
    ) -> Generation: ...


def parse_json_response(content: str) -> dict:
    """Parse one JSON object, optionally enclosed in one Markdown code fence.

    Prose surrounding JSON, duplicate keys, nonfinite numbers and multiple
    blocks are errors. Never extract a convenient substring from broken output.
    """
    if not isinstance(content, str):
        raise ModelError("Expected a text JSON response")
    text = content.strip()
    if text.startswith("```"):
        match = re.fullmatch(r"```(?:json)?\s*\n(.*?)\n```", text, flags=re.DOTALL | re.IGNORECASE)
        if not match:
            raise ModelError("Expected exactly one fenced JSON object")
        text = match.group(1).strip()

    def reject_constant(value: str) -> Any:
        raise ValueError(f"Nonfinite JSON number: {value}")

    def unique_object(pairs: list[tuple[str, Any]]) -> dict:
        result: dict = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"Duplicate JSON key: {key}")
            result[key] = value
        return result

    try:
        result = json.loads(text, parse_constant=reject_constant, object_pairs_hook=unique_object)
    except (ValueError, RecursionError) as exc:
        raise ModelError(f"Model response is not valid JSON: {exc}") from exc
    if not isinstance(result, dict):
        raise ModelError("Model response must be a JSON object")
    return result


class OpenAICompatibleAdapter:
    """Synchronous, non-streaming adapter for a llama.cpp compatible API."""

    adapter_id = "llama.cpp-openai-compatible"
    capabilities = {
        "text_generation": True,
        "structured_responses": True,
        "tool_call_requests": True,
        "token_accounting_when_available": True,
        "inference_timings_when_available": True,
    }
    max_response_bytes = 16 * 1024 * 1024

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8080",
        model: str | None = None,
        timeout: float = 180,
        max_tokens: int = 4096,
        context_size: int | None = None,
    ):
        parsed = urlsplit(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("Model endpoint must be an http:// or https:// URL")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Model endpoint must not contain credentials, a query, or a fragment")
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be finite and greater than zero")
        if isinstance(max_tokens, bool) or not isinstance(max_tokens, int) or max_tokens < 1:
            raise ValueError("max_tokens must be a positive integer")
        if context_size is not None and (
            isinstance(context_size, bool) or not isinstance(context_size, int) or context_size < 1
        ):
            raise ValueError("context_size must be a positive integer when provided")
        if model is not None and (not isinstance(model, str) or not model.strip()):
            raise ValueError("model must be a nonempty identifier when provided")
        self.base_url = base_url.rstrip("/")
        if self.base_url.endswith("/v1"):
            self.base_url = self.base_url[:-3]
        self.model = model
        self.timeout = timeout
        self.max_tokens = max_tokens
        self.context_size = context_size

    def _request(self, path: str, payload: dict | None = None, *, timeout: float | None = None) -> dict:
        data = None if payload is None else json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
        request = Request(
            self.base_url + path,
            data=data,
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            method="GET" if payload is None else "POST",
        )
        try:
            with urlopen(request, timeout=timeout or self.timeout) as response:
                body = response.read(self.max_response_bytes + 1)
        except HTTPError as exc:
            try:
                detail = exc.read(2048).decode("utf-8", errors="replace")
            except OSError:
                detail = exc.reason
            finally:
                exc.close()
            raise ModelError(f"{request.method} {path}: HTTP {exc.code}: {detail}") from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise ModelError(f"{request.method} {path}: {exc}") from exc
        if len(body) > self.max_response_bytes:
            raise ModelError(f"{path}: response exceeds {self.max_response_bytes} bytes")
        try:
            result = json.loads(body)
        except (ValueError, UnicodeError, RecursionError) as exc:
            raise ModelError(f"{path}: server returned invalid JSON") from exc
        if not isinstance(result, dict):
            raise ModelError(f"{path}: expected a JSON object")
        if result.get("error"):
            raise ModelError(f"{path}: {result['error']}", raw=result)
        return result

    @staticmethod
    def _model_ids(response: dict) -> list[str]:
        rows = response.get("data")
        if not isinstance(rows, list):
            raise ModelError("/v1/models: response has no model data list", raw=response)
        return [item["id"] for item in rows if isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"]]

    def info(self) -> dict:
        """Probe read-only routes. Missing optional llama.cpp routes are recorded."""
        errors: dict[str, str] = {}
        health: dict = {}
        props: dict = {}
        model_ids: list[str] = []
        models_ok = False
        probe_timeout = min(self.timeout, 5.0)
        for path in ("/health", "/v1/models", "/props"):
            try:
                response = self._request(path, timeout=probe_timeout)
                if path == "/health":
                    health = response
                elif path == "/v1/models":
                    model_ids = self._model_ids(response)
                    models_ok = bool(model_ids)
                else:
                    props = response
            except ModelError as exc:
                errors[path] = str(exc)
        selected = self.model or (model_ids[0] if model_ids else None)
        available = models_ok and selected in model_ids
        if health.get("status") not in {None, "ok", "ready"}:
            available = False
        health_error = errors.get("/health", "")
        if "HTTP 503" in health_error:
            available = False
        context = self.context_size
        if context is None:
            settings = props.get("default_generation_settings", {})
            if isinstance(settings, dict):
                candidate = settings.get("n_ctx")
                if isinstance(candidate, int) and not isinstance(candidate, bool) and candidate > 0:
                    context = candidate
            if context is None:
                candidate = props.get("n_ctx")
                if isinstance(candidate, int) and not isinstance(candidate, bool) and candidate > 0:
                    context = candidate
        if self.model and models_ok and self.model not in model_ids:
            errors["model"] = f"Configured model {self.model!r} is not advertised by this endpoint"
        return {
            "adapter": self.adapter_id,
            "base_url": self.base_url,
            "model": selected,
            "model_ids": model_ids,
            "available": available,
            "context_size": context,
            "capabilities": dict(self.capabilities),
            "health": health,
            "errors": errors,
        }

    def generate(self, messages: list[dict], response_schema: dict | None = None) -> Generation:
        if not isinstance(messages, list) or not messages or any(not isinstance(item, dict) for item in messages):
            raise ModelError("messages must be a nonempty list of message objects")
        if response_schema is not None and not isinstance(response_schema, dict):
            raise ModelError("response_schema must be a JSON schema object")
        model = self.model
        if model is None:
            model_ids = self._model_ids(self._request("/v1/models", timeout=min(self.timeout, 5.0)))
            if not model_ids:
                raise ModelError("The configured endpoint did not advertise any models")
            model = model_ids[0]
        payload = {"model": model, "messages": messages, "stream": False, "temperature": 0.2, "max_tokens": self.max_tokens}
        if response_schema is not None:
            # llama.cpp supports this form without an external SDK dependency.
            payload["response_format"] = {"type": "json_object", "schema": response_schema}
        started = time.monotonic()
        raw = self._request("/v1/chat/completions", payload)
        elapsed = time.monotonic() - started
        choices = raw.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise ModelError("Generation response has no completion choice", raw=raw)
        choice = choices[0]
        finish_reason = choice.get("finish_reason")
        if finish_reason == "length":
            raise ModelError("Generation reached the token/context limit; output is incomplete", raw=raw)
        if finish_reason not in {None, "stop", "tool_calls", "function_call"}:
            raise ModelError(f"Generation ended unexpectedly: {finish_reason}", raw=raw)
        message = choice.get("message")
        if not isinstance(message, dict):
            raise ModelError("Generation response has no assistant message", raw=raw)
        content = message.get("content")
        tool_calls = message.get("tool_calls") or []
        if not isinstance(tool_calls, list):
            raise ModelError("Generation tool_calls must be a list", raw=raw)
        if content is None and tool_calls:
            content = ""
        if not isinstance(content, str) or (not content.strip() and not tool_calls):
            raise ModelError("Generation response has no text or tool-call request", raw=raw)
        timings = dict(raw.get("timings")) if isinstance(raw.get("timings"), dict) else {}
        timings["request_seconds"] = round(elapsed, 6)
        usage = raw.get("usage") if isinstance(raw.get("usage"), dict) else {}
        response_model = raw.get("model")
        return Generation(
            content=content,
            model=response_model if isinstance(response_model, str) and response_model else model,
            usage=usage,
            timings=timings,
            tool_calls=tool_calls,
            raw=raw,
        )
