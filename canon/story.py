"""Story layer (owner decisions V6-V8, 25/10/26).

The M1 engine turns each chat message into one caption. That is a transcript, not a story.
This module adds what a comic writer does first:

- **Synopsis.** One plain-English telling of the whole episode before any panel is written:
  - what the hero wanted, and why it mattered
  - what got in the way, and the turning point
  - how it ended, and what it means

  Every sentence is checked against the thread's facts in meaning mode (V7), so the synopsis is
  true, but it is written for a general reader (V6).
- **Voice sheet.** How each character talks (V8: epic pictures, witty dialogue). A voice adds tone,
  never facts.
- **Panel jobs.** What the reader must learn or feel at each arc role.
- **Editor.** Reads the finished script as an outsider and names the panels that are unclear or
  jargon-heavy, so the writer gets one more pass before anything is drawn.
- **Behind the panels.** The real technical facts per panel, for builders who want them. This is
  the insider half of V6 ("A+B"): the story is plain English, and the notes keep the detail.

Harness-free: the model is an injected ``complete_json`` client; the gate is a
``canon.grounding.ClaimGate``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from canon.grounding import NUMBER_WORDS, figures_in

#: V8 (25/10/26): epic pictures, witty dialogue. Tone only; a voice never adds a fact.
DEFAULT_VOICES: dict[str, str] = {
    "Sahil": "the builder: blunt, impatient, dry British humour, short sentences, wants results not excuses",
    "Kensei": "the sword-saint agent: calm, precise, understated, one-line deadpan wit, never panics",
    "Octacon": "the coder: quick, a little smug, talks in fixes",
    "Quan": "the inspector: exacting, suspicious, says 'prove it'",
    "Wesker": "the ops chief: cold, clipped, theatrical menace",
    "Remii": "the researcher: curious, excitable, cites everything",
    "narrator": "a comic narrator: punchy present tense, sets time and stakes in a few words, plain English",
}

#: What each arc role must do for the reader (craft notes, docs/STORY-CRAFT.md). `{hero}` and
#: `{agent}` are filled by `jobs_for`; the shape of the story (arc type) can override any role.
COLD_OPEN = (
    "a cold open: start on the hook (the sharpest moment, threat or question of the story), then "
)

_BASE_JOBS: dict[str, str] = {
    "setup": COLD_OPEN + "introduce the characters ({hero}, the builder; {agent}, his AI agent), what "
    "{hero} wants and why it matters. Never open on scene-setting",
    "insert": "move the story one step: what was tried, found or learned",
    "hidden_problem": "the first sign that something is wrong",
    "diagnosis": "the moment the real cause becomes clear",
    "climax": "the decisive moment and the result itself",
    "aftermath": "what it cost, or what changed",
    "win": "the ending: the result and what it means (or the cliffhanger)",
}

#: Roles a shape tells differently. A role not listed keeps its base job.
TYPE_JOBS: dict[str, dict[str, str]] = {
    "mystery": {
        "setup": COLD_OPEN + "show the strangest symptom; {hero} and {agent} do not know what is wrong",
        "hidden_problem": "the clue that does not fit: what should have happened and did not",
        "diagnosis": "a false lead that fails, or the clue that finally fits",
        "climax": "the reveal: the real cause, shown at the moment it is understood",
        "aftermath": "what the cause explains, looking back at the earlier clues",
        "win": "the fix, or the open question that remains",
    },
    "pivot": {
        "setup": COLD_OPEN + "show the plan {hero} starts with and why he believes in it",
        "hidden_problem": "the first sign the plan will not hold",
        "diagnosis": "the moment {hero} accepts the plan is wrong",
        "climax": "the change of direction: the old plan dropped, the new one chosen",
        "aftermath": "the cost of switching: what is thrown away",
        "win": "the new plan's first result, or the doubt that remains about it",
    },
    "rivalry": {
        "setup": COLD_OPEN + "introduce the rival (what {hero} is up against) and what is at stake between them",
        "hidden_problem": "the rival's first advantage",
        "diagnosis": "the weakness or the tell that gives {hero} an opening",
        "climax": "the head-to-head: the decisive comparison and its result",
        "aftermath": "what the result does not settle",
        "win": "who came out ahead, and the next round",
    },
    "training-montage": {
        "setup": COLD_OPEN + "show where {hero} and {agent} start: the baseline and the target",
        "hidden_problem": "the first attempt and how far it falls short",
        "diagnosis": "the lesson that changes how they work",
        "climax": "the best result so far",
        "aftermath": "what it cost in time and tries",
        "win": "how far they came, from the first number to the last",
    },
}


def jobs_for(arc_type: str = "struggle-to-resolution", *, hero: str = "Sahil", agent: str = "Kensei") -> dict[str, str]:
    """What each panel must do for the reader, for this shape of story and this cast."""
    jobs = {**_BASE_JOBS, **TYPE_JOBS.get(arc_type, {})}
    return {role: text.format(hero=hero, agent=agent) for role, text in jobs.items()}


#: The default (struggle-to-resolution) jobs for the default cast, kept for callers that do not
#: know the shape or the cast.
PANEL_JOBS: dict[str, str] = jobs_for()

AUDIENCE_RULE = (
    "Write for a general reader who has never seen a terminal. Explain technical detail by "
    "what it meant (an exit code becomes 'the checker itself was broken'). Never show commit "
    "hashes, exit codes, file paths, task ids or tool names unless the name or number IS the "
    "story (a score, a count, a product name)."
)

#: Grounding layer the story is checked on (canon.grounding.STORY_LAYER): it may interpret,
#: it may not add an event.
NARRATION_LAYER = "story"

SYNOPSIS_PROMPT = (
    "You are the writer of a short comic that retells real work with an AI agent. Before any "
    "panel is written, tell the whole story in plain English, the way a good storyteller "
    "would: what the hero wanted and why it mattered to them, what stood in the way, the turn, "
    "how it ended and what it meant. You may interpret: what was at stake, what a moment felt "
    "like, why it mattered. You may NOT add anything that happened: no new event, cause, "
    "outcome, number, name, time or place; every event must be in the facts. "
    + AUDIENCE_RULE
    + " Answer JSON only: {\"title\": \"a punchy comic title, at most 6 words\", \"logline\": \"one sentence\", \"want\": \"...\", \"stakes\": \"...\", "
    "\"obstacle\": \"...\", \"turn\": \"...\", \"ending\": \"...\", \"meaning\": \"...\", "
    "\"hook\": \"the single most gripping moment, line or question of the story, to open on\"}. "
    "Each value is one short sentence, or empty if the facts do not support it."
)

EDITOR_PROMPT = (
    "You are a comic editor. Read this script as a reader who knows nothing about software. "
    "For each panel, judge whether its words are clear, connected to the story and free of "
    "jargon, whether the whole reads as a story with a want, a problem, a turn and an "
    "ending, and whether it delivers the requested tone. Flag any caption that only reports "
    "a number or a status (\"Zero failures.\") without saying what it meant to the hero or why "
    "it mattered: call it a readout. Answer JSON only: {\"score\": 1-5, \"problems\": [{\"panel\": \"<id>\", "
    "\"issue\": \"what is wrong, in a few words\"}]}. List only real problems."
)

SYNOPSIS_FIELDS = ("title", "logline", "want", "stakes", "obstacle", "turn", "ending", "meaning", "hook")
#: Fields that tell the story. The title is the episode title and the hook is what the first
#: panel opens on; neither is story text.
STORY_FIELDS = tuple(name for name in SYNOPSIS_FIELDS if name not in ("title", "hook"))

_HASH = re.compile(r"\b(?=[0-9a-f]*\d)(?=[0-9a-f]*[a-f])[0-9a-f]{7,40}\b", re.I)
_EXIT = re.compile(r"\bexit(?:\s+code)?\s*\d+\b", re.I)
_PATH = re.compile(r"(?:~?/[\w.\-]+){2,}|\b[\w\-]+\.(?:py|md|json|ya?ml|toml|sh|ts|js)\b", re.I)
_ID = re.compile(r"\b(?:t_[0-9a-f]{6,}|ev_[0-9a-f]{6,}|local-[0-9a-f]{6,}|[a-z]+_[a-z_]+\(\))", re.I)
_SNAKE = re.compile(r"\b[a-z]+(?:_[a-z0-9]+){1,}\b")
#: QAR-M2-04: engineering vocabulary a general reader does not know (V6). Product names that
#: ARE the story (Severian, LCM-X) are not here; neither are everyday words like "test".
_TECH = re.compile(
    r"\b(?:sqlite|postgres(?:ql)?|ranker|append-only|worktree|commit|regex|json|yaml|api|cli|pytest|"
    r"ci|gguf|lora|vram|endpoint|repo(?:sitory)?|branch|merge|rebase|stack ?trace|traceback|"
    r"handoff \d+|context v\d+|v\d+(?:\.\d+)+|sidecar|wal|schema|mypy|ruff|lint(?:er)?|"
    r"subprocess|daemon|cron|dispatcher|kanban|token(?:s)? per call|prompt tokens)\b",
    re.IGNORECASE,
)


def jargon_problem(text: str) -> str:
    """Why a line is too technical for the page ('' when it reads fine). V6."""
    value = text or ""
    for name, pattern in (("hash", _HASH), ("exit code", _EXIT), ("path", _PATH), ("id", _ID), ("code name", _SNAKE), ("jargon", _TECH)):
        found = pattern.search(value)
        if found:
            return f"{name}: {found.group(0)}"
    return ""


@dataclass
class Synopsis:
    fields: dict[str, str] = field(default_factory=dict)
    refused: dict[str, str] = field(default_factory=dict)
    source: str = "none"  # model | none

    def text(self) -> str:
        return " ".join(self.fields.get(name, "") for name in STORY_FIELDS if self.fields.get(name))

    def as_dict(self) -> dict[str, Any]:
        return {"fields": dict(self.fields), "refused": dict(self.refused), "source": self.source}


def write_synopsis(
    complete_json: Any,
    *,
    title: str,
    facts_text: str,
    brief_text: str,
    gate: Any = None,
    layer: str = NARRATION_LAYER,
) -> Synopsis:
    """A plain-English telling of the episode; every sentence checked against the facts.

    ``layer`` is the grounding layer: ``"story"`` lets the telling interpret (stakes,
    feeling, motive) while still refusing any new event, name or number; ``"caption"``
    keeps the old literal rule."""
    synopsis = Synopsis()
    if complete_json is None:
        return synopsis
    evidence = f"{facts_text}\n\n{brief_text}".strip()
    try:
        answer = complete_json(
            prompt=SYNOPSIS_PROMPT,
            payload={"title": title, "facts": facts_text[:3500], "brief": brief_text[:2500]},
            schema_hint={name: "string" for name in SYNOPSIS_FIELDS},
            stage="story.synopsis",
        )
    except Exception:  # noqa: BLE001 - no synopsis means the old per-panel path
        return synopsis
    synopsis.source = "model"
    _accept(synopsis, answer, SYNOPSIS_FIELDS, evidence, gate, layer)
    if synopsis.refused:
        # One repair pass: the writer sees why each refused sentence failed.
        retry = dict(synopsis.refused)
        try:
            answer = complete_json(
                prompt=SYNOPSIS_PROMPT + " Some sentences were refused by the fact checker. "
                "Rewrite ONLY those fields so they are true to the facts; keep them short and "
                "plain. Return the same JSON with only the rewritten fields.",
                payload={"title": title, "facts": facts_text[:3500], "brief": brief_text[:2500],
                         "refused": retry},
                schema_hint={name: "string" for name in retry},
                stage="story.synopsis.repair",
            )
        except Exception:  # noqa: BLE001
            return synopsis
        for name in retry:
            synopsis.refused.pop(name, None)
        _accept(synopsis, answer, tuple(retry), evidence, gate, layer)
    if "title" in synopsis.fields and len(synopsis.fields["title"].split()) > 6:
        synopsis.refused["title"] = "over 6 words"
        synopsis.fields.pop("title")
    return synopsis


def _accept(
    synopsis: Synopsis, answer: Mapping[str, Any], names: Sequence[str], evidence: str, gate: Any,
    layer: str = NARRATION_LAYER,
) -> None:
    for name in names:
        sentence = " ".join(str(answer.get(name) or "").split())
        if not sentence:
            continue
        if jargon_problem(sentence):
            synopsis.refused[name] = jargon_problem(sentence)
            continue
        if gate is not None:
            verdict = gate.check(sentence, evidence, layer=layer)
            if not verdict.supported:
                synopsis.refused[name] = verdict.reason
                continue
        synopsis.fields[name] = sentence.rstrip(".") if name == "title" else sentence


_PRONOUN = re.compile(r"\b(i|me|my|we|us|our|you|your|he|him|his|she|her|they|them|their)\b", re.IGNORECASE)


def readout_problem(caption: str, *, cast: Sequence[str] = ()) -> str:
    """Why a caption reads like a status readout ('' when it does not).

    A readout is a bare statistic or status line: it has a figure, nobody in it (no character
    and no pronoun) and no voice (no question or exclamation). "On questions about when things
    happened, LCM-X wins by 10 to 16 points." tells the reader a result but not why they should
    care. A caption that names who it mattered to, or asks or exclaims, is not flagged.
    """
    text = " ".join((caption or "").split())
    if not text or len(text.split()) > 16 or "?" in text or "!" in text:
        return ""
    has_number = bool(figures_in(text)) or any(
        re.search(rf"\b{word}\b", text, re.IGNORECASE) for word in (*NUMBER_WORDS, "zero")
    )
    if not has_number or _PRONOUN.search(text):
        return ""
    if any(re.search(rf"\b{re.escape(name)}\b", text, re.IGNORECASE) for name in cast if name):
        return ""
    return "reads like a status readout: say what the number meant to the hero"


def edit_script(
    complete_json: Any,
    panels: Sequence[Mapping[str, Any]],
    *,
    synopsis: str,
    tone: str = "",
    cast: Sequence[str] = (),
) -> dict[str, Any]:
    """The editor's read of a script: a 1-5 score and per-panel problems.

    Besides the model's read, any caption that is a bare readout (``readout_problem``) is
    added as a problem, and the score is capped at 3 so the rewrite pass runs: a model that
    liked the script is not allowed to wave a statistic through."""
    if complete_json is None or not panels:
        return {"score": 0, "problems": [], "source": "none"}
    script = [
        {"panel": p.get("id"), "role": p.get("role"),
         "caption": p.get("caption", ""),
         "lines": [f"{l.get('speaker')}: {l.get('text')}" for l in p.get("lines", [])]}
        for p in panels
    ]
    try:
        answer = complete_json(
            prompt=EDITOR_PROMPT,
            payload={"story": synopsis, "tone": tone, "script": script},
            schema_hint={"score": "int", "problems": [{"panel": "str", "issue": "str"}]},
            stage="story.editor",
        )
    except Exception as exc:  # noqa: BLE001 - recorded, so a failed editor is diagnosable
        return {"score": 0, "problems": [], "source": "unavailable", "error": f"{type(exc).__name__}: {str(exc)[:200]}"}
    problems = [
        {"panel": str(item.get("panel")), "issue": str(item.get("issue", ""))[:200]}
        for item in answer.get("problems") or []
        if isinstance(item, Mapping) and item.get("panel")
    ]
    try:
        score = int(answer.get("score") or 0)
    except (TypeError, ValueError):
        score = 0
    flagged = {item["panel"] for item in problems}
    readouts = 0
    for panel in panels:
        why = readout_problem(str(panel.get("caption", "")), cast=cast)
        if why and str(panel.get("id")) not in flagged:
            problems.append({"panel": str(panel.get("id")), "issue": why})
            readouts += 1
    if readouts and score:
        score = min(score, 3)
    return {"score": max(0, min(5, score)), "problems": problems, "source": "model"}


def behind_the_panels(panels: Sequence[Mapping[str, Any]], facts_by_panel: Mapping[str, str]) -> str:
    """Markdown notes for builders: the real technical facts behind each panel (V6 insider)."""
    lines = ["# Behind the panels", "", "The comic is told in plain English. These are the real details behind each panel.", ""]
    for number, panel in enumerate(panels, start=1):
        fact = facts_by_panel.get(str(panel.get("id")), "").strip()
        if not fact:
            continue
        ids = ", ".join(panel.get("caption_source_event_ids", [])[:3])
        lines.append(f"- **Panel {number}** ({panel.get('role')}): {fact}" + (f"  \n  _sources: {ids}_" if ids else ""))
    return "\n".join(lines) + "\n"


__all__ = (
    "AUDIENCE_RULE",
    "DEFAULT_VOICES",
    "NARRATION_LAYER",
    "PANEL_JOBS",
    "TYPE_JOBS",
    "Synopsis",
    "behind_the_panels",
    "edit_script",
    "jargon_problem",
    "jobs_for",
    "readout_problem",
    "write_synopsis",
)
