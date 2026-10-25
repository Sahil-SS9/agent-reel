"""Other AI harnesses (owner decision V12, 25/10/26).

Each adapter here turns one harness's local session logs into the engine's event stream
(``canon.source.HistorySource``), the same way the Hermes adapter does:

- **Read-only.** Files are opened for reading; SQLite stores open with ``mode=ro``.
  Nothing is written next to a harness's data.
- **No text in the stream.** Events carry counts and digests. Text stays behind a
  ``ContentRef`` with a logical store name (never a path), and comes back through
  ``fetch_content`` for the redaction gate.
- **Prose only.** A user or assistant message's text blocks are story material. Tool calls,
  tool results, thinking and system prompts are skipped.

Supported:
- ``claude-code``: ``~/.claude/projects/*/*.jsonl``
- ``codex``: ``~/.codex/sessions/**/*.jsonl``
- ``opencode``: ``~/.local/share/opencode/opencode.db`` (session/message/part tables only)
- ``pi``: ``~/.pi/agent/sessions/**/*.jsonl``
- ``jsonl``: any harness that writes JSON lines, described by a small mapping file
  (Command Code and others), see ``GENERIC_MAPPING_EXAMPLE``.

``status`` is honest: ``tested`` means it was run against real local sessions on the owner's
machine; ``mapped`` means it was built from the harness's documented format and checked
against fixtures only.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, Mapping, Sequence

from canon.events import (
    KIND_MESSAGE_ASSISTANT,
    KIND_MESSAGE_USER,
    KIND_SESSION_STARTED,
    SOURCE_MESSAGE,
    SOURCE_SESSION,
    ContentRef,
    Event,
    build_event,
    text_digest,
)
from canon.source import ContentUnavailable, ProfileRef, SourceInfo, Window


@dataclass(frozen=True)
class HarnessSpec:
    key: str
    label: str
    default_root: str
    status: str  # tested | mapped
    notes: str = ""


HARNESSES: dict[str, HarnessSpec] = {
    "hermes": HarnessSpec("hermes", "Hermes Agent", "~/.hermes", "tested", "every profile's state.db, kanban, cron, skills, memory"),
    "claude-code": HarnessSpec("claude-code", "Claude Code", "~/.claude/projects", "tested"),
    "codex": HarnessSpec("codex", "OpenAI Codex CLI", "~/.codex/sessions", "tested"),
    "opencode": HarnessSpec("opencode", "OpenCode", "~/.local/share/opencode/opencode.db", "tested",
                            "reads only the session, message and part tables"),
    "pi": HarnessSpec("pi", "Pi coding agent", "~/.pi/agent/sessions", "mapped", "built from Pi's documented session format"),
    "jsonl": HarnessSpec("jsonl", "Any JSONL harness (mapping file)", "", "mapped",
                         "Command Code and others: describe the log format in a small JSON mapping"),
}

#: A mapping for ``jsonl``: where the files are and where each field lives (dotted paths).
GENERIC_MAPPING_EXAMPLE = {
    "glob": "~/.commandcode/sessions/**/*.jsonl",
    "role": "message.role",
    "text": "message.content",
    "timestamp": "timestamp",
    "session": "session_id",
    "user_roles": ["user"],
    "assistant_roles": ["assistant"],
}


def _epoch(value: Any) -> float | None:
    """Seconds since the epoch from seconds, milliseconds or an ISO-8601 string (UTC if naive)."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return number / 1000.0 if number > 1e11 else number
    text = str(value).strip()
    if re.fullmatch(r"\d+(\.\d+)?", text):
        return _epoch(float(text))
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.timestamp()


def _dig(data: Any, path: str) -> Any:
    for part in path.split("."):
        if isinstance(data, Mapping):
            data = data.get(part)
        elif isinstance(data, list) and part.isdigit() and int(part) < len(data):
            data = data[int(part)]
        else:
            return None
    return data


def prose_of(content: Any, text_types: Sequence[str] = ("text", "input_text", "output_text")) -> str:
    """The prose in a message's content: a string, or the text blocks of a block list."""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = [
            str(block.get("text", "")).strip()
            for block in content
            if isinstance(block, Mapping) and block.get("type") in text_types and block.get("text")
        ]
        return "\n\n".join(p for p in parts if p)
    return ""


