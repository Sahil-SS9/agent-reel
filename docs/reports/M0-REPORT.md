# M0 report: PASS

## Plain-English summary

- The read-only history adapter works. It reads all 65 Hermes profiles plus the fleet-wide kanban, cron, skills and memory stores, and turns them into one clean event stream: **78,883 events over the last 7 days in 3.2 seconds**, using 36 MB of memory.
- **No files are created, renamed, truncated or deleted under `~/.hermes`.** `strace` shows every data file opened `O_RDONLY`, zero creations, zero rename/unlink/mkdir/chmod. The exact claim matters (audit F3): existing `-shm` wal-index pages are updated by normal SQLite read locking, as they are for any SQLite reader. No database content changes. Getting to "creates nothing" needed a real fix: SQLite creates `-wal`/`-shm` sidecar files even for a read-only connection, so the adapter now reads the SQLite header first and reads a private copy whenever creating sidecars would otherwise happen.
- The synthetic 4-week, 4-profile fixture is built and the adapter reads it as if it were a real Hermes home. Tests are green: **67 passed**, no network, no real history in the repo.
- Real history stayed out of the repo: the only real-data output is a summary written to the evidence folder. It contains counts and session titles, and a pre-flight leak scan on it comes back **clean**.
- Two things are honestly short of the letter of the handoff: memory *diffs* need a prior snapshot (Hermes keeps no memory history), and skill usage is collapsed to the latest timestamp per skill. Both are documented, with a fix path.

Commit: `ec91e37b6e4d0892e05550c14e0ce9cf134186da` (build commit; this report is the next commit)
Branch: `main`

## Gate results

| Gate item (HANDOFF §4, M0) | Result | Evidence |
|---|---|---|
| Read-only proof: no write opens under `~/.hermes`, or every DB opened `mode=ro` and nothing else opened for writing | **VERIFIED** — no files created, renamed, truncated or deleted; existing `-shm` wal-index pages are updated by normal SQLite read locking (exact wording per audit F3) | `build-evidence/M0/readonly-proof-verdict.txt`, `strace-openat.log`, `strace-strict.log`, `strace-strict-synthetic.log` |
| Real-data summary run | **VERIFIED** (7 days, 78,883 events, 3.2 s, 36 MB RSS) | `build-evidence/M0/real-data-summary.txt` |
| Tests green | **VERIFIED** (67 passed, 0 failed, 19.4 s) | `build-evidence/M0/tests.txt` |
| `adapters/hermes/history.py` reads sessions, messages, tool calls, kanban, skills, cron, memory into one `Event` stream | **VERIFIED** | `adapters/hermes/history.py`; per-source counts in the summary |
| `canon/HERMES_SCHEMA.md` maps every source table/field to an Event | **VERIFIED** | `canon/HERMES_SCHEMA.md` |
| CLI `--days 7 --summary` prints counts per profile and source plus the last 50 sessions, no message content | **VERIFIED** | summary output; `tests/test_history_adapter.py::test_summary_is_readable_and_prints_no_message_text` asserts message text never appears |
| Synthetic fixture: 4 weeks, 4 profiles, kanban + skills + cron | **VERIFIED** | `fixtures/build_synthetic_home.py`, `tests/test_fixtures.py` |
| State verification (§3) | **VERIFIED** — all 7 expectations met | `build-evidence/M0/state-verification.txt` |
| Memory/USER "fact diffs" | **PARTIAL** — snapshot + diff implemented and tested; Hermes keeps no memory revision history, so a diff needs an earlier snapshot (`--write-memory-snapshot` then `--memory-snapshot`). First run reports snapshots. | `tests/test_history_adapter.py::test_memory_snapshot_diff_reports_added_and_removed` |
| Images generated | **NOT APPLICABLE** — 0/40 used in M0 (no image step until M2) | — |

## Commands to reproduce

