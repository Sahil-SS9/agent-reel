"""Content-addressed cache for every model call.

SPEC §4: "every model call is keyed by (stage, model, prompt-hash, input-hash).
The same input gives the same canon." This is what makes a second run
byte-identical even when a model is involved.

The cache is deliberately plain: a directory of JSON files, one per key. No
database, no daemon, no TTL - a stale result is a *reproducible* result, and the
key includes the model and the prompt so a changed prompt misses rather than
silently reuses.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

CACHE_VERSION = 1


def fingerprint(value: Any) -> str:
    """Stable short hash of any JSON-able value."""
    blob = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]


@dataclass(frozen=True, slots=True)
class CacheKey:
    stage: str
    model: str
    prompt_hash: str
    input_hash: str

    def as_string(self) -> str:
        return "|".join((self.stage, self.model, self.prompt_hash, self.input_hash))

    def digest(self) -> str:
        return hashlib.sha256(self.as_string().encode("utf-8")).hexdigest()[:40]


class ModelCache:
    """A directory-backed cache. Safe to share between runs and processes."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)
        self._root_ready = False
        self.hits = 0
        self.misses = 0

    # -- internals ---------------------------------------------------------
    def _ensure(self) -> None:
        if not self._root_ready:
            self.root.mkdir(parents=True, exist_ok=True)
            self._root_ready = True

    def _path(self, key: CacheKey) -> Path:
        return self.root / f"{key.digest()}.json"

    # -- api ---------------------------------------------------------------
    def get(self, key: CacheKey) -> dict[str, Any] | None:
        path = self._path(key)
        if not path.is_file():
            self.misses += 1
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self.misses += 1
            return None
        if payload.get("v") != CACHE_VERSION or payload.get("key") != key.as_string():
            self.misses += 1
            return None
        self.hits += 1
        value = payload.get("value")
        return value if isinstance(value, dict) else None

    def set(self, key: CacheKey, value: Mapping[str, Any]) -> None:
        self._ensure()
        body = {
            "v": CACHE_VERSION,
            "key": key.as_string(),
            "stage": key.stage,
            "model": key.model,
            "value": dict(value),
        }
        path = self._path(key)
        # Atomic write: a half-written cache entry must never be read back.
        handle, tmp_name = tempfile.mkstemp(dir=str(self.root), suffix=".tmp")
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(body, stream, sort_keys=True, indent=1)
        os.replace(tmp_name, path)

    def stats(self) -> dict[str, int]:
        return {"hits": self.hits, "misses": self.misses}

    def __len__(self) -> int:
        if not self.root.is_dir():
            return 0
        return sum(1 for _ in self.root.glob("*.json"))
