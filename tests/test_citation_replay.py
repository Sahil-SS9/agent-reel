"""t_abdaa3a9 (Quan re-sample at 0689404): every citation replays from the trace alone
(finding 3), and a statement cites the events that state it, stating event first (1, 2, 4)."""

from __future__ import annotations

import json

from conftest import StubWriter
from adapters.hermes.pipeline import PipelineConfig, run_pipeline
from canon.episode import pool_digest, support_events
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


# findings 1, 2 and 4: a statement cites the events that state it, stating event first ----
# Shapes of Quan's plan-v4 p7, p12 and p2 (synthetic text, same word pattern): a long
# status summary shares a word with every line, while the event that states the line says
# it in one sentence; record fields ("content_digest: ...") are not words a line can state.
SUMMARY = (
    "Summary: the second job's code is finished and green; the numbers are not in yet.\n\n"
    "- Name links and the v2 context block are both ported, each behind its switch, off by "
    "default. It adds one search per name; linked memories score half the match.\n"
    "- Full suites pass on the final commit (1,379 SQLite, 1,440 PostgreSQL, zero "
    "failures); lint and types clean. Five places carry the new version. Report queued.\n"
    "content_digest: sha256:abc\nrole: assistant"
)
STATING_P7 = (
    "That's my measurement run finishing cleanly (exit 0). Already reported: context v2 "
    "passes, name links fail on the target category and on speed.\nrole: assistant"
)
SLOW = "Plain version. Searching long memories is slow, and the slow part misses answers."
P7 = "Better context for each search: passes. Linking memories by name: slower, and misses."


def test_the_event_that_states_a_statement_leads_its_citation():
    pool = {"summary": SUMMARY, "slow": SLOW, "stating": STATING_P7}
    ids, blocks = support_events(P7, ["stating"], pool, list(pool))
    assert ids[0] == "stating", ids
    assert blocks.startswith("That's my measurement run")
    assert "summary" not in ids  # it adds no clause the stating events leave uncovered


STATING_P12 = (
    "That's the first verify attempt; it failed with exit 127. Superseded. Traceback and all "
    "five attempts are in `VERIFY-BLOCKER.md`. Code state is unchanged; lint and types clean."
)
CAUSE = (
    "Found the real cause, and the code is fine: the verification tool is broken. I tried "
    "five ways to run it and wrote down each error; full gates pass, each attempt reported."
)
GATED = (
    "The third job's code is finished and fully gated. Recorded verification passes. Full "
    "suites on the same clean commit; each attempt written up, style report clean."
)
P12 = "Five attempts, the full error trail, a written blocker report, clean style, and more."


def test_every_clause_of_a_statement_is_backed_by_a_cited_event():
    pool = {"summary": SUMMARY, "gated": GATED, "cause": CAUSE, "stating": STATING_P12}
    ids, _ = support_events(P12, ["gated"], pool, list(pool))
    # Only the VERIFY-BLOCKER event states "a written blocker report".
    assert ids[0] == "stating", ids
    assert "summary" not in ids  # the long summary shares words but states no clause


def test_an_event_with_another_runs_figures_is_not_cited_for_a_figure_line():
    line = "Final score: 1,379 checks passed on one database, 1,440 on the other. All recorded."
    pool = {
        "other_run": (
            "Round-2 corrections applied. Final local checks: full suites 1,439 SQLite and "
            "1,500 PostgreSQL checks passed, zero failures."
        ),
        "stating": "Superseded by the final runs (1,379 SQLite, 1,440 PostgreSQL) and the recorded verification.",
        "summary": SUMMARY,
    }
    ids, _ = support_events(line, ["other_run"], pool, list(pool))
    assert "other_run" not in ids, ids
    assert ids and ids[0] in {"stating", "summary"}


def test_a_two_clause_claim_still_cites_both_stating_events():
    # Control for the figure rule: a figure-free clause keeps its own source.
    line = "Not done. Ready for the reviewer's re-check. The good run finished at 11:01, cleanly."
    pool = {
        "recheck": "Round-2 corrections are applied and ready for your re-check, not declared accepted. 1,439 passed.",
        "run": "That's the good run: the nine-run set finished at 11:01 with exit 0.",
        "summary": SUMMARY,
    }
    ids, _ = support_events(line, ["summary"], pool, list(pool))
    assert ids[:2] == ["run", "recheck"], ids
