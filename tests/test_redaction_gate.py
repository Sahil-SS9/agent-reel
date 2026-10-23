"""M1: the redaction gate."""

from __future__ import annotations

import pytest

from adapters.hermes.redact_source import rules_from_snapshot
from canon.events import build_event
from canon.llm import FakeLLM
from canon.cache import ModelCache
from canon.redact import (
    DeterministicRedactor,
    LeakResidue,
    ModelEntityGate,
    RedactionGate,
    candidate_names,
)
from canon.llm import CachedLLM


def make_gate(**kwargs) -> RedactionGate:
    redactor = DeterministicRedactor(rules_from_snapshot())
    return RedactionGate(redactor, **kwargs)


def _event(text_key: str = "text", **payload) -> object:
    return build_event(
        source="message",
        kind="message.user",
        ts=1700000000.0,
        profile="alpha",
        payload={"chars": 10, **payload},
        store="profile:alpha",
        table="messages",
        pk=str(text_key),
    )


# --------------------------------------------------------------------------- #
# deterministic pass
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "text, secret_value, category",
    [
        ("token sk-proj-AbCdEfGhIjKlMnOpQrStUv", "sk-proj-AbCdEfGhIjKlMnOpQrStUv", "secret"),
        ("ghp_9dQ2mXb7Vc4RtY8Np1Ls6Kw3Jz5Hg0Fa2Ed", "ghp_9dQ2mXb7Vc4RtY8Np1Ls6Kw3Jz5Hg0Fa2Ed", "secret"),
        ("AKIAIOSFODNN7EXAMPLE", "AKIAIOSFODNN7EXAMPLE", "secret"),
        ("Authorization: Bearer 9dQ2mXb7Vc4RtY8Np1Ls", "9dQ2mXb7Vc4RtY8Np1Ls", "secret"),
        ("OPENAI_API_KEY=sk-proj-QwErTyUiOp3AsDfGhJkLz", "sk-proj-QwErTyUiOp3AsDfGhJkLz", "secret"),
        ("the address is sahil@example.com", "sahil@example.com", "email"),
        ("ring 07700 900123 now", "07700 900123", "phone"),
        ("host 192.168.1.24 answered", "192.168.1.24", "ip"),
        ("open /home/someone/private/notes.txt", "/home/someone/private/notes.txt", "path"),
        # A signed URL trips both the URL rule and the credential rule; what
        # matters is that the token itself is gone, not which rule claimed it.
        ("https://x.test/a?token=9dQ2mXb7Vc4RtY8Np", "9dQ2mXb7Vc4RtY8Np", "url_token"),
    ],
)
def test_deterministic_pass_redacts_known_shapes(text, secret_value, category):
    gate = make_gate()
    redacted, findings = gate.redact_text(text)
    assert secret_value not in redacted, "the labelled value survived the gate"
    assert "[REDACTED:" in redacted
    assert category in {finding.category for finding in findings} or "secret" in {
        finding.category for finding in findings
    }


def test_email_is_not_double_masked():
    gate = make_gate()
    redacted, findings = gate.redact_text("mail sahil@example.com today")
    assert redacted.count("[REDACTED") == 1
    assert findings[0].category == "email"


def test_clean_text_passes_through_unchanged():
    gate = make_gate()
    text = "The rig hummed and the tests went green."
    assert gate.redact_text(text) == (text, ())


def test_timestamps_and_counts_are_not_mangled():
    """Over-redaction would wreck the story: epoch times and counts must survive."""
    gate = make_gate()
    text = "session started 1792745629 with 400 messages and 171 tool calls"
    redacted, findings = gate.redact_text(text)
    assert "1792745629" in redacted
    assert findings == ()


def test_residue_fails_closed():
    class BrokenRedactor(DeterministicRedactor):
        def redact(self, text):  # always claims there is nothing to do
            from canon.redact import RedactionResult

            return RedactionResult(text, ())

    rules = rules_from_snapshot()
    redactor = BrokenRedactor(rules)
    gate = RedactionGate(redactor)
    # findngs() still uses the real patterns, so the residue check trips.
    with pytest.raises(LeakResidue):
        gate.redact_text("mail me at sahil@example.com")


# --------------------------------------------------------------------------- #
# gate events
# --------------------------------------------------------------------------- #


