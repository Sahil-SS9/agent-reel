"""R3-F1: select stories by meaning, not by lifecycle noise."""

from __future__ import annotations

from canon.events import (
    KIND_MESSAGE_ASSISTANT,
    KIND_MESSAGE_USER,
    KIND_TASK_COMMENT,
    KIND_TASK_CREATED,
    KIND_TASK_STATUS,
    build_event,
)
from canon.gate import seal
from canon.selection import (
    build_candidates,
    describes_real_work,
    is_plumbing,
    select_stories,
)


def user(session, text, ts=1.0):
    event = build_event(
        source="session", kind=KIND_MESSAGE_USER, ts=ts, profile="Sahil",
        actor="Sahil", subject=session, payload={"text": text, "session_id": session},
        store="main", table="messages", pk=f"{session}-u{ts}",
    )
    return seal(event, event.payload)


def assistant(session, text, ts=2.0):
    event = build_event(
        source="session", kind=KIND_MESSAGE_ASSISTANT, ts=ts, profile="default",
        actor="default", subject=session, payload={"text": text, "session_id": session},
        store="main", table="messages", pk=f"{session}-a{ts}",
    )
    return seal(event, event.payload)


def task(task_id, title, statuses=("created", "blocked", "completed"), ts=10.0):
    events = []
    created = build_event(
        source="kanban", kind=KIND_TASK_CREATED, ts=ts, profile="kensei", actor="kensei",
        subject=task_id, payload={"task_id": task_id, "title": title},
        store="main", table="tasks", pk=f"{task_id}-c",
    )
    events.append(seal(created, created.payload))
    for index, status in enumerate(statuses, start=1):
        row = build_event(
            source="kanban", kind=KIND_TASK_STATUS, ts=ts + index, profile="octacon",
            actor="octacon", subject=task_id,
            payload={"task_id": task_id, "kind": status, "text": f"{status} on {title}"},
            store="main", table="task_events", pk=f"{task_id}-{status}",
        )
        events.append(seal(row, row.payload))
    return events


# --------------------------------------------------------------------------- #
# plumbing vs work
# --------------------------------------------------------------------------- #


def test_governance_cards_are_plumbing():
    for title in (
        "Needs Sahil's decision: Investigate the FEB-30 gate",
        "Triage the blocked card",
        "Review gate failed on the release",
        "dispatcher gave_up after 2 retries",
        "t_ec1754fc",
        "blocked",
    ):
        assert is_plumbing(title), title


def test_real_work_titles_are_not_plumbing():
    for title in (
        "Build the SQLite read-only adapter",
        "Add voice intake handoff to Misa-Misa",
        "Write the weekly comic renderer",
    ):
        assert not is_plumbing(title), title
        assert describes_real_work(title), title


def test_a_title_of_ids_only_is_not_real_work():
    assert not describes_real_work("t_abc123")


# --------------------------------------------------------------------------- #
# candidates
# --------------------------------------------------------------------------- #


def test_a_session_with_a_goal_and_an_outcome_is_a_candidate():
    events = [
        user("s1", "Please build the read-only SQLite adapter for the reel"),
        assistant("s1", "Built and tested the adapter; all 42 tests pass.", ts=3.0),
    ]
    selected, _all = select_stories(events)
    assert len(selected) == 1
    assert selected[0].kind == "session"
    assert selected[0].goal.startswith("Please build")
    assert "42 tests" in selected[0].outcome


def test_a_session_without_an_outcome_is_not_selected():
    events = [user("s1", "Please build the read-only SQLite adapter for the reel")]
    selected, all_candidates = select_stories(events)
    assert selected == []
    assert all_candidates[0].excluded == "no outcome"


def test_a_governance_task_family_is_never_a_story():
    events = task("t_gov", "Needs Sahil's decision: review gate for the release")
    selected, all_candidates = select_stories(events)
    assert selected == []
    assert "plumbing" in all_candidates[0].excluded


def test_a_real_work_task_family_is_a_story():
    events = task("t_work", "Build the SQLite read-only adapter for the reel")
    selected, _all = select_stories(events)
    assert len(selected) == 1
    assert selected[0].kind == "task"
    assert selected[0].title.startswith("Build the SQLite")


def test_sessions_outrank_bookkeeping():
    events = (
        task("t_gov", "Triage the blocked card", statuses=("created", "blocked", "completed"))
        + task("t_open", "Update the dispatcher retry policy", statuses=("created", "gave_up"))
        + [
            user("s9", "Please ship the weekly comic renderer this week"),
            assistant("s9", "Shipped the renderer and wired three episodes.", ts=3.0),
            user("s9", "Now make the captions readable", ts=4.0),
            assistant("s9", "Captions now compose from structured facts.", ts=5.0),
        ]
    )
    selected, all_candidates = select_stories(events, limit=3)
    assert selected[0].kind == "session"
    assert all(candidate.kind == "session" for candidate in selected)
    assert len(all_candidates) >= 3


def test_plumbing_events_stay_available_as_detail():
    """Excluded as a *story*, still present in the event list for a real thread."""
    events = task("t_gov", "Needs Sahil's decision: review gate")
    _selected, all_candidates = select_stories(events)
    assert all_candidates[0].event_ids, "the events must not be discarded"


def test_limit_is_respected():
    events = task("t_a", "Build the adapter for the reel") + task(
        "t_b", "Write the weekly renderer for the strip", ts=100.0
    ) + task("t_c", "Add the voice intake handoff", ts=200.0)
    selected, _all = select_stories(events, limit=2)
    assert len(selected) == 2
