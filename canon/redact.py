"""The redaction gate (M1). Nothing reaches beats, arcs or the renderer without it.

Two passes, as SPEC §4 requires:

1. **Deterministic** - regex rules (Hermes' vendor prefixes and secret-name
   vocabularies, supplied by the adapter; plus emails, phones, IPs, absolute
   paths, signed URLs, credentials in assignments and headers). No model, no
   network, always runs on every event.
2. **Model pass** - names, client names, internal project names, financial and
   health details. Runs in two cheap shapes rather than per message:
   - *vocabulary*: every distinct candidate proper noun in the window is
     classified once (batched, cached), then masked everywhere;
   - *span*: the story subset is classified for spans the vocabulary cannot see
     (an amount, a diagnosis).

Fail-closed: if the model errors, the event is quarantined, not released. If the
redacted text still trips a deterministic rule, the event is quarantined too.

The gate returns :class:`canon.gate.GatedEvent` objects and a quarantine list.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Protocol, Sequence

from canon.events import Event, PRIVACY_LEVELS, text_digest
from canon.gate import GatedEvent, seal
from canon.llm import CachedLLM, LLMError

MASK_TEMPLATE = "[REDACTED:{category}]"

#: Categories the deterministic pass owns.
DETERMINISTIC_CATEGORIES = frozenset(
    {"secret", "email", "phone", "ip", "path", "url_token", "financial", "health"}
)

#: Categories only the model pass can find, plus what the model may return.
MODEL_CATEGORIES = frozenset(
    {"person_name", "client_name", "project_name", "financial", "health"}
)

#: The classifier's other legal answer.
SAFE = "safe"

#: Words that look like names but are not: months, days, common sentence starts.
_STOPWORD_NAMES = frozenset(
    {
        "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
        "january", "february", "march", "april", "may", "june", "july", "august",
        "september", "october", "november", "december",
        "the", "this", "that", "then", "there", "these", "those", "it", "i", "we",
        "a", "an", "and", "but", "so", "if", "when", "what", "why", "how", "who",
        "ok", "okay", "yes", "no", "done", "next", "now", "not", "all", "none",
        "run", "fix", "test", "build", "ship", "plan", "spec", "task", "todo",
        "hermes", "python", "json", "sqlite", "git", "github", "discord", "telegram",
        "monday", "today", "tomorrow", "yesterday", "morning", "evening", "night",
    }
)

_CANDIDATE_RE = re.compile(r"\b([A-Z][a-z]{1,20}(?:\s+[A-Z][a-z]{1,20}){0,2})\b")
_TECHNICAL_TOKEN_RE = re.compile(r"[A-Za-z0-9_]*[_./][A-Za-z0-9_./]*")


@dataclass(frozen=True, slots=True)
class Rule:
    category: str
    name: str
    pattern: re.Pattern[str]


@dataclass(frozen=True, slots=True)
class Finding:
    category: str
    rule: str
    start: int
    end: int

    def as_dict(self) -> dict[str, Any]:
        return {"category": self.category, "rule": self.rule, "start": self.start, "end": self.end}


@dataclass(frozen=True, slots=True)
class RedactionResult:
    text: str
    findings: tuple[Finding, ...]

    @property
    def categories(self) -> tuple[str, ...]:
        return tuple(sorted({finding.category for finding in self.findings}))


class EntityClassifier(Protocol):
    """Classify candidate names/entities. Returns token -> category or 'safe'."""

    name: str

    def classify_vocabulary(self, candidates: Sequence[str]) -> dict[str, str]:
        ...

    def classify_spans(self, text: str, candidates: Sequence[str]) -> list[dict[str, str]]:
        ...


class DeterministicRedactor:
    """The regex pass. Pure, fast and dependency-free."""

    def __init__(self, rules: Sequence[Rule], *, mask_template: str = MASK_TEMPLATE) -> None:
        self.rules = tuple(rules)
        self.mask_template = mask_template

    def mask(self, category: str) -> str:
        """The replacement token for a category."""
        return self.mask_template.format(category=category)

    def findings(self, text: str) -> list[Finding]:
        found: list[Finding] = []
        for rule in self.rules:
            for match in rule.pattern.finditer(text):
                start, end = match.start(), match.end()
                if end <= start:
                    continue
                found.append(Finding(rule.category, rule.name, start, end))
        return found

    def redact(self, text: str) -> RedactionResult:
        if not text:
            return RedactionResult("", ())
        spans: list[tuple[int, int, str, str]] = []
        for rule in self.rules:
            for match in rule.pattern.finditer(text):
                start, end = match.start(), match.end()
                if end <= start:
                    continue
                # Do not mask an email twice: the address already carries the
                # information the path/credential rules would look for.
                spans.append((start, end, rule.category, rule.name))
        if not spans:
            return RedactionResult(text, ())

        # Merge overlapping spans, keeping the highest-severity category.
        severity = {
            "secret": 0, "financial": 1, "health": 2, "url_token": 3, "path": 4,
            "email": 5, "phone": 6, "ip": 7, "person_name": 8, "client_name": 9,
            "project_name": 10,
        }
        spans.sort(key=lambda span: (span[0], -(span[1] - span[0]), severity.get(span[2], 99)))
        merged: list[tuple[int, int, str, str]] = []
        for start, end, category, rule_name in spans:
            if merged and start < merged[-1][1]:
                prev_start, prev_end, prev_category, prev_rule = merged[-1]
                best = prev_category if severity.get(prev_category, 99) <= severity.get(category, 99) else category
                merged[-1] = (prev_start, max(prev_end, end), best, prev_rule if best == prev_category else rule_name)
            else:
                merged.append((start, end, category, rule_name))

        out: list[str] = []
        findings: list[Finding] = []
        cursor = 0
        for start, end, category, rule_name in merged:
            out.append(text[cursor:start])
            out.append(self.mask(category))
            findings.append(Finding(category, rule_name, start, end))
            cursor = end
        out.append(text[cursor:])
        return RedactionResult("".join(out), tuple(findings))


@dataclass(frozen=True, slots=True)
class Quarantine:
    event_id: str
    reason: str
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"event_id": self.event_id, "reason": self.reason, "detail": self.detail}


@dataclass
class GateReport:
    """What happened at the gate, for the stage report and the benchmark."""

    gated: int = 0
    quarantined: list[Quarantine] = field(default_factory=list)
    findings_by_category: dict[str, int] = field(default_factory=dict)
    vocabulary_size: int = 0
    model_calls: int = 0

    def note(self, categories: Iterable[str]) -> None:
        for category in categories:
            self.findings_by_category[category] = self.findings_by_category.get(category, 0) + 1

    def as_dict(self) -> dict[str, Any]:
        return {
            "gated": self.gated,
            "quarantined": [item.as_dict() for item in self.quarantined],
            "findings_by_category": dict(sorted(self.findings_by_category.items())),
            "vocabulary_size": self.vocabulary_size,
            "model_calls": self.model_calls,
        }


def candidate_names(text: str, allowlist: Iterable[str]) -> list[str]:
    """Proper-noun candidates worth classifying. Deterministic and cheap."""
    allowed = {item.lower() for item in allowlist}
    seen: dict[str, None] = {}
    for match in _CANDIDATE_RE.finditer(text):
        token = " ".join(match.group(1).split())
        lowered = token.lower()
        if lowered in allowed or lowered in _STOPWORD_NAMES:
            continue
        if _TECHNICAL_TOKEN_RE.search(token):
            continue
        if len(token) < 2:
            continue
        seen.setdefault(token, None)
    return list(seen)


#: Model answers drift in wording ("private_person", "customer", "internal").
#: Anything unrecognised fails closed to ``person_name``: an unclassified name is
#: treated as private rather than released.
_CATEGORY_HINTS: tuple[tuple[str, str], ...] = (
    ("financ", "financial"),
    ("money", "financial"),
    ("amount", "financial"),
    ("health", "health"),
    ("medical", "health"),
    ("diagnos", "health"),
    ("client", "client_name"),
    ("customer", "client_name"),
    ("organis", "client_name"),
    ("organiz", "client_name"),
    ("company", "client_name"),
    ("project", "project_name"),
    ("internal", "project_name"),
    ("person", "person_name"),
    ("people", "person_name"),
    ("individual", "person_name"),
    ("private", "person_name"),
    ("name", "person_name"),
)
_SAFE_HINTS = ("safe", "public", "owner", "tool", "product", "allowlisted", "not_private")


def normalise_category(answer: str) -> str:
    """Map a model's wording onto a category, failing closed when unsure."""
    text = (answer or "").strip().lower().replace("-", "_").replace(" ", "_")
    if not text:
        return "person_name"
    for hint in _SAFE_HINTS:
        if text == hint or text.startswith(hint):
            return SAFE
    for hint, category in _CATEGORY_HINTS:
        if hint in text:
            return category
    return "person_name"


