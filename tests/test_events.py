"""Tests for the normalised event model (canon must stay Hermes-free)."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

from canon import events as ev
from canon.events import ContentRef, Event, build_event, iter_jsonl_events, make_event_id


def test_event_id_is_deterministic():
    first = make_event_id("message", "message.user", 1234.5, {"store": "main", "pk": "1"})
    second = make_event_id("message", "message.user", 1234.5, {"store": "main", "pk": "1"})
    assert first == second
    assert first.startswith("ev_")


def test_event_id_changes_with_provenance_and_kind():
    base = make_event_id("message", "message.user", 1.0, {"pk": "1"})
    assert base != make_event_id("message", "message.user", 1.0, {"pk": "2"})
    assert base != make_event_id("message", "message.assistant", 1.0, {"pk": "1"})
    assert base != make_event_id("message", "message.user", 2.0, {"pk": "1"})


def test_unknown_source_is_rejected():
    with pytest.raises(ValueError):
        Event(id="ev_x", ts=1.0, source="not_a_source", kind="whatever")


def test_kind_is_required():
    with pytest.raises(ValueError):
        Event(id="ev_x", ts=1.0, source="message", kind="")


def test_build_event_creates_content_ref_only_when_asked():
    with_ref = build_event(
        source="message",
        kind="message.user",
        ts=1.0,
        store="main",
        table="messages",
        pk="7",
        payload={"chars": 10},
    )
    assert with_ref.content_ref == ContentRef(store="main", table="messages", pk="7")

    without = build_event(
        source="skill",
        kind="skill.used",
        ts=1.0,
        store="skills:default",
        table=".usage.json",
        pk="demo",
        content_column=None,
    )
    assert without.content_ref is None
    assert without.ref == {"store": "skills:default", "table": ".usage.json", "pk": "demo"}


def test_jsonl_roundtrip_preserves_everything():
    original = build_event(
        source="message",
        kind="message.user",
        ts=1700000000.5,
        profile="alpha",
        actor="alpha",
        subject="user",
        payload={"chars": 12, "content_digest": "sha256:abc"},
        store="profile:alpha",
        table="messages",
        pk="42",
    )
    line = ev.event_to_jsonl(original)
    restored = list(iter_jsonl_events([line]))[0]
    assert restored == original
    assert json.loads(line)["v"] == ev.SCHEMA_VERSION


def test_duplicate_ids_are_caught():
    one = build_event(source="skill", kind="skill.used", ts=1.0, store="s", table="t", pk="p")
    two = build_event(source="skill", kind="skill.patched", ts=1.0, store="s", table="t", pk="p")
    with pytest.raises(ValueError):
        ev.assert_unique_ids([one, one])
    assert ev.assert_unique_ids([one, two]) == 2


def test_discriminator_separates_same_row_same_second():
    a = build_event(
        source="tool_call", kind="tool.call", ts=1.0, store="s", table="messages", pk="1",
        discriminator="0:call_a",
    )
    b = build_event(
        source="tool_call", kind="tool.call", ts=1.0, store="s", table="messages", pk="1",
        discriminator="1:call_b",
    )
    assert a.id != b.id


def test_canon_package_never_imports_hermes():
    """Decision D2: the core must not depend on Hermes."""
    for module_name in ("canon.events", "canon.source"):
        module = importlib.import_module(module_name)
        source = Path(module.__file__ or "").read_text(encoding="utf-8")
        assert "import hermes" not in source
        assert "from hermes" not in source
        assert "from adapters" not in source
        assert "import adapters" not in source

    # Importing canon must not pull any Hermes module into sys.modules.
    for name in list(sys.modules):
        assert not name.startswith(("hermes_cli", "tools.hermes")), name
