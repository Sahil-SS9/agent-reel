"""V11 (25/10/26): Multiverse import, character set-up, contribution bundle."""

import hashlib
import json
from pathlib import Path

import pytest
from PIL import Image

from canon.assets import load_kits
from canon.characters import contribution_bundle, create_character, import_multiverse, sheet_prompt


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _multiverse(tmp_path):
    repo = tmp_path / "mv"
    (repo / "previews" / "nova").mkdir(parents=True)
    Image.new("RGB", (96, 64), "blue").save(repo / "previews" / "nova" / "anime.webp")
    Image.new("RGB", (96, 64), "green").save(repo / "previews" / "nova" / "gothic.webp")
    full = tmp_path / "full" / "characters" / "nova" / "styles" / "anime"
    full.mkdir(parents=True)
    Image.new("RGB", (300, 200), "red").save(full / "nova__sheet__anime__v01.png")
    (repo / "characters" / "nova").mkdir(parents=True)
    (repo / "characters" / "nova" / "README.md").write_text("# Nova\n\nA neon courier with a cat.\n")
    (repo / "characters" / "nova" / "manifest.json").write_text(json.dumps({
        "slug": "nova", "display_name": "Nova", "rights_status": "community-use",
        "published_styles": [
            {"style": "anime", "preview": {"path": "previews/nova/anime.webp", "sha256": _sha(repo / "previews/nova/anime.webp")},
             "full_resolution": {"archive_path": "characters/nova/styles/anime/nova__sheet__anime__v01.png", "sha256": _sha(full / "nova__sheet__anime__v01.png")}},
            {"style": "gothic", "preview": {"path": "previews/nova/gothic.webp", "sha256": "0" * 64}},
        ]}))
    for slug, rights in (("pendo", "approval-pending-per-profile"), ("minion", "third-party-association-not-reusable")):
        (repo / "characters" / slug).mkdir(parents=True)
        (repo / "characters" / slug / "manifest.json").write_text(json.dumps({
            "slug": slug, "rights_status": rights,
            "published_styles": [{"style": "anime", "preview": {"path": "previews/nova/anime.webp", "sha256": _sha(repo / "previews/nova/anime.webp")}}]}))
    (repo / "manifests").mkdir()
    (repo / "manifests" / "pending.json").write_text(json.dumps({"rights_pending": [{"slug": "pendo"}], "documentation_only": [{"slug": "ghost"}]}))
    (repo / "characters" / "ghost").mkdir(parents=True)
    (repo / "characters" / "ghost" / "manifest.json").write_text(json.dumps({"slug": "ghost", "published_styles": []}))
    return repo, tmp_path / "full"


def test_import_prefers_checked_full_res_and_skips_bad_checksums(tmp_path):
    repo, full = _multiverse(tmp_path)
    report = import_multiverse(repo, tmp_path / "kits", full_res=full)
    assert report.imported == ["nova"] and report.sheets["nova"] == ["anime"]  # gothic checksum wrong
    assert "documentation only" in report.skipped["ghost"]
    assert "pending" in report.skipped["pendo"] and "not cleared" in report.skipped["minion"]  # QAR-M2-03
    assert not (tmp_path / "kits" / "pendo").exists() and not (tmp_path / "kits" / "minion").exists()
    kits = load_kits(tmp_path / "none", tmp_path / "kits")
    nova = kits["nova"]
    assert nova.public_consent and nova.real_person and "Multiverse" in nova.licence
    assert Image.open(nova.sheets["anime"]).size == (300, 200)
    assert "neon courier" in nova.description


def test_import_falls_back_to_previews(tmp_path):
    repo, _full = _multiverse(tmp_path)
    report = import_multiverse(repo, tmp_path / "kits")
    assert report.previews_used == ["nova:anime"]


def test_create_character_dry_run_and_generated(tmp_path):
    answers = {"name": "Captain Byte", "look": "tall, silver hair", "outfit": "long red coat", "voice": "booming and theatrical"}
    dry = create_character(answers, tmp_path / "kits", style="anime", style_block="Anime style.", generate=None)
    assert not dry["generated"] and "Captain Byte" in dry["prompt"] and "No text" in dry["prompt"]
    sheet = tmp_path / "sheet.png"
    Image.new("RGB", (64, 64), "white").save(sheet)
    out = create_character(answers, tmp_path / "kits", style="anime", style_block="Anime style.", generate=lambda p, r, a: sheet)
    kit = load_kits(tmp_path / "none", tmp_path / "kits")["captain-byte"]
    assert out["generated"] and kit.voice == "booming and theatrical" and "anime" in kit.sheets
    assert not kit.real_person and not kit.public_consent


def test_photo_likeness_only_for_yourself(tmp_path):
    with pytest.raises(ValueError, match="yourself"):
        create_character({"name": "X"}, tmp_path, style="anime", style_block="", generate=None, photo=tmp_path / "p.jpg")


def test_contribution_bundle_follows_multiverse_rules(tmp_path):
    sheet = tmp_path / "sheet.png"
    Image.new("RGB", (1536, 1024), "white").save(sheet)
    create_character({"name": "Captain Byte", "look": "tall"}, tmp_path / "kits", style="anime", style_block="", generate=lambda p, r, a: sheet)
    result = contribution_bundle(tmp_path / "kits" / "captain-byte", tmp_path / "out", contributor="@me")
    bundle = Path(result["bundle"])
    manifest = json.loads((bundle / "characters" / "captain-byte" / "manifest.json").read_text())
    preview = bundle / manifest["published_styles"][0]["preview"]["path"]
    assert preview.suffix == ".webp" and Image.open(preview).size[0] <= 960
    assert manifest["published_styles"][0]["preview"]["sha256"] == _sha(preview)
    assert not list(bundle.rglob("*.prompt.txt")) and not list(bundle.rglob("*.png"))  # no prompts, no source images
    assert "git push" in (bundle / "PULL_REQUEST.md").read_text() and "@me" in (bundle / "PULL_REQUEST.md").read_text()
    # QAR-M2-02: no local paths anywhere in the bundle's text files
    import re as _re
    local = _re.compile(r"(/home/|/Users/|/tmp/|/root/|[A-Za-z]:\\\\|file://|" + _re.escape(str(tmp_path)) + ")")
    for path in bundle.rglob("*"):
        if path.suffix in {".md", ".json", ".txt"}:
            assert not local.search(path.read_text()), path


def test_sheet_prompt_shape():
    text = sheet_prompt({"name": "Z", "colours": "teal, gold"}, "Ink style.")
    assert "three-quarter" in text and "teal, gold" in text and text.endswith("watermarks.")
