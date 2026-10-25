"""Story tone (owner decision V16, 25/10/26): the user picks how the episode feels.

A tone is a short instruction for the writer (the words) and a hint for the director
(the pictures). Tones can be blended, either equally with ``comical+serious`` or weighted
with ``comical:70,serious:30``. ``auto`` picks a blend from the story itself.

A tone changes only the delivery: a joke, a hush or a hype line. It never changes what
happened. The truth rules apply to every tone the same way.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Mapping, Sequence

TONES: dict[str, tuple[str, str]] = {
    # name: (writer instruction, director hint)
    "witty": ("dry, witty dialogue with understated one-liners; plain and human",
              "cinematic and epic, with a wry touch in the expressions"),
    "comical": ("comedy first: banter, comic timing, exasperation and running gags; punchlines land on true moments",
                "cartoonish exaggerated expressions, sweat drops and reaction faces, slapstick energy, bright staging"),
    "serious": ("grounded and tense; few jokes; short, weighty lines; stakes felt, not explained",
                "moody, realistic lighting, restrained expressions, heavy shadows"),
    "quirky": ("offbeat and whimsical: odd metaphors, deadpan asides, characters noticing strange small things",
               "playful odd angles, surreal little background gags, whimsical props"),
    "epic": ("shonen hype: big declarations, rivalry, momentum, every win feels earned",
             "dynamic action, speed lines, heroic low angles, huge scale"),
    "wholesome": ("warm and encouraging; teamwork and small victories; gentle humour",
                  "soft warm light, friendly body language, cosy details"),
    "noir": ("hard-boiled: a world-weary narrator, clipped lines, rain-soaked metaphors",
             "high-contrast chiaroscuro, rain, neon reflections, smoky interiors"),
}
DEFAULT_TONE = "witty"

#: One example line per tone, so the writer hears the register (V16 tuning: an
#: instruction alone moved the delivery only slightly).
EXAMPLES: dict[str, str] = {
    "witty": "Kensei: 'The code is fine. The checker, less so.'",
    "comical": "Sahil: 'Eight attempts and NOT ONE passes? Brilliant. I'll just lie down, then.'",
    "serious": "Kensei: 'Eight candidates. None pass the rule as written.'",
    "quirky": "Kensei: 'The checker tripped over its own shoelaces. Five times. Same shoelace.'",
    "epic": "Kensei: 'Eight challengers entered. The rule still stands.'",
    "wholesome": "Sahil: 'None passed, but we know exactly why. That's a good night's work.'",
    "noir": "Narrator: 'Eight suspects. Every alibi checked out. None of them walked free.'",
}


@dataclass(frozen=True)
class Tone:
    parts: tuple[tuple[str, int], ...]  # (tone name, weight %)
    source: str = "chosen"  # chosen | auto

    @property
    def label(self) -> str:
        if len(self.parts) == 1:
            return self.parts[0][0]
        return " + ".join(f"{name} {weight}%" for name, weight in self.parts)

    def writer_text(self) -> str:
        examples = " ".join(f"Example of the register ({name}): {EXAMPLES[name]}" for name, _w in self.parts)
        if len(self.parts) == 1:
            body = TONES[self.parts[0][0]][0]
        else:
            body = "a blend - " + "; ".join(f"{weight}% {name}: {TONES[name][0]}" for name, weight in self.parts)
        return f"{body}. Commit to it: most lines should clearly sound like this. {examples} (Examples show voice only; never reuse their facts.)"

    def director_text(self) -> str:
        if len(self.parts) == 1:
            return TONES[self.parts[0][0]][1]
        return "; ".join(f"{name} ({weight}%): {TONES[name][1]}" for name, weight in self.parts)

    def as_dict(self) -> dict[str, object]:
        return {"label": self.label, "parts": [list(p) for p in self.parts], "source": self.source,
                "writer": self.writer_text(), "director": self.director_text()}


def parse_tone(text: str) -> Tone:
    """``comical``, ``comical+serious``, ``comical:70,serious:30`` (weights normalised to 100)."""
    value = (text or DEFAULT_TONE).strip().lower()
    items = [item for item in re.split(r"[+,]", value) if item.strip()]
    parts: list[tuple[str, float]] = []
    for item in items:
        name, _sep, weight = item.partition(":")
        name = name.strip()
        if name not in TONES:
            raise ValueError(f"unknown tone {name!r}; choose from {', '.join(TONES)} (or 'auto')")
        parts.append((name, float(weight) if weight.strip() else 1.0))
    if not parts:
        parts = [(DEFAULT_TONE, 1.0)]
    total = sum(w for _n, w in parts) or 1.0
    rounded = [(n, max(1, round(100 * w / total))) for n, w in parts]
    return Tone(tuple(rounded))


def auto_tone(*, drama: int, finished: bool, problems: Sequence[str] = ()) -> Tone:
    """A blend from the story itself: a hard fight with a win reads epic and funny, an
    unresolved struggle reads serious with a quirky edge, a calm success reads wholesome."""
    if drama >= 4 and finished:
        return Tone((("epic", 50), ("comical", 50)), source="auto")
    if drama >= 2 and not finished:
        return Tone((("serious", 60), ("quirky", 40)), source="auto")
    if finished:
        return Tone((("wholesome", 50), ("witty", 50)), source="auto")
    return Tone((("witty", 70), ("quirky", 30)), source="auto")


def tone_from_mapping(data: Mapping[str, object] | None) -> Tone | None:
    if not data or not data.get("parts"):
        return None
    return Tone(tuple((str(n), int(w)) for n, w in data["parts"]), source=str(data.get("source", "chosen")))  # type: ignore[union-attr]


__all__ = ("DEFAULT_TONE", "TONES", "Tone", "auto_tone", "parse_tone", "tone_from_mapping")