```bash
cd /home/kensei/repos/hermes-scrollback-reel
export TMPDIR="${TMPDIR:-$HOME/.hermes/cache/scratch}"   # rig convention: scratch, not the system temp dir

# venv (Python 3.12; pillow, pytest, jsonschema, pyyaml)
uv venv .venv --python 3.12
uv pip install --python .venv/bin/python pillow pytest jsonschema pyyaml

# 1. tests: expect "67 passed"
.venv/bin/python -m pytest

# 2. real-data summary: expect counts per source/profile, "read plan: 68 stores: ...",
#    the last 50 sessions, and "redaction preflight: 0 hit(s)"
.venv/bin/python -m adapters.hermes.history --days 7 --summary --redaction-preflight

# 3. read-only proof: expect "VERDICT: PASS", script exit 0
bash scripts/readonly_proof.sh

# 4. synthetic home + adapter against it
.venv/bin/python -m fixtures.build_synthetic_home "$TMPDIR/reel-synthetic" --seed 7
HERMES_HOME="$TMPDIR/reel-synthetic" .venv/bin/python -m adapters.hermes.history --days 7 --summary

# 5. write an event stream (refuses any path inside the repo)
.venv/bin/python -m adapters.hermes.history --days 7 --out "$TMPDIR/reel-events.jsonl"
```

## State verification (HANDOFF §3)

Run on 23/10/26, full output in `build-evidence/M0/state-verification.txt`:

| Check | Expected | Got |
|---|---|---|
| `git log --oneline -1` | pack commit | `1e7d3a4 Apply kensei-review conditions...` |
| `merge-base --is-ancestor a4072ce7e6 upstream/main` | exit 0 | exit 0 |
| `hermes --version` | v0.22.2+ KenseiAgent fork | `v0.22.2+4106.g513ab22 · fork b4cd1a93 · local 513ab229 (+1527 carried commits)` |
| `hermes plugins --help` | lists validate and doctor | both listed |
| `ls ~/.hermes/profiles/*/state.db \| wc -l` | ~65 | 65 |
| `select count(*) from sessions` (mode=ro) | positive | 10,918 |
| Multiverse anime dir | `sahil__sheet__anime__v01.png` | present |

## Tests

67 passed, 0 failed (`build-evidence/M0/tests.txt`):

| File | Covers |
|---|---|
| `tests/test_events.py` | event ids deterministic and unique, JSONL roundtrip, unknown source/kind rejected, canon imports no Hermes (D2) |
| `tests/test_ro_readonly.py` | `mode=ro` + `query_only` refuse INSERT/UPDATE/DELETE/CREATE; audit records only `ro`/`r`; URI-unsafe paths refused |
| `tests/test_stores.py` | journal-mode sniffing; in-place vs snapshot decisions; **no sidecar created next to the original DB**; locked read-only tree still reads; snapshot tree cleaned up; large-DB fallback |
| `tests/test_history_adapter.py` | all 7 sources emit; determinism (two runs byte-identical); no raw text in payloads; `fetch_content` works and refuses unsafe refs; profile/source filters; window edges; cron job names; kanban heartbeat filtering; memory diff; summary prints no message text; `--out` inside the repo refused; read-only audit clean after a run; unknown columns tolerated |
| `tests/test_fixtures.py` | fixture shape (4 profiles, 4 weeks, kanban/skills/cron/memory), reproducibility, read as a Hermes home |
| `tests/test_leakscan.py` | emails, phones, tokens, keys, IPs, home paths, high-entropy strings flagged; ordinary prose is not |

## Deviations from SPEC / decisions, and why

1. **The `Event` schema is defined here.** SPEC §4 lists the stage order and names the `Panel` and `Cache` additions, but does not enumerate `Event` fields (the v1 document it was rewritten from is not in the pack). So `canon/events.py` defines a versioned schema (`SCHEMA_VERSION = 1`) and `canon/HERMES_SCHEMA.md` maps every Hermes field to it. If the owner has the v1 schema, this is the one thing to reconcile before M1.
2. **Text never enters the event stream.** Payloads carry counts, digests and structural keys only; raw text sits behind a `ContentRef` and is fetched by the ingest stage, which is where M1's redaction gate goes. This is a deliberate reading of ground rule 5 ("real history never enters the repo"): the safest place to enforce it is structurally, not by discipline.
3. **An extra read-only layer was needed.** `sqlite3 mode=ro` prevents SQL writes but still creates `-wal`/`-shm` sidecars when they are absent — `strace` caught the adapter creating two files in `~/.hermes/cron/`. `adapters/hermes/stores.py` now sniffs the SQLite header (100 bytes, `O_RDONLY`) and reads a private copy when sidecars are missing, so nothing is created. Files >256 MB fall back to an in-place read and say so in the summary (no silent behaviour).
4. **`cwd` is reduced to a basename** and long opaque ids in titles are masked (`local-b8f628f7…`). Full paths are an out-of-project leak, and the M0 gate needs titles printed.
5. **Titles are embedded in `session.started` / `kanban.task.created` payloads** because the gate requires printing them. They are human/model text and must move behind a `ContentRef` (or pass the redaction gate) before any export. Flagged for M1.
6. **Memory facts are snapshot+difft**, as explained above. No invented history: `memory.fact` (present) on first run, `memory.fact.added`/`.removed` when a prior snapshot is supplied.
7. **Skill usage is a collapsed milestone.** The ledger stores `last_used_at` and a `use_count`, not a per-use log, so `skill.used` carries the count instead of N events. Not fabricated into per-use events.
8. **Kanban noise is filtered and counted.** `heartbeat` (2,607 rows), `commented`, `attached`, `linked` are not story material; they are dropped from the stream and reported as "658 noise rows filtered" in the summary rather than silently disappearing.
9. **`--profile X` scopes everything that carries a profile** (sessions, messages, tool calls, skills, memory, kanban-by-assignee) and omits fleet-level cron runs (they have no profile attribution). Documented in the CLI help.
10. **Extras not in the handoff** (small, all listed so they can be rejected): `adapters/hermes/leakscan.py` + `--redaction-preflight` (pre-flight scan of evidence text for emails/tokens/keys/paths — not the M1 gate); `pyproject.toml` (pytest config); `conftest.py` (repo root on `sys.path`); `scripts/readonly_proof.sh`.
11. **`adapters/hermes/history.py` runs as `python -m adapters.hermes.history`.** The repo is not an installable package yet (no `pyproject` build backend), so M2 will need to decide the packaging story when `plugin.yaml` lands.

## KENSEI defaults relied on

None of P1–P4 are exercised in M0 (no storage, styles, cast or privacy levels yet). Two forward-looking notes:

- **P1** (storage via `plugin_data_dir`): the memory-facts snapshot should live there once the plugin exists, so diffs work from run 2 without a CLI flag. Right now it is an explicit `--write-memory-snapshot` path.
- **P4** (privacy default `private`): M0 emits no export, so nothing to gate yet; the title-in-payload deviation above is the first thing P4 will need to cover.

## Open questions for the owner (5)

1. **Reconcile the `Event` schema with the old v1 document?** My recommendation: accept `canon/events.py` + `canon/HERMES_SCHEMA.md` as the schema of record unless you still have the 21/10 v1 spec, in which case send it and I will fold in any missing fields before M1.
2. **Memory diffs:** accept snapshot-diff (recommended — it is the only thing Hermes' data supports), or do you want the adapter to keep its own append-only fact journal so real per-week deltas exist without a flag? Recommended: snapshot in plugin storage at each run (P1).
3. **Titles and task titles in event payloads:** move them behind `ContentRef` at M1 (recommended, so payloads stay text-free), or keep them for convenience and rely on the redaction gate? Recommended: move them.
4. **`--profile` semantics:** confirm "scopes everything with a profile, drops fleet cron" (recommended) versus "always reads the whole fleet".
5. **Is reading `task_comments` worth it?** Kanban comments are the richest "who said what" signal the fleet produces, and M0 does not read them (not in the handoff list). Recommended: add as an M1 source, but only after the redaction gate, since comments are free text.

## Known gaps / not checked

- No real event stream was materialised from real history. By design: M0 produces a summary only, so no real text left the databases. The JSONL writer exists and is exercised against the synthetic home and `$TMPDIR` only.
- Skill backfill granularity is limited to milestones (see deviations).
- `~/.hermes/a2a_audit.jsonl` is absent on this rig, so the A2A source is untested (SPEC lists it as optional).
- Performance is measured for a 7-day window only: 3.2 s wall, 36 MB peak RSS. A 30-day window and the M1 ingest of full text are unmeasured.
- The adapter tolerates unknown columns (tested), but it has only been run against this fork's schema. Upstream `a4072ce7e6` was checked for ancestry, not executed against.
- `hermes plugins validate .` / `doctor . --ci` are M2 gates; the repo has no `plugin.yaml` yet, so they were not run.
- The redaction gate itself, beats, arcs, canon and Script IR are M1; nothing in this stage claims them.
