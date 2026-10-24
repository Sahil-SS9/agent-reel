"""Round 8 / R8-1: natural captions, and no caption the planner wrote itself.

The three input shapes the audit named: an imperative request, a first-person assistant
message, and a truncated title. In each case the planner must not put the fragment on the
page, and a grammatical sentence that a writer supplies must be accepted.
"""

from __future__ import annotations

from canon.caption import caption_problem
from conftest import StubWriter
from test_r8_prose_and_endings import plan_with


def test_natural_prose_passes_the_caption_policy():
    for caption in (
        "Sahil asked the fleet to benchmark both memory systems.",
        "Kensei could not open the artifact, so the review never happened.",
        "Sahil wanted a review of an idea about building.",
        "Severian scored 87.3 against LCM-X on LoCoMo.",
    ):
        assert caption_problem(caption, max_owner_quote=8) == "", caption


def test_the_template_shape_is_still_refused():
    for caption in ("Sahil asked for a review.", "Kensei reported the build.", "Kensei worked on the adapter."):
        assert caption_problem(caption, max_owner_quote=8) != ""


def test_an_imperative_goal_is_never_used_verbatim_as_a_caption():
    class Quiet(StubWriter):
        name = "quiet"

        def write(self, panels):
            return {panel["role"]: {"caption": "", "lines": []} for panel in panels}

    ir = plan_with(Quiet())
    for panel in ir.panels:
        assert "please benchmark our memory system" not in panel.caption.lower()


def test_a_first_person_message_is_quoted_by_nobody():
    class ThirdPerson(StubWriter):
        name = "third"

        def write(self, panels):
            captions = {
                "setup": "Sahil wanted both memory systems compared fairly.",
                "climax": "Severian scored 87.3 against LCM-X on LoCoMo.",
                "win": "Severian scored 87.3 against LCM-X on LoCoMo.",
            }
            return {
                panel["role"]: {
                    "caption": captions.get(
                        panel["role"], "Kensei could not open the artifact and did not review it."
                    ),
                    "lines": [],
                }
                for panel in panels
            }

    ir = plan_with(ThirdPerson())
    for panel in ir.panels:
        # never the raw first-person fragment; a third-person sentence is what we allow
        assert "i couldn't" not in panel.caption.lower()
        assert not panel.caption.lower().startswith("i ")


def test_a_truncated_title_is_not_a_caption():
    class Titled(StubWriter):
        name = "titled"

        def write(self, panels):
            captions = {
                "setup": "Sahil wanted a review of an idea about building.",
                "climax": "Severian scored 87.3 against LCM-X on LoCoMo.",
                "win": "Severian scored 87.3 against LCM-X on LoCoMo.",
            }
            return {
                panel["role"]: {"caption": captions.get(panel["role"], ""), "lines": []}
                for panel in panels
            }

    ir = plan_with(Titled())
    for panel in ir.panels:
        assert "idea/concept" not in panel.caption.lower()
