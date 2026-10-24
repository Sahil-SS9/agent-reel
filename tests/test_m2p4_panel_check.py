"""M2 P4: panel auto-check interpretation."""

from __future__ import annotations

import json

from adapters.hermes.vision import VisionError, host_vision
from canon.panel_check import check_question, interpret

GOOD = {
    "on_model": {"Sahil": True, "Kensei": True},
    "extra_people": 0,
    "text_in_image": False,
    "heads": {"Sahil": [0.25, 0.37, 0.35, 0.52], "Kensei": [0.75, 0.12, 0.86, 0.31]},
    "free": [[0.15, 0.01, 0.75, 0.27]],
    "keep_out": [[0.4, 0.5, 0.6, 0.7]],
}


def test_good_panel_passes():
    check = interpret("p1", ["Sahil", "Kensei"], GOOD)
    assert check.passed, check.problems
    assert check.heads["Kensei"] == [0.75, 0.12, 0.86, 0.31]


def test_off_model_extra_people_and_text_fail():
    bad = dict(GOOD, on_model={"Sahil": True, "Kensei": False}, extra_people=1, text_in_image=True)
    check = interpret("p1", ["Sahil", "Kensei"], bad)
    assert not check.passed
    joined = " ".join(check.problems)
    assert "Kensei is off-model" in joined and "unscripted" in joined and "text drawn" in joined


def test_missing_character_verdict_fails_closed():
    check = interpret("p1", ["Sahil", "Kensei"], dict(GOOD, on_model={"Sahil": True}))
    assert "Kensei is off-model or not found" in check.problems


def test_coarse_head_box_is_re_asked_tightly():
    coarse = dict(GOOD, heads={"Sahil": [0.0, 0.0, 0.5, 0.6], "Kensei": GOOD["heads"]["Kensei"]})
    asked = []

    def tighten(name):
        asked.append(name)
        return {"head": [0.2, 0.3, 0.28, 0.42]}

    check = interpret("p1", ["Sahil", "Kensei"], coarse, tighten=tighten)
    assert asked == ["Sahil"] and check.heads["Sahil"] == [0.2, 0.3, 0.28, 0.42]


def test_bad_boxes_are_dropped_and_reported():
    check = interpret("p1", ["Sahil"], {"on_model": {"Sahil": True}, "heads": {"Sahil": [1, 1, 1, 1]}, "free": []})
    assert "no head box for Sahil" in check.problems and "no free space for balloons reported" in check.problems


def test_question_names_the_cast():
    q = check_question(["Sahil", "Kensei"], {"Kensei": "visor, katana"})
    assert "Sahil, Kensei" in q and "Kensei: visor, katana" in q


def test_host_vision_parses_prefixed_json(tmp_path):
    def dispatch(name, args):
        return json.dumps({"success": True, "analysis": "[scaled to 1024px] " + json.dumps(GOOD)})

    assert host_vision(dispatch)(tmp_path / "p.png", "q")["extra_people"] == 0

    def broken(name, args):
        return json.dumps({"success": False, "analysis": "403"})

    try:
        host_vision(broken)(tmp_path / "p.png", "q")
    except VisionError:
        pass
    else:
        raise AssertionError
