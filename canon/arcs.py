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
from typing import Any, Iterable, Mapping, Sequence

from canon.beats import Beat
from canon.events import make_event_id
from canon.gate import GatedEvent
from canon.threads import Thread, beats_by_thread, causal_check, thread_index

ARC_ROLES = ("setup", "hidden_problem", "diagnosis", "climax", "aftermath", "win")
ARC_TYPES = ("struggle-to-resolution", "pivot", "rivalry", "mystery", "training-montage")

#: A weekly strip has 4-6 panels, so a thread needs at least this many beats.
MIN_BEATS_PER_ARC = 4


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
    thread_id: str = ""
    thread_kind: str = ""
    thread_label: str = ""
    causation: dict[str, Any] = field(default_factory=dict)

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
            "thread_id": self.thread_id,
            "thread_kind": self.thread_kind,
            "thread_label": self.thread_label,
            "causation": dict(self.causation),
        }


def _chain(beats: Sequence[Beat]) -> dict[str, str]:
    """Assign beats to arc roles so each role is caused by the previous one.

    Selection is chronological by construction: each role only looks at beats that
    come after the last one chosen, so a six-panel strip is filled whenever the
    week has enough material instead of silently losing panels to a re-sort.
    """
    ordered = sorted(beats, key=lambda beat: (beat.ts, beat.id))
    if not ordered:
        return {}

    roles: dict[str, str] = {}
    used: set[str] = set()
    cursor = float("-inf")

    def take(candidates: Sequence[Beat]) -> Beat | None:
        for beat in candidates:
            if beat.id in used or beat.ts < cursor:
                continue
            return beat
        return None

    def commit(role: str, beat: Beat | None) -> None:
        nonlocal cursor
        if beat is None:
            return
        roles[role] = beat.id
        used.add(beat.id)
        cursor = beat.ts

    struggles = [beat for beat in ordered if beat.type in {"struggle", "failure"}]
    climax = max(struggles or ordered, key=lambda beat: (beat.intensity, beat.ts))
    # Everything before the climax, in timeline order.
    before = [beat for beat in ordered if beat.ts <= climax.ts and beat.id != climax.id]
    after = [beat for beat in ordered if beat.ts > climax.ts]

    setup = take([beat for beat in before if beat.type in {"decision", "level-up", "joke"}])
    if setup is None:
        setup = take(before)
    commit("setup", setup)

    hidden = take([beat for beat in before if beat.type in {"struggle", "failure"}])
    commit("hidden_problem", hidden)

    diagnosis = take(
        [beat for beat in before if beat.type in {"struggle", "failure", "decision"}]
    )
    if diagnosis is None:
        diagnosis = take([beat for beat in after if beat.type in {"struggle", "failure"}])
    commit("diagnosis", diagnosis)

    if climax.ts >= cursor:
        commit("climax", climax)

    aftermath = take([beat for beat in after if beat.type in {"breakthrough", "decision"}])
    if aftermath is None:
        aftermath = take([beat for beat in after if beat.type in {"struggle", "failure"}])
    if aftermath is None:
        aftermath = take(after)
    commit("aftermath", aftermath)

    win = take(
        [beat for beat in after if beat.type in {"breakthrough", "decision", "level-up"}]
    )
    if win is None:
        win = take([beat for beat in after if beat.type == "joke"])
    if win is None:
        win = take(after)
    commit("win", win)

    # A weekly strip wants 4-6 panels. If the chain is short, fill the remaining roles
    # with this thread's own unused beats - never another thread's - and lay the
    # selected beats out in time so the roles stay chronological.
    selected = [beat for beat in ordered if beat.id in used]
    if len(selected) < 4:
        extras = [beat for beat in ordered if beat.id not in used]
        filled = list(selected)
        while extras and len(filled) < 6:
            filled.append(extras.pop(0))
        # Only re-lay the roles if that actually gives a strip; a three-beat thread
        # keeps its chain (and its climax) rather than being renamed into nothing.
        if len(filled) >= 4:
            filled.sort(key=lambda beat: (beat.ts, beat.id))
            roles = {role: beat.id for role, beat in zip(ARC_ROLES, filled)}
    return roles


