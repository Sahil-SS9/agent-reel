"""R2-F3: thinking is off by default, so a new caller cannot silently quarantine."""

from __future__ import annotations

import json

import pytest

from adapters.hermes.llm import FallbackLLM, OpenAICompatLLMClient
from canon.llm import LLMError


def test_thinking_is_off_by_default():
    client = OpenAICompatLLMClient(base_url="http://127.0.0.1:9/v1", model="m")
    assert client.extra_body["chat_template_kwargs"]["enable_thinking"] is False


def test_a_caller_can_still_ask_for_thinking():
    client = OpenAICompatLLMClient(base_url="http://127.0.0.1:9/v1", model="m", thinking=True)
    assert client.extra_body["chat_template_kwargs"]["enable_thinking"] is True


def test_an_explicit_extra_body_wins():
    client = OpenAICompatLLMClient(
        base_url="http://127.0.0.1:9/v1",
        model="m",
        extra_body={"chat_template_kwargs": {"enable_thinking": False}, "top_k": 7},
    )
    assert client.extra_body["top_k"] == 7
    assert client.extra_body["chat_template_kwargs"]["enable_thinking"] is False


def test_the_local_helper_still_disables_thinking():
    client = OpenAICompatLLMClient.local(port=8091)
    assert client.extra_body["chat_template_kwargs"]["enable_thinking"] is False


def test_an_empty_response_is_retried_then_raises():
    """The 22%-quarantine failure mode: content null. Retried once, then a clear error."""

    class Counting(OpenAICompatLLMClient):
        def __init__(self):
            super().__init__(base_url="http://127.0.0.1:9/v1", model="m")
            self.posts = 0

        def _post(self, body):  # noqa: D401 - test seam
            self.posts += 1
            return {"choices": [{"message": {"content": None}}]}

    client = Counting()
    with pytest.raises(LLMError) as excinfo:
        client.complete_json(prompt="x", payload={"a": 1})
    assert client.posts == 2, "an empty response should be retried once"
    assert "no usable content" in str(excinfo.value)


def test_fallback_is_used_and_counted():
    class Broken:
        name = "broken"

        def complete_json(self, **_kwargs):
            raise LLMError("down")

    class Good:
        name = "good"

        def complete_json(self, **_kwargs):
            return {"ok": True}

    llm = FallbackLLM(Broken(), Good())
    assert llm.complete_json(prompt="p", payload={}) == {"ok": True}
    stats = llm.stats()
    assert stats == {"calls": 1, "primary_failures": 1, "fallback_used": 1}


def test_no_fallback_raises_the_primary_error():
    class Broken:
        name = "broken"

        def complete_json(self, **_kwargs):
            raise LLMError("down")

    llm = FallbackLLM(Broken(), None)
    with pytest.raises(LLMError):
        llm.complete_json(prompt="p", payload={})
    assert llm.stats()["primary_failures"] == 1
