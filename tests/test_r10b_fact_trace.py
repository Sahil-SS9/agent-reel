"""A caption supported by a thread fact from another event cites that event too."""

from types import SimpleNamespace

from canon.episode import _supporting_fact_ids


def test_fact_from_another_event_is_cited():
    facts = [
        SimpleNamespace(event_id="e9", object="the plan", result="", source_text="checked the plan against the live checkout, cron stores and logs"),
        SimpleNamespace(event_id="e2", object="lunch", result="", source_text="ordered lunch"),
    ]
    caption = "Kensei checked the plan against the live checkout, cron stores and logs."
    assert _supporting_fact_ids(caption, facts) == ("e9",)
