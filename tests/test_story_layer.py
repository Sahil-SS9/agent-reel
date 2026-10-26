"""The story layer: narration may interpret, it may not add an event.

The caption layer restates facts, so a caption could only ever read like a log line. The
story layer lets narration carry stakes, feeling and motive while keeping the things that
can be wrong (names, numbers, outcomes, causes, who did what) under the same checks.
"""

from __future__ import annotations

import argparse
from types import SimpleNamespace

from canon.arcs import build_arc
from canon.beats import beats_from_events
from canon.canon import build_canon
from canon.episode import plan_episode
from canon.events import build_event
from canon.gate import seal
from canon.grounding import STORY_LAYER, ClaimGate
from canon.llm import CachedLLM
from canon.story import NARRATION_LAYER, SYNOPSIS_PROMPT, write_synopsis

EVIDENCE = (
    "Sahil asked Kensei to move the nightly job. Kensei moved it. "
    "The old job had been timing out for 2 nights."
)
CAST = ("Sahil", "Kensei", "Octacon")


class _NullCache:
    def get(self, _key):
        return None

    def set(self, _key, _value):
        return None


class _Judge:
    """A model that answers the same way every time and remembers what it was asked."""

    name = "judge"

    def __init__(self, supported: bool = True) -> None:
        self.supported = supported
        self.prompts: list[str] = []

    def complete_json(self, **kwargs):
        self.prompts.append(kwargs["prompt"])
        return {"supported": self.supported, "unbacked": [] if self.supported else ["a new event"]}


def _gate(judge: _Judge | None = None, **kwargs) -> ClaimGate:
    llm = CachedLLM(judge, _NullCache(), stage="t") if judge is not None else None
    return ClaimGate(llm, allow=CAST, cast=CAST, **kwargs)


# --------------------------------------------------------------------------- #
# the gate
# --------------------------------------------------------------------------- #


def test_the_layer_name_is_shared():
    assert STORY_LAYER == NARRATION_LAYER == "story"


def test_an_invented_number_is_refused_before_any_model_is_asked():
    judge = _Judge(True)
    verdict = _gate(judge).check("Sahil fought it for 5 nights.", EVIDENCE, layer="story")
    assert not verdict.supported
    assert "number:5" in verdict.reason
    assert judge.prompts == []


def test_an_invented_name_is_refused_before_any_model_is_asked():
    judge = _Judge(True)
    verdict = _gate(judge).check("Priya had warned him about it.", EVIDENCE, layer="story")
    assert not verdict.supported
    assert "name:" in verdict.reason
    assert judge.prompts == []


def test_a_named_character_must_be_in_the_evidence():
    judge = _Judge(True)
    verdict = _gate(judge).check("Octacon was already worried.", EVIDENCE, layer="story")
    assert not verdict.supported
    assert "unbacked actor Octacon" in verdict.reason
    assert judge.prompts == []


def test_without_a_model_the_story_layer_is_exactly_as_strict_as_a_caption():
    gate = _gate()
    line = "The whole week depended on that job."
    story, caption = gate.check(line, EVIDENCE, layer="story"), gate.check(line, EVIDENCE, layer="caption")
    assert not story.supported and not caption.supported
    assert story.reason == caption.reason
    # A line the evidence already states is fine on both.
    assert gate.check("Kensei moved it.", EVIDENCE, layer="story").supported


def test_the_model_can_pass_stakes_and_feeling():
    judge = _Judge(True)
    line = "The nightly job mattered more than Sahil would admit."
    verdict = _gate(judge).check(line, EVIDENCE, layer="story")
    assert verdict.supported and verdict.model_checked
    assert judge.prompts == [ClaimGate.STORY_PROMPT]


def test_the_caption_layer_still_refuses_that_same_line_for_vocabulary():
    # The point of the split: the strict layer cannot carry interpretation.
    verdict = _gate(_Judge(True)).check(
        "Everything rode on one stubborn reviewer.", "denji-reviewer blocked the task", layer="caption"
    )
    assert not verdict.supported
    assert "term overlap" in verdict.reason


def test_the_model_can_still_refuse_a_line_that_adds_an_event():
    verdict = _gate(_Judge(False)).check(
        "Kensei quietly rewrote the scheduler overnight.", EVIDENCE, layer="story"
    )
    assert not verdict.supported
    assert "not entailed" in verdict.reason


def test_a_story_line_that_cannot_be_judged_fails_closed():
    class Down:
        name = "down"

        def complete_json(self, **_kwargs):
            from canon.llm import LLMError

            raise LLMError("down")

    gate = _gate(Down())
    verdict = gate.check("The nightly job mattered more than Sahil would admit.", EVIDENCE, layer="story")
    assert not verdict.supported
    assert verdict.reason == "entailment check unavailable"
    assert gate.failures == 1


def test_a_question_asserts_nothing_so_it_needs_no_model():
    judge = _Judge(False)
    verdict = _gate(judge).check("Why would it do that?", EVIDENCE, layer="story")
    assert verdict.supported
    assert judge.prompts == []


