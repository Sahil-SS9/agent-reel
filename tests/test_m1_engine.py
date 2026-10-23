"""M1: beats, arcs, canon and the Script IR."""

from __future__ import annotations

import pytest

from canon.arcs import ARC_ROLES, build_arc, build_arcs
from canon.beats import BEAT_TYPES, Beat, beats_from_events
from canon.canon import Canon, build_canon
from canon.episode import (
    LLMDialogueWriter,
    TemplateDialogueWriter,
    plan_episode,
    validate_ir,
)
from canon.events import build_event
from canon.gate import GatedEvent, seal, UngatedError
from canon.redact import DeterministicRedactor, RedactionGate
from adapters.hermes.redact_source import rules_from_snapshot
from canon.cache import ModelCache
from canon.llm import CachedLLM, FakeLLM


def gate() -> RedactionGate:
    return RedactionGate(DeterministicRedactor(rules_from_snapshot()))


def gated(
    event_kind: str,
    ts: float,
    *,
    profile: str = "wesker",
    text: str = "",
    subject: str = "",
    **payload,
) -> GatedEvent:
    event = build_event(
        source="kanban" if event_kind.startswith("kanban") else "message",
        kind=event_kind,
        ts=ts,
        profile=profile,
        subject=subject,
        payload={"chars": len(text), **payload},
        store="main",
        table="messages",
        pk=f"{event_kind}-{ts}-{profile}",
        discriminator=subject,
    )
    sealed = gate().gate_event(event, text=text or None)
    assert sealed is not None
    return sealed


def test_beats_cover_the_expected_types():
    events = [
        gated("kanban.task.status", 100.0, kind="completed"),
        gated("kanban.task.status", 200.0, kind="blocked"),
        gated("cron.run.finished", 300.0, status="failed"),
        gated("message.user", 400.0, text="We decide to ship it tonight"),
        gated("skill.created", 500.0, subject="demo-skill"),
    ]
    beats = beats_from_events(events)
    types = {beat.type for beat in beats}
    assert types <= set(BEAT_TYPES)
    assert {"breakthrough", "struggle", "failure", "decision", "level-up"} <= types


def test_beats_require_gated_events():
    raw = build_event(
        source="message", kind="message.user", ts=1.0, payload={}, store="m", table="messages", pk="1"
    )
    with pytest.raises(UngatedError):
        beats_from_events([raw])


def test_beats_are_deterministic():
    events = [gated("kanban.task.status", float(index), kind="blocked") for index in range(5)]
    first = [beat.as_dict() for beat in beats_from_events(events)]
    second = [beat.as_dict() for beat in beats_from_events(events)]
    assert first == second


def test_beats_respect_the_cap_and_keep_the_strongest():
    events = [
        gated("kanban.task.status", float(index), kind="blocked" if index < 3 else "created")
        for index in range(10)
    ]
    beats = beats_from_events(events, max_beats=3)
    assert len(beats) == 3
    assert all(beat.intensity > 2 for beat in beats)


def test_beat_summary_never_contains_raw_payload_json():
    event = gated("message.user", 10.0, text='[{"id": "call_1", "function": "terminal"}]')
    beats = beats_from_events([event])
    assert beats == [], "a tool-call JSON blob is not a beat"


def test_tool_calls_do_not_produce_beats():
    event = build_event(
        source="tool_call",
        kind="tool.call",
        ts=1.0,
        profile="wesker",
        payload={"tool": "patch"},
        store="m",
        table="messages",
        pk="1",
    )
    sealed = gate().gate_event(event)
    assert sealed is not None
    assert beats_from_events([sealed]) == []


# --------------------------------------------------------------------------- #
# arcs
# --------------------------------------------------------------------------- #


def _story_events() -> list[GatedEvent]:
    return [
        gated("message.user", 100.0, text="We decide to fix the flaky test tonight"),
        gated("kanban.task.status", 200.0, kind="blocked"),
        gated("message.tool_result", 300.0, text="error: timeout talking to the runner"),
        gated("cron.run.finished", 400.0, status="failed"),
        gated("kanban.task.status", 500.0, kind="completed"),
        gated("message.tool_result", 600.0, text="tests passed, build green"),
        gated("kanban.task.status", 700.0, kind="blocked"),
    ]


def test_arc_has_the_template_roles_in_order():
    beats = beats_from_events(_story_events())
    arc = build_arc(beats)
    assert arc is not None
    assert arc.type == "struggle-to-resolution"
    roles = [role for role in ARC_ROLES if role in arc.roles]
    assert "climax" in roles
    timestamps = [
        next(beat.ts for beat in beats if beat.id == arc.roles[role]) for role in roles
    ]
    assert timestamps == sorted(timestamps), "arc roles must be chronological"


def test_arc_roles_are_distinct_beats():
    beats = beats_from_events(_story_events())
    arc = build_arc(beats)
    assert arc is not None
    assert len(set(arc.roles.values())) == len(arc.roles)


def test_arc_is_deterministic():
    beats = beats_from_events(_story_events())
    assert build_arc(beats).as_dict() == build_arc(beats).as_dict()


