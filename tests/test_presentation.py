"""M1-F6/F7: presentation - characters not ids, local time, one title, no repeats."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from canon.beats import beats_from_events
from canon.casting import build_cast_map, display_name, speaker_for
from canon.arcs import build_arc
from canon.canon import build_canon
from canon.episode import plan_episode
from canon.events import build_event
from canon.gate import seal
from canon.llm import FakeLLM
from canon.cache import ModelCache
from canon.llm import CachedLLM
from canon.titling import write_title


def test_default_profile_is_kensei():
    assert display_name("default") == "Kensei"
    assert display_name("kensei") == "Kensei"


def test_specialist_profiles_become_characters():
    assert display_name("octacon-backend") == "Octacon"
    assert display_name("wesker") == "Wesker"
    assert display_name("quan-security") == "Quan"


def test_cast_map_covers_profiles_and_the_hero():
    cast = build_cast_map(["default", "wesker", "octacon"], hero="Sahil")
    assert cast["default"] == "Kensei"
    assert cast["wesker"] == "Wesker"
    assert cast["Sahil"] == "Sahil"


def test_speaker_never_falls_back_to_a_profile_id():
    cast = build_cast_map(["default"], hero="Sahil")
    assert speaker_for("default", cast, hero="Sahil") == "Kensei"
    assert speaker_for("", cast, hero="Sahil") == "Sahil"


# --------------------------------------------------------------------------- #
# through the planner
# --------------------------------------------------------------------------- #


def _episode(**kwargs):
    events = []
    for index, (profile, kind_field, text) in enumerate(
        [
            ("default", "blocked", "the build blocked after 2 failures"),
            ("default", "blocked", "the build blocked again on the runner"),
            ("default", "completed", "the build completed after the fix"),
            ("default", "completed", "the build stayed green"),
        ]
    ):
        payload = {"kind": kind_field, "text": text, "task_id": "t_a", "chars": len(text)}
        event = build_event(
            source="kanban",
            kind="kanban.task.status",
            ts=1792700000.0 + index * 60,
            profile=profile,
            subject=kind_field,
            payload=payload,
            store="main",
            table="tasks",
            pk=f"t_a-{index}",
        )
        events.append(seal(event, payload))
    beats = beats_from_events(events)
    arc = build_arc(beats)
    canon = build_canon(events, beats)
    evidence = {event.id: str(event.payload.get("text", "")) for event in events}
    cast_map = build_cast_map([event.profile for event in events], hero="Sahil")
    return events, beats, arc, canon, evidence, cast_map


def test_panel_cast_uses_character_names():
    events, beats, arc, canon, evidence, cast_map = _episode()
    ir = plan_episode(
        arc, beats, canon, evidence=evidence, cast_map=cast_map, hero="Sahil"
    )
    names = {name for panel in ir.panels for name in panel.cast}
    assert "default" not in names
    assert "Kensei" in names
    for panel in ir.panels:
        for line in panel.lines:
            assert line.speaker in panel.cast


def test_captions_are_in_europe_london():
    _events, beats, arc, canon, evidence, cast_map = _episode()
    ir = plan_episode(arc, beats, canon, evidence=evidence, cast_map=cast_map)
    # 2026-10-23 is BST (UTC+1): 11:20 UTC is 12:20 in London.
    first = ir.panels[0].caption
    assert first
    utc_hour = datetime.fromtimestamp(beats[0].ts, tz=timezone.utc).hour
    london_hour = int(first.split()[3].split(":")[0])
    assert london_hour == (utc_hour + 1) % 24, first


def test_a_grounded_model_title_is_used():
    class Title:
        name = "title"

        def complete_json(self, **_kwargs):
            return {"title": "The build blocked again"}

    cached = CachedLLM(Title(), ModelCache.__new__(ModelCache), stage="t")
    cached.cache = _NullCache()
    _events, beats, _arc, _canon, _evidence, _cast = _episode()
    title, source = write_title(cached, beats=beats, derived="derived title")
    assert source == "model"
    assert title == "The build blocked again"


def test_an_ungrounded_title_is_refused():
    class Invent:
        name = "invent"

        def complete_json(self, **_kwargs):
            return {"title": "The GPU melted in the night"}

    cached = CachedLLM(Invent(), ModelCache.__new__(ModelCache), stage="t")
    cached.cache = _NullCache()
    _events, beats, _arc, _canon, _evidence, _cast = _episode()
    title, source = write_title(cached, beats=beats, derived="derived title")
    assert source == "ungrounded"
    assert title == "derived title"


class _NullCache:
    def get(self, _key):
        return None

    def set(self, _key, _value):
        return None


def test_no_model_title_falls_back_to_the_derived_one():
    _events, beats, _arc, _canon, _evidence, _cast = _episode()
    title, source = write_title(None, beats=beats, derived="derived title")
    assert (title, source) == ("derived title", "derived")


# --------------------------------------------------------------------------- #
# F7
# --------------------------------------------------------------------------- #


def test_a_tool_result_is_never_a_beat_on_its_own():
    payload = {"text": "error: timeout talking to the runner", "chars": 35}
    event = build_event(
        source="message",
        kind="message.tool_result",
        ts=10.0,
        profile="wesker",
        subject="read_file",
        payload=payload,
        store="main",
        table="messages",
        pk="1",
    )
    sealed = seal(event, payload)
    assert beats_from_events([sealed]) == []


def test_a_tool_name_never_becomes_a_struggle_beat():
    payload = {"tool": "skill_view", "chars": 0}
    event = build_event(
        source="tool_call",
        kind="tool.call",
        ts=10.0,
        profile="remii",
        subject="skill_view",
        payload=payload,
        store="main",
        table="messages",
        pk="2",
    )
    sealed = seal(event, payload)
    assert beats_from_events([sealed]) == []
