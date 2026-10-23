# Hermes → Event schema map (M0)

Every Hermes surface the adapter reads, and exactly how each field becomes a
normalised `Event` (`canon/events.py`). Written against the live fork
(KenseiAgent `v0.22.2+4106`, surfaces verified at upstream `a4072ce7e6`) and the
synthetic fixture in `fixtures/build_synthetic_home.py`.

Read this with `docs/hermes-surfaces.md` (where each surface is defined) and
`docs/SPEC.md` §4 (ingest → redact → beats → arcs → canon → plan → IR).

## 1. The event

| Field | Meaning |
|-------|---------|
| `id` | `ev_<blake2b12>` over `(source, kind, ts, ref, discriminator)`. Content-derived, so a re-run yields the same ids and ingest stays idempotent. |
| `ts` | Epoch seconds (UTC). Ordering key for the story timeline. |
| `source` | One of `session`, `message`, `tool_call`, `kanban`, `skill`, `cron`, `memory`. |
| `kind` | `<domain>.<what-happened>`, e.g. `message.user`, `kanban.task.created`. |
| `profile` | Owning profile slug (`default`, `ceecee`, …). Empty only for fleet-level records. |
| `actor` | Who acted: profile for user turns, tool name for tool turns, assignee for kanban. |
| `subject` | Short label: tool name, skill name, task id, status. Never free text. |
| `payload` | JSON-safe structure and digests only (see §3). |
| `ref` | Provenance: `{store, table, pk}`. `store` is a **logical** name (`main`, `profile:alpha`, `kanban`, `cron`, `skills:<profile>`, `memory:<profile>/<file>`), so no absolute path is ever embedded in an event. |
| `content_ref` | `{store, table, pk, column}` for the raw text, or `null` when there is none. |
| `derived_from` | Source event ids when an event is derived (used by later stages). |

`SCHEMA_VERSION = 1` (`canon/events.py`).

## 2. Source → table/field map

### 2.1 `session` — `state.db` → `sessions`

Read from the fleet store `$HERMES_HOME/state.db` and every
`$HERMES_HOME/profiles/*/state.db`. `profile` comes from `sessions.profile_name`
(falling back to the directory name for a profile store).

| Hermes field | Event |
|---|---|
| `started_at` | `ts` of `session.started` |
| `ended_at` + `end_reason` | `session.ended.ts`, `payload.end_reason` |
| `title` | `payload.title` (truncated to 160 chars) + `payload.title_chars`; raw text via `content_ref(column="title")` |
| `source` (`cli`/`cron`/`discord`/…) | `payload.source` |
| `model` | `payload.model` |
| `message_count`, `tool_call_count` | payload counts |
| `input_tokens`, `output_tokens` | payload counts |
| `git_branch` | `payload.git_branch` |
| `cwd` | `payload.cwd_name` — **basename only**; the absolute path is deliberately dropped |
| `parent_session_id` | `payload.parent_session_id` |
| `last_activity_at` | `payload.last_activity_at` |
| `archived` | `payload.archived` |
| `started_at < window.since` | `payload.span_in_window = true` |

A session is included when it was alive at any point in the window, even if it
began before it — long-running sessions are part of a week's story. `ts` stays
at `started_at`, so `span_in_window` is the flag that says "started earlier".

### 2.2 `message` — `state.db` → `messages`

| Hermes field | Event |
|---|---|
| `timestamp` | `ts` |
| `role` | `kind`: `user`→`message.user`, `assistant`→`message.assistant`, `tool`→`message.tool_result`, `session_meta`→`message.meta` |
| `content` | **not copied.** `payload.chars` + `payload.content_digest` (`sha256:` prefix, first 32 hex); raw text via `content_ref(column="content")` |
| `tool_name`, `tool_call_id` | payload |
| `tool_calls` (JSON) | `payload.tool_names`, `payload.tool_call_count`; one `tool.call` event each (§2.3) |
| `token_count`, `compacted` | payload |
| `active` | rows with `COALESCE(active,1) != 1` are skipped (rewound/inactive) |

