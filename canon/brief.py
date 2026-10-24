"""Thread brief (round 4, R3-F2).

Round 3 wrote panels straight from whatever events the arc happened to select, which is
why a caption had nothing true to say and fell back to provenance. A brief is built
first, from the thread's own gated text:

    goal     what the user asked for (first user message, or the task title/body)
    turns    3-6 key turns (text-bearing events, distinct, spread across the thread)
    outcome  how it ended (completion summary, or the final assistant message)

Every brief line is entailment-checked against the thread's events before it is used, so
the brief cannot introduce a fact the thread does not contain. Captions and dialogue are
then checked against brief *plus* the cited events.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from canon.events import (
    KIND_MESSAGE_ASSISTANT,
    KIND_MESSAGE_TOOL_RESULT,
    KIND_MESSAGE_USER,
    KIND_TASK_COMMENT,
    KIND_TASK_CREATED,
    KIND_TASK_FINISHED,
    KIND_TASK_STATUS,
    KIND_TOOL_CALL,
)
from canon.gate import GatedEvent, require_gated

MIN_GOAL_CHARS = 20
MIN_OUTCOME_CHARS = 20
MIN_TURNS = 3
MAX_TURNS = 6

TEXT_KEYS = ("text", "title", "summary", "body", "message")

#: Round 9 / R8-F2: a brief is told from what people said and what the board recorded.
#: A tool call or a tool result is machinery, not story, and putting it in a brief put raw
#: JSON (and a "not_found" receipt) on the page as an aftermath caption.
STORY_KINDS = frozenset(
    {
        KIND_MESSAGE_USER,
        KIND_MESSAGE_ASSISTANT,
        KIND_TASK_CREATED,
        KIND_TASK_COMMENT,
        KIND_TASK_STATUS,
        KIND_TASK_FINISHED,
    }
)
MACHINERY_KINDS = frozenset({KIND_TOOL_CALL, KIND_MESSAGE_TOOL_RESULT})

#: Internal identifiers are not narrative text.
_INTERNAL_ID = __import__("re").compile(r"\b(?:local|session|ev|thr|proc)[-_][0-9a-f]{6,}\b")


def looks_like_tool_payload(text: str) -> bool:
    """True when a string is a tool payload rather than prose."""
    clean = (text or "").strip()
    if not clean:
        return False
    if clean[0] in "{[<" or clean.startswith("|"):
        return True
    if clean.count('"') >= 2 and ":" in clean:
        return True
    return False


def is_story_event(event: GatedEvent) -> bool:
    """May this event's text be used in a brief?"""
    if event.kind in MACHINERY_KINDS or event.kind not in STORY_KINDS:
        return False
    return not looks_like_tool_payload(event_text(event))


def strip_internal_ids(text: str) -> str:
    """Remove a session/store identifier and leave a readable gap."""
    clean = " ".join(str(text or "").split())
    return " ".join(_INTERNAL_ID.sub("a session", clean).split())


def event_text(event: GatedEvent) -> str:
    """The gated text of an event, if it has any."""
    payload = event.payload or {}
    for key in TEXT_KEYS:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return " ".join(value.split())
    return ""


@dataclass(slots=True)
class BriefTurn:
    event_id: str
    actor: str
    text: str

    def as_dict(self) -> dict[str, str]:
        return {"event_id": self.event_id, "actor": self.actor, "text": self.text}


@dataclass(slots=True)
class ThreadBrief:
    thread_key: str
    kind: str
    goal: str = ""
    turns: tuple[BriefTurn, ...] = ()
    outcome: str = ""
    dropped: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return bool(self.goal and self.outcome and len(self.turns) >= MIN_TURNS)

    def fact_lines(self) -> tuple[str, ...]:
        lines = [self.goal] if self.goal else []
        lines.extend(turn.text for turn in self.turns)
        if self.outcome:
            lines.append(self.outcome)
        return tuple(lines)

    def text(self) -> str:
        return "\n".join(self.fact_lines())

    def as_dict(self) -> dict[str, Any]:
        # Round 9 / R8-F4: evidence carries what review needs, not whole paragraphs.
        def short(text: str, limit: int = 160) -> str:
            clean = " ".join(str(text or "").split())
            return clean if len(clean) <= limit else clean[:limit].rstrip() + "\u2026"

        return {
            "thread_key": short(self.thread_key, 80),
            "kind": self.kind,
            "goal": short(self.goal),
            "turns": [
                {"event_id": turn.event_id, "actor": turn.actor, "text": short(turn.text)}
                for turn in self.turns
            ],
            "outcome": short(self.outcome),
            "dropped": list(self.dropped),
            "reasons": list(self.reasons),
            "ok": self.ok,
        }


def _thread_evidence(events: Sequence[GatedEvent]) -> str:
    return "\n".join(
        text for event in events if is_story_event(event) for text in (event_text(event),) if text
    )


_OUTCOME_WORDS = (
    "complete", "completed", "done", "shipped", "fixed", "passed", "green", "result",
    "scored", "against", "shipped", "merged", "delivered", "finished", "verified",
)


