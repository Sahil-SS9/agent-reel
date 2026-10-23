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
        max_tokens: int = 900,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout = timeout
        self.retries = retries
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.name = f"openai-compat:{model}"
        self.calls = 0

    @classmethod
    def local(cls, model: str = "auto", port: int = 8091) -> "OpenAICompatLLMClient":
        """The rig's local serving route (Turbofit), no key involved."""
        return cls(base_url=f"http://127.0.0.1:{port}/v1", model=model)

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
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "You return JSON only. No prose, no markdown."},
                {"role": "user", "content": user_content},
            ],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        response = self._post(body)
        try:
            content = response["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"unexpected response shape: {exc}") from exc
        if not isinstance(content, str) or not content.strip():
            raise LLMError("model returned empty content")
        return parse_json_object(content)


class HermesCtxLLMClient:
    """Wrap Hermes' ``ctx.llm`` (plugin path, wired in M2)."""

    def __init__(self, ctx: Any, *, purpose: str = "scrollback-reel") -> None:
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
