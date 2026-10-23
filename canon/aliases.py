"""Stable fictional aliases for redacted terms (round 3, item 3).

`[REDACTED:project_name#ab12cd]` is honest but unreadable, and the audit says a script
must never show a marker. The gate tags every mask with a digest of the value it
replaced, so this module can give that value a stable alias:

* the same project always becomes the same fictional name, across episodes and runs;
* the alias book is persisted privately (mode 600) next to the memory snapshot;
* names get fictional names, everything else gets a plain description that reads
  naturally in a caption ("an address", "an internal address", "a local file").

The map is private: it never leaves the state dir, and the script only ever shows the
alias.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Iterable, Mapping

from adapters.hermes.evidence import write_private_json

MASK_RE = re.compile(r"\[REDACTED:([a-z_]+)(?:#([0-9a-f]{6}))?\]")

#: Descriptive aliases for things that are not characters.
DESCRIPTIVE: dict[str, tuple[str, ...]] = {
    "email": ("an email address", "a mailbox", "an address"),
    "phone": ("a phone number", "a direct line", "a mobile number"),
    "ip": ("an internal address", "a private address", "a network address"),
    "path": ("a local file", "a local folder", "a file on disk"),
    "url_token": ("a signed link", "an invite link", "a private link"),
    "secret": ("a key", "a credential", "a token"),
    "financial": ("an undisclosed sum", "an unstated amount", "a private figure"),
    "health": ("a private matter", "a personal matter", "a medical detail"),
}

PROJECT_WORDS = (
    "Lantern", "Ember", "Meridian", "Harbour", "Cinder", "Thistle", "Beacon", "Juniper",
    "Marlin", "Quarry", "Rookery", "Sable", "Tamarisk", "Vellum", "Willow", "Zephyr",
)
CLIENT_WORDS = (
    "Alder", "Bracken", "Copperfield", "Dunmore", "Elmsworth", "Fairhaven", "Glasswing",
    "Holloway", "Ironwood", "Kestrel", "Larkspur", "Mossgate", "Northwind", "Oakhurst",
)
PERSON_FIRST = (
    "Mara", "Elias", "Nadia", "Tomas", "Ines", "Rowan", "Priya", "Deniz", "Ada", "Kwame",
    "Lena", "Oscar", "Sofia", "Ravi", "Yara", "Bruno",
)
PERSON_LAST = (
    "Vance", "Okafor", "Lindqvist", "Moreau", "Sandoval", "Adeyemi", "Halden", "Kovac",
    "Ferreira", "Nakamura", "Bright", "Castellan", "Duarte", "Ellery",
)


def _pick(pool: tuple[str, ...], digest: str, salt: str = "") -> str:
    basis = f"{salt}:{digest}"
    index = int(hashlib.sha256(basis.encode("utf-8")).hexdigest()[:8], 16)
    return pool[index % len(pool)]


@dataclass
class AliasBook:
    """Mask id -> alias, persisted privately so episodes stay consistent."""

    path: Path
    entries: dict[str, str] = field(default_factory=dict)
    _used: set[str] = field(default_factory=set)

    # -- persistence -------------------------------------------------------
    @classmethod
    def load(cls, path: Path | str) -> "AliasBook":
        target = Path(path)
        entries: dict[str, str] = {}
        if target.is_file():
            try:
                payload = json.loads(target.read_text(encoding="utf-8"))
                if isinstance(payload, dict):
                    entries = {str(k): str(v) for k, v in payload.items()}
            except (OSError, json.JSONDecodeError):
                entries = {}
        book = cls(path=target, entries=entries)
        book._used = set(entries.values())
        return book

    def save(self) -> Path:
        return write_private_json(self.path, self.entries)

    # -- aliasing ----------------------------------------------------------
    def alias(self, category: str, digest: str | None) -> str:
        key = f"{category}#{digest or 'anon'}"
        if key in self.entries:
            return self.entries[key]
        if category == "client_name":
            base = f"{_pick(CLIENT_WORDS, digest or key)} Group"
        elif category == "person_name":
            base = f"{_pick(PERSON_FIRST, digest or key)} {_pick(PERSON_LAST, digest or key, 'last')}"
        elif category == "project_name":
            base = f"Project {_pick(PROJECT_WORDS, digest or key)}"
        else:
            base = _pick(DESCRIPTIVE.get(category, ("a private detail",)), digest or key)
        alias = base
        attempt = 1
        while alias in self._used and self.entries.get(key) != alias:
            # Two different values must not become the same character.
            alias = f"{base} {attempt + 1}"
            attempt += 1
            if attempt > 20:
                break
        self.entries[key] = alias
        self._used.add(alias)
        return alias

    def resolve(self, text: str) -> str:
        if not text or "[REDACTED:" not in text:
            return text

        def _sub(match: re.Match[str]) -> str:
            return self.alias(match.group(1), match.group(2))

        return MASK_RE.sub(_sub, text)

    def resolve_all(self, values: Iterable[str]) -> list[str]:
        return [self.resolve(value) for value in values]

    def as_dict(self) -> Mapping[str, str]:
        return dict(sorted(self.entries.items()))


def apply_to_ir(ir: Any, book: AliasBook) -> Any:
    """Return a copy of the episode with every mask replaced by its alias."""
    from canon.episode import EpisodeIR, Line, Panel

    panels = []
    for panel in ir.panels:
        lines = tuple(
            replace(line, text=book.resolve(line.text)) for line in panel.lines
        )
        panels.append(
            replace(
                panel,
                caption=book.resolve(panel.caption),
                lines=lines,
                cast=tuple(panel.cast),
            )
        )
    return replace(
        ir,
        panels=tuple(panels),
        logline=book.resolve(ir.logline),
    )


def masks_in(text: str) -> list[str]:
    return [match.group(0) for match in MASK_RE.finditer(text or "")]
