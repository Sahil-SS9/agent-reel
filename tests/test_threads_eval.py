"""Round 3 item 7: 30 synthetic threads, both layers, with an adversarial control."""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "eval" / "threads"))


def test_thirty_threads_are_clean_and_the_gate_can_fail():
    from eval.threads.run import run  # type: ignore[import-not-found]

    report = run()
    assert report["threads"] >= 30
    assert report["completed_threads"] > 0
    assert report["clean_problems"] == [], report["clean_problems"][:5]
    # The adversarial writer tries to smuggle a cause, a number and a name into every
    # panel; none of it may be released.
    assert report["adversarial_captions_or_lines_released"] == []
    assert report["adversarial_refusals"] > 0, "the control never fired, so the check is blind"
    # Open threads end on a labelled cliffhanger, finished ones do not.
    assert report["cliffhangers"] == report["threads"] - report["completed_threads"]
    assert report["ok"]
