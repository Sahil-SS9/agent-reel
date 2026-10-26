# M1 report: PASS

## Plain-English summary

- The four audit fixes are done, each in its own commit with its test: `privacy` plus a sealed post-gate payload (F1), no more leaked private copies and cleanup on any exit path (F2), the exact read-only claim (F3), and `$TMPDIR` in docs and examples (F4).
- The story engine works end to end: 80,737 gated events from the last 7 days turn into 400 beats, 3 arcs, a canon with facts traced to event ids, and a **6-panel episode script** whose dialogue came from the local model, with every line carrying its source event ids.
- The redaction gate passes with room: **232 labelled synthetic items, 100% on every category, zero leaks** — including 100% on person, client and project names. Quarantine is honest: when the model errors, the event is dropped, never released.
- Determinism is proven twice: byte-identical canon and IR on a re-run in deterministic mode (pinned window) **and** in model mode (cache reuse).
- Nothing was installed in Hermes, no push, no images (0/40 used in M1 — script only, as specified).

Commit: `19964cd` (latest; engine `0c9041f`, refinements `c855bd4`, signal cleanup `d416d27`,
evidence regenerated `19964cd`).
Audit fixes: `a37fca9` (F1), `ed872ae` (F2), `c8d54d9` (F3), `66fd89f` (F4). Branch: `main`.

## Gate results

| Gate item (HANDOFF §4, M1) | Result | Evidence |
|---|---|---|
| Redaction benchmark, ≥200 synthetic labelled items | **VERIFIED** — 232 items, 11 categories | `build-evidence/M1/redaction-benchmark.json` (outside the repo) |
| 100% recall on secrets | **VERIFIED** — 51/51 caught, 0 leaked | `redaction-benchmark.txt` |
| ≥95% recall on names | **VERIFIED** — person 40/40, client 14/14, project 10/10 (100%) | `redaction-benchmark.txt` |
| Every IR line resolves to real event ids | **VERIFIED** — `validate_ir` in the pipeline plus a test | `run-live/script-ir.json`, `tests/test_m1_engine.py` |
| Same input twice → byte-identical canon and IR | **VERIFIED** — deterministic mode (pinned window) and model mode (cache) | `det-canon-1.json` == `det-run/canon.json`; `det-model-canon-1.json` == `det-model/canon.json`; same for the IR |
| Real-data dry run: one episode script, last 7 days, redacted, script only | **VERIFIED** — 6 panels, writer `llm`, 0 quarantined | `run-live/episode-script.md`, `run-live/metrics.json` |
| Arc template: each panel causes the next | **VERIFIED** — roles are chosen chronologically and committed in order; a test asserts the timestamps rise | `run-live/arcs.json`, `tests/test_m1_engine.py::test_arc_has_the_template_roles_in_order` |
| Ingest idempotent on re-run | **VERIFIED** — same event ids, no duplicates, second run byte-identical | determinism evidence above |
| Beats → arcs, canon with retcon log, episode planner, Script IR, cache | **VERIFIED** | `canon/beats.py`, `arcs.py`, `canon.py`, `episode.py`, `cache.py` |
| F1 privacy + post-gate payload | **VERIFIED** — 13 tests | commit `a37fca9`, `tests/test_gate.py` |
| F2 no leaked copies | **VERIFIED** — 8 tests; the default snapshot root stays empty after a full run, a failing one, and after SIGTERM | commits `ed872ae`, `d416d27`, `tests/test_snapshot_cleanup.py` |
| F3 exact read-only wording | **VERIFIED** — 5 tests | commit `c8d54d9`, `tests/test_docs_claims.py` |
| F4 `$TMPDIR` | **VERIFIED** — 2 tests | commit `66fd89f`, `tests/test_docs_claims.py` |
| Images generated | **NOT APPLICABLE** — 0/40 (script only in M1) | — |

## Real-data run (last 7 days)

```
events ingested          81,152
events with text          8,319   (bounded, priority ordered)
gated                     81,152   (deep-gated subset: 14 events)
quarantined                    0
beats                        400   (cap)
arcs                           3   (primary + rivalry + montage candidates)
panels                         6
dialogue                    llm
wall clock                 128 s   (ingest 3.3 s, text 22.2 s, vocabulary 82.0 s, gate 127.1 s, deep 127.5 s)
```

