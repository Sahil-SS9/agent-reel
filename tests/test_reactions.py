"""R4-F3: a line reacts to its panel's fact; at most one generic interjection."""

from __future__ import annotations

from canon.arcs import build_brief_arc
from canon.beats import beats_from_events
from canon.brief import build_brief
from canon.canon import build_canon
from canon.caption import compose_caption
from canon.episode import TemplateDialogueWriter, _is_generic, plan_episode
from canon.events import KIND_MESSAGE_ASSISTANT, KIND_MESSAGE_USER, build_event
from canon.gate import seal


def msg(kind, text, ts, actor="owner", role="user"):
    event = build_event(
        source="session", kind=kind, ts=ts, profile="default", actor=actor, subject="s1",
        payload={"text": text, "role": role, "session_id": "s1"},
        store="main", table="messages", pk=f"s1-{ts}",
    )
    return seal(event, event.payload)


def episode():
    rows = [
        msg(KIND_MESSAGE_USER, "Please benchmark our memory system against the competitor", 1.0),
        msg(KIND_MESSAGE_ASSISTANT, "Started the benchmark harness and the scoring path", 2.0, "denji", "assistant"),
        msg(KIND_MESSAGE_USER, "The numbers must be comparable and honest", 3.0),
        msg(KIND_MESSAGE_ASSISTANT, "Scored 87.3 against 79.5 on the long-context set", 4.0, "denji", "assistant"),
        msg(KIND_MESSAGE_ASSISTANT, "Benchmark complete: 87.3 against 79.5, guard held", 5.0, "denji", "assistant"),
    ]
    brief = build_brief("s1", "session", rows)
    arc, beats = build_brief_arc(brief, {row.id: row for row in rows})
    evidence = {row.id: str(row.payload.get("text", "")) for row in rows}
    ir = plan_episode(
        arc, list(beats), build_canon(rows, beats_from_events(rows)),
        evidence=evidence, brief=brief,
        structured_captions={row.id: compose_caption(row, display={"owner": "Sahil"}) for row in rows},
        thread_evidence="\n".join(evidence.values()),
        cast_map={"owner": "Sahil", "denji": "Denji"},
        writer=TemplateDialogueWriter(("Sahil", "Denji")),
    )
    return ir, evidence


def test_no_line_is_a_bare_interjection():
    ir, _evidence = episode()
    lines = [line.text for panel in ir.panels for line in panel.lines]
    for line in lines:
        assert line not in {"Okay.", "Right.", "Ugh.", "Typical.", "Naturally."}


def test_every_line_relates_to_its_panel():
    ir, evidence = episode()
    for panel in ir.panels:
        for line in panel.lines:
            assert not _is_generic(line.text, evidence.get(line.source_event_ids[0], ""), panel.caption)


def test_at_most_one_generic_interjection_survives():
    class Interjector:
        name = "interjector"

        def write(self, panels):
            return {
                panel["role"]: {"caption": "", "lines": [["Sahil", "Ugh."], ["Sahil", "Typical."]]}
                for panel in panels
            }

    rows = [
        msg(KIND_MESSAGE_USER, "Please benchmark our memory system against the competitor", 1.0),
        msg(KIND_MESSAGE_ASSISTANT, "Started the benchmark harness and the scoring path", 2.0, "denji", "assistant"),
        msg(KIND_MESSAGE_USER, "The numbers must be comparable and honest", 3.0),
        msg(KIND_MESSAGE_ASSISTANT, "Benchmark complete: 87.3 against 79.5, guard held", 4.0, "denji", "assistant"),
    ]
    brief = build_brief("s1", "session", rows)
    arc, beats = build_brief_arc(brief, {row.id: row for row in rows})
    evidence = {row.id: str(row.payload.get("text", "")) for row in rows}
    ir = plan_episode(
        arc, list(beats), build_canon(rows, beats_from_events(rows)),
        writer=Interjector(), evidence=evidence, brief=brief,
        structured_captions={row.id: compose_caption(row, display={"owner": "Sahil"}) for row in rows},
        thread_evidence="\n".join(evidence.values()),
        cast_map={"owner": "Sahil", "denji": "Denji"},
    )
    generic = [line.text for panel in ir.panels for line in panel.lines if line.text in {"Ugh.", "Typical."}]
    assert len(generic) <= 1


def test_the_template_reaction_quotes_the_panel_fact():
    writer = TemplateDialogueWriter(("Wesker",))
    out = writer.write([{"role": "setup", "actors": ["Wesker"], "structured_caption": "Wesker completed the adapter and the snapshot path"}])
    line = out["setup"]["lines"][0][1]
    assert "adapter" in line.lower()


def test_no_caption_means_silence_not_filler():
    writer = TemplateDialogueWriter(("Wesker",))
    out = writer.write([{"role": "setup", "actors": ["Wesker"], "structured_caption": ""}])
    assert out["setup"]["lines"] == []
