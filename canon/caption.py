"""Captions from structured facts, never provenance (round 4, R3-F4).

The round 3 caption repair quoted the evidence, and for a kanban event the evidence began
``event: kanban.task.status gave_up octacon octacon {"failures": 2 ...}``. That is a
record dump, not a sentence a reader can follow.

A caption is now composed from structure - actor, action, object, status - and dropped
when there is nothing to say. A caption never contains ``event:``, a ``key=value`` dump,
a UUID or a bare task id.
"""

from __future__ import annotations

import re

from canon.events import (
    KIND_CRON_FINISHED,
    KIND_MESSAGE_ASSISTANT,
    KIND_MESSAGE_USER,
    KIND_TASK_CLAIMED,
    KIND_TASK_COMMENT,
    KIND_TASK_CREATED,
    KIND_TASK_FINISHED,
    KIND_TASK_STATUS,
    KIND_TOOL_CALL,
)
from canon.gate import GatedEvent

#: action word per status, then per event kind.
STATUS_VERBS: dict[str, str] = {
    "created": "opened",
    "claimed": "took on",
    "spawned": "spawned",
    "specified": "specified",
    "decomposed": "broke down",
    "dependency_wait": "waited on",
    "unblocked": "unblocked",
    "blocked": "was blocked on",
    "block_loop_detected": "looped on",
    "gave_up": "gave up on",
    "review_requested": "sent for review",
    "completed": "completed",
    "finished": "finished",
}

KIND_VERBS: dict[str, str] = {
    KIND_TASK_CREATED: "opened",
    KIND_TASK_CLAIMED: "took on",
    KIND_TASK_STATUS: "moved",
    KIND_TASK_FINISHED: "completed",
    KIND_TASK_COMMENT: "noted",
    KIND_MESSAGE_USER: "asked for",
    KIND_MESSAGE_ASSISTANT: "reported",
    KIND_TOOL_CALL: "ran",
    KIND_CRON_FINISHED: "finished",
}

#: Anything that makes a line a record dump rather than a sentence.
PROVENANCE = re.compile(
    r"(event:\s|\bkind=|task_id=|\{[^{}]*\}|\bt_[0-9a-f]{6,}|\bev_[0-9a-f]{8,}|\bsession_id=)",
    re.IGNORECASE,
)

MAX_OBJECT_WORDS = 10


def looks_like_provenance(text: str) -> bool:
    return bool(PROVENANCE.search(text or ""))


def _object_from(text: str) -> str:
    """The first clause of a text, short enough to be an object."""
    clause = re.split(r"[.;\n]", " ".join((text or "").split()), maxsplit=1)[0]
    clause = clause.strip(" ,:-\u2014")
    words = clause.split()
    if len(words) > MAX_OBJECT_WORDS:
        clause = " ".join(words[:MAX_OBJECT_WORDS])
    return clause


def _verb_for(event: GatedEvent) -> str:
    status = ""
    if event.kind in {KIND_TASK_STATUS, KIND_TASK_FINISHED}:
        status = str((event.payload or {}).get("kind") or "").strip().lower()
    return STATUS_VERBS.get(status) or KIND_VERBS.get(event.kind, "worked on")


def _actor_for(event: GatedEvent) -> str:
    for value in (event.actor, event.profile):
        if value and value not in {"default"}:
            return str(value).replace("-", " ").title()
    return "The fleet"


def _text_for(event: GatedEvent) -> str:
    payload = event.payload or {}
    for key in ("text", "title", "summary", "body", "message"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return " ".join(value.split())
    return ""


def compose_caption(event: GatedEvent) -> str:
    """A plain sentence about one event, or '' when there is nothing to say."""
    actor = _actor_for(event)
    verb = _verb_for(event)
    text = _text_for(event)
    obj = _object_from(text) if text else ""

    if obj.startswith(actor):
        sentence = f"{obj[0].upper()}{obj[1:]}."
    elif obj:
        sentence = f"{actor} {verb} {obj}."
    else:
        sentence = f"{actor} {verb}."
    sentence = re.sub(r"\s+", " ", sentence).strip()
    if looks_like_provenance(sentence):
        return ""
    if len(sentence.split()) < 3:
        return ""
    return sentence


def compose_from_parts(
    *, actor: str, action: str, obj: str = "", status: str = ""
) -> str:
    """The same rule for structured fields a caller already holds."""
    verb = STATUS_VERBS.get((status or "").strip().lower()) or (action or "").strip()
    who = (actor or "The fleet").replace("-", " ").title()
    thing = _object_from(obj) if obj else ""
    sentence = f"{who} {verb} {thing}." if thing else f"{who} {verb}."
    sentence = re.sub(r"\s+", " ", sentence).strip()
    if looks_like_provenance(sentence) or len(sentence.split()) < 3:
        return ""
    return sentence
