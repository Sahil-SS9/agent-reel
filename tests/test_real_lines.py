"""Real lines, the cold open and the readout check.

The pipeline used to turn a person's blunt, funny messages into flat captions. These tests
pin the three things that give a chapter a voice: real sentences offered as dialogue, a
story that opens on its sharpest moment, and an editor that will not wave a bare
statistic through.
"""

from __future__ import annotations

import argparse
from types import SimpleNamespace

from canon.arcs import build_arc
from canon.beats import beats_from_events
from canon.canon import build_canon
from canon.episode import LLMDialogueWriter, plan_episode
from canon.events import build_event
from canon.gate import seal
from canon.grounding import ClaimGate
from canon.reallines import candidates, punch, real_lines_for, sentences, usable
from canon.story import (
    PANEL_JOBS,
    STORY_FIELDS,
    SYNOPSIS_PROMPT,
    edit_script,
    readout_problem,
    write_synopsis,
)

MESSAGE = (
    "Go on, then. How bad is it? I'll check the logs now. "
    "Why is it always the same file? Honestly, nobody tested this properly."
)

# --------------------------------------------------------------------------- #
# picking the lines
# --------------------------------------------------------------------------- #


def test_the_punchy_sentences_are_picked_and_flat_ones_are_not():
    picked = candidates(MESSAGE)
    assert "How bad is it?" in picked
    assert "Why is it always the same file?" in picked
    assert "Go on, then." not in picked, "a flat three-word statement is not a line"
    assert "I'll check the logs now." not in picked, "assistant filler is never a line"


def test_a_candidate_is_a_verbatim_sentence_of_the_message():
    for line in candidates(MESSAGE):
        assert line in MESSAGE


def test_ties_keep_reading_order_and_the_limit_holds():
    assert candidates(MESSAGE, limit=1) == ["How bad is it?"]
    assert len(candidates(MESSAGE, limit=2)) == 2


def test_code_links_paths_ids_and_masks_are_not_speech():
    text = (
        "```\nrm -rf build/\n```\nOpen src/app.py now! See https://example.dev now! "
        "Call [REDACTED:person#a1b2c3] now! Fix commit 9f2c4ab1 now! Why is x_y_z failing?"
    )
    assert candidates(text) == []
    assert not usable("Open src/app.py now!")
    assert not usable("Call [REDACTED:person#a1b2c3] now!")
    assert usable("Fix the failing test!")


def test_length_and_word_limits_apply():
    assert not usable("Why?")
    assert not usable("why " * 17 + "now?")
    assert not usable("This is a perfectly reasonable question that is far too long to fit? " * 2)


def test_bullets_and_quotes_are_stripped_before_scoring():
    assert sentences('- "How bad is it?"') == ["How bad is it?"]
    assert punch("How bad is it?") > punch("Go on, then.")


# --------------------------------------------------------------------------- #
# per panel
# --------------------------------------------------------------------------- #

QUOTES = {
    "e1": "Okay, so I'll start with the tests! Why does the checker keep failing?",
    "e2": "Why is it always the same file? Honestly, nobody tested this properly.",
    "e3": "Why is the other thing blocked?",
}
ACTORS = {"e1": "Kensei", "e2": "Sahil", "e3": "Quan"}


def test_the_owner_comes_first_even_when_the_agent_spoke_first():
    rows = real_lines_for(["e1", "e2"], QUOTES, ACTORS, ["Kensei", "Sahil"], owner="Sahil")
    assert rows[0]["speaker"] == "Sahil"
    assert {row["speaker"] for row in rows} == {"Sahil", "Kensei"}
    assert all(row["event_id"] in {"e1", "e2"} for row in rows)


def test_someone_who_may_not_speak_this_panel_gets_no_candidates():
    rows = real_lines_for(["e1", "e2", "e3"], QUOTES, ACTORS, ["Sahil"], owner="Sahil")
    assert {row["speaker"] for row in rows} == {"Sahil"}


def test_an_unknown_actor_or_missing_text_gives_nothing():
    assert real_lines_for(["e9"], QUOTES, ACTORS, ["Sahil"]) == []
    assert real_lines_for(["e1"], {}, ACTORS, ["Kensei"]) == []


def test_the_same_sentence_is_offered_once():
    rows = real_lines_for(
        ["e1", "e2"], {"e1": "Why is it broken?", "e2": "Why is it broken?"},
        {"e1": "Sahil", "e2": "Sahil"}, ["Sahil"], owner="Sahil",
    )
    assert len(rows) == 1


# --------------------------------------------------------------------------- #
# the writer sees them
# --------------------------------------------------------------------------- #


class _Spy:
    def __init__(self) -> None:
        self.payloads: list[dict] = []

    def complete_json(self, *, prompt, payload, schema_hint=None, stage=None):
        self.payloads.append(payload)
        return {"panels": [{"key": item["key"], "caption": "", "lines": [
            {"speaker": item["speakers"][0], "text": "Ugh. Not again."}]} for item in payload["panels"]]}


