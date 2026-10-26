"""The host vision route (M2 P4/P5): ``vision_analyze`` through ``ctx.dispatch_tool``."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from canon.llm import parse_json_object


class VisionError(RuntimeError):
    pass


def host_vision(dispatch: Callable[..., str]) -> Callable[[Path, str], dict[str, Any]]:
    """A vision asker that survives a model answering in prose.

    The host model sometimes replies with a description instead of the JSON object it was
    asked for, which failed the whole panel check (and therefore the render) on 26/10/26.
    One retry with an explicit "JSON only" instruction recovers it; a second prose answer
    still raises, so a genuine failure is never hidden.
    """

    strict = "\n\nAnswer with one JSON object only. No prose, no markdown, no code fences."

    def ask(image: Path, question: str) -> dict[str, Any]:
        last_text = ""
        for attempt in range(2):
            prompt = question if attempt == 0 else question + strict
            try:
                raw = dispatch("vision_analyze", {"image_url": str(Path(image)), "question": prompt})
            except Exception as exc:  # noqa: BLE001
                raise VisionError(f"vision_analyze raised {type(exc).__name__}: {exc}") from exc
            try:
                payload = json.loads(raw) if isinstance(raw, str) else raw
            except json.JSONDecodeError as exc:
                raise VisionError(f"vision_analyze returned non-JSON: {str(raw)[:200]}") from exc
            if not isinstance(payload, dict) or not payload.get("success"):
                raise VisionError(f"vision_analyze failed: {str(payload)[:300]}")
            text = str(payload.get("analysis") or "")
            last_text = text
            start = text.find("{")
            if start < 0:
                continue
            try:
                return parse_json_object(text[start:])
            except Exception as exc:  # noqa: BLE001
                last_text = f"{text[:200]} ({exc})"
                continue
        raise VisionError(f"vision answer has no JSON: {last_text[:200]}")

    return ask
