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
from dataclasses import dataclass, field, replace
from typing import Any, Iterable, Mapping, Protocol, Sequence

from canon.arcs import ARC_ROLES, Arc
from canon.beats import Beat
from canon.casting import build_cast_map, speaker_for
from canon.canon import Canon
from canon.events import make_event_id
from canon.grounding import ClaimGate, ClaimReport, GroundingReport
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
    #: The fact caption: a plain, grounded sentence (narrator box).
    caption: str
    lines: tuple[Line, ...]
    #: The date/role label, kept separate so the caption can carry the facts.
    label: str = ""

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
            "label": self.label,
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
    grounding: Mapping[str, Any] = field(default_factory=dict)
    cliffhanger: bool = False

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
            "grounding": dict(self.grounding),
            "cliffhanger": self.cliffhanger,
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
    """Deterministic two layers: a fact caption plus claim-free reactions.

    The caption states what the evidence says. The dialogue adds tone only - it makes
    no claim, so it cannot be wrong, and it reads better than a truncated task title.
    """

    name = "template"

    #: Reactions carry no claim (round 3: pure register passes grounding).
    REACTIONS = (
        "Okay.", "Right.", "That's the one.", "Ugh.", "Of course.", "Here we go.",
        "Not again.", "Fine.", "Naturally.", "Typical.",
    )

    def __init__(self, cast: Sequence[str], *, hero: str = "Sahil") -> None:
        self.cast = tuple(cast) or (hero,)
        self.hero = hero

    def _speaker_for(self, index: int) -> str:
        pool = [self.hero] + [name for name in self.cast if name != self.hero]
        return pool[index % len(pool)]

    def caption_for(self, panel: Mapping[str, Any]) -> str:
        summary = str(panel.get("summary", "")).strip()
        if not summary:
            evidence = str(panel.get("evidence", "")).strip()
            return " ".join(evidence.split()[:12])
        if ": " in summary:
            summary = summary.split(": ", 1)[1]
        words = summary.split()
        if len(words) > 14:
            summary = " ".join(words[:14]).rstrip(" ,;:") + "."
        return summary

    def write(self, panels: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for index, panel in enumerate(panels):
            actors = list(panel.get("actors") or [])
            if actors:
                speaker = actors[index % len(actors)]
                reaction = self.REACTIONS[index % len(self.REACTIONS)]
                lines = [[speaker, reaction]]
            else:
                # Nobody is an actor of this panel's events. The owner may still react:
                # a claim-free reaction cannot misattribute a fact (R2-F2).
                reaction = self.REACTIONS[index % len(self.REACTIONS)]
                lines = [[self.hero, reaction]]
            out[panel["role"]] = {
                "caption": self.caption_for(panel),
                "lines": lines,
            }
        return out


class LLMDialogueWriter:
    """Cached model dialogue, constrained to the cast and to one arc role at a time."""

    name = "llm"

    PROMPT = (
        "You write one panel of a weekly comic that replays an AI agent's real work. "
        "Return two layers. "
        'JSON only: {"caption": "...", "lines": [{"speaker": "...", "text": "..."}]}. '
        "caption: ONE plain factual sentence, narrator voice, using only what the "
        "evidence says. No cause, no outcome, no number, no name that the evidence does "
        "not contain. "
        "lines: at most 2; each under 100 characters; speakers must be from the cast "
        "list AND must be the actor of a cited event. Dialogue MAY dramatise tone, "
        "emotion, sarcasm and metaphor - it may NOT add a fact: no new names, numbers, "
        "causes, outcomes or tools. A pure reaction is ideal when the evidence is thin. "
        "No text inside the image."
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
                "cast": list(panel.get("actors") or self.cast),
                "beat": panel.get("summary", ""),
                "evidence": panel.get("evidence", ""),
                "previous": context[-1] if context else "",
                "setting": panel.get("setting", ""),
                "format": panel.get("format", "strip"),
            }
            try:
                response = self.llm.complete_json(
                    prompt=self.PROMPT,
                    payload=payload,
                    schema_hint={
                        "caption": "string",
                        "lines": [{"speaker": "string", "text": "string"}],
                    },
                    stage="episode.dialogue",
                )
                caption, lines = self._validate(response)
            except (LLMError, ValueError):
                self.failures += 1
                caption, lines = "", []
            if not lines and self.fallback is not None:
                fallback = self.fallback.write([panel]).get(panel["role"], {})
                caption = caption or str(fallback.get("caption", ""))
                lines = [list(pair) for pair in fallback.get("lines", [])]
            out[panel["role"]] = {"caption": caption, "lines": lines}
            context.append(lines[0][1] if lines else str(panel.get("summary", "")))
        return out

    def _validate(self, response: Mapping[str, Any]) -> tuple[str, list[list[str]]]:
        rows = response.get("lines")
        if not isinstance(rows, list):
            raise ValueError("model returned no lines array")
        caption = " ".join(str(response.get("caption", "")).split())
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
        if not lines and not caption:
            raise ValueError("model returned neither a caption nor a usable line")
        return caption, lines


def _cast_for(
    beat: Beat | None,
    canon: Canon,
    hero: str,
    cast_map: Mapping[str, str] | None = None,
) -> tuple[str, ...]:
    """Panel cast in character names, never profile ids (audit M1-F6)."""
    mapping = cast_map or {}
    names: list[str] = [hero]
    if beat is not None and beat.profile:
        character = speaker_for(beat.profile, mapping, hero=hero)
        if character and character not in names:
            names.append(character)
    return tuple(names)


def _label(role: str, beat: Beat | None) -> str:
    label = ROLE_STAGING.get(role, ("", "", "", "", role.upper()))[4]
    if beat is None:
        return label
    import datetime as _dt
    from zoneinfo import ZoneInfo

    # Audit M1-F6: captions read in the owner's timezone, not UTC.
    try:
        zone = ZoneInfo("Europe/London")
    except Exception:  # pragma: no cover - tzdata missing
        zone = _dt.timezone.utc
    stamp = _dt.datetime.fromtimestamp(beat.ts, tz=zone).strftime("%a %d %b %H:%M")
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
    grounder: ClaimGate | None = None,
    evidence: Mapping[str, str] | None = None,
    actors_by_event: Mapping[str, str] | None = None,
    cast_map: Mapping[str, str] | None = None,
    title: str | None = None,
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

    evidence_map = evidence or {}

    def _evidence_for(beat: Beat | None) -> str:
        if beat is None:
            return ""
        chunks = [str(evidence_map.get(event_id, "")) for event_id in beat.event_ids]
        return "\n".join(chunk for chunk in chunks if chunk)

    actors_map = actors_by_event or {}

    def allowed_speakers(beat: Beat | None, cast_names: Sequence[str]) -> set[str]:
        """Who may speak this panel: the actors of its cited events (audit R2-F2).

        Enforcement needs attribution data. When the caller supplies none (unit tests,
        or a source without actor fields) the cast is the bound.
        """
        if beat is None:
            return set()
        if not actors_map:
            return set(cast_names)
        actors = {actors_map.get(event_id, "") for event_id in beat.event_ids} - {""}
        return {actor for actor in actors if actor in cast_names}

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
                "evidence": _evidence_for(beat),
                "cast": _cast_for(beat, canon, hero, cast_map),
                "actors": [],
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

    for spec in panel_specs:
        # Chapter-mode detail panels are built inline, so default their cast here.
        spec.setdefault("cast", _cast_for(spec["beat"], canon, hero, cast_map))
        spec["actors"] = sorted(allowed_speakers(spec["beat"], spec["cast"]))
    cast = sorted({name for spec in panel_specs for name in spec["cast"]})
    active_writer = writer or TemplateDialogueWriter(cast, hero=hero)
    dialogue = active_writer.write(panel_specs)

    report = GroundingReport()
    seen_text: set[str] = set()
    panels: list[Panel] = []
    actors_map = actors_by_event or {}

    for index, spec in enumerate(panel_specs, start=1):
        beat: Beat | None = spec["beat"]
        role = spec["role"]
        event_ids = tuple(beat.event_ids) if beat else tuple()
        if not event_ids:
            continue
        cast_names = tuple(spec.get("cast") or ())
        evidence_text = str(spec.get("evidence", ""))
        speakers_allowed = set(spec.get("actors") or ())
        written = dialogue.get(role, {})

        # ---- layer 1: the fact caption -----------------------------------
        caption = str(written.get("caption", "")).strip() if isinstance(written, dict) else ""
        if not caption:
            caption = TemplateDialogueWriter(cast_names, hero=hero).caption_for(spec)
        if grounder is not None and caption:
            report.captions += 1
            verdict = grounder.check(caption, evidence_text, layer="caption")
            if verdict.supported:
                report.captions_supported += 1
            else:
                repaired = grounder.literal_caption(evidence_text)
                report.reasons.append(f"{role} caption: {verdict.reason}")
                if repaired:
                    caption = repaired
                    report.captions_repaired += 1
                    report.captions_supported += 1
                else:
                    caption = ""
        caption_key = caption.lower().strip()
        if caption_key and caption_key in seen_text:
            caption = ""

        # ---- layer 2: dialogue -------------------------------------------
        lines: list[Line] = []
        duplicates: list[Line] = []
        for speaker, text in (written.get("lines") if isinstance(written, dict) else []) or []:
            def claim_free(text: str) -> bool:
                from canon.grounding import extract_claims

                return not extract_claims(text)

            if speaker not in speakers_allowed and not (speaker == hero and claim_free(text)):
                # Audit R2-F2: never put words in someone's mouth. The line becomes
                # narrator text if it survives grounding as a caption.
                if grounder is not None:
                    report.lines += 1
                    verdict = grounder.check(text, evidence_text, layer="caption")
                    if verdict.supported and not caption:
                        caption = text
                        caption_key = caption.lower().strip()
                        report.lines_converted += 1
                        continue
                report.lines_dropped += 1
                report.reasons.append(f"{role}: speaker {speaker!r} is not an actor")
                continue
            candidate = text
            if grounder is not None:
                report.lines += 1
                verdict = grounder.check(candidate, evidence_text, layer="dialogue")
                if verdict.supported:
                    report.lines_supported += 1
                else:
                    report.lines_dropped += 1
                    report.reasons.append(f"{role} line: {verdict.reason}")
                    continue
            key = candidate.lower().strip()
            if not key:
                report.lines_dropped += 1
                continue
            line = Line(speaker=speaker, text=candidate, source_event_ids=event_ids)
            if key in seen_text:
                duplicates.append(line)
                report.lines_dropped += 1
                continue
            seen_text.add(key)
            lines.append(line)
        if not lines and duplicates:
            lines.append(duplicates[0])
        if not caption and not lines:
            # Nothing survived and there is nothing to quote: state the event itself,
            # which is grounded by construction, or leave the panel out.
            tags = " ".join(beat.tags) if beat is not None and beat.tags else ""
            structural = " ".join(
                part for part in (beat.type.replace("-", " ") if beat else "", tags) if part
            ).strip()
            if not structural:
                continue
            caption = structural
            caption_key = caption.lower().strip()
        if caption_key:
            seen_text.add(caption_key)

        panels.append(
            Panel(
                id=f"{arc.id[-12:]}-p{index}",
                role=role,
                shot=spec["shot"],
                cast=cast_names,
                pose=spec["pose"],
                expression=spec["expression"],
                setting=spec["setting"],
                caption=caption,
                label=_label(role, beat),
                lines=tuple(lines),
            )
        )

    # ---- the arc ends properly (round 3, item 4) --------------------------
    cliffhanger = arc.status != "resolved"
    if cliffhanger and panels:
        last = panels[-1]
        panels[-1] = replace(
            last,
            label=(last.label + " \u00b7 " if last.label else "") + "To be continued\u2026",
        )

    logline = f"{title or arc.title}: {arc.stakes}"
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
        grounding=report.as_dict(),
        cliffhanger=cliffhanger,
    )


def validate_ir(ir: EpisodeIR, *, known_event_ids: Iterable[str]) -> list[str]:
    """Every IR line must resolve to a real gated event id. Returns problems."""
    known = set(known_event_ids)
    problems: list[str] = []
    if not ir.panels:
        problems.append("episode has no panels")
    for panel in ir.panels:
        # A panel is carried by its fact caption, its dialogue, or both (round 3).
        if not panel.lines and not panel.caption:
            problems.append(f"panel {panel.id} has neither a caption nor a line")
        for line in panel.lines:
            if not line.source_event_ids:
                problems.append(f"line by {line.speaker} in {panel.id} has no source_event_ids")
            for event_id in line.source_event_ids:
                if event_id not in known:
                    problems.append(f"{panel.id}: unknown source event id {event_id}")
    return problems
