"""Opening Hermes stores without writing a single byte into the Hermes home.

Why this module exists
----------------------
``sqlite3.connect("file:x?mode=ro")`` stops SQL data writes, but it is **not**
"no filesystem writes": for a database in WAL mode, SQLite opens ``-wal`` and
``-shm`` sidecars with ``O_RDWR|O_CREAT``, and creates them when they are
missing. ``strace`` catches that, and it is a real change to the user's directory.

So the adapter reads the SQLite header itself (100 bytes, ``O_RDONLY``) to learn
the journal mode *before* any connection is opened, and then:

* non-WAL database: open in place with ``mode=ro`` - creates nothing;
* WAL database whose sidecars already exist: open in place - SQLite only touches
  files that are already there;
* WAL database whose sidecars are missing: copy the file into a scratch tree
  outside the Hermes home and read the copy, so nothing is created in Hermes
  state. A database with no ``-wal`` has nothing uncheckpointed, so the copy is
  complete.

A copy is only taken below ``copy_limit`` bytes; above that the in-place path is
used and the decision is recorded so a report can say so honestly.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import tempfile
import weakref
from dataclasses import dataclass
from pathlib import Path

from adapters.hermes import ro

#: SQLite header offset 18/19: write/read format version. 2 means WAL.
_HEADER_SIZE = 100
_FORMAT_ROLLBACK = 1
_FORMAT_WAL = 2

JOURNAL_ROLLBACK = "rollback"
JOURNAL_WAL = "wal"
JOURNAL_UNKNOWN = "unknown"

ACTION_IN_PLACE = "in_place"
ACTION_SNAPSHOT = "snapshot"

DEFAULT_COPY_LIMIT = 256 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class StoreDecision:
    """Why a store was read the way it was."""

    path: str
    journal_mode: str
    action: str
    reason: str

    def as_line(self) -> str:
        return f"{self.path}: {self.action} ({self.journal_mode}, {self.reason})"


def journal_mode_of(path: Path | str) -> str:
    """Read the journal mode from the SQLite header without opening a connection."""
    try:
        with open(path, "rb") as handle:
            header = handle.read(_HEADER_SIZE)
    except OSError:
        return JOURNAL_UNKNOWN
    if len(header) < 20 or not header.startswith(b"SQLite format 3"):
        return JOURNAL_UNKNOWN
    write_version = header[18]
    read_version = header[19]
    if write_version == _FORMAT_WAL or read_version == _FORMAT_WAL:
        return JOURNAL_WAL
    if write_version == _FORMAT_ROLLBACK:
        return JOURNAL_ROLLBACK
    return JOURNAL_UNKNOWN


def sidecars(path: Path) -> tuple[Path, Path]:
    return Path(f"{path}-wal"), Path(f"{path}-shm")


def _default_snapshot_root() -> Path:
    base = os.environ.get("REEL_SNAPSHOT_DIR")
    root = Path(base).expanduser() if base else Path.home() / ".cache" / "scrollback-reel"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _remove_tree(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)


class StoreReader:
    """Opens Hermes databases read-only, never creating anything in the home."""

    def __init__(
        self,
        snapshot_root: Path | str | None = None,
        *,
        copy_limit: int = DEFAULT_COPY_LIMIT,
    ) -> None:
        self._snapshot_root = Path(snapshot_root) if snapshot_root is not None else None
        self._copy_limit = copy_limit
        self._session_dir: Path | None = None
        self._decisions: dict[str, StoreDecision] = {}
        self._copies: dict[str, Path] = {}
        self._open_connections: list[sqlite3.Connection] = []
        self._finalizer: weakref.finalize | None = None

    # -- decisions ---------------------------------------------------------
    def decisions(self) -> list[StoreDecision]:
        return list(self._decisions.values())

    def summary_line(self) -> str:
        counts: dict[str, int] = {}
        for decision in self._decisions.values():
            counts[decision.action] = counts.get(decision.action, 0) + 1
        if not counts:
            return "no stores opened"
        parts = [f"{count} {action.replace('_', ' ')}" for action, count in sorted(counts.items())]
        return ", ".join(parts)

    def snapshotted(self) -> list[StoreDecision]:
        return [d for d in self._decisions.values() if d.action == ACTION_SNAPSHOT]

    # -- opening -----------------------------------------------------------
    def open(self, path: Path | str) -> sqlite3.Connection:
        target = Path(path)
        key = str(target)
        existing = self._copies.get(key)
        if existing is not None:
            conn = ro.connect_ro(existing)
            self._open_connections.append(conn)
            return conn

        mode = journal_mode_of(target)
        wal_path, shm_path = sidecars(target)
        if mode != JOURNAL_WAL:
            self._record(target, mode, ACTION_IN_PLACE, "no WAL sidecars needed")
            conn = ro.connect_ro(target)
            self._open_connections.append(conn)
            return conn

        if wal_path.exists() and shm_path.exists():
            self._record(target, mode, ACTION_IN_PLACE, "WAL sidecars already present")
            conn = ro.connect_ro(target)
            self._open_connections.append(conn)
            return conn

        size = target.stat().st_size
        if size > self._copy_limit:
            self._record(
                target,
                mode,
                ACTION_IN_PLACE,
                f"WAL sidecars absent but {size} bytes exceeds the copy limit "
                f"({self._copy_limit}); opened in place",
            )
            conn = ro.connect_ro(target)
            self._open_connections.append(conn)
            return conn

        copy_path = self._snapshot(target)
        self._copies[key] = copy_path
        self._record(target, mode, ACTION_SNAPSHOT, "WAL sidecars absent, read a private copy")
        conn = ro.connect_ro(copy_path)
        self._open_connections.append(conn)
        return conn

    def _snapshot(self, target: Path) -> Path:
        if self._session_dir is None:
            root = self._snapshot_root or _default_snapshot_root()
            root = Path(root)
            root.mkdir(parents=True, exist_ok=True)
            self._session_dir = Path(tempfile.mkdtemp(prefix="reel-store-", dir=str(root)))
            # weakref.finalize fires on garbage collection *and* at interpreter
            # exit, so a run that raises (or never reaches close()) still cleans
            # up. Do not hold a bound method in atexit here: that strong reference
            # would keep self alive and stop the finaliser from ever running.
            self._finalizer = weakref.finalize(self, _remove_tree, self._session_dir)
        # Keep the relative shape so two stores with the same file name do not collide.
        safe = str(target).replace(os.sep, "__").lstrip("_")
        destination = self._session_dir / safe
        shutil.copy2(target, destination)
        return destination

    def _record(self, path: Path, mode: str, action: str, reason: str) -> None:
        self._decisions[str(path)] = StoreDecision(
            path=str(path), journal_mode=mode, action=action, reason=reason
        )

    # -- lifecycle ---------------------------------------------------------
    def _cleanup(self) -> None:
        """Remove the snapshot tree. Idempotent; safe to call more than once."""
        for conn in self._open_connections:
            ro.safe_close(conn)
        self._open_connections.clear()
        session_dir, self._session_dir = self._session_dir, None
        if session_dir is not None:
            shutil.rmtree(session_dir, ignore_errors=True)
        if self._finalizer is not None:
            self._finalizer.detach()
            self._finalizer = None

    def close(self) -> None:
        self._cleanup()

    def __enter__(self) -> "StoreReader":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()