def _title(beats: Iterable[Beat]) -> str:
    ordered = list(beats)
    for beat in ordered:
        if "fields:" in beat.summary:
            continue
        summary = beat.summary
        if ": " in summary:
            # Beat summaries are "profile: text"; a title should not start with an id.
            summary = summary.split(": ", 1)[1]
        cleaned = " ".join(
            word.strip(" .,:;!?\u2014-") for word in summary.split()
        )
        words = [word for word in cleaned.split() if len(word) > 3 and not word.startswith("ev_")]
        if len(words) >= 3:
            return " ".join(words[:6])
    # Nothing readable: name the agents involved rather than dumping field lists.
    profiles = sorted({beat.profile for beat in ordered if beat.profile})
    if profiles:
        return "The week " + ", ".join(profiles[:3]) + " had"
    return "A week on the rig"


def _stakes(roles: dict[str, str], by_id: dict[str, Beat]) -> str:
    climax = by_id.get(roles.get("climax", ""))
    if climax is None:
        return "the week's work"
    source = climax.summary
    if "fields:" in source:
        # Fall back to another role's summary that reads like a sentence.
        for role in ("hidden_problem", "aftermath", "setup", "win"):
            beat = by_id.get(roles.get(role, ""))
            if beat is not None and "fields:" not in beat.summary:
                source = beat.summary
                break
    text = " ".join(word.strip(" .,:;!?\u2014-") for word in source.split())
    words = [word for word in text.split() if word]
    return " ".join(words[:14]) if words else "the week's work"


def build_arc(
    beats: Sequence[Beat],
    *,
    arc_type: str = "struggle-to-resolution",
    window_start: float = 0.0,
    thread: Thread | None = None,
    events_by_id: Mapping[str, GatedEvent] | None = None,
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
    causation: dict[str, Any] = {}
    if thread is not None:
        index = {event_id: thread for event_id in thread.event_ids}
        causation = causal_check(
            ARC_ROLES, roles, list(beats), index, events_by_id or {}
        )
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
        thread_id=thread.id if thread else "",
        thread_kind=thread.kind if thread else "",
        thread_label=thread.label if thread else "",
        causation=causation,
    )


def build_arcs(
    threads: Sequence[Thread],
    beats: Sequence[Beat],
    *,
    events_by_id: Mapping[str, GatedEvent] | None = None,
    max_arcs: int = 3,
    window_start: float = 0.0,
) -> list[Arc]:
    """One arc per qualifying thread, best thread first (audit M1-F2).

    A thread must carry at least three beats to become a story, and a thread with
    real gated text always beats one without: the bake-off's working story came from
    session and task titles, not from tool names.
    """
    grouped = beats_by_thread(beats, threads)
    arcs: list[Arc] = []
    # ``threads`` arrive best-first (text before size before recency), so the first
    # thread with enough beats is the story, not whichever thread happened to be
    # seen first.
    for thread in threads:
        thread_beats = grouped.get(thread.id, [])
        if len(thread_beats) < MIN_BEATS_PER_ARC:
            continue
        arc = build_arc(
            thread_beats,
            arc_type="struggle-to-resolution",
            window_start=window_start,
            thread=thread,
            events_by_id=events_by_id,
        )
        if arc is not None:
            arcs.append(arc)
        if len(arcs) >= max_arcs:
            break
    return arcs


@dataclass
class ArcLedger:
    arcs: list[Arc] = field(default_factory=list)

    def primary(self) -> Arc | None:
        return self.arcs[0] if self.arcs else None

    def as_dict(self) -> dict[str, Any]:
        return {"arcs": [arc.as_dict() for arc in self.arcs]}
