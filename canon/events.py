"""The normalised event model every adapter produces.

Design rules
------------
1. Pure Python. No Hermes imports (decision D2).
2. An ``Event`` carries *structure*, never raw free text. Text lives behind a
   ``ContentRef`` and is fetched by the ingest stage, which must run the
   redaction gate before the text can travel any further. This keeps real
   history out of places it must not reach (HANDOFF ground rule 5).
3. Ids are content-derived, so the same source rows always give the same ids.
   Re-running ingest is therefore idempotent and comparable.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Iterable, Iterator, Mapping

SCHEMA_VERSION = 1

# --------------------------------------------------------------------------- #
# Sources and kinds
# --------------------------------------------------------------------------- #

SOURCE_SESSION = "session"
SOURCE_MESSAGE = "message"
SOURCE_TOOL_CALL = "tool_call"
SOURCE_KANBAN = "kanban"
SOURCE_SKILL = "skill"
SOURCE_CRON = "cron"
SOURCE_MEMORY = "memory"

#: Fixed emission order. Adapters must be deterministic; this is part of that.
SOURCE_ORDER: tuple[str, ...] = (
    SOURCE_SESSION,
    SOURCE_MESSAGE,
    SOURCE_TOOL_CALL,
    SOURCE_KANBAN,
    SOURCE_SKILL,
    SOURCE_CRON,
    SOURCE_MEMORY,
)

ALL_SOURCES = frozenset(SOURCE_ORDER)

# Kinds are dotted ``<domain>.<what-happened>``. The story engine groups by
# kind, so add kinds deliberately rather than per-adapter whimsy.
KIND_SESSION_STARTED = "session.started"
KIND_SESSION_ENDED = "session.ended"

KIND_MESSAGE_USER = "message.user"
KIND_MESSAGE_ASSISTANT = "message.assistant"
KIND_MESSAGE_TOOL_RESULT = "message.tool_result"
KIND_MESSAGE_META = "message.meta"

KIND_TOOL_CALL = "tool.call"

KIND_TASK_CREATED = "kanban.task.created"
KIND_TASK_STATUS = "kanban.task.status"
KIND_TASK_CLAIMED = "kanban.task.claimed"
KIND_TASK_FINISHED = "kanban.task.finished"
KIND_RUN_STARTED = "kanban.run.started"
KIND_RUN_FINISHED = "kanban.run.finished"

KIND_SKILL_CREATED = "skill.created"
KIND_SKILL_USED = "skill.used"
KIND_SKILL_PATCHED = "skill.patched"
KIND_SKILL_ARCHIVED = "skill.archived"

KIND_CRON_STARTED = "cron.run.started"
KIND_CRON_FINISHED = "cron.run.finished"

KIND_MEMORY_FACT = "memory.fact"
KIND_MEMORY_ADDED = "memory.fact.added"
KIND_MEMORY_REMOVED = "memory.fact.removed"


# --------------------------------------------------------------------------- #
# Content references
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class ContentRef:
    """Where the raw text for an event lives.

    ``store`` is a *logical* name resolved by the adapter (never an absolute
    path, so an event never names an out-of-project path). Adapters expose
    ``fetch_content(ref)`` to materialise the text.
    """

    store: str
    table: str
    pk: str
    column: str = "content"

    def as_dict(self) -> dict[str, str]:
        return {
            "store": self.store,
            "table": self.table,
            "pk": self.pk,
            "column": self.column,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ContentRef":
        return cls(
            store=str(data["store"]),
            table=str(data["table"]),
            pk=str(data["pk"]),
            column=str(data.get("column", "content")),
        )


# --------------------------------------------------------------------------- #
# Event
# --------------------------------------------------------------------------- #


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def make_event_id(
    source: str, kind: str, ts: float, ref: Mapping[str, Any] | None, discriminator: str = ""
) -> str:
    """Deterministic id from the fields that identify the row, not its content."""
    basis = _canonical_json(
        {
            "source": source,
            "kind": kind,
            "ts": round(float(ts), 6),
            "ref": dict(ref or {}),
            "d": discriminator,
        }
    )
    digest = hashlib.blake2b(basis.encode("utf-8"), digest_size=12).hexdigest()
    return f"ev_{digest}"


def text_digest(text: str) -> str:
    """Stable digest for text that must stay out of the event stream."""
    return "sha256:" + hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()[:32]


@dataclass(frozen=True, slots=True)
class Event:
    """One normalised thing that happened, from any source."""

    id: str
    ts: float
    source: str
    kind: str
    profile: str = ""
    actor: str = ""
    subject: str = ""
    payload: Mapping[str, Any] = field(default_factory=dict)
    ref: Mapping[str, str] = field(default_factory=dict)
    content_ref: ContentRef | None = None
    derived_from: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.source not in ALL_SOURCES:
            raise ValueError(f"unknown event source: {self.source!r}")
        if not self.kind:
            raise ValueError("event kind is required")

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "v": SCHEMA_VERSION,
            "id": self.id,
            "ts": round(float(self.ts), 6),
            "source": self.source,
            "kind": self.kind,
            "profile": self.profile,
            "actor": self.actor,
            "subject": self.subject,
            "payload": dict(self.payload),
            "ref": dict(self.ref),
        }
        if self.content_ref is not None:
            out["content_ref"] = self.content_ref.as_dict()
        if self.derived_from:
            out["derived_from"] = list(self.derived_from)
        return out

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Event":
        cref = data.get("content_ref")
        return cls(
            id=str(data["id"]),
            ts=float(data["ts"]),
            source=str(data["source"]),
            kind=str(data["kind"]),
            profile=str(data.get("profile", "")),
            actor=str(data.get("actor", "")),
            subject=str(data.get("subject", "")),
            payload=dict(data.get("payload") or {}),
            ref=dict(data.get("ref") or {}),
            content_ref=ContentRef.from_dict(cref) if cref else None,
            derived_from=tuple(data.get("derived_from") or ()),
        )


def build_event(
    *,
    source: str,
    kind: str,
    ts: float,
    profile: str = "",
    actor: str = "",
    subject: str = "",
    payload: Mapping[str, Any] | None = None,
    store: str = "",
    table: str = "",
    pk: str = "",
    content_column: str | None = "content",
    discriminator: str = "",
    derived_from: Iterable[str] = (),
) -> Event:
    """Convenience constructor that derives the id from the provenance."""
    ref: dict[str, str] = {}
    if store:
        ref["store"] = store
    if table:
        ref["table"] = table
    if pk:
        ref["pk"] = pk
    return Event(
        id=make_event_id(source, kind, ts, ref, discriminator),
        ts=float(ts),
        source=source,
        kind=kind,
        profile=profile,
        actor=actor,
        subject=subject,
        payload=dict(payload or {}),
        ref=ref,
        content_ref=(
            ContentRef(store=store, table=table, pk=pk, column=content_column or "content")
            if content_column and store and table and pk
            else None
        ),
        derived_from=tuple(derived_from),
    )


# --------------------------------------------------------------------------- #
# Serialisation helpers (JSONL: the ingest handoff format)
# --------------------------------------------------------------------------- #


def event_to_jsonl(event: Event) -> str:
    return _canonical_json(event.to_dict())


def iter_jsonl_events(lines: Iterable[str]) -> Iterator[Event]:
    for line in lines:
        line = line.strip()
        if not line:
            continue
        yield Event.from_dict(json.loads(line))


def assert_unique_ids(events: Iterable[Event]) -> int:
    """Guard: duplicate ids mean the provenance/discriminator design is broken."""
    seen: set[str] = set()
    count = 0
    for event in events:
        if event.id in seen:
            raise ValueError(f"duplicate event id: {event.id}")
        seen.add(event.id)
        count += 1
    return count
