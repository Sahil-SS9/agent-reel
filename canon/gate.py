"""The redaction gate's output type: the only thing later stages may see.

v1 says "nothing reaches beats/arcs/renderers before passing the redaction gate"
and the M0 audit (F1) made that a type, not a convention: a ``GatedEvent`` can
only be produced by the gate, which holds the seal. A raw ``Event`` cannot be
passed to beats, arcs, the episode planner or a renderer.

The seal is an identity check on a module-private class, so it is not forgeable
by accident (``GatedEvent(...)`` raises) and not reachable from other modules
without importing the underscore name deliberately, which a review can grep for.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from canon.events import Event


class _Seal:
    """Identity token held by the gate."""

    __slots__ = ()


_SEAL = _Seal()


class UngatedError(TypeError):
    """Raised when something tries to use an event that has not been gated."""


@dataclass(frozen=True, slots=True)
class GatedEvent:
    """An event whose payload has passed the redaction gate.

    ``payload`` here is the *redacted* payload (v1 ``payload_redacted``). There is
    deliberately no accessor for the raw payload.
    """

    id: str
    ts: float
    source: str
    kind: str
    profile: str
    actor: str
    subject: str
    privacy: str
    payload: Mapping[str, Any] = field(default_factory=dict)
    derived_from: tuple[str, ...] = ()
    #: Logical provenance ({store, table, pk}); logical names only, never a path.
    ref: Mapping[str, str] = field(default_factory=dict)
    _seal: Any = None

    def __post_init__(self) -> None:
        if self._seal is not _SEAL:
            raise UngatedError(
                "GatedEvent must be built by the redaction gate (canon.redact), "
                "never directly"
            )

    def __repr__(self) -> str:  # keep the seal out of reprs/logs
        return (
            f"GatedEvent(id={self.id!r}, ts={self.ts!r}, source={self.source!r}, "
            f"kind={self.kind!r}, privacy={self.privacy!r})"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "ts": self.ts,
            "source": self.source,
            "kind": self.kind,
            "profile": self.profile,
            "actor": self.actor,
            "subject": self.subject,
            "privacy": self.privacy,
            "payload_redacted": dict(self.payload),
            "derived_from": list(self.derived_from),
            "ref": dict(self.ref),
        }


def seal(event: Event, payload_redacted: Mapping[str, Any]) -> GatedEvent:
    """Build a gated event. Only the gate module should call this."""
    if event.payload_redacted is not None:
        raise UngatedError(f"event {event.id} was already gated")
    return GatedEvent(
        id=event.id,
        ts=event.ts,
        source=event.source,
        kind=event.kind,
        profile=event.profile,
        actor=event.actor,
        subject=event.subject,
        privacy=event.privacy,
        payload=dict(payload_redacted),
        derived_from=event.derived_from,
        ref=dict(event.ref),
        _seal=_SEAL,
    )


def require_gated(events: Any, *, stage: str) -> list[GatedEvent]:
    """Type-check a sequence of gated events for a downstream stage."""
    if isinstance(events, GatedEvent):
        return [events]
    try:
        items = list(events)
    except TypeError as exc:
        raise UngatedError(f"{stage} expects an iterable of GatedEvent") from exc
    for item in items:
        if not isinstance(item, GatedEvent):
            raise UngatedError(
                f"{stage} only accepts gated events; got {type(item).__name__}. "
                "Run canon.redact.RedactionGate first."
            )
    return items
