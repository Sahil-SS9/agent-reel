"""Style cards and character kits (M2 P1). Harness-free: no Hermes import.

A **style card** says how panels look:
- a prompt block and a negative block
- reference sheets
- the models it was tested on
- a licence note

A **character kit** says who someone is: one reference sheet per style.

Both are plain JSON on disk, so a user can add their own without code:
- built-ins ship in the repo (``styles/``, ``kits/``)
- user cards live in the plugin data dir (``<data>/styles/<name>/style.json``, ``<data>/kits/<key>/kit.json``)
- a user card with the same name overrides a built-in

Rules enforced here, before any image is generated:
- **Approval.** A kit renders only after its owner approved that exact sheet, recorded with the sheet's SHA-256. Replacing the sheet withdraws the approval.
- **Public mode (D9).** A kit that depicts a real person renders publicly only with a recorded consent. The owner's own kit counts as consented.
- **Untested styles** (status "experimental") are refused unless the caller opts in.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

STYLE_FIELDS = ("name", "prompt_block", "negative_block", "tested_on", "licence", "status")
KIT_FIELDS = ("name", "sheets", "licence")


class AssetError(ValueError):
    """A style card or kit is missing, invalid, or not cleared to render."""


@dataclass(frozen=True, slots=True)
class StyleCard:
    key: str
    name: str
    title: str
    prompt_block: str
    negative_block: str
    staging_rules: str
    refs: tuple[Path, ...]
    tested_on: tuple[str, ...]
    licence: str
    status: str  # approved | experimental
    source: str  # builtin | user

    @property
    def tested(self) -> bool:
        return self.status == "approved" and bool(self.tested_on)


@dataclass(frozen=True, slots=True)
class CharacterKit:
    key: str
    name: str
    role: str
    description: str
    sheets: Mapping[str, Path]
    real_person: bool
    owner: bool
    public_consent: bool
    licence: str
    source: str

    def sheet(self, style: str) -> Path:
        path = self.sheets.get(style)
        if path is None:
            raise AssetError(f"kit {self.key!r} has no sheet for style {style!r}")
        if not path.is_file():
            raise AssetError(f"kit {self.key!r} sheet for {style!r} is missing: {path}")
        return path


def _read(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AssetError(f"cannot read {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise AssetError(f"{path} is not a JSON object")
    return data


def _style(path: Path, source: str) -> StyleCard:
    data = _read(path)
    missing = [name for name in STYLE_FIELDS if name not in data]
    if missing:
        raise AssetError(f"style {path.parent.name!r} is missing {', '.join(missing)}")
    if data["status"] not in {"approved", "experimental"}:
        raise AssetError(f"style {path.parent.name!r} has unknown status {data['status']!r}")
    refs = tuple((path.parent / str(ref)).resolve() for ref in data.get("refs", []))
    return StyleCard(
        key=path.parent.name,
        name=str(data["name"]),
        title=str(data.get("title") or data["name"]),
        prompt_block=str(data["prompt_block"]).strip(),
        negative_block=str(data["negative_block"]).strip(),
        staging_rules=str(data.get("staging_rules", "")).strip(),
        refs=refs,
        tested_on=tuple(str(item) for item in data["tested_on"]),
        licence=str(data["licence"]),
        status=str(data["status"]),
        source=source,
    )


def _kit(path: Path, source: str) -> CharacterKit:
    data = _read(path)
    missing = [name for name in KIT_FIELDS if name not in data]
    if missing:
        raise AssetError(f"kit {path.parent.name!r} is missing {', '.join(missing)}")
    sheets = data["sheets"]
    if not isinstance(sheets, dict) or not sheets:
        raise AssetError(f"kit {path.parent.name!r} needs at least one sheet")
    return CharacterKit(
        key=path.parent.name,
        name=str(data["name"]),
        role=str(data.get("role", "cast")),
        description=str(data.get("description", "")),
        sheets={str(style): (path.parent / str(sheet)).expanduser().resolve() for style, sheet in sheets.items()},
        real_person=bool(data.get("real_person", False)),
        owner=bool(data.get("owner", False)),
        public_consent=bool(data.get("public_consent", False)),
        licence=str(data["licence"]),
        source=source,
    )


def _scan(roots: Iterable[tuple[Path, str]], filename: str, build) -> dict[str, Any]:
    found: dict[str, Any] = {}
    for root, source in roots:
        if not root.is_dir():
            continue
        for card in sorted(root.glob(f"*/{filename}")):
            found[card.parent.name] = build(card, source)  # later roots override
    return found


def load_styles(builtin_root: Path, user_root: Path | None = None) -> dict[str, StyleCard]:
    roots = [(Path(builtin_root), "builtin")]
    if user_root is not None:
        roots.append((Path(user_root), "user"))
    return _scan(roots, "style.json", _style)


def load_kits(builtin_root: Path, user_root: Path | None = None) -> dict[str, CharacterKit]:
    roots = [(Path(builtin_root), "builtin")]
    if user_root is not None:
        roots.append((Path(user_root), "user"))
    return _scan(roots, "kit.json", _kit)


def sheet_digest(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@dataclass
class Approvals:
    """Owner approvals of kit sheets, keyed ``<kit>:<style>`` -> sheet SHA-256."""

    path: Path
    entries: dict[str, str] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> "Approvals":
        path = Path(path)
        if not path.exists():
            return cls(path)
        data = _read(path)
        return cls(path, {str(key): str(value) for key, value in data.get("approved", {}).items()})

    def approve(self, kit: CharacterKit, style: str) -> str:
        digest = sheet_digest(kit.sheet(style))
        self.entries[f"{kit.key}:{style}"] = digest
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"approved": self.entries}, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        tmp.replace(self.path)
        return digest

    def is_approved(self, kit: CharacterKit, style: str) -> bool:
        recorded = self.entries.get(f"{kit.key}:{style}")
        return bool(recorded) and recorded == sheet_digest(kit.sheet(style))


def clear_to_render(
    *,
    style: StyleCard,
    kits: Iterable[CharacterKit],
    approvals: Approvals,
    public: bool,
    allow_untested_style: bool = False,
) -> list[str]:
    """Every reason this cast may not be rendered in this style. Empty means cleared."""
    problems: list[str] = []
    if not style.tested and not allow_untested_style:
        problems.append(f"style {style.key!r} is {style.status} and untested; run a bake-off first")
    for kit in kits:
        try:
            kit.sheet(style.key)
        except AssetError as exc:
            problems.append(str(exc))
            continue
        if not approvals.is_approved(kit, style.key):
            problems.append(f"kit {kit.key!r} in {style.key!r} is not approved (or its sheet changed)")
        if public and kit.real_person and not (kit.owner or kit.public_consent):
            problems.append(f"kit {kit.key!r} depicts a real person with no recorded consent for public use")
    return problems
