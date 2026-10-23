"""Private memory-fact snapshots, kept out of evidence (audit M1-F4).

The diff the M0 owner decision asked for needs the *previous* memory facts. It does
not need their text: a fact is identified by a hash, and only the current run's facts
carry gated text (so a change can be described without quoting the file).

Location: the plugin's own state directory, mode 600 - never an evidence folder.
In the live plugin this is ``plugin_data_dir("scrollback-reel")`` (P1); for CLI runs it
defaults to ``$REEL_STATE_DIR`` or ``~/.local/state/scrollback-reel``.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

from adapters.hermes.evidence import write_private_json

SNAPSHOT_VERSION = 2
DEFAULT_STATE_DIR = Path.home() / ".local" / "state" / "scrollback-reel"


def state_dir(explicit: Path | str | None = None) -> Path:
    if explicit is not None:
        return Path(explicit)
    env = os.environ.get("REEL_STATE_DIR")
    return Path(env) if env else DEFAULT_STATE_DIR


def fact_hash(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()[:32]


@dataclass
class FileSnapshot:
    """One memory file: per-fact hashes plus (current run only) gated text."""

    name: str
    facts: list[dict[str, Any]] = field(default_factory=list)

    def hashes(self) -> list[str]:
        return [str(fact["hash"]) for fact in self.facts]

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "count": len(self.facts),
            "facts": [dict(fact) for fact in self.facts],
        }

    def as_hashes_only(self) -> dict[str, Any]:
        """What goes into evidence: counts and hashes, never text."""
        return {"name": self.name, "count": len(self.facts), "hashes": self.hashes()}


@dataclass
class Snapshot:
    captured_at: float
    files: dict[str, FileSnapshot] = field(default_factory=dict)

    def hashes_by_file(self) -> dict[str, list[str]]:
        return {key: value.hashes() for key, value in sorted(self.files.items())}

    def as_hashes_only(self) -> dict[str, Any]:
        """The evidence-safe view: no text, only per-file counts and hashes."""
        return {
            "files": len(self.files),
            "facts": sum(len(value.facts) for value in self.files.values()),
            "per_file": {
                key: value.as_hashes_only() for key, value in sorted(self.files.items())
            },
        }

    def counts(self) -> dict[str, Any]:
        return {
            "files": len(self.files),
            "facts": sum(len(value.facts) for value in self.files.values()),
            "per_file": {key: len(value.facts) for key, value in sorted(self.files.items())},
        }

    def as_dict(self) -> dict[str, Any]:
        return {
            "v": SNAPSHOT_VERSION,
            "captured_at": round(float(self.captured_at), 6),
            "files": {key: value.as_dict() for key, value in sorted(self.files.items())},
        }


def build_snapshot(
    facts_by_file: Mapping[str, Iterable[str]],
    *,
    captured_at: float,
    gated_text: Mapping[str, Iterable[str]] | None = None,
) -> Snapshot:
    """Build a snapshot. ``gated_text`` must already have passed the gate."""
    snapshot = Snapshot(captured_at=captured_at)
    gated = gated_text or {}
    for key, facts in sorted(facts_by_file.items()):
        gated_values = list(gated.get(key, ()))
        entries: list[dict[str, Any]] = []
        for index, fact in enumerate(facts):
            entry: dict[str, Any] = {"hash": fact_hash(fact), "chars": len(fact)}
            if index < len(gated_values):
                entry["gated"] = str(gated_values[index])
            entries.append(entry)
        snapshot.files[key] = FileSnapshot(name=key, facts=entries)
    return snapshot


class SnapshotStore:
    """Reads and writes the private snapshot. Mode 600, outside evidence."""

    def __init__(self, root: Path | str | None = None) -> None:
        self.root = state_dir(root)

    @property
    def path(self) -> Path:
        return self.root / "memory-facts.json"

    def load(self) -> Snapshot | None:
        path = self.path
        if not path.is_file():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if payload.get("v") != SNAPSHOT_VERSION:
            return None
        files: dict[str, FileSnapshot] = {}
        for key, value in (payload.get("files") or {}).items():
            if not isinstance(value, dict):
                continue
            facts = [fact for fact in value.get("facts") or [] if isinstance(fact, dict)]
            files[str(key)] = FileSnapshot(name=str(key), facts=facts)
        return Snapshot(captured_at=float(payload.get("captured_at", 0.0)), files=files)

    def save(self, snapshot: Snapshot) -> Path:
        return write_private_json(self.path, snapshot.as_dict())

    def hashes_by_file(self) -> dict[str, list[str]]:
        snapshot = self.load()
        return snapshot.hashes_by_file() if snapshot else {}
