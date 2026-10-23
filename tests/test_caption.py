"""R3-F4: captions compose from structured facts and never print provenance."""

from __future__ import annotations

from canon.caption import compose_caption, compose_from_parts, looks_like_provenance
from canon.events import (
    KIND_MESSAGE_ASSISTANT,
    KIND_MESSAGE_USER,
    KIND_TASK_CREATED,
    KIND_TASK_STATUS,
    build_event,
)
from canon.gate import seal


def event(kind, *, actor="octacon", payload=None, ts=1.0, subject="t1"):
    built = build_event(
        source="kanban" if kind.startswith("kanban") else "session",
        kind=kind, ts=ts, profile=actor, actor=actor, subject=subject,
        payload=payload or {}, store="main", table="rows", pk=f"{subject}-{ts}",
    )
    return seal(built, built.payload)


def test_a_status_event_becomes_a_plain_sentence():
    row = event(
        KIND_TASK_STATUS,
        payload={"task_id": "t1", "kind": "blocked", "text": "the lockfile drifted on the adapter"},
    )
    caption = compose_caption(row)
    assert caption == "Octacon was blocked on the lockfile drifted on the adapter."


def test_a_completion_reads_like_a_sentence():
    row = event(
        KIND_TASK_STATUS,
        payload={"task_id": "t1", "kind": "completed", "text": "the adapter and the snapshot path"},
    )
    assert compose_caption(row) == "Octacon completed the adapter and the snapshot path."


def test_provenance_is_never_emitted():
    row = event(
        KIND_TASK_STATUS,
        payload={
            "task_id": "t1",
            "kind": "gave_up",
            "text": 'event: kanban.task.status gave_up {"failures": 2}',
        },
    )
    assert compose_caption(row) == ""


def test_a_bare_id_is_not_a_caption():
    row = event(KIND_TASK_STATUS, payload={"task_id": "t_deadbeef", "kind": "blocked", "text": "t_deadbeef"})
    caption = compose_caption(row)
    assert caption == "" or "t_deadbeef" not in caption


def test_a_message_becomes_asked_for():
    row = event(
        KIND_MESSAGE_USER,
        actor="Sahil",
        payload={"text": "the weekly comic renderer and three episodes", "session_id": "s1"},
        subject="s1",
    )
    assert compose_caption(row) == "Sahil asked for the weekly comic renderer and three episodes."


def test_an_assistant_message_reports():
    row = event(
        KIND_MESSAGE_ASSISTANT,
        actor="default",
        payload={"text": "the adapter is built and 42 tests pass", "session_id": "s1"},
        subject="s1",
    )
    caption = compose_caption(row)
    assert caption.startswith("The fleet reported")


def test_no_text_means_a_short_but_valid_sentence_or_nothing():
    row = event(KIND_TASK_STATUS, payload={"task_id": "t1", "kind": "blocked"})
    caption = compose_caption(row)
    assert caption == "" or len(caption.split()) >= 3


def test_from_parts_composes_and_refuses_dumps():
    assert compose_from_parts(actor="wesker", action="blocked", obj="the release gate") == (
        "Wesker blocked the release gate."
    )
    assert compose_from_parts(actor="wesker", action="blocked", obj='{"failures": 2}') == ""


def test_the_provenance_detector_sees_the_round_three_dumps():
    for dump in (
        "event: kanban.task.status gave_up octacon octacon {\"failures\": 2}",
        "task_id=t_abc123 kind=blocked",
        "ev_2452ddd1d160508f8f2bc1e3",
    ):
        assert looks_like_provenance(dump), dump