@dataclass
class Message:
    session: str
    ts: float
    role: str  # user | assistant
    locator: str  # "<line>" for files, "<message id>" for SQLite
    text: str


class _Base:
    """Shared HistorySource plumbing; subclasses yield ``Message`` records."""

    harness = "base"

    def __init__(self, root: str | Path | None = None, *, agent_name: str | None = None) -> None:
        spec = HARNESSES.get(self.harness)
        self.root = Path(os.path.expanduser(str(root or (spec.default_root if spec else "")))) if (root or spec) else Path()
        self.agent = agent_name or self.harness
        self._stores: dict[str, Path] = {}

    # HistorySource -------------------------------------------------------
    def info(self) -> SourceInfo:
        present = self.root.exists()
        return SourceInfo(
            harness=self.harness,
            root=str(self.root),
            profiles=(ProfileRef(name=self.agent, store=self.harness, available=present),),
            stores=(self.harness,) if present else (),
            missing=() if present else (str(self.root),),
        )

    def current_memory_facts(self) -> dict[str, list[str]]:
        return {}

    def counters(self) -> dict[str, Any]:
        return {}

    def close(self) -> None:
        return None

    def events(self, window: Window, sources: Sequence[str] | None = None) -> Iterator[Event]:
        wanted = set(sources or (SOURCE_SESSION, SOURCE_MESSAGE))
        seen_sessions: set[str] = set()
        for message in self._messages(window):
            if not window.contains(message.ts):
                continue
            store = self._store_key(message.session)
            if SOURCE_SESSION in wanted and message.session not in seen_sessions:
                seen_sessions.add(message.session)
                yield build_event(
                    source=SOURCE_SESSION, kind=KIND_SESSION_STARTED, ts=message.ts, profile=self.agent,
                    actor=self.agent, subject=self.harness,
                    payload={"session_id": f"{self.harness}:{message.session}", "harness": self.harness},
                    store=store, table="sessions", pk=message.session, content_column=None,
                )
            if SOURCE_MESSAGE not in wanted or not message.text:
                continue
            kind = KIND_MESSAGE_USER if message.role == "user" else KIND_MESSAGE_ASSISTANT
            yield build_event(
                source=SOURCE_MESSAGE, kind=kind, ts=message.ts, profile=self.agent,
                actor="owner" if message.role == "user" else self.agent, subject=message.role,
                payload={"role": message.role, "session_id": f"{self.harness}:{message.session}",
                         "chars": len(message.text), "content_digest": text_digest(message.text),
                         "harness": self.harness, "tool_names": [], "tool_call_count": 0},
                store=store, table="messages", pk=message.locator, content_column="content",
            )

    def fetch_content(self, ref: ContentRef) -> str:
        if not isinstance(ref, ContentRef) or ref.store not in self._stores:
            raise ContentUnavailable(f"unknown store: {getattr(ref, 'store', ref)!r}")
        text = self._read(self._stores[ref.store], ref.pk)
        if text is None:
            raise ContentUnavailable(f"no text at {ref.store}/{ref.pk}")
        return text

    # helpers -------------------------------------------------------------
    def _store_key(self, session: str) -> str:
        key = f"{self.harness}:{text_digest(session)[:16]}"
        return key

    def _messages(self, window: Window) -> Iterator[Message]:  # pragma: no cover - abstract
        raise NotImplementedError

    def _read(self, path: Path, locator: str) -> str | None:  # pragma: no cover - abstract
        raise NotImplementedError


