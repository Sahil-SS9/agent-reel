"""The production writer path: ``ctx.llm`` behind the pipeline's client interface.

Round 4 sent writer, title and entailment calls through the Hermes API server, which is a
full agent: every call carried the Hermes system prompt (~57k prompt tokens per call) and
the "judge" was an agent persona rather than a clean model. The production path is
``ctx.llm``: a raw host-owned completion against the user's active model.

This adapter has one job - make ``ctx.llm`` look like the ``complete_json`` client the
pipeline already speaks - and one obligation: count and log prompt/completion tokens per
call, so the cost is visible.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Mapping

from canon.llm import LLMError, parse_json_object

logger = logging.getLogger(__name__)

DEFAULT_MAX_TOKENS = 1200
DEFAULT_TIMEOUT = 120.0

SYSTEM = "You return JSON only. No prose, no markdown, no code fences."


class PluginLLMClient:
    """``ctx.llm`` as a JSON client, with per-call token accounting."""

    name = "ctx.llm"

    def __init__(
        self,
        llm: Any,
        *,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        timeout: float = DEFAULT_TIMEOUT,
        max_calls: int = 150,
    ) -> None:
        self.llm = llm
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.max_calls = max_calls
        self.calls = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.max_prompt_tokens_per_call = 0
        self.per_call: list[dict[str, Any]] = []

    # -- api ---------------------------------------------------------------
    def complete_json(
        self,
        *,
        prompt: str,
        payload: Mapping[str, Any],
        schema_hint: Mapping[str, Any] | None = None,
        stage: str = "",
    ) -> dict[str, Any]:
        if self.llm is None:
            raise LLMError("ctx.llm is not available (no host LLM facade)")
        if self.calls >= self.max_calls:
            raise LLMError(f"ctx.llm call budget exhausted: {self.calls}/{self.max_calls}")

        user_content = f"{prompt}\n\nInput JSON:\n{json.dumps(payload, sort_keys=True)[:8000]}"
        if schema_hint:
            user_content += f"\n\nResponse shape:\n{json.dumps(schema_hint, sort_keys=True)}"

        self.calls += 1
        result = self.llm.complete(
            messages=[
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": user_content},
            ],
            max_tokens=self.max_tokens,
            timeout=self.timeout,
        )
        text = str(getattr(result, "text", "") or "")
        usage = getattr(result, "usage", None)
        prompt_tokens = int(getattr(usage, "input_tokens", 0) or 0)
        completion_tokens = int(getattr(usage, "output_tokens", 0) or 0)
        self.prompt_tokens += prompt_tokens
        self.completion_tokens += completion_tokens
        self.max_prompt_tokens_per_call = max(self.max_prompt_tokens_per_call, prompt_tokens)
        self.per_call.append(
            {
                "call": self.calls,
                "stage": stage,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
            }
        )
        logger.info(
            "reel llm call %d (%s): prompt_tokens=%d completion_tokens=%d",
            self.calls,
            stage or "-",
            prompt_tokens,
            completion_tokens,
        )

        if not text.strip():
            raise LLMError("ctx.llm returned no usable content")
        try:
            return parse_json_object(text)
        except Exception as exc:  # noqa: BLE001 - a bad answer is a gate failure, not a crash
            raise LLMError(f"ctx.llm returned no JSON object: {exc}") from exc

    # -- reporting ---------------------------------------------------------
    def usage(self) -> dict[str, Any]:
        return {
            "endpoint": "ctx.llm",
            "calls": self.calls,
            "budget": self.max_calls,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "max_prompt_tokens_per_call": self.max_prompt_tokens_per_call,
        }