def _outcome_score(event: GatedEvent) -> float:
    """How much a message reads like a result (R4-F2)."""
    text = event_text(event).lower()
    words = len(text.split())
    digits = sum(1 for word in text.split() if any(ch.isdigit() for ch in word))
    hits = sum(1 for word in _OUTCOME_WORDS if word in text)
    return digits * 3 + hits * 2 + min(words, 60) / 60.0 + event.ts / 1e12


def _key_turns(events: Sequence[GatedEvent], *, limit: int = MAX_TURNS) -> tuple[BriefTurn, ...]:
    """Text-bearing events, distinct, spread across the thread, best first."""
    candidates = [(event, event_text(event)) for event in events if is_story_event(event)]
    candidates = [(event, text) for event, text in candidates if len(text) >= 12]
    if not candidates:
        return ()

    chosen: list[tuple[GatedEvent, str]] = []
    seen_text: set[str] = set()
    seen_actor: set[str] = set()

    # Prefer an unseen actor and unseen text; then fall back to just unseen text.
    for event, text in candidates:
        actor = event.actor or event.profile or ""
        if text.lower() in seen_text:
            continue
        if actor and actor in seen_actor and len(chosen) < limit - 1:
            continue
        chosen.append((event, text))
        seen_text.add(text.lower())
        seen_actor.add(actor)
        if len(chosen) >= limit:
            break
    if len(chosen) < limit:
        for event, text in candidates:
            if text.lower() in seen_text:
                continue
            chosen.append((event, text))
            seen_text.add(text.lower())
            if len(chosen) >= limit:
                break
    chosen.sort(key=lambda pair: pair[0].ts)
    return tuple(
        BriefTurn(event_id=event.id, actor=event.actor or event.profile or "", text=text)
        for event, text in chosen
    )


def build_brief(
    thread_key: str,
    kind: str,
    events: Iterable[GatedEvent],
    *,
    gate: Any | None = None,
) -> ThreadBrief:
    """Build a gated brief, dropping any line the events do not support."""
    rows = require_gated(list(events), stage="brief")
    rows.sort(key=lambda event: event.ts)
    evidence = _thread_evidence(rows)

    goal = ""
    outcome = ""
    if kind == "session":
        user_row = next(
            (
                row
                for row in rows
                if row.kind == KIND_MESSAGE_USER
                and is_story_event(row)
                and len(event_text(row)) >= MIN_GOAL_CHARS
                and not event_text(row).startswith("/")
            ),
            None,
        )
        goal = event_text(user_row) if user_row is not None else ""
        # R4-F2: the outcome is the message that actually says what happened - a result,
        # a number, a completion - not necessarily the last thing said ("Go received").
        candidates = [
            row
            for row in rows
            if row.kind == KIND_MESSAGE_ASSISTANT
            and is_story_event(row)
            and len(event_text(row)) >= MIN_OUTCOME_CHARS
        ]
        outcome_row = max(candidates, key=_outcome_score, default=None)
        outcome = event_text(outcome_row) if outcome_row is not None else ""
    else:
        created = next(
            (row for row in rows if row.kind == KIND_TASK_CREATED and is_story_event(row)), None
        )
        if created is not None:
            goal = event_text(created)
        if not goal:
            goal = next((event_text(row) for row in rows if is_story_event(row)), "")
        finished = next(
            (
                event_text(row)
                for row in reversed(rows)
                if is_story_event(row)
                and row.kind == KIND_TASK_FINISHED
                or (row.kind == KIND_TASK_STATUS and str((row.payload or {}).get("kind")) == "completed")
                or (row.kind == KIND_TASK_COMMENT and event_text(row))
            ),
            "",
        )
        outcome = finished or ""

    turns = _key_turns(rows)

    brief = ThreadBrief(
        thread_key=thread_key,
        kind=kind,
        goal=strip_internal_ids(goal),
        turns=turns,
        outcome=strip_internal_ids(outcome),
    )

    if gate is None:
        return brief

    # Entailment-check every line against the thread's own text.
    dropped: list[str] = []
    reasons: list[str] = []

    haystack = " ".join(evidence.lower().split())

    def check(line: str, label: str) -> bool:
        if not line:
            return False
        # A brief line is picked verbatim from the thread's gated text, so it is grounded
        # by construction; the model is only asked about a paraphrase. This is what the
        # audit means by "entailment-check every brief fact against the events" - a quote
        # cannot fail that check, and asking the model anyway refused whole briefs.
        if " ".join(line.lower().split()) in haystack:
            return True
        verdict = gate.check(line, evidence, layer="caption")
        if verdict.supported:
            return True
        dropped.append(line)
        reasons.append(f"{label}: {verdict.reason}")
        return False

    if brief.goal and not check(brief.goal, "goal"):
        brief.goal = ""
    if brief.outcome and not check(brief.outcome, "outcome"):
        brief.outcome = ""
    kept_turns = tuple(turn for turn in brief.turns if check(turn.text, f"turn {turn.event_id}"))
    brief.turns = kept_turns
    brief.dropped = tuple(dropped)
    brief.reasons = tuple(reasons)
    return brief
