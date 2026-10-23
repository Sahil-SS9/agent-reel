# M0 audit by KENSEI: PASS (confirmed independently)

Audited 23/10/26. Build ec91e37, report 4196d91.

## Re-run by the auditor (not taken from the report)

- `pytest`: 67 passed.
- `canon/` has no Hermes imports (grep).
- Live run under strace (`openat`, `rename*`, `unlink*`, `mkdir*`, `truncate`, `chmod`) of `history --days 7 --summary --redaction-preflight`:
  - exit 0
  - 400 data-file `O_RDONLY` opens
  - no write-flag opens of non-sidecar files under `~/.hermes`
  - no rename/unlink/mkdir/truncate/chmod under `~/.hermes`
  - redaction preflight 0 hits
- Sidecar birth times: no `-wal`/`-shm` was created by the builder's adapter. The only sidecars born today are:
  - 38 from KENSEI's own bake-off read at 02:52 (F5)
  - `shared-state.db` at 09:56 and kanban board DBs at 10:44, which were Hermes' own processes: born after the audit run had ended, and the boards are not read by the adapter
- No real history in the repo: real titles, ids and paths grepped across tests/fixtures/canon/adapters, none found.
- All leftover private copies in `~/.cache/scrollback-reel` are synthetic pytest homes. No copy of a real database remains.

## Findings

| ID | Severity | Finding | Required outcome |
|----|----------|---------|------------------|
| F1 | MEDIUM (KENSEI's pack gap) | The v1 schemas (Event/Beat/Arc/Entity/Episode/ScriptIR) were referenced but never copied into the pack. `events.py` lacks v1 `privacy`, and `payload` is pre-redaction. | Fixed in docs: SPEC §4 now has the v1 schemas verbatim. M1: add `privacy` (default private); later stages may only see the post-gate payload (`payload_redacted`). Test it. |
| F2 | LOW-MEDIUM | Tests leak private-copy dirs into the default root `~/.cache/scrollback-reel`: 85 dirs after the audit's own run, ~17 added per pytest run. They are synthetic, but the same path holds real copies on a real run that crashes before `close()`. | Tests pass `snapshot_root=tmp_path`; add an `atexit`/finaliser cleanup; add a test that the default root is empty after a run (including an exception path); delete the existing synthetic `reel-store-*` dirs. |
| F3 | LOW (wording) | "Nothing under `~/.hermes` is written": in-place reads of WAL DBs write read-marks into the existing `-shm` via shared memory (65 `-shm` mtimes changed at 10:09). Every SQLite reader does this, Hermes included, so it's accepted, but the claim must be exact. | Reword in HERMES_SCHEMA.md and reports: "no files created, renamed, truncated or deleted; existing `-shm` wal-index pages are updated by normal SQLite read locking". |
| F4 | LOW | Repro commands use `/tmp`. The rig convention is the scratch dir (`$TMPDIR` = `~/.hermes/cache/scratch`). | Use `$TMPDIR` in docs and examples. |
| F5 | LOW (KENSEI disclosure) | KENSEI's bake-off at 02:52 read every profile `state.db` with plain `mode=ro`. That created empty `-wal` + `-shm` in 19 profile dirs. They are harmless standard SQLite files and are left in place: deleting them would be another write. | None for the builder. KENSEI's comic skill now points at `sqlite-readonly-live-db`. |

## Owner decisions (recommendations; Sahil confirms)

1. Schema of record: accept `canon/events.py`, reconciled to v1 per F1.
2. Memory diffs: snapshot into `plugin_data_dir` on each run.
3. Titles: move behind ContentRef in M1, so only the gate releases them.
4. `--profile` semantics: as the builder proposed.
5. `task_comments`: yes, add in M1, behind the redaction gate.
