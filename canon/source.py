"""Harness-agnostic history source contract.

A ``HistorySource`` is the only thing the engine needs from a harness. Hermes is
the first adapter (``adapters/hermes``); another harness only has to satisfy this
protocol (decision D2).

Tests use fakes, so this module stays pure Python.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator, Protocol, Sequence, runtime_checkable

from canon.events import ContentRef, Event


@dataclass(frozen=True, slots=True)
class Window:
    """Half-open time window: ``since <= ts < until``."""

    since: float
    until: float | None = None

    def contains(self, ts: float) -> bool:
        if ts < self.since:
            return False
        if self.until is not None and ts >= self.until:
            return False
        return True


@dataclass(frozen=True, slots=True)
class ProfileRef:
    """A profile the adapter can read history from."""

    name: str
    store: str
    available: bool = True


@dataclass(frozen=True, slots=True)
class SourceInfo:
    """What an adapter found when it looked at the harness."""

    harness: str
    root: str
    profiles: tuple[ProfileRef, ...] = ()
    stores: tuple[str, ...] = ()
    missing: tuple[str, ...] = ()


class ContentUnavailable(RuntimeError):
    """Raised when an adapter cannot materialise a ``ContentRef``."""


@runtime_checkable
class HistorySource(Protocol):
    """What every harness adapter must implement."""

    def info(self) -> SourceInfo:
        ...

    def events(
        self, window: Window, sources: Sequence[str] | None = None
    ) -> Iterator[Event]:
        ...

    def fetch_content(self, ref: ContentRef) -> str:
        ...
