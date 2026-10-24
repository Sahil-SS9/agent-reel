"""Panel prompts (M2 P2): one Script IR panel becomes one image request.

The shape is the one Sahil approved in bake-off round 2:
- **Shot and setting** first.
- **STAGING.** Each scripted character is placed LEFT, RIGHT or CENTRE. The first speaker goes on the LEFT, so balloons read left to right.
- **A model line.** Every character is "exactly as in reference sheet N".
- **The style card's prompt block**, then its staging rules (25% headroom), then its negative block (no text in the art, no extra characters).

Only the panel's scripted cast is named, and every one of them needs a kit.

The caption is post-gate text. It is passed as scene context so the picture shows what happened. The image never contains it: the negative block bans text, and lettering is added afterwards as SVG.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from canon.assets import CharacterKit, StyleCard

POSITIONS = ("LEFT", "RIGHT", "CENTRE")
ORDINALS = ("first", "second", "third", "fourth", "fifth", "sixth")
SHOT_WORDS = {"wide": "Establishing wide shot", "medium": "Medium shot", "close": "Close-up"}


class PromptError(ValueError):
    """A panel cannot be turned into a prompt (missing kit, too many characters)."""


@dataclass(frozen=True, slots=True)
class PanelRequest:
    panel_id: str
    prompt: str
    references: tuple[Path, ...]
    cast: tuple[str, ...]
    positions: Mapping[str, str]
    aspect: str


def _kit_for(name: str, kits: Mapping[str, CharacterKit]) -> CharacterKit | None:
    key = name.strip().lower().replace(" ", "-")
    if key in kits:
        return kits[key]
    for kit in kits.values():
        if kit.name.lower() == name.strip().lower():
            return kit
    return None


def staging_order(panel: Mapping[str, Any]) -> list[str]:
    """Speakers first, in the order they speak, then the rest of the scripted cast."""
    order: list[str] = []
    for line in panel.get("lines", []) or []:
        speaker = str(line.get("speaker", "")).strip()
        if speaker and speaker not in order:
            order.append(speaker)
    for name in panel.get("cast", []) or []:
        if name and name not in order:
            order.append(str(name))
    return order


def build_panel_request(
    panel: Mapping[str, Any],
    *,
    style: StyleCard,
    kits: Mapping[str, CharacterKit],
    aspect: str = "landscape",
) -> PanelRequest:
    cast = staging_order(panel)
    if len(cast) > len(POSITIONS):
        raise PromptError(f"panel {panel.get('id')} has {len(cast)} characters; at most {len(POSITIONS)}")
    resolved: list[tuple[str, CharacterKit]] = []
    for name in cast:
        kit = _kit_for(name, kits)
        if kit is None:
            raise PromptError(f"panel {panel.get('id')}: no character kit for {name!r}")
        resolved.append((name, kit))

    positions = {name: POSITIONS[index] for index, (name, _kit) in enumerate(resolved)}
    expression = str(panel.get("expression", "")).strip()
    pose = str(panel.get("pose", "")).strip()

    staging_bits: list[str] = []
    for index, (name, _kit) in enumerate(resolved):
        bit = f"{name.upper()} on the {positions[name]}"
        if index == 0 and (pose or expression):
            bit += ", " + ", ".join(part for part in (pose, expression) if part)
        staging_bits.append(bit)

    references = tuple(kit.sheet(style.key) for _name, kit in resolved)
    model_line = ", ".join(
        f"{name.upper()} is exactly as in the {ORDINALS[index]} reference sheet"
        for index, (name, _kit) in enumerate(resolved)
    )

    shot = SHOT_WORDS.get(str(panel.get("shot", "")), "Medium shot")
    setting = str(panel.get("setting", "")).strip() or "the rig"
    caption = str(panel.get("caption", "")).strip()
    parts = [f"{shot}, {setting}."]
    if staging_bits:
        parts.append("STAGING: " + "; ".join(staging_bits) + ".")
    else:
        parts.append("STAGING: no characters; an empty scene.")
    if caption:
        parts.append(f"The moment this panel shows: {caption}")
    if resolved:
        parts.append(
            f"Characters: {model_line} - keep everyone on-model (face, hair, outfit, colours, "
            "proportions). Draw no other people."
        )
    parts.append(style.prompt_block)
    if style.staging_rules:
        parts.append(style.staging_rules)
    parts.append(style.negative_block)
    return PanelRequest(
        panel_id=str(panel.get("id", "")),
        prompt=" ".join(part.strip() for part in parts if part.strip()),
        references=references,
        cast=tuple(name for name, _kit in resolved),
        positions=positions,
        aspect=aspect,
    )


def build_episode_requests(
    ir: Mapping[str, Any], *, style: StyleCard, kits: Mapping[str, CharacterKit]
) -> tuple[list[PanelRequest], list[str]]:
    """Requests for every panel, plus the reasons any panel could not be prompted."""
    requests: list[PanelRequest] = []
    problems: list[str] = []
    for panel in ir.get("panels", []) or []:
        try:
            requests.append(build_panel_request(panel, style=style, kits=kits))
        except PromptError as exc:
            problems.append(str(exc))
    return requests, problems


def episode_cast(ir: Mapping[str, Any]) -> list[str]:
    seen: list[str] = []
    for panel in ir.get("panels", []) or []:
        for name in staging_order(panel):
            if name not in seen:
                seen.append(name)
    return seen


__all__: Sequence[str] = (
    "PanelRequest",
    "PromptError",
    "build_episode_requests",
    "build_panel_request",
    "episode_cast",
    "staging_order",
)
