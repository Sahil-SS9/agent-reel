"""Round 9 / R8-F2: tool calls and tool results are not story.

RED-first: written before the brief filter, so it fails on the r8 brief builder.
"""

from __future__ import annotations

from canon.brief import build_brief
from canon.events import (
    KIND_MESSAGE_ASSISTANT,
    KIND_MESSAGE_TOOL_RESULT,
    KIND_MESSAGE_USER,
    KIND_TOOL_CALL,
    build_event,
)
from canon.gate import seal

TOOL_TEXT = '{"ok": false, "error": "not_found", "detail": "chat_history_lookup"}'


def row(kind, text, ts, *, role="", actor="owner"):
    event = build_event(
        source="session",
        kind=kind,
        ts=ts,
        profile="kensei",
        actor=actor,
        subject="s-tools",
        payload={"text": text, "role": role, "session_id": "s-tools"},
        store="main",
        table="messages",
        pk=f"s-tools-{ts}",
    )
    return seal(event, event.payload)


def session():
    return [
        row(KIND_MESSAGE_USER, "Please compare the two memory providers properly", 1.0, role="user"),
        row(KIND_TOOL_CALL, "tool_search({query: memory providers})", 2.0, actor="kensei"),
        row(KIND_MESSAGE_TOOL_RESULT, TOOL_TEXT, 3.0, role="tool", actor="kensei"),
        row(KIND_MESSAGE_ASSISTANT, "Both providers were scored on the same corpus.", 4.0, role="assistant", actor="kensei"),
        row(KIND_MESSAGE_TOOL_RESULT, "| table | rows |\n| state | 41 |", 5.0, role="tool", actor="kensei"),
        row(KIND_MESSAGE_ASSISTANT, "Severian scored 87.3 against LCM-X at 79.5 on LoCoMo.", 6.0, role="assistant", actor="kensei"),
    ]


def test_tool_payloads_never_become_brief_turns():
    brief = build_brief("s-tools", "session", session())
    text = brief.text()
    assert "not_found" not in text
    assert "chat_history_lookup" not in text
    assert "| table |" not in text
    for turn in brief.turns:
        assert "{" not in turn.text and "|" not in turn.text


def test_the_prose_still_makes_the_brief():
    brief = build_brief("s-tools", "session", session())
    assert "compare the two memory providers" in brief.goal.lower()
    assert "87.3" in brief.outcome


def test_a_tool_only_event_is_not_a_turn_even_when_it_has_text():
    brief = build_brief("s-tools", "session", session())
    turn_ids = {turn.event_id for turn in brief.turns}
    tool_ids = {event.id for event in session() if "tool" in event.kind}
    assert not (turn_ids & tool_ids)


def test_a_session_id_is_stripped_from_goal_and_outcome():
    rows = [
        row(KIND_MESSAGE_USER, "local-539a874f7ef77157e046c61254834eb0 broke the session again", 1.0, role="user"),
        row(KIND_MESSAGE_ASSISTANT, "The session was restored and the suite passed.", 2.0, role="assistant", actor="kensei"),
        row(KIND_MESSAGE_ASSISTANT, "Everything is green again after the fix.", 3.0, role="assistant", actor="kensei"),
    ]
    brief = build_brief("s-ids", "session", rows)
    assert "local-539a" not in brief.goal
    assert "a session" in brief.goal.lower()


def test_metrics_brief_text_is_short():
    rows = session() + [
        row(KIND_MESSAGE_ASSISTANT, "word " * 120, 7.0, role="assistant", actor="kensei"),
    ]
    brief = build_brief("s-tools", "session", rows)
    payload = brief.as_dict()
    assert len(payload["goal"]) <= 161
    assert len(payload["outcome"]) <= 161
    for turn in payload["turns"]:
        assert len(turn["text"]) <= 161
        assert len(turn["text"]) <= 161