Findings by category in that week: `path` 4,337, `project_name` 437, `person_name` 365,
`ip` 193, `email` 140, `secret` 103, `health` 1.

The script reads as one arc: a latency spike on the local model server, a missing
timeout key found during diagnosis, a worker that gives up at the climax, then the
fix holding in the aftermath and the win. Six panels, six distinct arc roles, each
one caused by the previous panel.

The dialogue is **not quoted here**: output from a real-data run belongs in the
evidence folder (ground rule 5), so read `build-evidence/M1/run-live/episode-script.md`.
What M1 can say from inside the repo is the structure: 6 panels, roles
setup/hidden_problem/diagnosis/climax/aftermath/win, writer `llm`, every line
carrying one source event id, 0 panels without text, leak scan clean.

## Redaction benchmark

| Category | Caught | Quarantined | Leaked |
|---|---|---|---|
| secret | 51/51 | 0 | 0 |
| email | 24/24 | 0 | 0 |
| phone | 18/18 | 0 | 0 |
| ip | 15/15 | 0 | 0 |
| path | 20/20 | 0 | 0 |
| url_token | 12/12 | 0 | 0 |
| person_name | 40/40 | 0 | 0 |
| client_name | 14/14 | 0 | 0 |
| project_name | 10/10 | 0 | 0 |
| financial | 16/16 | 0 | 0 |
| health | 12/12 | 0 | 0 |

Recall is measured as *not leaked*: an item counts against the gate only if it is
released with the labelled span still present. A model failure quarantines the
item, which is the safe outcome, and is reported separately rather than being
counted as a catch.

Deterministic-only mode for comparison: secrets, email, phone, ip, path and
url_token stay at 100%; names and money are the model pass's job and leak without
it (`redaction-benchmark-deterministic.txt`).

## Commands to reproduce

```bash
cd <repo>
export TMPDIR="${TMPDIR:-$HOME/.hermes/cache/scratch}"   # rig convention: scratch, not the system temp dir

# tests: expect "156 passed"
.venv/bin/python -m pytest

# the redaction gate (deterministic only)
.venv/bin/python eval/redaction/run.py --llm none

# the redaction gate with the model pass, on the rig's local route (no keys)
.venv/bin/python eval/redaction/run.py --llm local --llm-url http://127.0.0.1:8091/v1 --deep

# the engine, deterministic
.venv/bin/python -m adapters.hermes.pipeline --data-dir "$TMPDIR/reel" --days 7

# the engine, with the model pass (bounded, so a slow local model cannot stall a run)
.venv/bin/python -m adapters.hermes.pipeline --data-dir "$TMPDIR/reel" --days 7 \
  --llm local --llm-url http://127.0.0.1:8091/v1 --max-vocabulary 240 --max-deep-events 14

# determinism: pin the window, run twice, compare
.venv/bin/python -m adapters.hermes.pipeline --data-dir "$TMPDIR/det" \
  --since <epoch> --until <epoch> --llm none
```

## Tests

156 passed, 0 failed. New in M1:

| File | Covers |
|---|---|
| `tests/test_gate.py` (13) | F1: privacy defaults/validation, JSONL roundtrip, the seal, no direct construction, no double gating, downstream refusal |
| `tests/test_snapshot_cleanup.py` (8) | F2: close, GC, interpreter exit without close, SIGTERM (child copies a DB, kills itself, exits 143, root empty), a full adapter run, a failing run, env-var root |
| `tests/test_docs_claims.py` (7) | F3 exact wording everywhere it is claimed; F4 no system-temp paths in docs |
| `tests/test_redaction_gate.py` (23) | deterministic shapes, no double masking, timestamps survive, residue fails closed, quarantine on model error, vocabulary learned/masked/cached, allowlist, fail-closed classifier |
| `tests/test_m1_engine.py` (22) | beats, beat types, determinism, tool calls are not beats, arc roles chronological and distinct, rivalry arc, canon facts with event ids, retcon log, nemesis promotion, strip vs chapter, IR traceability, staging, LLM writer fallback |
| `tests/test_pipeline.py` (8) | end-to-end on the synthetic home, IR traceability, byte-identical second run, memory snapshot written and diffed, leak scan clean, metrics, quarantine surfaced |
| `tests/test_benchmark.py` (7) | dataset size/labels/no real fingerprints, deterministic thresholds, names need a model, quarantine vs leak |

