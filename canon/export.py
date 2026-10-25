"""Exports (M2 P6): pages, a vertical strip, social sizes, a caption draft and a sidecar.

Nothing is posted anywhere. The files land in the episode folder, and the user decides what to share.

- **page-N / page:** comic-book pages (V4): justified rows, big moments (setup, climax, win) across the full width, fillers and smaller beats side by side; ``page`` is page 1
- **chapter.pdf:** every page in one PDF, the comic-book version
- **x-wide:** X 16:9, 3 columns (1600×900)
- **x-square:** X 1:1 (1080×1080)
- **linkedin-wide:** LinkedIn 1.91:1 (1200×628)
- **linkedin-portrait:** LinkedIn 4:5 (1080×1350)
- **discord:** full page, at most 8 MB (Discord's upload limit)
- **strip:** a single vertical column (webtoon-style)

The caption draft and the sidecar carry only post-gate text. The sidecar keeps the source event ids for every line and caption, so any shared strip can be traced back.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from PIL import Image, ImageDraw, ImageFont

from canon.letterer import BODY_FONT, TITLE_FONT

SOCIAL_SIZES = {
    "x-wide": ((1600, 900), 3),
    "x-square": ((1080, 1080), 2),
    "linkedin-wide": ((1200, 628), 3),
    "linkedin-portrait": ((1080, 1350), 2),
}
DISCORD_MAX_BYTES = 8 * 1024 * 1024


@dataclass
class ExportSet:
    files: dict[str, Path]
    caption_draft: str

    def as_dict(self) -> dict[str, Any]:
        return {"files": {k: str(v) for k, v in self.files.items()}, "caption_draft": self.caption_draft}


def compose(panels: Sequence[Image.Image], cols: int, title: str, footer: str = "", credit: str = "") -> Image.Image:
    if not panels:
        raise ValueError("no panels to compose")
    pw = max(p.size[0] for p in panels)
    ph = max(p.size[1] for p in panels)
    scale = pw / 1536
    gap, head, foot = int(24 * scale) + 4, int(220 * scale) + 40, int(130 * scale) + 30
    rows = (len(panels) + cols - 1) // cols
    width = cols * pw + (cols + 1) * gap
    height = head + rows * ph + (rows + 1) * gap + foot
    page = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(page)
    title_font = ImageFont.truetype(str(TITLE_FONT), max(24, int(120 * scale)))
    small = ImageFont.truetype(str(BODY_FONT), max(14, int(32 * scale)))
    draw.text((width / 2, head / 2 + 10), title, font=title_font, fill="black", anchor="mm")
    lone_last = cols > 1 and len(panels) % cols == 1
    for index, panel in enumerate(panels):
        r, c = divmod(index, cols)
        x, y = gap + c * (pw + gap), head + gap + r * (ph + gap)
        if lone_last and index == len(panels) - 1:
            # A single panel on the last row is centred, not left with a blank beside it.
            x = (width - pw) // 2
        page.paste(panel.convert("RGB").resize((pw, ph)), (x, y))
        draw.rectangle([x, y, x + pw, y + ph], outline="black", width=max(3, int(8 * scale)))
    if footer:
        draw.text((width - gap, height - foot / 2), footer, font=small, fill="black", anchor="rm")
    if credit:
        draw.text((gap, height - foot / 2), credit, font=small, fill="#555", anchor="lm")
    return page


PAGE_WIDTH = 2400
PAGE_RATIO = 1.45  # content height / width before a page breaks (a comic page is ~1:1.5)
ROW_TARGET = 2.6  # a row is full once the panels' aspect ratios add up to this
MAX_ROW_HEIGHT = 0.62  # of the page width: a lone square or tall panel is not blown up
SOLO_ROLES = ("setup", "climax", "win")


def layout_rows(sizes: Sequence[tuple[int, int]], roles: Sequence[str]) -> list[list[int]]:
    """Group panels, in reading order, into rows. Big story moments get a row alone."""
    rows: list[list[int]] = []
    current: list[int] = []
    total = 0.0
    for index, (w, h) in enumerate(sizes):
        role = roles[index] if index < len(roles) else ""
        if role in SOLO_ROLES:
            if current:
                rows.append(current)
                current, total = [], 0.0
            rows.append([index])
            continue
        current.append(index)
        total += w / max(1, h)
        if total >= ROW_TARGET or len(current) == 3:
            rows.append(current)
            current, total = [], 0.0
    if current:
        rows.append(current)
    return rows


def _row_geometry(row: list[int], sizes: Sequence[tuple[int, int]], width: int, gap: int) -> tuple[int, list[int]]:
    ratios = [sizes[i][0] / max(1, sizes[i][1]) for i in row]
    usable = width - gap * (len(row) + 1)
    height = int(min(usable / sum(ratios), width * MAX_ROW_HEIGHT))
    return height, [int(height * r) for r in ratios]


def compose_pages(
    panels: Sequence[Image.Image],
    roles: Sequence[str],
    title: str,
    footer: str = "",
    credit: str = "",
    width: int = PAGE_WIDTH,
) -> list[Image.Image]:
    """Comic-book pages with justified rows (V4). Panels keep their own aspect; nothing is cropped."""
    if not panels:
        raise ValueError("no panels to compose")
    sizes = [p.size for p in panels]
    gap = max(12, width // 100)
    head, foot = int(width * 0.09), int(width * 0.05)
    title_font = ImageFont.truetype(str(TITLE_FONT), max(24, int(width * 0.05)))
    small = ImageFont.truetype(str(BODY_FONT), max(14, int(width * 0.014)))
    pages_rows: list[list[tuple[list[int], int, list[int]]]] = [[]]
    used = 0
    for row in layout_rows(sizes, roles):
        height, widths = _row_geometry(row, sizes, width, gap)
        limit = width * PAGE_RATIO - (head if len(pages_rows) == 1 else 0)
        if pages_rows[-1] and used + height + gap > limit:
            pages_rows.append([])
            used = 0
        pages_rows[-1].append((row, height, widths))
        used += height + gap
    pages: list[Image.Image] = []
    for number, rows in enumerate(pages_rows, start=1):
        top = head if number == 1 else gap * 2
        content = sum(h + gap for _r, h, _w in rows) + gap
        page = Image.new("RGB", (width, top + content + foot), "white")
        draw = ImageDraw.Draw(page)
        if number == 1:
            draw.text((width / 2, head / 2 + gap), title, font=title_font, fill="black", anchor="mm")
        y = top + gap
        for row, height, widths in rows:
            x = (width - (sum(widths) + gap * (len(widths) - 1))) // 2
            for index, w in zip(row, widths):
                page.paste(panels[index].convert("RGB").resize((w, height)), (x, y))
                draw.rectangle([x, y, x + w, y + height], outline="black", width=max(3, width // 400))
                x += w + gap
            y += height + gap
        last = number == len(pages_rows)
        right = footer if (last and footer) else (f"{number} / {len(pages_rows)}" if len(pages_rows) > 1 else "")
        if right:
            draw.text((width - gap, page.size[1] - foot / 2), right, font=small, fill="black", anchor="rm")
        if credit:
            draw.text((gap, page.size[1] - foot / 2), credit, font=small, fill="#555", anchor="lm")
        pages.append(page)
    return pages


def fit(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    """Letterbox ``image`` into exactly ``size`` on white, never cropping a panel."""
    canvas = Image.new("RGB", size, "white")
    copy = image.copy()
    copy.thumbnail(size)
    canvas.paste(copy, ((size[0] - copy.size[0]) // 2, (size[1] - copy.size[1]) // 2))
    return canvas


def caption_draft(title: str, ir: Mapping[str, Any], *, hashtags: Sequence[str] = ("#HermesAgent",)) -> str:
    """A short post the owner can edit. Built from the episode's own captions only."""
    captions = [str(p.get("caption", "")).strip() for p in ir.get("panels", []) if str(p.get("caption", "")).strip()]
    body = captions[-1] if captions else ""
    lines = [title.strip()]
    if body:
        lines.append(body)
    if ir.get("cliffhanger"):
        lines.append("To be continued…")
    lines.append(" ".join(hashtags))
    return "\n\n".join(line for line in lines if line)


