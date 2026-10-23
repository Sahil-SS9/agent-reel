"""Pre-flight leak scan for output that is about to be written to evidence.

This is deliberately small and deterministic. It is **not** the M1 redaction
gate: it exists so a stage report or summary can be checked for obvious leaks
(emails, tokens, keys, IPs, absolute home paths) before it is stored.

M1 owns the real gate: Hermes' ``agent/redact.py`` patterns plus a model pass.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Iterable, Sequence

#: (name, compiled pattern). Order matters only for reporting.
PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("private_key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    (
        "provider_token",
        re.compile(
            r"\b(?:sk-[A-Za-z0-9_\-]{16,}|ghp_[A-Za-z0-9]{20,}|gho_[A-Za-z0-9]{20,}"
            r"|github_pat_[A-Za-z0-9_]{20,}|xox[abprs]-[A-Za-z0-9\-]{10,}"
            r"|AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_\-]{30,})\b"
        ),
    ),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\b")),
    ("email", re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")),
    (
        "phone",
        re.compile(r"(?<![\w.])(?:\+44\s?7\d{3}|07\d{3})\s?\d{3}\s?\d{3}(?![\w.])"),
    ),
    (
        "ipv4",
        re.compile(
            r"(?<![\w.])(?:(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\.){3}"
            r"(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)(?![\w.])"
        ),
    ),
    ("home_path", re.compile(r"/(?:home|Users)/[A-Za-z0-9._\-]+")),
    ("bearer", re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{12,}")),
)

#: Long tokens with no vowels are the classic shape of a generated secret.
_ENTROPY_CANDIDATE = re.compile(r"\b[A-Za-z0-9+/=_\-]{32,}\b")
_VOWELS = set("aeiouAEIOU")


@dataclass(frozen=True, slots=True)
class Leak:
    line: int
    pattern: str
    preview: str


def _preview(text: str, match: re.Match[str]) -> str:
    start = max(0, match.start() - 8)
    end = min(len(text), match.end() + 8)
    snippet = text[start:end].strip()
    if len(snippet) > 60:
        snippet = snippet[:57] + "..."
    return snippet


def _looks_random(token: str) -> bool:
    if len(token) < 32:
        return False
    digits = sum(ch.isdigit() for ch in token)
    if digits < 4:
        return False
    vowels = sum(ch in _VOWELS for ch in token)
    if vowels / len(token) > 0.2:
        return False
    distinct = len(set(token))
    if distinct < 12:
        return False
    entropy = -sum(
        (token.count(ch) / len(token)) * math.log2(token.count(ch) / len(token))
        for ch in set(token)
    )
    return entropy > 4.0


def scan_text(text: str, *, first_line: int = 1) -> list[Leak]:
    hits: list[Leak] = []
    for offset, line in enumerate(text.splitlines()):
        number = first_line + offset
        for name, pattern in PATTERNS:
            for match in pattern.finditer(line):
                hits.append(Leak(line=number, pattern=name, preview=_preview(line, match)))
        for match in _ENTROPY_CANDIDATE.finditer(line):
            token = match.group(0)
            if _looks_random(token) and not token.isdigit():
                hits.append(Leak(line=number, pattern="high_entropy", preview=token[:20] + "..."))
    return hits


def scan_lines(lines: Sequence[str]) -> list[Leak]:
    return scan_text("\n".join(lines))


def scan_iterable(chunks: Iterable[str]) -> list[Leak]:
    return scan_text("".join(chunks))
