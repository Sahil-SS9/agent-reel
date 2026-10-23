"""Locating a Hermes home without assuming one layout.

Hermes keeps fleet-wide state in ``$HERMES_HOME`` and per-profile state in
``$HERMES_HOME/profiles/<name>/``. Both are enumerated here so the rest of the
adapter never hardcodes a path.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_HERMES_HOME = Path.home() / ".hermes"


@dataclass(frozen=True, slots=True)
class ProfileStore:
    name: str
    home: Path
    state_db: Path

    @property
    def available(self) -> bool:
        return self.state_db.is_file()


@dataclass(frozen=True, slots=True)
class HermesPaths:
    """Resolved locations of everything the history adapter reads."""

    home: Path

    @classmethod
    def resolve(cls, root: str | os.PathLike[str] | None = None) -> "HermesPaths":
        if root is not None:
            return cls(Path(root).expanduser())
        env = os.environ.get("HERMES_HOME")
        if env:
            return cls(Path(env).expanduser())
        return cls(DEFAULT_HERMES_HOME)

    # ---- fleet-wide stores -------------------------------------------------
    @property
    def main_state_db(self) -> Path:
        return self.home / "state.db"

    @property
    def kanban_db(self) -> Path:
        return self.home / "kanban.db"

    @property
    def cron_executions_db(self) -> Path:
        return self.home / "cron" / "executions.db"

    @property
    def cron_jobs_json(self) -> Path:
        return self.home / "cron" / "jobs.json"

    @property
    def skills_usage_json(self) -> Path:
        return self.home / "skills" / ".usage.json"

    @property
    def memory_files(self) -> tuple[Path, Path]:
        return (self.home / "memories" / "MEMORY.md", self.home / "memories" / "USER.md")

    # ---- per profile -------------------------------------------------------
    @property
    def profiles_dir(self) -> Path:
        return self.home / "profiles"

    def profiles(self) -> list[ProfileStore]:
        """Every profile directory that has a state.db, sorted by name."""
        found: list[ProfileStore] = []
        root = self.profiles_dir
        if not root.is_dir():
            return found
        for entry in sorted(root.iterdir(), key=lambda p: p.name):
            if not entry.is_dir():
                continue
            state_db = entry / "state.db"
            found.append(ProfileStore(name=entry.name, home=entry, state_db=state_db))
        return found

    def profile(self, name: str) -> ProfileStore | None:
        for store in self.profiles():
            if store.name == name:
                return store
        return None

    def profile_skills_usage_json(self, store: ProfileStore) -> Path:
        return store.home / "skills" / ".usage.json"

    def profile_memory_files(self, store: ProfileStore) -> tuple[Path, Path]:
        return (store.home / "memories" / "MEMORY.md", store.home / "memories" / "USER.md")
