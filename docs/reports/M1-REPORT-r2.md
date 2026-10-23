# M1-r2 report: PASS

Rework of the M1 audit findings (docs/reviews/M1-AUDIT.md). Verdict first: all five
P0/P1 findings are fixed and re-verified; two P2s are fixed; one honest quality gap
(see "Known gaps") is stated rather than papered over.

Commit: `a6e9d89` (latest; rework commits `fcc29fd` F4, `7b2ef57` F1, `2ff28fa` F2,
`645924d` F3, `61356e8` F5/F6/F7, `59faaf5` one-thread strips, `c67e382` gated cast
names, `7985dd4` this report, `a6e9d89` state-dir guard). Branch: `main`. Nothing
pushed, nothing installed in Hermes.
203 tests pass at this commit.

## Plain-English summary

- The script no longer invents facts. Every line is checked against the gated text of
  the events it cites: 8 of 8 lines grounded on the real week, 0 rewritten, 0 dropped.
  The writer is told not to invent, and any line it does invent is replaced by a
  literal quote from the evidence or removed.
- A story is now one thread: the live episode comes from a single session lineage
  (`primary_thread: session`), and the causation check passes (`causation_verified:
  true`) because every step stays in that thread and moves it forward - not because
  the timestamps rise.
- The held-out set the auditor asked for exists and is clean: 36 separately written
  items, **17/17 secrets caught, 100% on every category, 0 leaked, 0 quarantined**.
  The Discord-in-a-path leak and the plain-text "the password is X" leak are both
  covered by the deterministic pass now.
- The memory dump is gone: no snapshot in evidence, the private store is mode 600 and
  holds per-fact hashes plus gated text, and the evidence writer refuses any value the
  gate would change.
- Model pass is stable: 0% quarantine (threshold 5%), retried on empty content with an
  optional fallback route, and the run reports items/s.

## Gate results

| Audit finding | Result | Evidence |
|---|---|---|
| M1-F1 no invented facts | **FIXED** — grounding gate (terms + entailment), 32-case eval, 8/8 lines grounded on the live run | `eval/grounding/`; `run-live/metrics.json` → `grounding` |
| M1-F2 one real story | **FIXED** — threads (task family / session lineage / shared subject), 4-panel strip from one session thread, causation verified | `canon/threads.py`; `run-live/arcs.json`; `causation_verified: true` |
| M1-F3 secrets in URL paths and plain-language credentials | **FIXED** — Discord/Slack webhooks, `/api/webhooks/<id>/<token>`, long opaque path segments, "the password is X", bare key headers; held-out set 36 items, 0 leaked | `benchmark-heldout-deep.txt` |
| M1-F4 raw memory in evidence | **FIXED** — three files deleted, snapshot now private (mode 600, hashes + gated text), evidence gets counts/hashes, writer refuses ungated text | `adapters/hermes/evidence.py`, `snapshot.py`; `tests/test_evidence_and_snapshot.py` |
| M1-F5 model pass stability | **FIXED** — empty content retried then fallback route; 0.0% quarantine; items/s reported; run fails above 5% | `run-live/metrics.json` → `quarantine_rate`; benchmark output |
| M1-F6 presentation | **FIXED** — cast map (default → Kensei, octacon → Octacon), captions in Europe/London, one cached grounded title, duplicate lines dropped | `canon/casting.py`, `canon/titling.py`; `tests/test_presentation.py` |
| M1-F7 tool names as beats | **FIXED** — a tool result is never a beat on its own; tool output is evidence for a thread's beat | `canon/beats.py`; `tests/test_presentation.py` |

Supporting gates re-run at this commit: **202 tests pass**; read-only proof PASS (no
files created, renamed, truncated or deleted under `~/.hermes`); dev benchmark 232 items
**100% on all eleven categories, 0 leaked, 0 quarantined**.

## Real-data dry run (script only, last 7 days)

```
events ingested          83,253
gated                    83,253   (deep-gated subset: 14 events)
quarantined                   0   → quarantine rate 0.0% (threshold 5%)
beats                       400
threads                     451
arcs                          3
panels                        4   (D7 says 4-6)
writer                      llm
primary thread           session
causation verified          yes
grounding        8/8 lines, rate 1.0, 0 rewritten, 0 dropped
title     "Implement approved next Modernisation Engine slice" (derived; the model
           title was refused as ungrounded, which is the gate working)
wall clock                 159 s
```

Redaction findings in that week: `path` 3,559 · `secret` 375 · `ip` 196 · `project_name`
160 · `email` 137 · `person_name` 36 · `health` 1.

The full script text lives in the evidence folder, not in the repo:
`build-evidence/M1-r2/run-live/episode-script.md` (ground rule 5).

## Redaction benchmarks