def sidecar(ir: Mapping[str, Any], *, style: str, render_report: Mapping[str, Any], checks: Sequence[Mapping[str, Any]],
            title: str = "") -> dict[str, Any]:
    import time as _time

    return {
        "episode_id": ir.get("episode_id"),
        "title": title or ir.get("logline", ""),
        # V13: the monthly book orders and filters episodes by when the story happened.
        "episode_time": float(ir.get("episode_time") or ir.get("resolved") or ir.get("opened") or _time.time()),
        "style": style,
        "panels": [
            {
                "id": p.get("id"),
                "caption": p.get("caption", ""),
                "caption_source_event_ids": list(p.get("caption_source_event_ids", [])),
                "lines": [
                    {"speaker": l.get("speaker"), "text": l.get("text"), "source_event_ids": list(l.get("source_event_ids", []))}
                    for l in p.get("lines", [])
                ],
            }
            for p in ir.get("panels", [])
        ],
        "render": dict(render_report),
        "checks": list(checks),
    }


def export_episode(
    lettered: Sequence[Image.Image],
    *,
    out_dir: Path,
    title: str,
    ir: Mapping[str, Any],
    style: str,
    render_report: Mapping[str, Any],
    checks: Sequence[Mapping[str, Any]],
    credit: str = "Hermes Scrollback Reel",
    roles: Sequence[str] | None = None,
) -> ExportSet:
    """``roles``: the role of each lettered panel (story roles or ``filler``), for layout."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    footer = "To be continued…" if ir.get("cliffhanger") else ""
    files: dict[str, Path] = {}
    for index, panel in enumerate(lettered, start=1):
        path = out / f"panel-{index}.jpg"
        panel.convert("RGB").save(path, quality=90)
        files[f"panel-{index}"] = path
    if roles is None:
        page = compose(lettered, 2, title, footer, credit)
        pages = [page]
    else:
        pages = compose_pages(lettered, roles, title, footer, credit)
        page = pages[0]
    for number, image in enumerate(pages, start=1):
        files[f"page-{number}"] = out / f"page-{number}.jpg"
        image.save(files[f"page-{number}"], quality=88, optimize=True)
    files["page"] = out / "page.jpg"
    page.save(files["page"], quality=88, optimize=True)
    files["chapter-pdf"] = out / "chapter.pdf"
    pages[0].save(files["chapter-pdf"], save_all=True, append_images=pages[1:], resolution=150)
    strip = compose(lettered, 1, title, footer, credit)
    files["strip"] = out / "strip.jpg"
    strip.save(files["strip"], quality=86, optimize=True)
    for name, (size, cols) in SOCIAL_SIZES.items():
        # A long chapter is shared by its first page; a short episode as one grid.
        grid = page if len(pages) > 1 or roles is not None else compose(lettered, cols, title, footer, credit)
        files[name] = out / f"{name}.jpg"
        fit(grid, size).save(files[name], quality=90)
    files["discord"] = out / "discord.jpg"
    quality = 88
    page.save(files["discord"], quality=quality, optimize=True)
    while files["discord"].stat().st_size > DISCORD_MAX_BYTES and quality > 40:
        quality -= 12
        page.save(files["discord"], quality=quality, optimize=True)
    draft = caption_draft(title, ir)
    files["caption"] = out / "caption.txt"
    files["caption"].write_text(draft + "\n", encoding="utf-8")
    files["sidecar"] = out / "sidecar.json"
    files["sidecar"].write_text(
        json.dumps(sidecar(ir, style=style, render_report=render_report, checks=checks, title=title), indent=1) + "\n",
        encoding="utf-8",
    )
    return ExportSet(files=files, caption_draft=draft)
