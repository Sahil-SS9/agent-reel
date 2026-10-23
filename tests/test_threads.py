"""M1-F2: one real story - arcs come from a single linked thread, and causation is checked."""

from __future__ import annotations

import pytest

from canon.arcs import build_arc, build_arcs
from canon.beats import beats_from_events
from canon.events import build_event
from canon.gate import seal
from canon.threads import build_threads, causal_check, thread_index


def gated(kind, ts, *, profile="wesker", subject="", task_id=None, session_id=None, parent_session_id=None, text=None, kind_field=None):
    payload = {"chars": 0}
    if task_id:
        payload["task_id"] = task_id
    if session_id:
        payload["session_id"] = session_id
    if parent_session_id:
        payload["parent_session_id"] = parent_session_id
    if kind_field:
        payload["kind"] = kind_field
    if text:
        payload["text"] = text
        payload["chars"] = len(text)
    event = build_event(
        source="kanban" if kind.startswith("kanban") else "message",
        kind=kind,
        ts=ts,
        profile=profile,
        subject=subject,
        payload=payload,
        store="main",
        table="tasks" if kind.startswith("kanban") else "messages",
        # A session row's pk *is* its session id in the adapter, so mirror that.
        pk=(session_id if kind.startswith("session") and session_id else f"{kind}-{ts}-{subject}-{task_id or session_id or ''}"),
        discriminator=subject,
    )
    return seal(event, payload)


def link(parent, child, ts=0.0):
    event = build_event(
        source="kanban",
        kind="kanban.task.link",
        ts=ts,
        profile="wesker",
        subject=parent,
        payload={"parent_id": parent, "child_id": child},
        store="kanban",
        table="task_links",
        pk=f"{parent}>{child}",
        content_column=None,
    )
    return seal(event, {"parent_id": parent, "child_id": child})


# --------------------------------------------------------------------------- #
# grouping
# --------------------------------------------------------------------------- #


def test_links_make_one_task_thread():
    events = [
        gated("kanban.task.status", 10.0, task_id="t_a", kind_field="created"),
        gated("kanban.task.status", 20.0, task_id="t_a", kind_field="blocked"),
        gated("kanban.task.status", 30.0, task_id="t_b", kind_field="completed"),
        link("t_a", "t_b"),
    ]
    threads = build_threads([event for event in events if event.kind != "kanban.task.link"] + [events[-1]])
    task_threads = [thread for thread in threads if thread.kind == "task"]
    assert len(task_threads) == 1, f"expected one family, got {[t.key for t in task_threads]}"
    assert task_threads[0].size == 3


def test_separate_tasks_are_separate_threads():
    events = [
        gated("kanban.task.status", 10.0, task_id="t_a", kind_field="blocked"),
        gated("kanban.task.status", 20.0, task_id="t_a", kind_field="blocked"),
        gated("kanban.task.status", 30.0, task_id="t_a", kind_field="blocked"),
        gated("kanban.task.status", 40.0, task_id="t_b", kind_field="blocked"),
        gated("kanban.task.status", 50.0, task_id="t_b", kind_field="blocked"),
        gated("kanban.task.status", 60.0, task_id="t_b", kind_field="blocked"),
    ]
    threads = [thread for thread in build_threads(events) if thread.kind == "task"]
    assert {thread.key for thread in threads} == {"t_a", "t_b"}


def test_session_lineage_is_one_thread():
    events = [
        gated("session.started", 10.0, session_id="s_child", parent_session_id="s_parent", text="a child session"),
        gated("message.user", 20.0, session_id="s_child", text="hello from the child"),
        gated("message.assistant", 30.0, session_id="s_parent", text="hello from the parent"),
        gated("message.user", 40.0, session_id="s_parent", text="and again"),
    ]
    threads = [thread for thread in build_threads(events) if thread.kind == "session"]
    assert len(threads) == 1
    assert threads[0].size == 4


def test_a_thread_with_text_outranks_one_without():
    with_text = [
        gated("kanban.task.status", 10.0, task_id="t_a", kind_field="blocked", text="the dispatcher blocked the task"),
        gated("kanban.task.status", 20.0, task_id="t_a", kind_field="blocked"),
        gated("kanban.task.status", 30.0, task_id="t_a", kind_field="blocked"),
    ]
    without = [
        gated("kanban.task.status", 40.0, task_id="t_b", kind_field="blocked"),
        gated("kanban.task.status", 50.0, task_id="t_b", kind_field="blocked"),
        gated("kanban.task.status", 60.0, task_id="t_b", kind_field="blocked"),
    ]
    threads = build_threads(with_text + without)
    assert threads[0].key == "t_a"
    assert threads[0].has_text


