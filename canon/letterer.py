"""The letterer (M2 P5): balloons, captions and tails placed after the art is made.

This is a port of bake-off r2 letterer v2, which Sahil approved, generalised from one fixed episode to any panel. It uses the vision check's normalised head boxes, free regions and keep-out boxes.

- **Nothing covers a face or a key object.** Heads and keep-out boxes are padded and blocked.
- **Balloons sit in the free space.** The search runs over font size × wrap width × position.
- **Reading order.** Each balloon sits right of the previous one on the same row, or below it.
- **Tails aim at the speaker's face.** An off-screen or hologram speaker gets a rectangular "comms" balloon instead.
- **The caption box** goes top-left, or bottom-left if the top is blocked.
- **Anything unplaceable is reported**, never silently dropped.

The art is never edited by the image model to add text. This module draws on top of the finished image with licence-clean OFL fonts (``assets/fonts``).
"""

from __future__ import annotations

import math
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Sequence

from PIL import Image, ImageDraw, ImageFont

FONT_DIR = Path(__file__).resolve().parents[1] / "assets" / "fonts"
BODY_FONT = FONT_DIR / "ComicNeue-Bold.ttf"
TITLE_FONT = FONT_DIR / "Bangers-Regular.ttf"
REFERENCE_WIDTH = 1536  # bake-off r2 panel width the sizes were tuned on


@dataclass
class LetterReport:
    placed: list[str] = field(default_factory=list)
    unplaced: list[str] = field(default_factory=list)
    caption_box: list[int] | None = None
    balloons: list[dict[str, object]] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        return not self.unplaced

    def as_dict(self) -> dict[str, object]:
        return {
            "placed": self.placed,
            "unplaced": self.unplaced,
            "caption_box": self.caption_box,
            "balloons": self.balloons,
            "complete": self.complete,
        }


def _px(box: Sequence[float], width: int, height: int) -> list[float]:
    return [box[0] * width, box[1] * height, box[2] * width, box[3] * height]


def _inter(a: Sequence[float], b: Sequence[float]) -> float:
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    return max(0.0, w) * max(0.0, h)


def _pad(box: Sequence[float], amount: float) -> list[float]:
    return [box[0] - amount, box[1] - amount, box[2] + amount, box[3] + amount]


def _font(path: Path, size: float) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(path), max(10, int(size)))


