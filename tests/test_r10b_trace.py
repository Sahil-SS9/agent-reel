"""Round 10b / QAR10-03: every caption and line can be followed to gated evidence."""

from __future__ import annotations

import json
from pathlib import Path

from conftest import StubWriter
from adapters.hermes.pipeline import PipelineConfig, run_pipeline


def test_each_episode_ships_a_trace_that_resolves_every_caption(hermes_env, tmp_path):
    data = tmp_path / "data"
    result = run_pipeline(
        PipelineConfig(
            data_dir=data, days=28, use_model=False, snapshot_root=tmp_path / "s",
            state_dir=tmp_path / "st", writer=StubWriter(), min_strip_panels=3,
        )
    )
    assert result.episodes, result.problems
    for row in result.episodes:
        ir = json.loads((data / f"script-ir-{row['number']}.json").read_text())
        trace = json.loads((data / f"episode-{row['number']}-trace.json").read_text())
        assert trace["arc"]["id"] in ir["arc_ids"]
        beat_ids = {beat["id"] for beat in trace["beats"]}
        assert set(trace["arc"]["roles"].values()) <= beat_ids
        captions = [panel for panel in ir["panels"] if panel["caption"]]
        assert captions
        for panel in captions:
            assert panel["caption_source_event_ids"], panel
            for event_id in panel["caption_source_event_ids"]:
                assert trace["evidence"].get(event_id), event_id
        for panel in ir["panels"]:
            for line in panel["lines"]:
                for event_id in line["source_event_ids"]:
                    assert event_id in trace["evidence"]
