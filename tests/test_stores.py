"""The store reader must never create files inside the Hermes home."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from adapters.hermes import ro
from adapters.hermes.stores import (
    ACTION_IN_PLACE,
    ACTION_SNAPSHOT,
    JOURNAL_ROLLBACK,
    JOURNAL_UNKNOWN,
    JOURNAL_WAL,
    StoreReader,
    journal_mode_of,
    sidecars,
)


def _rollback_db(path: Path) -> Path:
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE demo (id INTEGER PRIMARY KEY, value TEXT)")
    conn.execute("INSERT INTO demo (value) VALUES ('hello')")
    conn.commit()
    conn.close()
    return path


def _wal_db_no_sidecars(path: Path) -> Path:
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=wal")
    conn.execute("CREATE TABLE demo (id INTEGER PRIMARY KEY, value TEXT)")
    conn.execute("INSERT INTO demo (value) VALUES ('hello')")
    conn.commit()
    conn.close()  # checkpoint on close removes -wal/-shm, header stays WAL
    return path


def test_journal_mode_of_detects_rollback(tmp_path):
    assert journal_mode_of(_rollback_db(tmp_path / "a.db")) == JOURNAL_ROLLBACK


def test_journal_mode_of_detects_wal(tmp_path):
    assert journal_mode_of(_wal_db_no_sidecars(tmp_path / "b.db")) == JOURNAL_WAL


def test_journal_mode_of_rejects_non_sqlite(tmp_path):
    target = tmp_path / "not.db"
    target.write_text("this is not a database")
    assert journal_mode_of(target) == JOURNAL_UNKNOWN
    assert journal_mode_of(tmp_path / "missing.db") == JOURNAL_UNKNOWN


def test_rollback_db_is_read_in_place(tmp_path):
    path = _rollback_db(tmp_path / "a.db")
    reader = StoreReader(snapshot_root=tmp_path / "snap")
    try:
        conn = reader.open(path)
        assert conn.execute("SELECT value FROM demo").fetchone()["value"] == "hello"
    finally:
        reader.close()
    decisions = {d.path: d for d in reader.decisions()} if reader.decisions() else {}
    assert decisions[str(path)].action == ACTION_IN_PLACE


def test_wal_without_sidecars_is_snapshotted_and_creates_nothing(tmp_path):
    path = _wal_db_no_sidecars(tmp_path / "b.db")
    wal, shm = sidecars(path)
    assert not wal.exists() and not shm.exists()

    reader = StoreReader(snapshot_root=tmp_path / "snap")
    try:
        conn = reader.open(path)
        assert conn.execute("SELECT value FROM demo").fetchone()["value"] == "hello"
        # The whole point: nothing appeared next to the original database.
        assert not wal.exists(), "the reader created a -wal file in place"
        assert not shm.exists(), "the reader created a -shm file in place"
        # Second open reuses the same copy instead of copying twice.
        reader.open(path)
    finally:
        reader.close()

    decision = reader.decisions()[0]
    assert decision.action == ACTION_SNAPSHOT
    assert decision.journal_mode == JOURNAL_WAL


def test_wal_with_sidecars_is_read_in_place(tmp_path):
    path = tmp_path / "c.db"
    writer = sqlite3.connect(path)
    writer.execute("PRAGMA journal_mode=wal")
    writer.execute("PRAGMA wal_autocheckpoint=0")
    writer.execute("CREATE TABLE demo (id INTEGER PRIMARY KEY, value TEXT)")
    writer.execute("INSERT INTO demo (value) VALUES ('live row')")
    writer.commit()
    wal, shm = sidecars(path)
    assert wal.exists() and shm.exists()

    reader = StoreReader(snapshot_root=tmp_path / "snap")
    wal_size_before = wal.stat().st_size
    sidecars_existed = True
    try:
        conn = reader.open(path)
        # Uncheckpointed WAL content is visible, so recency is not lost.
        assert conn.execute("SELECT count(*) FROM demo").fetchone()[0] == 1
        sidecars_existed = wal.exists() and shm.exists()
        assert wal.stat().st_size == wal_size_before
    finally:
        reader.close()
        writer.close()
    decision = reader.decisions()[0]
    assert decision.action == ACTION_IN_PLACE
    assert sidecars_existed, "the reader removed the WAL sidecars"


def test_snapshot_tree_is_cleaned_up(tmp_path):
    path = _wal_db_no_sidecars(tmp_path / "b.db")
    snap_root = tmp_path / "snap"
    reader = StoreReader(snapshot_root=snap_root)
    reader.open(path)
    created = list(snap_root.iterdir())
    assert created, "expected a snapshot directory"
    reader.close()
    assert list(snap_root.iterdir()) == []


def test_large_wal_db_falls_back_to_in_place(tmp_path):
    path = _wal_db_no_sidecars(tmp_path / "big.db")
    reader = StoreReader(snapshot_root=tmp_path / "snap", copy_limit=1)
    try:
        conn = reader.open(path)
        assert conn.execute("SELECT count(*) FROM demo").fetchone()[0] == 1
    finally:
        reader.close()
    decision = reader.decisions()[0]
    assert decision.action == ACTION_IN_PLACE
    assert "copy limit" in decision.reason


def test_wal_db_in_a_read_only_tree_still_reads(tmp_path):
    """A WAL database whose sidecars cannot be created must fall back to a copy."""
    path = _wal_db_no_sidecars(tmp_path / "locked.db")
    (tmp_path / "locked.db-wal").unlink(missing_ok=True)
    locked = tmp_path / "locked"
    locked.mkdir()
    moved = locked / "locked.db"
    path.rename(moved)
    locked.chmod(0o555)
    try:
        reader = StoreReader(snapshot_root=tmp_path / "snap")
        try:
            conn = reader.open(moved)
            assert conn.execute("SELECT value FROM demo").fetchone()["value"] == "hello"
        finally:
            reader.close()
        assert reader.decisions()[0].action == ACTION_SNAPSHOT
        assert not (locked / "locked.db-wal").exists()
    finally:
        locked.chmod(0o755)


def test_store_reader_audit_stays_read_only(tmp_path):
    path = _wal_db_no_sidecars(tmp_path / "b.db")
    ro.reset_audit()
    reader = StoreReader(snapshot_root=tmp_path / "snap")
    reader.open(path)
    reader.close()
    ro.assert_read_only_audit()
    assert ro.read_only_audit()["all_read_only"] is True
