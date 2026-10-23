from pathlib import Path

import pytest

from fixtures.build_synthetic_home import build

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def synthetic_home(tmp_path_factory) -> Path:
    target = tmp_path_factory.mktemp("synthetic-hermes")
    return build(target, seed=7)


@pytest.fixture()
def fresh_home(tmp_path) -> Path:
    return build(tmp_path / "home", seed=11, days=3)


@pytest.fixture(autouse=True)
def _isolated_snapshot_root(tmp_path, monkeypatch):
    """F2: no test may write a private copy into the default root."""
    root = tmp_path / "snapshot-root"
    root.mkdir()
    monkeypatch.setenv("REEL_SNAPSHOT_DIR", str(root))
    return root


@pytest.fixture()
def hermes_env(monkeypatch, synthetic_home) -> Path:
    """Point the CLI at the synthetic home so tests never read real history."""
    monkeypatch.setenv("HERMES_HOME", str(synthetic_home))
    return synthetic_home


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT
