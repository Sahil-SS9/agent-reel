"""M3: action grammar in the treatment and the panel prompt, and the deck frame reaching both."""

from types import SimpleNamespace

from canon.director import DIRECTOR_PROMPT, ROLE_ACTION, direct
from canon.ideas import draw
from canon.panel_prompt import build_panel_request


def _ir() -> dict:
    return {
        "logline": "A true story",
        "episode_id": "ep1",
        "panels": [
            {"id": "p1", "role": "setup", "cast": ["Sahil"], "caption": "", "lines": [], "setting": "the rig"},
            {"id": "p2", "role": "climax", "cast": ["Sahil"], "caption": "", "lines": [], "setting": "the rig"},
        ],
    }


def test_every_rule_panel_carries_motion_reaction_and_camera():
    treatment = direct(_ir(), story_text="the build failed, then it passed")
    for panel in treatment.panels.values():
        assert panel.motion and panel.reaction and panel.camera
    # The climax is where something is struck; a calm setup has nothing to break yet.
    assert treatment.panels["p2"].impact
    assert treatment.panels["p2"].role in ROLE_ACTION


def test_the_deck_frame_decides_the_world_and_the_villain():
    frame = draw("Sahil", 4)
    treatment = direct(_ir(), story_text="a failure and a fix", frame=frame)
    assert treatment.world == frame["world"]["label"]
    assert treatment.villain_look == frame["villain"]["look"]
    assert treatment.panels["p1"].location == frame["world"]["label"]


def test_two_different_chapters_get_different_treatments():
    one = direct(_ir(), story_text="a failure and a fix", frame=draw("Sahil", 1))
    two = direct(_ir(), story_text="a failure and a fix", frame=draw("Sahil", 2))
    assert (one.world, one.villain_name) != (two.world, two.villain_name)


def test_the_director_prompt_asks_for_action_not_poses():
    lowered = DIRECTOR_PROMPT.lower()
    for word in ("frozen moment of action", "motion", "impact", "reaction", "camera"):
        assert word in lowered
    assert "full-bleed impact frame" in lowered


def test_the_panel_prompt_carries_the_action_grammar():
    treatment = direct(_ir(), story_text="a failure and a fix", frame=draw("Sahil", 3))
    style = SimpleNamespace(
        name="anime",
        prompt_block="anime style",
        staging_rules="",
        negative_block="no text",
        raw_template="",
        key="anime",
    )
    request = build_panel_request(
        {"id": "p2", "role": "climax", "cast": [], "caption": "", "lines": [], "setting": "the rig"},
        style=style,
        kits={},
        treatment=treatment.panels["p2"],
    )
    text = request["prompt"] if isinstance(request, dict) else str(request)
    for label in ("ACTION:", "MOTION:", "IMPACT:", "REACTION:", "CAMERA:", "Full-bleed impact frame"):
        assert label in text
