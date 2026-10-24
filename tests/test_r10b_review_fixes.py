"""Round 10b: Quan's QAR10-01/02 (independent review of r10).

QAR10-01: an allowlisted cast name swapped in as the actor was never checked, because
allowlisted words were skipped and a one-word sentence start was not treated as a name.
QAR10-02: numbers were compared as substrings, so "4" was backed by "14".
"""

from __future__ import annotations

import pytest

from canon.grounding import ClaimGate, check_terms


class AlwaysYes:
    def __init__(self) -> None:
        self.calls = 0

    def complete_json(self, *, prompt, payload, schema_hint=None, stage=""):
        self.calls += 1
        return {"supported": True, "unbacked": []}


CAST = ("Sahil", "Kensei")


@pytest.mark.parametrize("llm", [None, "yes"])
def test_actor_swap_at_sentence_start_is_refused(llm):
    model = AlwaysYes() if llm else None
    gate = ClaimGate(model, allow=CAST, cast=CAST)
    verdict = gate.check("Kensei approved the release.", "Sahil approved the release.", layer="caption")
    assert not verdict.supported
    assert "Kensei" in verdict.reason
    if model is not None:
        assert model.calls == 0  # refused before the model is asked


def test_actor_present_in_evidence_still_passes():
    gate = ClaimGate(None, allow=CAST, cast=CAST)
    assert gate.check("Sahil approved the release.", "Sahil approved the release.", layer="caption").supported


@pytest.mark.parametrize(
    "evidence, caption",
    [
        ("The suite passed all 14 tests.", "The suite passed all 4 tests."),
        ("It took 2.85 seconds.", "It took 2.8 seconds."),
        ("The run gated 81,152 events.", "The run gated 1,152 events."),
        ("It finished at 09:40.", "It finished at 9:4."),
        ("Scores were 87.3 and 79.5.", "Scores were 87 and 79.5."),
    ],
)
@pytest.mark.parametrize("llm", [None, "yes"])
def test_changed_number_is_refused_before_the_model(evidence, caption, llm):
    model = AlwaysYes() if llm else None
    verdict = ClaimGate(model).check(caption, evidence, layer="caption")
    assert not verdict.supported, caption
    if model is not None:
        assert model.calls == 0


@pytest.mark.parametrize(
    "evidence, caption",
    [
        ("The suite passed all 14 tests.", "The suite passed all 14 tests."),
        ("The run gated 81,152 events.", "The run gated 81152 events."),
        ("It finished at 09:40.", "It finished at 09:40."),
        ("Scores were 87.3 and 79.5.", "Scores were 87.3 and 79.5."),
    ],
)
def test_same_number_still_passes(evidence, caption):
    assert check_terms(caption, evidence).invented_numbers == ()
    assert ClaimGate(None).check(caption, evidence, layer="caption").supported
