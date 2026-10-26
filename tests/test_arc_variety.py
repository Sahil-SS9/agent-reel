"""Story shapes: not every thread is a fight with a monster.

A thread that reads as a mystery, a pivot, a rivalry or a training montage is told that way:
different panel jobs for the writer, a different treatment for the director, and no creature
at all where the opponent is a plan or a score.
"""

from __future__ import annotations

import pytest

from canon.arcs import ARC_TYPES, DEFAULT_ARC_TYPE, classify_arc_type, turn_texts
from canon.director import ARC_DIRECTION, NO_VILLAIN_TYPES, ROLE_ACTION, direct
from canon.episode import EpisodeIR
from canon.story import PANEL_JOBS, TYPE_JOBS, jobs_for

ROLES = ("setup", "hidden_problem", "diagnosis", "climax", "aftermath", "win")


def _ir(arc_type: str = "") -> dict:
    panels = [
        {"id": f"p{i}", "role": role, "caption": "", "lines": [], "cast": ["Sahil", "Kensei"]}
        for i, role in enumerate(ROLES)
    ]
    ir = {"logline": "A story", "panels": panels}
    if arc_type:
        ir["arc_type"] = arc_type
    return ir


# --------------------------------------------------------------------------- #
# the classifier
# --------------------------------------------------------------------------- #


def test_the_default_shape_is_the_struggle():
    assert DEFAULT_ARC_TYPE == "struggle-to-resolution"
    assert classify_arc_type() == DEFAULT_ARC_TYPE
    assert (
        classify_arc_type(
            goal="Fix the deploy", turns=["It failed", "Fixed it"], outcome="Deployed"
        )
        == DEFAULT_ARC_TYPE
    )


def test_every_shape_it_returns_is_a_known_one():
    samples = [
        {
            "goal": "Beat the competitor",
            "turns": ["Our model versus theirs", "The leaderboard says we lose"],
            "outcome": "",
        },
        {
            "goal": "Ship it",
            "turns": [
                "Let's switch to a different approach",
                "Scrap the cron job, use a queue instead",
            ],
            "outcome": "",
        },
        {
            "goal": "Why is it slow?",
            "turns": ["This is strange", "No idea why it stalls"],
            "outcome": "The cause was a lock",
        },
    ]
    for sample in samples:
        assert classify_arc_type(**sample) in ARC_TYPES


def test_rivalry_pivot_and_mystery_are_called_from_the_words():
    assert (
        classify_arc_type(goal="Beat the rival", turns=["a rival bot", "head-to-head test"])
        == "rivalry"
    )
    assert classify_arc_type(goal="x", turns=["switch to a queue", "scrap the cron job"]) == "pivot"
    why = ["why does it hang", "this is strange", "so it was the lock"]
    assert classify_arc_type(goal="x", turns=why, outcome="It turned out to be a lock") == "mystery"
    # A puzzle that is never solved is not told as a mystery with a reveal.
    assert (
        classify_arc_type(goal="x", turns=["why does it hang", "this is strange"])
        == DEFAULT_ARC_TYPE
    )


def test_a_steady_climb_is_a_training_montage():
    turns = ["accuracy up from 40%", "better at 55%", "faster again, 70%"]
    assert classify_arc_type(goal="Improve the score", turns=turns) == "training-montage"


def test_one_stray_word_does_not_change_the_shape():
    assert classify_arc_type(goal="Fix it", turns=["why", "it failed", "fixed"]) == DEFAULT_ARC_TYPE


def test_turn_texts_reads_objects_and_dicts():
    class Turn:
        text = "from an object"

    class Brief:
        turns = (Turn(), {"text": "from a dict"}, {"text": ""})

    assert turn_texts(Brief()) == ["from an object", "from a dict"]


# --------------------------------------------------------------------------- #
# the panel jobs
# --------------------------------------------------------------------------- #


def test_the_default_jobs_are_what_they_were():
    assert jobs_for() == PANEL_JOBS
    assert "Sahil" in PANEL_JOBS["setup"] and "Kensei" in PANEL_JOBS["setup"]


def test_the_cast_is_filled_in_not_hardcoded():
    jobs = jobs_for("struggle-to-resolution", hero="Priya", agent="Atlas")
    assert "Priya" in jobs["setup"] and "Atlas" in jobs["setup"]
    assert "Sahil" not in jobs["setup"] and "Kensei" not in jobs["setup"]


@pytest.mark.parametrize("arc_type", ARC_TYPES)
def test_every_shape_opens_cold_and_covers_every_role(arc_type):
    jobs = jobs_for(arc_type)
    assert set(ROLES) <= set(jobs)
    assert jobs["setup"].startswith("a cold open")
    assert "{" not in "".join(jobs.values())


def test_the_shapes_tell_the_story_differently():
    texts = {t: jobs_for(t)["climax"] for t in ARC_TYPES}
    assert len(set(texts.values())) == len(ARC_TYPES)
    assert set(TYPE_JOBS) == set(ARC_TYPES) - {DEFAULT_ARC_TYPE}


def test_an_unknown_shape_falls_back_to_the_default():
    assert jobs_for("nonsense") == jobs_for()


# --------------------------------------------------------------------------- #
# the director
# --------------------------------------------------------------------------- #


def test_the_default_treatment_is_unchanged():
    plain = direct(_ir(), story_text="the build failed")
    named = direct(_ir(), story_text="the build failed", arc_type=DEFAULT_ARC_TYPE)
    assert plain.villain_name and plain.has_villain
    assert plain.as_dict() == named.as_dict()
    assert "arc_type" not in plain.as_dict()
    assert plain.panels["p3"].motion == ROLE_ACTION["climax"][0]


