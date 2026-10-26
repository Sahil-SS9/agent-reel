"""Monthly comic book (owner decision V13, 25/10/26).

Collects a month's rendered episodes into one PDF:
- a cover with the month and the title
- a contents page
- every episode's pages, in date order

Each render folder is the output of ``render`` (``page-N.jpg`` / ``page.jpg`` plus
``sidecar.json``). Nothing is re-rendered and no model is called; it only lays out pages
that already exist. Harness-free (Pillow only).
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from PIL import Image, ImageDraw, ImageFont

from canon.letterer import BODY_FONT, TITLE_FONT

PAGE_SIZE = (2400, 3400)  # portrait comic page, ~A4 proportions


@dataclass
class BookEpisode:
    folder: Path
    title: str
    when: float
    pages: list[Path]
    style: str


def _pages(folder: Path) -> list[Path]:
    numbered = sorted(folder.glob("page-*.jpg"), key=lambda p: int(re.sub(r"\D", "", p.stem) or 0))
    if numbered:
        return numbered
    single = folder / "page.jpg"
    return [single] if single.is_file() else []


def find_episodes(roots: Iterable[Path]) -> list[BookEpisode]:
    """Every render folder (has sidecar.json and at least one page) under ``roots``."""
    found: dict[Path, BookEpisode] = {}
    for root in roots:
        root = Path(root).expanduser()
        candidates = [root] if (root / "sidecar.json").is_file() else [p.parent for p in root.rglob("sidecar.json")]
        for folder in candidates:
            pages = _pages(folder)
            if not pages or folder in found:
                continue
            try:
                sidecar = json.loads((folder / "sidecar.json").read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                sidecar = {}
            title = str(sidecar.get("title") or "")
            if not title:
                caption = folder / "caption.txt"
                title = caption.read_text(encoding="utf-8").splitlines()[0].strip() if caption.is_file() else folder.name
            when = float(sidecar.get("episode_time") or 0) or pages[0].stat().st_mtime
            found[folder] = BookEpisode(folder, title, when, pages, str(sidecar.get("style", "")))
    return sorted(found.values(), key=lambda e: e.when)


def in_month(episodes: Sequence[BookEpisode], month: str) -> list[BookEpisode]:
    """Episodes whose time falls in ``YYYY-MM`` (local time)."""
    if not month:
        return list(episodes)
    return [e for e in episodes if time.strftime("%Y-%m", time.localtime(e.when)) == month]


def _font(path: Path, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(path), size)


def _cover(title: str, subtitle: str, art: Path | None) -> Image.Image:
    page = Image.new("RGB", PAGE_SIZE, "#111")
    w, h = PAGE_SIZE
    if art is not None:
        image = Image.open(art).convert("RGB")
        image.thumbnail((w - 200, int(h * 0.6)))
        page.paste(image, ((w - image.size[0]) // 2, int(h * 0.25)))
    draw = ImageDraw.Draw(page)
    draw.text((w / 2, int(h * 0.12)), title, font=_font(TITLE_FONT, 190), fill="white", anchor="mm")
    draw.text((w / 2, int(h * 0.19)), subtitle, font=_font(BODY_FONT, 80), fill="#ddd", anchor="mm")
    draw.text((w / 2, h - 120), "Agent Reel", font=_font(BODY_FONT, 50), fill="#999", anchor="mm")
    return page


def _contents(episodes: Sequence[BookEpisode], first_page: int) -> Image.Image:
    page = Image.new("RGB", PAGE_SIZE, "white")
    draw = ImageDraw.Draw(page)
    w, _h = PAGE_SIZE
    draw.text((w / 2, 220), "Contents", font=_font(TITLE_FONT, 150), fill="black", anchor="mm")
    body = _font(BODY_FONT, 64)
    number = first_page
    y = 450
    for index, episode in enumerate(episodes, start=1):
        day = time.strftime("%d %b", time.localtime(episode.when))
        draw.text((200, y), f"{index}. {episode.title}"[:60], font=body, fill="black")
        draw.text((w - 200, y), f"{day}   p.{number}", font=body, fill="#444", anchor="ra")
        number += len(episode.pages)
        y += 110
    return page


def _fit(path: Path) -> Image.Image:
    image = Image.open(path).convert("RGB")
    canvas = Image.new("RGB", PAGE_SIZE, "white")
    image.thumbnail((PAGE_SIZE[0] - 120, PAGE_SIZE[1] - 160))
    canvas.paste(image, ((PAGE_SIZE[0] - image.size[0]) // 2, (PAGE_SIZE[1] - image.size[1]) // 2))
    return canvas


def build_book(episodes: Sequence[BookEpisode], out: Path, *, title: str, subtitle: str) -> dict[str, object]:
    if not episodes:
        raise ValueError("no rendered episodes to put in the book")
    first_art = episodes[0].folder / "panel-1.jpg"
    pages: list[Image.Image] = [_cover(title, subtitle, first_art if first_art.is_file() else episodes[0].pages[0])]
    pages.append(_contents(episodes, first_page=3))
    numbers = 3
    for episode in episodes:
        for path in episode.pages:
            image = _fit(path)
            ImageDraw.Draw(image).text((PAGE_SIZE[0] / 2, PAGE_SIZE[1] - 50), str(numbers),
                                       font=_font(BODY_FONT, 40), fill="#666", anchor="mm")
            pages.append(image)
            numbers += 1
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    pages[0].save(out, save_all=True, append_images=pages[1:], resolution=200)
    return {"pdf": str(out), "episodes": len(episodes), "pages": len(pages),
            "titles": [e.title for e in episodes]}


__all__ = ("BookEpisode", "build_book", "find_episodes", "in_month")
