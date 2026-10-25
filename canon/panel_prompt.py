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


#: The IR names settings loosely ("the rig at night"); the image model then invents a
#: new location every panel (first M2 render: a waterfront, a mountain hangar, a boardroom).
#: These pin each named setting to one concrete place, and every panel says it is the same
#: place, so the strip reads as one scene.
SETTING_DESCRIPTIONS = {
    "the rig": "the owner's home office: one desk with several glowing monitors, a tower PC and a small server rack, cables, a desk lamp",
    "the terminal glow": "a close view of a glowing terminal screen on the desk in the same home office",
}
SAME_PLACE = "Every panel of this episode is set in this same room."


def describe_setting(setting: str) -> str:
    text = (setting or "").strip()
    lowered = text.lower()
    for key, description in SETTING_DESCRIPTIONS.items():
        if lowered.startswith(key):
            rest = text[len(key):].strip(" ,")
            return f"{description}{(', ' + rest) if rest else ''}"
    return text or SETTING_DESCRIPTIONS["the rig"]


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
    treatment: Any = None,
    villain: Any = None,
) -> PanelRequest:
    """``treatment``: a canon.director.PanelTreatment (V1); ``villain``: (name, look, sheet path)."""
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

    sheets = [kit.sheet_for(style.key) for _name, kit in resolved]
    references = tuple(path for path, _exact in sheets)
    identity_only = any(not exact for _path, exact in sheets)
    model_line = ", ".join(
        f"{name.upper()} is exactly as in the {ORDINALS[index]} reference sheet"
        for index, (name, _kit) in enumerate(resolved)
    )

    caption = str(panel.get("caption", "")).strip()
    if treatment is not None:
        from canon.director import ANGLE_WORDS, SHOT_WORDS as DIRECTOR_SHOTS

        shot = f"{DIRECTOR_SHOTS.get(treatment.shot, 'Medium shot')}, {ANGLE_WORDS.get(treatment.angle, 'eye-level camera')}"
        parts = [f"{shot}. Location: {treatment.location}. All panels of this episode share this world."]
    else:
        shot = SHOT_WORDS.get(str(panel.get("shot", "")), "Medium shot")
        setting = describe_setting(str(panel.get("setting", "")))
        parts = [f"{shot}, {setting}. {SAME_PLACE}"]
    if staging_bits:
        parts.append("STAGING: " + "; ".join(staging_bits) + ".")
    else:
        parts.append("STAGING: no people in this panel." if treatment is not None else "STAGING: no characters; an empty scene.")
    villain_shown = (
        treatment is not None and villain is not None and treatment.villain_presence != "absent"
    )
    if treatment is not None:
        parts.append(f"ACTION: {treatment.action}.")
        if getattr(treatment, "tone", ""):
            parts.append(f"VISUAL TONE: {treatment.tone}.")
        parts.append("Dynamic comic-book composition, dramatic lighting, cinematic energy.")
    if caption:
        parts.append(f"The real event behind this panel (for mood only, never write it): {caption}")
    if villain_shown:
        name, look, sheet = villain
        presence = {"lurking": "half-hidden in the shadows", "attacking": "attacking in full view",
                    "defeated": "defeated, breaking apart"}.get(treatment.villain_presence, "present")
        parts.append(f"VILLAIN: {name.upper()} ({look}), {presence}.")
        references = references + (Path(sheet),)
        villain_ref = f"{name.upper()} is exactly as in the {ORDINALS[len(resolved)]} reference sheet"
        model_line = f"{model_line}, {villain_ref}" if model_line else villain_ref
    if resolved or villain_shown:
        extra = " Draw no other people." if resolved else ""
        parts.append(
            f"Characters: {model_line} - keep everyone on-model (face, hair, outfit, colours, "
            f"proportions).{extra}"
        )
    if identity_only:
        parts.append(
            "The reference sheets fix WHO each character is (face, hair, build, outfit design); "
            "redraw them entirely in the art style described here, not in the sheets' style."
        )
    comic_rules = (
        "This is ONE PANEL of a comic page. Keep the top quarter of the frame as open "
        "background for speech balloons added later."
    )
    if style.raw_template:
        from canon.assets import INSERT_MARK

        scene = " ".join(part.strip() for part in parts if part.strip())
        mood = {"setup": "calm before the storm", "hidden_problem": "uneasy, ominous",
                "diagnosis": "tense, focused", "climax": "explosive, high stakes",
                "aftermath": "quiet, spent", "win": "triumphant", "filler": "atmospheric"}.get(
            str(panel.get("role", "")), "dramatic")
        body = (style.raw_template.replace(INSERT_MARK, scene)
                .replace("[REFERENCE]", "the character reference sheets supplied with this request")
                .replace("[MOOD]", mood))
        mood_line = "" if "[MOOD]" in style.raw_template else f" Mood of this panel: {mood}."
        prompt = f"{body}\n\nCOMIC PANEL RULES: {comic_rules}{mood_line} {style.staging_rules} {style.negative_block}".strip()
    else:
        parts.append(style.prompt_block)
        if style.staging_rules:
            parts.append(style.staging_rules)
        parts.append(style.negative_block)
        prompt = " ".join(part.strip() for part in parts if part.strip())
    return PanelRequest(
        panel_id=str(panel.get("id", "")),
        prompt=prompt,
        references=references,
        cast=tuple(name for name, _kit in resolved) + ((villain[0],) if villain_shown else ()),
        positions=positions,
        aspect=aspect,
    )


def build_episode_requests(
    ir: Mapping[str, Any],
    *,
    style: StyleCard,
    kits: Mapping[str, CharacterKit],
    treatment: Any = None,
    villain: Any = None,
) -> tuple[list[PanelRequest], list[str]]:
    """Requests for every panel, plus the reasons any panel could not be prompted."""
    requests: list[PanelRequest] = []
    problems: list[str] = []
    by_id = {str(p.get("id")): p for p in ir.get("panels", []) or []}
    if treatment is None:
        order = [(str(p.get("id")), None) for p in ir.get("panels", []) or []]
    else:
        order = treatment.sequence(ir)
    for pid, item in order:
        panel = by_id.get(pid) or filler_panel(item)
        try:
            requests.append(build_panel_request(
                panel, style=style, kits=kits, treatment=item, villain=villain,
                aspect=panel_aspect(str(panel.get("role", ""))) if treatment is not None else "landscape",
            ))
        except PromptError as exc:
            problems.append(str(exc))
    return requests, problems


#: V4 layout: big story moments are wide, fillers are tall, the rest square. Providers
#: may ignore the aspect when given reference sheets; the page layout copes either way.
SOLO_ROLES = ("setup", "climax", "win")


def panel_aspect(role: str) -> str:
    if role in SOLO_ROLES:
        return "landscape"
    if role == "filler":
        return "portrait"
    return "square"


def filler_panel(item: Any) -> dict[str, Any]:
    """A wordless panel spec for a director filler: no caption, no lines, nothing to ground."""
    return {
        "id": item.panel_id, "role": "filler", "shot": "medium", "setting": "",
        "cast": list(item.cast), "pose": "", "expression": "", "caption": "", "lines": [],
    }


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
