"""R4-F1: the owner asked; a profile is the character; nobody is called "Assistant"."""

from __future__ import annotations

from canon.caption import compose_caption
from canon.events import (
    KIND_MESSAGE_ASSISTANT,
    KIND_MESSAGE_USER,
    KIND_TASK_STATUS,
    build_event,
)
from canon.gate import seal


def message(role, text, *, profile="default", ts=1.0, actor=None):
    kind = KIND_MESSAGE_USER if role == "user" else KIND_MESSAGE_ASSISTANT
    resolved = actor if actor is not None else ("owner" if role == "user" else profile)
    event = build_event(
        source="session", kind=kind, ts=ts, profile=profile, actor=resolved, subject="s1",
        payload={"text": text, "role": role, "session_id": "s1"},
        store="main", table="messages", pk=f"s1-{role}-{ts}",
    )
    return seal(event, event.payload)


def test_the_owners_own_message_is_captioned_as_the_owner():
    row = message("user", "yes I approve 2")
    caption = compose_caption(row, display={"owner": "Sahil", "default": "Kensei"})
    assert caption.startswith("Sahil asked for")
    assert "Kensei" not in caption


def test_an_assistant_message_is_the_profiles_character():
    row = message("assistant", "the adapter is built and 42 tests pass", profile="denji-reviewer")
    caption = compose_caption(row, display={"default": "Kensei", "denji-reviewer": "Denji"})
    assert caption.startswith("Denji")
    assert "Assistant" not in caption
    assert "asked" not in caption


def test_no_character_is_ever_called_assistant():
    row = message("assistant", "a plain report about the build", profile="assistant", actor="assistant")
    caption = compose_caption(row, display={})
    assert "Assistant" not in caption


def test_asked_is_only_said_of_the_owner():
    user_row = message("user", "please build the read-only adapter")
    assistant_row = message("assistant", "the read-only adapter is built and tests pass", ts=2.0)
    assert "asked" in compose_caption(user_row)
    assert "asked" not in compose_caption(assistant_row)


def test_a_task_event_does_not_use_the_owner_name():
    event = build_event(
        source="kanban", kind=KIND_TASK_STATUS, ts=3.0, profile="octacon", actor="octacon",
        subject="t1", payload={"task_id": "t1", "kind": "completed", "text": "the adapter"},
        store="main", table="task_events", pk="t1-c",
    )
    sealed = seal(event, event.payload)
    caption = compose_caption(sealed, display={"owner": "Sahil", "octacon": "Octacon"})
    assert caption.startswith("Octacon")
    assert "Sahil" not in caption


def test_an_unmapped_profile_still_gets_a_name_not_assistant():
    row = message("assistant", "a report from an unlisted worker profile", profile="wesker-2")
    caption = compose_caption(row, display={})
    assert "Assistant" not in caption
    assert caption.startswith("Wesker 2")
