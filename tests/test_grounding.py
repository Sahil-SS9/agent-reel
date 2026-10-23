"""M1-F1: the grounding gate - a line may only say what its events say."""

from __future__ import annotations

import dataclasses

import pytest

from canon.beats import beats_from_events
from canon.arcs import build_arc
from canon.canon import build_canon
from canon.cache import ModelCache
from canon.episode import LLMDialogueWriter, plan_episode, validate_ir
from canon.events import build_event
from canon.gate import seal
from canon.grounding import GroundingGate, check_terms, content_terms
from canon.llm import CachedLLM, FakeLLM

EVIDENCE = "denji-reviewer blocked the task after 2 failures. outcome: gave_up"


def test_invented_number_is_refused():
    gate = GroundingGate()
    verdict = gate.check("denji-reviewer blocked it after 5 failures.", EVIDENCE)
    assert not verdict.supported
    assert verdict.terms.invented_numbers == ("5",)


def test_invented_cause_is_refused_without_a_model():
    """The exact M1-F1 failure: a plausible cause that the evidence never states."""
    gate = GroundingGate()
    verdict = gate.check("the config was missing the timeout key.", EVIDENCE)
    assert not verdict.supported
    assert "config" in verdict.terms.invented


def test_supported_line_passes():
    gate = GroundingGate()
    verdict = gate.check("denji-reviewer blocked it after 2 failures.", EVIDENCE)
    assert verdict.supported, verdict.reason


def test_rephrasing_is_allowed_by_the_stem_match():
    gate = GroundingGate()
    assert gate.check("the task was blocked after 2 failures.", EVIDENCE).supported


def test_register_words_need_no_evidence():
    gate = GroundingGate()
    assert gate.check("honestly, denji-reviewer blocked it again.", EVIDENCE).supported


def test_content_terms_skip_stopwords_and_short_words():
    terms = content_terms("the task was blocked after 2 failures")
    assert "blocked" in terms and "failures" in terms
    assert "the" not in terms and "was" not in terms


def test_term_overlap_is_reported():
    report = check_terms("denji-reviewer blocked the config key.", EVIDENCE)
    assert 0 < report.overlap < 1
    assert "config" in report.invented


def test_model_can_refuse_a_line_the_terms_allow():
    """Rephrasing passes the terms; entailment is the check that catches a spin."""

    class Refuse:
        name = "refuse"

        def complete_json(self, **_kwargs):
            return {"supported": False, "invented": ["blocked on purpose"]}

    cached = CachedLLM(Refuse(), ModelCache.__new__(ModelCache), stage="t")
    cached.cache = _NullCache()
    verdict = GroundingGate(cached).check("denji-reviewer blocked it after 2 failures.", EVIDENCE)
    assert not verdict.supported
    assert "not entailed" in verdict.reason


class _NullCache:
    def get(self, _key):
        return None

    def set(self, _key, _value):
        return None


def test_model_error_fails_closed():
    class Exploding:
        name = "boom"

        def complete_json(self, **_kwargs):
            from canon.llm import LLMError

            raise LLMError("down")

    cached = CachedLLM(Exploding(), _NullCache(), stage="t")
    verdict = GroundingGate(cached).check("denji-reviewer blocked it after 2 failures.", EVIDENCE)
    assert not verdict.supported
    assert verdict.reason == "entailment check unavailable"


def test_literal_line_is_a_quote():
    gate = GroundingGate()
    line = gate.literal_line(EVIDENCE, limit=40)
    assert line in EVIDENCE or EVIDENCE.startswith(line.rstrip("."))
    assert gate.check(line, EVIDENCE).supported


# --------------------------------------------------------------------------- #
# through the episode planner
# --------------------------------------------------------------------------- #


def _episode(writer):
    events = []
    for index, (kind, text) in enumerate(
        [
            ("kanban.task.status", "blocked after 2 failures"),
            ("message.tool_result", "error: timeout talking to the runner"),
            ("kanban.task.status", "completed"),
        ]
    ):
        event = build_event(
            source="kanban",
            kind=kind,
            ts=float(index + 1),
            profile="wesker",
            subject=str(index),
            payload={"kind": "blocked" if index == 0 else "completed", "text": text},
            store="main",
            table="messages",
            pk=str(index),
        )
        events.append(seal(event, {"text": text, "kind": event.payload["kind"]}))
    beats = beats_from_events(events)
    arc = build_arc(beats)
    canon = build_canon(events, beats)
    evidence = {event.id: event.payload["text"] for event in events}
    ir = plan_episode(
        arc,
        beats,
        canon,
        writer=writer,
        grounder=GroundingGate(),
        evidence=evidence,
    )
    return events, beats, ir


class _LyingWriter:
    name = "liar"

    def write(self, panels):
        return {panel["role"]: [["wesker", "the config was missing the timeout key."]] for panel in panels}


class _HonestWriter:
    name = "honest"

    def write(self, panels):
        return {panel["role"]: [["wesker", panel.get("evidence", "").split("\n")[0][:80] or "it broke."]] for panel in panels}


def test_invented_lines_are_never_released():
    events, _beats, ir = _episode(_LyingWriter())
    assert ir.grounding["dropped"] > 0 or ir.grounding["rewritten"] > 0
    known = {event.id for event in events}
    assert validate_ir(ir, known_event_ids=known) == []
    for panel in ir.panels:
        for line in panel.lines:
            assert "timeout key" not in line.text.lower()


def test_grounded_lines_survive():
    _events, _beats, ir = _episode(_HonestWriter())
    assert ir.grounding["lines"] > 0
    assert ir.grounding["grounded_rate"] >= 0.5


def test_no_duplicate_lines_across_panels():
    _events, _beats, ir = _episode(_LyingWriter())
    texts = [line.text for panel in ir.panels for line in panel.lines]
    assert len(texts) == len(set(text.lower() for text in texts))


def test_the_eval_dataset_is_big_enough_and_one_hundred_percent_clean():
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "eval" / "grounding"))
    from eval.grounding.run import CASES, run  # type: ignore[import-not-found]

    assert len(CASES) >= 30, "the audit requires at least 30 synthetic beats"
    report = run(GroundingGate())
    assert report["ok"], report["released_unsupported"]
    assert report["invented_lines_refused"] == len(CASES)
    assert report["grounded_lines_passed"] == len(CASES)
