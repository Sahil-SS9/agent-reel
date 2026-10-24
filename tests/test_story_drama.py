"""V2: stories are scored for drama - a problem, a fight, a result."""

from canon.selection import drama_score


def test_problem_struggle_and_fix_scores_highest():
    texts = [
        "The nightly job failed again with a timeout.",
        "Still broken: the queue is blocked and the retry crashed.",
        "Fixed: the queue drains now and all 40 tests passed.",
    ]
    assert drama_score(texts) == 6


def test_admin_chat_scores_zero():
    assert drama_score(["please provide a progress update", "Here is the update. All good."]) == 0


def test_open_problem_scores_but_less_than_a_resolved_one():
    open_problem = drama_score(["The build failed with a regression.", "Still investigating."])
    resolved = drama_score(["The build failed with a regression.", "Fixed and merged."])
    assert 0 < open_problem < resolved