def test_who_did_it_is_still_checked_when_the_line_states_an_outcome():
    judge = _Judge(True)
    evidence = "Octacon fixed the release. Kensei watched."
    verdict = _gate(judge).check("Kensei fixed the release.", evidence, layer="story")
    assert not verdict.supported
    assert "actor not bound" in verdict.reason
    assert judge.prompts == []


# --------------------------------------------------------------------------- #
# the synopsis
# --------------------------------------------------------------------------- #

FIELDS = {
    "title": "The Night Job",
    "logline": "Sahil needs the nightly job moved before it fails again.",
    "want": "Sahil wants the job moved.",
    "stakes": "Another failed night would cost him the weekend.",
    "obstacle": "The old job keeps timing out.",
    "turn": "Kensei moves it.",
    "ending": "The job runs.",
    "meaning": "Some fixes are quiet.",
}


class _SpyGate:
    def __init__(self) -> None:
        self.layers: list[str] = []

    def check(self, sentence, evidence, *, layer="dialogue", **_kwargs):
        self.layers.append(layer)
        return SimpleNamespace(supported=True, reason="")


def _synopsis(**kwargs):
    gate = _SpyGate()
    result = write_synopsis(
        lambda **_k: dict(FIELDS), title="x", facts_text="facts", brief_text="brief", gate=gate, **kwargs
    )
    return result, gate


def test_the_synopsis_is_judged_on_the_story_layer_by_default():
    result, gate = _synopsis()
    assert set(gate.layers) == {"story"}
    assert result.fields["stakes"] == FIELDS["stakes"]


def test_the_synopsis_can_be_kept_literal():
    _result, gate = _synopsis(layer="caption")
    assert set(gate.layers) == {"caption"}


def test_the_synopsis_prompt_allows_interpretation_but_not_events():
    assert "You may interpret" in SYNOPSIS_PROMPT
    assert "You may NOT add anything that happened" in SYNOPSIS_PROMPT


# --------------------------------------------------------------------------- #
# the planner
# --------------------------------------------------------------------------- #


def _events():
    rows = [
        ("blocked", "denji-reviewer blocked the task after 2 failures"),
        ("blocked", "denji-reviewer blocked it again"),
        ("completed", "wesker fixed the blocker"),
        ("completed", "wesker closed the task"),
    ]
    out = []
    for index, (kind, text) in enumerate(rows):
        payload = {"kind": kind, "text": text, "task_id": "t_a", "chars": len(text)}
        event = build_event(
            source="kanban", kind="kanban.task.status", ts=float(index + 1),
            profile="wesker" if index >= 2 else "denji-reviewer",
            actor="wesker" if index >= 2 else "denji-reviewer",
            subject=kind, payload=payload, store="main", table="tasks", pk=f"t_a-{index}",
        )
        out.append(seal(event, payload))
    return out


class _InterpretingWriter:
    """Facts on the result panels, narration with stakes everywhere else."""

    name = "interpreting"
    CAPTION = "Everything rode on one stubborn reviewer."

    def write(self, panels):
        out = {}
        for panel in panels:
            first = str(panel.get("evidence", "")).split("\n")[0][:70]
            caption = first if panel["role"] in {"win", "climax"} else self.CAPTION
            out[panel["role"]] = {"caption": caption, "lines": []}
        return out


def _plan(layer: str):
    events = _events()
    beats = beats_from_events(events)
    llm = CachedLLM(_Judge(True), _NullCache(), stage="t")
    return plan_episode(
        build_arc(beats), beats, build_canon(events, beats),
        writer=_InterpretingWriter(),
        grounder=ClaimGate(llm, allow=("Sahil", "Denji-reviewer", "Wesker")),
        evidence={event.id: str(event.payload.get("text", "")) for event in events},
        actors_by_event={event.id: str(event.actor).capitalize() for event in events},
        cast_map={"denji-reviewer": "Denji-reviewer", "wesker": "Wesker", "default": "Kensei"},
        caption_layer=layer,
    )


def test_the_planner_keeps_an_interpretive_caption_on_the_story_layer():
    captions = [panel.caption for panel in _plan("story").panels]
    assert _InterpretingWriter.CAPTION in captions


def test_the_planner_default_is_unchanged_and_drops_that_caption():
    ir = _plan("caption")
    assert _InterpretingWriter.CAPTION not in [panel.caption for panel in ir.panels]
    assert any("term overlap" in reason for reason in ir.grounding["reasons"])


def test_the_planner_still_grounds_the_result_on_the_story_layer():
    ir = _plan("story")
    results = [panel.caption for panel in ir.panels if panel.role in {"win", "climax"} and panel.caption]
    assert results, "the result must still be stated"
    assert all("denji-reviewer blocked" in caption or "wesker" in caption for caption in results)


# --------------------------------------------------------------------------- #
# the switch
# --------------------------------------------------------------------------- #


def test_strict_captions_is_a_plan_flag_and_off_by_default():
    from adapters.hermes.pipeline import PipelineConfig
    from adapters.hermes.reel_cli import register_cli

    assert PipelineConfig(data_dir=".").strict_captions is False
    parser = argparse.ArgumentParser()
    register_cli(parser)
    assert parser.parse_args(["plan", "--strict-captions"]).strict_captions is True
    assert parser.parse_args(["plan"]).strict_captions is False