def _panels(count: int):
    roles = ["setup", "hidden_problem", "diagnosis", "climax", "aftermath", "win"]
    return [
        {"role": roles[i % 6], "key": f"k{i}", "speakers": ["Sahil"], "fact_sentence": "f",
         "evidence": "e", **({"real_lines": [{"speaker": "Sahil", "text": "How bad is it?", "event_id": "e"}]} if i == 0 else {})}
        for i in range(count)
    ]


def test_the_writer_is_given_real_lines_and_the_hook_only_where_they_belong():
    spy = _Spy()
    writer = LLMDialogueWriter(spy, ["Sahil"], story={"hook": "Everything was green and it was lying.", "jobs": {}, "voices": {}})
    writer.write(_panels(7))  # two scenes of at most five panels
    first, second = spy.payloads
    assert first["hook"] == "Everything was green and it was lying."
    assert "hook" not in second
    assert first["panels"][0]["real_lines"] == [{"speaker": "Sahil", "text": "How bad is it?"}]
    assert "real_lines" not in first["panels"][1]


def test_the_scene_prompt_tells_the_writer_to_use_them_and_to_open_on_the_hook():
    prompt = LLMDialogueWriter.SCENE_PROMPT
    assert "real_lines" in prompt and "A real line beats an invented one" in prompt
    assert "opens on it" in prompt
    assert "never just reports it" in prompt


# --------------------------------------------------------------------------- #
# through the planner: a real line is grounded and cited
# --------------------------------------------------------------------------- #


def _events():
    rows = [
        ("blocked", "denji-reviewer blocked the task after 2 failures"),
        ("blocked", "denji-reviewer blocked it again"),
        ("completed", "wesker fixed the blocker"),
        ("completed", "wesker closed the task"),
    ]
    out = []
    for index, (kind, text) in enumerate(rows):
        payload = {"kind": kind, "text": text, "task_id": "t_a", "chars": len(text)}
        event = build_event(
            source="kanban", kind="kanban.task.status", ts=float(index + 1),
            profile="wesker" if index >= 2 else "denji-reviewer",
            actor="wesker" if index >= 2 else "denji-reviewer",
            subject=kind, payload=payload, store="main", table="tasks", pk=f"t_a-{index}",
        )
        out.append(seal(event, payload))
    return out


class _RealLineWriter:
    """Uses whatever real line a panel offers; states the result on the last panels."""

    name = "real"

    def write(self, panels):
        out = {}
        for panel in panels:
            rows = panel.get("real_lines") or []
            caption = str(panel.get("evidence", "")).split("\n")[0][:70] if panel["role"] in {"win", "climax"} else ""
            out[panel["role"]] = {"caption": caption, "lines": [[r["speaker"], r["text"]] for r in rows[:1]]}
        return out


def _plan(quotes):
    events = _events()
    beats = beats_from_events(events)
    quote_map = {events[index].id: text for index, text in quotes.items()}
    evidence = {event.id: str(event.payload.get("text", "")) for event in events}
    for event_id, text in quote_map.items():
        evidence[event_id] = f"{evidence[event_id]}\n{text}"
    return events, plan_episode(
        build_arc(beats), beats, build_canon(events, beats),
        writer=_RealLineWriter(),
        grounder=ClaimGate(None, allow=("Sahil", "Denji-reviewer", "Wesker")),
        evidence=evidence,
        actors_by_event={event.id: str(event.actor).capitalize() for event in events},
        cast_map={"denji-reviewer": "Denji-reviewer", "wesker": "Wesker", "default": "Kensei"},
        quotes_by_event=quote_map or None,
    )


def test_a_real_line_reaches_the_page_cited_to_the_event_that_said_it():
    events, ir = _plan({1: "Why is it blocked again? Honestly, nobody checked this properly."})
    lines = [line for panel in ir.panels for line in panel.lines]
    texts = [line.text for line in lines]
    assert "Why is it blocked again?" in texts
    spoken = next(line for line in lines if line.text == "Why is it blocked again?")
    assert spoken.speaker == "Denji-reviewer"
    assert events[1].id in spoken.source_event_ids


def test_without_quotes_nothing_is_offered_and_nothing_changes():
    _, ir = _plan({})
    assert all(line.text != "Why is it blocked again?" for panel in ir.panels for line in panel.lines)


def test_an_invented_line_is_still_refused_when_real_lines_are_on():
    class Liar:
        name = "liar"

        def write(self, panels):
            return {panel["role"]: {"caption": "", "lines": [["Wesker", "the GPU melted at 91 degrees"]]}
                    for panel in panels}

    events = _events()
    beats = beats_from_events(events)
    ir = plan_episode(
        build_arc(beats), beats, build_canon(events, beats), writer=Liar(),
        grounder=ClaimGate(None, allow=("Sahil", "Denji-reviewer", "Wesker")),
        evidence={event.id: str(event.payload.get("text", "")) for event in events},
        actors_by_event={event.id: str(event.actor).capitalize() for event in events},
        cast_map={"denji-reviewer": "Denji-reviewer", "wesker": "Wesker", "default": "Kensei"},
        quotes_by_event={events[1].id: "Why is it blocked again?"},
    )
    assert all("melted" not in line.text for panel in ir.panels for line in panel.lines)


