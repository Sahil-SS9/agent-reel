"""The director (M2 story pass, owner decisions V1/V3, 25/10/26).

The script says what happened; the director decides how it LOOKS. Per panel it picks:
- a dramatised **location**
- an **action**
- the **villain**'s presence
- a **shot size** and **camera angle**

Following docs/STORY-CRAFT.md:
- the episode's problem becomes a villain (orphaned processes -> The Orphans)
- the climax is the biggest, most dynamic panel
- no two consecutive panels repeat a shot

Truth boundary: the treatment only changes the picture.
- Captions and lines are never edited here; they stay grounded by canon.grounding.
- Treatments must not ask for text in the art, so quotes and "sign that says ..." requests are stripped.

Harness-free: the model call is an injected ``complete_json``. Without a model, a rule-based treatment is used, so a render never depends on the director being available.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence

SHOTS = ("extreme-long", "long", "full", "medium", "close", "extreme-close")
ANGLES = ("eye", "low", "high", "dutch", "overhead")

SHOT_WORDS = {
    "extreme-long": "Extreme long shot",
    "long": "Long shot",
    "full": "Full shot",
    "medium": "Medium shot",
    "close": "Close-up",
    "extreme-close": "Extreme close-up",
}
ANGLE_WORDS = {
    "eye": "eye-level camera",
    "low": "low-angle camera looking up (power)",
    "high": "high-angle camera looking down (vulnerability)",
    "dutch": "tilted Dutch-angle camera (chaos)",
    "overhead": "overhead bird's-eye camera",
}

#: Role defaults from the craft notes. They are used when there is no model, and as the repair target when a model breaks the rules.
ROLE_DEFAULTS = {
    "setup": ("extreme-long", "eye", "absent"),
    "hidden_problem": ("full", "high", "lurking"),
    "diagnosis": ("close", "dutch", "lurking"),
    "climax": ("full", "low", "attacking"),
    "aftermath": ("medium", "eye", "defeated"),
    "win": ("long", "low", "defeated"),
}

#: The problem-kind -> villain library. Fictional creatures only, never a real person.
VILLAINS = {
    "process": ("The Orphans", "small gremlin-like orphaned processes with glowing eyes that hide in server racks and chew cables"),
    "limit": ("The Toll Wraith", "a hooded spectral gatekeeper made of red warning lights, holding a lantern that drains energy"),
    "failure": ("The Crash Golem", "a hulking golem of broken circuit boards and sparking cables"),
    "defect": ("The Glitch Swarm", "a swarm of flickering pixelated insects that corrupt whatever they touch"),
    "blocker": ("The Gatekeeper", "a towering armoured sentinel blocking a glowing doorway"),
    "default": ("The Static", "a shapeless storm of black static with glowing red eyes"),
}

_PATTERNS = (
    ("process", re.compile(r"\b(orphan|zombie|process|gateway|daemon|worker|session)s?\b", re.I)),
    ("limit", re.compile(r"\b(rate[- ]?limit|quota|usage limit|429|403|budget|limit)\b", re.I)),
    ("defect", re.compile(r"\b(bug|regression|leak|corrupt|drift|flaky)\w*\b", re.I)),
    ("blocker", re.compile(r"\b(blocked|stuck|timeout|timed out|refused|hung)\b", re.I)),
    ("failure", re.compile(r"\b(fail|broke|crash|error|exception)\w*\b", re.I)),
)

WORLD_DEFAULT = (
    "a neon-lit command deck high above a rain-soaked cyber city, its walls lined with "
    "glowing server towers"
)

_TEXT_REQUEST = re.compile(r"(\"[^\"]*\"|'[^']*'|\b(sign|banner|label|screen|text|words?|caption)s? (that )?(says?|reads?|showing)\b[^,.;]*)", re.I)

DIRECTOR_PROMPT = (
    "You are the director of a short comic based on true events. Do NOT change any "
    "words: captions and dialogue are fixed. Decide only how each panel LOOKS. The pictures "
    "may dramatise the work as a cinematic adventure: a villain that personifies the "
    "problem, a dramatic world, action, chases and fights. Rules: one villain for the "
    "episode, a creature or force, never a real person; the climax is the most dynamic "
    "panel (low or Dutch angle, full or long shot, impact); vary shot size and angle every "
    "panel; the setup is an establishing extreme-long or long shot; never ask for text, "
    "signs, labels or writing in the image. shot is one of "
    + ", ".join(SHOTS) + "; angle is one of " + ", ".join(ANGLES) + "; villain_presence is "
    "one of absent, lurking, attacking, defeated. Also add wordless FILLER panels like a "
    "real comic book, about one for every two story panels: establishing shots of the "
    "world, reaction close-ups, the villain lurking, the calm before the fight, the impact "
    "after it, a quiet closing beat. A filler goes after a story panel (never after the "
    "last one), has no words, and may show only the episode's cast or the villain. "
    "Answer JSON only: "
    '{"villain": {"name": "...", "look": "..."}, "world": "...", "panels": '
    '[{"id": "...", "location": "...", "action": "...", "villain_presence": "...", '
    '"shot": "...", "angle": "..."}], "fillers": [{"after": "<story panel id>", '
    '"kind": "...", "location": "...", "action": "...", "cast": ["..."], '
    '"villain_presence": "...", "shot": "...", "angle": "..."}]}'
)


@dataclass
class PanelTreatment:
    panel_id: str
    role: str
    location: str
    action: str
    villain_presence: str
    shot: str
    angle: str
    #: Filler panels only (V5): the story panel this one follows, and who is drawn.
    after: str = ""
    cast: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        data = {
            "panel_id": self.panel_id,
            "role": self.role,
            "location": self.location,
            "action": self.action,
            "villain_presence": self.villain_presence,
            "shot": self.shot,
            "angle": self.angle,
        }
        if self.role == "filler":
            data.update(after=self.after, cast=list(self.cast))
        return data


@dataclass
class Treatment:
    villain_name: str
    villain_look: str
    world: str
    panels: dict[str, PanelTreatment] = field(default_factory=dict)
    source: str = "rules"  # rules | model
    repairs: list[str] = field(default_factory=list)
    #: V5: wordless filler panels (establishing, reaction, lurking, impact, quiet beat).
    fillers: list[PanelTreatment] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "villain": {"name": self.villain_name, "look": self.villain_look},
            "world": self.world,
            "source": self.source,
            "repairs": self.repairs,
            "panels": [p.as_dict() for p in self.panels.values()],
            "fillers": [f.as_dict() for f in self.fillers],
        }

    def sequence(self, ir: Mapping[str, Any]) -> list[tuple[str, PanelTreatment | None]]:
        """Reading order: every story panel id, each followed by its fillers."""
        order: list[tuple[str, PanelTreatment | None]] = []
        for panel in ir.get("panels", []) or []:
            pid = str(panel.get("id"))
            order.append((pid, self.panels.get(pid)))
            order += [(f.panel_id, f) for f in self.fillers if f.after == pid]
        return order


FILLER_KINDS = ("establishing", "reaction", "lurk", "calm", "impact", "quiet")


def _episode_cast(ir: Mapping[str, Any]) -> list[str]:
    seen: list[str] = []
    for panel in ir.get("panels", []) or []:
        for name in panel.get("cast", []) or []:
            if name not in seen:
                seen.append(str(name))
    return seen


def _rule_fillers(treatment: "Treatment", ir: Mapping[str, Any]) -> list[PanelTreatment]:
    """About one wordless panel for every two story panels (V5), chosen by what comes next."""
    panels = list(ir.get("panels", []) or [])
    cast = _episode_cast(ir)
    hero = "Sahil" if "Sahil" in cast else (cast[0] if cast else "")
    name = treatment.villain_name
    fillers: list[PanelTreatment] = []
    toggle = 0
    for index, panel in enumerate(panels[:-1]):
        if index % 2 == 0:
            continue
        pid = str(panel.get("id"))
        role = str(panel.get("role", ""))
        upcoming = str(panels[index + 1].get("role", ""))
        if upcoming == "climax":
            kind, who, shot, angle, presence = "calm", (hero,), "extreme-close", "eye", "absent"
            action = f"{hero}'s eyes narrow in the half-light, a breath before the storm"
        elif role == "climax":
            kind, who, shot, angle, presence = "impact", (), "extreme-long", "overhead", "defeated"
            action = f"the shockwave of the clash rolls out; fragments of {name} scatter across the ground"
        elif upcoming in {"hidden_problem", "diagnosis", "insert"} and index < len(panels) * 0.7:
            kind, who, shot, angle, presence = "lurk", (), "long", "dutch", "lurking"
            action = f"{name} stir in the shadows, unseen, closer than before"
        elif toggle % 2 == 0:
            kind, who, shot, angle, presence = "establishing", (), "extreme-long", "high", "absent"
            action = "the world in silence: vast, glowing, still"
            toggle += 1
        else:
            kind, who, shot, angle, presence = "reaction", (hero,) if hero else (), "close", "low", "absent"
            action = f"{hero} pauses, taking in what just happened" if hero else "a quiet moment"
            toggle += 1
        if role in {"aftermath", "win"} and kind in {"lurk", "calm"}:
            kind, who, shot, angle, presence = "quiet", (), "long", "eye", "absent"
            action = "a quiet beat: the dust settles and the light returns"
        fillers.append(PanelTreatment(
            panel_id=f"{pid}-f{len(fillers) + 1}", role="filler", location=treatment.world,
            action=action, villain_presence=presence, shot=shot, angle=angle, after=pid,
            cast=tuple(n for n in who if n),
        ))
    return fillers


def _model_fillers(raw: Any, treatment: "Treatment", ir: Mapping[str, Any]) -> list[PanelTreatment] | None:
    """The director's own fillers, if they obey the rules; ``None`` means use the rules."""
    if not isinstance(raw, list):
        return None
    ids = [str(p.get("id")) for p in ir.get("panels", []) or []]
    cast = set(_episode_cast(ir))
    target = len(ids) // 2
    fillers: list[PanelTreatment] = []
    for item in raw:
        if not isinstance(item, dict) or str(item.get("after")) not in ids[:-1]:
            continue
        after = str(item.get("after"))
        who = tuple(str(n) for n in item.get("cast", []) or [] if str(n) in cast)[:2]
        fillers.append(PanelTreatment(
            panel_id=f"{after}-f{len(fillers) + 1}", role="filler",
            location=str(item.get("location") or treatment.world),
            action=str(item.get("action") or ""), villain_presence=str(item.get("villain_presence") or "absent"),
            shot=str(item.get("shot") or ""), angle=str(item.get("angle") or ""), after=after, cast=who,
        ))
    if not target or abs(len(fillers) - target) > 1:
        return None
    return fillers


