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
_THOUSANDS = re.compile(r"(?<=\d),(?=\d{3}(?:\D|$))")
#: A figure as a whole token (r10c / QAR10-02): keeps a leading minus sign, a version
#: prefix ("v14") and an ordinal suffix ("14th"), so -4/4, 14th/4th and v14/v4 differ.
#: A digit inside a hyphenated name ("Gemma-4-E4B") is part of that name, not a figure.
_FIGURE_RE = re.compile(
    r"(?<![\w\-.])(?:-(?=\d))?[vV]?\d[\d,.:]*(?:st|nd|rd|th)?(?![\w\-])"
)


def canonical_number(token: str) -> str:
    """One spelling per figure: no trailing punctuation, no thousands separators."""
    text = token.strip().rstrip(".,:")
    return _THOUSANDS.sub("", text).lower()


def figures_in(text: str) -> list[str]:
    """The figures in ``text`` as written (trailing punctuation stripped)."""
    return [match.group(0).rstrip(".,:") for match in _FIGURE_RE.finditer(text or "")]


def number_tokens(text: str) -> set[str]:
    """Every complete figure in ``text`` (r10b / QAR10-02: never a substring)."""
    return {canonical_number(token) for token in figures_in(text)}


#: Sentence ends only - a semicolon joins clauses about the same actor ("kensei stopped
#: the run on purpose; exit 143 was a SIGTERM"), so it must not split a name from its act.
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def attribution_blocks(text: str) -> list[str]:
    """Units within which an actor is bound to what it did (r10c / QAR10-01).

    The planner separates cited events (and thread facts) with blank lines, so a block
    is one event. Text without blank lines is split into sentences instead.
    """
    text = (text or "").strip()
    if not text:
        return []
    if "\n\n" in text:
        return [block.strip() for block in re.split(r"\n\s*\n", text) if block.strip()]
    return [part.strip() for part in _SENTENCE_SPLIT.split(text) if part.strip()]


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
        if lowered[0].isdigit():
            # Figures are checked as complete numbers by the number rule (r10b).
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

    line_numbers = figures_in(line)
    backed_numbers = number_tokens(evidence_text)
    invented_numbers = [
        number for number in line_numbers if canonical_number(number) not in backed_numbers
    ]
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
#: An acronym or a model/version code (GGUF, LCM-X, Q3, E4B): as specific as a name.
_ACRONYM_RE = re.compile(r"\b[A-Z][A-Z0-9]{1,}(?:-[A-Z0-9]+)*\b")
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
    for token in figures_in(line):
        add("number", token)
    for match in _PROPER_RE.finditer(line):
        token = " ".join(match.group(0).split())
        if token.lower() in allowed or _TECHNICAL_RE.search(token):
            continue
        # A capitalised first word is a sentence start, not a claim.
        if match.start() == 0 and len(token.split()) == 1:
            continue
        add("name", token)
    for match in _ACRONYM_RE.finditer(line):
        token = match.group(0)
        if token.lower() in allowed or token.isdigit():
            continue
        add("name", token)
    return tuple(claims)


