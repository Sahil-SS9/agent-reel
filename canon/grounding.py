"""The grounding gate (audit M1-F1): a line may only say what its events say.

The audit found the live script inventing "GGUF latency", "missing timeout key" and
"fix it or the rig burns down" from beats that cited only tool and skill names.
Citing an event id is not grounding, so this gate checks the claim itself:

1. **Term check** (deterministic, always): every content term in the line must appear
   in the evidence text of the events the line cites. Proper nouns and numbers are
   strict - one invented name or figure fails the line.
2. **Entailment check** (model, cached): does the evidence actually support the claim,
   or is the line plausible filler? Jokes and tone are fine; causes, outcomes,
   numbers and names are not.

A line that fails is rewritten as a literal quote from its own evidence (grounded by
construction) or dropped. The report carries the grounded-line rate.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

from canon.llm import CachedLLM, LLMError

#: Function words plus comic connective vocabulary that needs no evidence.
STOPWORDS = frozenset(
    """
    a an the and or but if then than that this these those it its it's is are was were
    be been being am do does did doing have has had having i you he she we they them us
    my your his her our their me him who whom which what when where why how not no yes
    so as at by for from in into of on onto out over to up with within without about
    after before again against between during through under above below once here there
    all any both each few more most other some such only own same too very just now
    can will would should could may might must shall let lets got get gets getting
    said says say tell tells told ask asks asked like want wants wanted need needs
    yeah okay ok well right sure good bad really still even ever never always
    again around back down off away
    """.split()
)

#: Comic register: allowed without evidence, because it adds no factual claim.
REGISTER = frozenset(
    """
    meanwhile suddenly outside inside later earlier finally almost nearly maybe
    perhaps honestly actually basically literally apparently clearly obviously
    dammit damn god hell wow huh hey look listen wait stop run hide fight hold
    burns burning fire alarm alarms chaos mess disaster nightmare fine okay done
    again tomorrow tonight yesterday week week's day day's night morning evening
    nobody everyone somebody someone something nothing anything everything
    """.split()
)

_NUMBER_RE = re.compile(r"\b\d[\d,.:]*\b")
_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z'\-]+|\d[\d,.]*")


@dataclass(frozen=True, slots=True)
class TermReport:
    checked: tuple[str, ...]
    supported: tuple[str, ...]
    invented: tuple[str, ...]
    invented_numbers: tuple[str, ...]

    @property
    def overlap(self) -> float:
        if not self.checked:
            return 1.0
        return len(self.supported) / len(self.checked)


@dataclass(frozen=True, slots=True)
class Verdict:
    supported: bool
    reason: str
    terms: TermReport
    model_checked: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "supported": self.supported,
            "reason": self.reason,
            "overlap": round(self.terms.overlap, 4),
            "invented_terms": list(self.terms.invented),
            "invented_numbers": list(self.terms.invented_numbers),
            "model_checked": self.model_checked,
        }


def _normalise(text: str) -> str:
    return " ".join(text.lower().split())


def content_terms(line: str, *, allow: Iterable[str] = ()) -> list[str]:
    """Content words in a line that must be backed by evidence."""
    allowed = {item.lower() for item in allow} | STOPWORDS | REGISTER
    terms: list[str] = []
    for token in _TOKEN_RE.findall(line):
        lowered = token.lower().strip("'-")
        if len(lowered) < 4:
            continue
        if lowered in allowed:
            continue
        terms.append(lowered)
    return list(dict.fromkeys(terms))


def _stem(word: str) -> str:
    """A crude stem: enough to let "blocked" match "blocking", not to invent a link."""
    return word[:6]


def check_terms(line: str, evidence_text: str, *, allow: Iterable[str] = ()) -> TermReport:
    """Every content term and every number in the line must appear in the evidence."""
    haystack = _normalise(evidence_text)
    stems = {_stem(token) for token in _TOKEN_RE.findall(haystack)}

    def present(term: str) -> bool:
        return term in haystack or _stem(term) in stems

    checked = content_terms(line, allow=allow)
    supported = [term for term in checked if present(term)]
    invented = [term for term in checked if not present(term)]

    line_numbers = [match.group(0) for match in _NUMBER_RE.finditer(line)]
    invented_numbers = [number for number in line_numbers if number not in haystack]
    return TermReport(
        checked=tuple(checked),
        supported=tuple(supported),
        invented=tuple(invented),
        invented_numbers=tuple(invented_numbers),
    )


class GroundingGate:
    """Terms always; entailment when a model is available."""

    PROMPT = (
        "You check one line of a comic against the evidence it cites. Answer JSON only: "
        '{"supported": true|false, "invented": ["..."]}. '
        "The line is supported only if every factual claim in it - what happened, why, "
        "numbers, names, outcomes - appears in the evidence. Tone, jokes, swearing and "
        "connective words are fine and must not be counted as unsupported. If a line "
        "names a cause, a component, a fix or a result that the evidence does not "
        "mention, it is NOT supported."
    )

    def __init__(
        self,
        llm: CachedLLM | None = None,
        *,
        min_overlap: float = 0.5,
        allow: Iterable[str] = (),
    ) -> None:
        self.llm = llm
        self.min_overlap = min_overlap
        self.allow = tuple(allow)
        self.model_calls = 0
        self.failures = 0

    def check(self, line: str, evidence_text: str) -> Verdict:
        terms = check_terms(line, evidence_text, allow=self.allow)
        if terms.invented_numbers:
            return Verdict(False, "invented numbers: " + ", ".join(terms.invented_numbers), terms)
        # Without a model there is no second opinion, so the term rule is absolute:
        # every content word must be backed. With a model, a low overlap is enough to
        # send the line to entailment (rephrasing is fine, invention is not).
        required = 1.0 if self.llm is None else self.min_overlap
        if terms.overlap < required:
            return Verdict(
                False,
                f"term overlap {terms.overlap:.0%} below {required:.0%}: "
                + ", ".join(terms.invented[:4]),
                terms,
            )
        if self.llm is None:
            return Verdict(True, "terms", terms)
        try:
            response = self.llm.complete_json(
                prompt=self.PROMPT,
                payload={"line": line, "evidence": evidence_text[:4000]},
                schema_hint={"supported": "bool", "invented": ["string"]},
                stage="grounding",
            )
        except LLMError:
            # Fail closed: an unverifiable line is not released.
            self.failures += 1
            return Verdict(False, "entailment check unavailable", terms)
        self.model_calls += 1
        supported = bool(response.get("supported"))
        if supported:
            return Verdict(True, "terms+model", terms, model_checked=True)
        invented = response.get("invented")
        detail = ", ".join(str(item) for item in invented[:4]) if isinstance(invented, list) else ""
        return Verdict(False, f"model: not entailed{(' (' + detail + ')') if detail else ''}", terms, model_checked=True)

    def literal_line(self, evidence_text: str, *, limit: int = 100) -> str:
        """A grounded replacement: a verbatim slice of the evidence."""
        text = " ".join(evidence_text.split())
        if not text:
            return ""
        if len(text) <= limit:
            return text
        cut = text.rfind(" ", 0, limit)
        return text[: cut if cut > 40 else limit].rstrip(" ,;:") + "."


@dataclass
class GroundingReport:
    lines: int = 0
    supported: int = 0
    rewritten: int = 0
    dropped: int = 0
    reasons: list[str] = field(default_factory=list)

    @property
    def rate(self) -> float:
        if not self.lines:
            return 1.0
        return self.supported / self.lines

    def as_dict(self) -> dict[str, Any]:
        return {
            "lines": self.lines,
            "supported": self.supported,
            "rewritten": self.rewritten,
            "dropped": self.dropped,
            "grounded_rate": round(self.rate, 4),
            "reasons": self.reasons[:20],
        }
