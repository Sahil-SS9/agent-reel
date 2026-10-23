"""M1-F4: no ungated text in evidence; memory snapshots are private and hashed."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from adapters.hermes.evidence import (
    EvidenceLeak,
    Gated,
    assert_no_raw_text,
    validate,
    write_json,
    write_private_json,
    write_text,
)
from adapters.hermes.redact_source import rules_from_snapshot
from adapters.hermes.snapshot import SnapshotStore, build_snapshot, fact_hash
from canon.redact import DeterministicRedactor, RedactionGate


def gate() -> RedactionGate:
    return RedactionGate(DeterministicRedactor(rules_from_snapshot()))


RAW_MEMORY = (
    "Sahil's accountant is jane.doe@example.com and the paperwork is in "
    "/home/kensei/private/accounts/2026.xlsx, ring 07700 900123."
)


# --------------------------------------------------------------------------- #
# the evidence writer
# --------------------------------------------------------------------------- #


def test_writer_refuses_raw_memory_text(tmp_path):
    """The exact M1-F4 leak: a memory fact with an email, a path and a phone."""
    target = tmp_path / "memory.json"
    with pytest.raises(EvidenceLeak) as excinfo:
        write_json(target, {"facts": [RAW_MEMORY]}, gate())
    assert "would be changed by the gate" in str(excinfo.value)
    assert not target.exists(), "a refused write must not touch the disk"


def test_writer_refuses_a_secret_anywhere_in_the_tree(tmp_path):
    payload = {"level1": {"level2": [{"note": "token sk-proj-9dQ2mXb7Vc4RtY8Np1"}]}}
    with pytest.raises(EvidenceLeak):
        write_json(tmp_path / "x.json", payload, gate())


def test_writer_accepts_counts_hashes_and_short_labels(tmp_path):
    payload = {
        "gated": 81_152,
        "quarantined": 0,
        "per_file": {"default/MEMORY.md": 13},
        "hashes": {"default/MEMORY.md": [fact_hash("a fact")]},
        "kinds": ["kanban.task.status", "message.user"],
        "status": "completed",
        "nothing": None,
    }
    written = write_json(tmp_path / "counts.json", payload, gate())
    assert written.is_file()
    assert json.loads(written.read_text())["per_file"]["default/MEMORY.md"] == 13


def test_writer_accepts_gated_text(tmp_path):
    written = write_json(
        tmp_path / "script-ir.json",
        {"line": Gated("Sahil: the build is green.")},
        gate(),
    )
    assert json.loads(written.read_text())["line"] == "Sahil: the build is green."


def test_validate_lists_every_problem_without_writing(tmp_path):
    payload = {"a": "mail me at jane.doe@example.com", "b": {"c": "x" * 5000}}
    problems = validate(payload, gate())
    assert len(problems) == 2
    assert any("looks like raw text" in problem for problem in problems)


def test_write_text_checks_rendered_scripts(tmp_path):
    with pytest.raises(EvidenceLeak):
        write_text(tmp_path / "script.md", f"# notes\n\n{RAW_MEMORY}", gate())
    assert write_text(tmp_path / "ok.md", "# Episode\n\nSahil ships.", gate()).is_file()


def test_private_writer_sets_mode_600(tmp_path):
    target = write_private_json(tmp_path / "private" / "snap.json", {"a": 1})
    assert stat.S_IMODE(os.stat(target).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(target.parent).st_mode) == 0o700


def test_assert_no_raw_text_scans_existing_files(tmp_path):
    dirty = tmp_path / "old-memory-facts.json"
    dirty.write_text(json.dumps({"facts": [RAW_MEMORY]}), encoding="utf-8")
    clean = tmp_path / "clean.json"
    clean.write_text(json.dumps({"gated": 1}), encoding="utf-8")
    problems = assert_no_raw_text([dirty, clean], gate())
    assert len(problems) == 1
    assert "old-memory-facts.json" in problems[0]


# --------------------------------------------------------------------------- #
# the private snapshot
# --------------------------------------------------------------------------- #


def test_snapshot_stores_hashes_and_gated_text_but_never_raw_text(tmp_path):
    facts = {"default/MEMORY.md": [RAW_MEMORY, "a harmless fact"]}
    gated = [gate().redact_text(RAW_MEMORY)[0], "a harmless fact"]
    snapshot = build_snapshot(
        facts,
        captured_at=1.0,
        gated_text={"default/MEMORY.md": list(gated)},
    )
    store = SnapshotStore(tmp_path / "state")
    path = store.save(snapshot)

    payload = json.loads(path.read_text(encoding="utf-8"))
    entry = payload["files"]["default/MEMORY.md"]["facts"][0]
    assert entry["hash"] == fact_hash(RAW_MEMORY)
    assert "jane.doe@example.com" not in json.dumps(payload), "raw memory reached the snapshot"
    assert "/home/kensei" not in json.dumps(payload)
    assert "[REDACTED:" in entry["gated"]


def test_snapshot_hashes_only_view_has_no_text():
    snapshot = build_snapshot(
        {"p/MEMORY.md": ["fact one"]}, captured_at=1.0, gated_text={"p/MEMORY.md": ["fact one"]}
    )
    view = snapshot.as_hashes_only()
    assert view["per_file"]["p/MEMORY.md"]["hashes"] == [fact_hash("fact one")]
    assert "gated" not in json.dumps(view)
    assert "fact one" not in json.dumps(view)


def test_snapshot_roundtrip_diffs_on_hashes(tmp_path):
    store = SnapshotStore(tmp_path / "state")
    first = build_snapshot({"p/MEMORY.md": ["alpha", "beta"]}, captured_at=1.0)
    store.save(first)
    assert store.hashes_by_file() == {"p/MEMORY.md": [fact_hash("alpha"), fact_hash("beta")]}

    second = build_snapshot({"p/MEMORY.md": ["alpha", "gamma"]}, captured_at=2.0)
    store.save(second)
    old = set(first.hashes_by_file()["p/MEMORY.md"])
    new = set(second.hashes_by_file()["p/MEMORY.md"])
    assert new - old == {fact_hash("gamma")}
    assert old - new == {fact_hash("beta")}


def test_snapshot_ignores_an_older_version(tmp_path):
    store = SnapshotStore(tmp_path / "state")
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text(json.dumps({"v": 1, "files": {}}), encoding="utf-8")
    assert store.load() is None


def test_state_dir_inside_evidence_is_refused(hermes_env, tmp_path):
    """The private snapshot may never be placed inside an evidence folder."""
    from adapters.hermes.pipeline import PipelineConfig, run_pipeline

    with pytest.raises(ValueError) as excinfo:
        run_pipeline(
            PipelineConfig(
                data_dir=tmp_path / "evidence",
                state_dir=tmp_path / "evidence" / ".state",
                days=28,
                use_model=False,
            )
        )
    assert "state_dir must not be inside data_dir" in str(excinfo.value)
