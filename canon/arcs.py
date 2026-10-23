"""Arcs: the arc template from decisions.md "Proven method" #1.

One arc per episode, never a highlight reel:

    setup -> hidden problem -> diagnosis -> climax -> aftermath -> win + cliffhanger

Every panel causes the next, so the arc is a *chain*: each role consumes the beat
that the previous role's outcome implies. Beats that do not fit any role are left
out rather than padding the chain.

Recurring problems become villains (an entity promoted after 3+ arcs); a
``rivalry`` arc is exactly that case: the same failure signature returning.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from canon.beats import Beat
from canon.events import make_event_id

ARC_ROLES = ("setup", "hidden_problem", "diagnosis", "climax", "aftermath", "win")
ARC_TYPES = ("struggle-to-resolution", "pivot", "rivalry", "mystery", "training-montage")


@dataclass(frozen=True, slots=True)
class Arc:
    id: str
    title: str
    type: str
    status: str
    roles: dict[str, str]
    beat_ids: tuple[str, ...]
    stakes: str
    opened: float
    resolved: float | None
    cliffhanger: str = ""

    def __post_init__(self) -> None:
        if self.type not in ARC_TYPES:
            raise ValueError(f"unknown arc type: {self.type!r}")
        if self.status not in {"open", "resolved"}:
            raise ValueError(f"unknown arc status: {self.status!r}")

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "type": self.type,
            "status": self.status,
            "roles": dict(sorted(self.roles.items())),
            "beat_ids": list(self.beat_ids),
            "stakes": self.stakes,
            "opened": round(self.opened, 6),
            "resolved": round(self.resolved, 6) if self.resolved else None,
            "cliffhanger": self.cliffhanger,
        }


def _chain(beats: Sequence[Beat]) -> dict[str, str]:
    """Assign beats to arc roles so each role is caused by the previous one."""
    ordered = sorted(beats, key=lambda beat: (beat.ts, beat.id))
    struggles = [beat for beat in ordered if beat.type in {"struggle", "failure"}]
    wins = [beat for beat in ordered if beat.type == "breakthrough"]
    decisions = [beat for beat in ordered if beat.type == "decision"]
    levelups = [beat for beat in ordered if beat.type == "level-up"]

    roles: dict[str, str] = {}
    if not ordered:
        return roles

    climax = max(struggles or ordered, key=lambda beat: (beat.intensity, beat.ts))
    roles["climax"] = climax.id

    before = [beat for beat in ordered if beat.ts <= climax.ts and beat.id != climax.id]
    after = [beat for beat in ordered if beat.ts > climax.ts]

    setup_pool = [beat for beat in before if beat.type in {"decision", "level-up", "joke"}]
    setup = setup_pool[0] if setup_pool else (before[0] if before else None)
    if setup is not None:
        roles["setup"] = setup.id

    hidden_pool = [
        beat
        for beat in before
        if beat.type in {"struggle", "failure"}
        and beat.id != climax.id
        and beat.id != roles.get("setup")
    ]
    if hidden_pool:
        roles["hidden_problem"] = hidden_pool[0].id

    diagnosis_pool = [
        beat
        for beat in before
        if beat.id not in {roles.get("hidden_problem"), climax.id}
        and beat.type in {"struggle", "failure", "decision"}
    ]
    if diagnosis_pool:
        roles["diagnosis"] = diagnosis_pool[-1].id

    # aftermath and win must happen *after* the climax, or the chain reads as a
    # flashback. A role with no beat after the climax stays empty.
    aftermath_pool = [
        beat
        for beat in after
        if beat.type in {"breakthrough", "decision"} and beat.ts >= climax.ts
    ]
    if aftermath_pool:
        roles["aftermath"] = aftermath_pool[0].id

    win_pool = [
        beat
        for beat in after
        if beat.ts > climax.ts and beat.id != roles.get("aftermath")
    ]
    if win_pool:
        roles["win"] = win_pool[-1].id

    # Enforce chronological order across the chain.
    order = [role for role in ARC_ROLES if role in roles]
    last_ts = float("-inf")
    for role in order:
        beat = next((item for item in ordered if item.id == roles[role]), None)
        if beat is None or beat.ts < last_ts:
            roles.pop(role, None)
            continue
        last_ts = beat.ts
    return roles


def _title(beats: Iterable[Beat]) -> str:
    for beat in beats:
        cleaned = " ".join(
            word.strip(" .,:;!?\u2014-") for word in beat.summary.split()
        )
        words = [word for word in cleaned.split() if len(word) > 3 and not word.startswith("ev_")]
        if len(words) >= 3:
            return " ".join(words[:6])
    return "A week on the rig"


def _stakes(roles: dict[str, str], by_id: dict[str, Beat]) -> str:
    climax = by_id.get(roles.get("climax", ""))
    if climax is None:
        return "the week's work"
    text = " ".join(
        word.strip(" .,:;!?\u2014-") for word in climax.summary.split()
    )
    words = [word for word in text.split() if word]
    return " ".join(words[:14]) if words else "the week's work"


def build_arc(
    beats: Sequence[Beat],
    *,
    arc_type: str = "struggle-to-resolution",
    window_start: float = 0.0,
) -> Arc | None:
    if not beats:
        return None
    roles = _chain(beats)
    if "climax" not in roles:
        return None
    by_id = {beat.id: beat for beat in beats}
    ordered_ids = tuple(
        roles[role] for role in ARC_ROLES if role in roles
    )
    climax = by_id[roles["climax"]]
    win = by_id.get(roles.get("win", ""))
    opened = min(by_id[beat_id].ts for beat_id in ordered_ids)
    resolved = max(by_id[beat_id].ts for beat_id in ordered_ids)
    status = "resolved" if win is not None else "open"
    cliffhanger = ""
    if status == "resolved":
        later = [beat for beat in beats if beat.ts > resolved and beat.type in {"struggle", "failure"}]
        if later:
            cliffhanger = later[0].summary
    else:
        cliffhanger = climax.summary
    return Arc(
        id=make_event_id("arc", arc_type, opened, {"beats": list(ordered_ids)}),
        title=_title(by_id[beat_id] for beat_id in ordered_ids),
        type=arc_type,
        status=status,
        roles=dict(roles),
        beat_ids=ordered_ids,
        stakes=_stakes(roles, by_id),
        opened=opened,
        resolved=resolved if status == "resolved" else None,
        cliffhanger=cliffhanger,
    )


def build_arcs(
    beats: Sequence[Beat],
    *,
    max_arcs: int = 3,
    window_start: float = 0.0,
) -> list[Arc]:
    """One primary arc, plus a rivalry arc when the same problem keeps returning."""
    arcs: list[Arc] = []
    primary = build_arc(beats, arc_type="struggle-to-resolution", window_start=window_start)
    if primary is None:
        return arcs
    arcs.append(primary)

    # Rivalry: the same struggle signature appearing three or more times.
    signatures: dict[str, list[Beat]] = {}
    for beat in beats:
        if beat.type not in {"struggle", "failure"}:
            continue
        signature = beat.tags[-1] if beat.tags else beat.type
        signatures.setdefault(signature, []).append(beat)
    rival = sorted(
        ((signature, group) for signature, group in signatures.items() if len(group) >= 3),
        key=lambda item: (-len(item[1]), item[0]),
    )
    if rival and len(arcs) < max_arcs:
        signature, group = rival[0]
        arc = build_arc(group, arc_type="rivalry", window_start=window_start)
        if arc is not None:
            arcs.append(arc)

    # Training montage: a day with many level-ups and no big struggle.
    by_day: dict[int, list[Beat]] = {}
    for beat in beats:
        by_day.setdefault(int(beat.ts // 86400), []).append(beat)
    for day, group in sorted(by_day.items()):
        levelups = [beat for beat in group if beat.type == "level-up"]
        struggles = [beat for beat in group if beat.type in {"struggle", "failure"}]
        if len(levelups) >= 3 and len(struggles) <= 1 and len(arcs) < max_arcs:
            arc = build_arc(group, arc_type="training-montage", window_start=window_start)
            if arc is not None:
                arcs.append(arc)
            break
    return arcs


@dataclass
class ArcLedger:
    arcs: list[Arc] = field(default_factory=list)

    def primary(self) -> Arc | None:
        return self.arcs[0] if self.arcs else None

    def as_dict(self) -> dict[str, Any]:
        return {"arcs": [arc.as_dict() for arc in self.arcs]}
