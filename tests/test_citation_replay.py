"""t_abdaa3a9 (Quan re-sample at 0689404, finding 3): every citation replays from the
trace alone, because the trace archives the exact runtime evidence pool."""

from __future__ import annotations

import json

from conftest import StubWriter
from adapters.hermes.pipeline import PipelineConfig, run_pipeline
from canon.episode import pool_digest
from eval.trace_replay import replay


# finding 3 ---------------------------------------------------------------------------
def test_a_trace_archives_the_whole_runtime_pool_and_every_citation_replays(hermes_env, tmp_path):
    data = tmp_path / "data"
    result = run_pipeline(
        PipelineConfig(
            data_dir=data, days=28, use_model=False, snapshot_root=tmp_path / "s",
            state_dir=tmp_path / "st", writer=StubWriter(), min_strip_panels=3,
        )
    )
    assert result.episodes, result.problems
    for row in result.episodes:
        trace = json.loads((data / f"episode-{row['number']}-trace.json").read_text())
        archive = trace["evidence_pool"]
        beat_ids = [e for beat in trace["beats"] for e in beat["event_ids"]]
        # Every story event with text is archived whole, not only the cited ones, and every
        # cited id is readable in full (thread-fact events outside the story included).
        assert set(archive["order"]) <= set(beat_ids)
        assert set(trace["evidence"]) <= set(archive["order"]) | set(archive["cited_outside_pool"])
        pool = {e: archive["events"][e] for e in archive["order"]}
        assert archive["sha256"] == pool_digest(pool)
        assert trace["panels"] and all("own_event_ids" in p for p in trace["panels"])
        out = replay(trace)
        assert out["replayed"] > 0
        assert out["ok"], [r for r in out["rows"] if not r["match"]]


def test_a_cut_or_missing_pool_entry_is_caught_by_the_replay(hermes_env, tmp_path):
    data = tmp_path / "data"
    result = run_pipeline(
        PipelineConfig(
            data_dir=data, days=28, use_model=False, snapshot_root=tmp_path / "s",
            state_dir=tmp_path / "st", writer=StubWriter(), min_strip_panels=3,
        )
    )
    trace = json.loads((data / f"episode-{result.episodes[0]['number']}-trace.json").read_text())
    first = trace["evidence_pool"]["order"][0]
    trace["evidence_pool"]["events"][first] = trace["evidence_pool"]["events"][first][:20]
    assert not replay(trace)["ok"]  # the digest no longer matches
    del trace["evidence_pool"]
    assert "error" in replay(trace)
