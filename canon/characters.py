"""Characters: the Hermes Multiverse and your own (owner decision V11, 25/10/26).

Three things a user can do:

1. **Import Multiverse characters.** The Hermes Multiverse is open for community use.
   Each character's ``manifest.json`` lists its published style sheets. Full-resolution
   sheets come from the release ZIP (unpacked); the in-repo WebP previews are the fallback.
   Every sheet is checked against its manifest SHA-256 before it is used.
2. **Create your own character** through a short set-up exercise: who it is, how it looks
   and talks. The answers become a reference-sheet prompt (and a voice line for the writer).
   The sheet is generated through the user's image source and must be approved before any
   render.
3. **Offer it to the Multiverse.** This builds a contribution bundle in the Multiverse's own
   layout (manifest, README, WebP preview) and a pull-request description. Nothing is pushed:
   the user runs the printed commands themselves.

Harness-free: image generation is an injected callable.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from PIL import Image

SETUP_QUESTIONS: tuple[tuple[str, str], ...] = (
    ("name", "What is the character called?"),
    ("who", "Who are they? (e.g. 'me, the builder', 'my AI agent', 'a rival bot') "),
    ("look", "How do they look? Face, hair, build, age range."),
    ("outfit", "What do they wear? Signature clothes or armour."),
    ("colours", "Their main colours (2-4)."),
    ("signature", "One signature item or feature people remember (optional)."),
    ("voice", "How do they talk? (e.g. 'calm and dry', 'loud and excitable')"),
)

#: Multiverse style names that match a built-in reel style key.
STYLE_ALIASES = {"anime": "anime", "ink-pen-sketch": "ink-pen-sketch"}


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-") or "character"


def sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# ------------------------------------------------------------------ import
@dataclass
class ImportReport:
    imported: list[str] = field(default_factory=list)
    skipped: dict[str, str] = field(default_factory=dict)
    sheets: dict[str, list[str]] = field(default_factory=dict)
    previews_used: list[str] = field(default_factory=list)


def import_multiverse(
    repo: Path,
    kits_dir: Path,
    *,
    full_res: Path | None = None,
    only: Sequence[str] = (),
    allow_previews: bool = True,
) -> ImportReport:
    """Copy Multiverse characters into ``kits_dir`` as character kits."""
    repo, kits_dir = Path(repo).expanduser(), Path(kits_dir).expanduser()
    report = ImportReport()
    characters = repo / "characters"
    if not characters.is_dir():
        raise FileNotFoundError(f"not a Hermes Multiverse checkout (no characters/): {repo}")
    pending = _pending_slugs(repo / "manifests" / "pending.json")
    for manifest_path in sorted(characters.glob("*/manifest.json")):
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        slug = str(manifest.get("slug") or manifest_path.parent.name)
        if only and slug not in only:
            continue
        styles = manifest.get("published_styles") or []
        if not styles:
            report.skipped[slug] = "documentation only (no published style sheets)"
            continue
        # QAR-M2-03: only characters open for community use are imported. Pending creator
        # approval and third-party associations stay out until the Multiverse clears them.
        rights = str(manifest.get("rights_status") or "")
        if slug in pending or rights != OPEN_RIGHTS:
            report.skipped[slug] = f"rights not cleared for use ({rights or 'unknown'}{', pending' if slug in pending else ''})"
            continue
        target = kits_dir / slug
        sheets: dict[str, str] = {}
        for entry in styles:
            style = str(entry.get("style") or "")
            full = entry.get("full_resolution") or {}
            preview = entry.get("preview") or {}
            source: Path | None = None
            if full_res is not None and full.get("archive_path"):
                candidate = Path(full_res).expanduser() / str(full["archive_path"])
                if candidate.is_file() and sha256(candidate) == full.get("sha256"):
                    source = candidate
            if source is None and allow_previews and preview.get("path"):
                candidate = repo / str(preview["path"])
                if candidate.is_file() and sha256(candidate) == preview.get("sha256"):
                    source = candidate
                    report.previews_used.append(f"{slug}:{style}")
            if source is None:
                continue
            target.mkdir(parents=True, exist_ok=True)
            key = STYLE_ALIASES.get(style, style)
            copy = target / f"{key}{source.suffix.lower()}"
            copy.write_bytes(source.read_bytes())
            sheets[key] = copy.name
        if not sheets:
            report.skipped[slug] = "no sheet matched its manifest checksum"
            continue
        description = _readme_summary(manifest_path.parent / "README.md")
        kit = {
            "name": str(manifest.get("display_name") or slug),
            "role": "cast",
            "description": description,
            "sheets": sheets,
            "real_person": True,
            "owner": False,
            # V11: the Multiverse owner opened it for community use (25/10/26). The repo's
            # manifest still says rights "unknown-not-cleared"; both are recorded.
            "public_consent": True,  # rights_status == community-use (checked above)
            "licence": "Hermes Multiverse, community use with credit (rights_status: community-use)",
            "source": "hermes-multiverse",
        }
        (target / "kit.json").write_text(json.dumps(kit, indent=1) + "\n", encoding="utf-8")
        report.imported.append(slug)
        report.sheets[slug] = sorted(sheets)
    return report


#: The Multiverse rights value that clears a character for use (NOTICE.md, 25/10/26).
OPEN_RIGHTS = "community-use"


def _pending_slugs(path: Path) -> set[str]:
    """Slugs the Multiverse holds back: rights pending, or documentation only."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    held = (data.get("rights_pending") or []) + (data.get("documentation_only") or [])
    return {str(item["slug"]) for item in held if isinstance(item, dict) and item.get("slug")}


