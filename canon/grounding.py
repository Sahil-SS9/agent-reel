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

    # A multi-word allowlisted name ("The Reviewer", "Project Lantern") must also cover
    # its own words, or a caption that uses the alias looks ungrounded.
    allowed_words = {
        word
        for entry in allow
        for word in str(entry).lower().replace("-", " ").split()
    }

    def present(term: str) -> bool:
        return term in haystack or _stem(term) in stems or term in allowed_words

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
    """Counters for both layers (round 3, item 1)."""

    # captions (narrator facts)
    captions: int = 0
    captions_supported: int = 0
    captions_repaired: int = 0
    # dialogue
    lines: int = 0
    lines_supported: int = 0
    lines_converted: int = 0
    lines_dropped: int = 0
    reasons: list[str] = field(default_factory=list)

    @property
    def rate(self) -> float:
        total = self.captions + self.lines
        if not total:
            return 1.0
        return (self.captions_supported + self.lines_supported) / total

    def as_dict(self) -> dict[str, Any]:
        return {
            "captions": self.captions,
            "captions_supported": self.captions_supported,
            "captions_repaired": self.captions_repaired,
            "lines": self.lines,
            "lines_supported": self.lines_supported,
            "lines_converted": self.lines_converted,
            "lines_dropped": self.lines_dropped,
            "grounded_rate": round(self.rate, 4),
            "reasons": self.reasons[:20],
        }


# --------------------------------------------------------------------------- #
# Claim-level grounding (round 3, item 1)
# --------------------------------------------------------------------------- #
#
# Word overlap is what forced r2 into literal quotes: every content word had to appear
# in the evidence, so only a quote could pass. A claim gate asks a narrower and more
# useful question - is anything in this line *capable of being wrong* - and checks only
# that:
#
#   name    a proper noun (person, project, client, tool, alias)
#   number  a figure, count, time or amount
#   outcome a stated result (fixed, broke, completed, gave up, passed, shipped)
#   cause   a stated reason (because, due to, so that, caused, after ... so)
#
# Names and numbers are checked against the evidence text; outcomes and causes need the
# model, because whether "it broke *because* X" is supported is a reading question. A
# line with no claims (emotion, banter, reaction) passes: there is nothing to be wrong.

CAUSE_WORDS = ("because", "due to", "so that", "caused", "as a result", "which is why")
OUTCOME_WORDS = (
    "fixed", "broke", "broken", "completed", "failed", "gave up", "passed", "shipped",
    "merged", "cancelled", "resolved", "reopened", "lost", "won", "found", "deleted",
    "restored", "throttled", "crashed", "timed out", "timeout",
)
_PROPER_RE = re.compile(r"\b(?:[A-Z][a-z]{1,20})(?:\s+[A-Z][a-z]{1,20}){0,2}\b")
_TECHNICAL_RE = re.compile(r"[A-Za-z0-9_]*[_./][A-Za-z0-9_./]*")


@dataclass(frozen=True, slots=True)
class Claim:
    kind: str  # name | number | outcome | cause
    text: str

    def as_dict(self) -> dict[str, str]:
        return {"kind": self.kind, "text": self.text}


@dataclass(frozen=True, slots=True)
class ClaimReport:
    claims: tuple[Claim, ...]
    unbacked: tuple[Claim, ...]

    @property
    def clean(self) -> bool:
        return not self.unbacked

    @property
    def needs_model(self) -> bool:
        return any(claim.kind in {"cause", "outcome"} for claim in self.claims)

    def as_dict(self) -> dict[str, Any]:
        return {
            "claims": [claim.as_dict() for claim in self.claims],
            "unbacked": [claim.as_dict() for claim in self.unbacked],
        }


def extract_claims(line: str, *, allow: Iterable[str] = ()) -> tuple[Claim, ...]:
    """Everything in the line that could be wrong."""
    allowed = {item.lower() for item in allow} | STOPWORDS | REGISTER
    claims: list[Claim] = []
    seen: set[tuple[str, str]] = set()

    def add(kind: str, text: str) -> None:
        key = (kind, text.lower())
        if key not in seen:
            seen.add(key)
            claims.append(Claim(kind, text))

    lowered = " ".join(line.lower().split())
    for word in CAUSE_WORDS:
        if word in lowered:
            add("cause", word)
    for word in OUTCOME_WORDS:
        if re.search(rf"\b{re.escape(word)}\b", lowered):
            add("outcome", word)
    for match in _NUMBER_RE.finditer(line):
        add("number", match.group(0))
    for match in _PROPER_RE.finditer(line):
        token = " ".join(match.group(0).split())
        if token.lower() in allowed or _TECHNICAL_RE.search(token):
            continue
        # A capitalised first word is a sentence start, not a claim.
        if match.start() == 0 and len(token.split()) == 1:
            continue
        add("name", token)
    return tuple(claims)