@pytest.mark.parametrize("arc_type", sorted(NO_VILLAIN_TYPES))
def test_a_pivot_or_a_montage_has_no_creature(arc_type):
    treatment = direct(_ir(), story_text="the build failed", arc_type=arc_type)
    assert not treatment.has_villain
    assert treatment.villain_name == "" and treatment.villain_look == ""
    everything = list(treatment.panels.values()) + treatment.fillers
    assert {item.villain_presence for item in everything} == {"absent"}
    text = " ".join(f"{i.action} {i.motion} {i.impact} {i.reaction}" for i in everything).lower()
    for word in ("villain", "gremlin", "golem", "static", "wraith"):
        assert word not in text
    assert treatment.as_dict()["arc_type"] == arc_type


@pytest.mark.parametrize("arc_type", sorted(NO_VILLAIN_TYPES))
def test_the_deck_villain_is_ignored_when_there_is_none(arc_type):
    frame = {
        "conflict": {"label": "a race"},
        "world": {"label": "a quiet library"},
        "genre": {"label": "noir"},
        "villain": {"key": "ledger-hydra", "label": "The Ledger Hydra", "look": "many heads"},
        "motif": {"label": "rain"},
        "shot": {"label": "a wide window"},
    }
    treatment = direct(_ir(), story_text="x", frame=frame, arc_type=arc_type)
    assert not treatment.has_villain
    assert treatment.world == "a quiet library"
    model = _Model()
    direct(_ir(), story_text="x", frame=frame, complete_json=model, arc_type=arc_type)
    assert "villain archetype" not in model.payloads[0]["frame"]
    assert "world: a quiet library" in model.payloads[0]["frame"]
    direct(_ir(), story_text="x", frame=frame, complete_json=model)
    assert "villain archetype: The Ledger Hydra" in model.payloads[1]["frame"]


def test_a_mystery_keeps_the_culprit_out_of_frame_until_the_reveal():
    treatment = direct(_ir(), story_text="the build failed", arc_type="mystery")
    presence = {item.role: item.villain_presence for item in treatment.panels.values()}
    assert presence["setup"] == presence["hidden_problem"] == presence["diagnosis"] == "absent"
    assert presence["climax"] == "attacking"
    assert treatment.has_villain


def test_a_rivalry_has_the_rival_in_the_room_from_the_start():
    treatment = direct(_ir(), story_text="the build failed", arc_type="rivalry")
    assert treatment.panels["p0"].villain_presence != "absent"
    assert treatment.has_villain


def test_the_shapes_are_directed_differently():
    seen = set()
    for arc_type in ARC_TYPES:
        treatment = direct(_ir(), story_text="the build failed", arc_type=arc_type)
        seen.add(
            tuple(
                (i.shot, i.angle, i.villain_presence, i.action) for i in treatment.panels.values()
            )
        )
    assert len(seen) == len(ARC_TYPES)


class _Model:
    """A director model that always draws a monster, whatever it was told."""

    def __init__(self):
        self.prompts = []
        self.payloads = []

    def __call__(self, **kwargs):
        self.prompts.append(kwargs["prompt"])
        self.payloads.append(kwargs["payload"])
        return {
            "villain": {"name": "The Beast", "look": "a roaring beast"},
            "world": "a harbour at dusk",
            "panels": [
                {
                    "id": f"p{i}",
                    "location": "the dock",
                    "action": "stands",
                    "villain_presence": "attacking",
                    "shot": "full",
                    "angle": "low",
                }
                for i in range(len(ROLES))
            ],
            "fillers": [],
        }


@pytest.mark.parametrize("arc_type", sorted(NO_VILLAIN_TYPES))
def test_the_model_cannot_add_a_creature_to_a_shape_without_one(arc_type):
    model = _Model()
    treatment = direct(_ir(), story_text="x", complete_json=model, arc_type=arc_type)
    assert model.prompts[0].endswith(ARC_DIRECTION[arc_type])
    assert model.payloads[0]["story_shape"] == arc_type
    assert not treatment.has_villain
    assert {i.villain_presence for i in list(treatment.panels.values()) + treatment.fillers} == {
        "absent"
    }


def test_the_model_cannot_show_the_culprit_before_the_reveal_in_a_mystery():
    treatment = direct(_ir(), story_text="x", complete_json=_Model(), arc_type="mystery")
    assert treatment.panels["p0"].villain_presence == "absent"
    assert treatment.panels["p3"].villain_presence == "attacking"
    assert any("culprit kept out of frame" in r for r in treatment.repairs)


def test_the_default_shape_sends_the_model_nothing_new():
    model = _Model()
    direct(_ir(), story_text="x", complete_json=model)
    assert "story_shape" not in model.payloads[0]
    assert model.prompts[0].endswith('"villain_presence": "...", "shot": "...", "angle": "..."}]}')


# --------------------------------------------------------------------------- #
# the episode
# --------------------------------------------------------------------------- #


def test_the_episode_carries_its_shape_only_when_it_has_one():
    base = {
        "episode_id": "e",
        "season": 1,
        "number": 1,
        "format": "strip",
        "format_hints": (),
        "arc_ids": ("a",),
        "logline": "l",
        "panels": (),
        "writer": "w",
    }
    assert "arc_type" not in EpisodeIR(**base).as_dict()
    assert EpisodeIR(**base, arc_type="pivot").as_dict()["arc_type"] == "pivot"