def _readme_summary(path: Path) -> str:
    if not path.is_file():
        return ""
    lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines()]
    prose = [line for line in lines if line and not line.startswith(("#", "!", "|", "-", "<", ">"))]
    return " ".join(prose[:2])[:300]


# ------------------------------------------------------------------ create
def sheet_prompt(answers: Mapping[str, str], style_block: str) -> str:
    """The reference-sheet prompt for a new character, from the set-up answers."""
    name = answers.get("name", "the character")
    bits = [
        f"Character reference sheet for an original comic character called {name}",
        f"({answers['who']})" if answers.get("who") else "",
        f". Appearance: {answers['look']}." if answers.get("look") else ".",
        f" Outfit: {answers['outfit']}." if answers.get("outfit") else "",
        f" Main colours: {answers['colours']}." if answers.get("colours") else "",
        f" Signature: {answers['signature']}." if answers.get("signature") else "",
        " Show a front view, a three-quarter view and a side view, plus three facial "
        "expressions (calm, determined, laughing), on a plain light background, evenly lit. "
        "Keep proportions and colours identical across every view. ",
        style_block,
        " No text, labels, names or watermarks.",
    ]
    return "".join(bits).strip()


def create_character(
    answers: Mapping[str, str],
    kits_dir: Path,
    *,
    style: str,
    style_block: str,
    generate: Callable[[str, Sequence[Path], str], Path] | None,
    photo: Path | None = None,
    is_owner: bool = False,
) -> dict[str, Any]:
    """Make a kit from the set-up answers. ``generate=None`` writes the prompt only (dry run)."""
    name = str(answers.get("name") or "").strip()
    if not name:
        raise ValueError("a character needs a name")
    slug = slugify(name)
    target = Path(kits_dir).expanduser() / slug
    target.mkdir(parents=True, exist_ok=True)
    prompt = sheet_prompt(answers, style_block)
    if photo is not None and not is_owner:
        raise ValueError("a photo likeness is only allowed for yourself (pass --owner)")
    (target / f"{style}.prompt.txt").write_text(prompt + "\n", encoding="utf-8")
    kit_path = target / "kit.json"
    kit: dict[str, Any] = json.loads(kit_path.read_text(encoding="utf-8")) if kit_path.is_file() else {}
    kit.update({
        "name": name,
        "role": "cast",
        "description": " ".join(str(answers.get(k, "")) for k in ("look", "outfit", "colours", "signature") if answers.get(k)).strip(),
        "voice": str(answers.get("voice", "")),
        "real_person": bool(photo is not None or is_owner),
        "owner": bool(is_owner),
        "public_consent": bool(is_owner),
        "licence": "created by the user with their own image source",
        "source": "user-created",
        "setup_answers": {k: str(v) for k, v in answers.items()},
    })
    kit.setdefault("sheets", {})
    produced = None
    if generate is not None:
        references = [Path(photo)] if photo is not None else []
        produced = generate(prompt, references, "landscape")
        sheet = target / f"{style}{Path(produced).suffix or '.png'}"
        sheet.write_bytes(Path(produced).read_bytes())
        kit["sheets"][style] = sheet.name
    kit_path.write_text(json.dumps(kit, indent=1) + "\n", encoding="utf-8")
    return {"slug": slug, "kit": str(kit_path), "prompt": prompt, "sheet": kit["sheets"].get(style, ""), "generated": produced is not None}