class ModelEntityGate:
    """The model pass: vocabulary once, spans for the story subset."""

    VOCAB_PROMPT = (
        "You are a privacy classifier for a private comic that replays an AI agent's "
        "work. For each candidate name decide what it is. Answer with JSON only: "
        '{"results": [{"name": "...", "category": "safe|person_name|client_name|'
        'project_name|financial|health"}]}. '
        "safe = the owner, a public tool or product, a weekday/month, or ordinary "
        "prose. person_name = a private individual. client_name = a customer or "
        "organisation the owner works with. project_name = an internal project name "
        "that is not public. Never invent a name that is not in the list."
    )
    SPAN_PROMPT = (
        "Find private details in the text that must not appear in a comic: private "
        "people's names, client or customer names, internal project names, money "
        'amounts, and health details. Answer with JSON only: {"spans": [{"text": '
        '"<exact substring>", "category": "person_name|client_name|project_name|'
        'financial|health"}]}. Copy each substring exactly from the text. Return '
        '{"spans": []} when there is nothing private.'
    )

    def __init__(
        self,
        llm: CachedLLM,
        *,
        allowlist: Iterable[str] = (),
        batch_size: int = 40,
    ) -> None:
        self.llm = llm
        self.name = getattr(llm, "name", "model")
        self.allowlist = tuple(sorted(allowlist))
        self.batch_size = max(1, batch_size)
        self.calls = 0

    # -- vocabulary --------------------------------------------------------
    def classify_vocabulary(self, candidates: Sequence[str]) -> dict[str, str]:
        verdicts: dict[str, str] = {}
        ordered = sorted({candidate for candidate in candidates if candidate})
        for start in range(0, len(ordered), self.batch_size):
            batch = ordered[start : start + self.batch_size]
            payload = {"candidates": batch, "allowlist": list(self.allowlist)}
            try:
                response = self.llm.complete_json(
                    prompt=self.VOCAB_PROMPT,
                    payload=payload,
                    schema_hint={"results": [{"name": "string", "category": "string"}]},
                    stage="redact.vocabulary",
                )
            except LLMError:
                # Fail closed for the whole batch: unknown names are treated as
                # private rather than released.
                for name in batch:
                    verdicts[name] = "person_name"
                self.calls += 1
                continue
            self.calls += 1
            rows = response.get("results")
            if not isinstance(rows, list):
                # No usable structure: fail closed for the batch.
                for name in batch:
                    verdicts[name] = "person_name"
                continue
            answered: set[str] = set()
            for row in rows:
                if not isinstance(row, Mapping):
                    continue
                name = str(
                    row.get("name") or row.get("candidate") or row.get("text") or ""
                ).strip()
                answer = str(
                    row.get("category") or row.get("classification") or row.get("label") or ""
                )
                if not name:
                    continue
                answered.add(name)
                verdicts[name] = normalise_category(answer)
            # A candidate the model skipped is not safe, it is unanswered.
            for name in batch:
                if name not in answered:
                    verdicts.setdefault(name, "person_name")
        return verdicts

    # -- spans -------------------------------------------------------------
    def classify_spans(self, text: str, candidates: Sequence[str]) -> list[dict[str, str]]:
        payload = {"text": text, "candidates": list(candidates)[:40]}
        try:
            response = self.llm.complete_json(
                prompt=self.SPAN_PROMPT,
                payload=payload,
                schema_hint={"spans": [{"text": "string", "category": "string"}]},
                stage="redact.spans",
            )
        except LLMError:
            self.calls += 1
            raise
        self.calls += 1
        spans: list[dict[str, str]] = []
        rows = response.get("spans")
        if not isinstance(rows, list):
            raise LLMError("span pass returned no spans array")
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            piece = str(row.get("text") or row.get("span") or "").strip()
            category = normalise_category(
                str(row.get("category") or row.get("classification") or "")
            )
            if piece:
                spans.append({"text": piece, "category": category})
        return spans


