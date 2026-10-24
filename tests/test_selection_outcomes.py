"""Round 8 / R8-3: a substantive outcome outranks a long conversation.

RED-first: written before the ranking change, so it fails on the current score.
"""

from __future__ import annotations

from canon.selection import StoryCandidate, is_substantive_outcome, rank_candidates


def candidate(name, *, goal, outcome, user_turns, text_chars=400):
    return StoryCandidate(
        kind="session",
        key=name,
        goal=goal,
        title=goal[:80],
        outcome=outcome,
        user_turns=user_turns,
        text_chars=text_chars,
        event_ids=tuple(f"{name}-{index}" for index in range(6)),
    )


def test_qualitative_completed_work_beats_verbose_bookkeeping():
    finished = candidate(
        "finished",
        goal="Review the memory system against the alternative",
        outcome="Every persona run finished and no skill made the agent worse.",
        user_turns=2,
    )
    bookkeeping = candidate(
        "bookkeeping",
        goal="Please review this and keep going with the plan",
        outcome="Go received.",
        user_turns=12,
        text_chars=4000,
    )
    ranked = rank_candidates([bookkeeping, finished])
    assert ranked[0].key == "finished", [row.key for row in ranked]


def test_a_naked_one_liner_is_not_a_substantive_outcome():
    assert not is_substantive_outcome("Go received.")
    assert not is_substantive_outcome("Okay.")
    assert not is_substantive_outcome("[IMPORTANT: Background process proc_1 completed normally")


def test_a_measured_result_is_substantive():
    assert is_substantive_outcome(
        "The head-to-head is finished: Severian beats LCM-X on two of three benchmarks."
    )
    assert is_substantive_outcome("All 12 re-runs passed and the suite is green.")


def test_conversation_length_still_breaks_ties_between_equal_outcomes():
    short = candidate("short", goal="Fix the adapter", outcome="The adapter is fixed and merged.", user_turns=2)
    long = candidate("long", goal="Fix the adapter", outcome="The adapter is fixed and merged.", user_turns=9)
    ranked = rank_candidates([short, long])
    assert ranked[0].key == "long"
