"""Build a synthetic Hermes home for tests and benchmarks.

Nothing here comes from real history: every title, message and task is
generated text. The layout mirrors the live Hermes home closely enough that the
same adapter code paths run, while using only a *subset* of the live columns (so
the adapter's forward/back-compatible column filtering is exercised too).
"""

from __future__ import annotations

import argparse
import json
import random
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROFILES = ("alpha", "beta", "gamma", "delta")
DAYS = 28
TOOLS = ("terminal", "read_file", "patch", "search_files", "write_file", "skill_view")
SKILLS = (
    "synthetic-skill-one",
    "synthetic-skill-two",
    "synthetic-skill-three",
    "synthetic-skill-four",
    "synthetic-skill-five",
)
CRON_JOBS = (
    ("job-alpha-hourly", "synthetic-hourly-digest"),
    ("job-beta-daily", "synthetic-daily-review"),
    ("job-gamma-weekly", "synthetic-weekly-scan"),
)


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(timespec="microseconds")


def _state_db(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=wal")
    conn.executescript(
        """
        CREATE TABLE sessions (
            id TEXT PRIMARY KEY,
            source TEXT NOT NULL,
            title TEXT,
            profile_name TEXT,
            started_at REAL NOT NULL,
            ended_at REAL,
            end_reason TEXT,
            message_count INTEGER DEFAULT 0,
            tool_call_count INTEGER DEFAULT 0,
            input_tokens INTEGER DEFAULT 0,
            output_tokens INTEGER DEFAULT 0,
            model TEXT,
            git_branch TEXT,
            cwd TEXT,
            parent_session_id TEXT,
            last_activity_at REAL,
            archived INTEGER DEFAULT 0
        );
        CREATE TABLE messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT,
            tool_call_id TEXT,
            tool_calls TEXT,
            tool_name TEXT,
            timestamp REAL NOT NULL,
            token_count INTEGER,
            active INTEGER DEFAULT 1,
            compacted INTEGER DEFAULT 0
        );
        CREATE INDEX idx_messages_session ON messages(session_id, timestamp);
        """
    )
    return conn


def _kanban_db(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=wal")
    conn.executescript(
        """
        CREATE TABLE tasks (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            body TEXT,
            assignee TEXT,
            status TEXT NOT NULL,
            priority INTEGER DEFAULT 0,
            created_by TEXT,
            created_at INTEGER NOT NULL,
            started_at INTEGER,
            completed_at INTEGER,
            tenant TEXT,
            project_id TEXT,
            result TEXT
        );
        CREATE TABLE task_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT NOT NULL,
            run_id INTEGER,
            kind TEXT NOT NULL,
            payload TEXT,
            created_at INTEGER NOT NULL
        );
        CREATE TABLE task_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT NOT NULL,
            profile TEXT,
            step_key TEXT,
            status TEXT NOT NULL,
            started_at INTEGER NOT NULL,
            ended_at INTEGER,
            outcome TEXT,
            summary TEXT,
            error TEXT
        );
        CREATE TABLE task_comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT NOT NULL,
            author TEXT NOT NULL,
            body TEXT NOT NULL,
            created_at INTEGER NOT NULL
        );
        CREATE TABLE task_links (parent_id TEXT, child_id TEXT);
        """
    )
    return conn


def _cron_db(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=wal")
    conn.executescript(
        """
        CREATE TABLE executions (
            id TEXT PRIMARY KEY,
            job_id TEXT NOT NULL,
            source TEXT NOT NULL,
            process_id TEXT NOT NULL,
            pid INTEGER NOT NULL,
            status TEXT NOT NULL,
            claimed_at TEXT NOT NULL,
            started_at TEXT,
            finished_at TEXT,
            error TEXT
        );
        """
    )
    return conn


def build(target: Path, *, seed: int = 20261023, days: int = DAYS) -> Path:
    """Create a synthetic Hermes home at ``target`` and return the path."""
    rng = random.Random(seed)
    target = Path(target)
    target.mkdir(parents=True, exist_ok=True)
    now = datetime.now(tz=timezone.utc).replace(microsecond=0)
    start = now - timedelta(days=days)
    start_ts = start.timestamp()
    end_ts = now.timestamp()

    stores = [("default", target / "state.db")] + [
        (name, target / "profiles" / name / "state.db") for name in PROFILES
    ]

    session_counter = 0
    for profile, db_path in stores:
        conn = _state_db(db_path)
        sessions_in_profile = 2 if profile == "default" else 2
        for day in range(days):
            for slot in range(sessions_in_profile):
                session_counter += 1
                session_id = f"synthetic-{profile}-{session_counter:04d}"
                started = start_ts + day * 86400 + (9 + slot * 6) * 3600 + rng.randint(0, 1200)
                message_count = rng.randint(6, 18)
                duration = message_count * rng.randint(20, 90)
                ended = started + duration
                title = (
                    f"Synthetic {profile} session {day + 1}.{slot + 1}: "
                    f"fixture work on module {rng.choice('ABCDE')}"
                )
                conn.execute(
                    "INSERT INTO sessions (id, source, title, profile_name, started_at, ended_at,"
                    " end_reason, message_count, tool_call_count, input_tokens, output_tokens,"
                    " model, git_branch, cwd, parent_session_id, last_activity_at, archived)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        session_id,
                        rng.choice(("cli", "cron", "discord")),
                        title,
                        profile,
                        started,
                        ended,
                        "completed" if rng.random() > 0.2 else "",
                        message_count,
                        0,
                        rng.randint(500, 4000),
                        rng.randint(200, 2000),
                        "synthetic-model-v1",
                        "main",
                        f"/synthetic/{profile}/project",
                        None,
                        ended,
                        0,
                    ),
                )
                tool_calls = 0
                for index in range(message_count):
                    ts = started + index * 45
                    if index % 3 == 0:
                        role = "user"
                        content = (
                            f"Synthetic request {index} in {profile}: please do fixture task "
                            f"{rng.randint(1, 99)}."
                        )
                        conn.execute(
                            "INSERT INTO messages (session_id, role, content, timestamp,"
                            " token_count, active, compacted) VALUES (?,?,?,?,?,?,?)",
                            (
                                session_id,
                                role,
                                content,
                                ts,
                                len(content) // 4,
                                1,
                                0,
                            ),
                        )
                    elif index % 3 == 1:
                        tool = rng.choice(TOOLS)
                        tool_calls += 1
                        calls = json.dumps(
                            [
                                {
                                    "id": f"call_{session_id}_{index}",
                                    "call_id": f"call_{session_id}_{index}",
                                    "type": "function",
                                    "function": {
                                        "name": tool,
                                        "arguments": json.dumps(
                                            {"path": f"/synthetic/{profile}/file{index}.py"}
                                        ),
                                    },
                                }
                            ]
                        )
                        content = f"Synthetic assistant planning step {index}."
                        conn.execute(
                            "INSERT INTO messages (session_id, role, content, tool_calls,"
                            " timestamp, token_count, active, compacted)"
                            " VALUES (?,?,?,?,?,?,?,?)",
                            (
                                session_id,
                                "assistant",
                                content,
                                calls,
                                ts,
                                len(content) // 4,
                                1,
                                0,
                            ),
                        )
                    else:
                        tool = rng.choice(TOOLS)
                        content = f"Synthetic tool output for {tool} step {index}: ok."
                        conn.execute(
                            "INSERT INTO messages (session_id, role, content, tool_name,"
                            " tool_call_id, timestamp, token_count, active, compacted)"
                            " VALUES (?,?,?,?,?,?,?,?,?)",
                            (
                                session_id,
                                "tool",
                                content,
                                tool,
                                f"call_{session_id}_{index - 1}",
                                ts,
                                len(content) // 4,
                                1,
                                0,
                            ),
                        )
                conn.execute(
                    "UPDATE sessions SET tool_call_count = ? WHERE id = ?",
                    (tool_calls, session_id),
                )
        conn.commit()
        conn.close()

    # ---- kanban ---------------------------------------------------------
    kanban = _kanban_db(target / "kanban.db")
    task_counter = 0
    for day in range(days):
        task_counter += 1
        created = int(start_ts + day * 86400 + 10 * 3600)
        started = created + rng.randint(60, 900)
        completed = started + rng.randint(600, 5400) if rng.random() > 0.25 else None
        assignee = rng.choice(PROFILES)
        task_id = f"t_synthetic{task_counter:04d}"
        title = f"Synthetic task {task_counter}: fixture work for {assignee}"
        kanban.execute(
            "INSERT INTO tasks (id, title, body, assignee, status, priority, created_by,"
            " created_at, started_at, completed_at, tenant, project_id, result)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                task_id,
                title,
                f"Synthetic body for {task_id}. No real content.",
                assignee,
                "done" if completed else "blocked",
                rng.randint(0, 9),
                "synthetic-kensei",
                created,
                started,
                completed,
                "",
                "",
                "synthetic result" if completed else "",
            ),
        )
        kanban.execute(
            "INSERT INTO task_events (task_id, run_id, kind, payload, created_at)"
            " VALUES (?,?,?,?,?)",
            (task_id, None, "created", json.dumps({"by": "synthetic-kensei"}), created),
        )
        kanban.execute(
            "INSERT INTO task_events (task_id, run_id, kind, payload, created_at)"
            " VALUES (?,?,?,?,?)",
            (task_id, None, "claimed", json.dumps({"assignee": assignee}), started),
        )
        kanban.execute(
            "INSERT INTO task_events (task_id, run_id, kind, payload, created_at)"
            " VALUES (?,?,?,?,?)",
            (task_id, None, "heartbeat", json.dumps({"note": "synthetic"}), started + 30),
        )
        if completed:
            kanban.execute(
                "INSERT INTO task_events (task_id, run_id, kind, payload, created_at)"
                " VALUES (?,?,?,?,?)",
                (task_id, None, "completed", json.dumps({"ok": True}), completed),
            )
        run_status = "done" if completed else "blocked"
        cur = kanban.execute(
            "INSERT INTO task_runs (task_id, profile, step_key, status, started_at, ended_at,"
            " outcome, summary, error) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                task_id,
                assignee,
                "",
                run_status,
                started,
                completed,
                "completed" if completed else "blocked",
                f"Synthetic run summary for {task_id}.",
                None if completed else "synthetic blocker",
            ),
        )
        kanban.execute("UPDATE task_events SET run_id = ? WHERE task_id = ?", (cur.lastrowid, task_id))
        # A task family every third day, so threads can be built from links.
        if task_counter > 1 and task_counter % 3 == 1:
            parent_id = f"t_synthetic{task_counter - 1:04d}"
            kanban.execute(
                "INSERT INTO task_links (parent_id, child_id) VALUES (?,?)",
                (parent_id, task_id),
            )
        kanban.execute(
            "INSERT INTO task_comments (task_id, author, body, created_at) VALUES (?,?,?,?)",
            (
                task_id,
                rng.choice(PROFILES),
                f"Synthetic comment on {task_id}: fixture note {rng.randint(1, 99)}.",
                created + 120,
            ),
        )
    kanban.commit()
    kanban.close()

    # ---- cron -----------------------------------------------------------
    cron = _cron_db(target / "cron" / "executions.db")
    exec_counter = 0
    for hour in range(days * 24):
        ts = start_ts + hour * 3600
        if rng.random() > 0.55:
            continue
        job_id, _ = rng.choice(CRON_JOBS)
        exec_counter += 1
        status = "completed" if rng.random() > 0.15 else "failed"
        started = ts + 30
        finished = started + rng.randint(5, 120)
        cron.execute(
            "INSERT INTO executions (id, job_id, source, process_id, pid, status, claimed_at,"
            " started_at, finished_at, error) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                f"exec_{exec_counter:05d}",
                job_id,
                "ticker",
                f"proc_{exec_counter}",
                1000 + exec_counter,
                status,
                _iso(ts),
                _iso(started),
                _iso(finished),
                None if status == "completed" else "synthetic failure",
            ),
        )
    cron.commit()
    cron.close()

    jobs = {
        "jobs": [
            {"id": job_id, "name": name, "schedule": "*/60"}
            for job_id, name in CRON_JOBS
        ],
        "updated_at": _iso(now.timestamp()),
    }
    (target / "cron" / "jobs.json").write_text(json.dumps(jobs, indent=1), encoding="utf-8")

    # ---- skills + memory ------------------------------------------------
    def write_skills(profile: str, home: Path) -> None:
        skills_dir = home / "skills"
        skills_dir.mkdir(parents=True, exist_ok=True)
        usage = {}
        for index, skill in enumerate(SKILLS):
            created = start_ts + index * 86400 + (1 + index) * 3600
            usage[f"./{skill}"] = {
                "created_at": _iso(created),
                "last_used_at": _iso(min(created + rng.randint(3600, 86400 * 5), end_ts - 60)),
                "last_viewed_at": _iso(created),
                "last_patched_at": _iso(created + 7200) if index % 2 else None,
                "patch_count": 1 if index % 2 else 0,
                "patch_generation": 1 if index % 2 else 0,
                "pinned": index == 0,
                "state": "active",
                "use_count": rng.randint(1, 14),
                "view_count": rng.randint(1, 20),
                "archived_at": _iso(created + 86400 * 3) if index == len(SKILLS) - 1 else None,
                "created_by": profile,
            }
        (skills_dir / ".usage.json").write_text(json.dumps(usage, indent=1), encoding="utf-8")

    def write_memory(profile: str, home: Path, n_facts: int) -> None:
        mem_dir = home / "memories"
        mem_dir.mkdir(parents=True, exist_ok=True)
        facts = [f"Synthetic fact {i + 1} for {profile}: fixture value {rng.randint(1, 500)}." for i in range(n_facts)]
        (mem_dir / "MEMORY.md").write_text("\n\u00a7\n".join(facts) + "\n", encoding="utf-8")
        user_facts = [f"Synthetic user fact {i + 1} for {profile}." for i in range(2)]
        (mem_dir / "USER.md").write_text("\n\u00a7\n".join(user_facts) + "\n", encoding="utf-8")

    write_skills("default", target)
    write_memory("default", target, 6)
    for profile in PROFILES:
        home = target / "profiles" / profile
        write_skills(profile, home)
        write_memory(profile, home, 4)

    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate a synthetic Hermes home.")
    parser.add_argument("target", help="directory to create")
    parser.add_argument("--seed", type=int, default=20261023)
    parser.add_argument("--days", type=int, default=DAYS)
    args = parser.parse_args(argv)
    target = build(Path(args.target).expanduser(), seed=args.seed, days=args.days)
    print(f"synthetic Hermes home written to {target}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
