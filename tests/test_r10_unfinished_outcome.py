"""Round 10: an in-progress outcome does not make a story "resolved".

The r10 run told the LCM-X benchmark session as a finished story ending on a WIN panel,
when its last message was a forecast ("the last score should now land around 22:45").
A brief arc is resolved only when its outcome states a finished result; otherwise it
ends on "To be continued".
"""

from __future__ import annotations

from types import SimpleNamespace

from canon.arcs import build_brief_arc
from canon.selection import outcome_is_finished


def test_forecast_is_not_finished():
    assert not outcome_is_finished(
        "Severian has worked through about half of LongMemEval; the last score should now land around 22:45."
    )


def test_still_running_is_not_finished():
    assert not outcome_is_finished(
        "Severian 87.3 vs LCM-X 79.5 on LoCoMo; a tie on BEAM; LongMemEval still running."
    )


def test_finished_result_is_finished():
    assert outcome_is_finished(
        "Everything is finished: the full test suite passes and no skill made the AI worse for any persona."
    )


def _brief(outcome: str):
    turns = tuple(
        SimpleNamespace(event_id=f"e{i}", text=f"turn {i} text about the benchmark", actor="owner")
        for i in range(4)
    )
    return SimpleNamespace(turns=turns, outcome=outcome, goal="benchmark LCM-X", thread_key="s1")


def test_brief_arc_with_forecast_outcome_stays_open():
    arc, _ = build_brief_arc(_brief("The last score should now land around 22:45."), {})
    assert arc is not None and arc.status == "open"


def test_brief_arc_with_finished_outcome_resolves():
    arc, _ = build_brief_arc(
        _brief("Everything is finished: the full test suite passes and every persona was tested."), {}
    )
    assert arc is not None and arc.status == "resolved"
