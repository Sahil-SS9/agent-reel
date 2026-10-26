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

import re

import json
from dataclasses import dataclass, field, replace
from typing import Any, Iterable, Mapping, Protocol, Sequence

from canon.arcs import ARC_ROLES, Arc
from canon.beats import Beat
from canon.casting import build_cast_map, speaker_for
from canon.canon import Canon
from canon.events import make_event_id
from canon.caption import (
    MAX_OWNER_QUOTE_WORDS,
    caption_problem,
    caption_problem,
    compose_caption,
    looks_like_provenance,
    trim_caption,
)
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
#: V4 (25/10/26): a chapter has up to 14 story panels (fillers come on top, in the
#: director), giving 16-24 panels over 3-4 pages.
CHAPTER_MAX_STORY = 14


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
    #: r10b / QAR10-03: the events the caption was judged against (the panel's own
    #: cited events; the thread's fact list is recorded per episode in the trace file).
    caption_source_event_ids: tuple[str, ...] = ()
    #: t_abdaa3a9: the panel's own anchoring events (its beat's ids). Citations are ranked
    #: against these, so the trace records them for a third-party replay.
    event_ids: tuple[str, ...] = ()

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
            "caption_source_event_ids": list(self.caption_source_event_ids),
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
    #: t_abdaa3a9: the exact runtime pool lines were cited from (story order) and the ids
    #: captions were cited from. Not part of the script IR; the trace archives them so
    #: every citation replays deterministically.
    citation_pool: Mapping[str, str] = field(default_factory=dict)
    caption_pool_ids: tuple[str, ...] = ()

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
        """Return {panel_key: ...}; the key is the role, or ``insert-N`` for chapter inserts."""


class TemplateDialogueWriter:
    """Deterministic two layers: a fact caption plus claim-free reactions.

    The caption states what the evidence says. The dialogue adds tone only - it makes
    no claim, so it cannot be wrong, and it reads better than a truncated task title.
    """

    name = "template"

    #: Reactions carry no claim (round 3: pure register passes grounding). Each is used
    #: at most once per episode; when they run out the panel is silent, because silence
    #: beats filler (round 4, R3-F5).
    REACTIONS = (
        "That's the one.", "Ugh.", "Of course.", "Here we go.", "Not again.",
        "Naturally.", "Typical.", "Finally.", "Well then.", "As expected.",
    )

    def __init__(self, cast: Sequence[str], *, hero: str = "Sahil") -> None:
        self.cast = tuple(cast) or (hero,)
        self.hero = hero
        self.used: set[str] = set()

    def _speaker_for(self, index: int) -> str:
        pool = [self.hero] + [name for name in self.cast if name != self.hero]
        return pool[index % len(pool)]

    def caption_for(self, panel: Mapping[str, Any]) -> str:
        """Nothing (round 8 / R7-F1).

        A caption is written prose, so the template writer does not produce one. Stitching
        actor + verb + object from a clipped input produced "Sahil wants please read and
        review this idea/concept." - mechanical, not readable.
        """
        return ""

    def _summary_caption(self, panel: Mapping[str, Any]) -> str:
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
        """Captions only (round 6, R5-F1).

        The template used to invent a line when the model gave none, and those lines were
        fragments ("Worked on …", "Reported …"). A panel now carries a caption, and a
        spoken line only when the writer actually wrote one. Silence is better than a
        truncated fragment in a character's mouth.
        """
        out: dict[str, dict[str, Any]] = {}
        for panel in panels:
            out[panel.get("key", panel["role"])] = {"caption": self.caption_for(panel), "lines": []}
        return out


