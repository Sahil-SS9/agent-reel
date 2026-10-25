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

#: What each arc role must do for the reader (craft notes, docs/STORY-CRAFT.md).
PANEL_JOBS: dict[str, str] = {
    "setup": "who the hero is, what they want and why it matters",
    "insert": "move the story one step: what was tried, found or learned",
    "hidden_problem": "the first sign that something is wrong",
    "diagnosis": "the moment the real cause becomes clear",
    "climax": "the decisive moment and the result itself",
    "aftermath": "what it cost, or what changed",
    "win": "the ending: the result and what it means (or the cliffhanger)",
}

AUDIENCE_RULE = (
    "Write for a general reader who has never seen a terminal. Explain technical detail by "
    "what it meant (an exit code becomes 'the checker itself was broken'). Never show commit "
    "hashes, exit codes, file paths, task ids or tool names unless the name or number IS the "
    "story (a score, a count, a product name)."
)

SYNOPSIS_PROMPT = (
    "You are the writer of a short comic that retells real work with an AI agent. Before any "
    "panel is written, tell the whole story in plain English. Use ONLY what the facts say: no "
    "new event, cause, outcome, number or name. "
    + AUDIENCE_RULE
    + " Answer JSON only: {\"title\": \"a punchy comic title, at most 6 words\", \"logline\": \"one sentence\", \"want\": \"...\", \"stakes\": \"...\", "
    "\"obstacle\": \"...\", \"turn\": \"...\", \"ending\": \"...\", \"meaning\": \"...\"}. "
    "Each value is one short sentence, or empty if the facts do not support it."
)

EDITOR_PROMPT = (
    "You are a comic editor. Read this script as a reader who knows nothing about software. "
    "For each panel, judge whether its words are clear, connected to the story and free of "
    "jargon, and whether the whole reads as a story with a want, a problem, a turn and an "
    "ending. Answer JSON only: {\"score\": 1-5, \"problems\": [{\"panel\": \"<id>\", "
    "\"issue\": \"what is wrong, in a few words\"}]}. List only real problems."
)

SYNOPSIS_FIELDS = ("title", "logline", "want", "stakes", "obstacle", "turn", "ending", "meaning")
#: Fields that tell the story (the title is used as the episode title, not story text).
STORY_FIELDS = SYNOPSIS_FIELDS[1:]

_HASH = re.compile(r"\b(?=[0-9a-f]*\d)(?=[0-9a-f]*[a-f])[0-9a-f]{7,40}\b", re.I)
_EXIT = re.compile(r"\bexit(?:\s+code)?\s*\d+\b", re.I)
_PATH = re.compile(r"(?:~?/[\w.\-]+){2,}|\b[\w\-]+\.(?:py|md|json|ya?ml|toml|sh|ts|js)\b", re.I)
_ID = re.compile(r"\b(?:t_[0-9a-f]{6,}|ev_[0-9a-f]{6,}|local-[0-9a-f]{6,}|[a-z]+_[a-z_]+\(\))", re.I)
_SNAKE = re.compile(r"\b[a-z]+(?:_[a-z0-9]+){1,}\b")


def jargon_problem(text: str) -> str:
    """Why a line is too technical for the page ('' when it reads fine). V6."""
    value = text or ""
    for name, pattern in (("hash", _HASH), ("exit code", _EXIT), ("path", _PATH), ("id", _ID), ("code name", _SNAKE)):
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
) -> Synopsis:
    """A plain-English telling of the episode; every sentence checked against the facts."""
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
    _accept(synopsis, answer, SYNOPSIS_FIELDS, evidence, gate)
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
        _accept(synopsis, answer, tuple(retry), evidence, gate)
    if "title" in synopsis.fields and len(synopsis.fields["title"].split()) > 6:
        synopsis.refused["title"] = "over 6 words"
        synopsis.fields.pop("title")
    return synopsis


def _accept(synopsis: Synopsis, answer: Mapping[str, Any], names: Sequence[str], evidence: str, gate: Any) -> None:
    for name in names:
        sentence = " ".join(str(answer.get(name) or "").split())
        if not sentence:
            continue
        if jargon_problem(sentence):
            synopsis.refused[name] = jargon_problem(sentence)
            continue
        if gate is not None:
            verdict = gate.check(sentence, evidence, layer="caption")
            if not verdict.supported:
                synopsis.refused[name] = verdict.reason
                continue
        synopsis.fields[name] = sentence.rstrip(".") if name == "title" else sentence


def edit_script(complete_json: Any, panels: Sequence[Mapping[str, Any]], *, synopsis: str) -> dict[str, Any]:
    """The editor's read of a script: a 1-5 score and per-panel problems."""
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
            payload={"story": synopsis, "script": script},
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
    "AUDIENCE_RULE", "DEFAULT_VOICES", "PANEL_JOBS", "Synopsis", "behind_the_panels",
    "edit_script", "jargon_problem", "write_synopsis",
)
