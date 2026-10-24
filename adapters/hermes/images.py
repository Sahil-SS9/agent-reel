"""The host image route (M2 P3): ``image_generate`` through ``ctx.dispatch_tool``.

The user's own Hermes image provider renders the panels. This module only adapts the
tool's JSON reply (``{"success": true, "image": "/abs/path.png"}`` or an error) to the
renderer's generator interface.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Sequence

from canon.render import RenderError, is_transient

ASPECTS = {"landscape", "portrait", "square"}


def host_generator(dispatch: Callable[..., str]) -> Callable[[str, Sequence[Path], str], Path]:
    def generate(prompt: str, references: Sequence[Path], aspect: str) -> Path:
        args: dict[str, Any] = {
            "prompt": prompt,
            "aspect_ratio": aspect if aspect in ASPECTS else "landscape",
        }
        if references:
            args["reference_image_urls"] = [str(Path(ref)) for ref in references]
        try:
            raw = dispatch("image_generate", args)
        except Exception as exc:  # noqa: BLE001 - a host failure is a render failure
            raise RenderError(f"image_generate raised {type(exc).__name__}: {exc}", transient=is_transient(str(exc))) from exc
        try:
            payload = json.loads(raw) if isinstance(raw, str) else raw
        except json.JSONDecodeError as exc:
            raise RenderError(f"image_generate returned non-JSON: {str(raw)[:200]}") from exc
        if not isinstance(payload, dict) or not payload.get("success"):
            message = str((payload or {}).get("error") if isinstance(payload, dict) else raw)[:300]
            raise RenderError(f"image_generate failed: {message}", transient=is_transient(message))
        image = payload.get("host_image") or payload.get("image")
        if not isinstance(image, str) or not image.startswith("/"):
            raise RenderError(f"image_generate returned no local file: {str(image)[:200]}")
        return Path(image)

    return generate
