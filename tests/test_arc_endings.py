"""Round 3 item 4: an arc ends properly - prefer a finished thread, else a cliffhanger."""

from __future__ import annotations

from canon.arcs import build_arc, build_arcs
from canon.beats import beats_from_events
from canon.canon import build_canon
from canon.episode import plan_episode
from canon.events import build_event
from canon.gate import seal
from canon.threads import build_threads


def gated(kind, ts, *, task_id, kind_field, profile="wesker", text=""):
    payload = {"kind": kind_field, "task_id": task_id, "chars": len(text)}
    if text:
        payload["text"] = text
    event = build_event(
        source="kanban",
        kind=kind,
        ts=float(ts),
        profile=profile,
        subject=kind_field,
        payload=payload,
        store="main",
        table="tasks",
        pk=f"{task_id}-{ts}",
    )
    return seal(event, payload)


def _thread(task_id, statuses, base=0.0, profile="wesker"):
    return [
        gated("kanban.task.status", base + index, task_id=task_id, kind_field=status, profile=profile,
              text=f"{status} on the run")
        for index, status in enumerate(statuses)
    ]


def test_threads_that_finished_are_preferred():
    finished = _thread("t_done", ["created", "blocked", "blocked", "blocked", "completed"], base=0.0)
    unfinished = _thread("t_open", ["created", "blocked", "blocked", "blocked", "blocked"], base=100.0)
    threads = build_threads(finished + unfinished)
    assert threads[0].key == "t_done"
    assert threads[0].completed is True
    assert threads[1].completed is False


def test_a_finished_thread_produces_a_resolved_arc_with_no_cliffhanger():
    events = _thread("t_done", ["created", "blocked", "blocked", "blocked", "completed"])
    threads = build_threads(events)
    beats = beats_from_events(events)
    arcs = build_arcs(threads, beats)
    assert arcs
    arc = arcs[0]
    assert arc.status == "resolved"
    canon = build_canon(events, beats)
    ir = plan_episode(arc, beats, canon)
    assert ir.cliffhanger is False
    assert all("to be continued" not in panel.caption.lower() for panel in ir.panels)


def test_an_unfinished_thread_ends_with_a_labelled_cliffhanger():
    events = _thread("t_open", ["created", "blocked", "blocked", "blocked", "blocked"])
    threads = build_threads(events)
    beats = beats_from_events(events)
    arc = build_arc(beats, thread=threads[0])
    assert arc is not None and arc.status == "open"
    canon = build_canon(events, beats)
    ir = plan_episode(arc, beats, canon)
    assert ir.cliffhanger is True
    assert "to be continued" in ir.panels[-1].caption.lower()