def pick_villain(text: str) -> tuple[str, str]:
    for kind, pattern in _PATTERNS:
        if pattern.search(text or ""):
            return VILLAINS[kind]
    return VILLAINS["default"]


def no_text(value: str) -> str:
    """Strip anything that would ask the image model to draw words."""
    cleaned = _TEXT_REQUEST.sub("", value or "")
    return " ".join(cleaned.split()).strip(" ,;:")


def _rules(ir: Mapping[str, Any], story_text: str) -> Treatment:
    name, look = pick_villain(story_text)
    treatment = Treatment(villain_name=name, villain_look=look, world=WORLD_DEFAULT)
    for panel in ir.get("panels", []) or []:
        role = str(panel.get("role", "aftermath"))
        shot, angle, presence = ROLE_DEFAULTS.get(role, ("medium", "eye", "absent"))
        action = {
            "setup": "the heroes arrive and survey the scene, calm before the storm",
            "hidden_problem": f"{name} creep in unnoticed in the shadows behind the heroes",
            "diagnosis": f"the heroes spot the first trace of {name}",
            "climax": f"the heroes clash with {name} in a burst of light and motion lines",
            "aftermath": f"the dust settles; scattered remains of {name} fade away",
            "win": "the heroes stand victorious, the world calm again",
        }.get(role, "the heroes press on")
        treatment.panels[str(panel.get("id"))] = PanelTreatment(
            panel_id=str(panel.get("id")), role=role, location=WORLD_DEFAULT,
            action=action, villain_presence=presence, shot=shot, angle=angle,
        )
    treatment.fillers = _rule_fillers(treatment, ir)
    return treatment