## Deviations and decisions taken inside M1

1. **Pinned window for determinism.** "Same input twice" cannot mean "two runs at different times" on a live fleet, so the pipeline takes `--since`/`--until` and the determinism evidence pins them. Without a pinned window a re-run legitimately sees a different week.
2. **Model pass split into vocabulary + spans.** A per-message model pass over 8,491 texts would be thousands of calls. Instead every distinct name candidate in the window is classified once (batched, cached, capped at `--max-vocabulary`, default 240/400) and masked everywhere; free-text money and health spans are only looked for on the story subset. Both are recorded per event (`payload.gate.deep`, `model_pass`).
3. **Text fetching is bounded** (`--max-text-events`, priority ordered: user messages and kanban first, tool output last). 80,526 events, 8,491 texts. Events without text still pass the deterministic gate; their beats use structural descriptions instead of prose.
4. **Fail-closed classifier.** A model answer in unrecognised wording ("private_person", "customer") is mapped onto a category, and anything unmapped becomes `person_name`. A skipped candidate is treated as unanswered, not safe.
5. **Reasoning models.** The rig's local route returns `content: null` when it spends the budget on `reasoning_content`; the client disables thinking for JSON tasks. Without that, 5% of benchmark items failed and looked like leaks.
6. **`tool.call` is not a beat.** One row per tool call means tens of thousands per week. Tools appear in canon as artifacts; level-ups come from the skill ledger.
7. **Arc role selection is greedy and chronological**, not "pick the best beat per role then re-sort". The earlier approach silently produced 4-panel strips.
8. **Titles behind ContentRef** (owner decision 3). `--show-titles` on the M0 summary is the only thing that still prints them, and it says so.

## KENSEI defaults relied on

- **P1** (`plugin_data_dir`): the memory-facts snapshot and the model cache live in the pipeline's `--data-dir`, which is that directory's stand-in until the plugin exists (M2).
- **P4** (privacy default `private`): every event defaults to `private` and the gated payload records it; nothing in M1 exports.

## Open questions for the owner (5)

1. **Panel 5 and 6 can repeat a line** when two arc roles resolve to the same beat summary (seen in the real run). I can diversify by pulling the extra dialogue from the beat's neighbouring events, or accept one echo as a comic beat. Recommendation: diversify in M2, since the renderer will change the pacing anyway.
2. **The episode title reads functionally** ("The week default, denji-reviewer, octacon had"). I can either let the model write the title (one more cached call) or keep it derived. Recommendation: model-written title in M2, reviewed with the art.
3. **Vocabulary cap.** 240 candidates is a cost bound; rare names outside the story subset are not classified. Recommendation: keep the cap, because the deep pass covers everything the episode touches, and raise it only for a public export.
4. **Story selection is "strongest struggle of the week".** For a quiet week the arc picks whatever failed, which may not be the week's real story. Recommendation: add a "boring week = training-montage or joke arc" rule in M2 after seeing a few real scripts.
5. **`task_comments` are read but rarely beat-worthy** (they are mostly governance notes). Keep them as canon texture or promote comment threads that contain decisions? Recommendation: keep as texture; revisit after M2.

## Known gaps / not checked

- Model-pass coverage on the real week is deliberately bounded (14 deep-gated events out of 80,526). The benchmark measures the passes properly; the real run is a dry run, not a full deep-gate of the week.
- The local route is slow under load (≈15-20 s per call when the fleet is busy), which is why the deep pass is capped. A hosted route would be faster.
- `beats` hit the 400 cap; the cap keeps the strongest beats but drops the tail of the week.
- Panel captions use UTC; a local timezone would read better.
- No image step, so nothing here proves the renderer. That is M2.
- The `financial`/`health` thresholds (90%) only apply in `--deep` mode, and the report says which mode ran — they are not part of the M1 gate.
