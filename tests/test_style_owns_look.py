"""A style owns its look: its world, its composition, its impact frame and its lettering.

There used to be one shared look underneath every style: a cyber-city default world, a
"dynamic comic-book, cinematic energy" line on every prompt, speed lines on every climax and
the same white balloons everywhere. That is why different styles looked alike.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from canon.assets import load_styles
from canon.director import WORLD_DEFAULT, direct
from canon.letterer import LetterStyle, letter_panel
from canon.panel_prompt import IMPACT_DEFAULT, build_panel_request

ROOT = Path(__file__).resolve().parents[1]
ROLES = ("setup", "hidden_problem", "diagnosis", "climax", "aftermath", "win")


def _ir():
    panels = [
        {"id": f"p{i}", "role": r, "caption": "", "lines": [], "cast": ["Sahil"]}
        for i, r in enumerate(ROLES)
    ]
    return {"logline": "x", "panels": panels}


def _style(**kwargs):
    base = {
        "name": "s",
        "key": "s",
        "prompt_block": "a style",
        "staging_rules": "",
        "negative_block": "no text",
        "raw_template": "",
    }
    return SimpleNamespace(**{**base, **kwargs})


def _prompt(style, role="climax"):
    treatment = direct(_ir(), story_text="the build failed", world=getattr(style, "world", ""))
    panel = {
        "id": "p3" if role == "climax" else "p0",
        "role": role,
        "cast": [],
        "caption": "",
        "lines": [],
        "setting": "the rig",
    }
    return build_panel_request(
        panel, style=style, kits={}, treatment=treatment.panels[panel["id"]]
    ).prompt


# --------------------------------------------------------------------------- #
# the prompt
# --------------------------------------------------------------------------- #


def test_no_shared_cinematic_layer_is_added_to_a_prompt():
    prompt = _prompt(_style())
    assert "cinematic energy" not in prompt
    assert "Dynamic comic-book" not in prompt


def test_the_impact_frame_has_no_genre_effects_unless_the_style_asks():
    assert IMPACT_DEFAULT in _prompt(_style())
    assert "speed lines" not in IMPACT_DEFAULT and "debris" not in IMPACT_DEFAULT


def test_a_style_can_own_its_composition_and_impact():
    style = _style(
        composition="Flat planes and a high horizon.", impact="A great wave sweeps the scene."
    )
    prompt = _prompt(style)
    assert "Flat planes and a high horizon." in prompt
    assert "A great wave sweeps the scene." in prompt
    assert IMPACT_DEFAULT not in prompt


def test_two_styles_give_two_different_prompts_for_the_same_panel():
    a = _prompt(_style(composition="Tight, low-key framing.", impact="A hard flash of light."))
    b = _prompt(_style(composition="Flat planes.", impact="A great wave."))
    assert a != b


# --------------------------------------------------------------------------- #
# the world
# --------------------------------------------------------------------------- #


def test_the_default_world_is_plain_not_a_cyber_city():
    for word in ("neon", "cyber", "rain", "server"):
        assert word not in WORLD_DEFAULT.lower()
    assert direct(_ir(), story_text="x").world == WORLD_DEFAULT


def test_the_director_uses_the_style_world():
    treatment = direct(_ir(), story_text="x", world="a mountain village in mist")
    assert treatment.world == "a mountain village in mist"
    assert {p.location for p in treatment.panels.values()} == {"a mountain village in mist"}


def test_the_deck_still_beats_the_style_world():
    frame = {
        "conflict": {"label": "c"},
        "world": {"label": "a harbour"},
        "genre": {"label": "g"},
        "villain": {"key": "k", "label": "K", "look": "l"},
        "motif": {"label": "m"},
        "shot": {"label": "s"},
    }
    assert (
        direct(_ir(), story_text="x", frame=frame, world="a mountain village").world == "a harbour"
    )


def test_a_directing_model_is_told_the_style_world():
    seen = {}

    def model(**kwargs):
        seen["prompt"] = kwargs["prompt"]
        return {"villain": {}, "world": "", "panels": [], "fillers": []}

    treatment = direct(
        _ir(), story_text="x", complete_json=model, world="a mountain village in mist"
    )
    assert "a mountain village in mist" in seen["prompt"]
    assert treatment.world == "a mountain village in mist"


# --------------------------------------------------------------------------- #
# the style cards
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def styles():
    return load_styles(ROOT / "styles")


def test_style_cards_read_what_they_own(styles):
    noir = styles["noir-webtoon"]
    assert "rain" in noir.world and noir.composition and noir.impact
    assert noir.lettering["balloon"] == "rounded"
    hud = styles["cyberpunk-hud"]
    assert "cyber city" in hud.world
    assert hud.lettering["balloon"] == "rect" and hud.lettering["ink"].startswith("#")


def test_a_style_without_a_look_adds_nothing(styles):
    plain = styles["anime"]
    assert plain.world == plain.composition == plain.impact == ""
    assert dict(plain.lettering) == {}


def test_the_shipped_styles_do_not_share_a_world(styles):
    worlds = [styles[key].world for key in ("noir-webtoon", "cyberpunk-hud", "ukiyo-e-folktale")]
    assert all(worlds) and len(set(worlds)) == 3


# --------------------------------------------------------------------------- #
# the lettering
# --------------------------------------------------------------------------- #


def test_the_default_letter_style_is_the_original_look():
    look = LetterStyle()
    assert (look.balloon, look.balloon_fill, look.caption_fill, look.ink, look.font) == (
        "ellipse",
        "white",
        "#fff3b0",
        "black",
        "comic",
    )


def test_a_letter_style_is_read_from_a_style_block_and_ignores_junk():
    look = LetterStyle.from_style(
        {
            "balloon": "rect",
            "ink": "#112233",
            "outline": "9",
            "font": "wingdings",
            "balloon_fill": "not-a-colour",
            "caption_shape": "rounded",
        }
    )
    assert look.balloon == "rect" and look.ink == "#112233" and look.caption_shape == "rounded"
    assert look.outline == 3.0  # clamped
    assert look.font == "comic" and look.balloon_fill == "white"
    assert LetterStyle.from_style(None) == LetterStyle()


def _colours(image):
    return {colour for _count, colour in image.getcolors(maxcolors=1_000_000)}


def _letter(look):
    image = Image.new("RGB", (800, 600), (90, 90, 90))
    out, report = letter_panel(
        image,
        heads={"sahil": [0.6, 0.5, 0.8, 0.8]},
        free=[[0.05, 0.02, 0.95, 0.3]],
        caption="Later that night.",
        lines=[("Sahil", "It is still broken.")],
        look=look,
    )
    assert report.complete
    return out


def test_lettering_differs_by_style_and_default_is_unchanged():
    default = _letter(None)
    assert _letter(LetterStyle()).tobytes() == default.tobytes()
    hud = _letter(
        LetterStyle.from_style(
            {
                "balloon": "rect",
                "balloon_fill": "#0d1b2a",
                "ink": "#7ff3ff",
                "caption_fill": "#07121c",
                "font": "display",
            }
        )
    )
    paper = _letter(
        LetterStyle.from_style({"balloon": "rounded", "balloon_fill": "#f6ecd2", "ink": "#2b1d14"})
    )
    assert len({default.tobytes(), hud.tobytes(), paper.tobytes()}) == 3
    # The balloon really is drawn in the style's colour.
    assert (13, 27, 42) in _colours(hud)
    assert (246, 236, 210) in _colours(paper)
