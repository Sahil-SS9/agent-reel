"""Round 10: a selected child session finds its lineage thread.

r9 skipped 5 of 11 selected stories as "no thread for this story": the selected key was
a child session id, while the lineage thread is keyed by its root session.
"""

from __future__ import annotations

from types import SimpleNamespace

from adapters.hermes.pipeline import _thread_for_candidate


def test_child_session_resolves_through_its_events():
    root = SimpleNamespace(id="thr_root", key="root-session")
    other = SimpleNamespace(id="thr_other", key="other")
    by_event = {"e1": root, "e2": root, "e3": other}
    candidate = SimpleNamespace(key="child-session", event_ids=("e1", "e2", "e3"))
    assert _thread_for_candidate(candidate, by_event) is root


def test_no_events_in_any_thread_is_none():
    candidate = SimpleNamespace(key="x", event_ids=("nope",))
    assert _thread_for_candidate(candidate, {}) is None
