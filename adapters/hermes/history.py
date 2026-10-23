"""Hermes history adapter: read-only ingest of a live Hermes home.

Reads, from every profile plus the fleet-wide stores:

* ``state.db``: ``sessions`` and ``messages`` (tool calls live as JSON in
  ``messages.tool_calls``; there is no separate tool-call table)
* ``kanban.db``: ``tasks``, ``task_events``, ``task_runs``
* ``skills/.usage.json`` per profile
* ``cron/executions.db`` plus ``cron/jobs.json`` for job names
* ``memories/MEMORY.md`` and ``USER.md`` fact snapshots (and diffs when a prior
  snapshot is supplied)

...and normalises all of it into one deterministic ``Event`` stream
(``canon.events``). Event payloads carry structure and digests, never free
text; the text sits behind a ``ContentRef`` for the ingest stage to fetch and
redact.

CLI::

    python -m adapters.hermes.history --days 7 --summary

The adapter only ever opens databases read-only (see ``adapters/hermes/ro.py``).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence

from canon.events import (
    ALL_SOURCES,
    KIND_CRON_FINISHED,
    KIND_CRON_STARTED,
    KIND_MEMORY_ADDED,
    KIND_MEMORY_FACT,
    KIND_MEMORY_REMOVED,
    KIND_MESSAGE_ASSISTANT,
    KIND_MESSAGE_META,
    KIND_MESSAGE_TOOL_RESULT,
    KIND_MESSAGE_USER,
    KIND_RUN_FINISHED,
    KIND_RUN_STARTED,
    KIND_SESSION_ENDED,
    KIND_SESSION_STARTED,
    KIND_SKILL_ARCHIVED,
    KIND_SKILL_CREATED,
    KIND_SKILL_PATCHED,
    KIND_SKILL_USED,
    KIND_TASK_CLAIMED,
    KIND_TASK_COMMENT,
    KIND_TASK_CREATED,
    KIND_TASK_FINISHED,
    KIND_TASK_STATUS,
    KIND_TOOL_CALL,
    SOURCE_CRON,
    SOURCE_KANBAN,
    SOURCE_MEMORY,
    SOURCE_MESSAGE,
    SOURCE_ORDER,
    SOURCE_SESSION,
    SOURCE_SKILL,
    SOURCE_TOOL_CALL,
    Event,
    build_event,
    make_event_id,
    text_digest,
)
from canon.source import ContentUnavailable, ProfileRef, SourceInfo, Window

from adapters.hermes import ro
from adapters.hermes.paths import HermesPaths, ProfileStore
from adapters.hermes.stores import StoreReader

STORE_MAIN = "main"
STORE_KANBAN = "kanban"
STORE_CRON = "cron"
STORE_SKILLS = "skills"

#: Primary-key column per table, used to materialise a ``ContentRef``.
PK_COLUMNS: dict[str, str] = {
    "messages": "id",
    "sessions": "id",
    "tasks": "id",
    "task_events": "id",
    "task_runs": "id",
    "task_comments": "id",
    "executions": "id",
}

#: Only these tables may be read through ``fetch_content``.
CONTENT_TABLES = frozenset(PK_COLUMNS)

#: task_events kinds that represent a state change worth a story beat.
STATUS_EVENT_KINDS = frozenset(
    {
        "created",
        "claimed",
        "promoted",
        "completed",
        "blocked",
        "unblocked",
        "review_requested",
        "gave_up",
        "archived",
        "auto_archived",
        "decomposed",
        "spawned",
        "specified",
        "worker_result",
        "block_loop_detected",
        "protocol_violation",
        "claim_rejected",
        "dependency_wait",
        "owner_admitted",
        "forced_skill_rejected",
    }
)

#: High-volume, low-story kinds dropped from the event stream (still counted).
NOISE_EVENT_KINDS = frozenset({"heartbeat"})

MESSAGE_KIND_BY_ROLE = {
    "user": KIND_MESSAGE_USER,
    "assistant": KIND_MESSAGE_ASSISTANT,
    "tool": KIND_MESSAGE_TOOL_RESULT,
    "session_meta": KIND_MESSAGE_META,
}

TITLE_PREVIEW = 160
FACT_SEPARATOR = "\u00a7"


# --------------------------------------------------------------------------- #
# small helpers
# --------------------------------------------------------------------------- #


def _row_get(row: sqlite3.Row, name: str, default: Any = None) -> Any:
    try:
        keys = row.keys()
    except AttributeError:  # pragma: no cover - defensive
        return default
    return row[name] if name in keys else default


def _epoch(value: Any) -> float | None:
    """Coerce a stored timestamp to epoch seconds.

    Hermes stores epoch seconds (REAL/INTEGER) almost everywhere and ISO-8601
    text in the cron ledger; this handles both without guessing units silently.
    """
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        pass
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def _iso(ts: float | None) -> str:
    if ts is None:
        return ""
    return datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat(timespec="seconds")


#: Long opaque identifiers (session ids, uuids) show up inside titles and are
#: noise in a summary; keep a short prefix so they stay recognisable.
_LONG_ID = re.compile(
    r"\b(?:local|sess|session|run|exec)[-_][0-9a-f]{16,}\b"
    r"|\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b"
)


def _mask_ids(text: str) -> str:
    return _LONG_ID.sub(lambda m: m.group(0)[:14] + "\u2026", text)


def _preview(text: str | None, limit: int = TITLE_PREVIEW) -> str:
    if not text:
        return ""
    flat = _mask_ids(" ".join(str(text).split()))
    return flat if len(flat) <= limit else flat[: limit - 1] + "\u2026"


def _parse_json_list(raw: str | None) -> list[Any]:
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return []
    return value if isinstance(value, list) else []


def _tool_names_from_calls(raw: str | None) -> list[str]:
    names: list[str] = []
    for entry in _parse_json_list(raw):
        if not isinstance(entry, Mapping):
            continue
        fn = entry.get("function") if isinstance(entry.get("function"), Mapping) else entry
        name = (fn or {}).get("name")
        if isinstance(name, str) and name:
            names.append(name)
    return names


def _split_facts(text: str) -> list[str]:
    """Split a Hermes memory file into facts.

    Facts are separated by a line containing only the section sign. A file with
    no separator is one fact per non-empty line, which is what older stores use.
    """
    if FACT_SEPARATOR in text:
        parts = re.split(rf"\n\s*{re.escape(FACT_SEPARATOR)}\s*\n", text)
    else:
        parts = text.splitlines()
    return [part.strip() for part in parts if part.strip()]


# --------------------------------------------------------------------------- #
# the adapter
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class ReadCounts:
    emitted: int
    skipped_noise: int
    skipped_inactive: int


class HermesHistorySource:
    """``HistorySource`` implementation for a Hermes home."""

    def __init__(
        self,
        root: str | os.PathLike[str] | None = None,
        *,
        profiles: Sequence[str] | None = None,
        include_main: bool = True,
        memory_snapshot: Mapping[str, Any] | None = None,
        snapshot_root: Path | str | None = None,
    ) -> None:
        self.paths = HermesPaths.resolve(root if root is not None else None)
        self._profile_filter = tuple(profiles) if profiles else None
        self._include_main = include_main
        self._memory_snapshot = dict(memory_snapshot or {})
        self._counters: dict[str, ReadCounts] = {}
        # All database access goes through this: it refuses to create anything
        # inside the Hermes home (see adapters/hermes/stores.py).
        self._stores = StoreReader(snapshot_root=snapshot_root)
        self._stores_closed = False

    def close(self) -> None:
        if not self._stores_closed:
            self._stores.close()
            self._stores_closed = True

    def store_decisions(self):
        return self._stores.decisions()

    # -- discovery ---------------------------------------------------------
    def info(self) -> SourceInfo:
        stores: list[str] = []
        missing: list[str] = []
        if self.paths.main_state_db.is_file():
            stores.append("state.db")
        else:
            missing.append("state.db")
        for label, path in (
            ("kanban.db", self.paths.kanban_db),
            ("cron/executions.db", self.paths.cron_executions_db),
            ("cron/jobs.json", self.paths.cron_jobs_json),
            ("skills/.usage.json", self.paths.skills_usage_json),
        ):
            (stores if path.is_file() else missing).append(label)
        profs = tuple(
            ProfileRef(name=p.name, store=p.state_db.name if p.available else "")
            for p in self._selected_profiles()
        )
        return SourceInfo(
            harness="hermes",
            root=str(self.paths.home),
            profiles=profs,
            stores=tuple(stores),
            missing=tuple(missing),
        )

    def _selected_profiles(self) -> list[ProfileStore]:
        stores = self.paths.profiles()
        if self._profile_filter is None:
            return stores
        wanted = set(self._profile_filter)
        return [store for store in stores if store.name in wanted]

    def counters(self) -> dict[str, ReadCounts]:
        return dict(self._counters)

    # -- event stream ------------------------------------------------------
    def events(
        self, window: Window, sources: Sequence[str] | None = None
    ) -> Iterator[Event]:
        wanted = tuple(sources) if sources else SOURCE_ORDER
        unknown = set(wanted) - ALL_SOURCES
        if unknown:
            raise ValueError(f"unknown sources requested: {sorted(unknown)}")
        self._counters = {}
        for source in SOURCE_ORDER:
            if source not in wanted:
                continue
            if source == SOURCE_SESSION:
                yield from self._iter_sessions(window)
            elif source == SOURCE_MESSAGE:
                yield from self._iter_messages(window)
            elif source == SOURCE_TOOL_CALL:
                yield from self._iter_tool_calls(window)
            elif source == SOURCE_KANBAN:
                yield from self._iter_kanban(window)
            elif source == SOURCE_SKILL:
                yield from self._iter_skills(window)
            elif source == SOURCE_CRON:
                yield from self._iter_cron(window)
            elif source == SOURCE_MEMORY:
                yield from self._iter_memory(window)

    def _count(self, source: str, *, emitted: int = 0, noise: int = 0, inactive: int = 0) -> None:
        prev = self._counters.get(source, ReadCounts(0, 0, 0))
        self._counters[source] = ReadCounts(
            prev.emitted + emitted, prev.skipped_noise + noise, prev.skipped_inactive + inactive
        )

    # -- sessions ----------------------------------------------------------
    def _session_databases(self) -> Iterator[tuple[str, Path, str]]:
        """Yield ``(store, path, default_profile)`` for every session store."""
        if self._include_main and self.paths.main_state_db.is_file():
            yield STORE_MAIN, self.paths.main_state_db, "default"
        for store in self._selected_profiles():
            if store.available:
                yield f"profile:{store.name}", store.state_db, store.name

    def _iter_sessions(self, window: Window) -> Iterator[Event]:
        for store, path, default_profile in self._session_databases():
            conn = self._stores.open(path)
            try:
                if not ro.table_exists(conn, "sessions"):
                    continue
                cols = ro.filter_columns(
                    conn,
                    "sessions",
                    (
                        "id",
                        "source",
                        "title",
                        "profile_name",
                        "started_at",
                        "ended_at",
                        "end_reason",
                        "message_count",
                        "tool_call_count",
                        "input_tokens",
                        "output_tokens",
                        "model",
                        "git_branch",
                        "cwd",
                        "parent_session_id",
                        "last_activity_at",
                        "archived",
                    ),
                )
                if not cols:
                    continue
                select = ", ".join(cols)
                activity_expr = (
                    "COALESCE(last_activity_at, started_at)"
                    if "last_activity_at" in cols
                    else "started_at"
                )
                rows = conn.execute(
                    f"SELECT {select} FROM sessions "
                    f"WHERE {activity_expr} >= ? "
                    "ORDER BY started_at ASC, id ASC",
                    (window.since,),
                )
                for row in rows:
                    started = _epoch(_row_get(row, "started_at"))
                    if started is None:
                        continue
                    last_activity = _epoch(_row_get(row, "last_activity_at"))
                    ended = _epoch(_row_get(row, "ended_at"))
                    # Keep a session when it was alive at any point in the window,
                    # even if it began before it (long-running sessions matter to
                    # the story). ``span_in_window`` tells consumers which is which.
                    stamps = [t for t in (started, last_activity, ended) if t is not None]
                    if not any(window.contains(t) for t in stamps):
                        continue
                    title = _row_get(row, "title") or ""
                    profile = (_row_get(row, "profile_name") or default_profile or "").strip()
                    cwd = _row_get(row, "cwd") or ""
                    payload = {
                        "source": _row_get(row, "source") or "",
                        "model": _row_get(row, "model") or "",
                        # Owner decision 3 (M0 audit): the title lives behind the
                        # content ref and only the redaction gate releases it.
                        "title_chars": len(title),
                        "started_at": started,
                        "ended_at": ended,
                        "last_activity_at": last_activity,
                        "message_count": _row_get(row, "message_count") or 0,
                        "tool_call_count": _row_get(row, "tool_call_count") or 0,
                        "input_tokens": _row_get(row, "input_tokens") or 0,
                        "output_tokens": _row_get(row, "output_tokens") or 0,
                        "git_branch": _row_get(row, "git_branch") or "",
                        "cwd_name": Path(cwd).name if cwd else "",
                        "parent_session_id": _row_get(row, "parent_session_id") or "",
                        "archived": bool(_row_get(row, "archived") or 0),
                        "span_in_window": started < window.since,
                    }
                    yield build_event(
                        source=SOURCE_SESSION,
                        kind=KIND_SESSION_STARTED,
                        ts=started,
                        profile=profile,
                        actor=profile,
                        subject=_row_get(row, "source") or "",
                        payload=payload,
                        store=store,
                        table="sessions",
                        pk=str(_row_get(row, "id")),
                        content_column="title",
                    )
                    self._count(SOURCE_SESSION, emitted=1)
                    if ended is not None and ended >= window.since and (
                        window.until is None or ended < window.until
                    ):
                        yield build_event(
                            source=SOURCE_SESSION,
                            kind=KIND_SESSION_ENDED,
                            ts=ended,
                            profile=profile,
                            actor=profile,
                            subject=_row_get(row, "end_reason") or "",
                            payload={
                                "end_reason": _row_get(row, "end_reason") or "",
                                "started_at": started,
                                "message_count": _row_get(row, "message_count") or 0,
                                "tool_call_count": _row_get(row, "tool_call_count") or 0,
                            },
                            store=store,
                            table="sessions",
                            pk=str(_row_get(row, "id")),
                            content_column=None,
                            discriminator="ended",
                        )
                        self._count(SOURCE_SESSION, emitted=1)
            finally:
                ro.safe_close(conn)

    # -- messages ----------------------------------------------------------
    def _iter_messages(self, window: Window) -> Iterator[Event]:
        for store, path, default_profile in self._session_databases():
            conn = self._stores.open(path)
            try:
                if not ro.table_exists(conn, "messages"):
                    continue
                has_sessions = ro.table_exists(conn, "sessions")
                msg_cols = ro.filter_columns(
                    conn,
                    "messages",
                    (
                        "id",
                        "session_id",
                        "role",
                        "content",
                        "tool_name",
                        "tool_call_id",
                        "tool_calls",
                        "timestamp",
                        "token_count",
                        "active",
                        "compacted",
                    ),
                )
                if not msg_cols:
                    continue
                select = ", ".join(f"m.{c}" for c in msg_cols)
                join = "LEFT JOIN sessions s ON s.id = m.session_id" if has_sessions else ""
                session_cols = (
                    ro.filter_columns(conn, "sessions", ("profile_name",)) if has_sessions else []
                )
                session_select = ", s.profile_name AS session_profile" if session_cols else ""
                active_clause = (
                    "AND COALESCE(m.active, 1) = 1" if "active" in msg_cols else ""
                )
                sql = (
                    f"SELECT {select}{session_select} FROM messages m {join} "
                    f"WHERE m.timestamp >= ? {active_clause} "
                    "ORDER BY m.timestamp ASC, m.id ASC"
                )
                params: list[Any] = [window.since]
                if window.until is not None:
                    sql = sql.replace("ORDER BY", "AND m.timestamp < ? ORDER BY")
                    params.append(window.until)
                for row in conn.execute(sql, params):
                    ts = _epoch(_row_get(row, "timestamp"))
                    if ts is None:
                        continue
                    role = (_row_get(row, "role") or "").strip()
                    kind = MESSAGE_KIND_BY_ROLE.get(role)
                    if kind is None:
                        continue
                    profile = (
                        _row_get(row, "session_profile") or default_profile or ""
                    ).strip()
                    raw_calls = _row_get(row, "tool_calls")
                    tool_names = _tool_names_from_calls(raw_calls)
                    content = _row_get(row, "content")
                    chars = len(content) if isinstance(content, str) else 0
                    payload = {
                        "role": role,
                        "session_id": _row_get(row, "session_id") or "",
                        "chars": chars,
                        "content_digest": text_digest(content) if chars else "",
                        "tool_name": _row_get(row, "tool_name") or "",
                        "tool_call_id": _row_get(row, "tool_call_id") or "",
                        "tool_names": tool_names,
                        "tool_call_count": len(tool_names),
                        "token_count": _row_get(row, "token_count") or 0,
                        "compacted": bool(_row_get(row, "compacted") or 0),
                    }
                    actor = profile if role == "user" else (payload["tool_name"] or role)
                    yield build_event(
                        source=SOURCE_MESSAGE,
                        kind=kind,
                        ts=ts,
                        profile=profile,
                        actor=actor,
                        subject=payload["tool_name"] or role,
                        payload=payload,
                        store=store,
                        table="messages",
                        pk=str(_row_get(row, "id")),
                        content_column="content",
                    )
                    self._count(SOURCE_MESSAGE, emitted=1)
            finally:
                ro.safe_close(conn)

    # -- tool calls (JSON inside assistant messages) ------------------------
    def _iter_tool_calls(self, window: Window) -> Iterator[Event]:
        for store, path, default_profile in self._session_databases():
            conn = self._stores.open(path)
            try:
                if not ro.table_exists(conn, "messages"):
                    continue
                has_sessions = ro.table_exists(conn, "sessions")
                session_select = ""
                join = ""
                if has_sessions:
                    join = "LEFT JOIN sessions s ON s.id = m.session_id"
                    if ro.filter_columns(conn, "sessions", ("profile_name",)):
                        session_select = ", s.profile_name AS session_profile"
                sql = (
                    "SELECT m.id AS id, m.session_id AS session_id, m.timestamp AS timestamp, "
                    f"m.tool_calls AS tool_calls{session_select} FROM messages m {join} "
                    "WHERE m.timestamp >= ? AND m.tool_calls IS NOT NULL"
                )
                params: list[Any] = [window.since]
                if window.until is not None:
                    sql += " AND m.timestamp < ?"
                    params.append(window.until)
                sql += " ORDER BY m.timestamp ASC, m.id ASC"
                for row in conn.execute(sql, params):
                    ts = _epoch(_row_get(row, "timestamp"))
                    if ts is None:
                        continue
                    profile = (
                        _row_get(row, "session_profile") or default_profile or ""
                    ).strip()
                    message_id = str(_row_get(row, "id"))
                    for index, entry in enumerate(_parse_json_list(_row_get(row, "tool_calls"))):
                        if not isinstance(entry, Mapping):
                            continue
                        fn = (
                            entry.get("function")
                            if isinstance(entry.get("function"), Mapping)
                            else entry
                        )
                        name = str((fn or {}).get("name") or "").strip()
                        if not name:
                            continue
                        raw_args = (fn or {}).get("arguments")
                        args_text = raw_args if isinstance(raw_args, str) else json.dumps(
                            raw_args, sort_keys=True, default=str
                        )
                        call_id = str(
                            entry.get("call_id") or entry.get("id") or f"{message_id}#{index}"
                        )
                        payload = {
                            "tool": name,
                            "call_id": call_id,
                            "session_id": _row_get(row, "session_id") or "",
                            "message_id": message_id,
                            "args_chars": len(args_text),
                            "args_digest": text_digest(args_text),
                            "args_keys": sorted(_arg_keys(args_text)),
                        }
                        yield build_event(
                            source=SOURCE_TOOL_CALL,
                            kind=KIND_TOOL_CALL,
                            ts=ts,
                            profile=profile,
                            actor=profile,
                            subject=name,
                            payload=payload,
                            store=store,
                            table="messages",
                            pk=message_id,
                            content_column="tool_calls",
                            discriminator=f"{index}:{call_id}",
                        )
                        self._count(SOURCE_TOOL_CALL, emitted=1)
            finally:
                ro.safe_close(conn)

    # -- kanban ------------------------------------------------------------
    def _iter_kanban(self, window: Window) -> Iterator[Event]:
        path = self.paths.kanban_db
        if not path.is_file():
            return
        allowed = set(self._profile_filter) if self._profile_filter else None
        conn = self._stores.open(path)
        try:
            for event in self._kanban_tasks(conn, window, allowed):
                yield event
            for event in self._kanban_task_events(conn, window, allowed):
                yield event
            for event in self._kanban_runs(conn, window, allowed):
                yield event
            for event in self._kanban_comments(conn, window, allowed):
                yield event
        finally:
            ro.safe_close(conn)

    def _kanban_tasks(
        self, conn: sqlite3.Connection, window: Window, allowed: set[str] | None = None
    ) -> Iterator[Event]:
        if not ro.table_exists(conn, "tasks"):
            return
        cols = ro.filter_columns(
            conn,
            "tasks",
            (
                "id",
                "title",
                "assignee",
                "status",
                "priority",
                "created_by",
                "created_at",
                "started_at",
                "completed_at",
                "tenant",
                "project_id",
                "result",
            ),
        )
        if not cols:
            return
        bounds = []
        params: list[Any] = []
        if "created_at" in cols:
            bounds.append("created_at >= ?")
            params.append(window.since)
        for column in ("completed_at", "started_at"):
            if column in cols:
                bounds.append(f"COALESCE({column}, 0) >= ?")
                params.append(window.since)
        where = " OR ".join(bounds) if bounds else "1=1"
        sql = (
            f"SELECT {', '.join(cols)} FROM tasks WHERE {where} "
            "ORDER BY created_at ASC, id ASC"
        )
        for row in conn.execute(sql, params):
            task_id = str(_row_get(row, "id"))
            created = _epoch(_row_get(row, "created_at"))
            started = _epoch(_row_get(row, "started_at"))
            completed = _epoch(_row_get(row, "completed_at"))
            title = _row_get(row, "title") or ""
            assignee = (_row_get(row, "assignee") or "").strip()
            if allowed is not None and assignee not in allowed:
                continue
            if created is not None:
                yield build_event(
                    source=SOURCE_KANBAN,
                    kind=KIND_TASK_CREATED,
                    ts=created,
                    profile=assignee,
                    actor=(_row_get(row, "created_by") or "").strip(),
                    subject=task_id,
                    payload={
                        "task_id": task_id,
                        "title_chars": len(title),
                        "assignee": assignee,
                        "status": _row_get(row, "status") or "",
                        "priority": _row_get(row, "priority") or 0,
                        "created_by": (_row_get(row, "created_by") or ""),
                        "tenant": _row_get(row, "tenant") or "",
                        "project_id": _row_get(row, "project_id") or "",
                    },
                    store=STORE_KANBAN,
                    table="tasks",
                    pk=task_id,
                    content_column="title",
                )
                self._count(SOURCE_KANBAN, emitted=1)
            if started is not None and started >= window.since:
                yield build_event(
                    source=SOURCE_KANBAN,
                    kind=KIND_TASK_CLAIMED,
                    ts=started,
                    profile=assignee,
                    actor=assignee,
                    subject=task_id,
                    payload={"task_id": task_id, "assignee": assignee},
                    store=STORE_KANBAN,
                    table="tasks",
                    pk=task_id,
                    content_column=None,
                    discriminator="claimed",
                )
                self._count(SOURCE_KANBAN, emitted=1)
            if completed is not None and completed >= window.since:
                yield build_event(
                    source=SOURCE_KANBAN,
                    kind=KIND_TASK_FINISHED,
                    ts=completed,
                    profile=assignee,
                    actor=assignee,
                    subject=task_id,
                    payload={
                        "task_id": task_id,
                        "assignee": assignee,
                        "status": _row_get(row, "status") or "",
                    },
                    store=STORE_KANBAN,
                    table="tasks",
                    pk=task_id,
                    content_column="result",
                    discriminator="finished",
                )
                self._count(SOURCE_KANBAN, emitted=1)

    def _kanban_task_events(
        self, conn: sqlite3.Connection, window: Window, allowed: set[str] | None = None
    ) -> Iterator[Event]:
        if not ro.table_exists(conn, "task_events"):
            return
        cols = ro.filter_columns(
            conn, "task_events", ("id", "task_id", "run_id", "kind", "payload", "created_at")
        )
        if not cols:
            return
        select = ", ".join(f"e.{column}" for column in cols)
        join = "LEFT JOIN tasks t ON t.id = e.task_id" if ro.table_exists(conn, "tasks") else ""
        assignee_select = ", t.assignee AS assignee" if join else ""
        sql = (
            f"SELECT {select}{assignee_select} FROM task_events e {join} WHERE e.created_at >= ? "
            "ORDER BY e.created_at ASC, e.id ASC"
        )
        params: list[Any] = [window.since]
        if window.until is not None:
            sql = sql.replace("ORDER BY", "AND e.created_at < ? ORDER BY")
            params.append(window.until)
        for row in conn.execute(sql, params):
            if allowed is not None and (_row_get(row, "assignee") or "").strip() not in allowed:
                continue
            kind = str(_row_get(row, "kind") or "")
            if kind in NOISE_EVENT_KINDS:
                self._count(SOURCE_KANBAN, noise=1)
                continue
            if kind not in STATUS_EVENT_KINDS:
                self._count(SOURCE_KANBAN, noise=1)
                continue
            ts = _epoch(_row_get(row, "created_at"))
            if ts is None:
                continue
            assignee = (_row_get(row, "assignee") or "").strip()
            raw_payload = _row_get(row, "payload") or ""
            payload_keys: list[str] = []
            if isinstance(raw_payload, str) and raw_payload.strip():
                try:
                    parsed = json.loads(raw_payload)
                except ValueError:
                    parsed = None
                if isinstance(parsed, Mapping):
                    payload_keys = sorted(str(key) for key in parsed)
            yield build_event(
                source=SOURCE_KANBAN,
                kind=KIND_TASK_STATUS,
                ts=ts,
                profile=assignee,
                actor=assignee,
                subject=kind,
                payload={
                    "task_id": str(_row_get(row, "task_id") or ""),
                    "kind": kind,
                    "assignee": assignee,
                    "run_id": _row_get(row, "run_id"),
                    "payload_keys": payload_keys,
                    "payload_digest": text_digest(raw_payload)
                    if isinstance(raw_payload, str) and raw_payload
                    else "",
                },
                store=STORE_KANBAN,
                table="task_events",
                pk=str(_row_get(row, "id")),
                content_column="payload",
            )
            self._count(SOURCE_KANBAN, emitted=1)

    def _kanban_runs(
        self, conn: sqlite3.Connection, window: Window, allowed: set[str] | None = None
    ) -> Iterator[Event]:
        if not ro.table_exists(conn, "task_runs"):
            return
        cols = ro.filter_columns(
            conn,
            "task_runs",
            (
                "id",
                "task_id",
                "profile",
                "step_key",
                "status",
                "started_at",
                "ended_at",
                "outcome",
                "summary",
                "error",
            ),
        )
        if not cols:
            return
        if "ended_at" in cols and "started_at" in cols:
            activity = "COALESCE(ended_at, started_at)"
        elif "started_at" in cols:
            activity = "started_at"
        elif "ended_at" in cols:
            activity = "ended_at"
        else:
            activity = "id"
        order = "started_at ASC, id ASC" if "started_at" in cols else "id ASC"
        sql = (
            f"SELECT {', '.join(cols)} FROM task_runs "
            f"WHERE {activity} >= ? ORDER BY {order}"
        )
        for row in conn.execute(sql, (window.since,)):
            run_id = str(_row_get(row, "id"))
            profile = (_row_get(row, "profile") or "").strip()
            if allowed is not None and profile not in allowed:
                continue
            started = _epoch(_row_get(row, "started_at"))
            ended = _epoch(_row_get(row, "ended_at"))
            if started is not None:
                yield build_event(
                    source=SOURCE_KANBAN,
                    kind=KIND_RUN_STARTED,
                    ts=started,
                    profile=profile,
                    actor=profile,
                    subject=profile,
                    payload={
                        "run_id": run_id,
                        "task_id": str(_row_get(row, "task_id") or ""),
                        "profile": profile,
                        "step_key": _row_get(row, "step_key") or "",
                    },
                    store=STORE_KANBAN,
                    table="task_runs",
                    pk=run_id,
                    content_column=None,
                )
                self._count(SOURCE_KANBAN, emitted=1)
            if ended is not None and ended >= window.since:
                yield build_event(
                    source=SOURCE_KANBAN,
                    kind=KIND_RUN_FINISHED,
                    ts=ended,
                    profile=profile,
                    actor=profile,
                    subject=str(_row_get(row, "outcome") or _row_get(row, "status") or ""),
                    payload={
                        "run_id": run_id,
                        "task_id": str(_row_get(row, "task_id") or ""),
                        "profile": profile,
                        "status": _row_get(row, "status") or "",
                        "outcome": _row_get(row, "outcome") or "",
                        "has_summary": bool(_row_get(row, "summary")),
                        "has_error": bool(_row_get(row, "error")),
                    },
                    store=STORE_KANBAN,
                    table="task_runs",
                    pk=run_id,
                    content_column="summary",
                    discriminator="finished",
                )
                self._count(SOURCE_KANBAN, emitted=1)

    def _kanban_comments(
        self, conn: sqlite3.Connection, window: Window, allowed: set[str] | None = None
    ) -> Iterator[Event]:
        """Task comments: the richest "who said what" signal the fleet produces.

        Added in M1 on the owner's decision, and behind the redaction gate: the
        body is only reachable through a ContentRef.
        """
        if not ro.table_exists(conn, "task_comments"):
            return
        cols = ro.filter_columns(
            conn, "task_comments", ("id", "task_id", "author", "body", "created_at")
        )
        if not cols:
            return
        select = ", ".join(f"c.{column}" for column in cols)
        join = "LEFT JOIN tasks t ON t.id = c.task_id" if ro.table_exists(conn, "tasks") else ""
        assignee_select = ", t.assignee AS assignee" if join else ""
        sql = (
            f"SELECT {select}{assignee_select} FROM task_comments c {join} "
            "WHERE c.created_at >= ? ORDER BY c.created_at ASC, c.id ASC"
        )
        params: list[Any] = [window.since]
        if window.until is not None:
            sql = sql.replace("ORDER BY", "AND c.created_at < ? ORDER BY")
            params.append(window.until)
        for row in conn.execute(sql, params):
            assignee = (_row_get(row, "assignee") or "").strip()
            if allowed is not None and assignee not in allowed:
                continue
            ts = _epoch(_row_get(row, "created_at"))
            if ts is None:
                continue
            body = _row_get(row, "body") or ""
            author = str(_row_get(row, "author") or "").strip()
            yield build_event(
                source=SOURCE_KANBAN,
                kind=KIND_TASK_COMMENT,
                ts=ts,
                profile=assignee,
                actor=author,
                subject=author,
                payload={
                    "task_id": str(_row_get(row, "task_id") or ""),
                    "author": author,
                    "comment_chars": len(body),
                    "comment_digest": text_digest(body) if body else "",
                    "assignee": assignee,
                },
                store=STORE_KANBAN,
                table="task_comments",
                pk=str(_row_get(row, "id")),
                content_column="body",
            )
            self._count(SOURCE_KANBAN, emitted=1)

    # -- skills ------------------------------------------------------------
    def _skill_usage_files(self) -> Iterator[tuple[str, Path]]:
        fleet = self.paths.skills_usage_json
        if self._include_main and fleet.is_file():
            yield "default", fleet
        for store in self._selected_profiles():
            path = self.paths.profile_skills_usage_json(store)
            if path.is_file():
                yield store.name, path

    def _iter_skills(self, window: Window) -> Iterator[Event]:
        for profile, path in self._skill_usage_files():
            try:
                raw = ro.read_text(path)
                usage = json.loads(raw)
            except (json.JSONDecodeError, OSError):
                continue
            if not isinstance(usage, Mapping):
                continue
            store = f"{STORE_SKILLS}:{profile}"
            for name in sorted(usage, key=str):
                entry = usage[name]
                if not isinstance(entry, Mapping):
                    continue
                skill = str(name).lstrip("./")
                use_count = int(entry.get("use_count") or 0)
                view_count = int(entry.get("view_count") or 0)
                patch_count = int(entry.get("patch_count") or 0)
                state = str(entry.get("state") or "")
                base_payload = {
                    "skill": skill,
                    "use_count": use_count,
                    "view_count": view_count,
                    "patch_count": patch_count,
                    "state": state,
                    "pinned": bool(entry.get("pinned") or False),
                }
                milestones = (
                    (KIND_SKILL_CREATED, entry.get("created_at"), {}),
                    (KIND_SKILL_USED, entry.get("last_used_at"), {"use_count": use_count}),
                    (KIND_SKILL_PATCHED, entry.get("last_patched_at"), {"patch_count": patch_count}),
                    (KIND_SKILL_ARCHIVED, entry.get("archived_at"), {"state": state}),
                )
                for kind, stamp, extra in milestones:
                    ts = _epoch(stamp)
                    if ts is None or not window.contains(ts):
                        continue
                    if kind == KIND_SKILL_USED and use_count <= 0:
                        continue
                    if kind == KIND_SKILL_PATCHED and patch_count <= 0:
                        continue
                    yield build_event(
                        source=SOURCE_SKILL,
                        kind=kind,
                        ts=ts,
                        profile=profile,
                        actor=profile,
                        subject=skill,
                        payload={**base_payload, **extra},
                        store=store,
                        table=".usage.json",
                        pk=skill,
                        content_column=None,
                        discriminator=kind,
                    )
                    self._count(SOURCE_SKILL, emitted=1)

    # -- cron --------------------------------------------------------------
    def _cron_job_names(self) -> dict[str, str]:
        path = self.paths.cron_jobs_json
        if not path.is_file():
            return {}
        try:
            raw = json.loads(ro.read_text(path))
        except (json.JSONDecodeError, OSError):
            return {}
        jobs = raw.get("jobs") if isinstance(raw, Mapping) else raw
        names: dict[str, str] = {}
        if isinstance(jobs, Mapping):
            iterable: Iterable[Any] = jobs.values()
        elif isinstance(jobs, list):
            iterable = jobs
        else:
            return names
        for job in iterable:
            if not isinstance(job, Mapping):
                continue
            job_id = str(job.get("id") or "")
            if job_id:
                names[job_id] = str(job.get("name") or "")
        return names

    def _iter_cron(self, window: Window) -> Iterator[Event]:
        path = self.paths.cron_executions_db
        if not path.is_file():
            return
        if self._profile_filter is not None:
            # Cron runs carry no profile attribution, so they cannot honour a
            # profile filter; they are fleet-level records.
            return
        names = self._cron_job_names()
        conn = self._stores.open(path)
        try:
            if not ro.table_exists(conn, "executions"):
                return
            cols = ro.filter_columns(
                conn,
                "executions",
                ("id", "job_id", "source", "status", "claimed_at", "started_at", "finished_at", "error"),
            )
            if not cols:
                return
            # claimed_at is ISO-8601 text with a local offset, so string ordering
            # across offsets is not reliable. Take a deliberately loose lower
            # bound in SQL, then filter precisely on parsed epochs below.
            loose = datetime.fromtimestamp(window.since - 86400, tz=timezone.utc).isoformat()
            sql = (
                f"SELECT {', '.join(cols)} FROM executions WHERE claimed_at >= ? "
                "ORDER BY claimed_at ASC, id ASC"
            )
            for row in conn.execute(sql, (loose,)):
                job_id = str(_row_get(row, "job_id") or "")
                job_name = names.get(job_id, "")
                started = _epoch(_row_get(row, "started_at"))
                finished = _epoch(_row_get(row, "finished_at"))
                status = str(_row_get(row, "status") or "")
                payload = {
                    "job_id": job_id,
                    "job_name": job_name,
                    "status": status,
                    "source": _row_get(row, "source") or "",
                    "has_error": bool(_row_get(row, "error")),
                }
                if started is not None and window.contains(started):
                    yield build_event(
                        source=SOURCE_CRON,
                        kind=KIND_CRON_STARTED,
                        ts=started,
                        profile="",
                        actor=job_name or job_id,
                        subject=job_name or job_id,
                        payload=payload,
                        store=STORE_CRON,
                        table="executions",
                        pk=str(_row_get(row, "id")),
                        content_column=None,
                    )
                    self._count(SOURCE_CRON, emitted=1)
                if finished is not None and window.contains(finished):
                    yield build_event(
                        source=SOURCE_CRON,
                        kind=KIND_CRON_FINISHED,
                        ts=finished,
                        profile="",
                        actor=job_name or job_id,
                        subject=status,
                        payload=payload,
                        store=STORE_CRON,
                        table="executions",
                        pk=str(_row_get(row, "id")),
                        content_column="error",
                        discriminator="finished",
                    )
                    self._count(SOURCE_CRON, emitted=1)
        finally:
            ro.safe_close(conn)

    # -- memory ------------------------------------------------------------
    def _memory_files(self) -> Iterator[tuple[str, Path]]:
        if self._include_main:
            for path in self.paths.memory_files:
                if path.is_file():
                    yield "default", path
        for store in self._selected_profiles():
            for path in self.paths.profile_memory_files(store):
                if path.is_file():
                    yield store.name, path

    def current_memory_facts(self) -> dict[str, list[str]]:
        """Snapshot of facts per file, keyed ``"<profile>/<filename>"``."""
        snapshot: dict[str, list[str]] = {}
        for profile, path in self._memory_files():
            try:
                text = ro.read_text(path)
            except OSError:
                continue
            snapshot[f"{profile}/{path.name}"] = _split_facts(text)
        return snapshot

    def _iter_memory(self, window: Window) -> Iterator[Event]:
        for profile, path in self._memory_files():
            try:
                text = ro.read_text(path)
                mtime = path.stat().st_mtime
            except OSError:
                continue
            key = f"{profile}/{path.name}"
            facts = _split_facts(text)
            prior = self._memory_snapshot.get(key)
            store = f"memory:{key}"
            if prior is not None:
                prior_set = set(prior)
                current_set = set(facts)
                # Always emit the current facts, so a re-run with no changes gives
                # a byte-identical stream (and therefore identical canon). The
                # added/removed events are the diff on top.
                for index, fact in enumerate(facts):
                    if not window.contains(mtime):
                        continue
                    yield build_event(
                        source=SOURCE_MEMORY,
                        kind=KIND_MEMORY_FACT,
                        ts=mtime,
                        profile=profile,
                        actor=profile,
                        subject=path.name,
                        payload={
                            "file": path.name,
                            "fact_digest": text_digest(fact),
                            "fact_chars": len(fact),
                            "index": index,
                            "change": "present",
                        },
                        store=store,
                        table="lines",
                        pk=str(index),
                        content_column="line",
                    )
                    self._count(SOURCE_MEMORY, emitted=1)
                for index, fact in enumerate(facts):
                    if fact in prior_set:
                        continue
                    yield build_event(
                        source=SOURCE_MEMORY,
                        kind=KIND_MEMORY_ADDED,
                        ts=mtime,
                        profile=profile,
                        actor=profile,
                        subject=path.name,
                        payload={
                            "file": path.name,
                            "fact_digest": text_digest(fact),
                            "fact_chars": len(fact),
                            "change": "added",
                        },
                        store=store,
                        table="lines",
                        pk=str(index),
                        content_column="line",
                        discriminator="added",
                    )
                    self._count(SOURCE_MEMORY, emitted=1)
                for index, fact in enumerate(prior):
                    if fact in current_set:
                        continue
                    yield build_event(
                        source=SOURCE_MEMORY,
                        kind=KIND_MEMORY_REMOVED,
                        ts=mtime,
                        profile=profile,
                        actor=profile,
                        subject=path.name,
                        payload={
                            "file": path.name,
                            "fact_digest": text_digest(fact),
                            "fact_chars": len(fact),
                            "change": "removed",
                        },
                        store=store,
                        table="lines",
                        pk=str(index),
                        content_column="line",
                        discriminator="removed",
                    )
                    self._count(SOURCE_MEMORY, emitted=1)
                continue
            if not window.contains(mtime):
                continue
            for index, fact in enumerate(facts):
                yield build_event(
                    source=SOURCE_MEMORY,
                    kind=KIND_MEMORY_FACT,
                    ts=mtime,
                    profile=profile,
                    actor=profile,
                    subject=path.name,
                    payload={
                        "file": path.name,
                        "fact_digest": text_digest(fact),
                        "fact_chars": len(fact),
                        "index": index,
                        "change": "present",
                    },
                    store=store,
                    table="lines",
                    pk=str(index),
                    content_column="line",
                )
                self._count(SOURCE_MEMORY, emitted=1)

    # -- content materialisation -------------------------------------------
    def fetch_content(self, ref_content) -> str:  # type: ignore[override]
        """Return the raw text behind a ``ContentRef``, read-only.

        This is the seam the ingest stage uses to pull text so it can be
        redacted. Nothing here redacts: the caller must (M1 owns that gate).
        """
        from canon.events import ContentRef

        if not isinstance(ref_content, ContentRef):
            raise ContentUnavailable("fetch_content expects a ContentRef")
        ref = ref_content
        store, table, pk, column = ref.store, ref.table, ref.pk, ref.column
        if store.startswith("memory:"):
            return self._fetch_memory_line(store[len("memory:") :], column, pk)
        if store.startswith(f"{STORE_SKILLS}:"):
            return self._fetch_skill_json(store, column, pk)
        path = self._path_for_store(store)
        if path is None:
            raise ContentUnavailable(f"unknown store: {store!r}")
        if table not in CONTENT_TABLES:
            raise ContentUnavailable(f"table not readable through content refs: {table!r}")
        pk_column = PK_COLUMNS[table]
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", column):
            raise ContentUnavailable(f"unsafe column name: {column!r}")
        allowed = {
            "messages": {"content", "tool_calls", "reasoning", "reasoning_content"},
            "sessions": {"title", "system_prompt", "last_activity_description"},
            "tasks": {"title", "body", "result"},
            "task_events": {"payload"},
            "task_runs": {"summary", "metadata", "error"},
            "task_comments": {"body"},
            "executions": {"error"},
        }
        if column not in allowed.get(table, set()):
            raise ContentUnavailable(f"column {column!r} is not exposable for {table!r}")
        conn = self._stores.open(path)
        try:
            row = conn.execute(
                f"SELECT {column} AS value FROM {table} WHERE {pk_column} = ?", (pk,)
            ).fetchone()
        except sqlite3.DatabaseError as exc:
            raise ContentUnavailable(str(exc)) from exc
        finally:
            ro.safe_close(conn)
        if row is None:
            raise ContentUnavailable(f"no row {table}.{pk_column}={pk}")
        value = row["value"]
        return "" if value is None else str(value)

    def _path_for_store(self, store: str) -> Path | None:
        if store == STORE_MAIN:
            return self.paths.main_state_db
        if store == STORE_KANBAN:
            return self.paths.kanban_db
        if store == STORE_CRON:
            return self.paths.cron_executions_db
        if store.startswith("profile:"):
            name = store[len("profile:") :]
            profile = self.paths.profile(name)
            return profile.state_db if profile else None
        return None

    def _fetch_memory_line(self, key: str, column: str, pk: str) -> str:
        if column not in {"line", "content"}:
            raise ContentUnavailable(f"unsupported memory column: {column!r}")
        profile, _, filename = key.partition("/")
        candidates: list[Path] = []
        if profile == "default" and self._include_main:
            candidates.extend(self.paths.memory_files)
        store = self.paths.profile(profile)
        if store is not None:
            candidates.extend(self.paths.profile_memory_files(store))
        for path in candidates:
            if path.name != filename:
                continue
            try:
                text = ro.read_text(path)
            except OSError:
                continue
            facts = _split_facts(text)
            try:
                index = int(pk)
            except ValueError:
                raise ContentUnavailable(f"bad memory line ref: {pk!r}")
            if 0 <= index < len(facts):
                return facts[index]
            raise ContentUnavailable(f"memory line {index} out of range for {filename}")
        raise ContentUnavailable(f"memory file not found: {key}")

    def _fetch_skill_json(self, store: str, column: str, pk: str) -> str:
        if column not in {"content", "json", "line"}:
            raise ContentUnavailable(f"unsupported skills column: {column!r}")
        profile = store.split(":", 1)[1]
        if profile == "default" and self._include_main:
            path = self.paths.skills_usage_json
        else:
            store_ref = self.paths.profile(profile)
            if store_ref is None:
                raise ContentUnavailable(f"unknown profile: {profile}")
            path = self.paths.profile_skills_usage_json(store_ref)
        try:
            usage = json.loads(ro.read_text(path))
        except (OSError, json.JSONDecodeError) as exc:
            raise ContentUnavailable(str(exc)) from exc
        for key in (pk, f"./{pk}"):
            if key in usage:
                return json.dumps(usage[key], sort_keys=True)
        raise ContentUnavailable(f"skill not found in usage ledger: {pk}")


def _arg_keys(args_text: str) -> set[str]:
    try:
        parsed = json.loads(args_text)
    except (TypeError, ValueError):
        return set()
    if isinstance(parsed, Mapping):
        return {str(key) for key in parsed}
    return set()


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def _window_from_args(args: argparse.Namespace) -> Window:
    now = datetime.now(tz=timezone.utc)
    until = _epoch(args.until) if args.until else None
    end = until if until is not None else now.timestamp()
    since = end - args.days * 86400
    return Window(since=since, until=until)


def _load_memory_snapshot(path: str | None) -> dict[str, Any] | None:
    if not path:
        return None
    target = Path(path).expanduser()
    if not target.is_file():
        return None
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _is_inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _display_path(path: str) -> str:
    """Show a path with the user's home collapsed to ``~`` (no absolute home leak)."""
    user_home = str(Path.home())
    if path == user_home:
        return "~"
    if path.startswith(user_home + os.sep):
        return "~" + path[len(user_home) :]
    return path


