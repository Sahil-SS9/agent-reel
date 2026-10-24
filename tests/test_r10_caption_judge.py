"""Round 10: the caption judge.

r9 blamed the model for refusing true captions. The run cache disagreed: the model was
asked six times and said yes six times. The refusals came from the deterministic term
rule, which demanded that every content word of a caption appear verbatim in the
evidence - so any paraphrase failed before the model was ever asked.

The rule now matches the older GroundingGate design: names and numbers are always
checked deterministically; with a model, a caption needs a minimum term overlap and
then entailment decides; without a model the full-overlap rule stays (fail closed).
"""

from __future__ import annotations

from canon.grounding import ClaimGate, extract_claims


class FakeLLM:
    """Records calls; answers with a fixed verdict."""

    def __init__(self, supported: bool) -> None:
        self.supported = supported
        self.calls: list[dict] = []

    def complete_json(self, *, prompt, payload, schema_hint=None, stage=""):
        self.calls.append(dict(payload))
        return {"supported": self.supported, "unbacked": [] if self.supported else ["x"]}


EVIDENCE = (
    "The verify step did not run. It needed approval and the approval prompt "
    "timed out after 5 minutes."
)
PARAPHRASE = "The verification command never ran: it needed approval, and the prompt timed out after 5 minutes."


def test_true_paraphrase_reaches_the_model_and_passes():
    llm = FakeLLM(True)
    verdict = ClaimGate(llm).check(PARAPHRASE, EVIDENCE, layer="caption")
    assert verdict.supported, verdict.reason
    assert len(llm.calls) == 1
    # the judge is told which words it must look at
    assert "verification" in " ".join(llm.calls[0].get("terms_not_in_evidence", []))


def test_model_refusal_still_refuses():
    verdict = ClaimGate(FakeLLM(False)).check(PARAPHRASE, EVIDENCE, layer="caption")
    assert not verdict.supported
    assert verdict.model_checked


def test_without_a_model_the_full_overlap_rule_stays():
    verdict = ClaimGate(None).check(PARAPHRASE, EVIDENCE, layer="caption")
    assert not verdict.supported


def test_low_overlap_caption_is_refused_without_asking_the_model():
    llm = FakeLLM(True)
    verdict = ClaimGate(llm).check(
        "Quarterly revenue forecasts collapsed amid regulatory scrutiny overseas.",
        EVIDENCE,
        layer="caption",
    )
    assert not verdict.supported
    assert llm.calls == []


def test_invented_number_is_refused_even_if_the_model_agrees():
    verdict = ClaimGate(FakeLLM(True)).check(
        "The verify step did not run; the prompt timed out after 9 minutes.",
        EVIDENCE,
        layer="caption",
    )
    assert not verdict.supported
    assert "9" in verdict.reason


def test_invented_acronym_is_a_name_claim():
    kinds = {(c.kind, c.text) for c in extract_claims("The GGUF latency spiked again.")}
    assert ("name", "GGUF") in kinds


def test_invented_acronym_is_refused_even_if_the_model_agrees():
    verdict = ClaimGate(FakeLLM(True)).check(
        "The GGUF approval prompt timed out after 5 minutes.", EVIDENCE, layer="caption"
    )
    assert not verdict.supported
    assert "GGUF" in verdict.reason
