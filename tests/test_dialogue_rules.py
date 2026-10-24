"""R3-F5: silence beats filler, no reaction repeats, thread cast may speak."""

from __future__ import annotations

from canon.arcs import build_arcs
from canon.beats import beats_from_events
from canon.brief import build_brief
from canon.canon import build_canon
from canon.caption import compose_caption
from canon.facts import build_facts, facts_text
from conftest import FactCaptionWriter, StubWriter
from canon.episode import TemplateDialogueWriter, plan_episode, validate_ir
from canon.events import KIND_TASK_CREATED, KIND_TASK_STATUS, build_event
from canon.gate import seal
from canon.threads import build_threads


def make_events():
    created = build_event(
        source="kanban", kind=KIND_TASK_CREATED, ts=1.0, profile="kensei", actor="kensei",
        subject="t1", payload={"task_id": "t1", "title": "Build the SQLite read-only adapter"},
        store="main", table="tasks", pk="t1-c",
    )
    rows = [seal(created, created.payload)]
    for index, (actor, kind_field, text) in enumerate(
        (
            ("wesker", "blocked", "the lockfile drifted on the adapter build"),
            ("octacon", "blocked", "the fixture was stale again in the snapshot test"),
            ("quan", "blocked", "the runner timed out while copying the database"),
            ("wesker", "completed", "wesker completed the adapter and the snapshot path"),
        ),
        start=2,
    ):
        row = build_event(
            source="kanban", kind=KIND_TASK_STATUS, ts=float(index), profile=actor,
            actor=actor, subject="t1",
            payload={"task_id": "t1", "kind": kind_field, "text": text},
            store="main", table="task_events", pk=f"t1-{index}",
        )
        rows.append(seal(row, row.payload))
    return rows


def plan(writer=None):
    events = make_events()
    threads = build_threads(events)
    beats = beats_from_events(events)
    arcs = build_arcs(threads, beats, events_by_id={event.id: event for event in events})
    arc = arcs[0]
    evidence = {event.id: str(event.payload.get("text", "")) for event in events}
    brief = build_brief(threads[0].key, "task", events)
    canon = build_canon(events, beats)
    cast_map = {"wesker": "Wesker", "octacon": "Octacon", "quan": "Quan", "kensei": "Kensei"}
    facts = build_facts(brief, {event.id: event for event in events}, display=cast_map, hero="Sahil")
    ir = plan_episode(
        arc, beats, canon,
        writer=writer or FactCaptionWriter(),
        evidence=evidence, brief=brief, cast_map=cast_map,
        structured_captions={event.id: compose_caption(event) for event in events},
        thread_evidence="\n".join(evidence.values()),
        facts=facts,
        facts_evidence=facts_text(facts),
    )
    return ir


def test_no_filler_word_is_ever_used():
    ir = plan()
    texts = [line.text for panel in ir.panels for line in panel.lines]
    assert "Okay." not in texts
    assert "Right." not in texts


def test_no_reaction_repeats_within_an_episode():
    ir = plan()
    texts = [line.text.lower() for panel in ir.panels for line in panel.lines]
    assert len(texts) == len(set(texts))


def test_a_panel_with_no_text_is_dropped():
    """Silence beats filler: a writer may return nothing for a panel."""

    class Quiet:
        name = "quiet"

        def write(self, panels):
            out = {}
            for index, panel in enumerate(panels):
                caption = "" if index else ""
                if panel["role"] in {"climax", "win"}:
                    caption = str(panel.get("fact_sentence") or "")  # the outcome
                out[panel["role"]] = {
                    "caption": caption,
                    "lines": [["Wesker", "That's the one."]] if index == 0 else [],
                }
            return out

    ir = plan(Quiet())
    silent = [panel for panel in ir.panels if not panel.lines]
    assert silent, "a panel with nothing true to say may stay silent"
    assert all(panel.caption for panel in silent), "a silent panel still carries its caption"
    # silence itself is not a problem: the panel is carried by its caption
    known = {
        event_id
        for panel in ir.panels
        for line in panel.lines
        for event_id in line.source_event_ids
    }
    problems = validate_ir(ir, known_event_ids=known)
    assert not any("no lines" in problem for problem in problems)


def test_thread_cast_members_from_the_evidence_may_speak():
    """A writer that does speak may only use the thread's cast (R5-F1: no fallback)."""

    class Talker:
        name = "talker"

        def write(self, panels):
            return {
                panel["role"]: {
                    "caption": str(panel.get("fact_sentence") or "")
                    if panel["role"] in {"climax", "win"}
                    else "",
                    "lines": [["Quan", "The fixture was stale again."]],
                }
                for panel in panels
            }

    ir = plan(Talker())
    speakers = {line.speaker for panel in ir.panels for line in panel.lines}
    assert speakers, "at least one thread cast member should speak"
    assert speakers <= {"Sahil", "Wesker", "Octacon", "Quan", "Kensei"}


def test_an_outsider_never_speaks():
    class Outsider:
        name = "outsider"

        def write(self, panels):
            return {
                panel["role"]: {
                    "caption": "",
                    "lines": [["Priya", "I deleted seven files from the adapter build"]],
                }
                for panel in panels
            }

    ir = plan(Outsider())
    assert all(line.speaker != "Priya" for panel in ir.panels for line in panel.lines)


def test_the_template_writer_goes_silent_once_its_reactions_run_out():
    writer = TemplateDialogueWriter(("Wesker",))
    panels = [{"role": f"p{index}", "actors": ["Wesker"], "structured_caption": "", "summary": ""} for index in range(14)]
    out = writer.write(panels)
    texts = [row["lines"][0][1] for row in out.values() if row["lines"]]
    assert len(texts) == len(set(texts)), "no repeat"
    assert len(texts) <= len(TemplateDialogueWriter.REACTIONS)
