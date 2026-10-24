"""M2 P1: style cards and character kits."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from canon.assets import Approvals, AssetError, clear_to_render, load_kits, load_styles

REPO = Path(__file__).resolve().parents[1]


def test_builtin_styles_load_and_two_are_approved():
    styles = load_styles(REPO / "styles")
    assert {"anime", "ink-pen-sketch", "noir-webtoon"} <= set(styles)
    assert styles["anime"].tested and styles["ink-pen-sketch"].tested
    assert not styles["noir-webtoon"].tested
    for ref in styles["anime"].refs:
        assert ref.is_file()


def test_builtin_kits_have_sheets_for_both_approved_styles():
    kits = load_kits(REPO / "kits")
    for key in ("kensei", "the-orphans"):
        for style in ("anime", "ink-pen-sketch"):
            assert kits[key].sheet(style).is_file()
        assert not kits[key].real_person


def _user_kit(root: Path, key: str, **fields) -> Path:
    d = root / key
    d.mkdir(parents=True)
    (d / "anime.jpg").write_bytes(b"sheet-v1")
    data = {"name": key.title(), "sheets": {"anime": "anime.jpg"}, "licence": "test"}
    data.update(fields)
    (d / "kit.json").write_text(json.dumps(data))
    return d


def test_unapproved_kit_is_refused_and_approval_clears_it(tmp_path):
    styles = load_styles(REPO / "styles")
    _user_kit(tmp_path / "kits", "pat")
    kit = load_kits(REPO / "kits", tmp_path / "kits")["pat"]
    approvals = Approvals.load(tmp_path / "approvals.json")
    problems = clear_to_render(style=styles["anime"], kits=[kit], approvals=approvals, public=False)
    assert any("not approved" in p for p in problems)
    approvals.approve(kit, "anime")
    again = Approvals.load(tmp_path / "approvals.json")
    assert clear_to_render(style=styles["anime"], kits=[kit], approvals=again, public=False) == []


def test_changing_the_sheet_withdraws_the_approval(tmp_path):
    styles = load_styles(REPO / "styles")
    d = _user_kit(tmp_path / "kits", "pat")
    kit = load_kits(REPO / "kits", tmp_path / "kits")["pat"]
    approvals = Approvals.load(tmp_path / "approvals.json")
    approvals.approve(kit, "anime")
    (d / "anime.jpg").write_bytes(b"sheet-v2")
    assert any("not approved" in p for p in clear_to_render(
        style=styles["anime"], kits=[kit], approvals=approvals, public=False))


@pytest.mark.parametrize(
    "fields, public, blocked",
    [
        ({"real_person": True}, True, True),
        ({"real_person": True}, False, False),
        ({"real_person": True, "public_consent": True}, True, False),
        ({"real_person": True, "owner": True}, True, False),
    ],
)
def test_real_people_need_consent_for_public_renders(tmp_path, fields, public, blocked):
    styles = load_styles(REPO / "styles")
    _user_kit(tmp_path / "kits", "pat", **fields)
    kit = load_kits(REPO / "kits", tmp_path / "kits")["pat"]
    approvals = Approvals.load(tmp_path / "approvals.json")
    approvals.approve(kit, "anime")
    problems = clear_to_render(style=styles["anime"], kits=[kit], approvals=approvals, public=public)
    assert bool([p for p in problems if "consent" in p]) is blocked


def test_experimental_style_needs_an_explicit_opt_in(tmp_path):
    styles = load_styles(REPO / "styles")
    assert any("untested" in p for p in clear_to_render(
        style=styles["noir-webtoon"], kits=[], approvals=Approvals(tmp_path / "a.json"), public=False))
    assert clear_to_render(style=styles["noir-webtoon"], kits=[], approvals=Approvals(tmp_path / "a.json"),
                           public=False, allow_untested_style=True) == []


def test_user_style_overrides_builtin_and_bad_cards_are_refused(tmp_path):
    user = tmp_path / "styles"
    (user / "anime").mkdir(parents=True)
    (user / "anime" / "style.json").write_text(json.dumps({
        "name": "anime", "prompt_block": "mine", "negative_block": "no text", "tested_on": [],
        "licence": "mine", "status": "experimental"}))
    assert load_styles(REPO / "styles", user)["anime"].source == "user"
    (user / "broken").mkdir()
    (user / "broken" / "style.json").write_text(json.dumps({"name": "broken"}))
    with pytest.raises(AssetError):
        load_styles(REPO / "styles", user)
