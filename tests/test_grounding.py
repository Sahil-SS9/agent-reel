"""Round 3 item 1: claim-level grounding for both layers.

The r2 gate checked word overlap, so only a literal quote could pass. These tests pin
the behaviour that replaced it: claims are extracted (names, numbers, outcomes,
causes), names and numbers must appear in the evidence, causes and outcomes need the
model, and a line that makes no claim (a reaction) passes.
"""

from __future__ import annotations

import pytest

from canon.beats import beats_from_events
from canon.arcs import build_arc
from canon.canon import build_canon
from canon.cache import ModelCache
from canon.episode import LLMDialogueWriter, plan_episode, validate_ir
from canon.events import build_event
from canon.gate import seal
from canon.grounding import ClaimGate, check_claims, extract_claims
from canon.llm import CachedLLM, FakeLLM, LLMError

EVIDENCE = "denji-reviewer blocked the task after 2 failures. outcome: gave up"


class _NullCache:
    def get(self, _key):
        return None

    def set(self, _key, _value):
        return None


def gate(**kwargs) -> ClaimGate:
    return ClaimGate(**kwargs)


# --------------------------------------------------------------------------- #
# claim extraction
# --------------------------------------------------------------------------- #


def test_numbers_are_claims():
    claims = extract_claims("it failed 3 times")
    assert any(claim.kind == "number" and claim.text == "3" for claim in claims)


def test_causes_and_outcomes_are_claims():
    kinds = {claim.kind for claim in extract_claims("it broke because the config was missing")}
    assert "cause" in kinds and "outcome" in kinds


def test_a_pure_reaction_carries_no_claim():
    assert extract_claims("Ugh. Not again.") == ()


def test_names_are_claims():
    claims = extract_claims("Then Mara Vance called")
    assert any(claim.kind == "name" and "Mara" in claim.text for claim in claims)


# --------------------------------------------------------------------------- #
# the gate
# --------------------------------------------------------------------------- #


def test_an_invented_number_is_refused():
    verdict = gate().check("denji-reviewer blocked it after 5 failures.", EVIDENCE)
    assert not verdict.supported
    assert "number:5" in verdict.reason


def test_an_invented_cause_needs_a_model_and_fails_closed_without_one():
    verdict = gate().check("it broke because the config was missing.", EVIDENCE)
    assert not verdict.supported
    assert "needs a model" in verdict.reason


def test_a_supported_line_passes():
    verdict = gate().check("denji-reviewer blocked the task after 2 failures.", EVIDENCE)
    assert verdict.supported


def test_a_pure_reaction_passes_without_a_model():
    verdict = gate().check("Ugh. Not again.", EVIDENCE)
    assert verdict.supported
    assert "no claim" in verdict.reason


def test_the_model_can_refuse_a_line_the_claims_allow():
    class Refuse:
        name = "refuse"

        def complete_json(self, **_kwargs):
            return {"supported": False, "unbacked": ["the fix"]}

    cached = CachedLLM(Refuse(), _NullCache(), stage="t")
    verdict = gate(llm=cached).check("it gave up after 2 failures.", EVIDENCE)
    assert not verdict.supported
    assert "not entailed" in verdict.reason


def test_a_model_error_fails_closed():
    class Exploding:
        name = "boom"

        def complete_json(self, **_kwargs):
            raise LLMError("down")

    cached = CachedLLM(Exploding(), _NullCache(), stage="t")
    verdict = gate(llm=cached).check("it gave up after 2 failures.", EVIDENCE)
    assert not verdict.supported
    assert verdict.reason == "entailment check unavailable"


def test_the_literal_caption_is_short_and_grounded():
    g = gate(max_quote_words=8)
    caption = g.literal_caption(EVIDENCE)
    assert len(caption.split()) <= 8
    assert caption.rstrip(".") in EVIDENCE
    assert g.check(caption, EVIDENCE).supported


def test_verbatim_quotes_over_twelve_words_are_flagged():
    g = gate(max_quote_words=12)
    long_quote = " ".join(["denji-reviewer blocked the task after 2 failures and then"] * 3)
    assert not g.quote_ok(long_quote)
    assert g.quote_ok("denji-reviewer blocked the task")


# --------------------------------------------------------------------------- #
# through the planner: both layers
# --------------------------------------------------------------------------- #