### 2.3 `tool_call` — `message` rows' `messages.tool_calls` JSON

Hermes has no separate tool-call table; calls live in the assistant message JSON.
Each entry becomes one `tool.call` event, `discriminator = "<index>:<call_id>"`
so several calls in one message stay distinct.

| JSON field | Event |
|---|---|
| `function.name` (or `name`) | `payload.tool`, `subject` |
| `call_id` / `id` | `payload.call_id` |
| `function.arguments` | `payload.args_chars`, `payload.args_digest`, `payload.args_keys` (top-level argument names). The argument text is **not** copied; `content_ref(column="tool_calls")` gives the raw JSON. |

### 2.4 `kanban` — `$HERMES_HOME/kanban.db`

| Table | Event | Fields |
|---|---|---|
| `tasks` | `kanban.task.created` | `ts=created_at`, `payload.title` (160 + `title_chars`), `assignee`, `status`, `priority`, `created_by`, `tenant`, `project_id`; `content_ref(column="title")` |
| `tasks` | `kanban.task.claimed` | `ts=started_at`, `payload.assignee` |
| `tasks` | `kanban.task.finished` | `ts=completed_at`, `payload.status`; `content_ref(column="result")` |
| `task_events` | `kanban.task.status` | `ts=created_at`, `payload.kind` (the event kind), `payload.payload_keys`, `payload.payload_digest`; joined to `tasks.assignee` for `profile` |
| `task_runs` | `kanban.run.started` | `ts=started_at`, `payload.task_id`, `profile`, `step_key` |
| `task_runs` | `kanban.run.finished` | `ts=ended_at`, `payload.status`, `outcome`, `has_summary`, `has_error`; `content_ref(column="summary")` |

Filtered out (counted in `skipped_noise`): `task_events.kind` of `heartbeat`,
`commented`, `attached`, `linked` and anything else not in
`history.STATUS_EVENT_KINDS`. Their text is not story material.

### 2.5 `skill` — `skills/.usage.json` (fleet) and `profiles/*/skills/.usage.json`

One entry per skill. Only milestones are emitted, because the ledger keeps the
*latest* timestamps rather than a history.

| Ledger field | Event |
|---|---|
| `created_at` | `skill.created` |
| `last_used_at` (+ `use_count`) | `skill.used` |
| `last_patched_at` (+ `patch_count`) | `skill.patched` |
| `archived_at` (+ `state`) | `skill.archived` |
| `use_count`, `view_count`, `patch_count`, `state`, `pinned` | payload on every skill event |

`skill.used` is a *collapsed* milestone: `use_count` carries how many times.
There is no per-use timestamp in the ledger, and this adapter does not invent
one. Backfill granularity is a known limitation (§5).

### 2.6 `cron` — `$HERMES_HOME/cron/executions.db` + `cron/jobs.json`

| Field | Event |
|---|---|
| `started_at` | `cron.run.started.ts` |
| `finished_at` + `status` | `cron.run.finished.ts`, `payload.status` |
| `job_id` → `jobs.json[].name` | `payload.job_name`, `actor`, `subject` |
| `source`, `has_error` | payload; error text via `content_ref(column="error")` |

`claimed_at` is ISO-8601 text with a local offset, so string ordering across
offsets is unsafe. The query takes a deliberately loose SQL lower bound
(`since - 1 day`) and then filters on parsed epochs. Correct, not clever.

Cron runs carry no profile attribution; `profile` is empty.

### 2.7 `memory` — `memories/MEMORY.md` and `USER.md`

Facts are split on a line containing only `§` (older stores fall back to one
fact per line).

| Mode | Event |
|---|---|
| No prior snapshot | `memory.fact` (`payload.change="present"`), `ts` = file mtime, `payload.fact_digest`, `fact_chars`, `index`; raw text via `content_ref(column="line")` |
| Prior snapshot supplied | `memory.fact.added` / `memory.fact.removed` per changed fact |

Hermes keeps no memory revision history, so a real diff needs a prior snapshot:
`--write-memory-snapshot` stores one, `--memory-snapshot` diffs against it. The
first run of any install therefore reports snapshots, not diffs.