def check_claims(line: str, evidence_text: str, *, allow: Iterable[str] = ()) -> ClaimReport:
    """Names and numbers must appear in the evidence; causes and outcomes need a model."""
    haystack = " ".join((evidence_text or "").lower().split())
    claims = extract_claims(line, allow=allow)
    figures = number_tokens(evidence_text)

    def backed(claim: Claim) -> bool:
        if claim.kind == "number":
            # QAR10-02: a complete figure, never a substring ("4" is not in "14").
            return canonical_number(claim.text) in figures
        needle = claim.text.lower()
        if needle in haystack:
            return True
        if claim.kind != "name":
            return False
        # A multi-word name is backed when every word is present ("Denji Reviewer" for a
        # profile called denji-reviewer). The term check already allows this; the claim
        # check refusing it made every composed caption fail.
        words = [word for word in needle.replace("-", " ").split() if word]
        return bool(words) and all(word in haystack for word in words)

    unbacked = [
        claim
        for claim in claims
        if claim.kind in {"name", "number"} and not backed(claim)
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

    #: Captions are narration, so they are judged as facts. Paraphrase is expected; the
    #: judge is told which words are not in the evidence so it looks at exactly those.
    CAPTION_PROMPT = (
        "You check one narrator caption of a comic against the evidence it cites. "
        'Answer JSON only: {"supported": true|false, "unbacked": ["..."]}. '
        "Rewording, synonyms and summarising are fine. The caption is supported only if "
        "everything it states - who did it, what happened, why, when, a number, a name, "
        "an outcome, a tool - is stated or directly implied by the evidence. "
        "terms_not_in_evidence lists caption words that do not appear in the evidence: "
        "for each, decide whether it is a rewording of something the evidence says or a "
        "new fact. A wrong actor, a flipped outcome, an added cause, an added time of day "
        "or any detail the evidence does not give makes the caption NOT supported. When "
        "unsure, answer false."
    )

    #: V7 (25/10/26, owner decision): "true in meaning". Plain-English retelling of a
    #: technical detail is a rewording, not a new fact. Names, numbers and who-did-what
    #: stay deterministic; only the vocabulary floor goes, and the judge decides meaning.
    MEANING_PROMPT = (
        "You check one line of a comic that retells real work for a general reader, against "
        "the evidence it cites. "
        'Answer JSON only: {"supported": true|false, "unbacked": ["..."]}. '
        "The line may use plain English instead of the evidence's jargon: an exit code, a "
        "commit hash or a tool name explained by what it MEANT (\"the checker itself was "
        "broken\", \"the test copy was missing a tool\") is a rewording and is supported. "
        "Tone, emotion, metaphor and reaction are not claims. The line is NOT supported if it "
        "adds anything the evidence does not say or directly imply: a wrong actor, a flipped "
        "or invented outcome, an added cause, a time, a number, a name or a detail. A vivid "
        "metaphor that implies a new fact (\"the server caught fire\") is not supported. "
        "terms_not_in_evidence lists words not in the evidence; for each decide whether it is "
        "a plain-English rewording or a new fact. When unsure, answer false."
    )

    #: With a model, a caption must share at least this much vocabulary with its
    #: evidence before the model is asked; below it the caption is about something else.
    #: In meaning mode (V7) there is no vocabulary floor; the judge decides meaning.
    MIN_CAPTION_OVERLAP = 0.5
    MIN_MEANING_OVERLAP = 0.0

    def __init__(
        self,
        llm: CachedLLM | None = None,
        *,
        allow: Iterable[str] = (),
        cast: Iterable[str] = (),
        max_quote_words: int = 12,
        meaning: bool = False,
    ) -> None:
        self.llm = llm
        #: V7: judge captions and lines on meaning (plain-English retelling allowed).
        self.meaning = meaning
        self.allow = tuple(allow)
        #: Character names. They are legal vocabulary (allow), but a caption that names
        #: one is claiming that person was involved, so the name must be in the cited
        #: evidence (r10b / QAR10-01).
        # r10c: a caller that only passes an allowlist still gets the actor check for the
        # names in it (QAR10-01 failed for allow-only callers).
        # M2 P0 (Quan P3): case-insensitive - every allowlisted entry counts, so a
        # lower-case allowlist cannot skip the actor check. Production passes `cast`.
        named = cast or self.allow
        self.cast = tuple(dict.fromkeys(str(name).strip() for name in named if str(name).strip()))
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

        terms = None
        if layer == "caption":
            named = [
                name for name in self.cast
                if re.search(rf"\b{re.escape(name)}\b", line, re.IGNORECASE)
            ]
            missing_cast = [
                name for name in named
                if not re.search(rf"\b{re.escape(name)}\b", evidence_text or "", re.IGNORECASE)
            ]
            if missing_cast:
                return ClaimVerdict(
                    False,
                    "unbacked actor " + ", ".join(missing_cast[:4]) + " (not in the cited evidence)",
                    report,
                )
            unbound = self._unbound_actors(line, evidence_text, named)
            if unbound:
                return ClaimVerdict(
                    False,
                    "actor not bound to the action: " + ", ".join(unbound[:4])
                    + " (no cited event names them doing it)",
                    report,
                )
            terms = check_terms(line, evidence_text, allow=self.allow)
            if terms.invented_numbers:
                return ClaimVerdict(
                    False, "invented numbers: " + ", ".join(terms.invented_numbers[:4]), report
                )
            # Round 10: without a model the term rule is the only judge, so it is
            # absolute. With a model it is a relevance floor; the model decides whether
            # the remaining words are rewording or new facts. Demanding full overlap with
            # a model refused every paraphrase before the model was ever asked (r9).
            if self.llm is None:
                required = 1.0  # no model: fail closed, exactly as before
            else:
                required = self.MIN_MEANING_OVERLAP if self.meaning else self.MIN_CAPTION_OVERLAP
            if terms.overlap < required:
                return ClaimVerdict(
                    False,
                    f"caption term overlap {terms.overlap:.0%} below {required:.0%}: "
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
        payload: dict[str, Any] = {
            "line": line,
            "evidence": (evidence_text or "")[:4000],
            "claims": [claim.as_dict() for claim in report.claims],
        }
        if terms is not None:
            payload["terms_not_in_evidence"] = list(terms.invented)
        if self.meaning:
            prompt = self.MEANING_PROMPT
        else:
            prompt = self.CAPTION_PROMPT if layer == "caption" else self.PROMPT
        try:
            response = self.llm.complete_json(
                prompt=prompt,
                payload=payload,
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

    def _unbound_actors(self, line: str, evidence_text: str, named: Sequence[str]) -> list[str]:
        """Named actors with no evidence block that names them *and* shares the action.

        r10c / QAR10-01: presence anywhere in the merged evidence let "Kensei leaves one
        command" pass when only Octacon's event mentions the command. Each named actor
        needs one block (one cited event, or one sentence) carrying both the name and at
        least one of the caption's content words.
        """
        if not named:
            return []
        names_lower = {name.lower() for name in self.cast}
        content = {
            term[:6]
            for term in content_terms(line, allow=())
            if term not in names_lower and not any(term in n.lower().split() for n in self.cast)
        }
        if not content:
            return []
        blocks = attribution_blocks(evidence_text)
        unbound: list[str] = []
        for name in named:
            pattern = re.compile(rf"\b{re.escape(name)}\b", re.IGNORECASE)
            bound = False
            for block in blocks:
                if not pattern.search(block):
                    continue
                stems = {token.lower()[:6] for token in _TOKEN_RE.findall(block)}
                if content & stems:
                    bound = True
                    break
            if not bound:
                unbound.append(name)
        return unbound

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
