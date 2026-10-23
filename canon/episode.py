"""Episode planner and Script IR.

Two formats (decision D7): a weekly 4-6 panel strip, and an on-demand 8-12 panel
chapter. Both are built from one arc so each panel causes the next, and both carry
``source_event_ids`` on every line so a reader can trace any caption back to the
real session.

Dialogue comes from a writer. The template writer is deterministic and always
available; the model writer is cached, schema-checked and falls back to the
template rather than failing an episode.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Protocol, Sequence

from canon.arcs import ARC_ROLES, Arc
from canon.beats import Beat
from canon.canon import Canon
from canon.events import make_event_id
from canon.llm import CachedLLM, LLMError

SHOTS = ("wide", "medium", "close", "insert")

#: Role -> (shot, pose, expression, setting, panel caption prefix).
ROLE_STAGING: dict[str, tuple[str, str, str, str, str]] = {
    "setup": ("wide", "standing at the desk", "calm", "the rig at night", "SETUP"),
    "hidden_problem": ("medium", "half-turned toward the screen", "puzzled", "the rig", "SOMETHING IS WRONG"),
    "diagnosis": ("close", "leaning in", "narrow-eyed", "the terminal glow", "FOUND IT"),
    "climax": ("wide", "mid-action", "determined", "the rig, alarms implied", "NO MERCY"),
    "aftermath": ("medium", "sitting back", "tired relief", "the rig, quieter", "AFTER"),
    "win": ("wide", "arms folded", "satisfied", "the rig, morning light", "WIN"),
}

STRIP_ROLES = ARC_ROLES  # 6 panels: one per role
CHAPTER_EXTRA = ("insert", "insert")  # chapter adds detail beats


@dataclass(frozen=True, slots=True)
class Line:
    speaker: str
    text: str
    source_event_ids: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "speaker": self.speaker,
            "text": self.text,
            "source_event_ids": list(self.source_event_ids),
        }


@dataclass(frozen=True, slots=True)
class Panel:
    id: str
    role: str
    shot: str
    cast: tuple[str, ...]
    pose: str
    expression: str
    setting: str
    caption: str
    lines: tuple[Line, ...]

    def __post_init__(self) -> None:
        if self.shot not in SHOTS:
            raise ValueError(f"unknown shot: {self.shot!r}")

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "role": self.role,
            "shot": self.shot,
            "cast": list(self.cast),
            "pose": self.pose,
            "expression": self.expression,
            "setting": self.setting,
            "caption": self.caption,
            "lines": [line.as_dict() for line in self.lines],
        }


@dataclass(frozen=True, slots=True)
class EpisodeIR:
    episode_id: str
    season: int
    number: int
    format: str
    format_hints: tuple[str, ...]
    arc_ids: tuple[str, ...]
    logline: str
    panels: tuple[Panel, ...]
    writer: str

    def as_dict(self) -> dict[str, Any]:
        scene = {
            "id": f"{self.episode_id}-sc1",
            "setting": self.panels[0].setting if self.panels else "the rig",
            "cast": sorted({name for panel in self.panels for name in panel.cast}),
            "shots": [panel.id for panel in self.panels],
        }
        return {
            "episode_id": self.episode_id,
            "season": self.season,
            "number": self.number,
            "format": self.format,
            "format_hints": list(self.format_hints),
            "arc_ids": list(self.arc_ids),
            "logline": self.logline,
            "writer": self.writer,
            "panels": [panel.as_dict() for panel in self.panels],
            "scenes": [scene],
        }

    def to_json(self) -> str:
        return json.dumps(self.as_dict(), indent=1, sort_keys=True)

    def line_event_ids(self) -> list[str]:
        return [event_id for panel in self.panels for line in panel.lines for event_id in line.source_event_ids]

    def speakers(self) -> set[str]:
        return {line.speaker for panel in self.panels for line in panel.lines}


class DialogueWriter(Protocol):
    name: str

    def write(self, panels: Sequence[Mapping[str, Any]]) -> dict[str, list[list[str]]]:
        """Return {panel_role: [[speaker, text], ...]}."""


class TemplateDialogueWriter:
    """Deterministic dialogue: the beat summary, split into two beats of speech."""

    name = "template"

    def __init__(self, cast: Sequence[str], *, hero: str = "Sahil") -> None:
        self.cast = tuple(cast)
        self.hero = hero

    def _speaker_for(self, index: int) -> str:
        pool = [self.hero] + [name for name in self.cast if name != self.hero]
        return pool[index % len(pool)]

    def write(self, panels: Sequence[Mapping[str, Any]]) -> dict[str, list[list[str]]]:
        out: dict[str, list[list[str]]] = {}
        for index, panel in enumerate(panels):
            summary = str(panel.get("summary", "")).strip()
            speaker = self._speaker_for(index)
            other = self._speaker_for(index + 1)
            if not summary:
                out[panel["role"]] = []
                continue
            head, _, tail = summary.partition(":")
            text_main = (tail or head).strip()
            if len(text_main) > 120:
                cut = text_main.rfind(" ", 0, 120)
                text_main, text_rest = text_main[: cut if cut > 40 else 120], text_main[cut:]
            else:
                text_rest = ""
            lines = [[speaker, text_main.rstrip(" .,") + "."]]
            if text_rest.strip():
                lines.append([other, text_rest.strip()[:120]])
            out[panel["role"]] = lines
        return out


class LLMDialogueWriter:
    """Cached model dialogue, constrained to the cast and to one arc role at a time."""

    name = "llm"

    PROMPT = (
        "You write one panel of a weekly comic that replays an AI agent's real work. "
        "Hard rules: at most 2 speech lines per panel; each line at most 100 characters; "
        "speakers must come from the cast list; the panel must show the consequence of the "
        "previous panel; no text inside the image, dialogue only. "
        'Answer with JSON only: {"lines": [{"speaker": "...", "text": "..."}]}.'
    )

    def __init__(
        self,
        llm: CachedLLM,
        cast: Sequence[str],
        *,
        fallback: DialogueWriter | None = None,
        max_chars: int = 100,
    ) -> None:
        self.llm = llm
        self.cast = tuple(dict.fromkeys(cast))
        self.fallback = fallback
        self.max_chars = max_chars
        self.failures = 0

    def write(self, panels: Sequence[Mapping[str, Any]]) -> dict[str, list[list[str]]]:
        out: dict[str, list[list[str]]] = {}
        context: list[str] = []
        for panel in panels:
            payload = {
                "role": panel["role"],
                "cast": list(self.cast),
                "beat": panel.get("summary", ""),
                "previous": context[-1] if context else "",
                "setting": panel.get("setting", ""),
                "format": panel.get("format", "strip"),
            }
            try:
                response = self.llm.complete_json(
                    prompt=self.PROMPT,
                    payload=payload,
                    schema_hint={"lines": [{"speaker": "string", "text": "string"}]},
                    stage="episode.dialogue",
                )
                lines = self._validate(response)
            except (LLMError, ValueError):
                self.failures += 1
                lines = []
            if not lines and self.fallback is not None:
                lines = [
                    list(pair)
                    for pair in self.fallback.write([panel]).get(panel["role"], [])
                ]
            out[panel["role"]] = lines
            context.append(str(lines[0][1]) if lines else str(panel.get("summary", "")))
        return out

    def _validate(self, response: Mapping[str, Any]) -> list[list[str]]:
        rows = response.get("lines")
        if not isinstance(rows, list):
            raise ValueError("model returned no lines array")
        lines: list[list[str]] = []
        for row in rows[:2]:
            if not isinstance(row, Mapping):
                continue
            speaker = str(row.get("speaker", "")).strip()
            text = " ".join(str(row.get("text", "")).split())
            if speaker not in self.cast:
                raise ValueError(f"speaker not in cast: {speaker!r}")
            if not text:
                continue
            if len(text) > self.max_chars:
                text = text[: self.max_chars].rstrip() + "..."
            lines.append([speaker, text])
        if not lines:
            raise ValueError("model returned no usable lines")
        return lines


def _cast_for(beat: Beat | None, canon: Canon, hero: str) -> tuple[str, ...]:
    names: list[str] = [hero]
    if beat is not None and beat.profile and beat.profile not in names:
        names.append(beat.profile)
    return tuple(names)


def _caption(role: str, beat: Beat | None) -> str:
    label = ROLE_STAGING.get(role, ("", "", "", "", role.upper()))[4]
    if beat is None:
        return label
    import datetime as _dt

    stamp = _dt.datetime.fromtimestamp(beat.ts, tz=_dt.timezone.utc).strftime("%a %d %b %H:%M")
    return f"{stamp} \u00b7 {label}"


def plan_episode(
    arc: Arc,
    beats: Sequence[Beat],
    canon: Canon,
    *,
    format: str = "strip",
    season: int = 1,
    number: int = 1,
    writer: DialogueWriter | None = None,
    hero: str = "Sahil",
) -> EpisodeIR:
    """Plan an episode from one arc.

    ``format`` is ``strip`` (6 panels, one per arc role) or ``chapter`` (8-12
    panels: the six roles plus detail panels from the arc's own beats).
    """
    if format not in {"strip", "chapter"}:
        raise ValueError(f"unknown format: {format!r}")
    by_id = {beat.id: beat for beat in beats}
    roles = [role for role in STRIP_ROLES if role in arc.roles]
    if not roles:
        raise ValueError("arc has no roles to plan from")

    panel_specs: list[dict[str, Any]] = []
    for role in roles:
        beat = by_id.get(arc.roles[role])
        shot, pose, expression, setting, _ = ROLE_STAGING[role]
        panel_specs.append(
            {
                "role": role,
                "beat": beat,
                "shot": shot,
                "pose": pose,
                "expression": expression,
                "setting": setting,
                "summary": beat.summary if beat else "",
                "format": format,
            }
        )

    if format == "chapter":
        # Detail panels: the arc's own beats that no role used, up to 12 panels.
        used = set(arc.roles.values())
        extra = [beat for beat in beats if beat.id not in used and len(panel_specs) < 10]
        for beat in extra:
            panel_specs.insert(
                max(1, len(panel_specs) - 2),
                {
                    "role": "insert",
                    "beat": beat,
                    "shot": "insert",
                    "pose": "detail of the screen",
                    "expression": "n/a",
                    "setting": "the terminal glow",
                    "summary": beat.summary,
                    "format": format,
                },
            )

    cast = sorted({name for spec in panel_specs for name in _cast_for(spec["beat"], canon, hero)})
    active_writer = writer or TemplateDialogueWriter(cast, hero=hero)
    dialogue = active_writer.write(panel_specs)

    panels: list[Panel] = []
    for index, spec in enumerate(panel_specs, start=1):
        beat: Beat | None = spec["beat"]
        role = spec["role"]
        event_ids = tuple(beat.event_ids) if beat else tuple()
        if not event_ids:
            continue
        cast_names = _cast_for(beat, canon, hero)
        speakers = dialogue.get(role, [])
        lines: list[Line] = []
        for speaker, text in speakers:
            if speaker not in cast_names:
                continue
            lines.append(Line(speaker=speaker, text=text, source_event_ids=event_ids))
        if not lines:
            # A panel with no line is still a panel (silent beat), but every panel
            # that has text must trace to events, so the template fills the gap.
            fallback = TemplateDialogueWriter(cast_names, hero=hero).write([spec]).get(role, [])
            for speaker, text in fallback:
                lines.append(Line(speaker=speaker, text=text, source_event_ids=event_ids))
        panels.append(
            Panel(
                id=f"{arc.id[-12:]}-p{index}",
                role=role,
                shot=spec["shot"],
                cast=cast_names,
                pose=spec["pose"],
                expression=spec["expression"],
                setting=spec["setting"],
                caption=_caption(role, beat),
                lines=tuple(lines),
            )
        )

    logline = f"{arc.title}: {arc.stakes}"
    return EpisodeIR(
        episode_id=make_event_id("episode", format, arc.opened, {"arc": arc.id, "n": number}),
        season=season,
        number=number,
        format=format,
        format_hints=("6-panel grid", "vertical strip", "x 3x2") if format == "strip" else ("8-12 panel chapter", "vertical strip"),
        arc_ids=(arc.id,),
        logline=logline,
        panels=tuple(panels),
        writer=getattr(active_writer, "name", "unknown"),
    )


def validate_ir(ir: EpisodeIR, *, known_event_ids: Iterable[str]) -> list[str]:
    """Every IR line must resolve to a real gated event id. Returns problems."""
    known = set(known_event_ids)
    problems: list[str] = []
    if not ir.panels:
        problems.append("episode has no panels")
    for panel in ir.panels:
        if not panel.lines:
            problems.append(f"panel {panel.id} has no lines")
        for line in panel.lines:
            if not line.source_event_ids:
                problems.append(f"line by {line.speaker} in {panel.id} has no source_event_ids")
            for event_id in line.source_event_ids:
                if event_id not in known:
                    problems.append(f"{panel.id}: unknown source event id {event_id}")
    return problems