def _repair(treatment: Treatment, ir: Mapping[str, Any]) -> Treatment:
    """Enforce the craft rules on whatever the model returned."""
    previous: tuple[str, str] | None = None
    for panel in ir.get("panels", []) or []:
        pid = str(panel.get("id"))
        role = str(panel.get("role", "aftermath"))
        item = treatment.panels.get(pid)
        default_shot, default_angle, default_presence = ROLE_DEFAULTS.get(role, ("medium", "eye", "absent"))
        if item is None:
            item = PanelTreatment(pid, role, treatment.world, "the heroes press on", default_presence, default_shot, default_angle)
            treatment.panels[pid] = item
            treatment.repairs.append(f"{pid}: missing, rule default used")
        if item.shot not in SHOTS:
            treatment.repairs.append(f"{pid}: unknown shot {item.shot!r}")
            item.shot = default_shot
        if item.angle not in ANGLES:
            treatment.repairs.append(f"{pid}: unknown angle {item.angle!r}")
            item.angle = default_angle
        if item.villain_presence not in {"absent", "lurking", "attacking", "defeated"}:
            item.villain_presence = default_presence
        if role == "climax" and (item.angle not in {"low", "dutch"} or item.shot not in {"full", "long"}):
            treatment.repairs.append(f"{pid}: climax made dynamic")
            item.shot, item.angle = "full", "low" if item.angle not in {"low", "dutch"} else item.angle
        if previous == (item.shot, item.angle):
            treatment.repairs.append(f"{pid}: repeated shot varied")
            item.angle = next(a for a in ANGLES if a != item.angle and a != "overhead")
        item.location = no_text(item.location) or treatment.world
        item.action = no_text(item.action) or "the heroes press on"
        previous = (item.shot, item.angle)
    treatment.villain_look = no_text(treatment.villain_look)
    treatment.world = no_text(treatment.world) or WORLD_DEFAULT
    for filler in treatment.fillers:
        filler.shot = filler.shot if filler.shot in SHOTS else "extreme-long"
        filler.angle = filler.angle if filler.angle in ANGLES else "high"
        if filler.villain_presence not in {"absent", "lurking", "attacking", "defeated"}:
            filler.villain_presence = "absent"
        filler.location = no_text(filler.location) or treatment.world
        filler.action = no_text(filler.action) or "a quiet beat"
    # No two consecutive panels - story or filler - share both shot and angle.
    previous = None
    for pid, item in treatment.sequence(ir):
        if item is None:
            continue
        if previous == (item.shot, item.angle):
            treatment.repairs.append(f"{pid}: repeated shot varied")
            item.angle = next(a for a in ANGLES if a != item.angle and a != "overhead")
        previous = (item.shot, item.angle)
    return treatment