def check_claims(line: str, evidence_text: str, *, allow: Iterable[str] = ()) -> ClaimReport:
    """Names and numbers must appear in the evidence; causes and outcomes need a model."""
    haystack = " ".join((evidence_text or "").lower().split())
    claims = extract_claims(line, allow=allow)
    unbacked = [
        claim
        for claim in claims
        if claim.kind in {"name", "number"} and claim.text.lower() not in haystack
    ]
    return ClaimReport(claims=claims, unbacked=tuple(unbacked))


class ClaimVerdict:
    """A claim verdict (kept separate so the legacy term verdict can stay as it was)."""

    def __init__(
        self,
        supported: bool,
        reason: str,
        claims: ClaimReport,
        *,
        model_checked: bool = False,
    ) -> None:
        self.supported = supported
        self.reason = reason
        self.claims = claims
        self.model_checked = model_checked

    def as_dict(self) -> dict[str, Any]:
        return {
            "supported": self.supported,
            "reason": self.reason,
            "model_checked": self.model_checked,
            **self.claims.as_dict(),
        }


class ClaimGate:
    """Two-layer grounding: captions strict, dialogue claim-checked."""

    PROMPT = (
        "You check one line of a comic against the evidence it cites. "
        'Answer JSON only: {"supported": true|false, "unbacked": ["..."]}. '
        "A line is supported only if every factual claim in it - what happened, why, a "
        "number, a name, an outcome, a tool - appears in the evidence. Tone, emotion, "
        "jokes, swearing, metaphor and reaction are NOT claims: a line that only reacts "
        "is supported. A line that states a cause, an outcome, a fix, a component or a "
        "result the evidence does not mention is NOT supported."
    )

    def __init__(
        self,
        llm: CachedLLM | None = None,
        *,
        allow: Iterable[str] = (),
        max_quote_words: int = 12,
    ) -> None:
        self.llm = llm
        self.allow = tuple(allow)
        self.max_quote_words = max_quote_words
        self.model_calls = 0
        self.failures = 0

    def check(
        self, line: str, evidence_text: str, *, layer: str = "dialogue", strict: bool = True
    ) -> ClaimVerdict:
        """Check one layer.

        ``layer="caption"`` is a factual sentence: every content word must be in the
        evidence (the model confirms when it is available). ``layer="dialogue"`` is a
        performance: only claims are checked, so a reaction passes untouched.
        """
        report = check_claims(line, evidence_text, allow=self.allow)
        if report.unbacked:
            detail = ", ".join(f"{claim.kind}:{claim.text}" for claim in report.unbacked[:4])
            return ClaimVerdict(False, f"unbacked {detail}", report)

        if layer == "caption":
            terms = check_terms(line, evidence_text, allow=self.allow)
            if terms.overlap < 1.0:
                return ClaimVerdict(
                    False,
                    "caption states something the evidence does not: "
                    + ", ".join(terms.invented[:4]),
                    report,
                )
        elif not report.needs_model:
            # Dialogue with no claim: pure reaction, nothing to be wrong about.
            return ClaimVerdict(True, "no claim to verify", report)

        if self.llm is None:
            if layer == "dialogue" and report.needs_model and strict:
                return ClaimVerdict(False, "cause/outcome needs a model to verify", report)
            return ClaimVerdict(True, "claims clean (no model available)", report)
        try:
            response = self.llm.complete_json(
                prompt=self.PROMPT,
                payload={
                    "line": line,
                    "evidence": (evidence_text or "")[:4000],
                    "claims": [claim.as_dict() for claim in report.claims],
                },
                schema_hint={"supported": "bool", "unbacked": ["string"]},
                stage="grounding",
            )
        except LLMError:
            self.failures += 1
            return ClaimVerdict(False, "entailment check unavailable", report)
        self.model_calls += 1
        if bool(response.get("supported")):
            return ClaimVerdict(True, "claims + entailment", report, model_checked=True)
        unbacked = response.get("unbacked")
        detail = ", ".join(str(item) for item in unbacked[:4]) if isinstance(unbacked, list) else ""
        return ClaimVerdict(
            False, f"not entailed{(' (' + detail + ')') if detail else ''}", report,
            model_checked=True,
        )

    def quote_ok(self, text: str) -> bool:
        """A verbatim quote is grounded by construction, but a long one is lazy writing."""
        return len((text or "").split()) <= self.max_quote_words

    def literal_caption(self, evidence_text: str, *, limit_words: int | None = None) -> str:
        """A short grounded sentence built from the evidence itself."""
        limit = limit_words or self.max_quote_words
        text = " ".join((evidence_text or "").split())
        if not text:
            return ""
        words = text.split()
        if len(words) > limit:
            return " ".join(words[:limit]).rstrip(" ,;:") + "."
        return text
