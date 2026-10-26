"""LLM clients for the adapter.

Decision D3: the plugin calls whatever Hermes is configured with and never holds
its own keys. Two implementations:

* :class:`HermesCtxLLMClient` - the real plugin path, ``ctx.llm`` (wired in M2).
* :class:`OpenAICompatLLMClient` - any OpenAI-compatible endpoint, which is how
  the CLI runs against the user's *local* model (Turbofit on this rig) without a
  key. Used for the M1 dry run and the redaction benchmark.

Retry with backoff on 5xx, per the bake-off lesson in decisions.md ("proven
method" #8).
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Any, Mapping

from canon.llm import LLMError, parse_json_object

DEFAULT_TIMEOUT = 180.0
DEFAULT_RETRIES = 3


class OpenAICompatLLMClient:
    """Chat-completions client with JSON output and bounded retries."""

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        retries: int = DEFAULT_RETRIES,
        temperature: float = 0.0,
        max_tokens: int = 1200,
        extra_body: Mapping[str, Any] | None = None,
        thinking: bool = False,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout = timeout
        self.retries = retries
        self.temperature = temperature
        self.max_tokens = max_tokens
        # Audit R2-F3: thinking is OFF by default. A reasoning model that spends its
        # budget on reasoning_content returns content: null, which the gate treats as a
        # failure - any new caller would silently quarantine its items.
        body = dict(extra_body or {})
        body.setdefault("chat_template_kwargs", {"enable_thinking": bool(thinking)})
        self.extra_body = body
        self.name = f"openai-compat:{model}"
        self.calls = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0

    def __repr__(self) -> str:  # never include the key
        return f"OpenAICompatLLMClient(base_url={self.base_url!r}, model={self.model!r})"

    def usage(self) -> dict[str, int]:
        return {
            "calls": self.calls,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
        }

    @classmethod
    def local(cls, model: str = "auto", port: int = 8091) -> "OpenAICompatLLMClient":
        """The rig's local serving route (Turbofit), no key involved.

        Thinking is disabled: a reasoning model here spends the whole token budget
        on ``reasoning_content`` and returns ``content: null``, which looks like an
        empty answer and fails the call. JSON tasks do not need it.
        """
        return cls(
            base_url=f"http://127.0.0.1:{port}/v1",
            model=model,
            extra_body={"chat_template_kwargs": {"enable_thinking": False}},
        )

    # -- internals ---------------------------------------------------------
    def _post(self, body: Mapping[str, Any]) -> dict[str, Any]:
        payload = json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=payload,
            headers={
                "Content-Type": "application/json",
                **({"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}),
            },
            method="POST",
        )
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    body_text = response.read().decode("utf-8", "replace")
                return json.loads(body_text)
            except urllib.error.HTTPError as exc:
                last_error = exc
                if exc.code < 500 and exc.code != 429:
                    raise LLMError(f"HTTP {exc.code} from {self.base_url}") from exc
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                last_error = exc
            # Backoff: 0.5s, 1s, 2s ...
            time.sleep(0.5 * (2**attempt))
        raise LLMError(f"model call failed after {self.retries + 1} attempts: {last_error}")

    # -- api ---------------------------------------------------------------
    def complete_json(
        self,
        *,
        prompt: str,
        payload: Mapping[str, Any],
        schema_hint: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.calls += 1
        user_content = (
            f"{prompt}\n\nInput JSON:\n{json.dumps(payload, sort_keys=True)[:12000]}"
        )
        if schema_hint:
            user_content += (
                f"\n\nResponse shape:\n{json.dumps(schema_hint, sort_keys=True)}"
            )
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "You return JSON only. No prose, no markdown."},
                {"role": "user", "content": user_content},
            ],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        body.update(self.extra_body)
        # A reasoning model can return content: null after spending its budget on
        # reasoning_content. Retry once with the same body (thinking is already off
        # on this client) before giving up - audit M1-F5: 22% of items failed this way.
        last_error: Exception | None = None
        for _attempt in range(2):
            response = self._post(body)
            usage = response.get("usage") if isinstance(response, dict) else None
            if isinstance(usage, dict):
                self.prompt_tokens += int(usage.get("prompt_tokens") or 0)
                self.completion_tokens += int(usage.get("completion_tokens") or 0)
            try:
                content = response["choices"][0]["message"]["content"]
            except (KeyError, IndexError, TypeError) as exc:
                last_error = exc
                continue
            if isinstance(content, str) and content.strip():
                return parse_json_object(content)
            last_error = LLMError("model returned empty content")
        raise LLMError(f"model returned no usable content ({last_error})")


class FallbackLLM:
    """Try the primary client, then a fallback route, and count both (audit M1-F5)."""

    def __init__(self, primary: Any, fallback: Any | None = None) -> None:
        self.primary = primary
        self.fallback = fallback
        self.name = getattr(primary, "name", "primary")
        self.primary_failures = 0
        self.fallback_used = 0
        self.calls = 0

    def complete_json(self, **kwargs: Any) -> dict[str, Any]:
        self.calls += 1
        try:
            return self.primary.complete_json(**kwargs)
        except LLMError:
            self.primary_failures += 1
            if self.fallback is None:
                raise
            self.fallback_used += 1
            return self.fallback.complete_json(**kwargs)

    def stats(self) -> dict[str, int]:
        return {
            "calls": self.calls,
            "primary_failures": self.primary_failures,
            "fallback_used": self.fallback_used,
        }


class HermesCtxLLMClient:
    """Wrap Hermes' ``ctx.llm`` (plugin path, wired in M2)."""

    def __init__(self, ctx: Any, *, purpose: str = "agent-reel") -> None:
        self.ctx = ctx
        self.purpose = purpose
        self.name = "hermes-ctx"  # pragma: no cover - host dependent

    def complete_json(
        self,
        *,
        prompt: str,
        payload: Mapping[str, Any],
        schema_hint: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not hasattr(self.ctx, "llm"):  # pragma: no cover - host dependent
            raise LLMError("ctx has no llm client")
        response = self.ctx.llm.complete_structured(  # pragma: no cover - host dependent
            prompt=prompt,
            payload=payload,
            schema=schema_hint or {},
            purpose=self.purpose,
        )
        if isinstance(response, Mapping):
            return dict(response)
        if isinstance(response, str):
            return parse_json_object(response)
        raise LLMError("ctx.llm returned an unexpected type")


def client_from_env() -> OpenAICompatLLMClient | None:
    """Build a local client when the rig's serving route is reachable."""
    base_url = os.environ.get("REEL_LLM_BASE_URL")
    if not base_url:
        return None
    return OpenAICompatLLMClient(
        base_url=base_url,
        model=os.environ.get("REEL_LLM_MODEL", "auto"),
        api_key=os.environ.get("REEL_LLM_API_KEY") or None,
    )


# --------------------------------------------------------------------------- #
# Call budget (round 4, kept in round 5)
# --------------------------------------------------------------------------- #
#
# Round 4 sent the writer through the Hermes API server. That is dropped: it is a full
# agent, so every call carried the Hermes system prompt (~57k prompt tokens) and the
# "judge" was an agent persona rather than a clean model. The writer now runs on
# ctx.llm through adapters/hermes/plugin_llm.py. The budget guard stays because a run
# still has to be bounded.

class BudgetExceeded(LLMError):
    """A run spent more model calls than its budget allows."""


class BudgetedLLM:
    """A thin guard around a client: a hard call cap, and nothing else."""

    def __init__(self, inner: Any, *, max_calls: int = 150, name: str = "writer") -> None:
        self.inner = inner
        self.name = name
        self.max_calls = max_calls
        self.calls = 0

    def complete_json(self, **kwargs: Any) -> dict[str, Any]:
        if self.calls >= self.max_calls:
            raise BudgetExceeded(
                f"{self.name} budget exhausted: {self.calls}/{self.max_calls} calls"
            )
        self.calls += 1
        return self.inner.complete_json(**kwargs)

    def usage(self) -> dict[str, Any]:
        inner = getattr(self.inner, "usage", None)
        payload = dict(inner() if callable(inner) else {})
        payload.update({"calls": self.calls, "budget": self.max_calls})
        return payload