class RedactionGate:
    """Gate events: deterministic always, model pass where it is affordable."""

    def __init__(
        self,
        redactor: DeterministicRedactor,
        *,
        model_gate: ModelEntityGate | None = None,
        allowlist: Iterable[str] = (),
        max_chars: int = 4000,
        privacy: str = "private",
    ) -> None:
        if privacy not in PRIVACY_LEVELS:
            raise ValueError(f"unknown privacy level: {privacy!r}")
        self.redactor = redactor
        self.model_gate = model_gate
        self.allowlist = tuple(sorted(allowlist))
        self.max_chars = max_chars
        self.privacy = privacy
        self.report = GateReport()
        self._vocabulary: dict[str, str] = {}
        self._name_patterns: tuple[tuple[re.Pattern[str], str], ...] = ()

    # -- vocabulary --------------------------------------------------------
    def learn_vocabulary(
        self, texts: Iterable[str], *, max_candidates: int = 500
    ) -> dict[str, str]:
        """Classify the distinct candidates once, then mask them everywhere.

        ``max_candidates`` is a hard cost bound: a week of history can produce
        thousands of proper-noun candidates, and one model call per 40 of them adds
        up. The most frequent names are the ones that matter for a week's story, so
        the budget goes to them (deterministic tie-break by name).
        """
        if self.model_gate is None:
            return {}
        counts: dict[str, int] = {}
        for text in texts:
            for name in candidate_names(text, self.allowlist):
                counts[name] = counts.get(name, 0) + 1
        ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
        candidates = [name for name, _ in ranked[:max_candidates]]
        verdicts = self.model_gate.classify_vocabulary(candidates)
        self._vocabulary = {name: category for name, category in verdicts.items() if category != SAFE}
        self.report.vocabulary_size = len(self._vocabulary)
        self.report.model_calls += self.model_gate.calls
        self._name_patterns = tuple(
            (
                re.compile(rf"(?<![\w]){re.escape(name)}(?![\w])"),
                category,
            )
            for name, category in sorted(self._vocabulary.items())
        )
        return dict(self._vocabulary)

    def _apply_vocabulary(self, text: str) -> RedactionResult:
        if not self._name_patterns:
            return RedactionResult(text, ())
        spans: list[tuple[int, int, str, str]] = []
        for pattern, category in self._name_patterns:
            for match in pattern.finditer(text):
                spans.append((match.start(), match.end(), category, f"vocabulary:{category}"))
        if not spans:
            return RedactionResult(text, ())
        spans.sort()
        out: list[str] = []
        findings: list[Finding] = []
        cursor = 0
        for start, end, category, rule_name in spans:
            if start < cursor:
                continue
            out.append(text[cursor:start])
            out.append(self.redactor.mask(category))
            findings.append(Finding(category, rule_name, start, end))
            cursor = end
        out.append(text[cursor:])
        return RedactionResult("".join(out), tuple(findings))

    def _apply_spans(self, text: str, spans: Sequence[Mapping[str, str]]) -> RedactionResult:
        if not spans:
            return RedactionResult(text, ())
        ranges: list[tuple[int, int, str]] = []
        for span in spans:
            piece = str(span.get("text", ""))
            category = str(span.get("category", "person_name"))
            if not piece:
                continue
            start = text.find(piece)
            while start != -1:
                ranges.append((start, start + len(piece), category))
                start = text.find(piece, start + 1)
        if not ranges:
            return RedactionResult(text, ())
        ranges.sort()
        out: list[str] = []
        findings: list[Finding] = []
        cursor = 0
        for start, end, category in ranges:
            if start < cursor:
                continue
            out.append(text[cursor:start])
            out.append(self.redactor.mask(category))
            findings.append(Finding(category, "model_span", start, end))
            cursor = end
        out.append(text[cursor:])
        return RedactionResult("".join(out), tuple(findings))

    # -- per event ---------------------------------------------------------
    def redact_text(self, text: str, *, deep: bool = False) -> tuple[str, tuple[Finding, ...]]:
        """Deterministic pass, then the learned vocabulary, then optional spans."""
        if not text:
            return "", ()
        clipped = text[: self.max_chars]
        findings: list[Finding] = []

        determ = self.redactor.redact(clipped)
        findings.extend(determ.findings)
        current = determ.text

        vocab = self._apply_vocabulary(current)
        findings.extend(vocab.findings)
        current = vocab.text

        if deep and self.model_gate is not None:
            candidates = candidate_names(current, self.allowlist)
            try:
                spans = self.model_gate.classify_spans(current, candidates)
            except LLMError:
                self.report.model_calls += 1
                raise
            span_result = self._apply_spans(current, spans)
            findings.extend(span_result.findings)
            current = span_result.text

        # Fail closed: a redaction that still trips a rule is not released.
        residue = self.redactor.findings(current)
        if residue:
            raise LeakResidue(
                "redacted text still matches "
                + ", ".join(sorted({finding.rule for finding in residue})[:3])
            )
        return current, tuple(findings)

    def scan(self, text: str) -> tuple[Finding, ...]:
        """Report leaks in ``text`` without modifying it (no clipping, no masking).

        Used by the evidence writer: it needs to know whether a value would leak, not
        what the redacted form looks like.
        """
        if not text:
            return ()
        found: list[Finding] = list(self.redactor.findings(text))
        for pattern, category in self._name_patterns:
            for match in pattern.finditer(text):
                found.append(Finding(category, f"vocabulary:{category}", match.start(), match.end()))
        return tuple(found)

    def gate_event(
        self,
        event: Event,
        *,
        text: str | None = None,
        deep: bool = False,
    ) -> GatedEvent | None:
        """Gate one event. Returns None (and quarantines it) on any failure."""
        try:
            safe_payload, findings = self._safe_payload(event.payload, deep=deep)
            if text:
                redacted_text, text_findings = self.redact_text(text, deep=deep)
                safe_payload = dict(safe_payload)
                safe_payload["text"] = redacted_text
                safe_payload["text_digest"] = text_digest(redacted_text)
                findings = findings + text_findings
        except LeakResidue as exc:
            self.report.quarantined.append(
                Quarantine(event.id, "leak_residue", str(exc))
            )
            return None
        except LLMError as exc:
            self.report.quarantined.append(Quarantine(event.id, "model_error", str(exc)))
            return None
        except Exception as exc:  # noqa: BLE001 - quarantine, never release
            self.report.quarantined.append(
                Quarantine(event.id, "gate_error", f"{type(exc).__name__}: {exc}")
            )
            return None

        self.report.note(finding.category for finding in findings)
        self.report.gated += 1
        safe_payload["gate"] = {
            "privacy": event.privacy,
            "deep": bool(deep),
            "model_pass": bool(deep and self.model_gate is not None),
            "findings": sorted({finding.category for finding in findings}),
        }
        return seal(event, safe_payload)

    def _safe_payload(
        self, payload: Mapping[str, Any], *, deep: bool
    ) -> tuple[dict[str, Any], tuple[Finding, ...]]:
        safe: dict[str, Any] = {}
        findings: list[Finding] = []
        for key, value in sorted(payload.items()):
            if isinstance(value, bool) or isinstance(value, (int, float)):
                safe[key] = value
            elif isinstance(value, str):
                redacted, hits = self.redact_text(value, deep=False)
                safe[key] = redacted
                findings.extend(hits)
            elif isinstance(value, Mapping):
                nested, hits = self._safe_payload(value, deep=deep)
                safe[key] = nested
                findings.extend(hits)
            elif isinstance(value, (list, tuple)):
                items: list[Any] = []
                for item in value:
                    if isinstance(item, str):
                        redacted, hits = self.redact_text(item, deep=False)
                        items.append(redacted)
                        findings.extend(hits)
                    elif isinstance(item, (int, float, bool)) or item is None:
                        items.append(item)
                    elif isinstance(item, Mapping):
                        nested, hits = self._safe_payload(item, deep=deep)
                        items.append(nested)
                        findings.extend(hits)
                    else:
                        items.append(str(item))
                safe[key] = items
            elif value is None:
                safe[key] = None
            else:
                safe[key] = str(value)
        return safe, tuple(findings)


class LeakResidue(RuntimeError):
    """The redacted output still contains something that looks like a leak."""