def direct(
    ir: Mapping[str, Any],
    *,
    story_text: str,
    complete_json: Callable[..., Mapping[str, Any]] | None = None,
) -> Treatment:
    """A visual treatment for the episode: model when available, rules otherwise."""
    if complete_json is None:
        return _repair(_rules(ir, story_text), ir)
    panels = [
        {"id": p.get("id"), "role": p.get("role"), "caption": p.get("caption", ""),
         "lines": [f"{l.get('speaker')}: {l.get('text')}" for l in p.get("lines", [])],
         "cast": list(p.get("cast", []))}
        for p in ir.get("panels", []) or []
    ]
    try:
        answer = complete_json(
            prompt=DIRECTOR_PROMPT,
            payload={"title": ir.get("logline", ""), "story": story_text[:3000], "panels": panels},
            schema_hint={"villain": {"name": "str", "look": "str"}, "world": "str", "panels": ["object"], "fillers": ["object"]},
            stage="episode.director",
        )
    except Exception:  # noqa: BLE001 - a missing director never blocks a render
        fallback = _repair(_rules(ir, story_text), ir)
        fallback.repairs.append("director model unavailable; rules used")
        return fallback
    raw_villain = answer.get("villain")
    villain: Mapping[str, Any] = raw_villain if isinstance(raw_villain, dict) else {}
    default_name, default_look = pick_villain(story_text)
    treatment = Treatment(
        villain_name=str(villain.get("name") or default_name)[:40],
        villain_look=str(villain.get("look") or default_look)[:300],
        world=str(answer.get("world") or WORLD_DEFAULT)[:300],
        source="model",
    )
    roles = {str(p.get("id")): str(p.get("role", "")) for p in ir.get("panels", []) or []}
    for item in answer.get("panels") or []:
        if not isinstance(item, dict) or str(item.get("id")) not in roles:
            continue
        pid = str(item.get("id"))
        treatment.panels[pid] = PanelTreatment(
            panel_id=pid, role=roles[pid],
            location=str(item.get("location") or ""), action=str(item.get("action") or ""),
            villain_presence=str(item.get("villain_presence") or "absent"),
            shot=str(item.get("shot") or ""), angle=str(item.get("angle") or ""),
        )
    model_fillers = _model_fillers(answer.get("fillers"), treatment, ir)
    if model_fillers is None:
        treatment.fillers = _rule_fillers(treatment, ir)
        treatment.repairs.append("fillers: model count off target; rule fillers used")
    else:
        treatment.fillers = model_fillers
    return _repair(treatment, ir)


__all__: Sequence[str] = ("Treatment", "PanelTreatment", "direct", "pick_villain", "no_text", "SHOT_WORDS", "ANGLE_WORDS")
