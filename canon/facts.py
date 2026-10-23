"""Atomic facts: what a brief says, in pieces small enough to check (round 6).

Round 5 judged a caption against the whole raw evidence of a panel, and a paraphrase
almost always lost: the evidence is a long message, the caption is one sentence, and the
check could not tell "summarised" from "invented". So the caption fell back to a quote of
the owner's own words, or to nothing.

A brief is now reduced to atomic facts first - actor, action, object, result, numbers -
each one already entailed by its events. Captions and lines are judged against that short
list instead. Every fact is derived from the thread's own gated text; a fact never
paraphrases, so it cannot introduce a claim the thread does not contain.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from canon.events import (
    KIND_MESSAGE_ASSISTANT,
    KIND_MESSAGE_USER,
    KIND_TASK_CLAIMED,
    KIND_TASK_COMMENT,
    KIND_TASK_CREATED,
    KIND_TASK_FINISHED,
    KIND_TASK_STATUS,
)
from canon.gate import GatedEvent

MAX_OBJECT_WORDS = 12
MAX_RESULT_WORDS = 16

_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")

#: Verbs a fact may use, by event kind and status. None of them is a template filler.
_STATUS_VERBS = {
    "created": "opened",
    "claimed": "took on",
    "blocked": "hit",
    "gave_up": "gave up on",
    "completed": "completed",
    "unblocked": "cleared",
    "review_requested": "sent for review",
}
_KIND_VERBS = {
    KIND_TASK_CREATED: "opened",
    KIND_TASK_CLAIMED: "took on",
    KIND_TASK_STATUS: "hit",
    KIND_TASK_FINISHED: "completed",
    KIND_TASK_COMMENT: "noted",
    KIND_MESSAGE_USER: "wants",
    KIND_MESSAGE_ASSISTANT: "reported",
}


@dataclass(frozen=True, slots=True)
class Fact:
    """One thing the thread actually says."""

    kind: str  # goal | turn | outcome
    actor: str
    action: str
    object: str = ""
    result: str = ""
    numbers: tuple[str, ...] = ()
    event_id: str = ""
    source_text: str = ""

    @property
    def sentence(self) -> str:
        """A caption-sized statement of this fact, in the thread's own words."""
        if self.kind == "outcome" and self.result:
            clause = self.result.strip(" .;")
            if not clause:
                return ""
            return f"{clause[0].upper()}{clause[1:]}."
        if not self.object:
            return ""
        who = self.actor or ""
        opener = f"{who} {self.action} {self.object}".strip()
        opener = re.sub(r"\s+", " ", opener)
        return f"{opener[0].upper()}{opener[1:]}." if opener else ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "actor": self.actor,
            "action": self.action,
            "object": self.object,
            "result": self.result,
            "numbers": list(self.numbers),
            "event_id": self.event_id,
            "sentence": self.sentence,
        }


#: A sentence boundary, but not the period inside a number ("87.3").
_BOUNDARY = re.compile(r"(?:;|\n|\.(?=\s|$))")


def _first_clause(text: str, limit: int) -> str:
    clause = _BOUNDARY.split(" ".join((text or "").split()), maxsplit=1)[0]
    clause = clause.strip(" ,:-\u2014")
    words = clause.split()
    if len(words) > limit:
        clause = " ".join(words[:limit])
    return clause


def _clauses(text: str) -> list[str]:
    parts = _BOUNDARY.split(" ".join((text or "").split()))
    return [part.strip(" ,:-\u2014") for part in parts if part.strip()]


def _numbers(text: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(_NUMBER.findall(text or "")))


def _verb_for(event: GatedEvent) -> str:
    status = str((event.payload or {}).get("kind") or "").strip().lower()
    if status in _STATUS_VERBS:
        return _STATUS_VERBS[status]
    return _KIND_VERBS.get(event.kind, "handled")


def _actor_for(event: GatedEvent, display: Mapping[str, str], hero: str) -> str:
    role = str((event.payload or {}).get("role") or "").lower()
    if role == "user" or event.actor == "owner":
        return display.get("owner") or hero
    for key in (event.profile, event.actor):
        mapped = display.get(key or "")
        if mapped:
            return mapped
        clean = str(key or "").replace("-", " ").title()
        if clean and clean.lower() not in {"default", "assistant", "agent", "the fleet"}:
            return clean
    return "The agent"


def build_facts(
    brief: Any,
    events_by_id: Mapping[str, GatedEvent],
    *,
    display: Mapping[str, str] | None = None,
    hero: str = "Sahil",
) -> tuple[Fact, ...]:
    """Reduce a brief to atomic facts, in story order."""
    table = dict(display or {})
    facts: list[Fact] = []

    def text_of(event_id: str) -> str:
        event = events_by_id.get(event_id)
        if event is None:
            return ""
        payload = event.payload or {}
        for key in ("text", "title", "summary", "body", "message"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return " ".join(value.split())
        return ""

    # goal
    goal = str(getattr(brief, "goal", "") or "")
    goal_event = next(
        (
            event_id
            for event_id in events_by_id
            if text_of(event_id) and text_of(event_id) in goal
        ),
        "",
    )
    if goal:
        actor = (
            _actor_for(events_by_id[goal_event], table, hero)
            if goal_event and goal_event in events_by_id
            else (table.get("owner") or hero)
        )
        facts.append(
            Fact(
                kind="goal",
                actor=actor,
                action="wants",
                object=_first_clause(goal, MAX_OBJECT_WORDS),
                numbers=_numbers(goal),
                event_id=goal_event,
                source_text=goal,
            )
        )

    # turns
    for turn in getattr(brief, "turns", ()) or ():
        event_id = getattr(turn, "event_id", "")
        event = events_by_id.get(event_id)
        text = getattr(turn, "text", "") or text_of(event_id)
        if event is None or not text:
            continue
        facts.append(
            Fact(
                kind="turn",
                actor=_actor_for(event, table, hero),
                action=_verb_for(event),
                object=_first_clause(text, MAX_OBJECT_WORDS),
                numbers=_numbers(text),
                event_id=event_id,
                source_text=text,
            )
        )

    # outcome: one fact per clause, so the numbers survive into the strip
    outcome = str(getattr(brief, "outcome", "") or "")
    outcome_event = next(
        (event_id for event_id in events_by_id if text_of(event_id) and text_of(event_id) in outcome),
        "",
    )
    actor = (
        _actor_for(events_by_id[outcome_event], table, hero)
        if outcome_event and outcome_event in events_by_id
        else "The agent"
    )
    for clause in _clauses(outcome):
        short = _first_clause(clause, MAX_RESULT_WORDS)
        if not short:
            continue
        facts.append(
            Fact(
                kind="outcome",
                actor=actor,
                action="reported",
                result=short,
                numbers=_numbers(short),
                event_id=outcome_event,
                source_text=outcome,
            )
        )
    return tuple(facts)


def facts_text(facts: Iterable[Fact]) -> str:
    """The short list captions and lines are judged against."""
    return "\n".join(fact.sentence for fact in facts if fact.sentence)


def outcome_facts(facts: Sequence[Fact]) -> tuple[Fact, ...]:
    return tuple(fact for fact in facts if fact.kind == "outcome")


def fact_numbers(facts: Iterable[Fact]) -> tuple[str, ...]:
    seen: dict[str, None] = {}
    for fact in facts:
        for number in fact.numbers:
            seen.setdefault(number, None)
    return tuple(seen)
