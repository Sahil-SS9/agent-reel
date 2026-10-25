"""V12 (25/10/26): other harnesses become the same read-only, text-free event stream."""

import json
import sqlite3
import time
from pathlib import Path

from canon.events import KIND_MESSAGE_ASSISTANT, KIND_MESSAGE_USER
from canon.source import HistorySource, Window
from adapters.harnesses.sessions import CompositeSource, make_source, prose_of

NOW = time.time()
ISO = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(NOW - 3600))
WINDOW = Window(since=NOW - 86400)


def _write(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def _check(source, expect_user, expect_assistant):
    assert isinstance(source, HistorySource)
    events = list(source.events(WINDOW))
    users = [e for e in events if e.kind == KIND_MESSAGE_USER]
    assistants = [e for e in events if e.kind == KIND_MESSAGE_ASSISTANT]
    assert [source.fetch_content(e.content_ref) for e in users] == expect_user
    assert [source.fetch_content(e.content_ref) for e in assistants] == expect_assistant
    for event in users + assistants:
        assert "text" not in event.payload and event.payload["chars"] > 0  # no text in the stream
        assert "/" not in event.content_ref.store  # logical store names, never paths
    assert all(e.actor == "owner" for e in users)
    return events


def test_claude_code(tmp_path):
    _write(tmp_path / "proj" / "s1.jsonl", [
        {"type": "user", "timestamp": ISO, "message": {"role": "user", "content": "Fix the flaky login test."}},
        {"type": "assistant", "timestamp": ISO, "message": {"role": "assistant", "content": [
            {"type": "thinking", "thinking": "secret plan"}, {"type": "text", "text": "Found it: a race in setup."},
            {"type": "tool_use", "name": "Bash", "input": {}}]}},
        {"type": "user", "timestamp": ISO, "message": {"role": "user", "content": [{"type": "tool_result", "content": "ok"}]}},
        {"type": "user", "timestamp": ISO, "isSidechain": True, "message": {"role": "user", "content": "sub-agent chatter"}},
        {"type": "summary", "summary": "x"},
    ])
    _check(make_source("claude-code", root=str(tmp_path)), ["Fix the flaky login test."], ["Found it: a race in setup."])


def test_codex(tmp_path):
    _write(tmp_path / "2026" / "10" / "25" / "rollout-1.jsonl", [
        {"timestamp": ISO, "type": "session_meta", "payload": {"id": "abc", "cwd": "/x"}},
        {"timestamp": ISO, "type": "response_item", "payload": {"type": "message", "role": "user", "content": [
            {"type": "input_text", "text": "<environment_context>cwd</environment_context>"}]}},
        {"timestamp": ISO, "type": "response_item", "payload": {"type": "message", "role": "user", "content": [
            {"type": "input_text", "text": "Speed up the parser."}]}},
        {"timestamp": ISO, "type": "response_item", "payload": {"type": "function_call", "name": "shell"}},
        {"timestamp": ISO, "type": "response_item", "payload": {"type": "message", "role": "assistant", "content": [
            {"type": "output_text", "text": "Parser is 2x faster now."}]}},
        {"timestamp": ISO, "type": "response_item", "payload": {"type": "message", "role": "developer", "content": [
            {"type": "input_text", "text": "system rules"}]}},
    ])
    _check(make_source("codex", root=str(tmp_path)), ["Speed up the parser."], ["Parser is 2x faster now."])


def test_pi(tmp_path):
    _write(tmp_path / "--home-me--" / "2026_abc.jsonl", [
        {"type": "session", "id": "abc", "timestamp": ISO},
        {"type": "message", "timestamp": ISO, "message": {"role": "user", "content": [{"type": "text", "text": "Add dark mode."}]}},
        {"type": "message", "timestamp": ISO, "message": {"role": "toolResult", "content": [{"type": "text", "text": "ok"}]}},
        {"type": "message", "timestamp": ISO, "message": {"role": "assistant", "content": [{"type": "text", "text": "Dark mode is in."}]}},
    ])
    _check(make_source("pi", root=str(tmp_path)), ["Add dark mode."], ["Dark mode is in."])


def test_generic_jsonl_mapping(tmp_path):
    _write(tmp_path / "logs" / "a" / "one.jsonl", [
        {"when": NOW - 60, "who": "human", "body": "Ship the release notes."},
        {"when": NOW - 30, "who": "bot", "body": "Release notes are published."},
        {"when": NOW - 10, "who": "tool", "body": "noise"},
    ])
    mapping = {"glob": str(tmp_path / "logs" / "**" / "*.jsonl"), "name": "commandcode", "role": "who", "text": "body",
               "timestamp": "when", "user_roles": ["human"], "assistant_roles": ["bot"]}
    _check(make_source("jsonl", mapping=mapping), ["Ship the release notes."], ["Release notes are published."])


def test_opencode_reads_only_story_tables(tmp_path):
    db = tmp_path / "opencode.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        "CREATE TABLE session (id text primary key, title text); "
        "CREATE TABLE message (id text primary key, session_id text, time_created integer, time_updated integer, data text); "
        "CREATE TABLE part (id text primary key, message_id text, session_id text, time_created integer, time_updated integer, data text); "
        "CREATE TABLE credential (id text, value text);"
    )
    ms = int((NOW - 3600) * 1000)
    conn.execute("INSERT INTO credential VALUES ('c', 'sk-should-never-be-read')")
    conn.execute("INSERT INTO message VALUES ('m1','s1',?,?,?)", (ms, ms, json.dumps({"role": "user"})))
    conn.execute("INSERT INTO message VALUES ('m2','s1',?,?,?)", (ms + 1, ms + 1, json.dumps({"role": "assistant"})))
    conn.execute("INSERT INTO part VALUES ('p1','m1','s1',?,?,?)", (ms, ms, json.dumps({"type": "text", "text": "Plan the migration."})))
    conn.execute("INSERT INTO part VALUES ('p2','m2','s1',?,?,?)", (ms, ms, json.dumps({"type": "tool", "tool": "bash"})))
    conn.execute("INSERT INTO part VALUES ('p3','m2','s1',?,?,?)", (ms, ms, json.dumps({"type": "text", "text": "Migration plan drafted."})))
    conn.commit()
    conn.close()
    before = sorted(p.name for p in tmp_path.iterdir())
    events = _check(make_source("opencode", root=str(db)), ["Plan the migration."], ["Migration plan drafted."])
    assert sorted(p.name for p in tmp_path.iterdir()) == before  # read-only: no sidecars created
    assert all("sk-should" not in json.dumps(e.payload) for e in events)


def test_composite_merges_by_time(tmp_path):
    _write(tmp_path / "pi" / "x" / "1.jsonl", [
        {"type": "message", "timestamp": NOW - 100, "message": {"role": "user", "content": "first"}}])
    _write(tmp_path / "cc" / "p" / "2.jsonl", [
        {"type": "user", "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(NOW - 50)), "message": {"role": "user", "content": "second"}}])
    combo = CompositeSource([make_source("pi", root=str(tmp_path / "pi")), make_source("claude-code", root=str(tmp_path / "cc"))])
    texts = [combo.fetch_content(e.content_ref) for e in combo.events(WINDOW) if e.content_ref]
    assert texts == ["first", "second"]
    assert combo.info().harness == "pi+claude-code"


def test_prose_of_skips_non_text_blocks():
    assert prose_of([{"type": "text", "text": "a"}, {"type": "tool_use"}, {"type": "output_text", "text": "b"}]) == "a\n\nb"
    assert prose_of(None) == ""