# ------------------------------------------------------------------ contribute
def contribution_bundle(kit_dir: Path, out_dir: Path, *, contributor: str = "") -> dict[str, Any]:
    """A Multiverse-shaped contribution for one user-created kit, plus a PR description.

    Follows the Multiverse CONTRIBUTING rules: no prompts, no local paths, no source images in
    Git (only a sanitised WebP preview); full-resolution sheets go through the maintainers'
    private review path.
    """
    kit_dir = Path(kit_dir).expanduser()
    kit = json.loads((kit_dir / "kit.json").read_text(encoding="utf-8"))
    slug = slugify(kit.get("name") or kit_dir.name)
    root = Path(out_dir).expanduser() / slug
    previews = root / "previews" / slug
    character = root / "characters" / slug
    previews.mkdir(parents=True, exist_ok=True)
    character.mkdir(parents=True, exist_ok=True)
    published = []
    for style, sheet_name in sorted((kit.get("sheets") or {}).items()):
        sheet = kit_dir / sheet_name
        if not sheet.is_file():
            continue
        image = Image.open(sheet).convert("RGB")
        image.thumbnail((960, 640))
        preview = previews / f"{style}.webp"
        image.save(preview, "WEBP", quality=82, method=6)  # re-encoded: no source metadata
        published.append({"style": style, "preview": {
            "path": f"previews/{slug}/{style}.webp", "sha256": sha256(preview),
            "width": image.size[0], "height": image.size[1]}})
    if not published:
        raise ValueError("the kit has no sheets to contribute; create one first")
    manifest = {
        "schema_version": 1, "slug": slug, "display_name": kit.get("name", slug), "aliases": [],
        "design_status": "proposed", "rights_status": "contributed-by-creator",
        "target_styles": [p["style"] for p in published], "published_styles": published,
    }
    (character / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8")
    description = kit.get("description") or "An original character."
    (character / "README.md").write_text(
        f"# {kit.get('name', slug)}\n\n{description}\n\nVoice: {kit.get('voice') or 'not set'}.\n\n"
        "Fan-fictional character description, not a biography. Contributed by its creator for "
        "community use in the Hermes Multiverse.\n", encoding="utf-8")
    pr = (
        f"# Add {kit.get('name', slug)} to the Hermes Multiverse\n\n"
        f"- New character: `{slug}` ({len(published)} style preview(s): {', '.join(p['style'] for p in published)})\n"
        f"- Contributed by: {contributor or 'the creator'}; I made this character and agree to community use.\n"
        "- Full-resolution sheets: available through the private maintainer review path.\n"
        "- Checked: no prompts, logs, credentials or local paths are included.\n\n"
        "Before opening the PR, from your Multiverse fork (BUNDLE = the folder holding this file):\n\n"
        f"```\ngit checkout -b add-{slug}\ncp -r BUNDLE/characters/{slug} characters/\n"
        f"mkdir -p previews/{slug} && cp BUNDLE/previews/{slug}/*.webp previews/{slug}/\n"
        "python3 scripts/verify_repository.py --root .\n"
        f"git add characters/{slug} previews/{slug} && git commit -m \"feat: add {slug}\"\n"
        f"git push origin add-{slug}   # then open the PR on GitHub\n```\n"
    )
    (root / "PULL_REQUEST.md").write_text(pr, encoding="utf-8")
    return {"bundle": str(root), "slug": slug, "previews": len(published), "pr": str(root / "PULL_REQUEST.md")}


__all__ = ("SETUP_QUESTIONS", "contribution_bundle", "create_character", "import_multiverse", "sheet_prompt")
