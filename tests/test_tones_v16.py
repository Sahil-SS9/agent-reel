"""V16 (25/10/26): selectable and blended story tones."""

import pytest

from canon.director import direct
from canon.episode import LLMDialogueWriter
from canon.tones import auto_tone, parse_tone


def test_single_blend_and_weights():
    assert parse_tone("comical").label == "comical"
    blend = parse_tone("comical+serious")
    assert blend.parts == (("comical", 50), ("serious", 50)) and "blend" in blend.writer_text()
    weighted = parse_tone("comical:70,serious:30")
    assert weighted.parts == (("comical", 70), ("serious", 30)) and "70% comical" in weighted.writer_text()
    assert parse_tone("").label == "witty"
    with pytest.raises(ValueError, match="unknown tone"):
        parse_tone("grimdark")


def test_auto_tone_follows_the_story():
    assert auto_tone(drama=6, finished=True).label == "epic 50% + comical 50%"
    assert auto_tone(drama=3, finished=False).parts[0][0] == "serious"
    assert auto_tone(drama=0, finished=True).parts[0][0] == "wholesome"
    assert auto_tone(drama=0, finished=False).source == "auto"


def test_writer_receives_tone():
    seen = []

    class Model:
        def complete_json(self, *, prompt, payload, **_k):
            seen.append((prompt, payload))
            return {"panels": [{"key": "setup", "caption": "", "lines": [{"speaker": "Sahil", "text": "Right."}]}]}

    LLMDialogueWriter(Model(), ["default"], story={"tone": parse_tone("comical").writer_text(), "synopsis": "s"}).write(
        [{"role": "setup", "key": "setup", "speakers": ["Sahil"]}])
    assert "comic timing" in seen[0][1]["tone"] and "TONE" in seen[0][0]


def test_director_tone_reaches_every_panel_prompt(tmp_path):
    import copy
    from pathlib import Path

    from canon.assets import load_kits, load_styles
    from canon.panel_prompt import build_episode_requests

    ir = {"logline": "x", "panels": [{"id": f"p{i}", "role": r, "caption": "c", "lines": [], "cast": ["Kensei"]}
                                     for i, r in enumerate(["setup", "hidden_problem", "climax", "win"], 1)]}
    tone = parse_tone("noir").director_text()
    t = direct(copy.deepcopy(ir), story_text="crash", tone=tone)
    repo = Path(__file__).resolve().parents[1]
    reqs, problems = build_episode_requests(ir, style=load_styles(repo / "styles")["anime"], kits=load_kits(repo / "kits", tmp_path),
                                            treatment=t)
    assert not problems and all("chiaroscuro" in r.prompt for r in reqs)
