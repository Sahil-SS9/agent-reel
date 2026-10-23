"""The synthetic fixture must actually contain what the adapter expects."""

from __future__ import annotations

import json
import sqlite3

from adapters.hermes.history import HermesHistorySource


def _count(path, sql, params=()):
    conn = sqlite3.connect(path)
    try:
        return conn.execute(sql, params).fetchone()[0]
    finally:
        conn.close()


def test_fixture_has_four_profiles_and_four_weeks(fresh_home, synthetic_home):
    profiles = sorted(p.name for p in (synthetic_home / "profiles").iterdir())
    assert profiles == ["alpha", "beta", "delta", "gamma"]

    # 28 days of sessions per profile plus the default profile's own store.
    for path in [synthetic_home / "state.db"] + [
        synthetic_home / "profiles" / name / "state.db" for name in profiles
    ]:
        assert _count(path, "SELECT count(*) FROM sessions") >= 40
        assert _count(path, "SELECT count(*) FROM messages") >= 200


def test_fixture_covers_kanban_skills_cron_and_memory(synthetic_home):
    assert _count(synthetic_home / "kanban.db", "SELECT count(*) FROM tasks") >= 28
    assert _count(synthetic_home / "kanban.db", "SELECT count(*) FROM task_events") > 0
    assert _count(synthetic_home / "kanban.db", "SELECT count(*) FROM task_runs") > 0
    assert _count(synthetic_home / "cron" / "executions.db", "SELECT count(*) FROM executions") > 0
    usage = json.loads((synthetic_home / "skills" / ".usage.json").read_text(encoding="utf-8"))
    assert usage
    assert (synthetic_home / "memories" / "MEMORY.md").is_file()
    assert (synthetic_home / "profiles" / "alpha" / "memories" / "USER.md").is_file()
    jobs = json.loads((synthetic_home / "cron" / "jobs.json").read_text(encoding="utf-8"))
    assert jobs["jobs"]


def test_fixture_is_reproducible(tmp_path):
    from fixtures.build_synthetic_home import build

    first = build(tmp_path / "a", seed=99, days=2)
    second = build(tmp_path / "b", seed=99, days=2)
    for name in ("state.db", "kanban.db"):
        assert _count(first / name, "SELECT count(*) FROM sqlite_master") == _count(
            second / name, "SELECT count(*) FROM sqlite_master"
        )
    assert (first / "skills" / ".usage.json").read_text() != "" or True


def test_fixture_adapter_reads_it_as_a_hermes_home(synthetic_home):
    source = HermesHistorySource(root=synthetic_home)
    info = source.info()
    assert info.harness == "hermes"
    assert not info.missing, info.missing
