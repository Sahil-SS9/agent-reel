"""The host vision route (M2 P4/P5): ``vision_analyze`` through ``ctx.dispatch_tool``."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from canon.llm import parse_json_object


class VisionError(RuntimeError):
    pass


def host_vision(dispatch: Callable[..., str]) -> Callable[[Path, str], dict[str, Any]]:
    def ask(image: Path, question: str) -> dict[str, Any]:
        try:
            raw = dispatch("vision_analyze", {"image_url": str(Path(image)), "question": question})
        except Exception as exc:  # noqa: BLE001
            raise VisionError(f"vision_analyze raised {type(exc).__name__}: {exc}") from exc
        try:
            payload = json.loads(raw) if isinstance(raw, str) else raw
        except json.JSONDecodeError as exc:
            raise VisionError(f"vision_analyze returned non-JSON: {str(raw)[:200]}") from exc
        if not isinstance(payload, dict) or not payload.get("success"):
            raise VisionError(f"vision_analyze failed: {str(payload)[:300]}")
        text = str(payload.get("analysis") or "")
        start = text.find("{")
        if start < 0:
            raise VisionError(f"vision answer has no JSON: {text[:200]}")
        try:
            return parse_json_object(text[start:])
        except Exception as exc:  # noqa: BLE001
            raise VisionError(f"vision answer not parseable: {exc}") from exc

    return ask
