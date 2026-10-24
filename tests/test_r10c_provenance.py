"""r10c / QAR10-03: a caption cites the episode event that states it directly."""

from canon.episode import _supporting_event_ids


def test_direct_witness_in_another_panel_is_cited():
    pool = {
        "ask": "Sahil asked for a read-only audit. Do not make any changes.",
        "witness": "Kensei reported the audit. No files were modified at any point.",
        "other": "Kensei described the scheduler and the cron stores.",
    }
    ids = _supporting_event_ids("Across the audit, not a single file was modified.", pool)
    assert "witness" in ids
    assert "other" not in ids


def test_unrelated_events_are_not_cited():
    pool = {"x": "Lunch was ordered at noon."}
    assert _supporting_event_ids("The audit modified no files.", pool) == ()
