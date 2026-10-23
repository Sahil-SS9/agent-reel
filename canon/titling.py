"""One cached title call, after grounding (audit M1-F6).

The derived title read "The week default, denji-reviewer, octacon had". A title is a
creative act, so it comes from the model - once, cached, and constrained to the arc's
own grounded material.
"""

from __future__ import annotations

import re
from typing import Any, Sequence

from canon.beats import Beat
from canon.llm import CachedLLM, LLMError

MAX_TITLE_WORDS = 7
MAX_TITLE_CHARS = 60

TITLE_PROMPT = (
    "Give this comic episode one title. It must name what actually happened in the "
    "beats, in at most 7 words, with no invented facts, no quotes and no full stop. "
    'Answer with JSON only: {"title": "..."}.'
)

#: Words a title may use that the beats need not contain: glue and register only.
_ALLOWED = frozenset(
    """
    the a an of and or in on at to for with from by is was are were be been it its
    this that these those a week day night again still back out up down over under
    how why what when where who nobody everyone something nothing one two three
    """.split()
)


def _clean(title: str) -> str:
    text = " ".join(title.split()).strip(" .,:;!?\"'")
    if not text:
        return ""
    words = text.split()
    if len(words) > MAX_TITLE_WORDS:
        text = " ".join(words[:MAX_TITLE_WORDS])
    if len(text) > MAX_TITLE_CHARS:
        text = text[:MAX_TITLE_CHARS].rstrip(" ,;:-")
    return text


def _grounded(title: str, beats: Sequence[Beat]) -> bool:
    """A title may only use words the beats contain, plus glue."""
    haystack = " ".join(beat.summary.lower() for beat in beats)
    for word in re.findall(r"[A-Za-z][A-Za-z'\-]+", title.lower()):
        if len(word) < 3 or word in _ALLOWED:
            continue
        if word not in haystack:
            return False
    return True


def write_title(
    llm: CachedLLM | None,
    *,
    beats: Sequence[Beat],
    derived: str,
    hero: str = "Sahil",
) -> tuple[str, str]:
    """Return (title, source). ``source`` is "model", "derived" or "fallback"."""
    if llm is None:
        return derived, "derived"
    payload = {
        "beats": [beat.summary for beat in beats][:12],
        "hero": hero,
        "derived": derived,
    }
    try:
        response = llm.complete_json(
            prompt=TITLE_PROMPT,
            payload=payload,
            schema_hint={"title": "string"},
            stage="episode.title",
        )
    except LLMError:
        return derived, "fallback"
    candidate = _clean(str(response.get("title", "")))
    if not candidate:
        return derived, "fallback"
    if not _grounded(candidate, beats):
        # A title that invents a word is exactly the M1-F1 failure in miniature.
        return derived, "ungrounded"
    return candidate, "model"
