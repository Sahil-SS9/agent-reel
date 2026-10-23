"""Canon: entities, facts and an append-only retcon log.

v1 rules kept exactly:
  * facts carry the event ids that support them;
  * canon never overwrites a fact silently - a changed fact appends a retcon.

Everything here is deterministic: same gated events in, same canon out.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from canon.beats import Beat
from canon.events import KIND_TASK_FINISHED, KIND_TOOL_CALL, make_event_id
from canon.gate import GatedEvent, require_gated

ENTITY_KINDS = ("hero", "agent", "nemesis", "place", "artifact", "running_joke")


@dataclass(slots=True)
class Fact:
    id: str
    entity_id: str
    key: str
    value: str
    event_ids: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "entity_id": self.entity_id,
            "key": self.key,
            "value": self.value,
            "event_ids": list(self.event_ids),
        }


@dataclass(slots=True)
class Entity:
    id: str
    kind: str
    name: str
    canon_facts: list[Fact] = field(default_factory=list)
    ref_sheet: str = ""
    voice: str = ""

    def __post_init__(self) -> None:
        if self.kind not in ENTITY_KINDS:
            raise ValueError(f"unknown entity kind: {self.kind!r}")

    def fact(self, key: str) -> Fact | None:
        for fact in self.canon_facts:
            if fact.key == key:
                return fact
        return None

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "name": self.name,
            "canon_facts": [fact.as_dict() for fact in self.canon_facts],
            "ref_sheet": self.ref_sheet,
            "voice": self.voice,
        }


@dataclass(frozen=True, slots=True)
class Retcon:
    id: str
    entity_id: str
    key: str
    old_value: str
    new_value: str
    reason: str
    ts: float
    event_ids: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "entity_id": self.entity_id,
            "key": self.key,
            "old_value": self.old_value,
            "new_value": self.new_value,
            "reason": self.reason,
            "ts": round(self.ts, 6),
            "event_ids": list(self.event_ids),
        }


class Canon:
    """The world state. Facts never change silently."""

    def __init__(self) -> None:
        self.entities: dict[str, Entity] = {}
        self.retcons: list[Retcon] = []

    # -- entities ----------------------------------------------------------
    def entity(self, kind: str, name: str, *, voice: str = "") -> Entity:
        entity_id = make_event_id("entity", kind, 0.0, {"name": name})
        existing = self.entities.get(entity_id)
        if existing is not None:
            return existing
        entity = Entity(id=entity_id, kind=kind, name=name, voice=voice)
        self.entities[entity_id] = entity
        return entity

    def by_name(self, name: str) -> Entity | None:
        for entity in self.entities.values():
            if entity.name == name:
                return entity
        return None

    # -- facts -------------------------------------------------------------
    def set_fact(
        self,
        entity: Entity,
        key: str,
        value: str,
        event_ids: Sequence[str],
        *,
        ts: float = 0.0,
        reason: str = "",
    ) -> Fact:
        """Record a fact. A change appends a retcon instead of overwriting."""
        current = entity.fact(key)
        fact_id = make_event_id("fact", key, ts, {"entity": entity.id, "value": value})
        if current is not None:
            if current.value == value:
                return current
            self.retcons.append(
                Retcon(
                    id=make_event_id("retcon", key, ts, {"entity": entity.id, "new": value}),
                    entity_id=entity.id,
                    key=key,
                    old_value=current.value,
                    new_value=value,
                    reason=reason or "fact changed with new evidence",
                    ts=ts,
                    event_ids=tuple(event_ids),
                )
            )
            current.value = value
            current.event_ids = tuple(event_ids)
            return current
        fact = Fact(
            id=fact_id,
            entity_id=entity.id,
            key=key,
            value=value,
            event_ids=tuple(event_ids),
        )
        entity.canon_facts.append(fact)
        return fact

    # -- serialisation -----------------------------------------------------
    def as_dict(self) -> dict[str, Any]:
        return {
            "entities": [self.entities[key].as_dict() for key in sorted(self.entities)],
            "retcons": [retcon.as_dict() for retcon in self.retcons],
        }

    def to_json(self) -> str:
        import json

        return json.dumps(self.as_dict(), indent=1, sort_keys=True)


def build_canon(
    events: Iterable[GatedEvent],
    beats: Sequence[Beat],
    *,
    hero_names: Sequence[str] = ("Sahil",),
    window_start: float = 0.0,
) -> Canon:
    """Derive the world from gated events and beats.

    Agents come from event profiles, the hero from the owner, a nemesis from a
    recurring problem (a rivalry signature), places and artifacts from what the
    week actually used.
    """
    gated = require_gated(events, stage="canon")
    canon = Canon()

    hero = None
    for name in hero_names:
        hero = canon.entity("hero", name, voice="dry, fast, wants the thing shipped")
    canon.entity("place", "the rig", voice="two 3090s, a lot of terminals")

    profile_counts: dict[str, int] = {}
    tool_counts: dict[str, int] = {}
    for event in gated:
        if event.profile:
            profile_counts[event.profile] = profile_counts.get(event.profile, 0) + 1
        if event.kind == KIND_TOOL_CALL:
            tool = str(event.payload.get("tool", ""))
            if tool:
                tool_counts[tool] = tool_counts.get(tool, 0) + 1

    agents: dict[str, Entity] = {}
    for profile, count in sorted(profile_counts.items()):
        agents[profile] = canon.entity("agent", profile, voice="specialist")

    # Facts per agent, each carrying the events that support it.
    per_agent_events: dict[str, list[GatedEvent]] = {}
    for event in gated:
        if event.profile:
            per_agent_events.setdefault(event.profile, []).append(event)
    for profile, entity in agents.items():
        events_for_agent = per_agent_events.get(profile, [])
        if not events_for_agent:
            continue
        canon.set_fact(
            entity,
            "activity",
            f"{len(events_for_agent)} events",
            [event.id for event in events_for_agent[:20]],
            ts=max(event.ts for event in events_for_agent),
            reason="window activity",
        )
        finished = [
            event
            for event in events_for_agent
            if event.kind == KIND_TASK_FINISHED
        ]
        if finished:
            canon.set_fact(
                entity,
                "tasks_finished",
                str(len(finished)),
                [event.id for event in finished],
                ts=max(event.ts for event in finished),
                reason="task completions in the window",
            )

    # Nemesis: the problem that kept coming back.
    struggle_counts: dict[str, list[Beat]] = {}
    for beat in beats:
        if beat.type not in {"struggle", "failure"}:
            continue
        signature = beat.tags[-1] if beat.tags else beat.type
        struggle_counts.setdefault(signature, []).append(beat)
    recurring = sorted(
        ((signature, group) for signature, group in struggle_counts.items() if len(group) >= 3),
        key=lambda item: (-len(item[1]), item[0]),
    )
    for signature, group in recurring[:1]:
        nemesis = canon.entity("nemesis", signature, voice="returns every time you think it is fixed")
        canon.set_fact(
            nemesis,
            "appearances",
            str(len(group)),
            [event_id for beat in group for event_id in beat.event_ids],
            ts=max(beat.ts for beat in group),
            reason="promoted to villain after 3+ appearances",
        )

    # Artifacts: the tools the week leaned on hardest.
    for tool, count in sorted(tool_counts.items(), key=lambda item: (-item[1], item[0]))[:3]:
        artifact = canon.entity("artifact", tool)
        tool_events = [
            event
            for event in gated
            if event.kind == KIND_TOOL_CALL and event.payload.get("tool") == tool
        ]
        # Timestamp from the events themselves, never from "now": a fact id that
        # moved with the wall clock would make canon non-deterministic.
        ts = min((event.ts for event in tool_events), default=0.0)
        canon.set_fact(
            artifact,
            "uses",
            str(count),
            [event.id for event in tool_events][:20],
            ts=ts,
            reason="tool usage in the window",
        )

    return canon
