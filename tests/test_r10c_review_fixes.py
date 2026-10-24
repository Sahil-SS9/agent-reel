"""Round 10c: Quan's r10b re-review (t_8645faf5) - actor binding and number forms.

QAR10-01 remainder: allow-only callers, lowercase names, and an actor taking credit for
another actor's action when both appear in the cited evidence.
QAR10-02 remainder: sign, ordinal and version-prefixed figures.
"""

from __future__ import annotations

import pytest

from canon.grounding import ClaimGate, attribution_blocks


class AlwaysAgree:
    def __init__(self) -> None:
        self.calls = 0

    def complete_json(self, *, prompt, payload, schema_hint=None, stage=""):
        self.calls += 1
        return {"supported": True, "unbacked": []}


@pytest.mark.parametrize("with_model", [False, True])
def test_allow_only_caller_still_refuses_actor_swap(with_model):
    model = AlwaysAgree() if with_model else None
    verdict = ClaimGate(model, allow=("Sahil", "Kensei")).check(
        "Kensei approved the release.", "Sahil approved the release.", layer="caption"
    )
    assert not verdict.supported
    if model:
        assert model.calls == 0


@pytest.mark.parametrize("with_model", [False, True])
def test_lowercase_actor_swap_is_refused(with_model):
    model = AlwaysAgree() if with_model else None
    verdict = ClaimGate(model, allow=("Sahil", "Kensei"), cast=("Sahil", "Kensei")).check(
        "kensei approved the release.", "Sahil approved the release.", layer="caption"
    )
    assert not verdict.supported
    if model:
        assert model.calls == 0


@pytest.mark.parametrize("with_model", [False, True])
def test_cross_source_actor_action_swap_is_refused(with_model):
    model = AlwaysAgree() if with_model else None
    cast = ("Sahil", "Kensei", "Octacon")
    verdict = ClaimGate(model, allow=cast, cast=cast).check(
        "Kensei leaves Sahil one command to run.",
        "Kensei reported that the handoff was ready. Octacon reported one command for Sahil to run.",
        layer="caption",
    )
    assert not verdict.supported
    assert "Kensei" in verdict.reason
    if model:
        assert model.calls == 0


def test_cross_source_with_event_blocks_is_refused():
    cast = ("Sahil", "Kensei", "Octacon")
    evidence = (
        "Kensei reported the handoff is ready.\nIt has three phases and a reviewer.\n\n"
        "Octacon reported the one command for Sahil.\nRun the installer with the pinned ref."
    )
    verdict = ClaimGate(None, allow=cast, cast=cast).check(
        "Kensei leaves Sahil one command to run the installer.", evidence, layer="caption"
    )
    assert not verdict.supported


def test_true_attribution_across_lines_of_one_event_passes():
    cast = ("Sahil", "Kensei")
    evidence = (
        "Kensei reported the audit is complete.\nNo files were modified during the audit.\n\n"
        "Sahil asked for a read-only audit."
    )
    verdict = ClaimGate(None, allow=cast, cast=cast).check(
        "Kensei reported the audit is complete.", evidence, layer="caption"
    )
    assert verdict.supported, verdict.reason


def test_blocks_are_paragraphs_when_present_else_sentences():
    assert attribution_blocks("A did x.\nmore.\n\nB did y.") == ["A did x.\nmore.", "B did y."]
    assert attribution_blocks("A did x. B did y.") == ["A did x.", "B did y."]


@pytest.mark.parametrize(
    "evidence, caption",
    [
        ("The temperature reached -4 degrees.", "The temperature reached 4 degrees."),
        ("The 14th build passed.", "The 4th build passed."),
        ("Build v14 passed.", "Build v4 passed."),
        ("Release v2.3.1 shipped.", "Release v2.3 shipped."),
    ],
)
@pytest.mark.parametrize("with_model", [False, True])
def test_number_forms_are_refused_before_the_model(evidence, caption, with_model):
    model = AlwaysAgree() if with_model else None
    verdict = ClaimGate(model).check(caption, evidence, layer="caption")
    assert not verdict.supported, caption
    if model:
        assert model.calls == 0


@pytest.mark.parametrize(
    "evidence, caption",
    [
        ("The temperature reached -4 degrees.", "The temperature reached -4 degrees."),
        ("The 14th build passed.", "The 14th build passed."),
        ("Build v14 passed.", "Build v14 passed."),
        ("Scores were 87.3 and 79.5.", "Scores were 87.3 and 79.5."),
    ],
)
def test_same_number_forms_pass(evidence, caption):
    assert ClaimGate(None).check(caption, evidence, layer="caption").supported


def test_semicolon_clause_keeps_the_actor_bound():
    cast = ("Sahil", "Kensei")
    verdict = ClaimGate(None, allow=cast, cast=cast).check(
        "Kensei stopped the run on purpose; exit 143 was a SIGTERM, not a crash.",
        "kensei stopped the run on purpose; exit 143 was a SIGTERM, not a crash.",
        layer="caption",
    )
    assert verdict.supported, verdict.reason
    assert attribution_blocks("A did x; then y. B did z.") == ["A did x; then y.", "B did z."]
