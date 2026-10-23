"""Round 6 / R5-F3: panels state their own facts, and the result reaches the climax."""

from __future__ import annotations

from canon.arcs import build_brief_arc
from canon.beats import beats_from_events
from canon.brief import build_brief
from canon.canon import build_canon
from canon.caption import compose_caption
from canon.episode import plan_episode
from canon.events import KIND_MESSAGE_ASSISTANT, KIND_MESSAGE_USER, build_event
from canon.facts import build_facts, facts_text
from canon.gate import seal


def msg(kind, text, ts, role):
    event = build_event(
        source="session", kind=kind, ts=ts, profile="default",
        actor="owner" if role == "user" else "denji", subject="s1",
        payload={"text": text, "role": role, "session_id": "s1"},
        store="main", table="messages", pk=f"s1-{ts}",
    )
    return seal(event, event.payload)


def episode():
    rows = [
        msg(KIND_MESSAGE_USER, "Please benchmark our memory system against LCM-X properly", 1.0, "user"),
        msg(KIND_MESSAGE_ASSISTANT, "Started the benchmark harness and the scoring path", 2.0, "assistant"),
        msg(KIND_MESSAGE_USER, "The numbers must be comparable and honest", 3.0, "user"),
        msg(KIND_MESSAGE_ASSISTANT, "Scored the long-context set and wrote the results table", 4.0, "assistant"),
        msg(
            KIND_MESSAGE_ASSISTANT,
            "Severian 87.3 vs LCM-X 79.5 on LoCoMo; a tie on BEAM; LongMemEval still running",
            5.0,
            "assistant",
        ),
    ]
    by_id = {row.id: row for row in rows}
    brief = build_brief("s1", "session", rows)
    facts = build_facts(brief, by_id, display={"owner": "Sahil", "denji": "Kensei"}, hero="Sahil")
    arc, beats = build_brief_arc(brief, by_id)
    ir = plan_episode(
        arc, list(beats), build_canon(rows, beats_from_events(rows)),
        evidence={row.id: str(row.payload.get("text", "")) for row in rows},
        brief=brief, facts=facts, facts_evidence=facts_text(facts),
        structured_captions={row.id: compose_caption(row) for row in rows},
        cast_map={"owner": "Sahil", "denji": "Kensei"},
    )
    return ir


def test_the_setup_panel_states_the_goal_in_the_owners_voice():
    ir = episode()
    setup = next(panel for panel in ir.panels if panel.role == "setup")
    assert setup.caption
    assert "Sahil" in setup.caption
    assert "asked for" not in setup.caption.lower()


def test_the_climax_states_the_numbers():
    ir = episode()
    climax = next(panel for panel in ir.panels if panel.role in {"climax", "win"})
    assert "87.3" in climax.caption and "79.5" in climax.caption


def test_no_caption_uses_a_template_opening():
    ir = episode()
    for panel in ir.panels:
        assert not panel.caption.startswith(("Worked on", "Reported"))
        assert "asked for" not in panel.caption.lower()


def test_every_panel_has_a_caption_or_a_line():
    ir = episode()
    for panel in ir.panels:
        assert panel.caption or panel.lines
