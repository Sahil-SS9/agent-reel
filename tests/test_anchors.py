"""R3-F3: no panel without gated text in the brief."""

from __future__ import annotations

from canon.arcs import build_arcs
from canon.beats import beats_from_events
from canon.brief import build_brief
from canon.canon import build_canon
from canon.episode import plan_episode, usable_anchor_count
from canon.events import KIND_TASK_CREATED, KIND_TASK_STATUS, build_event
from canon.gate import seal
from canon.threads import build_threads


def task_events(texts):
    """rows: (kind_field, text or '')"""
    created = build_event(
        source="kanban", kind=KIND_TASK_CREATED, ts=1.0, profile="kensei", actor="kensei",
        subject="t1", payload={"task_id": "t1", "title": "Build the SQLite read-only adapter"},
        store="main", table="tasks", pk="t1-c",
    )
    rows = [seal(created, created.payload)]
    for index, (kind_field, text) in enumerate(texts, start=2):
        payload = {"task_id": "t1", "kind": kind_field}
        if text:
            payload["text"] = text
        event = build_event(
            source="kanban", kind=KIND_TASK_STATUS, ts=float(index), profile="octacon",
            actor="octacon", subject="t1", payload=payload,
            store="main", table="task_events", pk=f"t1-{index}",
        )
        rows.append(seal(event, payload))
    return rows


def evidence_of(events):
    return {event.id: str(event.payload.get("text", "")) for event in events}


def plan(events, *, with_brief=True):
    threads = build_threads(events)
    beats = beats_from_events(events)
    arcs = build_arcs(threads, beats, events_by_id={event.id: event for event in events})
    assert arcs
    arc = arcs[0]
    evidence = evidence_of(events)
    brief = build_brief(threads[0].key, "task", events) if with_brief else None
    canon = build_canon(events, beats)
    ir = plan_episode(arc, beats, canon, evidence=evidence, brief=brief)
    return ir, beats, brief, evidence


def test_a_status_only_beat_cannot_anchor_a_panel():
    events = task_events([("blocked", ""), ("blocked", ""), ("blocked", ""), ("completed", "")])
    ir, beats, brief, evidence = plan(events)
    assert len(ir.panels) == 0, "beats with no gated text must not become panels"
    assert usable_anchor_count(beats, brief=brief, evidence=evidence) == 0


def test_beats_with_text_do_anchor_panels():
    events = task_events(
        [
            ("blocked", "the lockfile drifted on the adapter"),
            ("blocked", "the fixture was stale again in the snapshot test"),
            ("blocked", "the runner timed out while copying the database"),
            ("completed", "octacon completed the adapter and the snapshot path"),
        ]
    )
    ir, _beats, _brief, _evidence = plan(events)
    assert 3 <= len(ir.panels) <= 4
    assert all(panel.caption or panel.lines for panel in ir.panels)


def test_a_mixed_beat_set_keeps_only_the_text_bearing_panels():
    events = task_events(
        [
            ("blocked", ""),
            ("blocked", "the fixture was stale again in the snapshot test"),
            ("blocked", ""),
            ("completed", "octacon completed the adapter and the snapshot path"),
        ]
    )
    ir, beats, brief, evidence = plan(events)
    assert usable_anchor_count(beats, brief=brief, evidence=evidence) < len(beats)
    assert len(ir.panels) < 4
