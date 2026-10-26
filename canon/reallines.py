"""Real lines: the best things people actually said, offered to the script writer.

A comic that retells real work has better dialogue lying around than any model will invent:
the owner's blunt, dry, impatient messages. This module finds the short, punchy sentences in
the gated text of a panel's own messages and hands them to the writer as *candidates*.

- **Verbatim.** A candidate is a sentence taken unchanged from a message, so it is grounded by
  construction: the event that holds it states it.
- **Already redacted.** The text comes from the gated payload, never from raw history.
- **Candidates, not lines.** The writer may use one, or not. Whatever it writes still goes
  through the grounding gate like any other line.
- **No code, no plumbing.** Sentences with paths, hashes, ids, jargon, code fences, links or
  redaction masks are skipped, so a real line reads like something a person says.

Pure text, no I/O.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from canon.aliases import masks_in
from canon.caption import looks_like_provenance
from canon.story import jargon_problem

MAX_CHARS = 90
MIN_WORDS = 3
MAX_WORDS = 16
PER_PANEL = 3
#: A sentence must earn at least this much to be offered. Flat statements score 0 or 1.
MIN_SCORE = 2

_FENCE = re.compile(r"```.*?```", re.DOTALL)
_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")
_BULLET = re.compile(r"^\s*(?:[-*•>]+|\d+[.)])\s+")
_NOISE = re.compile(r"[`{}|<>]|https?://|www\.|=>|->|\\\\")
_SECOND_PERSON = re.compile(r"\b(you|your|we|let's|lets|us|our)\b", re.IGNORECASE)
_STANCE = re.compile(
    r"\b(why|how bad|not again|finally|stop|wait|seriously|really|never|always|prove|wrong|"
    r"broken|please|sorry|thanks|brilliant|great|terrible|awful|hate|love|worry|worried|"
    r"surprised|obviously|actually|honestly|fine|enough|again|still|already|nothing|everything)\b",
    re.IGNORECASE,
)
#: Assistant filler and tool narration: never a good line.
_FILLER_OPENER = re.compile(
    r"^\s*(here'?s|here is|i'll|i will|i've|i have|let me|now i|now let|sure|okay,? so|"
    r"great,? (so|i)|next,? i|first,? i|done\b|got it\b|understood\b|summary\b|note:)",
    re.IGNORECASE,
)


def _clean(text: str) -> str:
    text = _FENCE.sub(" ", text or "")
    return text


def sentences(text: str) -> list[str]:
    """The candidate sentences of a message, in order: no code, bullets stripped."""
    out: list[str] = []
    for chunk in _SPLIT.split(_clean(text)):
        sentence = _BULLET.sub("", chunk).strip(" \t\"'“”")
        sentence = " ".join(sentence.split())
        if sentence:
            out.append(sentence)
    return out


def usable(sentence: str, *, max_chars: int = MAX_CHARS) -> bool:
    """Short, human, and free of anything that is not speech."""
    words = sentence.split()
    if not (MIN_WORDS <= len(words) <= MAX_WORDS) or len(sentence) > max_chars:
        return False
    if sentence.endswith(":") or _NOISE.search(sentence):
        return False
    return not (masks_in(sentence) or looks_like_provenance(sentence) or jargon_problem(sentence))


def punch(sentence: str) -> int:
    """How much a sentence sounds like a person with a point of view (0 = a flat statement)."""
    score = 0
    if sentence.endswith("?"):
        score += 2
    if sentence.endswith("!"):
        score += 2
    if _SECOND_PERSON.search(sentence):
        score += 1
    if _STANCE.search(sentence):
        score += 1
    if len(sentence) <= 60:
        score += 1
    if _FILLER_OPENER.match(sentence):
        score -= 3
    return score


def candidates(text: str, *, max_chars: int = MAX_CHARS, limit: int = PER_PANEL) -> list[str]:
    """The punchiest usable sentences of one message, best first (ties keep reading order)."""
    scored: list[tuple[int, int, str]] = []
    seen: set[str] = set()
    for position, sentence in enumerate(sentences(text)):
        key = sentence.lower()
        if key in seen or not usable(sentence, max_chars=max_chars):
            continue
        seen.add(key)
        score = punch(sentence)
        if score >= MIN_SCORE:
            scored.append((-score, position, sentence))
    scored.sort()
    return [sentence for _score, _position, sentence in scored[:limit]]


def real_lines_for(
    event_ids: Iterable[str],
    quotes_by_event: Mapping[str, str],
    actors_by_event: Mapping[str, str],
    speakers: Sequence[str],
    *,
    owner: str = "",
    limit: int = PER_PANEL,
) -> list[dict[str, Any]]:
    """Candidates for one panel: what the panel's own speakers really said in its events.

    The owner's lines come first, because they are the ones a reader wants to hear.
    """
    allowed = {name for name in speakers if name}
    found: list[dict[str, Any]] = []
    seen: set[str] = set()
    for event_id in event_ids:
        speaker = str(actors_by_event.get(event_id, "")).strip()
        if not speaker or speaker not in allowed:
            continue
        for text in candidates(str(quotes_by_event.get(event_id, "")), limit=limit):
            key = text.lower()
            if key in seen:
                continue
            seen.add(key)
            found.append({"speaker": speaker, "text": text, "event_id": event_id})
    found.sort(key=lambda row: 0 if owner and row["speaker"] == owner else 1)
    return found[:limit]


__all__ = ("candidates", "punch", "real_lines_for", "sentences", "usable")