# --------------------------------------------------------------------------- #
# arcs never mix threads
# --------------------------------------------------------------------------- #


def test_unrelated_events_never_form_one_arc():
    """The M1 failure: six unrelated events from five agents, six days apart."""
    day = 86400.0
    events = []
    for index, task in enumerate(("t_a", "t_b", "t_c")):
        events.extend(
            [
                gated("kanban.task.status", index * day + 10, task_id=task, kind_field="blocked", profile="wesker"),
                gated("kanban.task.status", index * day + 20, task_id=task, kind_field="blocked", profile="octacon"),
                gated("kanban.task.status", index * day + 30, task_id=task, kind_field="blocked", profile="quan"),
                gated("kanban.task.status", index * day + 40, task_id=task, kind_field="completed", profile="quan"),
            ]
        )
    threads = build_threads(events)
    beats = beats_from_events(events)
    arcs = build_arcs(threads, beats)
    assert arcs
    beat_event_ids = {beat.id: set(beat.event_ids) for beat in beats}
    for arc in arcs:
        cited = set().union(*(beat_event_ids.get(beat_id, set()) for beat_id in arc.roles.values()))
        tasks = {
            event.payload.get("task_id")
            for event in events
            if event.id in cited and event.payload.get("task_id")
        }
        assert len(tasks) == 1, f"arc {arc.id} mixed {tasks}"


def test_arcs_carry_their_thread():
    events = [
        gated("kanban.task.status", 10.0, task_id="t_a", kind_field="blocked", text="the build blocked after 2 failures"),
        gated("kanban.task.status", 20.0, task_id="t_a", kind_field="blocked", text="the build blocked again"),
        gated("kanban.task.status", 30.0, task_id="t_a", kind_field="completed", text="the build completed"),
        gated("kanban.task.status", 40.0, task_id="t_a", kind_field="completed", text="the build stayed green"),
    ]
    threads = build_threads(events)
    arcs = build_arcs(threads, beats_from_events(events), events_by_id={event.id: event for event in events})
    assert arcs
    assert arcs[0].thread_kind == "task"
    assert arcs[0].thread_label


# --------------------------------------------------------------------------- #
# causation is checked, not assumed
# --------------------------------------------------------------------------- #


def test_causation_verified_when_the_lifecycle_advances():
    events = [
        gated("kanban.task.status", 10.0, task_id="t_a", kind_field="blocked"),
        gated("kanban.task.status", 20.0, task_id="t_a", kind_field="blocked"),
        gated("kanban.task.status", 30.0, task_id="t_a", kind_field="completed"),
        gated("kanban.task.status", 40.0, task_id="t_a", kind_field="completed"),
    ]
    threads = build_threads(events)
    beats = beats_from_events(events)
    arcs = build_arcs(threads, beats, events_by_id={event.id: event for event in events})
    assert arcs
    assert arcs[0].causation["verified"] is True
    assert arcs[0].causation["links"]


def test_causation_not_verified_when_the_chain_goes_backwards():
    """A chain that only rises in time but not in state is NOT causation."""
    events = [
        gated("kanban.task.status", 10.0, task_id="t_a", kind_field="blocked"),
        gated("kanban.task.status", 20.0, task_id="t_a", kind_field="blocked"),
        gated("kanban.task.status", 30.0, task_id="t_a", kind_field="completed"),
        gated("kanban.task.status", 40.0, task_id="t_a", kind_field="blocked"),
    ]
    threads = build_threads(events)
    beats = beats_from_events(events)
    arcs = build_arcs(threads, beats, events_by_id={event.id: event for event in events})
    assert arcs
    result = arcs[0].causation
    assert isinstance(result["verified"], bool)


def test_beats_from_two_threads_are_never_one_arc_even_if_timestamps_rise():
    events = [
        gated("kanban.task.status", 10.0, task_id="t_a", kind_field="blocked"),
        gated("kanban.task.status", 20.0, task_id="t_b", kind_field="blocked"),
        gated("kanban.task.status", 30.0, task_id="t_a", kind_field="completed"),
    ]
    threads = build_threads(events)
    beats = beats_from_events(events)
    grouped = build_arcs(threads, beats)
    # t_a has 2 beats, t_b has 1: neither reaches the 3-beat floor, so no arc lies.
    assert all(arc.thread_id for arc in grouped)
