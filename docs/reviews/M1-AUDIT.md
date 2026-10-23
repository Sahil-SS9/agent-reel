# M1 audit by KENSEI: CHANGES REQUIRED (not PASS)

Audited 23/10/26 at HEAD 4cdf249. Baseline M0 7e2e5bc.

## Confirmed sound (re-run by the auditor)

- 156 tests pass.
- Clean tree, no remote.
- No leftover private copies in `~/.cache/scrollback-reel`.
- No stray pipeline processes.
- F1–F4 fixes are in place, each in its own commit.
- The `GatedEvent` seal, the cache keys and pinned-window determinism are present as described.
- The read-only adapter work from M0 still holds.

## Findings

| ID | Severity | Finding | Required outcome |
|----|----------|---------|------------------|
| M1-F1 | **P0** | **The script invents facts.** The six cited beats are `default: local-gguf-serving` (skill used), `remii: skill_view`, `octacon: read_file`, `denji-reviewer: gave_up`, `wesker: hermes-cron-operations`, `wesker: hermes-agent`. The LLM writer turned them into "the GGUF server's latency is spiking", "the config is missing the timeout key", "fix it or the rig burns down". None of that is in the cited events. Citing an event id is not grounding. This breaks the core rule "every generated line carries the source event ids it came from. No invented facts." | Add a grounding gate. Every factual claim in a line must be supported by the gated content of its cited events (entailment check by model, plus an entity/term overlap check). Unsupported lines are rewritten literally or dropped. The writer prompt forbids new facts. Add an eval: ≥30 synthetic beats with known content; 0 unsupported claims released. Report the grounded-line rate on the real run. |
| M1-F2 | **P0** | **The "arc" is not a story.** It stitches six unrelated events from five agents across six days (Fri 16 evening → Thu 22 14:14). The report's "each panel causes the next: VERIFIED" rests on rising timestamps and distinct roles. That is a proxy, not causation. This is the exact "random panels" failure Sahil rejected in bake-off round 1. | Build arcs from **one linked thread**: the same kanban task family (parent/child, claimed → blocked → completed, comments), the same session lineage (`parent_session_id`), or the same subject or entity. Prefer threads with human-meaningful gated titles; the bake-off's working story came from session and task titles. Add negative tests: unrelated events must never form one arc. Relabel the M1 claim as NOT VERIFIED until a causal-link check exists. |
| M1-F3 | **P0** | **Secret recall is not 100% on independent data.** The auditor held out 27 items, not shared with the builder. In deep mode with the local model it leaked a **Discord webhook token** embedded in a URL path (`/api/webhooks/<id>/<token>`). This fleet runs on Discord, so that is a likely real secret. In deterministic mode a plain-text "the password is …" also leaked; the model pass caught it. The 232-item benchmark was written by the same agent that wrote the rules, so its 100% is self-graded. | Cover tokens in URL paths (webhooks, signed paths) and plain-language credential phrases in the deterministic pass. Split the benchmark into dev and a **held-out set written separately and never tuned against**, and report recall on held-out. KENSEI will re-run its own private held-out set at the next audit. |
| M1-F4 | **P1** | **Raw memory dumped into shared evidence.** `memory-facts.json` (3 copies: run-live, det-run, det-model) holds the full unredacted MEMORY/USER facts of every profile: 53 email addresses and 25 absolute paths, mode 644, in `~/handoffs`. That breaks ground rule 5 ("outputs from real-data runs … must pass the redaction gate first") and v1 "memory: facts only, never full contents into scripts". KENSEI has chmod-ed the three files to 600 as containment. | Delete the three files. The snapshot store lives only in the plugin data dir (mode 600), never in an evidence folder. Store per-fact hashes plus gated text; diff on hashes. Evidence gets counts only. Add a test that the evidence writer refuses ungated text. |
| M1-F5 | **P1** | **Model pass is unstable and slow.** On the held-out set, 6 of 27 items (22%) were quarantined with "model returned empty content" (fail-closed, but story material is lost), and the run took 4 min 50 s for 27 items. | Make the empty-content handling robust: retry with thinking off, then a fallback route. Report the quarantine rate per run and fail the run above a threshold (e.g. 5%). Report items/second. |
| M1-F6 | P2 | Presentation: functional title ("The week default, denji-reviewer, octacon had"), panels 5 and 6 repeat one line, cast shows profile ids (`default`) instead of character names, captions are in UTC. | Cast map (profile → character; `default` → KENSEI), title via one cached call, no duplicate lines, captions in Europe/London. |
| M1-F7 | P2 | Raw tool names (`read_file`, `skill_view`, `terminal`) become "struggle" beats. | A tool call is never a beat on its own. It can only add detail to a beat from a thread. |

## Owner decisions raised by the builder (KENSEI recommendations)

1. Repeated tail lines: fix now under M1-F6, not M2.
2. Title: yes, one cached call, after grounding (M1-F1).
3. Vocabulary cap 240: keep for private runs. Public export needs the full pass.
4. Quiet-week rule: superseded by M1-F2. Pick the strongest real thread; a quiet week gets a training-montage arc from skill level-ups.
5. `task_comments`: promote decision-bearing threads. They are core thread material under M1-F2.