| Set | Mode | Items | Secrets | Names | Quarantined | Leaked |
|---|---|---|---|---|---|---|
| dev (`dataset.jsonl`) | model + deep | 232 | 51/51 | 64/64 | 0 | 0 |
| held-out (`dataset-heldout.jsonl`) | model + deep | 36 | **17/17** | 7/7 | 0 | 0 |
| held-out | deterministic only | 36 | **17/17** | n/a | 0 | 0 |

Throughput: the held-out cold run did 36 items in 21.9 s (1.6 items/s); the dev run
reported 222 items/s on a warm cache. The pipeline gated 83,253 events in 158 s. Both
deep benchmarks were re-run at the rework HEAD (14:16) and still report 100% on every
category with 0 leaked; those re-runs were served from the model cache, which is the
SPEC §4 guarantee, so the throughput line above quotes the cold numbers.

Recall is measured as *not leaked*; a quarantine counts as safe and is reported
separately, and the gate fails if more than 5% of a run is quarantined.

## Deviations and decisions inside the rework

1. **Threads before arcs.** The M1 arc builder is gone: `build_arcs` takes threads and
   beats, never a bare event stream. A thread needs four beats for a strip (D7's 4-6
   panel range), and a short chain is filled from the *same* thread's unused beats.
2. **Causation is a check, not a claim.** `causal_check` verifies same thread + forward
   lifecycle (kanban rank) or later timestamp in the same lineage. The report line
   "each panel causes the next" is backed by `causation_verified` in the metrics, and
   would read NOT VERIFIED if the check failed.
3. **Grounding rewrites rather than drops where it can.** An unsupported line becomes a
   literal quote from its evidence; only when there is nothing to quote is it dropped.
   That is why the live lines read like the task titles they came from.
4. **Character names are gated too.** A profile whose name matches a learned sensitive
   term gets a neutral alias (`Agent N`). After adding the fleet's own agent names to
   the allowlist, the live cast is Sahil, Kensei, Denji, Gojo, The Reviewer, Octacon.
5. **The vendor-prefix rules needed a left boundary.** Hermes' `sk-` pattern has none,
   so the skill name `kanban-blocked-task-resolution` matched it and the evidence
   writer refused the output. The writer was right; the rule was too loose.
6. **The memory snapshot lives outside evidence** in `$REEL_STATE_DIR` (default
   `~/.local/state/scrollback-reel`), mode 600; `plugin_data_dir` in the live plugin.
   During the rework I passed a state dir *inside* build-evidence and put the snapshot
   back next to the evidence; it is deleted and `run_pipeline` now refuses any
   `state_dir` under `data_dir` (`a6e9d89`).

## Known gaps (stated, not hidden)

- **The dialogue reads like task descriptions.** Grounding is doing its job: the model's
  invented lines were refused and replaced by literal quotes, so panels 1-3 are the
  thread's own task titles. Better prose needs a writer that can be creative *inside*
  the evidence (for example: give it the thread's gated titles and ask for a line that
  quotes one of them), which is a design change I would rather agree with the owner
  before making.
- **Four panels, not six.** The thread's lifecycle only supplies four distinct moments.
  D7 allows 4-6, so this is inside spec, but a richer week will read better.
- **The title is the derived one.** The model's title was refused as ungrounded, which
  is the gate working; a title prompt that quotes the thread's own words would land.
- Deep-gate coverage is still bounded (14 events), and the local model is slow under
  load (the run took 159 s for 83,253 events, most of it the model pass).

## Commands to reproduce

```bash
cd /home/kensei/repos/hermes-scrollback-reel
export TMPDIR="${TMPDIR:-$HOME/.hermes/cache/scratch}"

.venv/bin/python -m pytest                                             # 202 passed
.venv/bin/python eval/grounding/run.py                                 # 32/32 both ways
.venv/bin/python eval/redaction/run.py --llm none                     # dev, deterministic
.venv/bin/python eval/redaction/run.py --llm none \
    --dataset eval/redaction/dataset-heldout.jsonl                     # held-out, deterministic
.venv/bin/python eval/redaction/run.py --llm local \
    --llm-url http://127.0.0.1:8091/v1 --deep                          # dev, model
.venv/bin/python eval/redaction/run.py --llm local \
    --llm-url http://127.0.0.1:8091/v1 --deep \
    --dataset eval/redaction/dataset-heldout.jsonl                     # held-out, model
.venv/bin/python -m adapters.hermes.pipeline --data-dir "$TMPDIR/reel" --days 7 \
    --llm local --llm-url http://127.0.0.1:8091/v1 \
    --max-vocabulary 240 --max-deep-events 14
bash scripts/readonly_proof.sh                                         # VERDICT: PASS
```