## 3. Text never travels in the event stream

Ground rule 5 (real history never enters the repo) is enforced structurally:

* payloads carry counts, hashes and structural keys — never message bodies;
* the text is reachable only through `fetch_content(content_ref)`, which is the
  seam the M1 redaction gate sits behind;
* the CLI refuses to write an event stream anywhere inside this repo.

`payload` digests are `text_digest()` = `sha256:` + first 32 hex of the UTF-8
text, so equal text compares equal without being stored.

## 4. Windows and determinism

* `Window(since, until)` is half-open: `since <= ts < until`; `until=None`
  means "now".
* Each source query has an explicit `ORDER BY` on stable keys, and sources are
  emitted in the fixed `SOURCE_ORDER`. Two runs over the same data therefore
  produce byte-identical streams, which is what M1's "same input gives the same
  canon" requirement rests on.
* `--days N` sets `since = now - N*86400` unless `--since` overrides it.

## 5. Known limitations (honest list)

1. **Memory diffs need a prior snapshot** (§2.7). Without one, first-run output
   is a fact snapshot.
2. **Skill usage is collapsed** to the latest timestamp per skill (§2.5).
3. **Kanban payload text** (`task_events.payload`, task `body`) is not copied
   into events; only keys and a digest. Fetch it with a content ref if a beat
   needs it.
4. **Message titles are embedded** in `session.started.payload.title` and
   `kanban.task.created.payload.title` because the M0 gate requires printing
   them. They are model/user-authored text and must pass the M1 redaction gate
   before export.
5. **`cwd` is reduced to a basename.** Full paths are an out-of-project path
   leak and are dropped at ingest rather than redacted later.
6. **Profiles are discovered by directory scan.** A profile with no `state.db`
   is listed as unavailable and contributes nothing.
7. **No A2A source.** `~/.hermes/a2a_audit.jsonl` exists only when the A2A
   plugin is used and is absent on this rig (`docs/hermes-surfaces.md`).

## 6. Read-only guarantee

Two layers, because "read-only" in SQLite means "no SQL writes", not "no
filesystem writes".

**Layer 1 - connection guards** (`adapters/hermes/ro.py`):

1. the SQLite URI carries `mode=ro`, so SQLite refuses data writes;
2. `PRAGMA query_only=1` refuses writes even if opened writable;
3. every opened path is recorded with its mode, and the CLI calls
   `assert_read_only_audit()`, exiting non-zero on any `w`/`w+`/`rw`.

**Layer 2 - no writes at the filesystem level either** (`adapters/hermes/stores.py`):

`strace` showed that `mode=ro` still makes SQLite open `-wal`/`-shm` with
`O_RDWR|O_CREAT` and *create* them when they are missing - a real change to the
user's directory. So the journal mode is read from the SQLite header (100 bytes,
`O_RDONLY`) before any connection exists, and then:

| Case | Action | Effect |
|---|---|---|
| not WAL (rollback journal) | open in place, `mode=ro` | creates nothing |
| WAL, `-wal` and `-shm` already present | open in place, `mode=ro` | touches existing files only; uncheckpointed WAL rows are visible |
| WAL, sidecars missing | copy the file into a private scratch tree outside the Hermes home, read the copy | nothing is created in Hermes state; a database with no `-wal` has nothing uncheckpointed, so the copy is complete |
| WAL, sidecars missing, larger than the copy limit (256 MB default, `REEL_SNAPSHOT_DIR` / `StoreReader(copy_limit=...)`) | open in place and record why | no silent behaviour: the summary prints the decision |

`--summary` prints the plan, e.g. `read plan: 68 stores: 67 in place, 1 snapshot`.
Snapshot copies live under `~/.cache/scrollback-reel` (never inside `~/.hermes`)
and are deleted when the run closes the reader.

`scripts/readonly_proof.sh` proves all of it from outside the process in three
parts: a live strace run (data files `O_RDONLY`, no creation, no mutating
syscalls), a strict run against a read-only-locked copy of a live profile (every
write-flag open denied), and the same on the read-only-locked synthetic home.
