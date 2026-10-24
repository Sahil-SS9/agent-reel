"""Round 8: captions are written prose, and a finished story must show its outcome.

R7-F1: the planner no longer stitches actor + verb + object from clipped input.
R7-F2: dropping the result panel may not export as a completed story.
"""

from __future__ import annotations

import pytest

from canon.arcs import build_brief_arc
from canon.beats import beats_from_events
from canon.brief import build_brief
from canon.canon import build_canon
from canon.episode import EpisodeRefused, plan_episode
from canon.events import KIND_MESSAGE_ASSISTANT, KIND_MESSAGE_USER, build_event
from canon.facts import build_facts, facts_text
from canon.gate import seal


def msg(kind, text, ts, role="user"):
    event = build_event(
        source="session", kind=kind, ts=ts, profile="default",
        actor="owner" if role == "user" else "denji", subject="s1",
        payload={"text": text, "role": role, "session_id": "s1"},
        store="main", table="messages", pk=f"s1-{ts}",
    )
    return seal(event, event.payload)


def rows():
    return [
        msg(KIND_MESSAGE_USER, "Please benchmark our memory system against LCM-X properly", 1.0),
        msg(KIND_MESSAGE_ASSISTANT, "Started the benchmark harness and the scoring path", 2.0, "assistant"),
        msg(KIND_MESSAGE_ASSISTANT, "Severian 87.3 vs LCM-X 79.5 on LoCoMo", 3.0, "assistant"),
    ]


def context(*, with_facts=True):
    events = rows()
    by_id = {row.id: row for row in events}
    brief = build_brief("s1", "session", events)
    facts = build_facts(brief, by_id, display={"owner": "Sahil", "denji": "Kensei"}, hero="Sahil")
    arc, beats = build_brief_arc(brief, by_id)
    return events, brief, facts, arc, list(beats)


class Talker:
    name = "talker"

    def __init__(self, by_role):
        self.by_role = by_role

    def write(self, panels):
        return {
            panel["role"]: {"caption": self.by_role.get(panel["role"], ""), "lines": []}
            for panel in panels
        }


GOOD = {
    "setup": "Sahil wanted a fair benchmark of both memory systems.",
    "climax": "Severian scored 87.3 against LCM-X on LoCoMo.",
    "win": "Severian scored 87.3 against LCM-X on LoCoMo.",
}


def plan(writer, *, facts=None, brief=None, arc=None, beats=None):
    events, brief_, facts_, arc_, beats_ = context()
    return plan_episode(
        arc or arc_, beats or beats_, build_canon(events, beats_from_events(events)),
        evidence={row.id: str(row.payload.get("text", "")) for row in events},
        brief=brief or brief_,
        facts=facts if facts is not None else facts_,
        facts_evidence=facts_text(facts_ if facts is None else facts),
        writer=writer,
        cast_map={"owner": "Sahil", "denji": "Kensei"},
    )


def test_a_written_sentence_is_used_verbatim():
    ir = plan(Talker(GOOD))
    captions = [panel.caption for panel in ir.panels if panel.caption]
    assert "Sahil wanted a fair benchmark of both memory systems." in captions


def test_the_planner_never_stitches_a_caption_itself():
    """No writer, no caption: the old code filled the page with actor + verb + object."""
    class Silent:
        name = "silent"

        def write(self, panels):
            return {panel["role"]: {"caption": "", "lines": []} for panel in panels}

    ir = plan(Silent())
    assert ir.panels == ()
    assert all("dropped" in reason for reason in ir.grounding["reasons"])


def test_a_caption_that_invents_a_number_is_dropped_not_replaced():
    class Invent(Talker):
        name = "invent"

    ir = plan(Invent({"setup": "Sahil asked for a benchmark that scored 99.9 on BEAM."}))
    captions = [panel.caption for panel in ir.panels if panel.caption]
    assert all("99.9" not in caption for caption in captions)


def test_a_finished_story_without_a_visible_outcome_is_refused():
    class NoOutcome(Talker):
        name = "no-outcome"

    writer = NoOutcome({"setup": "Sahil wanted a fair benchmark of both memory systems."})
    with pytest.raises(EpisodeRefused) as refused:
        plan(writer)
    assert "outcome" in str(refused.value)


def test_a_finished_story_with_a_visible_outcome_exports():
    ir = plan(Talker(GOOD))
    assert ir.cliffhanger is False
    assert any("87.3" in panel.caption for panel in ir.panels if panel.caption)


def plan_with(writer, *, caption_by_role=None):
    """Plan the fixture with the given writer (no grounder), for reuse by other tests."""
    return plan(writer)
