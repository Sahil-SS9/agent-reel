"""The evidence writer: nothing goes into an evidence folder that the gate would change.

Audit M1-F4: the pipeline wrote ``memory-facts.json`` into the evidence folder and it
held the full unredacted MEMORY/USER text of every profile - 53 emails, 25 absolute
paths, mode 644, in ``~/handoffs``. That is a ground-rule-5 breach.

The rule enforced here is deliberately mechanical: **a string may only be written if
running the redaction gate over it changes nothing.** Raw memory facts change (emails,
paths, names), so they are refused; a value the gate already produced is unchanged and
passes. Text produced by the gate itself can also be wrapped in :class:`Gated` to skip
the re-scan.

Anything refused raises :class:`EvidenceLeak` with the offending path, so the run fails
loudly instead of quietly publishing.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping


class EvidenceLeak(RuntimeError):
    """A value about to be written to evidence would not survive the gate."""


@dataclass(frozen=True, slots=True)
class Gated:
    """Text that the gate has already produced. Unwrapped as-is."""

    text: str

    def __str__(self) -> str:
        return self.text


#: Longest plain string an evidence file may carry without being marked gated.
MAX_PLAIN_STRING = 4000


def _check_string(value: str, where: str, gate: Any) -> str:
    if len(value) > MAX_PLAIN_STRING:
        raise EvidenceLeak(f"{where}: string of {len(value)} chars looks like raw text")
    # Ask the gate what it *finds*, not what it would produce: a long script gets
    # truncated by redact_text, and truncation is not a leak.
    findings = gate.scan(value)
    if findings:
        categories = sorted({finding.category for finding in findings})
        raise EvidenceLeak(
            f"{where}: value would be changed by the gate ({', '.join(categories)}); "
            "write the gated form or a count instead"
        )
    return value


def _walk(payload: Any, where: str, gate: Any, problems: list[str]) -> Any:
    if isinstance(payload, Gated):
        return payload.text
    if isinstance(payload, str):
        try:
            return _check_string(payload, where, gate)
        except EvidenceLeak as exc:
            problems.append(str(exc))
            return "[refused]"
    if isinstance(payload, Mapping):
        return {
            str(key): _walk(value, f"{where}.{key}", gate, problems)
            for key, value in payload.items()
        }
    if isinstance(payload, (list, tuple)):
        return [
            _walk(value, f"{where}[{index}]", gate, problems)
            for index, value in enumerate(payload)
        ]
    if isinstance(payload, (int, float, bool)) or payload is None:
        return payload
    return str(payload)


def validate(payload: Any, gate: Any) -> list[str]:
    """Return the list of leaks that would be committed by writing ``payload``."""
    problems: list[str] = []
    _walk(payload, "<root>", gate, problems)
    return problems


def write_json(path: Path | str, payload: Any, gate: Any, *, indent: int = 1) -> Path:
    """Write JSON to an evidence path, refusing any value the gate would change."""
    target = Path(path)
    problems: list[str] = []
    clean = _walk(payload, target.name, gate, problems)
    if problems:
        raise EvidenceLeak(
            f"refusing to write {target}: " + "; ".join(problems[:5])
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(clean, indent=indent, sort_keys=True), encoding="utf-8")
    return target


def write_text(path: Path | str, text: str, gate: Any) -> Path:
    """Write gated prose (a rendered script) after re-checking it."""
    target = Path(path)
    _check_string(text, target.name, gate)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return target


def write_private_json(path: Path | str, payload: Any) -> Path:
    """Write to a private store (plugin data dir): mode 600, no evidence rules.

    Used only for the memory snapshot, which lives outside evidence by design
    (audit M1-F4) and must never be copied into it.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(target.parent, 0o700) if target.parent.exists() else None
    handle = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(handle, "w", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=1, sort_keys=True)
    os.chmod(target, 0o600)
    return target


def assert_no_raw_text(paths: Iterable[Path], gate: Any) -> list[str]:
    """Scan existing files for anything the gate would change. Returns problems."""
    problems: list[str] = []
    for path in paths:
        target = Path(path)
        if not target.is_file():
            continue
        try:
            text = target.read_text(encoding="utf-8")
        except OSError:
            continue
        _, findings = gate.redact_text(text)
        if findings:
            problems.append(
                f"{target}: {len(findings)} gated item(s): "
                + ", ".join(sorted({finding.category for finding in findings}))
            )
    return problems
