"""R3-F2: a thread brief built from gated text, entailment-checked."""

from __future__ import annotations

from canon.brief import MAX_TURNS, MIN_TURNS, build_brief, event_text
from canon.events import (
    KIND_MESSAGE_ASSISTANT,
    KIND_MESSAGE_USER,
    KIND_TASK_CREATED,
    KIND_TASK_STATUS,
    build_event,
)
from canon.gate import seal
from canon.grounding import ClaimGate


def message(session, kind, text, ts, actor="Sahil"):
    event = build_event(
        source="session", kind=kind, ts=ts, profile=actor, actor=actor, subject=session,
        payload={"text": text, "session_id": session},
        store="main", table="messages", pk=f"{session}-{ts}",
    )
    return seal(event, event.payload)


def session_events():
    return [
        message("s1", KIND_MESSAGE_USER, "Please build the read-only SQLite adapter for the reel", 1.0),
        message("s1", KIND_MESSAGE_ASSISTANT, "Starting on the adapter and the snapshot path.", 2.0, "default"),
        message("s1", KIND_MESSAGE_USER, "The sidecar files must not be created", 3.0),
        message("s1", KIND_MESSAGE_ASSISTANT, "Added the header check so WAL databases are copied first.", 4.0, "default"),
        message("s1", KIND_MESSAGE_USER, "Good, now prove it with strace", 5.0),
        message("s1", KIND_MESSAGE_ASSISTANT, "Built and tested the adapter; 42 tests pass and no sidecars appear.", 6.0, "default"),
    ]


def test_the_goal_is_the_first_thing_the_user_asked_for():
    brief = build_brief("s1", "session", session_events())
    assert brief.goal.startswith("Please build the read-only SQLite adapter")


def test_the_outcome_is_the_final_assistant_message():
    brief = build_brief("s1", "session", session_events())
    assert "42 tests pass" in brief.outcome


def test_the_brief_has_between_three_and_six_turns():
    brief = build_brief("s1", "session", session_events())
    assert MIN_TURNS <= len(brief.turns) <= MAX_TURNS


def test_turns_are_ordered_and_carry_an_actor():
    brief = build_brief("s1", "session", session_events())
    assert [turn.text for turn in brief.turns]
    assert all(turn.actor for turn in brief.turns)


def test_a_task_family_brief_uses_the_created_title_and_the_completion():
    created = build_event(
        source="kanban", kind=KIND_TASK_CREATED, ts=1.0, profile="kensei", actor="kensei",
        subject="t1", payload={"task_id": "t1", "title": "Build the SQLite read-only adapter"},
        store="main", table="tasks", pk="t1-c",
    )
    rows = [seal(created, created.payload)]
    for index, (kind_field, text) in enumerate(
        (("blocked", "the lockfile drifted on the adapter"), ("blocked", "the fixture was stale again"),
         ("completed", "octacon completed the adapter and the snapshot path")),
        start=2,
    ):
        row = build_event(
            source="kanban", kind=KIND_TASK_STATUS, ts=float(index), profile="octacon",
            actor="octacon", subject="t1", payload={"task_id": "t1", "kind": kind_field, "text": text},
            store="main", table="task_events", pk=f"t1-{kind_field}{index}",
        )
        rows.append(seal(row, row.payload))
    brief = build_brief("t1", "task", rows)
    assert brief.goal.startswith("Build the SQLite")
    assert "completed the adapter" in brief.outcome


def test_an_unsupported_brief_line_is_dropped():
    class Liar:
        name = "liar"

        def complete_json(self, payload, **_kwargs):
            return {"supported": "timeout key" not in payload["line"].lower()}

    from canon.cache import ModelCache
    from canon.llm import CachedLLM

    gate = ClaimGate(CachedLLM(Liar(), ModelCache.__new__(ModelCache), stage="t"))
    gate.llm.cache = _NullCache()
    rows = session_events() + [
        message("s1", KIND_MESSAGE_ASSISTANT, "the config was missing the timeout key", 3.5, "default")
    ]
    brief = build_brief("s1", "session", rows, gate=gate)
    assert "timeout key" not in brief.text().lower()
    assert brief.dropped


class _NullCache:
    def get(self, _key):
        return None

    def set(self, _key, _value):
        return None


def test_event_text_prefers_the_text_field():
    rows = session_events()
    assert event_text(rows[0]).startswith("Please build")


def test_brief_is_not_ok_without_a_goal():
    rows = [message("s2", KIND_MESSAGE_ASSISTANT, "An answer with no question behind it.", 1.0, "default")]
    brief = build_brief("s2", "session", rows)
    assert not brief.ok