def letter_panel(
    image: Image.Image,
    *,
    heads: Mapping[str, Sequence[float]],
    free: Sequence[Sequence[float]],
    keep_out: Sequence[Sequence[float]] = (),
    caption: str = "",
    lines: Sequence[tuple[str, str]] = (),
    comms: Sequence[str] = (),
    step: int = 16,
    font_scale: float = 1.0,
) -> tuple[Image.Image, LetterReport]:
    """``font_scale``: QAR-M2-07 - panels shown smaller on a multi-panel page get bigger text,
    so dialogue stays readable at whole-page view."""
    im = image.convert("RGB").copy()
    draw = ImageDraw.Draw(im)
    width, height = im.size
    scale = width / REFERENCE_WIDTH * max(1.0, font_scale)
    report = LetterReport()

    head_px = {name.lower(): _px(box, width, height) for name, box in heads.items()}
    blocked = [_pad(box, 18 * scale) for box in head_px.values()]
    blocked += [_pad(_px(box, width, height), 10 * scale) for box in keep_out]
    free_px = [_px(box, width, height) for box in free]
    placed: list[list[float]] = []

    cap_font = _font(BODY_FONT, 30 * scale)
    capbox: list[float] | None = None
    if caption:
        wrapped_caption = textwrap.fill(caption, max(30, int(width / (17 * scale))))
        tb = draw.multiline_textbbox((0, 0), wrapped_caption, font=cap_font, spacing=4)
        cw, ch = tb[2] - tb[0] + 36 * scale, tb[3] - tb[1] + 26 * scale
        capbox = [0, 0, cw, ch]
        if any(_inter(capbox, b) > 0 for b in blocked):
            capbox = [0, height - ch, cw, height]
        placed.append(capbox)

    prev_top: float | None = None
    prev_right = 0.0
    comms_lower = {name.lower() for name in comms}
    for speaker, text in lines:
        head = head_px.get(speaker.lower())
        is_comms = speaker.lower() in comms_lower or head is None
        if head is None:
            # Off-screen speaker: aim at the nearest edge of the free space, comms balloon.
            head = [width * 0.02, height * 0.02, width * 0.08, height * 0.12]
        hx, hy = (head[0] + head[2]) / 2, head[1]
        best = None
        # M2 lettering fix (26/10/26): 7 of 10 balloons were dropped on a real chapter page
        # because the strict pass refuses any overlap with a keep-out box, and the vision
        # check returns enough keep-outs to blanket a dense panel. Placement now relaxes in
        # tiers instead of losing the line: faces are never covered; art first, then other
        # balloons, then a smaller size only as the last resort.
        head_blocked = [_pad(box, 18 * scale) for box in head_px.values()]
        attempts = (
            # Tier 1: strict - faces and the vision keep-out boxes.
            (blocked, (38, 34, 30)),
            # Tier 2 (Quan D1, 26/10/26: this used to be byte-identical to tier 1): art may
            # be covered, faces may not. A dense panel's keep-outs can blanket half of it.
            (head_blocked, (38, 34, 30)),
            # Tier 3: last resort - a smaller size, still never over a face.
            (head_blocked, (38, 34, 30, 26)),
        )
        for blockers, sizes in attempts:
            if best is not None:
                break
            for size in sizes:
                font = _font(BODY_FONT, size * scale)
                for wrap in (14, 18, 22, 28, 34):
                    wrapped = textwrap.fill(text, wrap)
                    tb = draw.multiline_textbbox((0, 0), wrapped, font=font, spacing=4, align="center")
                    tw, th = tb[2] - tb[0], tb[3] - tb[1]
                    bw, bh = int(tw * 1.32 + 50 * scale), int(th * 1.45 + 40 * scale)
                    if bw >= width - 20 or bh >= height - 20:
                        continue
                    stride = max(4, int(step * scale))
                    for x in range(10, max(11, width - bw - 10), stride):
                        for y in range(10, max(11, height - bh - 10), stride):
                            if prev_top is not None and not (
                                y >= prev_top + 30 * scale or (abs(y - prev_top) <= 60 * scale and x >= prev_right - 20 * scale)
                            ):
                                continue
                            box = [x, y, x + bw, y + bh]
                            if any(_inter(box, b) > 0 for b in blockers + placed):
                                continue
                            in_free = sum(_inter(box, f) for f in free_px) / (bw * bh)
                            dist = math.hypot(x + bw / 2 - hx, (y + bh - hy) * 1.3)
                            score = 1.6 * dist + 900 * (1 - min(in_free, 1)) + (400 if y + bh > hy + 40 * scale else 0) + 8 * (38 - size)
                            if best is None or score < best[0]:
                                best = (score, box, wrapped, font, bw, bh)
        if best is None:
            report.unplaced.append(f"{speaker}: {text}")
            continue
        _score, box, wrapped, font, bw, bh = best
        placed.append(box)
        prev_top, prev_right = box[1], box[2]
        cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
        tx, ty = (hx, (head[1] + head[3]) / 2) if is_comms else (hx, head[1] + (head[3] - head[1]) * 0.55)
        angle = math.atan2(ty - cy, tx - cx)
        ex, ey = cx + (bw / 2) * math.cos(angle), cy + (bh / 2) * math.sin(angle)
        length = math.hypot(tx - ex, ty - ey)
        tail = min(max(length - (head[3] - head[1]) * 0.35, 30 * scale), 480 * scale)
        tip = (ex + tail * math.cos(angle), ey + tail * math.sin(angle))
        perp = angle + math.pi / 2
        base = 26 * scale
        b1 = (cx + (bw / 2 - 30 * scale) * math.cos(angle) + base * math.cos(perp),
              cy + (bh / 2 - 20 * scale) * math.sin(angle) + base * math.sin(perp))
        b2 = (cx + (bw / 2 - 30 * scale) * math.cos(angle) - base * math.cos(perp),
              cy + (bh / 2 - 20 * scale) * math.sin(angle) - base * math.sin(perp))
        fill = "#e8fbff" if is_comms else "white"
        outline = max(2, int(4 * scale))
        draw.polygon([b1, b2, tip], fill=fill, outline="black", width=outline)
        if is_comms:
            draw.rounded_rectangle(box, radius=int(18 * scale), fill=fill, outline="black", width=outline + 1)
        else:
            draw.ellipse(box, fill=fill, outline="black", width=outline + 1)
        draw.polygon([(b1[0] * 0.9 + tip[0] * 0.1, b1[1] * 0.9 + tip[1] * 0.1),
                      (b2[0] * 0.9 + tip[0] * 0.1, b2[1] * 0.9 + tip[1] * 0.1), (cx, cy)], fill=fill)
        draw.multiline_text((cx, cy), wrapped, font=font, fill="black", anchor="mm", spacing=4, align="center")
        report.placed.append(speaker)
        report.balloons.append({"speaker": speaker, "box": [int(v) for v in box], "tip": [int(tip[0]), int(tip[1])], "comms": is_comms})

    if caption and capbox is not None:
        wrapped_caption = textwrap.fill(caption, max(30, int(width / (17 * scale))))
        draw.rectangle(capbox, fill="#fff3b0", outline="black", width=max(2, int(4 * scale)))
        draw.multiline_text((capbox[0] + 18 * scale, capbox[1] + 10 * scale), wrapped_caption, font=cap_font, fill="black", spacing=4)
        report.caption_box = [int(v) for v in capbox]
    return im, report