# --------------------------------------------------------------------------- #
# the cold open
# --------------------------------------------------------------------------- #

FIELDS = {
    "title": "The Green Lie", "logline": "Sahil learns the tests were lying.",
    "want": "Sahil wants a release he can trust.", "stakes": "A bad release would cost him a week.",
    "obstacle": "Every test passed and the build was still broken.", "turn": "Kensei finds the checker was broken.",
    "ending": "The real tests run.", "meaning": "Green is not the same as true.",
    "hook": "Every test was green, and the build was broken.",
}


class _Gate:
    def check(self, sentence, evidence, *, layer="dialogue", **_kwargs):
        return SimpleNamespace(supported=True, reason="")


def test_the_synopsis_carries_a_hook_that_is_not_part_of_the_story_text():
    result = write_synopsis(lambda **_k: dict(FIELDS), title="x", facts_text="f", brief_text="b", gate=_Gate())
    assert result.fields["hook"] == FIELDS["hook"]
    assert FIELDS["hook"] not in result.text()
    assert "hook" not in STORY_FIELDS and "title" not in STORY_FIELDS
    assert '"hook"' in SYNOPSIS_PROMPT


def test_the_setup_panel_opens_on_the_hook_not_on_scenery():
    job = PANEL_JOBS["setup"]
    assert job.startswith("a cold open")
    assert "Never open on scene-setting" in job


# --------------------------------------------------------------------------- #
# readouts
# --------------------------------------------------------------------------- #


def test_a_bare_statistic_is_a_readout():
    assert readout_problem("On questions about when things happened, LCM-X wins by 10 to 16 points.")
    assert readout_problem("Zero failures.")
    assert readout_problem("Nine runs passed.")


def test_a_caption_with_a_person_a_voice_or_no_number_is_not():
    cast = ("Sahil", "Kensei")
    assert readout_problem("Sahil needed it done by 5.", cast=cast) == ""
    assert readout_problem("It cost him the whole weekend, 2 days.") == ""
    assert readout_problem("Ten wins, and nobody believed it!") == ""
    assert readout_problem("Why did it take 3 tries?") == ""
    assert readout_problem("The checker itself was broken.") == ""
    assert readout_problem("") == ""


def _complete(score, problems=()):
    return lambda **_k: {"score": score, "problems": list(problems)}


PANELS = [
    {"id": "ep-p1", "role": "setup", "caption": "Sahil needs the release before Friday.", "lines": []},
    {"id": "ep-p2", "role": "win", "caption": "LCM-X wins by 10 to 16 points.", "lines": []},
]


def test_the_editor_flags_a_readout_and_caps_a_generous_score_so_the_rewrite_runs():
    review = edit_script(_complete(5), PANELS, synopsis="s", cast=("Sahil",))
    assert review["score"] == 3
    assert review["problems"] == [{"panel": "ep-p2", "issue": readout_problem(PANELS[1]["caption"])}]
    assert 0 < review["score"] < 4 and review["problems"]  # the pipeline's rewrite condition


def test_the_editor_does_not_double_flag_a_panel_the_model_already_flagged():
    review = edit_script(_complete(3, [{"panel": "ep-p2", "issue": "flat"}]), PANELS, synopsis="s", cast=("Sahil",))
    assert [item["panel"] for item in review["problems"]] == ["ep-p2"]
    assert review["problems"][0]["issue"] == "flat"


def test_a_clean_script_keeps_its_score():
    clean = [PANELS[0]]
    assert edit_script(_complete(5), clean, synopsis="s", cast=("Sahil",)) == {
        "score": 5, "problems": [], "source": "model"}


def test_an_unavailable_editor_is_unchanged():
    def boom(**_k):
        raise RuntimeError("down")

    review = edit_script(boom, PANELS, synopsis="s", cast=("Sahil",))
    assert review["source"] == "unavailable" and review["score"] == 0


# --------------------------------------------------------------------------- #
# the switch
# --------------------------------------------------------------------------- #


def test_real_lines_are_on_by_default_and_can_be_turned_off():
    from adapters.hermes.pipeline import PipelineConfig
    from adapters.hermes.reel_cli import register_cli

    assert PipelineConfig(data_dir=".").real_lines is True
    parser = argparse.ArgumentParser()
    register_cli(parser)
    assert parser.parse_args(["plan", "--no-real-lines"]).no_real_lines is True
    assert parser.parse_args(["plan"]).no_real_lines is False
