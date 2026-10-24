"""Panel rendering (M2 P3). Harness-free: the image call is injected.

The renderer:
- **Calls the generator** once per panel request, through a callable the adapter supplies. The Hermes adapter routes it through the host's ``image_generate`` tool, so the user's own configured provider is used.
- **Retries transient provider failures** with backoff. Bake-off r2 saw one 503 from Codex images.
- **Accepts whatever size comes back.** The provider ignores the requested aspect when given reference images (bake-off r2), so layout adapts later.
- **Caches by content.** The cache key covers the prompt text, the bytes of every reference sheet, and the aspect, so a re-run never pays twice for the same panel.
- **Enforces a per-episode image budget**, counting real calls only. Cache hits are free.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Sequence

from canon.panel_prompt import PanelRequest

Generator = Callable[[str, Sequence[Path], str], Path]

TRANSIENT_MARKERS = ("500", "502", "503", "504", "timeout", "timed out", "temporar", "rate limit", "429", "overloaded")


class RenderError(RuntimeError):
    """The generator failed. ``transient`` failures may be retried."""

    def __init__(self, message: str, *, transient: bool = False) -> None:
        super().__init__(message)
        self.transient = transient


def is_transient(message: str) -> bool:
    lowered = message.lower()
    return any(marker in lowered for marker in TRANSIENT_MARKERS)


def request_key(request: PanelRequest) -> str:
    digest = hashlib.sha256()
    digest.update(request.prompt.encode("utf-8"))
    digest.update(request.aspect.encode("utf-8"))
    for ref in request.references:
        digest.update(hashlib.sha256(Path(ref).read_bytes()).digest())
    return digest.hexdigest()


@dataclass
class RenderReport:
    rendered: dict[str, Path] = field(default_factory=dict)
    cache_hits: int = 0
    calls: int = 0
    retries: int = 0
    failures: list[str] = field(default_factory=list)
    seconds: float = 0.0

    def as_dict(self) -> dict[str, object]:
        return {
            "rendered": {key: str(value) for key, value in self.rendered.items()},
            "cache_hits": self.cache_hits,
            "calls": self.calls,
            "retries": self.retries,
            "failures": list(self.failures),
            "seconds": round(self.seconds, 1),
        }


@dataclass
class PanelRenderer:
    generate: Generator
    cache_dir: Path
    budget: int = 12
    max_retries: int = 3
    backoff_s: float = 4.0
    sleep: Callable[[float], None] = time.sleep
    calls_made: int = 0

    def _cached(self, key: str) -> Path | None:
        path = self.cache_dir / f"{key}.png"
        return path if path.is_file() else None

    def render_one(self, request: PanelRequest, out_dir: Path, report: RenderReport, *, attempt_tag: str = "") -> Path | None:
        key = request_key(request) + (f"-{attempt_tag}" if attempt_tag else "")
        target = Path(out_dir) / f"{request.panel_id}{('-' + attempt_tag) if attempt_tag else ''}.png"
        cached = self._cached(key)
        if cached is not None:
            report.cache_hits += 1
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(cached, target)
            return target
        if self.calls_made >= self.budget:
            report.failures.append(f"{request.panel_id}: image budget of {self.budget} reached")
            return None
        delay = self.backoff_s
        for attempt in range(1, self.max_retries + 1):
            self.calls_made += 1
            report.calls += 1
            try:
                produced = Path(self.generate(request.prompt, request.references, request.aspect))
            except RenderError as exc:
                if exc.transient and attempt < self.max_retries and self.calls_made < self.budget:
                    report.retries += 1
                    self.sleep(delay)
                    delay *= 2
                    continue
                report.failures.append(f"{request.panel_id}: {exc}")
                return None
            if not produced.is_file():
                report.failures.append(f"{request.panel_id}: generator returned no file ({produced})")
                return None
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(produced, self.cache_dir / f"{key}.png")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(produced, target)
            return target
        return None

    def render(self, requests: Sequence[PanelRequest], out_dir: Path) -> RenderReport:
        report = RenderReport()
        started = time.time()
        for request in requests:
            path = self.render_one(request, out_dir, report)
            if path is not None:
                report.rendered[request.panel_id] = path
        report.seconds = time.time() - started
        return report


def write_render_manifest(path: Path, requests: Sequence[PanelRequest], report: RenderReport) -> None:
    """What was asked for and what came back. Prompts hold only post-gate text."""
    data = {
        "requests": [
            {
                "panel_id": request.panel_id,
                "prompt": request.prompt,
                "references": [str(ref) for ref in request.references],
                "cast": list(request.cast),
                "positions": dict(request.positions),
                "aspect": request.aspect,
            }
            for request in requests
        ],
        "report": report.as_dict(),
    }
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, indent=1, sort_keys=True) + "\n", encoding="utf-8")
