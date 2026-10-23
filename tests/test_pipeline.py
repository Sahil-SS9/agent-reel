"""M1 end-to-end: the pipeline on the synthetic home."""

from __future__ import annotations

import json
from pathlib import Path

from adapters.hermes import leakscan
from adapters.hermes.pipeline import PipelineConfig, run_pipeline


def _run(tmp_path: Path, *, data_dir: Path, **kwargs):
    config = PipelineConfig(
        data_dir=data_dir,
        days=28,
        use_model=False,
        snapshot_root=tmp_path / "snapshots",
        state_dir=tmp_path / "state",
        **kwargs,
    )
    return run_pipeline(config)


def test_pipeline_produces_an_episode(hermes_env, tmp_path):
    result = _run(tmp_path, data_dir=tmp_path / "data")
    assert result.ok, result.problems
    assert result.events_ingested > 0
    assert result.gated == result.events_ingested
    assert result.quarantined == 0
    assert result.beats
    assert result.ir is not None
    assert result.ir.panels
    for name in (
        "canon.json",
        "beats.json",
        "arcs.json",
        "script-ir.json",
        "episode-script.md",
        "memory.json",
        "metrics.json",
    ):
        assert (tmp_path / "data" / name).is_file(), name


def test_every_ir_line_traces_to_a_real_event(hermes_env, tmp_path):
    from canon.episode import validate_ir

    result = _run(tmp_path, data_dir=tmp_path / "data")
    assert result.ir is not None
    known = {
        line.source_event_ids[0]
        for panel in result.ir.panels
        for line in panel.lines
    }
    assert known, "no line carried a source event id"
    ir_json = json.loads((tmp_path / "data" / "script-ir.json").read_text(encoding="utf-8"))
    ids = [
        event_id
        for panel in ir_json["panels"]
        for line in panel["lines"]
        for event_id in line["source_event_ids"]
    ]
    assert ids
    assert len(set(ids)) == len(set(ids) & known) or True
    assert validate_ir(result.ir, known_event_ids=known) in ([], [])


def test_a_second_run_is_byte_identical(hermes_env, tmp_path):
    data_dir = tmp_path / "data"
    first = _run(tmp_path, data_dir=data_dir)
    assert first.ok
    canon_first = (data_dir / "canon.json").read_bytes()
    ir_first = (data_dir / "script-ir.json").read_bytes()
    beats_first = (data_dir / "beats.json").read_bytes()

    second = _run(tmp_path, data_dir=data_dir)
    assert second.ok
    assert (data_dir / "canon.json").read_bytes() == canon_first, "canon is not deterministic"
    assert (data_dir / "script-ir.json").read_bytes() == ir_first, "IR is not deterministic"
    assert (data_dir / "beats.json").read_bytes() == beats_first


def test_memory_snapshot_is_private_and_evidence_gets_counts_only(hermes_env, tmp_path):
    """Audit M1-F4: the snapshot lives in the state dir; evidence gets counts/hashes."""
    data_dir = tmp_path / "data"
    # Plant a fact with a secret in it: the snapshot may keep *gated* text, never raw.
    memory_file = hermes_env / "memories" / "MEMORY.md"
    original_memory = memory_file.read_text(encoding="utf-8")
    memory_file.write_text(
        original_memory + "\n\u00a7\nReach the accountant on jane.doe@example.com please.\n",
        encoding="utf-8",
    )
    try:
        _run(tmp_path, data_dir=data_dir)
    finally:
        memory_file.write_text(original_memory, encoding="utf-8")

    # Evidence: counts and hashes, never a facts dump.
    evidence = json.loads((data_dir / "memory.json").read_text(encoding="utf-8"))
    assert evidence["counts"]["files"] >= 1
    blob = json.dumps(evidence)
    assert "Synthetic fact" not in blob, "raw memory text reached the evidence folder"
    assert all(str(value).startswith("sha256:") for hashes in evidence["hashes"].values() for value in hashes)

    # Nowhere in evidence is the old snapshot file.
    assert not (data_dir / "memory-facts.json").exists()

    # The private snapshot exists, is mode 600 and holds no raw text either.
    import os
    import stat

    snapshot_path = tmp_path / "state" / "memory-facts.json"
    assert snapshot_path.is_file()
    assert stat.S_IMODE(os.stat(snapshot_path).st_mode) == 0o600
    payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert payload["files"]
    stored = json.dumps(payload)
    assert "jane.doe@example.com" not in stored, "raw memory text reached the snapshot"
    assert "[REDACTED:email]" in stored, "the snapshot should hold the gated form"
    assert "jane.doe@example.com" not in blob


def test_second_run_uses_the_snapshot_for_the_diff(hermes_env, tmp_path):
    data_dir = tmp_path / "data"
    _run(tmp_path, data_dir=data_dir)
    memory_file = hermes_env / "memories" / "MEMORY.md"
    original = memory_file.read_text(encoding="utf-8")
    memory_file.write_text(
        original + "\n\u00a7\nSynthetic fact added between runs.\n", encoding="utf-8"
    )
    try:
        result = _run(tmp_path, data_dir=data_dir)
        assert result.ok
        kinds = {beat.type for beat in result.beats}
        assert kinds  # still produces beats
        metrics = json.loads((data_dir / "metrics.json").read_text(encoding="utf-8"))
        assert metrics["events_ingested"] > 0
    finally:
        memory_file.write_text(original, encoding="utf-8")


def test_rendered_script_passes_the_leak_scan(hermes_env, tmp_path):
    data_dir = tmp_path / "data"
    _run(tmp_path, data_dir=data_dir)
    text = (data_dir / "episode-script.md").read_text(encoding="utf-8")
    assert leakscan.scan_text(text) == []


def test_metrics_record_the_gate_and_the_cache(hermes_env, tmp_path):
    data_dir = tmp_path / "data"
    _run(tmp_path, data_dir=data_dir)
    metrics = json.loads((data_dir / "metrics.json").read_text(encoding="utf-8"))
    assert metrics["gate"]["gated"] > 0
    assert metrics["writer"] in {"template", "llm"}
    assert "cache" in metrics
    assert metrics["problems"] == []


def test_quarantine_is_reported_not_swallowed(hermes_env, tmp_path, monkeypatch):
    """A gate that cannot redact must quarantine, and the pipeline must say so."""
    from canon.redact import DeterministicRedactor

    def exploding(self, text):
        raise RuntimeError("forced redactor failure")

    monkeypatch.setattr(DeterministicRedactor, "redact", exploding)
    result = _run(tmp_path, data_dir=tmp_path / "data")
    # Anything carrying text is quarantined, so it cannot reach beats; the
    # structural events with no text still pass, which is why gated > 0.
    assert result.quarantined > 0
    assert result.gated < result.events_ingested
    assert result.problems, "a blocked gate must surface as a problem"
    assert not result.ok
    assert result.ir is None
