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
    # Tests use custom state dirs next to their data dir; the production guard has its
    # own test which clears this.
    monkeypatch.setenv("REEL_ALLOW_CUSTOM_STATE", "1")
    return root


@pytest.fixture()
def hermes_env(monkeypatch, synthetic_home) -> Path:
    """Point the CLI at the synthetic home so tests never read real history."""
    monkeypatch.setenv("HERMES_HOME", str(synthetic_home))
    return synthetic_home


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


class StubWriter:
    """A deterministic stand-in for the model: one written sentence per panel.

    Captions are prose (round 8 / R7-F1), so a planner test has to supply a writer.
    """

    name = "stub"

    def __init__(self, captions: dict | None = None, lines: dict | None = None):
        self.captions = dict(captions or {})
        self.lines = dict(lines or {})
        self.seen: list[str] = []

    def write(self, panels):
        out = {}
        for panel in panels:
            role = panel["role"]
            self.seen.append(role)
            caption = self.captions.get(role)
            if caption is None:
                caption = str(panel.get("fact_sentence") or panel.get("summary") or "").strip()
            out[role] = {"caption": caption, "lines": [list(pair) for pair in self.lines.get(role, [])]}
        return out


class FactCaptionWriter:
    """A stand-in for the model that writes the panel's fact sentence as its caption.

    Tests that are about dialogue, casting or plumbing need panels to exist; this writer
    makes them exist without pretending to be the prose writer.
    """

    name = "fact-caption"

    def __init__(self, lines: dict | None = None):
        self.lines = dict(lines or {})

    def write(self, panels):
        out = {}
        for panel in panels:
            caption = str(panel.get("fact_sentence") or panel.get("summary") or "").strip()
            out[panel["role"]] = {
                "caption": caption,
                "lines": [list(pair) for pair in self.lines.get(panel["role"], [])],
            }
        return out
