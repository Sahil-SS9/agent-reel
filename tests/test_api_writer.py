"""R3-F6: the writer uses the owner's main model via the local API server."""

from __future__ import annotations

import json

import pytest

from adapters.hermes.llm import (
    API_SERVER_BASE_URL,
    API_SERVER_MODEL,
    BudgetedLLM,
    BudgetExceeded,
    OpenAICompatLLMClient,
    api_server_client,
    read_api_server_key,
)


def test_the_key_is_read_from_the_env_file(tmp_path):
    env = tmp_path / ".env"
    env.write_text('SOMETHING=1\nAPI_SERVER_KEY=test-key-value\nOTHER=2\n', encoding="utf-8")
    assert read_api_server_key(env) == "test-key-value"


def test_a_missing_env_file_means_no_key(tmp_path):
    assert read_api_server_key(tmp_path / "nope.env") == ""


def test_the_client_builds_from_the_api_server(tmp_path):
    env = tmp_path / ".env"
    env.write_text("API_SERVER_KEY=k\n", encoding="utf-8")
    writer = api_server_client(env_path=env)
    inner = writer.inner
    assert isinstance(inner, OpenAICompatLLMClient)
    assert inner.base_url == API_SERVER_BASE_URL
    assert inner.model == API_SERVER_MODEL
    assert inner.api_key == "k"


def test_the_key_cannot_leak_through_repr():
    client = OpenAICompatLLMClient(base_url="http://127.0.0.1:1/v1", model="m", api_key="secret-key")
    assert "secret-key" not in repr(client)


def test_tokens_are_counted_from_the_usage_block():
    class Counting(OpenAICompatLLMClient):
        def _post(self, body):
            return {
                "choices": [{"message": {"content": json.dumps({"ok": True})}}],
                "usage": {"prompt_tokens": 11, "completion_tokens": 7},
            }

    client = Counting(base_url="http://127.0.0.1:1/v1", model="m")
    client.complete_json(prompt="p", payload={"a": 1})
    client.complete_json(prompt="p", payload={"a": 2})
    assert client.usage() == {"calls": 2, "prompt_tokens": 22, "completion_tokens": 14}


def test_the_budget_is_enforced():
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
    assert writer.usage()["budget"] == 2


def test_the_default_budget_matches_the_audit():
    writer = api_server_client(env_path="/nonexistent")
    assert writer.max_calls == 150


def test_the_redaction_endpoint_is_not_the_api_server():
    """Redaction stays on the local model: only post-gate text leaves the process."""
    local = OpenAICompatLLMClient.local()
    assert local.base_url == "http://127.0.0.1:8091/v1"
    assert local.base_url != API_SERVER_BASE_URL
