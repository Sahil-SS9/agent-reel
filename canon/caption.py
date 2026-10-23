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
    # "asked" is only ever said of the owner (R4-F1).
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
    cleaned = re.sub(r"https?://\S+", "a link", text or "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    # Drop the conversational lead-in so the object is the thing itself.
    for lead in ("please ", "can you ", "could you ", "i want you to ", "i need "):
        if cleaned.lower().startswith(lead):
            cleaned = cleaned[len(lead):]
            break
    clause = re.split(r"[.;\n]", cleaned.strip(), maxsplit=1)[0]
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


#: Names that must never appear as a character (round 5, R4-F1).
NON_CHARACTERS = frozenset({"assistant", "default", "agent", "the fleet", "user", "owner", ""})

OWNER_ACTOR = "owner"


def _role_of(event: GatedEvent) -> str:
    return str((event.payload or {}).get("role") or "").strip().lower()


def _actor_for(
    event: GatedEvent, *, display: dict[str, str] | None = None, hero: str = "Sahil"
) -> str:
    """Who the event belongs to.

    R4-F1: a user message is the owner's, whatever profile was active, and an assistant
    message is the profile's character - never a tool name and never "Assistant".
    """
    table = display or {}
    if _role_of(event) == "user" or event.actor == OWNER_ACTOR:
        return table.get(OWNER_ACTOR) or hero
    for key in (event.profile, event.actor):
        if not key:
            continue
        mapped = table.get(key)
        if mapped and mapped.strip().lower() not in NON_CHARACTERS:
            return mapped
        clean = str(key).replace("-", " ").title()
        if clean.strip().lower() not in NON_CHARACTERS:
            return clean
    # Never fall back to the owner for someone else's action, and never to "Assistant".
    return "The agent"


def _text_for(event: GatedEvent) -> str:
    payload = event.payload or {}
    for key in ("text", "title", "summary", "body", "message"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return " ".join(value.split())
    return ""


def compose_caption(
    event: GatedEvent, *, display: dict[str, str] | None = None, hero: str = "Sahil"
) -> str:
    """A plain sentence about one event, or '' when there is nothing to say."""
    actor = _actor_for(event, display=display, hero=hero)
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


# --------------------------------------------------------------------------- #
# Caption policy (round 5, R4-F2)
# --------------------------------------------------------------------------- #
#
# A caption paraphrases a fact from the brief in at most 20 words and never quotes the
# owner's own message beyond 8 words. The owner's raw text is his, not the comic's.

MAX_CAPTION_WORDS = 20
MAX_OWNER_QUOTE_WORDS = 8

_STOP = frozenset(
    "the a an and or of to in on at for with from by is was are were be been it its this "
    "that these those i you he she we they my your his her our their as so but if then".split()
)


def _words(text: str) -> list[str]:
    import re as _re

    return [w for w in _re.findall(r"[a-z0-9']+", (text or "").lower())]


def longest_common_run(caption: str, source: str) -> int:
    """Longest run of consecutive words shared by a caption and a source text."""
    left, right = _words(caption), _words(source)
    if not left or not right:
        return 0
    best = 0
    previous = [0] * (len(right) + 1)
    for i in range(1, len(left) + 1):
        current = [0] * (len(right) + 1)
        for j in range(1, len(right) + 1):
            if left[i - 1] == right[j - 1]:
                current[j] = previous[j - 1] + 1
                best = max(best, current[j])
        previous = current
    return best


#: The template shapes the audit refuses: "Sahil asked for ...", "Kensei reported ...".
TEMPLATE_OPENING = re.compile(
    r"^\s*[A-Z][\w'\-]*(?:\s+[A-Z][\w'\-]*){0,2}\s+"
    r"(?:asked(?:\s+for)?|reported|worked\s+on)\b",
    re.IGNORECASE,
)


def caption_problem(
    caption: str,
    *,
    owner_texts: list[str] | tuple[str, ...] = (),
    max_words: int = MAX_CAPTION_WORDS,
    max_owner_quote: int = MAX_OWNER_QUOTE_WORDS,
) -> str:
    """Why this caption is not acceptable ('' when it is).

    Every caption path - the model's paraphrase, a composed sentence, a trimmed variant,
    the template fallback - goes through this one function (R5-F2).
    """
    text = " ".join((caption or "").split())
    if not text:
        return "empty"
    if len(text.split()) > max_words:
        return f"over {max_words} words ({len(text.split())})"
    if looks_like_provenance(text):
        return "provenance"
    if TEMPLATE_OPENING.match(text):
        return "template opening (asked for / reported)"
    for source in owner_texts:
        if longest_common_run(text, source) > max_owner_quote:
            return f"quotes the owner for more than {max_owner_quote} words"
    return ""


def trim_caption(caption: str, *, max_words: int = MAX_CAPTION_WORDS) -> str:
    """Cut a caption to the policy length on a word boundary, keeping the sentence."""
    words = " ".join((caption or "").split()).split()
    if len(words) <= max_words:
        return " ".join(words)
    return " ".join(words[:max_words]).rstrip(" ,;:") + "."
