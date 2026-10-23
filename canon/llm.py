"""The LLM seam, plus the cache wrapper every stage goes through.

Decision D3: the plugin never holds keys - it uses whichever client Hermes is
configured with (`ctx.llm`). This module defines the protocol so the core stays
harness-free, and ships a fake for tests.

Every real call is wrapped by :class:`CachedLLM`, which is what makes "the same
input twice gives byte-identical canon" true rather than hopeful.
"""

from __future__ import annotations

import json
from typing import Any, Mapping, Protocol, runtime_checkable

from canon.cache import CacheKey, ModelCache, fingerprint


class LLMError(RuntimeError):
    """A model call failed in a way the caller must handle (retry, quarantine)."""


@runtime_checkable
class LLMClient(Protocol):
    """What a stage needs from a model."""

    name: str

    def complete_json(
        self,
        *,
        prompt: str,
        payload: Mapping[str, Any],
        schema_hint: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        ...


class FakeLLM:
    """Deterministic stand-in for tests.

    ``responses`` maps a fingerprint of the payload to a response, or a callable
    receives the payload and returns one. Anything unmatched raises, so a test
    never silently passes on an unexpected prompt.
    """

    def __init__(
        self,
        responses: Mapping[str, Any] | None = None,
        *,
        name: str = "fake-llm",
        default: Any = None,
    ) -> None:
        self.responses = dict(responses or {})
        self.name = name
        self.default = default
        self.calls: list[Mapping[str, Any]] = []

    def complete_json(
        self,
        *,
        prompt: str,
        payload: Mapping[str, Any],
        schema_hint: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.calls.append(payload)
        key = fingerprint(payload)
        if key in self.responses:
            value = self.responses[key]
        elif prompt in self.responses:
            value = self.responses[prompt]
        elif self.default is not None:
            value = self.default
        else:
            raise LLMError(f"FakeLLM has no response for {prompt!r} / {key}")
        if callable(value):
            value = value(payload)
        if not isinstance(value, dict):
            raise LLMError(f"FakeLLM response must be a dict, got {type(value).__name__}")
        return value


class CachedLLM:
    """Cache every call by (stage, model, prompt-hash, input-hash)."""

    def __init__(self, client: LLMClient, cache: ModelCache, *, stage: str) -> None:
        self.client = client
        self.cache = cache
        self.stage = stage
        self.name = getattr(client, "name", "unknown")

    def complete_json(
        self,
        *,
        prompt: str,
        payload: Mapping[str, Any],
        schema_hint: Mapping[str, Any] | None = None,
        stage: str | None = None,
    ) -> dict[str, Any]:
        key = CacheKey(
            stage=stage or self.stage,
            model=self.name,
            prompt_hash=fingerprint(
                {"prompt": prompt, "schema": schema_hint or {}}
            ),
            input_hash=fingerprint(payload),
        )
        cached = self.cache.get(key)
        if cached is not None:
            return cached
        value = self.client.complete_json(
            prompt=prompt, payload=payload, schema_hint=schema_hint
        )
        if not isinstance(value, dict):  # pragma: no cover - defensive
            raise LLMError(f"model returned {type(value).__name__}, expected an object")
        self.cache.set(key, value)
        return value


class NullLLM:
    """A client that refuses every call.

    Used when a stage can proceed deterministically; any accidental model
    dependency raises instead of quietly degrading.
    """

    name = "null-llm"

    def complete_json(
        self,
        *,
        prompt: str,
        payload: Mapping[str, Any],
        schema_hint: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        raise LLMError("no LLM client configured for this run")


def parse_json_object(text: str) -> dict[str, Any]:
    """Parse a model response that should be one JSON object.

    Providers wrap JSON in prose or fences often enough that a strict parse is
    a false economy; anything unrecoverable raises and the caller quarantines.
    """
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        if stripped.lower().startswith("json"):
            stripped = stripped[4:]
        stripped = stripped.strip()
    try:
        value = json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start == -1 or end <= start:
            raise LLMError("model response contained no JSON object")
        try:
            value = json.loads(stripped[start : end + 1])
        except json.JSONDecodeError as exc:
            raise LLMError(f"model response was not valid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise LLMError("model response was JSON but not an object")
    return value
