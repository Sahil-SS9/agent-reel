"""Tests for the read-only database guard."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from adapters.hermes import ro


def _db(path: Path) -> Path:
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE demo (id INTEGER PRIMARY KEY, value TEXT)")
    conn.execute("INSERT INTO demo (value) VALUES ('hello')")
    conn.commit()
    conn.close()
    return path


def test_connect_ro_reads(tmp_path):
    path = _db(tmp_path / "demo.db")
    conn = ro.connect_ro(path)
    try:
        assert conn.execute("SELECT value FROM demo").fetchone()["value"] == "hello"
    finally:
        ro.safe_close(conn)


@pytest.mark.parametrize(
    "statement",
    [
        "INSERT INTO demo (value) VALUES ('nope')",
        "CREATE TABLE extra (id INTEGER)",
        "UPDATE demo SET value = 'changed'",
        "DELETE FROM demo",
    ],
)
def test_connect_ro_refuses_writes(tmp_path, statement):
    path = _db(tmp_path / "demo.db")
    conn = ro.connect_ro(path)
    try:
        with pytest.raises(sqlite3.DatabaseError):
            conn.execute(statement)
    finally:
        ro.safe_close(conn)
    # The database on disk is untouched.
    check = sqlite3.connect(path)
    try:
        rows = check.execute("SELECT value FROM demo").fetchall()
    finally:
        check.close()
    assert rows == [("hello",)]


def test_audit_only_records_read_modes(tmp_path):
    ro.reset_audit()
    path = _db(tmp_path / "demo.db")
    conn = ro.connect_ro(path)
    ro.safe_close(conn)
    ro.assert_read_only_audit()
    audit = ro.read_only_audit()
    assert audit["all_read_only"] is True
    assert audit["modes"] == ["ro"]
    assert audit["files_opened"] == 1


def test_read_text_is_recorded_as_read(tmp_path):
    ro.reset_audit()
    target = tmp_path / "notes.md"
    target.write_text("hello", encoding="utf-8")
    assert ro.read_text(target) == "hello"
    audit = ro.read_only_audit()
    assert audit["modes"] == ["r"]
    ro.assert_read_only_audit()


def test_missing_database_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        ro.connect_ro(tmp_path / "absent.db")


def test_uri_unsafe_path_is_refused(tmp_path):
    with pytest.raises(ro.ReadOnlyViolation):
        ro.connect_ro(tmp_path / "weird?name.db")


def test_filter_columns_drops_unknown_columns(tmp_path):
    path = _db(tmp_path / "demo.db")
    conn = ro.connect_ro(path)
    try:
        assert ro.filter_columns(conn, "demo", ("id", "value", "not_a_column")) == ["id", "value"]
        assert ro.filter_columns(conn, "missing_table", ("id",)) == []
    finally:
        ro.safe_close(conn)
