"""Threads: one real story, not stitched events (audit M1-F2).

The M1 arc stitched six unrelated events from five agents across six days and called
it a story. A story needs a spine, so events are grouped into threads first:

* **task** - a kanban family: a task and its parent/child links, with the whole
  lifecycle (created, claimed, status changes, runs, comments) of every task in it;
* **session** - a session lineage: a session and its ``parent_session_id`` ancestors
  and descendants, with their messages and tool calls;
* **entity** - a shared subject that is neither: one skill, one cron job.

An arc is then built from the beats of **one** thread. Two events from different
threads can never share an arc, which is what the negative tests assert.

``causal_check`` answers the audit's other point: rising timestamps are not causation,
so an arc only claims causation when every step stays inside the thread *and* moves the
thread's lifecycle forward (kanban) or follows the session lineage.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

from canon.beats import Beat
from canon.events import (
    KIND_CRON_FINISHED,
    KIND_CRON_STARTED,
    KIND_MESSAGE_ASSISTANT,
    KIND_MESSAGE_META,
    KIND_MESSAGE_TOOL_RESULT,
    KIND_MESSAGE_USER,
    KIND_SESSION_STARTED,
    KIND_TASK_CLAIMED,
    KIND_TASK_COMMENT,
    KIND_TASK_CREATED,
    KIND_TASK_FINISHED,
    KIND_TASK_LINK,
    KIND_TASK_STATUS,
    KIND_TOOL_CALL,
    make_event_id,
)
from canon.gate import GatedEvent, require_gated

THREAD_KINDS = ("task", "session", "entity")

MESSAGE_KINDS = frozenset(
    {
        KIND_MESSAGE_USER,
        KIND_MESSAGE_ASSISTANT,
        KIND_MESSAGE_TOOL_RESULT,
        KIND_MESSAGE_META,
        KIND_TOOL_CALL,
    }
)
TASK_KINDS = frozenset(
    {KIND_TASK_CREATED, KIND_TASK_CLAIMED, KIND_TASK_STATUS, KIND_TASK_FINISHED, KIND_TASK_COMMENT}
)

#: Kanban lifecycle order, used by the causation check.
LIFECYCLE_RANK: dict[str, int] = {
    "created": 0,
    "claimed": 1,
    "spawned": 1,
    "specified": 1,
    "decomposed": 1,
    "dependency_wait": 2,
    "blocked": 3,
    "block_loop_detected": 4,
    "gave_up": 5,
    "unblocked": 4,
    "review_requested": 5,
    "completed": 6,
}


class _UnionFind:
    def __init__(self) -> None:
        self.parent: dict[str, str] = {}

    def find(self, item: str) -> str:
        self.parent.setdefault(item, item)
        root = item
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[item] != root:
            self.parent[item], item = root, self.parent[item]
        return root

    def union(self, left: str, right: str) -> None:
        left_root, right_root = self.find(left), self.find(right)
        if left_root != right_root:
            self.parent[max(left_root, right_root)] = min(left_root, right_root)


@dataclass(frozen=True, slots=True)
class Thread:
    id: str
    kind: str
    key: str
    label: str
    event_ids: tuple[str, ...]
    start: float
    end: float
    has_text: bool = False
    size: int = 0

    def __post_init__(self) -> None:
        if self.kind not in THREAD_KINDS:
            raise ValueError(f"unknown thread kind: {self.kind!r}")

    #: True when the thread reached a completed state (round 3, item 4).
    completed: bool = False

    @property
    def score(self) -> tuple[int, int, float, float]:
        """Prefer threads that finished, then ones with text, then size, then recency."""
        return (1 if self.completed else 0, 1 if self.has_text else 0, self.size, self.end)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "key": self.key,
            "label": self.label,
            "event_ids": list(self.event_ids),
            "start": round(self.start, 6),
            "end": round(self.end, 6),
            "has_text": self.has_text,
            "completed": self.completed,
            "size": self.size,
        }


def _task_key(event: GatedEvent) -> str | None:
    task_id = event.payload.get("task_id") or event.payload.get("parent_id")
    return str(task_id) if task_id else None


def _session_key(event: GatedEvent) -> str | None:
    session_id = event.payload.get("session_id")
    if session_id:
        return str(session_id)
    if event.kind == KIND_SESSION_STARTED:
        return str(event.ref.get("pk") or "")
    return None


def _label_for(events: Sequence[GatedEvent]) -> str:
    """The best human-meaningful gated text in the thread, if any."""
    for event in events:
        text = event.payload.get("text")
        if isinstance(text, str):
            cleaned = " ".join(text.split())
            if len(cleaned) >= 8:
                return cleaned[:90]
    for event in events:
        if event.subject:
            return event.subject[:90]
    return events[0].kind if events else ""


def build_threads(events: Iterable[GatedEvent]) -> list[Thread]:
    """Group gated events into task families, session lineages and shared subjects."""
    gated = require_gated(events, stage="threads")
    by_id = {event.id: event for event in gated}

    tasks = _UnionFind()
    sessions = _UnionFind()

    for event in gated:
        if event.kind == KIND_TASK_LINK:
            parent = str(event.payload.get("parent_id") or "")
            child = str(event.payload.get("child_id") or "")
            if parent and child:
                tasks.union(parent, child)
        elif event.kind in TASK_KINDS:
            key = _task_key(event)
            if key:
                tasks.find(key)
        parent_session = str(event.payload.get("parent_session_id") or "")
        if event.kind == KIND_SESSION_STARTED and parent_session:
            own = str(event.ref.get("pk") or "")
            if own:
                sessions.union(own, parent_session)
        if event.kind in MESSAGE_KINDS:
            key = _session_key(event)
            if key:
                sessions.find(key)

    task_groups: dict[str, list[GatedEvent]] = {}
    session_groups: dict[str, list[GatedEvent]] = {}
    entity_groups: dict[str, list[GatedEvent]] = {}

    for event in gated:
        if event.kind == KIND_TASK_LINK:
            continue
        if event.kind in TASK_KINDS:
            key = _task_key(event)
            if key:
                task_groups.setdefault(tasks.find(key), []).append(event)
                continue
        if event.kind in MESSAGE_KINDS or event.kind == KIND_SESSION_STARTED:
            key = _session_key(event)
            if key:
                session_groups.setdefault(sessions.find(key), []).append(event)
                continue
        if event.kind in {KIND_CRON_STARTED, KIND_CRON_FINISHED}:
            subject = event.subject or str(event.payload.get("job_id") or "")
            if subject:
                entity_groups.setdefault(f"cron:{subject}", []).append(event)
                continue
        if event.kind.startswith("skill.") and event.subject:
            entity_groups.setdefault(f"skill:{event.subject}", []).append(event)

    threads: list[Thread] = []
    for family, group in task_groups.items():
        threads.append(_thread("task", family, group))
    for lineage, group in session_groups.items():
        threads.append(_thread("session", lineage, group))
    for key, group in entity_groups.items():
        threads.append(_thread("entity", key, group))

    threads = [thread for thread in threads if thread.size >= 3]
    threads.sort(key=lambda thread: (-thread.score[0], -thread.score[1], -thread.score[2], thread.id))
    return threads


def _thread(kind: str, key: str, group: Sequence[GatedEvent]) -> Thread:
    ordered = sorted(group, key=lambda event: (event.ts, event.id))
    label = _label_for(ordered)
    has_text = any(
        isinstance(event.payload.get("text"), str) and len(str(event.payload.get("text"))) >= 8
        for event in ordered
    )
    completed = any(
        (event.kind == KIND_TASK_FINISHED)
        or (event.kind == KIND_TASK_STATUS and str(event.payload.get("kind")) == "completed")
        for event in ordered
    )
    return Thread(
        completed=completed,
        id=make_event_id("thread", kind, ordered[0].ts, {"key": key}),
        kind=kind,
        key=key,
        label=label,
        event_ids=tuple(event.id for event in ordered),
        start=ordered[0].ts,
        end=ordered[-1].ts,
        has_text=has_text,
        size=len(ordered),
    )


def thread_index(threads: Sequence[Thread]) -> dict[str, Thread]:
    """event id -> thread."""
    index: dict[str, Thread] = {}
    for thread in threads:
        for event_id in thread.event_ids:
            index[event_id] = thread
    return index


def beats_by_thread(beats: Sequence[Beat], threads: Sequence[Thread]) -> dict[str, list[Beat]]:
    index = thread_index(threads)
    grouped: dict[str, list[Beat]] = {}
    for beat in beats:
        thread = next((index[event_id] for event_id in beat.event_ids if event_id in index), None)
        if thread is None:
            continue
        grouped.setdefault(thread.id, []).append(beat)
    return grouped


# --------------------------------------------------------------------------- #
# causation
# --------------------------------------------------------------------------- #


def _event_rank(event: GatedEvent) -> int | None:
    if event.kind == KIND_TASK_CREATED:
        return LIFECYCLE_RANK["created"]
    if event.kind == KIND_TASK_CLAIMED:
        return LIFECYCLE_RANK["claimed"]
    if event.kind == KIND_TASK_STATUS:
        return LIFECYCLE_RANK.get(str(event.payload.get("kind") or ""), None)
    if event.kind == KIND_TASK_FINISHED:
        return LIFECYCLE_RANK["completed"]
    return None


def causal_check(
    role_order: Sequence[str],
    roles: Mapping[str, str],
    beats: Sequence[Beat],
    index: Mapping[str, Thread],
    events_by_id: Mapping[str, GatedEvent],
) -> dict[str, Any]:
    """Does each panel follow from the previous one, or is this only a timestamp order?

    A link is verified when both beats belong to the same thread and the later event
    moves that thread forward: for a task, a non-decreasing lifecycle rank; for a
    session, a later timestamp inside the same lineage.
    """
    by_beat = {beat.id: beat for beat in beats}
    links: list[dict[str, Any]] = []
    verified = True
    previous: Beat | None = None
    for role in role_order:
        beat_id = roles.get(role)
        if not beat_id or beat_id not in by_beat:
            continue
        beat = by_beat[beat_id]
        if previous is not None:
            prev_thread = next((index[event_id] for event_id in previous.event_ids if event_id in index), None)
            cur_thread = next((index[event_id] for event_id in beat.event_ids if event_id in index), None)
            same_thread = prev_thread is not None and cur_thread is not None and prev_thread.id == cur_thread.id
            forward = beat.ts >= previous.ts
            detail = "same thread, later in time" if same_thread else "different thread"
            if same_thread and prev_thread is not None and prev_thread.kind == "task":
                prev_ranks = [
                    rank
                    for event_id in previous.event_ids
                    if (event := events_by_id.get(event_id)) is not None
                    if (rank := _event_rank(event)) is not None
                ]
                cur_ranks = [
                    rank
                    for event_id in beat.event_ids
                    if (event := events_by_id.get(event_id)) is not None
                    if (rank := _event_rank(event)) is not None
                ]
                if prev_ranks and cur_ranks and max(cur_ranks) < max(prev_ranks):
                    same_thread = False
                    detail = "lifecycle went backwards"
                elif cur_ranks:
                    detail = "same task thread, lifecycle advanced"
            ok = same_thread and forward
            verified = verified and ok
            links.append(
                {
                    "from": previous.id,
                    "to": beat.id,
                    "verified": ok,
                    "detail": detail,
                }
            )
        previous = beat
    return {"verified": verified and len(links) > 0, "links": links}
