"""F2: private copies must not outlive a run, even a failing one."""

from __future__ import annotations

import gc
import os
import subprocess
import sqlite3
import sys
from pathlib import Path

import pytest

from adapters.hermes.stores import ACTION_SNAPSHOT, StoreReader


def _wal_db_without_sidecars(path: Path) -> Path:
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=wal")
    conn.execute("CREATE TABLE demo (id INTEGER PRIMARY KEY, value TEXT)")
    conn.execute("INSERT INTO demo (value) VALUES ('hello')")
    conn.commit()
    conn.close()
    assert not Path(f"{path}-wal").exists()
    return path


def test_snapshot_dir_is_removed_on_close(tmp_path):
    root = tmp_path / "root"
    reader = StoreReader(snapshot_root=root)
    reader.open(_wal_db_without_sidecars(tmp_path / "a.db"))
    assert list(root.iterdir()), "expected a snapshot directory while open"
    reader.close()
    assert list(root.iterdir()) == []


def test_snapshot_dir_is_removed_when_the_run_raises(tmp_path):
    root = tmp_path / "root"
    reader = StoreReader(snapshot_root=root)
    reader.open(_wal_db_without_sidecars(tmp_path / "a.db"))
    assert list(root.iterdir())
    # Simulate a run that dies before close(): drop the only reference.
    del reader
    gc.collect()
    assert list(root.iterdir()) == []


def test_close_is_idempotent(tmp_path):
    root = tmp_path / "root"
    reader = StoreReader(snapshot_root=root)
    reader.open(_wal_db_without_sidecars(tmp_path / "a.db"))
    reader.close()
    reader.close()
    assert list(root.iterdir()) == []


def test_interpreter_exit_cleans_up_without_close(tmp_path):
    """atexit path: the process ends normally and must not leave a copy behind."""
    root = tmp_path / "root"
    root.mkdir()
    db = _wal_db_without_sidecars(tmp_path / "a.db")
    code = (
        "import sys;"
        "from pathlib import Path;"
        "sys.path.insert(0, %r);"
        "from adapters.hermes.stores import StoreReader;"
        "r = StoreReader(snapshot_root=Path(%r));"
        "r.open(Path(%r));"
        "print('open', len(list(Path(%r).iterdir())))"
        % (str(Path(__file__).resolve().parents[1]), str(root), str(db), str(root))
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "open 1" in result.stdout
    assert list(root.iterdir()) == [], "atexit left the snapshot behind"


def test_default_root_is_empty_after_a_full_adapter_run(tmp_path, synthetic_home):
    """The real adapter path, not just StoreReader in isolation."""
    from adapters.hermes.history import HermesHistorySource
    from canon.source import Window

    root = tmp_path / "default-root"
    source = HermesHistorySource(root=synthetic_home, snapshot_root=root)
    from datetime import datetime, timezone

    now = datetime.now(tz=timezone.utc).timestamp()
    events = list(source.events(Window(since=now - 40 * 86400)))
    source.close()
    assert events
    assert list(root.iterdir()) == []


def test_default_root_is_empty_after_a_failing_adapter_run(tmp_path, synthetic_home):
    from adapters.hermes.history import HermesHistorySource
    from canon.source import Window
    from datetime import datetime, timezone

    root = tmp_path / "default-root"
    source = HermesHistorySource(root=synthetic_home, snapshot_root=root)
    now = datetime.now(tz=timezone.utc).timestamp()
    gen = source.events(Window(since=now - 40 * 86400))
    next(gen)  # starts reading, may create a copy
    with pytest.raises(RuntimeError):
        raise RuntimeError("run dies mid-way")
    del gen, source
    gc.collect()
    assert list(root.iterdir()) == []


def test_sigterm_cleans_up_the_snapshot(tmp_path):
    """A killed run must not leave a copy of the user's database behind.

    weakref.finalize covers GC and a normal exit; a signal needs the CLI's handler
    to turn it into a normal exit, so the whole stack is exercised here.
    """
    root = tmp_path / "root"
    root.mkdir()
    db = _wal_db_without_sidecars(tmp_path / "a.db")
    code = (
        "import os, signal, sys;"
        "from pathlib import Path;"
        "sys.path.insert(0, %r);"
        "from adapters.hermes.pipeline import _install_signal_cleanup;"
        "from adapters.hermes.stores import StoreReader;"
        "_install_signal_cleanup();"
        "r = StoreReader(snapshot_root=Path(%r));"
        "r.open(Path(%r));"
        "print('copied', len([p for p in Path(%r).iterdir() if p.name.startswith('reel-store')]))"
        ";os.kill(os.getpid(), signal.SIGTERM)"
        % (str(Path(__file__).resolve().parents[1]), str(root), str(db), str(root))
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert "copied 1" in result.stdout
    assert result.returncode == 143, result.returncode  # 128 + SIGTERM
    assert [p for p in root.iterdir() if p.name.startswith("reel-store")] == []


def test_env_var_controls_the_default_root(tmp_path, monkeypatch):
    root = tmp_path / "env-root"
    monkeypatch.setenv("REEL_SNAPSHOT_DIR", str(root))
    reader = StoreReader()
    reader.open(_wal_db_without_sidecars(tmp_path / "a.db"))
    assert reader.decisions()[0].action == ACTION_SNAPSHOT
    assert list(root.iterdir())
    reader.close()
    assert list(root.iterdir()) == []
