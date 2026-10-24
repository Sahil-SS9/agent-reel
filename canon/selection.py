"""Story selection by meaning (round 4, R3-F1).

Round 3 picked whichever thread had the strongest blocked -> completed shape. That is
fleet bookkeeping: review gates, triage, dispatcher give-ups and "Needs Sahil's
decision" cards win the ranking while the week's real work never reaches the page.

A story is a session where the user stated a goal and something came of it, or a task
family whose title describes real work. Governance and admin plumbing is never a story;
it may still appear as a detail inside a real one.

Ranking is by user involvement, a clear outcome, and size - in that order.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from canon.events import (
    KIND_MESSAGE_ASSISTANT,
    KIND_MESSAGE_USER,
    KIND_TASK_COMMENT,
    KIND_TASK_CREATED,
    KIND_TASK_FINISHED,
    KIND_TASK_STATUS,
)
from canon.gate import GatedEvent, require_gated

#: Bookkeeping, not story. Matched against a title, goal or outcome line.
PLUMBING_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"needs? (sahil'?s?|your|human) (decision|approval|input)",
        r"\btriage\b",
        r"\breview gate\b",
        r"\bgovernance(-guard)?\b",
        r"\bdispatcher?\b",
        r"\bgave[ _]up\b",
        r"\bretry|retries\b",
        r"\bblock[- ]loop\b",
        r"missing required (contract )?sections",
        r"^\s*(blocked|unblocked|claimed|completed|finished|created|todo|ready)\s*$",
        r"^\s*t_[0-9a-f]{6,}\s*",
    )
)

#: A title must carry at least this many content words to be real work.
MIN_TITLE_WORDS = 3

_ID_ONLY = re.compile(r"^\s*t_[0-9a-f]{4,}\s*$")


def is_plumbing(text: str) -> bool:
    """True when the line is fleet bookkeeping rather than work."""
    candidate = " ".join((text or "").split())
    if not candidate:
        return True
    if _ID_ONLY.match(candidate):
        return True
    return any(pattern.search(candidate) for pattern in PLUMBING_PATTERNS)


#: A result a story can end on. A number alone is not a result, and neither is a receipt.
_RESULT_CUES = {
    "beats", "beat", "beaten", "passed", "passes", "green", "finished", "complete",
    "completed", "merged", "shipped", "landed", "fixed", "verified", "measured", "scored",
    "tied", "ties", "failed", "fails", "worse", "better", "improved", "reduced",
}
#: Receipts and acknowledgements that arrive as the last assistant message.
_RECEIPT = re.compile(
    r"^(go received|okay|ok|done|thanks|received|acknowledged|noted)\.?$", re.IGNORECASE
)
_BOILERPLATE = re.compile(r"background process|exit code|\[important:", re.IGNORECASE)


def is_substantive_outcome(text: str) -> bool:
    """Does this outcome say what the work actually produced?

    Round 8 / R8-3: a long conversation must not outrank a finished result, and a two-word
    receipt must not count as one. Numbers alone are not enough - a result needs a verb of
    completion or comparison, applied to something.
    """
    clean = " ".join(str(text or "").split())
    if len(clean) < 20 or _RECEIPT.match(clean) or _BOILERPLATE.search(clean):
        return False
    words = {
        word.strip(".,;:!?()[]\"'\u2014-").lower() for word in clean.split()
    }
    if not words & _RESULT_CUES:
        return False
    # "passed" alone on a receipt is not a result; it needs some substance around it.
    return len([word for word in words if len(word) > 3]) >= 4


def _content_words(text: str) -> int:
    return len([word for word in re.findall(r"[A-Za-z][A-Za-z'\-]+", text or "") if len(word) > 2])


def describes_real_work(title: str) -> bool:
    return not is_plumbing(title) and _content_words(title) >= MIN_TITLE_WORDS


def _event_text(event: GatedEvent) -> str:
    payload = event.payload or {}
    for key in ("text", "title", "summary", "body", "message"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return " ".join(value.split())
    return ""


@dataclass(slots=True)
class StoryCandidate:
    """One possible story, before ranking."""

    kind: str  # session | task
    key: str
    title: str = ""
    goal: str = ""
    outcome: str = ""
    user_turns: int = 0
    text_chars: int = 0
    event_ids: tuple[str, ...] = ()
    excluded: str = ""

    @property
    def eligible(self) -> bool:
        if self.excluded:
            return False
        if not self.goal or not self.outcome:
            return False
        return not is_plumbing(self.title or self.goal)

    @property
    def score(self) -> tuple[int, int, int, int]:
        """A substantive result first, then user involvement, text, size.

        Round 8 / R8-3: length is a tie-breaker, not a reason to tell a story. A finished
        result - qualitative or measured - outranks a long conversation about nothing.
        """
        return (
            1 if is_substantive_outcome(self.outcome) else 0,
            self.user_turns,
            self.text_chars,
            len(self.event_ids),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "key": self.key,
            "title": self.title,
            "goal": self.goal[:160],
            "outcome": self.outcome[:160],
            "user_turns": self.user_turns,
            "text_chars": self.text_chars,
            "events": len(self.event_ids),
            "eligible": self.eligible,
            "excluded": self.excluded,
            "score": list(self.score),
        }


def _session_candidates(events: Sequence[GatedEvent]) -> list[StoryCandidate]:
    grouped: dict[str, list[GatedEvent]] = {}
    for event in events:
        if event.kind not in {KIND_MESSAGE_USER, KIND_MESSAGE_ASSISTANT}:
            continue
        payload = event.payload or {}
        key = str(payload.get("session_id") or event.subject or "")
        if not key:
            continue
        grouped.setdefault(key, []).append(event)

    out: list[StoryCandidate] = []
    for key, rows in grouped.items():
        rows.sort(key=lambda event: event.ts)
        user_rows = [row for row in rows if row.kind == KIND_MESSAGE_USER and _event_text(row)]
        assistant_rows = [
            row for row in rows if row.kind == KIND_MESSAGE_ASSISTANT and _event_text(row)
        ]
        candidate = StoryCandidate(
            kind="session",
            key=key,
            event_ids=tuple(row.id for row in rows),
            user_turns=len(user_rows),
            text_chars=sum(len(_event_text(row)) for row in rows),
        )
        if user_rows:
            # The goal is the first thing the user actually asked for.
            first = next(
                (row for row in user_rows if len(_event_text(row)) >= 20 and not _event_text(row).startswith("/")),
                user_rows[0],
            )
            candidate.goal = _event_text(first)
            candidate.title = candidate.goal[:80]
        if assistant_rows:
            candidate.outcome = _event_text(assistant_rows[-1])
        if not candidate.goal:
            candidate.excluded = "no user goal"
        elif not candidate.outcome:
            candidate.excluded = "no outcome"
        elif is_plumbing(candidate.goal) or is_plumbing(candidate.outcome):
            candidate.excluded = "plumbing"
        out.append(candidate)
    return out


def _task_candidates(events: Sequence[GatedEvent]) -> list[StoryCandidate]:
    grouped: dict[str, list[GatedEvent]] = {}
    for event in events:
        if event.kind not in {KIND_TASK_CREATED, KIND_TASK_STATUS, KIND_TASK_FINISHED, KIND_TASK_COMMENT}:
            continue
        payload = event.payload or {}
        key = str(payload.get("task_id") or event.subject or "")
        if not key:
            continue
        grouped.setdefault(key, []).append(event)

    out: list[StoryCandidate] = []
    for key, rows in grouped.items():
        rows.sort(key=lambda event: event.ts)
        texts = [(row, _event_text(row)) for row in rows]
        title = next((text for row, text in texts if row.kind == KIND_TASK_CREATED and text), "")
        if not title:
            title = next((text for _row, text in texts if text), "")
        candidate = StoryCandidate(
            kind="task",
            key=key,
            title=title,
            goal=title,
            event_ids=tuple(row.id for row in rows),
            user_turns=sum(1 for _row, text in texts if text),
            text_chars=sum(len(text) for _row, text in texts),
        )
        completed = next(
            (
                text
                for row, text in reversed(texts)
                if row.kind == KIND_TASK_FINISHED
                or (str((row.payload or {}).get("kind")) == "completed")
            ),
            "",
        )
        candidate.outcome = completed or next(
            (text for _row, text in reversed(texts) if text), ""
        )
        if not title:
            candidate.excluded = "no title"
        elif not describes_real_work(title):
            candidate.excluded = "plumbing or not real work"
        elif not candidate.outcome:
            candidate.excluded = "no outcome"
        out.append(candidate)
    return out


def build_candidates(events: Iterable[GatedEvent]) -> list[StoryCandidate]:
    gated = require_gated(list(events), stage="selection")
    return _session_candidates(gated) + _task_candidates(gated)


def rank_candidates(candidates: Sequence[StoryCandidate]) -> list[StoryCandidate]:
    """Best first, using the same score the selector uses."""
    return sorted(candidates, key=lambda candidate: candidate.score, reverse=True)


def select_stories(
    events: Iterable[GatedEvent], *, limit: int = 3
) -> tuple[list[StoryCandidate], list[StoryCandidate]]:
    """Return (selected, all_candidates) ordered best first."""
    candidates = build_candidates(events)
    eligible = sorted(
        (candidate for candidate in candidates if candidate.eligible),
        key=lambda candidate: candidate.score,
        reverse=True,
    )
    return eligible[:limit], candidates