class _JsonlBase(_Base):
    pattern = "*.jsonl"

    def files(self) -> list[Path]:
        if self.root.is_file():
            return [self.root]
        return sorted(self.root.glob(self.pattern)) if self.root.is_dir() else []

    def parse(self, record: Mapping[str, Any]) -> tuple[str, str, float | None, str | None] | None:
        """(role, text, ts, session override) or None to skip."""
        raise NotImplementedError

    def _messages(self, window: Window) -> Iterator[Message]:
        for path in self.files():
            try:
                if path.stat().st_mtime < window.since:
                    continue  # nothing in this file can fall in the window
            except OSError:
                continue
            session = path.stem
            store = self._store_key(session)
            self._stores[store] = path
            with path.open("r", encoding="utf-8", errors="replace") as handle:
                for number, line in enumerate(handle, start=1):
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(record, Mapping):
                        continue
                    parsed = self.parse(record)
                    if parsed is None:
                        continue
                    role, text, ts, _override = parsed
                    if ts is None or not text:
                        continue
                    yield Message(session=session, ts=ts, role=role, locator=str(number), text=text)

    def _read(self, path: Path, locator: str) -> str | None:
        try:
            wanted = int(locator)
        except ValueError:
            return None
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for number, line in enumerate(handle, start=1):
                if number == wanted:
                    try:
                        parsed = self.parse(json.loads(line))
                    except json.JSONDecodeError:
                        return None
                    return parsed[1] if parsed else None
        return None


class ClaudeCodeSource(_JsonlBase):
    harness = "claude-code"
    pattern = "*/*.jsonl"

    def parse(self, record: Mapping[str, Any]):
        if record.get("type") not in {"user", "assistant"} or record.get("isSidechain") or record.get("isMeta"):
            return None
        message = record.get("message") or {}
        role = str(message.get("role") or record.get("type"))
        if role not in {"user", "assistant"}:
            return None
        text = prose_of(message.get("content"))
        if role == "user" and (text.startswith("<") or "tool_result" in json.dumps(message.get("content"))[:200]):
            return None  # command wrappers and tool results are not prose
        return role, text, _epoch(record.get("timestamp")), None


class CodexSource(_JsonlBase):
    harness = "codex"
    pattern = "**/*.jsonl"

    def parse(self, record: Mapping[str, Any]):
        if record.get("type") != "response_item":
            return None
        payload = record.get("payload") or {}
        if payload.get("type") != "message" or payload.get("role") not in {"user", "assistant"}:
            return None
        text = prose_of(payload.get("content"))
        if payload.get("role") == "user" and text.startswith(("<environment_context", "<user_instructions", "# AGENTS.md")):
            return None
        return str(payload["role"]), text, _epoch(record.get("timestamp")), None


class PiSource(_JsonlBase):
    harness = "pi"
    pattern = "**/*.jsonl"

    def parse(self, record: Mapping[str, Any]):
        if record.get("type") != "message":
            return None
        message = record.get("message") or {}
        role = str(message.get("role") or "")
        if role not in {"user", "assistant"}:
            return None
        return role, prose_of(message.get("content")), _epoch(record.get("timestamp") or message.get("timestamp")), None


class GenericJsonlSource(_JsonlBase):
    harness = "jsonl"

    def __init__(self, mapping: Mapping[str, Any], *, agent_name: str | None = None) -> None:
        self.mapping = dict(mapping)
        pattern = os.path.expanduser(str(self.mapping.get("glob") or ""))
        if not pattern:
            raise ValueError("a jsonl mapping needs a 'glob'")
        base, _sep, rest = pattern.partition("*")
        root = Path(base).parent if not base.endswith("/") else Path(base)
        super().__init__(root, agent_name=agent_name or str(self.mapping.get("name") or "agent"))
        self.pattern = str(Path(pattern).relative_to(root)) if rest else Path(pattern).name
        self.harness = str(self.mapping.get("name") or "jsonl")

    def parse(self, record: Mapping[str, Any]):
        role = str(_dig(record, self.mapping.get("role", "role")) or "")
        users = set(self.mapping.get("user_roles", ["user"]))
        assistants = set(self.mapping.get("assistant_roles", ["assistant"]))
        if role in users:
            role = "user"
        elif role in assistants:
            role = "assistant"
        else:
            return None
        text = prose_of(_dig(record, self.mapping.get("text", "content")))
        return role, text, _epoch(_dig(record, self.mapping.get("timestamp", "timestamp"))), None


