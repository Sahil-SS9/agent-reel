"""M2 P2: panel prompts follow the approved bake-off r2 shape."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from canon.assets import load_kits, load_styles
from canon.panel_prompt import PromptError, build_episode_requests, build_panel_request, staging_order

REPO = Path(__file__).resolve().parents[1]


def _kits(tmp_path):
    d = tmp_path / "kits" / "sahil"
    d.mkdir(parents=True)
    (d / "anime.jpg").write_bytes(b"x")
    (d / "kit.json").write_text(json.dumps({
        "name": "Sahil", "sheets": {"anime": "anime.jpg"}, "licence": "owner",
        "real_person": True, "owner": True}))
    return load_kits(REPO / "kits", tmp_path / "kits")


PANEL = {
    "id": "p1", "role": "setup", "shot": "wide", "setting": "the rig at night",
    "cast": ["Sahil", "Kensei"], "pose": "standing at the desk", "expression": "calm",
    "caption": "Sahil wants the dev-radio build audited through Phase 2.",
    "lines": [{"speaker": "Kensei", "text": "On it.", "source_event_ids": ["e1"]}],
}


def test_prompt_has_the_approved_shape(tmp_path):
    style = load_styles(REPO / "styles")["anime"]
    req = build_panel_request(PANEL, style=style, kits=_kits(tmp_path))
    p = req.prompt
    assert p.startswith("Establishing wide shot, the owner's home office:")
    assert "at night" in p.split(".")[0]
    # first speaker on the LEFT so balloons read left to right
    assert "KENSEI on the LEFT, standing at the desk, calm" in p
    assert "SAHIL on the RIGHT" in p
    assert "KENSEI is exactly as in the first reference sheet" in p
    assert "SAHIL is exactly as in the second reference sheet" in p
    assert "Draw no other people." in p
    assert "top 25 percent" in p
    assert "No text" in p
    assert req.references[0].name == "anime.jpg" and "kensei" in str(req.references[0])
    assert req.positions == {"Kensei": "LEFT", "Sahil": "RIGHT"}


def test_missing_kit_is_refused_not_drawn_generic(tmp_path):
    style = load_styles(REPO / "styles")["anime"]
    panel = dict(PANEL, cast=["Quan"], lines=[])
    with pytest.raises(PromptError, match="no character kit for 'Quan'"):
        build_panel_request(panel, style=style, kits=_kits(tmp_path))


def test_more_than_three_characters_is_refused(tmp_path):
    style = load_styles(REPO / "styles")["anime"]
    panel = dict(PANEL, cast=["Sahil", "Kensei", "The Orphans", "Quan"], lines=[])
    with pytest.raises(PromptError, match="at most 3"):
        build_panel_request(panel, style=style, kits=_kits(tmp_path))


def test_episode_collects_problems_per_panel(tmp_path):
    style = load_styles(REPO / "styles")["anime"]
    ir = {"panels": [PANEL, dict(PANEL, id="p2", cast=["Quan"], lines=[])]}
    requests, problems = build_episode_requests(ir, style=style, kits=_kits(tmp_path))
    assert [r.panel_id for r in requests] == ["p1"]
    assert problems == ["panel p2: no character kit for 'Quan'"]


def test_staging_order_speakers_first():
    assert staging_order(PANEL) == ["Kensei", "Sahil"]


def test_named_settings_are_pinned_to_one_place(tmp_path):
    from canon.panel_prompt import describe_setting

    style = load_styles(REPO / "styles")["anime"]
    req = build_panel_request(dict(PANEL, setting="the rig, alarms implied"), style=style, kits=_kits(tmp_path))
    assert "home office" in req.prompt and "alarms implied" in req.prompt
    assert "same room" in req.prompt
    assert describe_setting("a train station") == "a train station"
