"""End-to-end tests for the Hermes history adapter against a synthetic home."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from adapters.hermes import history, ro
from adapters.hermes.history import HermesHistorySource, main
from canon.events import (
    KIND_CRON_FINISHED,
    KIND_MEMORY_ADDED,
    KIND_MEMORY_FACT,
    KIND_MEMORY_REMOVED,
    KIND_SESSION_STARTED,
    KIND_SKILL_CREATED,
    KIND_SKILL_USED,
    KIND_TOOL_CALL,
    SOURCE_ORDER,
)
from canon.source import ContentUnavailable, Window


def full_window() -> Window:
    now = datetime.now(tz=timezone.utc).timestamp()
    return Window(since=now - 40 * 86400)


def collect(home: Path, window: Window | None = None, sources=None, **kwargs):
    source = HermesHistorySource(root=home, **kwargs)
    events = list(source.events(window or full_window(), sources))
    return source, events


def test_info_reports_profiles_and_stores(synthetic_home):
    source = HermesHistorySource(root=synthetic_home)
    info = source.info()
    assert info.harness == "hermes"
    assert {p.name for p in info.profiles} == {"alpha", "beta", "gamma", "delta"}
    assert "state.db" in info.stores
    assert "kanban.db" in info.stores
    assert "cron/executions.db" in info.stores


def test_every_source_produces_events(synthetic_home):
    _, events = collect(synthetic_home)
    seen = {event.source for event in events}
    assert seen == set(SOURCE_ORDER), f"missing sources: {set(SOURCE_ORDER) - seen}"


def test_event_stream_is_deterministic(synthetic_home):
    _, first = collect(synthetic_home)
    _, second = collect(synthetic_home)
    assert [event.to_dict() for event in first] == [event.to_dict() for event in second]


def test_event_ids_are_unique(synthetic_home):
    from canon.events import assert_unique_ids

    _, events = collect(synthetic_home)
    assert assert_unique_ids(events) == len(events)


def test_message_events_carry_no_raw_text(synthetic_home):
    _, events = collect(synthetic_home, sources=["message"])
    assert events
    needle = "Synthetic request"
    for event in events:
        blob = json.dumps(event.payload)
        assert needle not in blob
        assert "content" not in event.payload
        assert event.content_ref is not None
        assert event.payload["content_digest"].startswith("sha256:")
    # The text is still reachable through the content ref.
    text = HermesHistorySource(root=synthetic_home).fetch_content(events[0].content_ref)
    assert needle in text


def test_profile_filter_limits_events(synthetic_home):
    _, events = collect(synthetic_home, profiles=["alpha"], include_main=False)
    profiles = {event.profile for event in events if event.source == "session"}
    assert profiles == {"alpha"}


def test_source_filter_limits_events(synthetic_home):
    _, events = collect(synthetic_home, sources=["kanban"])
    assert {event.source for event in events} == {"kanban"}


def test_unknown_source_is_rejected(synthetic_home):
    source = HermesHistorySource(root=synthetic_home)
    with pytest.raises(ValueError):
        list(source.events(full_window(), ["nonsense"]))


def test_window_excludes_old_events(fresh_home):
    now = datetime.now(tz=timezone.utc).timestamp()
    _, wide = collect(fresh_home, Window(since=now - 40 * 86400))
    _, narrow = collect(fresh_home, Window(since=now - 1 * 86400))
    assert narrow, "expected some activity in the last day"
    assert len(narrow) < len(wide)
    for event in narrow:
        session = event.payload.get("span_in_window")
        if event.kind == KIND_SESSION_STARTED:
            # Long sessions may start before the window but must still be live in it.
            if not session:
                assert event.ts >= now - 1 * 86400 - 5
        else:
            assert event.ts >= now - 1 * 86400 - 5


def test_tool_calls_come_from_message_json(synthetic_home):
    _, events = collect(synthetic_home, sources=["tool_call"])
    assert events
    event = events[0]
    assert event.kind == KIND_TOOL_CALL
    assert event.payload["tool"]
    assert event.payload["args_digest"].startswith("sha256:")
    assert "args" not in event.payload
    raw = HermesHistorySource(root=synthetic_home).fetch_content(event.content_ref)
    assert "function" in raw


def test_kanban_heartbeats_are_filtered_and_counted(synthetic_home):
    source, events = collect(synthetic_home, sources=["kanban"])
    kinds = {event.payload.get("kind") for event in events if event.kind == "kanban.task.status"}
    assert "heartbeat" not in kinds
    assert source.counters()["kanban"].skipped_noise > 0


def test_cron_events_use_job_names(synthetic_home):
    _, events = collect(synthetic_home, sources=["cron"])
    finished = [e for e in events if e.kind == KIND_CRON_FINISHED]
    assert finished
    names = {e.payload["job_name"] for e in finished}
    assert names <= {"synthetic-hourly-digest", "synthetic-daily-review", "synthetic-weekly-scan"}
    assert names, "job names from jobs.json should be attached"


def test_skill_events_cover_lifecycle(synthetic_home):
    _, events = collect(synthetic_home, sources=["skill"])
    kinds = {event.kind for event in events}
    assert KIND_SKILL_CREATED in kinds
    assert KIND_SKILL_USED in kinds


def test_fetch_content_rejects_unsafe_refs(synthetic_home):
    source = HermesHistorySource(root=synthetic_home)
    from canon.events import ContentRef

    with pytest.raises(ContentUnavailable):
        source.fetch_content(ContentRef(store="nowhere", table="messages", pk="1", column="content"))
    with pytest.raises(ContentUnavailable):
        source.fetch_content(ContentRef(store="main", table="secrets", pk="1", column="content"))
    with pytest.raises(ContentUnavailable):
        source.fetch_content(
            ContentRef(store="main", table="messages", pk="1", column="content; DROP TABLE messages")
        )
    with pytest.raises(ContentUnavailable):
        source.fetch_content(ContentRef(store="main", table="messages", pk="999999", column="content"))


def test_fetch_content_reads_kanban_title(synthetic_home):
    source = HermesHistorySource(root=synthetic_home)
    _, events = collect(synthetic_home, sources=["kanban"])
    created = [e for e in events if e.kind == "kanban.task.created"]
    assert created
    title = source.fetch_content(created[0].content_ref)
    assert title.startswith("Synthetic task")


def test_memory_snapshot_diff_reports_added_and_removed(fresh_home):
    source = HermesHistorySource(root=fresh_home)
    from canon.events import text_digest

    # The snapshot holds per-fact hashes, not text (audit M1-F4).
    prior = {
        key: [text_digest(fact) for fact in facts]
        for key, facts in source.current_memory_facts().items()
    }
    assert prior

    key = "default/MEMORY.md"
    old_facts = source.current_memory_facts()[key]
    updated = [old_facts[0], "Synthetic fact NEW: added after the snapshot."] + old_facts[2:]
    (fresh_home / "memories" / "MEMORY.md").write_text("\n\u00a7\n".join(updated) + "\n", encoding="utf-8")

    diff_source = HermesHistorySource(root=fresh_home, memory_snapshot=prior)
    events = [
        event
        for event in diff_source.events(full_window(), ["memory"])
        if event.profile == "default" and event.payload.get("file") == "MEMORY.md"
    ]
    kinds = {event.kind for event in events}
    # The current facts are always emitted (stable across re-runs); the diff rides
    # on top of them.
    assert KIND_MEMORY_FACT in kinds
    assert {KIND_MEMORY_ADDED, KIND_MEMORY_REMOVED} <= kinds
    assert sum(1 for e in events if e.kind == KIND_MEMORY_ADDED) == 1
    assert sum(1 for e in events if e.kind == KIND_MEMORY_REMOVED) == 1


def test_fetch_content_reads_memory_fact(fresh_home):
    source = HermesHistorySource(root=fresh_home)
    _, events = collect(fresh_home, sources=["memory"])
    fact_events = [e for e in events if e.content_ref and e.content_ref.store.startswith("memory:")]
    assert fact_events
    text = source.fetch_content(fact_events[0].content_ref)
    assert "Synthetic" in text


def test_summary_is_readable_and_prints_no_message_text(hermes_env, capsys):
    code = main(["--days", "28", "--summary", "--redaction-preflight"])
    captured = capsys.readouterr()
    assert code == 0
    out = captured.out
    assert "events per source" in out
    assert "events per profile" in out
    assert "last 50 sessions" in out
    assert "Synthetic request" not in out, "message content must never be printed"
    assert "redaction preflight" in out
    # Owner decision 3 (M0 audit): titles no longer ride in the event stream and
    # are not printed unless the diagnostic is asked for them.
    assert "Synthetic alpha session" not in out
    assert "--show-titles" in out


def test_summary_can_show_titles_on_request(hermes_env, capsys):
    code = main(["--days", "7", "--summary", "--show-titles"])
    out = capsys.readouterr().out
    assert code == 0
    assert "Synthetic " in out, "the diagnostic should fetch titles when asked"


def test_redaction_preflight_flags_a_planted_secret(hermes_env, capsys, monkeypatch):
    from adapters.hermes import leakscan

    original = leakscan.scan_lines

    def fake_scan(lines):
        return original(["contact test@example.com and /home/someone/secret"])

    monkeypatch.setattr(leakscan, "scan_lines", fake_scan)
    code = main(["--days", "7", "--summary", "--redaction-preflight"])
    out = capsys.readouterr().out
    assert code == 0
    assert "hit(s)" in out
    assert "email" in out


def test_profile_flag_excludes_the_fleet_store(hermes_env, capsys):
    code = main(["--days", "7", "--summary", "--profile", "alpha"])
    out = capsys.readouterr().out
    assert code == 0
    # Only the alpha profile row should be present in the per-profile table.
    profile_rows = [
        line
        for line in out.splitlines()
        if line.startswith(("alpha", "beta", "delta", "gamma", "(fleet)"))
    ]
    assert any(line.startswith("alpha") for line in profile_rows)
    assert not any(line.startswith(("beta", "delta", "gamma", "(fleet)")) for line in profile_rows)


def test_out_inside_repo_is_refused(hermes_env, repo_root, capsys):
    target = repo_root / "should-not-exist.jsonl"
    code = main(["--days", "7", "--out", str(target)])
    assert code == 3
    assert "refusing" in capsys.readouterr().err
    assert not target.exists()


def test_out_writes_jsonl_with_stable_ids(hermes_env, tmp_path, capsys):
    first = tmp_path / "events-a.jsonl"
    second = tmp_path / "events-b.jsonl"
    assert main(["--days", "7", "--out", str(first)]) == 0
    assert main(["--days", "7", "--out", str(second)]) == 0
    lines_a = first.read_text(encoding="utf-8").splitlines()
    lines_b = second.read_text(encoding="utf-8").splitlines()
    assert lines_a and lines_a == lines_b
    ids = [json.loads(line)["id"] for line in lines_a]
    assert len(ids) == len(set(ids))


def test_memory_snapshot_write_and_use(hermes_env, tmp_path, capsys):
    snapshot = tmp_path / "memory-snapshot.json"
    assert main(["--days", "7", "--write-memory-snapshot", str(snapshot)]) == 0
    data = json.loads(snapshot.read_text(encoding="utf-8"))
    assert "default/MEMORY.md" in data
    assert main(["--days", "7", "--summary", "--memory-snapshot", str(snapshot)]) == 0
    out = capsys.readouterr().out
    assert "memory.fact.added" in out or "memory          " in out


def test_read_only_audit_is_clean_after_a_run(hermes_env, capsys):
    ro.reset_audit()
    assert main(["--days", "7"]) == 0
    ro.assert_read_only_audit()
    audit = ro.read_only_audit()
    assert audit["all_read_only"] is True
    assert set(audit["modes"]) <= {"ro", "r"}
    assert isinstance(audit["modes"], list)
    assert audit["files_opened"] > 0


def test_live_schema_superset_still_works(tmp_path):
    """A database with extra columns the adapter does not know must still read."""
    home = tmp_path / "home"
    home.mkdir()
    conn = sqlite3.connect(home / "state.db")
    conn.executescript(
        """
        CREATE TABLE sessions (id TEXT PRIMARY KEY, title TEXT, started_at REAL,
            last_activity_at REAL, message_count INTEGER, brand_new_column TEXT);
        CREATE TABLE messages (id INTEGER PRIMARY KEY, session_id TEXT, role TEXT,
            content TEXT, timestamp REAL, brand_new_column TEXT);
        """
    )
    now = datetime.now(tz=timezone.utc).timestamp()
    conn.execute(
        "INSERT INTO sessions VALUES ('s1', 'Fixture session', ?, ?, 1, 'x')", (now - 60, now - 30)
    )
    conn.execute(
        "INSERT INTO messages VALUES (1, 's1', 'user', 'hello there', ?, 'x')", (now - 55,)
    )
    conn.commit()
    conn.close()

    source = HermesHistorySource(root=home)
    events = list(source.events(Window(since=now - 3600), ["session", "message"]))
    kinds = [event.kind for event in events]
    assert KIND_SESSION_STARTED in kinds
    assert "message.user" in kinds
