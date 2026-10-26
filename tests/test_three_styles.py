"""Three shipped styles that really are different: ligne-claire, halftone-noir, risograph-print.

The point of a style library is that the same story comes out looking like three different
books. These tests fail if the three drift back to a shared look: the same world, the same
framing, the same impact frame or the same balloons.
"""

from __future__ import annotations

from itertools import combinations
from pathlib import Path

import pytest
from PIL import Image

from canon.assets import load_styles
from canon.director import direct
from canon.letterer import LetterStyle, letter_panel
from canon.panel_prompt import build_panel_request

ROOT = Path(__file__).resolve().parents[1]
THREE = ("ligne-claire", "halftone-noir", "risograph-print")
ROLES = ("setup", "hidden_problem", "diagnosis", "climax", "aftermath", "win")


@pytest.fixture(scope="module")
def styles():
    cards = load_styles(ROOT / "styles")
    return {key: cards[key] for key in THREE}


def test_each_of_the_three_owns_a_full_look(styles):
    for card in styles.values():
        assert card.world and card.composition and card.impact, card.key
        assert card.lettering, card.key


@pytest.mark.parametrize("field", ["world", "composition", "impact"])
def test_no_two_share_a_world_a_framing_or_an_impact_frame(styles, field):
    for a, b in combinations(styles.values(), 2):
        assert getattr(a, field) != getattr(b, field), (a.key, b.key, field)


def test_no_two_share_the_same_lettering(styles):
    looks = {key: LetterStyle.from_style(card.lettering) for key, card in styles.items()}
    for a, b in combinations(looks, 2):
        assert looks[a] != looks[b], (a, b)
    # The strongest differences: shape, ink and fill, not a hair's width of outline.
    assert len({look.ink for look in looks.values()}) == 3
    assert len({look.balloon_fill for look in looks.values()}) == 3
    assert len({(look.balloon, look.font) for look in looks.values()}) == 3


def test_the_same_panel_is_prompted_three_ways(styles):
    panels = [{"id": f"p{i}", "role": r, "cast": [], "caption": "", "lines": [], "setting": "the rig"}
              for i, r in enumerate(ROLES)]
    ir = {"logline": "x", "panels": panels}
    prompts = {}
    for key, card in styles.items():
        treatment = direct(ir, story_text="the build failed", world=card.world)
        prompts[key] = build_panel_request(
            panels[3], style=card, kits={}, treatment=treatment.panels["p3"]).prompt
    assert len(set(prompts.values())) == 3
    assert "halftone" in prompts["halftone-noir"].lower()
    assert "risograph" in prompts["risograph-print"].lower()
    assert "outline" in prompts["ligne-claire"].lower()
    # A style's own words do not leak into another style's prompt.
    assert "halftone" not in prompts["risograph-print"].lower()
    assert "risograph" not in prompts["halftone-noir"].lower()
    # None of them carries the old shared look.
    for prompt in prompts.values():
        assert "cinematic energy" not in prompt and "cyber city" not in prompt.lower()


def test_the_same_lettering_job_looks_different_in_each(styles):
    renders = {}
    for key, card in styles.items():
        image = Image.new("RGB", (800, 600), (120, 120, 120))
        out, report = letter_panel(
            image, heads={"sahil": [0.6, 0.5, 0.8, 0.8]}, free=[[0.05, 0.02, 0.95, 0.3]],
            caption="Later that night.", lines=[("Sahil", "It is still broken.")],
            look=LetterStyle.from_style(card.lettering),
        )
        assert report.complete
        renders[key] = out.tobytes()
    assert len(set(renders.values())) == 3