class OpenCodeSource(_Base):
    """Reads only the session/message/part tables; account and credential tables are never touched."""

    harness = "opencode"

    def __init__(self, root: str | Path | None = None, *, agent_name: str | None = None) -> None:
        super().__init__(root, agent_name=agent_name)
        from adapters.hermes.stores import StoreReader  # the shared read-only, WAL-safe opener

        self._reader = StoreReader()

    def _connect(self) -> sqlite3.Connection:
        return self._reader.open(self.root)

    def _messages(self, window: Window) -> Iterator[Message]:
        if not self.root.is_file():
            return
        conn = self._connect()
        try:
            store_rows = conn.execute(
                "SELECT m.id, m.session_id, m.time_created, m.data FROM message m "
                "WHERE m.time_created >= ? ORDER BY m.time_created, m.id", (int(window.since * 1000),)
            ).fetchall()
            for message_id, session_id, created, data in store_rows:
                try:
                    role = str(json.loads(data).get("role") or "")
                except (json.JSONDecodeError, AttributeError):
                    continue
                if role not in {"user", "assistant"}:
                    continue
                text = self._text(conn, message_id)
                store = self._store_key(session_id)
                self._stores[store] = self.root
                yield Message(session=session_id, ts=_epoch(created) or 0.0, role=role, locator=message_id, text=text)
        finally:
            conn.close()

    @staticmethod
    def _text(conn: sqlite3.Connection, message_id: str) -> str:
        parts = []
        for (data,) in conn.execute("SELECT data FROM part WHERE message_id = ? ORDER BY time_created, id", (message_id,)):
            try:
                part = json.loads(data)
            except json.JSONDecodeError:
                continue
            if isinstance(part, Mapping) and part.get("type") == "text" and part.get("text") and not part.get("synthetic"):
                parts.append(str(part["text"]).strip())
        return "\n\n".join(p for p in parts if p)

    def _read(self, path: Path, locator: str) -> str | None:
        conn = self._connect()
        try:
            return self._text(conn, locator) or None
        finally:
            conn.close()


class CompositeSource:
    """Several harnesses read as one history (events merged by time)."""

    def __init__(self, sources: Iterable[Any]) -> None:
        self.sources = list(sources)

    def info(self) -> SourceInfo:
        infos = [s.info() for s in self.sources]
        return SourceInfo(
            harness="+".join(i.harness for i in infos), root=";".join(i.root for i in infos),
            profiles=tuple(p for i in infos for p in i.profiles), stores=tuple(s for i in infos for s in i.stores),
            missing=tuple(m for i in infos for m in i.missing),
        )

    def events(self, window: Window, sources: Sequence[str] | None = None) -> Iterator[Event]:
        merged = [event for source in self.sources for event in source.events(window, sources)]
        merged.sort(key=lambda e: (e.ts, e.id))
        return iter(merged)

    def fetch_content(self, ref: ContentRef) -> str:
        for source in self.sources:
            try:
                return source.fetch_content(ref)
            except ContentUnavailable:
                continue
        raise ContentUnavailable(f"no harness owns {ref.store!r}")

    def current_memory_facts(self) -> dict[str, list[str]]:
        facts: dict[str, list[str]] = {}
        for source in self.sources:
            getter: Callable[[], dict[str, list[str]]] | None = getattr(source, "current_memory_facts", None)
            if getter:
                facts.update(getter())
        return facts

    def counters(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for source in self.sources:
            out.update(getattr(source, "counters", dict)())
        return out

    def close(self) -> None:
        for source in self.sources:
            closer = getattr(source, "close", None)
            if closer:
                closer()


def make_source(harness: str, *, root: str = "", mapping: Mapping[str, Any] | None = None, agent_name: str = "") -> Any:
    """A HistorySource for one non-Hermes harness."""
    name = agent_name or None
    if harness == "claude-code":
        return ClaudeCodeSource(root or None, agent_name=name)
    if harness == "codex":
        return CodexSource(root or None, agent_name=name)
    if harness == "opencode":
        return OpenCodeSource(root or None, agent_name=name)
    if harness == "pi":
        return PiSource(root or None, agent_name=name)
    if harness == "jsonl":
        if not mapping:
            raise ValueError("--harness jsonl needs --mapping <file.json>")
        return GenericJsonlSource(mapping, agent_name=name)
    raise ValueError(f"unknown harness {harness!r}; choose one of {', '.join(HARNESSES)}")


__all__ = ("HARNESSES", "GENERIC_MAPPING_EXAMPLE", "CompositeSource", "make_source", "prose_of")
