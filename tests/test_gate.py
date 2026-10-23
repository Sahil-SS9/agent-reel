"""F1: the privacy field and the post-gate payload boundary."""

from __future__ import annotations

import dataclasses
import json
from typing import Any

import pytest

from canon import events as ev
from canon.events import PRIVACY_INTERNAL, PRIVACY_LEVELS, PRIVACY_PRIVATE, PRIVACY_PUBLIC
from canon.events import build_event, iter_jsonl_events
from canon.gate import GatedEvent, UngatedError, require_gated, seal


def _event(**kwargs: Any) -> ev.Event:
    base: dict[str, Any] = dict(
        source="message",
        kind="message.user",
        ts=1700000000.0,
        profile="alpha",
        payload={"chars": 12, "content_digest": "sha256:abc"},
        store="profile:alpha",
        table="messages",
        pk="1",
    )
    base.update(kwargs)
    return build_event(**base)


def test_privacy_defaults_to_private():
    assert _event().privacy == PRIVACY_PRIVATE


@pytest.mark.parametrize("level", PRIVACY_LEVELS)
def test_privacy_levels_are_accepted(level):
    assert _event(privacy=level).privacy == level


def test_unknown_privacy_level_is_rejected():
    with pytest.raises(ValueError):
        _event(privacy="secret-squirrel")


def test_privacy_survives_jsonl_roundtrip():
    for level in (PRIVACY_PRIVATE, PRIVACY_INTERNAL, PRIVACY_PUBLIC):
        event = _event(privacy=level)
        restored = list(iter_jsonl_events([ev.event_to_jsonl(event)]))[0]
        assert restored.privacy == level
        assert json.loads(ev.event_to_jsonl(event))["privacy"] == level


def test_event_has_no_redacted_payload_before_the_gate():
    assert _event().payload_redacted is None
    assert "payload_redacted" not in json.loads(ev.event_to_jsonl(_event()))


def test_gated_event_cannot_be_built_directly():
    with pytest.raises(UngatedError):
        GatedEvent(
            id="ev_x",
            ts=1.0,
            source="message",
            kind="message.user",
            profile="alpha",
            actor="alpha",
            subject="user",
            privacy=PRIVACY_PRIVATE,
            payload={"chars": 1},
        )


def test_seal_produces_a_gated_event_with_only_redacted_payload():
    event = _event()
    gated = seal(event, {"chars": 12, "text": "redacted text"})
    assert isinstance(gated, GatedEvent)
    assert gated.payload == {"chars": 12, "text": "redacted text"}
    assert gated.privacy == PRIVACY_PRIVATE
    # The raw payload's digest field is not carried over automatically.
    assert "content_digest" not in gated.payload
    assert gated.to_dict()["payload_redacted"]["text"] == "redacted text"
    assert json.loads(json.dumps(gated.to_dict()))["payload_redacted"]


def test_a_gated_event_cannot_carry_the_raw_payload():
    event = _event()
    gated = seal(event, {"chars": 12})
    assert gated.payload == {"chars": 12}
    assert "content_digest" not in gated.payload
    # An event that already carries a redacted payload must not be gated twice.
    already = dataclasses.replace(event, payload_redacted={"chars": 1})
    with pytest.raises(UngatedError):
        seal(already, {"chars": 12})


def test_downstream_stages_reject_ungated_events():
    raw = _event()
    with pytest.raises(UngatedError):
        require_gated([raw], stage="beats")
    with pytest.raises(UngatedError):
        require_gated(["not an event"], stage="arcs")


def test_downstream_stages_accept_gated_events():
    gated = seal(_event(), {"chars": 12})
    assert require_gated([gated], stage="beats") == [gated]
    assert require_gated(gated, stage="beats") == [gated]


def test_gated_repr_does_not_dump_the_payload():
    gated = seal(_event(), {"text": "private words"})
    assert "private words" not in repr(gated)


def test_schema_version_bumped_for_the_new_field():
    assert ev.SCHEMA_VERSION == 2
