"""M2 P7: kit commands, render clearance, and the optional daily/weekly blueprints."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

from PIL import Image

from adapters.hermes.render_cli import kit_command, register_render_cli, render_command

REPO = Path(__file__).resolve().parents[1]


def _parser():
    p = argparse.ArgumentParser()
    subs = p.add_subparsers(dest="reel_action")
    register_render_cli(subs)
    return p


def test_kit_add_then_approve_then_list(tmp_path, capsys):
    sheet = tmp_path / "me.png"
    Image.new("RGB", (64, 64), "red").save(sheet)
    args = _parser().parse_args(["kit", "add", "sahil", "--name", "Sahil", "--style", "anime",
                                 "--sheet", str(sheet), "--real-person", "--owner", "--assets-dir", str(tmp_path)])
    assert kit_command(args, lambda: tmp_path) == 0
    args = _parser().parse_args(["kit", "approve", "sahil", "--style", "anime", "--assets-dir", str(tmp_path)])
    assert kit_command(args, lambda: tmp_path) == 2  # must look first
    args = _parser().parse_args(["kit", "approve", "sahil", "--style", "anime", "--yes", "--assets-dir", str(tmp_path)])
    assert kit_command(args, lambda: tmp_path) == 0
    args = _parser().parse_args(["kit", "list", "--assets-dir", str(tmp_path)])
    kit_command(args, lambda: tmp_path)
    out = capsys.readouterr().out
    assert "sahil" in out and "anime=approved" in out and "owner" in out


class Ctx:
    def __init__(self):
        self.calls = []

    def dispatch_tool(self, name, args):
        self.calls.append(name)
        raise AssertionError("no image may be generated before clearance")


def test_render_refuses_uncleared_cast_without_generating(tmp_path, capsys):
    plan = tmp_path / "plan"
    plan.mkdir()
    ir = {"logline": "T", "panels": [{"id": "p1", "shot": "wide", "cast": ["Sahil", "Kensei"], "caption": "x",
                                      "lines": [], "pose": "", "expression": "", "setting": "the rig"}]}
    (plan / "script-ir-1.json").write_text(json.dumps(ir))
    args = _parser().parse_args(["render", "--plan-dir", str(plan), "--assets-dir", str(tmp_path / "assets")])
    ctx = Ctx()
    assert render_command(args, ctx=ctx, default_dir=lambda: tmp_path) == 1
    out = capsys.readouterr().out
    assert "no character kit for 'Sahil'" in out
    assert "kit 'kensei' in 'anime' is not approved" in out
    assert ctx.calls == []


def test_blueprints_are_templates_with_the_right_schedules():
    spec = importlib.util.spec_from_file_location("reelinit", REPO / "__init__.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    seen = {}

    class BP:
        def register_automation_blueprint(self, key, **kw):
            seen[key] = kw

    module._register_blueprints(BP())
    assert seen["daily-strip"]["schedule_template"] == "{minute} {hour} * * *"
    assert seen["weekly-strip"]["schedule_template"] == "{minute} {hour} * * {dow}"
    assert [s["name"] for s in seen["weekly-strip"]["slots"]] == ["time", "day", "format", "style"]
    assert seen["monthly-book"]["schedule_template"] == "{minute} {hour} 1 * *"
    assert "hermes reel book --month" in seen["monthly-book"]["prompt_template"]
    styles = next(s for s in seen["weekly-strip"]["slots"] if s["name"] == "style")["options"]
    assert styles[0] == "anime" and "ukiyo-e-folktale" in styles and len(styles) >= 12
    for key, kw in seen.items():
        assert "Never post" in kw["prompt_template"]
        if key != "monthly-book":
            assert "--days 1" in kw["prompt_template"] or "--days 7" in kw["prompt_template"]
            assert "--format {format}" in kw["prompt_template"]

    class Old:  # host without a blueprint catalog: nothing registered, no error
        pass

    module._register_blueprints(Old())


def test_display_text_shortens_long_hashes_only():
    from adapters.hermes.render_cli import display_text

    assert display_text("committed as 1e7d3a4d0196721a98afa66b85c353862dc6ccea.") == "committed as 1e7d3a4."
    assert display_text("HEAD 1ac908d9 is clean") == "HEAD 1ac908d9 is clean"