def _events():
    rows = [
        ("blocked", "denji-reviewer blocked the task after 2 failures"),
        ("blocked", "denji-reviewer blocked it again"),
        ("completed", "wesker fixed the blocker"),
        ("completed", "wesker closed the task"),
    ]
    out = []
    for index, (kind_field, text) in enumerate(rows):
        payload = {"kind": kind_field, "text": text, "task_id": "t_a", "chars": len(text)}
        event = build_event(
            source="kanban",
            kind="kanban.task.status",
            ts=float(index + 1),
            profile="wesker" if index >= 2 else "denji-reviewer",
            actor="wesker" if index >= 2 else "denji-reviewer",
            subject=kind_field,
            payload=payload,
            store="main",
            table="tasks",
            pk=f"t_a-{index}",
        )
        out.append(seal(event, payload))
    return out


def _plan(writer, *, actors=True, llm=None):
    events = _events()
    beats = beats_from_events(events)
    arc = build_arc(beats)
    canon = build_canon(events, beats)
    evidence = {event.id: str(event.payload.get("text", "")) for event in events}
    actors_by_event = (
        {event.id: str(event.actor).capitalize() for event in events} if actors else None
    )
    cast_map = {"denji-reviewer": "Denji-reviewer", "wesker": "Wesker", "default": "Kensei"}
    return events, plan_episode(
        arc,
        beats,
        canon,
        writer=writer,
        grounder=ClaimGate(llm, allow=("Sahil", "Denji-reviewer", "Wesker")),
        evidence=evidence,
        actors_by_event=actors_by_event,
        cast_map=cast_map,
    )


class _LyingWriter:
    name = "liar"

    def write(self, panels):
        return {
            panel["role"]: {
                "caption": "the config was missing the timeout key",
                "lines": [["Wesker", "and then the GPU melted at 91 degrees"]],
            }
            for panel in panels
        }


class _HonestWriter:
    name = "honest"

    def write(self, panels):
        return {
            panel["role"]: {
                "caption": str(panel.get("evidence", "")).split("\n")[0][:70] or "It happened.",
                "lines": [["Wesker", "Ugh. Not again."]],
            }
            for panel in panels
        }


def test_invented_captions_and_lines_are_never_released():
    events, ir = _plan(_LyingWriter())
    # Only the script itself matters: the grounding report is allowed to say which
    # terms it refused.
    script = " ".join(
        [panel.caption for panel in ir.panels]
        + [panel.label for panel in ir.panels]
        + [line.text for panel in ir.panels for line in panel.lines]
        + [ir.logline]
    ).lower()
    assert "timeout key" not in script
    assert "melted" not in script
    assert "91" not in script
    assert ir.grounding["captions_repaired"] > 0 or ir.grounding["lines_dropped"] > 0
    assert validate_ir(ir, known_event_ids={event.id for event in events}) == []


def test_honest_lines_survive():
    _events, ir = _plan(_HonestWriter())
    assert ir.grounding["captions_supported"] > 0
    assert ir.grounding["lines_supported"] > 0


def test_a_speaker_who_is_not_an_actor_is_not_given_words():
    """R2-F2: kanban text written by another agent is never put in a speaker's mouth."""
    class WrongSpeaker:
        name = "wrong"

        def write(self, panels):
            return {
                panel["role"]: {
                    "caption": "",
                    "lines": [["Kensei", "I blocked the task after 2 failures"]],
                }
                for panel in panels
            }

    _events, ir = _plan(WrongSpeaker())
    for panel in ir.panels:
        for line in panel.lines:
            assert line.speaker != "Kensei", (
                "Kensei is not an actor of any cited event, so he cannot say the line"
            )


def test_no_duplicate_lines_or_captions():
    _events, ir = _plan(_LyingWriter())
    texts = [line.text.lower() for panel in ir.panels for line in panel.lines]
    assert len(texts) == len(set(texts))
    captions = [panel.caption.lower() for panel in ir.panels if panel.caption]
    assert len(captions) == len(set(captions))


def test_the_eval_dataset_is_clean():
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "eval" / "grounding"))
    from eval.grounding.run import CASES, run  # type: ignore[import-not-found]

    assert len(CASES) >= 30
    report = run(ClaimGate())
    assert report["ok"], report["released_unsupported"]
    assert report["invented_lines_refused"] == len(CASES)
