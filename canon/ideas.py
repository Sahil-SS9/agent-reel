"""The idea deck: what makes chapter N look and read unlike chapter N-1.

The facts of an episode always come from the user's own gated history. The deck only
decides the frame: which conflict shape, which world, which genre, which villain
archetype, which visual motif and which opening shot. The draw is deterministic per
(seed, chapter number), so a chapter is reproducible, but it changes every chapter and
differs per user.

Combinations: 12 conflicts x 12 worlds x 8 genres x 12 villains x 10 motifs x 8 shots,
before the per-panel shot rotation - over a million distinct looks from one small file.
"""

from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path
from typing import Any, Mapping

DECK_PATH = Path(__file__).resolve().parents[1] / "assets" / "ideas" / "deck.json"

#: Keys the rest of the code reads. Order matters: it is the draw order.
SECTIONS = ("conflicts", "worlds", "genres", "villains", "motifs", "shots")


def load_deck(path: Path | None = None) -> dict[str, list[dict[str, str]]]:
    raw = json.loads((path or DECK_PATH).read_text(encoding="utf-8"))
    deck: dict[str, list[dict[str, str]]] = {}
    for section in SECTIONS:
        items = raw.get(section)
        if not isinstance(items, list) or not items:
            raise ValueError(f"idea deck: {section} is missing or empty")
        cleaned = [
            {"key": str(item["key"]), "label": str(item.get("label") or item.get("look") or item["key"])}
            for item in items
            if isinstance(item, Mapping) and item.get("key")
        ]
        if not cleaned:
            raise ValueError(f"idea deck: {section} has no usable entries")
        deck[section] = cleaned
    return deck


def combination_count(deck: Mapping[str, list[dict[str, str]]]) -> int:
    total = 1
    for section in SECTIONS:
        total *= len(deck[section])
    return total


def draw(
    seed: str,
    chapter: int,
    *,
    deck: Mapping[str, list[dict[str, str]]] | None = None,
    avoid: Mapping[str, list[str]] | None = None,
) -> dict[str, Any]:
    """One frame for one chapter.

    ``seed`` is the user's identity (hero name), so two users draw different frames.
    ``avoid`` lists keys already used, so a chapter does not repeat the previous look.
    """
    deck = deck or load_deck()
    rng = random.Random(f"{seed}:{int(chapter)}:{_digest(seed, chapter)}")
    avoid = avoid or {}
    frame: dict[str, Any] = {"seed": seed, "chapter": int(chapter)}
    for section in SECTIONS:
        items = deck[section]
        used = {str(k) for k in (avoid.get(section) or [])}
        pool = [item for item in items if item["key"] not in used] or items
        pick = rng.choice(pool)
        value = {"key": pick["key"], "label": pick["label"]}
        if section == "villains":
            value["look"] = _villain_look(deck, pick["key"])
        frame[section[:-1] if section.endswith("s") else section] = value
    return frame


def frame_prompt(frame: Mapping[str, Any]) -> str:
    """The one-line brief the director and the panel prompts both see."""
    bits = [
        f"conflict: {frame['conflict']['label']}",
        f"world: {frame['world']['label']}",
        f"genre: {frame['genre']['label']}",
        f"villain archetype: {frame['villain']['label']} ({frame['villain'].get('look', '')})",
        f"motif: {frame['motif']['label']}",
        f"opening shot: {frame['shot']['label']}",
    ]
    return "; ".join(bits)


def _villain_look(deck: Mapping[str, list[dict[str, str]]], key: str) -> str:
    raw = json.loads(DECK_PATH.read_text(encoding="utf-8")).get("villains") or []
    for item in raw:
        if isinstance(item, Mapping) and item.get("key") == key:
            return str(item.get("look") or "")
    return ""


def _digest(seed: str, chapter: int) -> str:
    return hashlib.sha256(f"{seed}|{chapter}".encode()).hexdigest()[:8]