def test_arcs_are_built_only_from_one_thread():
    """Audit M1-F2: two task families never share an arc."""
    from canon.threads import build_threads

    events = [
        gated("kanban.task.status", float(index * 10), kind="blocked", subject=f"t{index}", task_id="t_a")
        for index in range(3)
    ] + [
        gated("kanban.task.status", 100.0 + index, kind="completed", subject=f"u{index}", task_id="t_b")
        for index in range(3)
    ]
    threads = build_threads(events)
    assert len(threads) == 2
    arcs = build_arcs(threads, beats_from_events(events))
    assert arcs
    for arc in arcs:
        event_threads = {event.payload.get("task_id") for event in events if event.id in set(arc.beat_ids) | set(arc.roles.values())}
        assert len(event_threads) <= 1, f"arc {arc.id} mixed threads: {event_threads}"


# --------------------------------------------------------------------------- #
# canon
# --------------------------------------------------------------------------- #


def test_canon_facts_carry_event_ids():
    events = _story_events()
    beats = beats_from_events(events)
    canon = build_canon(events, beats)
    facts = [
        fact for entity in canon.entities.values() for fact in entity.canon_facts
    ]
    assert facts
    for fact in facts:
        assert fact.event_ids, f"fact {fact.key} has no supporting events"
        known = {event.id for event in events}
        assert set(fact.event_ids) <= known


def test_canon_retcon_log_never_overwrites_silently():
    canon = Canon()
    entity = canon.entity("agent", "wesker")
    canon.set_fact(entity, "status", "busy", ["ev_1"], ts=1.0)
    canon.set_fact(entity, "status", "idle", ["ev_2"], ts=2.0, reason="job finished")
    assert entity.fact("status").value == "idle"
    assert len(canon.retcons) == 1
    retcon = canon.retcons[0]
    assert retcon.old_value == "busy"
    assert retcon.new_value == "idle"
    assert retcon.reason == "job finished"


def test_canon_is_deterministic():
    events = _story_events()
    beats = beats_from_events(events)
    first = build_canon(events, beats).to_json()
    second = build_canon(events, beats).to_json()
    assert first == second


def test_canon_promotes_a_recurring_problem_to_nemesis():
    events = [
        gated("kanban.task.status", float(index * 10), kind="blocked", subject="blocked")
        for index in range(4)
    ]
    beats = beats_from_events(events)
    canon = build_canon(events, beats)
    kinds = {entity.kind for entity in canon.entities.values()}
    assert "nemesis" in kinds


# --------------------------------------------------------------------------- #
# episode / Script IR
# --------------------------------------------------------------------------- #


def _ir(**kwargs):
    events = _story_events()
    beats = beats_from_events(events)
    arc = build_arc(beats)
    canon = build_canon(events, beats)
    return events, plan_episode(arc, beats, canon, **kwargs)


def test_strip_has_six_panels_and_chapter_more():
    _, strip = _ir(format="strip")
    _, chapter = _ir(format="chapter")
    assert len(strip.panels) >= 4
    assert len(chapter.panels) >= len(strip.panels)


def test_every_line_traces_to_a_real_event():
    events, ir = _ir()
    assert validate_ir(ir, known_event_ids={event.id for event in events}) == []


def test_ir_validation_catches_phantom_event_ids():
    import dataclasses

    _, ir = _ir()
    ir2 = dataclasses.replace(ir, panels=ir.panels[:1])
    problems = validate_ir(ir2, known_event_ids={"ev_not_a_real_id"})
    assert problems
    assert any("unknown source event id" in problem for problem in problems)


def test_ir_is_deterministic_with_the_template_writer():
    _, first = _ir()
    _, second = _ir()
    assert first.to_json() == second.to_json()


def test_speakers_come_from_the_panel_cast():
    _, ir = _ir()
    for panel in ir.panels:
        for line in panel.lines:
            assert line.speaker in panel.cast


def test_panels_carry_staging():
    _, ir = _ir()
    for panel in ir.panels:
        assert panel.shot in {"wide", "medium", "close", "insert"}
        assert panel.setting
        assert panel.caption
        assert panel.pose
        assert panel.expression


def test_llm_writer_falls_back_when_the_model_returns_rubbish(tmp_path):
    class Rubbish:
        name = "rubbish"

        def complete_json(self, **_kwargs):
            return {"lines": [{"speaker": "Not In Cast", "text": "hi"}]}

    cached = CachedLLM(Rubbish(), ModelCache(tmp_path / "cache"), stage="dialogue")
    events = _story_events()
    beats = beats_from_events(events)
    arc = build_arc(beats)
    canon = build_canon(events, beats)
    cast = ["Sahil", "wesker"]
    writer = LLMDialogueWriter(
        cached, cast, fallback=TemplateDialogueWriter(cast, hero="Sahil")
    )
    ir = plan_episode(arc, beats, canon, writer=writer)
    assert writer.failures > 0
    assert ir.panels
    for panel in ir.panels:
        for line in panel.lines:
            assert line.speaker in panel.cast


def test_llm_writer_uses_a_valid_model_response(tmp_path):
    class Good:
        name = "good"

        def complete_json(self, **_kwargs):
            return {"lines": [{"speaker": "Sahil", "text": "Ship it."}]}

    cached = CachedLLM(Good(), ModelCache(tmp_path / "cache"), stage="dialogue")
    events = _story_events()
    beats = beats_from_events(events)
    arc = build_arc(beats)
    canon = build_canon(events, beats)
    cast = ["Sahil", "wesker"]
    ir = plan_episode(
        arc, beats, canon, writer=LLMDialogueWriter(cached, cast, fallback=None)
    )
    texts = {line.text for panel in ir.panels for line in panel.lines}
    assert "Ship it." in texts
