"""Read-only access to a live Hermes home.

Every database open in this adapter goes through :func:`connect_ro`. Three
independent guards, so a mistake in one does not become a write:

1. the SQLite URI carries ``mode=ro``, so SQLite itself refuses writes;
2. ``PRAGMA query_only=1`` makes the connection refuse writes even if opened
   writable by accident;
3. every opened path is recorded, and :func:`assert_read_only_audit` lets the
   CLI prove it opened nothing writable.

Non-SQLite files (JSON ledgers, markdown) are opened with an explicit ``"r"``
mode through :func:`read_text`.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable

_OPENED: list[tuple[str, str]] = []  # (mode, path)


class ReadOnlyViolation(RuntimeError):
    pass


def _record(mode: str, path: Path | str) -> None:
    _OPENED.append((mode, str(path)))


def opened_files() -> list[tuple[str, str]]:
    """Every file this process opened through this module, in order."""
    return list(_OPENED)


def reset_audit() -> None:
    _OPENED.clear()


def read_only_audit() -> dict[str, object]:
    modes = sorted({mode for mode, _ in _OPENED})
    return {
        "files_opened": len(_OPENED),
        "modes": modes,
        "all_read_only": all(mode in {"ro", "r"} for mode, _ in _OPENED),
        "paths": [path for _, path in _OPENED],
    }


def assert_read_only_audit() -> None:
    audit = read_only_audit()
    if not audit["all_read_only"]:
        bad = [(m, p) for m, p in _OPENED if m not in {"ro", "r"}]
        raise ReadOnlyViolation(f"non read-only opens detected: {bad[:5]}")


def connect_ro(path: Path | str, *, timeout: float = 5.0) -> sqlite3.Connection:
    """Open a SQLite database with all three read-only guards applied."""
    target = Path(path)
    text = str(target)
    if "?" in text or "#" in text:
        raise ReadOnlyViolation(f"refusing URI-unsafe database path: {text}")
    if not target.exists():
        raise FileNotFoundError(target)
    conn = sqlite3.connect(f"file:{text}?mode=ro", uri=True, timeout=timeout)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA query_only = 1")
    except sqlite3.DatabaseError:
        conn.close()
        raise
    _record("ro", target)
    return conn


def read_text(path: Path | str) -> str:
    """Read a text file, explicitly read-only."""
    target = Path(path)
    with open(target, "r", encoding="utf-8", errors="replace") as handle:  # noqa: SIM115
        _record("r", target)
        return handle.read()


def table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return row is not None


def columns(conn: sqlite3.Connection, table: str) -> set[str]:
    try:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    except sqlite3.DatabaseError:
        return set()
    return {str(row["name"]) for row in rows}


def filter_columns(
    conn: sqlite3.Connection, table: str, wanted: Iterable[str]
) -> list[str]:
    """Keep only columns this Hermes version actually has (forward/back compat)."""
    present = columns(conn, table)
    if not present:
        return []
    return [name for name in wanted if name in present]


def safe_close(conn: sqlite3.Connection | None) -> None:
    if conn is None:
        return
    try:
        conn.close()
    except sqlite3.Error:
        pass