class LLMDialogueWriter:
    """Cached model dialogue, constrained to the cast and to one arc role at a time."""

    name = "llm"

    PROMPT = (
        "You write one panel of a weekly comic that replays an AI agent's real work. "
        "Return two layers. "
        'JSON only: {"caption": "...", "lines": [{"speaker": "...", "text": "..."}]}. '
        "caption: ONE grammatical narrator sentence about this panel, written as prose - "
        "it must state the 'facts' line, may use the 'evidence' line for detail, and may "
        "state nothing that is in neither - on a climax or win panel it must state the "
        "RESULT itself, including any score or figure the evidence gives - "
        "subject, verb, object - in at most eighteen words. Build it from the 'facts' list, "
        "which is the only thing you may state: no cause, no outcome, no number and no name "
        "that the facts do not contain. Compress the facts into English; never paste a "
        "fragment of the source text, never open with 'X asked for' or 'X reported', and "
        "never quote the owner's words for more than six words in a row. If you cannot "
        "write a sentence that is both grammatical and true to the facts, return an empty "
        "caption. "
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
        story: Mapping[str, Any] | None = None,
    ) -> None:
        self.llm = llm
        self.cast = tuple(dict.fromkeys(cast))
        self.fallback = fallback
        self.max_chars = max_chars
        self.failures = 0
        #: V6-V8: {"synopsis": str, "voices": {name: voice}, "jobs": {role: job},
        #: "notes": {panel_key: editor note}}. None keeps the M1 per-panel prompt.
        self.story = dict(story) if story else None
        self.jargon_dropped = 0

    #: V6 (25/10/26): story mode writes the script in scenes of a few panels at a time,
    #: so panels connect, facts are not repeated and every character gets a voice.
    SCENE_PROMPT = (
        "You are writing a stretch of a comic script that retells real work with an AI agent, "
        "for a general reader. The pictures are epic; the words are plain, human and a little "
        "witty. You get the whole story (synopsis), the script so far, and the next panels: "
        "each with its job in the story, the facts it may use, the evidence behind them, and "
        "who may speak. Return JSON only: {\"panels\": [{\"key\": \"...\", \"caption\": \"...\", "
        "\"lines\": [{\"speaker\": \"...\", \"text\": \"...\"}]}]} with one entry per panel, same keys. "
        "Rules: dialogue carries the scene - at most 2 lines per panel, each under 90 characters, "
        "in the speaker's voice, only from that panel's speakers; give EVERY main character a "
        "voice across the stretch (Kensei is the AI agent and should speak, not only be described). "
        "A caption is optional (time, stakes, or a fact nobody would say aloud), at most 15 words. "
        "Translate engineering words for a general reader: say 'the database' not SQLite or "
        "PostgreSQL, 'the second job' not 'Handoff 2', 'the new version' not 'v2'. "
        "Never repeat a fact the script already stated. Each panel must move the story forward "
        "from the one before. Truth: every claim (what happened, who did it, why, a number, a "
        "name, an outcome) must be in that panel's facts or evidence or the synopsis; say it in "
        "plain English by what it meant. Tone, jokes and metaphor are free; new facts are not. "
        "Never show commit hashes, exit codes, file paths, task ids or tool names unless the name "
        "or number IS the story. Write in the requested TONE (it shapes delivery only, never "
        "the facts). If an editor note is given for a panel, fix exactly that."
    )
    SCENE_SIZE = 5

    def _write_story(self, panels: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
        from canon.story import jargon_problem

        story = self.story or {}
        voices = story.get("voices", {})
        notes = story.get("notes", {})
        out: dict[str, dict[str, Any]] = {}
        so_far: list[str] = []
        indexed = list(enumerate(panels, start=1))
        for start in range(0, len(indexed), self.SCENE_SIZE):
            chunk = indexed[start:start + self.SCENE_SIZE]
            items = []
            for position, panel in chunk:
                # Character names from the planner (who appears in this thread's evidence). The
                # writer's own cast list holds profile ids, so it must not filter these.
                speakers = list(dict.fromkeys(panel.get("speakers") or panel.get("actors") or self.cast))
                item = {
                    "key": panel.get("key", panel["role"]),
                    "job": story.get("jobs", {}).get(panel["role"], ""),
                    "facts": panel.get("fact_sentence", ""),
                    "evidence": str(panel.get("evidence", ""))[:700],
                    "speakers": speakers,
                }
                if notes.get(f"p{position}"):
                    item["editor_note"] = notes[f"p{position}"]
                items.append(item)
            cast_here = sorted({s for item in items for s in item["speakers"]})
            payload = {
                "tone": story.get("tone", ""),
                "synopsis": story.get("synopsis", ""),
                "script_so_far": so_far[-12:],
                "voices": {name: voices.get(name, "natural") for name in cast_here} | {"narrator": voices.get("narrator", "")},
                "panels": items,
            }
            try:
                response = self.llm.complete_json(
                    prompt=self.SCENE_PROMPT,
                    payload=payload,
                    schema_hint={"panels": [{"key": "string", "caption": "string", "lines": [{"speaker": "string", "text": "string"}]}]},
                    stage="episode.scene",
                )
                rows = response.get("panels")
                if not isinstance(rows, list):
                    raise ValueError("scene reply has no panels list")
            except (LLMError, ValueError):
                self.failures += 1
                rows = []
            by_key = {str(row.get("key")): row for row in rows if isinstance(row, Mapping)}
            for item in items:
                row = by_key.get(str(item["key"]), {})
                try:
                    caption, lines = self._validate(row, allowed=item["speakers"]) if row else ("", [])
                except ValueError:
                    caption, lines = "", []
                if caption and jargon_problem(caption):
                    caption = ""
                    self.jargon_dropped += 1
                kept = [line for line in lines if not jargon_problem(line[1])]
                self.jargon_dropped += len(lines) - len(kept)
                out[str(item["key"])] = {"caption": caption, "lines": kept}
                said = " / ".join(([caption] if caption else []) + [f"{s}: {t}" for s, t in kept])
                if said:
                    so_far.append(said)
        return out

    def write(self, panels: Sequence[Mapping[str, Any]]) -> dict[str, list[list[str]]]:
        if self.story is not None:
            return self._write_story(panels)  # type: ignore[return-value]
        out: dict[str, list[list[str]]] = {}
        context: list[str] = []
        for panel in panels:
            payload = {
                "role": panel["role"],
                "cast": list(panel.get("actors") or self.cast),
                "facts": panel.get("fact_sentence", ""),
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
            # Round 8 / R7-F1: no template caption and no template line. A panel whose
            # panel the model could not write stays empty and is dropped by the planner.
            # V4: keyed per panel - a chapter has several "insert" panels, and keying by
            # role made each one overwrite the last (all but one came back empty).
            out[panel.get("key", panel["role"])] = {"caption": caption, "lines": lines}
            context.append(lines[0][1] if lines else str(panel.get("summary", "")))
        return out

    def _validate(self, response: Mapping[str, Any], *, allowed: Sequence[str] | None = None) -> tuple[str, list[list[str]]]:
        allowed_names = set(allowed) if allowed is not None else set(self.cast)
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
            if speaker not in allowed_names:
                # A line for someone who was not there is dropped, not fatal: losing the
                # whole panel (caption included) over one bad speaker is worse.
                continue
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


def usable_anchor_count(
    beats: Sequence[Beat],
    *,
    brief: Any | None,
    evidence: Mapping[str, str] | None = None,
) -> int:
    """How many of these beats carry gated text in the brief (R3-F3)."""
    evidence_map = evidence or {}
    if brief is None:
        return len(beats)
    ids = {
        turn.get("event_id") if isinstance(turn, dict) else getattr(turn, "event_id", "")
        for turn in (getattr(brief, "turns", ()) or ())
    }
    text_ids = {str(event_id) for event_id in ids if str(evidence_map.get(str(event_id), "")).strip()}
    return sum(1 for beat in beats if any(event_id in text_ids for event_id in beat.event_ids))


def compose_caption_first(beat: Beat | None) -> str:
    """A last-resort caption from the beat's own type, never a dump."""
    if beat is None:
        return ""
    action = beat.type.replace("-", " ").replace("_", " ")
    return ""


_GENERIC_STOP = frozenset(
    "the a an and or of to in on at for with from by is was are were be it its this that "
    "these those i you we they my our their okay right ugh sure fine well here not again "
    "of course naturally typical finally expected then now".split()
)


def _is_generic(line: str, evidence_text: str, caption: str) -> bool:
    """A line is generic when it shares no content word with its panel's fact (R4-F3)."""
    haystack = f"{evidence_text} {caption}".lower()
    words = [w for w in re.findall(r"[a-z][a-z'\-]{2,}", (line or "").lower()) if w not in _GENERIC_STOP]
    if not words:
        return True
    return not any(word in haystack for word in words)


_QUESTION_RE = re.compile(r"[^.!?]*\?")


def story_evidence_pool(beats: Sequence[Beat], evidence: Mapping[str, str] | None) -> dict[str, str]:
    """The exact evidence every line and caption of an episode is cited from (t_abdaa3a9).

    One entry per story event that carries text, in story order (first occurrence). The
    planner ranks citations from this pool and the trace archives it unchanged, so a third
    party can replay every citation from the evidence folder alone.
    """
    evidence_map = evidence or {}
    pool: dict[str, str] = {}
    for beat in beats:
        for event_id in beat.event_ids:
            text = str(evidence_map.get(event_id, ""))
            if text.strip() and event_id not in pool:
                pool[event_id] = text
    return pool


def pool_digest(pool: Mapping[str, str]) -> str:
    """sha256 of an evidence pool, order included (the ranking's tie-break uses it)."""
    import hashlib
    import json

    payload = json.dumps([[str(k), str(v)] for k, v in pool.items()], ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def support_events(
    text: str,
    own_ids: Sequence[str],
    line_pool: Mapping[str, str],
    order: Sequence[str],
) -> tuple[list[str], str]:
    """The events that state what a line says, and their evidence blocks.

    The line is judged against exactly these events and cites exactly these ids, so a true
    fact from a different event cannot hide behind the panel's own ids.

    t_6950a3d0 (Quan): the events that *state* the line win over the panel's own ids. The
    earlier version pre-filled up to three own ids that merely overlapped, which crowded
    out the cross-panel event that actually stated the line; the judge then saw the wrong
    evidence and a true line was cited against it. Ranking comes first now, and an own id
    joins only if it clears the same support bar and there is room.
    """
    from canon.grounding import content_terms

    terms = {t[:6] for t in content_terms(text, allow=())}

    def overlap(event_id: str) -> int:
        return len(terms & {t[:6] for t in content_terms(line_pool.get(event_id, ""), allow=())})

    ranked = sorted(line_pool, key=lambda e: (-overlap(e), order.index(e)))
    best = overlap(ranked[0]) if ranked else 0
    # An event sharing only a stray word does not state the line: keep events whose
    # overlap is at least half the best one (takeover tightening).
    floor = max(1, (best + 1) // 2)
    chosen: list[str] = []
    for e in ranked:
        if len(chosen) >= 3 or overlap(e) < floor:
            break
        chosen.append(e)
    for e in own_ids:
        if len(chosen) >= 3:
            break
        if e in line_pool and overlap(e) >= floor and e not in chosen:
            chosen.append(e)
    chosen.sort(key=lambda e: -overlap(e))
    blocks = "\n\n".join(" ".join(line_pool[e].split()) for e in chosen)
    return chosen, blocks


def _states_something(line: str) -> bool:
    """True when the line asserts something a source must back (QAR-M2-01).

    Questions are removed first; a lone reaction word ("Understood.", "Okay.") is not a
    statement. Two or more content words outside a question are.
    """
    from canon.grounding import statement_content_terms

    return len(statement_content_terms(line, allow=())) >= 2


class EpisodeRefused(Exception):
    """The story cannot be told honestly; the pipeline records the reason and moves on."""


_COMPLETION_CUES = {
    "done", "finished", "complete", "completed", "green", "passed", "pass", "shipped",
    "landed", "fixed", "merged", "closed", "measured", "verified", "deployed",
}
_STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with", "at", "by",
    "is", "was", "were", "are", "it", "this", "that", "i", "we", "you", "they", "he",
    "she", "my", "our", "their", "as", "but", "so", "if", "then", "than", "from",
}


def _content_words(text: str) -> set[str]:
    return {
        word.strip(".,;:!?()[]\"'\u2014-").lower()
        for word in str(text or "").split()
        if word.strip(".,;:!?()[]\"'\u2014-").lower() not in _STOPWORDS
        and len(word.strip(".,;:!?()[]\"'\u2014-")) > 2
    }


def _ending_supported(
    panels: Sequence[Panel],
    facts: Sequence[Any],
    outcome_text: str,
    panel_evidence: str = "",
) -> tuple[bool, str]:
    """Is there a visible, sourced outcome for a finished thread?

    The strip may only export as complete when a panel actually shows the result. A panel
    that merely moves the story along is not an ending, and dropping the result panel must
    refuse the episode rather than quietly present a finished story without its outcome.
    """
    units = [str(getattr(fact, "sentence", "") or "") for fact in facts
             if getattr(fact, "kind", "") == "outcome"]
    units = [unit for unit in units if unit] or [outcome_text]
    units = [unit for unit in units if unit.strip()]
    if not units:
        # No structured outcome to judge against: the caller has no brief (tests, or a
        # thread whose brief could not be built). Nothing is claimed, so nothing to refuse.
        return True, ""
    shown = " ".join(
        [panel.caption for panel in panels if panel.caption]
        + [line.text for panel in panels for line in panel.lines]
        + [panel_evidence]
    )
    shown_words = _content_words(shown)
    shown_low = shown.lower()
    for unit in units:
        numbers = {token for token in unit.split() if any(ch.isdigit() for ch in token)}
        if numbers and any(number.strip(".,;:") in shown for number in numbers):
            return True, ""
        unit_words = _content_words(unit)
        if unit_words and len(unit_words & shown_words) >= min(3, max(1, len(unit_words) - 1)):
            return True, ""
        if unit_words & _COMPLETION_CUES and unit_words & shown_words:
            return True, ""
    return False, "no panel states it"


def _supporting_fact_ids(caption: str, facts: Sequence[Any]) -> tuple[str, ...]:
    """Event ids of thread facts that share content with the caption (r10b trace).

    A caption is judged against its panel's evidence *and* the thread's fact list, so a
    caption can be true because of a fact from another event. Those events are cited
    too, or the trace would point only at the panel and miss the real support.
    """
    stop = {"the", "and", "with", "that", "this", "from", "into", "wants", "sahil", "kensei"}

    def words(text: str) -> set[str]:
        return {w[:6] for w in re.findall(r"[a-z0-9]{4,}", (text or "").lower()) if w not in stop}

    mine = words(caption)
    out: list[str] = []
    for fact in facts or ():
        event_id = str(getattr(fact, "event_id", "") or "")
        source = f"{getattr(fact, 'object', '')} {getattr(fact, 'result', '')} {getattr(fact, 'source_text', '')}"
        if event_id and len(mine & words(source)) >= 2:
            out.append(event_id)
    return tuple(out)


def _supporting_event_ids(caption: str, pool: Mapping[str, str]) -> tuple[str, ...]:
    """Episode events whose own text directly states what the caption says (r10c).

    QAR10-03: "not a single file was modified" cited two read-only instructions while
    the event that actually said "No files were modified" sat in another panel. Any
    event already cited in this episode whose text shares most of the caption's content
    is cited as well.
    """
    stop = {"the", "and", "with", "that", "this", "from", "into", "wants", "sahil", "kensei"}

    def words(text: str) -> set[str]:
        return {
            w.rstrip("s")[:6]
            for w in re.findall(r"[a-z0-9]{4,}", (text or "").lower())
            if w not in stop
        }

    mine = words(caption)
    if len(mine) < 2:
        return ()
    # The best-matching event(s): every event tied for the highest shared-content count,
    # when that count is at least two. A half-the-caption bar missed the direct witness
    # "No files were modified" (2 shared words of an 8-word caption) on real data.
    scores = {event_id: len(mine & words(text)) for event_id, text in pool.items()}
    best = max(scores.values(), default=0)
    if best < 2:
        return ()
    return tuple(event_id for event_id, score in scores.items() if score == best)


def _verbatim_support(caption: str, pool: Mapping[str, str]) -> tuple[str, ...]:
    """Events whose text carries the caption's own figures or word-numbers (t_6950a3d0).

    ``_supporting_event_ids`` scores whole-word overlap, so a caption's most distinctive
    tokens ("23:16", "twelve") are lost among generic words like "test" and "run": the
    caption then cites events that merely mention tests. A figure or word-number that
    appears verbatim in an event is that event's claim, so it is cited first.
    """
    from canon.grounding import _NUMBER_WORD_RE, figures_in

    tokens = list(dict.fromkeys(figures_in(caption) + [m.group(0) for m in _NUMBER_WORD_RE.finditer(caption)]))
    out: list[str] = []
    for token in tokens:
        needle = token.lower()
        for event_id, text in pool.items():
            if needle in (text or "").lower() and event_id not in out:
                out.append(event_id)
    return tuple(out)


def caption_citation(
    caption: str, own_ids: Sequence[str], pool: Mapping[str, str], facts: Sequence[Any]
) -> tuple[str, ...]:
    """A caption's cited events, in citing order (shared by the planner and the replay)."""
    return tuple(
        dict.fromkeys(
            _verbatim_support(caption, pool)
            + tuple(own_ids)
            + _supporting_fact_ids(caption, facts)
            + _supporting_event_ids(caption, pool)
        )
    )


def line_kind(text: str) -> str:
    """``claim`` (an extractable claim token), ``statement`` or ``reaction``.

    Claims and statements cite only the events that state them; a reaction keeps the
    panel's own ids as context (shared by the planner and the replay).
    """
    from canon.grounding import extract_claims

    if extract_claims(text):
        return "claim"
    if _states_something(text):
        return "statement"
    return "reaction"


def _policy_caption(
    spec: Mapping[str, Any],
    *,
    candidate: str = "",
    seen: set[str] | None = None,
) -> str:
    """A written caption that passes the policy, or nothing (round 8 / R7-F1).

    Only the writer's own sentence can reach the page. Facts are evidence: turning them
    into prose by concatenation is what produced clipped, mechanical captions, so the
    planner refuses rather than fills.
    """
    for text in (candidate, trim_caption(candidate)):
        if not text or not acceptable_text(spec, text):
            continue
        if seen is not None and text.lower().strip() in seen:
            continue
        return text
    return ""


def acceptable_text(spec: Mapping[str, Any], text: str) -> bool:
    """The caption policy, usable from the repair and fallback paths."""
    if looks_like_provenance(text):
        return False
    if len(" ".join(text.split()).split()) < 3:
        return False
    return caption_problem(
        text,
        owner_texts=tuple(spec.get("owner_texts") or ()),
        max_owner_quote=MAX_OWNER_QUOTE_WORDS,
    ) == ""


def _logline(title: str, panels: Sequence[Panel]) -> str:
    """The header line: the title only (R5-F4).

    The header used to be the title plus a sentence lifted from the last panel, which made
    a 10-18 word line and sometimes carried the owner's raw message. It is now the title,
    and nothing else: if there is no title there is no header line.
    """
    return " ".join((title or "").split())


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
    brief: Any | None = None,
    structured_captions: Mapping[str, str] | None = None,
    thread_evidence: str = "",
    owner_texts: Sequence[str] = (),
    outcome_caption: str = "",
    facts: Sequence[Any] = (),
    facts_evidence: str = "",
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
    structured = structured_captions or {}

    # R3-F3: a panel is anchored on a beat that carries gated text in the brief. A beat
    # made of status churn has nothing true to say, so it is skipped rather than filled
    # with a fallback.
    brief_event_ids = {
        str(turn.get("event_id"))
        for turn in (getattr(brief, "turns", ()) or ())
        if isinstance(turn, dict)
    } or {turn.event_id for turn in (getattr(brief, "turns", ()) or ()) if not isinstance(turn, dict)}
    brief_text_ids = {event_id for event_id in brief_event_ids if str(evidence_map.get(event_id, "")).strip()}

    def usable(beat: Beat | None) -> bool:
        if beat is None:
            return False
        if brief is None:
            # Enforcement needs a brief. A caller that supplies none gets the old
            # contract; the pipeline always passes one.
            return True
        return any(event_id in brief_text_ids for event_id in beat.event_ids)

    def _evidence_for(beat: Beat | None) -> str:
        if beat is None:
            return ""
        # r10c: one blank-line-separated block per cited event, so an actor stays bound
        # to what its own event says (attribution_blocks in canon.grounding).
        chunks = [
            re.sub(r"\n\s*\n", "\n", str(evidence_map.get(event_id, ""))).strip()
            for event_id in beat.event_ids
        ]
        return "\n\n".join(chunk for chunk in chunks if chunk)

    actors_map = actors_by_event or {}

    # A speaker must appear in what the thread says. The fact list names who did what, so
    # it counts as evidence for eligibility even when the raw text never says the name.
    thread_haystack = " ".join(f"{thread_evidence}\n{facts_evidence}".lower().split())

    def in_thread_evidence(name: str) -> bool:
        needle = str(name).replace("-", " ").lower()
        return bool(needle) and needle in thread_haystack

    def allowed_speakers(beat: Beat | None, cast_names: Sequence[str]) -> set[str]:
        """Who may speak this panel.

        Round 4 (R3-F5) widens the round 3 rule: a line may name any thread cast member
        who appears in the thread's evidence, not only an actor of the panel's own
        events. The *claim* rule is unchanged - what the line says must still be backed
        by the events it cites.
        """
        if beat is None:
            return set()
        if thread_haystack:
            return {name for name in cast_names if in_thread_evidence(name)}
        if not actors_map:
            return set(cast_names)
        actors = {actors_map.get(event_id, "") for event_id in beat.event_ids} - {""}
        return {actor for actor in actors if actor in cast_names}

    # Round 6: the facts a panel may state, chosen by its role in the story.
    goal_facts = [fact for fact in facts if getattr(fact, "kind", "") == "goal"]
    turn_facts = [fact for fact in facts if getattr(fact, "kind", "") == "turn"]
    result_facts = [fact for fact in facts if getattr(fact, "kind", "") == "outcome"]
    used_facts: set[str] = set()

    def facts_for(role: str) -> str:
        if role == "setup" and goal_facts:
            return goal_facts[0].sentence
        if role in {"climax", "win"} and not result_facts:
            # No structured result: the first clause of the brief's outcome is the result
            # this panel must show (round 8 / R7-F2). Short, so a caption can state it.
            outcome_line = str(getattr(brief, "outcome", "") or "").strip()
            if outcome_line:
                first = outcome_line.replace("\n", " ").split(".")[0]
                words = first.split()[:14]
                return " ".join(words).rstrip(" ,;:-")
        if role in {"climax", "win"} and result_facts:
            for fact in result_facts:
                sentence = fact.sentence
                if sentence and sentence not in used_facts:
                    used_facts.add(sentence)
                    return sentence
            return ""
        for fact in turn_facts:
            sentence = fact.sentence
            if sentence and sentence not in used_facts:
                used_facts.add(sentence)
                return sentence
        return ""

    panel_specs: list[dict[str, Any]] = []
    for role in roles:
        beat = by_id.get(arc.roles[role])
        if not usable(beat):
            continue
        shot, pose, expression, setting, _ = ROLE_STAGING[role]
        fact_sentence = facts_for(role)
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
                # A caption comes from the fact list (round 6). The composed
                # "actor + verb + object" sentence is not a caption source: it produced
                # every template shape the audit refused.
                # The facts this panel may state, handed to the writer as its source. If the
                # thread has no unused fact left, the panel's own gated evidence is the
                # source - otherwise the writer starves on exactly the later panels.
                "fact_sentence": fact_sentence
                or " ".join(str(_evidence_for(beat)).split())[:220],
                "facts_only": bool(facts),
                "owner_texts": tuple(owner_texts),
                "actors": [],
                "format": format,
            }
        )

    if format == "chapter":
        # Detail panels: the arc's own beats that no role used, up to 12 panels.
        used = set(arc.roles.values())
        extra = [beat for beat in beats if beat.id not in used and usable(beat)]
        extra = extra[: max(0, CHAPTER_MAX_STORY - len(panel_specs))]
        for beat in extra:
            # V4: a development panel sits where it happened in time, between the roles.
            position = len(panel_specs)
            for index, spec in enumerate(panel_specs):
                if spec["beat"].ts > beat.ts:
                    position = index
                    break
            position = max(1, min(position, len(panel_specs) - 1))
            panel_specs.insert(
                position,
                {
                    "role": "insert",
                    "beat": beat,
                    "shot": "medium",
                    "pose": "working",
                    "expression": "focused",
                    "setting": "the rig",
                    "summary": beat.summary,
                    # V4: an insert gets the same sources as a role panel. Without them
                    # the writer had no facts and no evidence, so it (rightly) wrote nothing.
                    "evidence": _evidence_for(beat),
                    "fact_sentence": facts_for("insert")
                    or " ".join(str(_evidence_for(beat)).split())[:220],
                    "facts_only": bool(facts),
                    "owner_texts": tuple(owner_texts),
                    "actors": [],
                    "format": format,
                },
            )

    # QAR-M2-01: the actors of this story's events, and the evidence pool a line can cite.
    actor_lookup = actors_by_event or {}
    story_event_ids = [event_id for beat in beats for event_id in beat.event_ids]
    thread_actors = {actor_lookup[e] for e in story_event_ids if actor_lookup.get(e)}
    if thread_actors:
        thread_actors.add(hero)
    line_pool = story_evidence_pool(beats, evidence_map)

    def line_support(text: str, own_ids: Sequence[str]) -> tuple[list[str], str]:
        return support_events(text, own_ids, line_pool, list(line_pool))

    inserts = 0
    for spec in panel_specs:
        if spec["role"] == "insert":
            inserts += 1
            spec["key"] = f"insert-{inserts}"
        else:
            spec["key"] = spec["role"]
    for spec in panel_specs:
        # Chapter-mode detail panels are built inline, so default their cast here.
        spec.setdefault("cast", _cast_for(spec["beat"], canon, hero, cast_map))
        spec["actors"] = sorted(allowed_speakers(spec["beat"], spec["cast"]))
        # QAR-M2-01: who may speak comes from structured actors - the people who actually
        # wrote or did an event in this story - never from a name merely mentioned in text.
        if thread_actors:
            spec["speakers"] = sorted(
                name for name in set(spec["cast"]) | set((cast_map or {}).values()) | {hero}
                if name in thread_actors
            )
        else:
            spec["speakers"] = sorted(set(spec["actors"]) or set(spec["cast"]))
    cast = sorted({name for spec in panel_specs for name in spec["cast"]})
    active_writer = writer or TemplateDialogueWriter(cast, hero=hero)
    dialogue = active_writer.write(panel_specs)

    report = GroundingReport()
    generic_used = 0
    seen_text: set[str] = set()
    panels: list[Panel] = []
    actors_map = actors_by_event or {}

    # r10c / QAR10-03: every event cited anywhere in this episode, so a caption can also
    # cite the event that states it directly even when that event anchors another panel.
    episode_pool: dict[str, str] = {}
    for _spec in panel_specs:
        _beat = _spec.get("beat")
        for _event_id in (tuple(_beat.event_ids) if _beat else ()):
            episode_pool[_event_id] = str(evidence_map.get(_event_id, ""))

    for index, spec in enumerate(panel_specs, start=1):
        beat: Beat | None = spec["beat"]
        role = spec["role"]
        event_ids = tuple(beat.event_ids) if beat else tuple()
        if not event_ids:
            continue
        cast_names = tuple(spec.get("cast") or ())
        evidence_text = str(spec.get("evidence", ""))
        # Round 8: a caption may only state what the panel's evidence contains. The fact
        # list is the clean core of it, but a fact is a short summary, so a true caption
        # that names a component or a figure from the source must not be called invented.
        # The union is stricter than the raw text alone about invented claims and no more
        # permissive: anything in neither source is still refused.
        # r10c: each thread fact is its own block (one actor, one action) and each cited
        # event is its own block, so actor/action binding can be checked per block.
        fact_blocks = "\n\n".join(
            line.strip() for line in str(facts_evidence or "").splitlines() if line.strip()
        )
        judge_text = (
            f"{fact_blocks}\n\n{evidence_text}".strip() if fact_blocks else evidence_text
        )
        speakers_allowed = set(spec.get("speakers") or spec.get("actors") or ())
        written = dialogue.get(spec.get("key", role), {})

        # ---- layer 1: the fact caption -----------------------------------
        # Round 8 / R7-F1: the caption is the writer's sentence. Facts are evidence for the
        # check, never a page source, so there is nothing to fall back to and nothing to
        # "repair" - a caption either passes or the panel goes without one.
        model_caption = str(written.get("caption", "")).strip() if isinstance(written, dict) else ""
        owner_texts = tuple(str(t) for t in (owner_texts or ()) if str(t).strip())

        def acceptable(text: str, *, composed: bool = False) -> bool:
            if not text:
                return False
            limit = 3 if composed else 8
            if caption_problem(text, owner_texts=owner_texts, max_owner_quote=limit):
                return False
            if grounder is not None:
                verdict = grounder.check(text, judge_text, layer="caption")
                if not verdict.supported:
                    return False
            return True

        # R4-F2: the model paraphrases the fact; the composed sentence is the fallback.
        caption = ""
        if acceptable(model_caption):
            caption = model_caption
        elif model_caption:
            trimmed = trim_caption(model_caption)
            if acceptable(trimmed):
                caption = trimmed
            else:
                # Round 9: a dropped caption must say why, so yield is diagnosable.
                why = caption_problem(trimmed, owner_texts=owner_texts, max_owner_quote=8)
                if not why and grounder is not None:
                    # Round 10: name the real reason. r9's generic wording hid that the
                    # deterministic term rule, not the model, refused these captions.
                    why = grounder.check(trimmed, judge_text, layer="caption").reason
                why = why or "not supported by the panel evidence"
                report.reasons.append(f"{role} caption refused: {why}")
        if caption and (len(caption.split()) < 3 or looks_like_provenance(caption)):
            caption = ""
        if grounder is not None and caption:
            report.captions += 1
            # Round 7: the caption was checked against judge_text when it was chosen, so it
            # must be re-checked against the same text. Re-checking a fact sentence against
            # the long raw evidence failed it, which is what "repaired" the strip with the
            # composer's "Kensei worked on ..." sentence on real runs.
            verdict = grounder.check(caption, judge_text, layer="caption")
            if verdict.supported:
                report.captions_supported += 1
            else:
                # Round 8 / R7-F1: a caption that fails its check is dropped, not
                # replaced with a mechanical sentence. The writer gets one turn.
                report.reasons.append(f"{role} caption: {verdict.reason}")
                caption = ""
        if caption and looks_like_provenance(caption):
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
            # V4: one generic interjection per six panels (a chapter is longer than a strip).
            if _is_generic(candidate, evidence_text, caption) and generic_used >= max(1, len(panel_specs) // 6):
                report.lines_dropped += 1
                report.reasons.append(f"{role}: second generic interjection dropped")
                continue
            if _is_generic(candidate, evidence_text, caption):
                generic_used += 1
            line_ids: tuple[str, ...] = event_ids
            if grounder is not None:
                report.lines += 1
                support_ids, support_text = line_support(candidate, event_ids)
                kind = line_kind(candidate)
                if kind == "claim":
                    if not support_ids:
                        report.lines_dropped += 1
                        report.reasons.append(f"{role} line: no event states this")
                        continue
                    # QAR-M2-01: a line that makes a claim is spoken by someone who acted in
                    # one of the events it cites (the owner may voice his own requests).
                    cited_actors = {actor_lookup.get(e, "") for e in support_ids}
                    if actor_lookup and speaker not in cited_actors:
                        report.lines_dropped += 1
                        report.reasons.append(f"{role} line: {speaker} did not act in the events it cites")
                        continue
                    verdict = grounder.check(candidate, support_text, layer="dialogue")
                    line_ids = tuple(support_ids)
                elif kind == "statement":
                    # QAR-M2-01 (takeover fix): most story statements ("Every test passes on
                    # both databases") carry no extractable claim token, so they used to be
                    # judged against the whole panel and cite the panel's ids. A statement
                    # now cites, and is judged against, only the events that state it.
                    if not support_ids:
                        report.lines_dropped += 1
                        report.reasons.append(f"{role} line: no event states this")
                        continue
                    verdict = grounder.check(candidate, support_text, layer="dialogue")
                    line_ids = tuple(support_ids)
                else:
                    # A pure question or reaction ("Okay.", "What's that one?") states
                    # nothing; it keeps the panel's ids as context.
                    verdict = grounder.check(candidate, evidence_text or support_text, layer="dialogue")
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
            line = Line(speaker=speaker, text=candidate, source_event_ids=line_ids)
            if key in seen_text:
                duplicates.append(line)
                report.lines_dropped += 1
                continue
            seen_text.add(key)
            lines.append(line)
        if not lines and duplicates:
            lines.append(duplicates[0])
        if not caption and not lines:
            # Nothing written survived, and a panel is never filled mechanically.
            report.reasons.append(f"{role}: dropped, nothing written survived")
            continue
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
                event_ids=event_ids,
                caption_source_event_ids=(
                    caption_citation(caption, event_ids, episode_pool, facts) if caption else ()
                ),
            )
        )

    # ---- the ending must be earned (round 8 / R7-F2) ----------------------
    cliffhanger = arc.status != "resolved"
    if not cliffhanger and panels:
        supported, why = _ending_supported(
            panels,
            facts,
            getattr(brief, "outcome", "") or "",
            " ".join(str(spec.get("evidence", "")) for spec in panel_specs),
        )
        if not supported:
            kept = len(panels)
            detail = "; ".join(report.reasons[-2:]) if report.reasons else "no reasons"
            raise EpisodeRefused(
                f"finished thread with no visible outcome ({why}; {kept} panel(s) kept: {detail})"
            )
    if cliffhanger and panels:
        last = panels[-1]
        panels[-1] = replace(
            last,
            label=(last.label + " \u00b7 " if last.label else "") + "To be continued\u2026",
        )

    logline = _logline(title, panels)
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
        citation_pool=dict(line_pool),
        caption_pool_ids=tuple(episode_pool),
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
        if panel.caption and not panel.caption_source_event_ids:
            problems.append(f"caption in {panel.id} has no source_event_ids")
        for event_id in panel.caption_source_event_ids:
            if event_id not in known:
                problems.append(f"{panel.id}: unknown caption source event id {event_id}")
        for line in panel.lines:
            if not line.source_event_ids:
                problems.append(f"line by {line.speaker} in {panel.id} has no source_event_ids")
            for event_id in line.source_event_ids:
                if event_id not in known:
                    problems.append(f"{panel.id}: unknown source event id {event_id}")
    return problems
