"""Other harnesses: a log file is a session, but a story needs a thread."""
import json
from pathlib import Path

from adapters.harnesses.sessions import ClaudeCodeSource, GenericJsonlSource, Window


def _write(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")


def _record(role: str, text: str, when: str, cwd: str = "/work/project") -> dict:
    return {
        "type": role,
        "cwd": cwd,
        "timestamp": when,
        "sessionId": f"s-{text[:6]}",
        "message": {"role": role, "content": text if role == "user" else [{"type": "text", "text": text}]},
    }


def test_claude_sessions_in_one_project_share_a_thread(tmp_path):
    for i in range(3):
        _write(tmp_path / "projects" / "-work-project" / f"s{i}.jsonl",
               [_record("user", f"question {i}", "2026-10-20T10:00:00Z"),
                _record("assistant", f"answer {i}", "2026-10-20T10:00:05Z")])
    src = ClaudeCodeSource(tmp_path / "projects")
    msgs = list(src._messages(Window(since=0, until=2e9)))
    assert len({m.session for m in msgs}) == 3          # three sessions …
    assert len({m.thread for m in msgs}) == 1           # … one thread
    assert {m.thread for m in msgs} == {"-work-project"}


def test_a_jsonl_mapping_can_name_the_thread_field(tmp_path):
    path = tmp_path / "logs" / "a.jsonl"
    _write(path, [
        _record("user", "one", "2026-10-20T10:00:00Z", cwd="/work/alpha"),
        _record("assistant", "two", "2026-10-20T10:00:05Z", cwd="/work/alpha"),
        _record("user", "three", "2026-10-20T11:00:00Z", cwd="/work/beta"),
    ])
    mapping = {"name": "claude-code", "glob": str(tmp_path / "logs" / "*.jsonl"),
               "role": "message.role", "text": "message.content", "timestamp": "timestamp",
               "session": "sessionId", "thread": "cwd"}
    src = GenericJsonlSource(mapping)
    threads = {m.thread for m in src._messages(Window(since=0, until=2e9))}
    assert threads == {"/work/alpha", "/work/beta"}


def test_without_a_thread_every_file_stays_its_own_thread(tmp_path):
    _write(tmp_path / "x" / "a.jsonl", [_record("user", "hi", "2026-10-20T10:00:00Z")])
    mapping = {"glob": str(tmp_path / "x" / "*.jsonl"), "role": "message.role",
               "text": "message.content", "timestamp": "timestamp"}
    src = GenericJsonlSource(mapping)
    msgs = list(src._messages(Window(since=0, until=2e9)))
    assert msgs and msgs[0].thread in {"", "a"}