def _summary_lines(
    source: "HermesHistorySource",
    events: Iterable[Event],
    window: Window,
    *,
    top_sessions: int = 50,
    show_titles: bool = False,
) -> list[str]:
    per_source: dict[str, int] = {}
    per_profile: dict[str, int] = {}
    per_profile_source: dict[tuple[str, str], int] = {}
    sessions: list[Event] = []
    total = 0
    for event in events:
        total += 1
        per_source[event.source] = per_source.get(event.source, 0) + 1
        profile = event.profile or "(fleet)"
        per_profile[profile] = per_profile.get(profile, 0) + 1
        key = (profile, event.source)
        per_profile_source[key] = per_profile_source.get(key, 0) + 1
        if event.kind == KIND_SESSION_STARTED:
            sessions.append(event)

    info = source.info()
    counters = source.counters()
    lines: list[str] = []
    lines.append("Hermes Scrollback Reel \u2014 history summary")
    lines.append(f"harness:        {info.harness}")
    lines.append(f"hermes home:    {_display_path(info.root)}")
    lines.append(
        f"window:         {_iso(window.since)} .. "
        f"{_iso(window.until) if window.until else 'now'} "
        f"({( (window.until or datetime.now(tz=timezone.utc).timestamp()) - window.since)/86400:.2f} days)"
    )
    available = sum(1 for profile in info.profiles if profile.store)
    unavailable = len(info.profiles) - available
    tail = f" ({unavailable} without a state.db)" if unavailable else ""
    lines.append(f"profiles:       {available} with a state.db of {len(info.profiles)} dirs{tail}")
    lines.append(f"stores found:   {', '.join(info.stores) if info.stores else '(none)'}")
    if info.missing:
        lines.append(f"stores missing: {', '.join(info.missing)}")
    decisions = source.store_decisions()
    if decisions:
        counts: dict[str, int] = {}
        for decision in decisions:
            counts[decision.action] = counts.get(decision.action, 0) + 1
        plan = ", ".join(
            f"{count} {action.replace('_', ' ')}" for action, count in sorted(counts.items())
        )
        lines.append(f"read plan:      {len(decisions)} stores: {plan}")
        for decision in decisions:
            if decision.action == "snapshot":
                lines.append(f"  copied:       {_display_path(decision.path)} ({decision.reason})")
    lines.append("")
    lines.append("=== events per source ===")
    for name in SOURCE_ORDER:
        count = per_source.get(name, 0)
        extra = ""
        if name in counters:
            c = counters[name]
            bits = []
            if c.skipped_noise:
                bits.append(f"{c.skipped_noise} noise rows filtered")
            if c.skipped_inactive:
                bits.append(f"{c.skipped_inactive} inactive rows skipped")
            if bits:
                extra = "  (" + "; ".join(bits) + ")"
        lines.append(f"{name:<14}{count:>9,}{extra}")
    lines.append(f"{'TOTAL':<14}{total:>9,}")
    lines.append("")
    lines.append("=== events per profile (top 20) ===")
    ordered = sorted(per_profile.items(), key=lambda kv: (-kv[1], kv[0]))
    for profile, count in ordered[:20]:
        lines.append(f"{profile:<28}{count:>9,}")
    if len(ordered) > 20:
        remainder = sum(count for _, count in ordered[20:])
        lines.append(f"{'(other %d profiles)' % (len(ordered) - 20):<28}{remainder:>9,}")
    lines.append("")
    lines.append("=== profile x source (top 15 profiles) ===")
    header = "profile".ljust(24) + "".join(name[:9].rjust(10) for name in SOURCE_ORDER)
    lines.append(header)
    for profile, _ in ordered[:15]:
        row = profile.ljust(24)
        for name in SOURCE_ORDER:
            row += f"{per_profile_source.get((profile, name), 0):>10,}"
        lines.append(row)
    lines.append("")
    lines.append(
        f"=== last {top_sessions} sessions "
        f"(title, profile, time, message count) ==="
        if show_titles
        else f"=== last {top_sessions} sessions (profile, time, message count; "
        f"titles stay behind the gate - add --show-titles) ==="
    )
    sessions.sort(
        key=lambda ev: (
            ev.payload.get("last_activity_at") or ev.payload.get("started_at") or ev.ts
        ),
        reverse=True,
    )
    for event in sessions[:top_sessions]:
        activity = event.payload.get("last_activity_at") or event.payload.get("started_at")
        title = ""
        if show_titles and event.content_ref is not None:
            try:
                title = _preview(source.fetch_content(event.content_ref))
            except Exception:  # noqa: BLE001 - a diagnostic must never fail the run
                title = "(title unavailable)"
        lines.append(
            f"{_iso(activity):<25} {event.profile or '(none)':<18} "
            f"{event.payload.get('source', ''):<9} "
            f"{event.payload.get('message_count', 0):>6} msgs  {title}"
        )
    if not sessions:
        lines.append("(no sessions in window)")
    return lines


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m adapters.hermes.history",
        description="Read-only Hermes history adapter for the Scrollback Reel.",
    )
    parser.add_argument("--days", type=float, default=7.0, help="window size in days (default 7)")
    parser.add_argument("--since", default=None, help="explicit window start (epoch or ISO-8601)")
    parser.add_argument("--until", default=None, help="explicit window end (epoch or ISO-8601)")
    parser.add_argument("--summary", action="store_true", help="print the human summary")
    parser.add_argument(
        "--show-titles",
        action="store_true",
        help=(
            "include session titles in the summary. Titles are not carried in the "
            "event stream (owner decision: only the redaction gate releases them); "
            "this diagnostic fetches them directly for the owner's own screen."
        ),
    )
    parser.add_argument("--out", default=None, help="write the event stream as JSONL to this path")
    parser.add_argument(
        "--sources",
        default=None,
        help="comma separated subset: " + ",".join(SOURCE_ORDER),
    )
    parser.add_argument(
        "--profile",
        action="append",
        default=None,
        help=(
            "restrict to this profile (repeatable). Scopes every source that carries a "
            "profile attribution (sessions, messages, tool calls, skills, memory, "
            "kanban-by-assignee). Fleet-level cron runs are omitted while a filter is set. "
            "Default: every profile plus the fleet-wide store."
        ),
    )
    parser.add_argument(
        "--memory-snapshot",
        default=None,
        help="prior memory facts snapshot (JSON) to diff against",
    )
    parser.add_argument(
        "--write-memory-snapshot",
        default=None,
        help="write the current memory facts snapshot to this path",
    )
    parser.add_argument(
        "--redaction-preflight",
        action="store_true",
        help="scan generated output for obvious leaks before it is written to evidence",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    window = _window_from_args(args)
    if args.since:
        since = _epoch(args.since)
        if since is None:
            parser.error(f"unparseable --since: {args.since!r}")
        window = Window(since=since, until=window.until)
    sources = [part.strip() for part in args.sources.split(",")] if args.sources else None

    snapshot = _load_memory_snapshot(args.memory_snapshot)
    # ``--profile X`` means only X: the fleet-wide (default) store is dropped
    # unless the caller asks for it by name.
    include_main = not args.profile or "default" in args.profile
    source = HermesHistorySource(
        profiles=args.profile,
        include_main=include_main,
        memory_snapshot=snapshot,
    )
    info = source.info()
    has_profile_store = any(profile.store for profile in info.profiles)
    if not info.stores and not has_profile_store:
        print("no Hermes stores found", file=sys.stderr)
        return 2

    events = source.events(window, sources)

    if args.out:
        out_path = Path(args.out).expanduser()
        repo_root = Path(__file__).resolve().parents[2]
        if _is_inside(out_path, repo_root):
            print(
                "refusing to write real history inside the repo; use an evidence path "
                "(HANDOFF ground rule 5)",
                file=sys.stderr,
            )
            return 3
        out_path.parent.mkdir(parents=True, exist_ok=True)
        count = 0
        with open(out_path, "w", encoding="utf-8") as handle:
            for event in events:
                handle.write(json.dumps(event.to_dict(), sort_keys=True) + "\n")
                count += 1
        print(f"wrote {count:,} events to {out_path}")
    elif args.summary:
        lines = _summary_lines(
            source, events, window, show_titles=bool(args.show_titles)
        )
        if args.redaction_preflight:
            from adapters.hermes.leakscan import scan_lines

            hits = scan_lines(lines)
            lines.append("")
            lines.append(f"=== redaction preflight: {len(hits)} hit(s) ===")
            for hit in hits[:20]:
                lines.append(f"line {hit.line}: {hit.pattern} -> {hit.preview}")
            if not hits:
                lines.append("clean: no emails, tokens, keys, IPs or absolute paths in this output")
        print("\n".join(lines))
    else:
        count = 0
        for _ in events:
            count += 1
        print(f"{count:,} events in window")

    source.close()

    if args.write_memory_snapshot:
        target = Path(args.write_memory_snapshot).expanduser()
        target.parent.mkdir(parents=True, exist_ok=True)
        snapshot_out = source.current_memory_facts()
        target.write_text(json.dumps(snapshot_out, indent=1, sort_keys=True), encoding="utf-8")
        print(f"wrote memory facts snapshot ({len(snapshot_out)} files) to {target}")

    try:
        ro.assert_read_only_audit()
    except ro.ReadOnlyViolation as exc:
        print(f"READ-ONLY VIOLATION: {exc}", file=sys.stderr)
        return 4
    if os.environ.get("REEL_SHOW_AUDIT"):
        audit = ro.read_only_audit()
        print(
            f"[audit] opened {audit['files_opened']} files, "
            f"modes={audit['modes']}, all_read_only={audit['all_read_only']}",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
