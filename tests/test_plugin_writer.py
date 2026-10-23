"""Round 5 Step 0: the writer runs on ctx.llm, and its tokens are counted per call."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

import pytest

from adapters.hermes.llm import BudgetedLLM, BudgetExceeded
from adapters.hermes.plugin_llm import PluginLLMClient
from canon.llm import LLMError


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class Result:
    text: str
    usage: Usage


class FakeCtxLlm:
    """Stands in for the host facade: a raw completion, no Hermes system prompt."""

    def __init__(self, replies, *, input_tokens=900, output_tokens=40):
        self.replies = list(replies)
        self.calls = []
        self._in = input_tokens
        self._out = output_tokens

    def complete(self, messages, **kwargs):
        self.calls.append({"messages": messages, **kwargs})
        return Result(self.replies.pop(0), Usage(self._in, self._out))


def test_the_writer_speaks_the_pipeline_client_interface():
    llm = FakeCtxLlm([json.dumps({"title": "A title"})])
    client = PluginLLMClient(llm)
    assert client.complete_json(prompt="p", payload={"a": 1}) == {"title": "A title"}


def test_tokens_are_counted_per_call():
    llm = FakeCtxLlm([json.dumps({"ok": 1}), json.dumps({"ok": 2})], input_tokens=700, output_tokens=25)
    client = PluginLLMClient(llm)
    client.complete_json(prompt="p", payload={})
    client.complete_json(prompt="p", payload={})
    usage = client.usage()
    assert usage["calls"] == 2
    assert usage["prompt_tokens"] == 1400
    assert usage["completion_tokens"] == 50
    assert usage["max_prompt_tokens_per_call"] == 700
    assert [row["call"] for row in client.per_call] == [1, 2]


def test_each_call_is_logged_with_its_tokens(caplog):
    llm = FakeCtxLlm([json.dumps({"ok": 1})], input_tokens=321, output_tokens=12)
    client = PluginLLMClient(llm)
    with caplog.at_level(logging.INFO):
        client.complete_json(prompt="p", payload={}, stage="episode.title")
    assert "prompt_tokens=321" in caplog.text
    assert "completion_tokens=12" in caplog.text
    assert "episode.title" in caplog.text


def test_no_host_llm_is_a_named_error():
    with pytest.raises(LLMError) as excinfo:
        PluginLLMClient(None).complete_json(prompt="p", payload={})
    assert "ctx.llm is not available" in str(excinfo.value)


def test_an_empty_answer_is_an_error_not_a_silent_pass():
    llm = FakeCtxLlm(["   "])
    with pytest.raises(LLMError):
        PluginLLMClient(llm).complete_json(prompt="p", payload={})


def test_prose_instead_of_json_is_an_error():
    llm = FakeCtxLlm(["I think the title should be about the adapter."])
    with pytest.raises(LLMError):
        PluginLLMClient(llm).complete_json(prompt="p", payload={})


def test_the_call_budget_is_enforced():
    llm = FakeCtxLlm([json.dumps({"ok": 1})])
    client = PluginLLMClient(llm, max_calls=1)
    client.complete_json(prompt="p", payload={})
    with pytest.raises(LLMError):
        client.complete_json(prompt="p", payload={})


def test_the_budget_guard_still_wraps_any_client():
    class Fine:
        name = "fine"

        def complete_json(self, **_kwargs):
            return {"ok": True}

    writer = BudgetedLLM(Fine(), max_calls=2)
    writer.complete_json(prompt="p", payload={})
    writer.complete_json(prompt="p", payload={})
    with pytest.raises(BudgetExceeded):
        writer.complete_json(prompt="p", payload={})
    assert writer.usage()["calls"] == 2


def test_no_api_server_route_remains():
    import adapters.hermes.llm as llm_module

    assert not hasattr(llm_module, "api_server_client")
    assert not hasattr(llm_module, "read_api_server_key")
