"""Beats: the story-shaped units extracted from gated events.

Deterministic on purpose. SPEC §4 wants "the same input twice gives byte-identical
canon", and a rule table gives that for free; a model here would need the cache to
promise the same thing, and would make the benchmark unreadable.

A beat is v1's shape: ``{id, type, summary, intensity, event_ids[], ts}``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

from canon.events import (
    KIND_CRON_FINISHED,
    KIND_MESSAGE_TOOL_RESULT,
    KIND_MESSAGE_USER,
    KIND_RUN_FINISHED,
    KIND_SKILL_CREATED,
    KIND_SKILL_USED,
    KIND_TASK_COMMENT,
    KIND_TASK_CREATED,
    KIND_TASK_FINISHED,
    KIND_TASK_STATUS,
    make_event_id,
)
from canon.gate import GatedEvent, require_gated

BEAT_TYPES = (
    "struggle",
    "breakthrough",
    "failure",
    "decision",
    "level-up",
    "joke",
    "cameo",
)

#: ``tool.call`` is deliberately absent: one call per row means tens of thousands
#: per week and it is not a story unit. Tools show up in canon as artifacts, and
#: level-ups come from the skill ledger instead.
TRIGGER_KINDS = frozenset(
    {
        KIND_TASK_CREATED,
        KIND_TASK_COMMENT,
        KIND_TASK_STATUS,
        KIND_TASK_FINISHED,
        KIND_RUN_FINISHED,
        KIND_CRON_FINISHED,
        KIND_MESSAGE_TOOL_RESULT,
        KIND_MESSAGE_USER,
        KIND_SKILL_CREATED,
        KIND_SKILL_USED,
    }
)

#: Words in a redacted payload that mean something went wrong.
STRUGGLE_WORDS = (
    "error", "failed", "failure", "blocked", "traceback", "timeout", "timed out",
    "crash", "broken", "exception", "denied", "retry", "flaky", "stuck",
)
RESOLUTION_WORDS = (
    "done", "completed", "fixed", "passed", "green", "merged", "shipped",
    "success", "resolved", "works",
)
DECISION_WORDS = ("decide", "decision", "approve", "go/no-go", "sign off", "sign-off", "choose", "scope")
JOKE_WORDS = ("ha", "lol", "joke", "funny", "again", "obviously", "of course")

STATUS_KIND_WEIGHT = {
    "blocked": 4,
    "gave_up": 5,
    "block_loop_detected": 4,
    "protocol_violation": 3,
    "claim_rejected": 2,
    "completed": 4,
    "promoted": 2,
    "review_requested": 3,
    "decomposed": 2,
    "created": 1,
    "claimed": 1,
    "unblocked": 2,
    "archived": 1,
    "auto_archived": 1,
    "spawned": 1,
    "specified": 1,
    "worker_result": 2,
    "dependency_wait": 2,
    "owner_admitted": 3,
    "forced_skill_rejected": 2,
}


@dataclass(frozen=True, slots=True)
class Beat:
    id: str
    type: str
    summary: str
    intensity: int
    event_ids: tuple[str, ...]
    ts: float
    profile: str = ""
    tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.type not in BEAT_TYPES:
            raise ValueError(f"unknown beat type: {self.type!r}")
        if not 1 <= self.intensity <= 5:
            raise ValueError(f"beat intensity out of range: {self.intensity}")

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "summary": self.summary,
            "intensity": self.intensity,
            "event_ids": list(self.event_ids),
            "ts": round(self.ts, 6),
            "profile": self.profile,
            "tags": list(self.tags),
        }


def _text_of(event: GatedEvent) -> str:
    value = event.payload.get("text")
    return value if isinstance(value, str) else ""


def _haystack(event: GatedEvent) -> str:
    parts = [_text_of(event)]
    for key in ("status", "outcome", "kind", "end_reason", "tool", "title"):
        value = event.payload.get(key)
        if isinstance(value, str):
            parts.append(value)
    return " ".join(parts).lower()


def _hits(haystack: str, words: Sequence[str]) -> int:
    return sum(1 for word in words if word in haystack)


_JSON_KEY_RE = re.compile(r'"([A-Za-z_]{3,30})"\s*:')


def _clean_text(text: str) -> str:
    """Turn raw text into something a comic can use.

    Tool output and kanban payloads are often JSON or JSON-ish; pasting that into a
    caption is how a script ends up reading like a stack trace.
    """
    value = " ".join(text.split())
    if not value:
        return ""
    if value[0] in "{[" or value.count('"') >= 4:
        # JSON-ish: a field list is not a caption. Return nothing and let the
        # structural fallback describe the event instead.
        return ""
    return value


def _summary_for(event: GatedEvent, beat_type: str) -> str:
    text = _clean_text(_text_of(event))
    if len(text) > 140:
        text = text[:137].rstrip() + "..."
    who = event.profile or event.actor or "the rig"
    subject = event.subject or event.kind
    if text:
        return f"{who}: {text}"
    # Structural fallback: no text was fetched for this event (bounded on purpose),
    # so describe it from the safe fields instead of inventing prose.
    tool = event.payload.get("tool")
    if isinstance(tool, str) and tool:
        keys = event.payload.get("args_keys")
        hint = ", ".join(str(k) for k in keys[:3]) if isinstance(keys, list) and keys else ""
        return f"{who}: {tool}{(' (' + hint + ')') if hint else ''}"
    status = event.payload.get("status") or event.payload.get("outcome")
    if isinstance(status, str) and status:
        return f"{who}: {subject} {status}".strip()
    return f"{who}: {subject}"


def classify(event: GatedEvent) -> tuple[str, int] | None:
    """Map one gated event to (beat type, intensity), or None when it is not a beat."""
    hay = _haystack(event)
    struggles = _hits(hay, STRUGGLE_WORDS)
    resolutions = _hits(hay, RESOLUTION_WORDS)
    decisions = _hits(hay, DECISION_WORDS)

    if event.kind == KIND_TASK_STATUS:
        kind = str(event.payload.get("kind", ""))
        weight = STATUS_KIND_WEIGHT.get(kind, 0)
        if not weight:
            return None
        if kind in {"blocked", "gave_up", "block_loop_detected", "protocol_violation", "claim_rejected"}:
            return "struggle", min(5, max(2, weight))
        if kind in {"completed", "promoted", "unblocked"}:
            return "breakthrough", min(5, max(2, weight))
        if decisions:
            return "decision", 3
        return None

    if event.kind == KIND_TASK_FINISHED:
        return ("breakthrough", 4) if "done" in hay or not struggles else ("struggle", 3)

    if event.kind == KIND_RUN_FINISHED:
        outcome = str(event.payload.get("outcome", "")).lower()
        status = str(event.payload.get("status", "")).lower()
        if outcome in {"crashed", "timed_out", "spawn_failed", "gave_up", "reclaimed", "failed"}:
            return "failure", 4
        if status in {"done", "completed"}:
            return "breakthrough", 3
        return None

    if event.kind == KIND_CRON_FINISHED:
        status = str(event.payload.get("status", "")).lower()
        if status == "failed":
            return "failure", 3
        return None

    if event.kind == KIND_MESSAGE_TOOL_RESULT:
        if struggles:
            return "struggle", min(5, 2 + struggles)
        return None

    if event.kind == KIND_SKILL_CREATED:
        return "level-up", 3

    if event.kind == KIND_SKILL_USED:
        uses = int(event.payload.get("use_count") or 0)
        if uses >= 5:
            return "level-up", min(5, 2 + uses // 5)
        return None

    if event.kind == KIND_TASK_COMMENT:
        if struggles:
            return "struggle", 2
        if decisions:
            return "decision", 3
        return None

    if event.kind == KIND_MESSAGE_USER:
        if decisions:
            return "decision", 3
        if _hits(hay, JOKE_WORDS) >= 2:
            return "joke", 2
        return None

    return None


def beats_from_events(
    events: Iterable[GatedEvent],
    *,
    max_beats: int = 400,
    min_intensity: int = 1,
) -> list[Beat]:
    """Turn gated events into beats, in timeline order, capped to the strongest."""
    gated = require_gated(events, stage="beats")
    produced: list[Beat] = []
    seen: set[str] = set()
    for event in sorted(gated, key=lambda item: (item.ts, item.id)):
        if event.kind not in TRIGGER_KINDS:
            continue
        verdict = classify(event)
        if verdict is None:
            continue
        beat_type, intensity = verdict
        if intensity < min_intensity:
            continue
        key = f"{beat_type}:{event.id}"
        if key in seen:
            continue
        seen.add(key)
        produced.append(
            Beat(
                id=make_event_id("beat", beat_type, event.ts, {"event": event.id}),
                type=beat_type,
                summary=_summary_for(event, beat_type),
                intensity=intensity,
                event_ids=(event.id,),
                ts=event.ts,
                profile=event.profile,
                tags=(event.kind, event.subject) if event.subject else (event.kind,),
            )
        )
    if len(produced) > max_beats:
        # Keep the strongest and earliest-tied, preserving timeline order.
        ranked = sorted(
            produced,
            key=lambda beat: (-beat.intensity, beat.ts, beat.id),
        )[:max_beats]
        produced = sorted(ranked, key=lambda beat: (beat.ts, beat.id))
    return produced


@dataclass
class BeatLedger:
    beats: list[Beat] = field(default_factory=list)

    def by_type(self) -> dict[str, list[Beat]]:
        out: dict[str, list[Beat]] = {beat_type: [] for beat_type in BEAT_TYPES}
        for beat in self.beats:
            out[beat.type].append(beat)
        return out

    def as_dict(self) -> dict[str, Any]:
        return {"beats": [beat.as_dict() for beat in self.beats]}

    @classmethod
    def from_events(cls, events: Iterable[GatedEvent], **kwargs: Any) -> "BeatLedger":
        return cls(beats=beats_from_events(events, **kwargs))