def test_gate_event_releases_a_gated_event_with_text():
    gate = make_gate()
    sealed = gate.gate_event(_event(), text="ring 07700 900123 about the build")
    assert sealed is not None
    assert sealed.payload["text"].startswith("ring [REDACTED:phone#")
    assert sealed.payload["text_digest"].startswith("sha256:")
    assert "phone" in sealed.payload["gate"]["findings"]


def test_gate_event_quarantines_on_model_error():
    class ExplodingLLM:
        name = "explodes"

        def complete_json(self, **_kwargs):
            from canon.llm import LLMError

            raise LLMError("provider 500")

    cache = ModelCache.__new__(ModelCache)  # not used: the call fails first
    gate = make_gate(model_gate=ModelEntityGate(_CachedStub(ExplodingLLM())))
    sealed = gate.gate_event(_event(), text="Priya Raman signed off", deep=True)
    assert sealed is None
    assert gate.report.quarantined
    assert gate.report.quarantined[0].reason == "model_error"


class _CachedStub:
    """Minimal CachedLLM stand-in that always calls through."""

    def __init__(self, client):
        self.client = client
        self.name = client.name

    def complete_json(self, **kwargs):
        return self.client.complete_json(**kwargs)


def test_unstructured_payload_strings_are_redacted_too():
    gate = make_gate()
    event = _event(owner_email="sahil@example.com", nested={"ip": "10.0.0.17"})
    sealed = gate.gate_event(event)
    assert sealed is not None
    assert "[REDACTED:email#" in sealed.payload["owner_email"]
    assert "[REDACTED:ip#" in sealed.payload["nested"]["ip"]


def test_privacy_rides_along_to_the_gated_event():
    gate = make_gate()
    event = build_event(
        source="message",
        kind="message.user",
        ts=1.0,
        payload={},
        store="main",
        table="messages",
        pk="1",
        privacy="internal",
    )
    sealed = gate.gate_event(event)
    assert sealed is not None
    assert sealed.privacy == "internal"
    assert sealed.payload["gate"]["privacy"] == "internal"


def test_unknown_privacy_level_is_refused_at_gate_construction():
    with pytest.raises(ValueError):
        make_gate(privacy="top-secret")


# --------------------------------------------------------------------------- #
# model pass
# --------------------------------------------------------------------------- #


def test_candidate_names_skips_allowlist_and_stopwords():
    names = candidate_names(
        "On Friday Sahil met Mike Harrington at Kestrel Labs", ["Sahil", "Kestrel Labs"]
    )
    assert "Mike Harrington" in names
    assert "Sahil" not in names
    assert "Friday" not in names


def test_vocabulary_pass_masks_names_found_by_the_model(tmp_path):
    responses = {
        "redact.vocabulary": lambda payload: {
            "results": [
                {
                    "name": name,
                    "category": "person_name" if " " in name or name in {"Priya", "Raman"} else "safe",
                }
                for name in payload["candidates"]
            ]
        }
    }
    fake = FakeLLM({}, default=responses["redact.vocabulary"])
    cached = CachedLLM(fake, ModelCache(tmp_path / "cache"), stage="test")
    model_gate = ModelEntityGate(cached, allowlist=("Sahil",))
    gate = make_gate(model_gate=model_gate, allowlist=("Sahil",))
    gate.learn_vocabulary(["Priya Raman signed off", "Sahil asked for it"])
    redacted, findings = gate.redact_text("Priya Raman signed off and Sahil asked")
    assert "[REDACTED:person_name#" in redacted
    assert "Sahil" in redacted
    assert "person_name" in {finding.category for finding in findings}


def test_vocabulary_failure_fails_closed():
    class Exploding:
        name = "boom"

        def complete_json(self, **_kwargs):
            from canon.llm import LLMError

            raise LLMError("down")

    cached = _CachedStub(Exploding())
    model_gate = ModelEntityGate(cached, allowlist=())
    verdicts = model_gate.classify_vocabulary(["Mike Harrington"])
    assert verdicts == {"Mike Harrington": "person_name"}


def test_vocabulary_is_cached(tmp_path):
    calls = {"n": 0}

    def responder(payload):
        calls["n"] += 1
        return {"results": [{"name": name, "category": "safe"} for name in payload["candidates"]]}

    fake = FakeLLM({}, default=responder)
    cache = ModelCache(tmp_path / "cache")
    for _ in range(2):
        cached = CachedLLM(fake, cache, stage="test")
        model_gate = ModelEntityGate(cached, allowlist=())
        model_gate.classify_vocabulary(["Mike Harrington", "Priya Raman"])
    assert calls["n"] == 1, "the second run should have been a cache hit"
