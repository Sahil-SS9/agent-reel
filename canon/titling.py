"""One cached title call, after grounding (round 3, item 5).

A title is short, carries no redaction marker, and is entailed by the thread's own
evidence. The derived title is the fallback and follows the same rules.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Iterable, Sequence

from canon.beats import Beat
from canon.llm import CachedLLM, LLMError

MAX_TITLE_WORDS = 6
MAX_TITLE_CHARS = 48

TITLE_PROMPT = (
    "Title this comic episode in at most 6 words. It must describe what actually "
    "happened in the beats: no invented place, person, project, number or outcome, no "
    "quotation marks, no full stop. Prefer the thread's own words. "
    'Answer with JSON only: {"title": "..."}.'
)

#: Words a title may use that the beats need not contain: glue and register only.
_ALLOWED = frozenset(
    """
    the a an of and or in on at to for with from by is was are were be been it its
    this that these those one two three a week day night again still back out up down
    how why what when where who nobody everyone something nothing
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
    """A title may only use words the beats contain, plus glue.

    This is the cheap pre-filter; claims are checked separately by the gate.
    """
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
    gate: Any | None = None,
    evidence: str = "",
    alias: Callable[[str], str] | None = None,
) -> tuple[str, str]:
    """Return (title, source). ``source`` is model / derived / fallback / ungrounded."""

    def finish(candidate: str) -> str:
        text = _clean(candidate)
        if alias is not None:
            text = alias(text)
        return text

    derived_clean = finish(derived)

    def acceptable(candidate: str) -> bool:
        if not candidate:
            return False
        if "[REDACTED" in candidate:
            return False  # a title never shows a marker (round 3, item 3)
        if len(candidate.split()) > MAX_TITLE_WORDS:
            return False
        if gate is not None and evidence:
            # A title may compress what happened; it may not claim a name, a number, an
            # outcome or a cause the thread does not contain.
            verdict = gate.check(candidate, evidence, layer="dialogue")
            if not verdict.supported:
                return False
        return _grounded(candidate, beats)

    if llm is None:
        return derived_clean, "derived"

    payload = {
        "beats": [beat.summary for beat in beats][:12],
        "hero": hero,
        "derived": derived_clean,
    }
    try:
        response = llm.complete_json(
            prompt=TITLE_PROMPT,
            payload=payload,
            schema_hint={"title": "string"},
            stage="episode.title",
        )
    except LLMError:
        return derived_clean, "fallback"

    candidate = finish(str(response.get("title", "")))
    if not candidate:
        return derived_clean, "fallback"
    if not acceptable(candidate):
        return derived_clean, "ungrounded"
    return candidate, "model"
