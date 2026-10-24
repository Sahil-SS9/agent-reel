"""V1/V3 director: dramatised pictures, words untouched, craft rules enforced."""

import copy
from pathlib import Path

from canon.director import direct, no_text, pick_villain

IR = {
    "logline": "The queue that would not drain",
    "panels": [
        {"id": f"p{i}", "role": role, "caption": f"cap {i}", "lines": [], "cast": ["Kensei"]}
        for i, role in enumerate(["setup", "hidden_problem", "diagnosis", "climax", "aftermath", "win"], 1)
    ],
}


def test_rules_treatment_has_villain_and_varied_shots():
    t = direct(IR, story_text="the worker process was orphaned and the job failed")
    assert t.villain_name == "The Orphans"
    shots = [(p.shot, p.angle) for p in t.panels.values()]
    assert all(a != b for a, b in zip(shots, shots[1:]))
    climax = t.panels["p4"]
    assert climax.angle in {"low", "dutch"} and climax.shot in {"full", "long"}
    assert t.panels["p1"].shot in {"extreme-long", "long"}


def test_director_never_edits_words():
    ir = copy.deepcopy(IR)
    direct(ir, story_text="rate limit hit", complete_json=lambda **k: {"panels": []})
    assert ir == IR


def test_model_output_is_repaired_to_the_rules():
    def model(**_kwargs):
        return {"villain": {"name": "Rate Wraith", "look": "a ghost holding a sign that says STOP"},
                "world": "a frozen citadel",
                "panels": [{"id": p["id"], "location": "a sign reading \"429\" over a bridge", "action": "run",
                            "villain_presence": "attacking", "shot": "medium", "angle": "eye"} for p in IR["panels"]]}
    t = direct(IR, story_text="", complete_json=model)
    assert t.source == "model"
    assert "STOP" not in t.villain_look and "429" not in t.panels["p1"].location
    shots = [(p.shot, p.angle) for p in t.panels.values()]
    assert all(a != b for a, b in zip(shots, shots[1:]))
    assert t.panels["p4"].angle in {"low", "dutch"}


def test_model_failure_falls_back_to_rules():
    def broken(**_kwargs):
        raise RuntimeError("down")
    t = direct(IR, story_text="tests failed", complete_json=broken)
    assert t.source == "rules" and t.panels


def test_villain_library_and_text_stripping():
    assert pick_villain("hit the usage limit")[0] == "The Toll Wraith"
    assert pick_villain("nothing here")[0] == "The Static"
    assert "says" not in no_text("a banner that says HELLO over the door")


def test_panel_prompt_uses_treatment_and_villain_sheet(tmp_path):
    from canon.assets import load_kits, load_styles
    from canon.panel_prompt import build_episode_requests

    repo = Path(__file__).resolve().parents[1]
    style = load_styles(repo / "styles")["anime"]
    kits = load_kits(repo / "kits", tmp_path / "kits")
    ir = copy.deepcopy(IR)
    sheet = tmp_path / "villain.png"
    sheet.write_bytes(b"x")
    t = direct(ir, story_text="process orphaned")
    reqs, problems = build_episode_requests(ir, style=style, kits=kits, treatment=t, villain=(t.villain_name, t.villain_look, sheet))
    assert not problems
    climax = next(r for r in reqs if r.panel_id == "p4")
    assert "low-angle" in climax.prompt and "THE ORPHANS" in climax.prompt
    assert Path(sheet) in climax.references and "The Orphans" in climax.cast
    setup = next(r for r in reqs if r.panel_id == "p1")
    assert "THE ORPHANS" not in setup.prompt  # absent in the setup
    assert "never write it" in climax.prompt
