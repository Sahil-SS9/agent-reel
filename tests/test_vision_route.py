"""The host vision route: a prose answer must not fail the whole panel check."""

import json
from pathlib import Path

import pytest

from adapters.hermes.vision import VisionError, host_vision


def _reply(analysis: str) -> str:
    return json.dumps({"success": True, "analysis": analysis})


def test_a_prose_first_answer_is_retried_and_recovers(tmp_path):
    calls: list[str] = []
    answers = iter([
        _reply("The image depicts two characters in a futuristic setting."),
        _reply('{"on_model": {"Sahil": true}, "extra_people": 0, "text_in_image": false}'),
    ])

    def dispatch(_tool, payload):
        calls.append(payload["question"])
        return next(answers)

    ask = host_vision(dispatch)
    out = ask(tmp_path / "panel.jpg", "Check this panel.")
    assert out["extra_people"] == 0
    assert len(calls) == 2
    assert "JSON object only" in calls[1]  # the retry is explicit, not a silent loop


def test_two_prose_answers_still_fail_loudly(tmp_path):
    def dispatch(_tool, _payload):
        return _reply("Still just describing the picture.")

    ask = host_vision(dispatch)
    with pytest.raises(VisionError, match="no JSON"):
        ask(tmp_path / "panel.jpg", "Check this panel.")


def test_a_missing_json_object_never_becomes_a_silent_pass(tmp_path):
    def dispatch(_tool, _payload):
        raise RuntimeError("vision tool is down")

    ask = host_vision(dispatch)
    with pytest.raises(VisionError, match="vision_analyze raised"):
        ask(tmp_path / "panel.jpg", "Check this panel.")


def test_a_json_answer_on_the_first_ask_costs_only_one_call(tmp_path):
    calls: list[int] = []

    def dispatch(_tool, _payload):
        calls.append(1)
        return _reply('{"on_model": {}, "extra_people": 0, "text_in_image": false}')

    host_vision(dispatch)(Path("/tmp/x.jpg"), "q")
    assert len(calls) == 1
