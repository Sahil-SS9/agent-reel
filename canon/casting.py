"""The cast: profiles are agents, not labels (audit M1-F6).

A panel that says "default: ..." is showing a database column, not a character.
This module maps a Hermes profile onto a display name once, and everything downstream
(panel cast, speakers, canon) uses the display name.

``default`` is the main profile, and on this rig that is KENSEI.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

#: Explicit overrides. Anything else is derived from the profile id.
DEFAULT_NAMES: dict[str, str] = {
    "default": "Kensei",
    "kensei": "Kensei",
    "kensei-review": "The Reviewer",
    "triage-router": "The Router",
}

#: Roles that read as people rather than machines.
ROLE_PREFIXES = ("mrhermagi", "gojo", "dezzy", "ceecee", "quan")


def display_name(profile: str, mapping: Mapping[str, str] | None = None) -> str:
    """Profile id -> character name. Unknown ids are title-cased, never dropped."""
    if not profile:
        return ""
    table = dict(DEFAULT_NAMES)
    if mapping:
        table.update({str(key): str(value) for key, value in mapping.items()})
    if profile in table:
        return table[profile]
    parts = [part for part in profile.replace("_", "-").split("-") if part]
    if not parts:
        return profile
    # "octacon-backend" -> "Octacon"; "quan-security" -> "Quan"
    if parts[0] in {"kensei"}:
        return "Kensei"
    return parts[0].capitalize()


def build_cast_map(profiles: Sequence[str], *, hero: str = "Sahil") -> dict[str, str]:
    cast = {profile: display_name(profile) for profile in sorted(set(profiles)) if profile}
    cast.setdefault("default", "Kensei")
    cast[hero] = hero
    return cast


def to_display(profile: str, cast_map: Mapping[str, str]) -> str:
    return cast_map.get(profile, display_name(profile))


def speaker_for(profile: str, cast_map: Mapping[str, str], *, hero: str) -> str:
    """A speaker must be a character: the hero or the agent's display name."""
    if not profile:
        return hero
    return to_display(profile, cast_map)


def summarise(cast_map: Mapping[str, str]) -> list[dict[str, Any]]:
    return [{"profile": key, "character": value} for key, value in sorted(cast_map.items())]
