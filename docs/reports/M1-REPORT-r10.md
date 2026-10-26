# M1 round 10 — KENSEI direct build (owner override, 24/10/26)

Verdict (producer, not independent): PARTIAL. Yield is fixed (3/3 on the 7-day window, three consecutive runs); the grounding gate is still safe on the production judge; story quality and the benchmark acceptance item remain open. Independent review is required before M1 can close — KENSEI built this round, so KENSEI cannot sign it off.

Base 2f8fdfc (r9) → head 72b802b on branch m1-r10-kensei. Installed live copy = 72b802b (reinstalls logged in build-evidence/M1-r10/reinstalls.log; note 2e49c55 was briefly installed with 5 failing pipeline tests and superseded within minutes).

## Root cause of the r9 yield loss (measured, not inferred)
r9 claimed the model judge rejected its own true captions. The r9 run cache contradicts this: 6 grounding model calls, 6 × supported=true. The refusals came from `ClaimGate.check(layer="caption")` requiring 100% verbatim content-word overlap *before* the model was asked, so any paraphrase failed. Titles had the same flaw in `titling._grounded` (every word must appear in beat summaries) → "A session".

## Changes (one concern per commit)
- e8e5365 caption judge: names/numbers stay deterministic (acronyms like GGUF/LCM-X now count as names); with a model, a 50% vocabulary floor then entailment with a caption-specific prompt that lists the words not found in the evidence; without a model the 100% rule stays (fail closed). Refusal reasons now name the real cause. New `hermes reel eval-grounding` runs the eval on ctx.llm (the production judge). Eval gains 12 paraphrase cases with subtle inventions (wrong actor, flipped outcome, added cause/time, changed figure).
- 2e49c55 / 770b988 child sessions resolve to their lineage thread through their events (r9 skipped 5/11 as "no thread"); strips need 4 panels (D7; configurable, tests on the tiny fixture use 3; a test pins the production default); `--since/--until`; brief refusals name what is missing.
- e162691 model titles judged like captions when a judge exists; story rows in metrics re-gated after the 160-char cut (the evidence writer had refused a whole metrics file on the September window — the safety net worked; the cause is fixed).
- 72b802b a forecast/still-running outcome no longer resolves an arc (it was labelled WIN on the in-progress LCM-X session).

## Measured
- Tests: 351 passed (`pytest -q`, canonical, from the repo root).
- Grounding eval on ctx.llm, run twice: invented refused 44/44 both runs; true lines 43/44; paraphrases 11/12 (one below the vocabulary floor). No-model eval: 0 released.
- Thread eval GATE PASSED (120 adversarial refusals). Redaction, read-only adapter and gate code unchanged since r9 (empty diff) — held-out redaction not re-run.
- Real runs (all via `hermes reel plan --dry-run`, ctx.llm, max ≈2–3k prompt tokens/call):
  - 7-day: run-2, run-3, run-final → 3/3 episodes each, 4–6 panels, model titles.
  - 10–12 Sep: run-bench-2 → 3/3. 10–11 Sep: run-bench-0910 → 2 episodes (other candidates had no outcome or 2-turn briefs).

## Open — for the reviewer and the owner
1. Benchmark acceptance not met. The finished 87.3 vs 79.5 session (state.db, 10 Sep) is not among the window's top candidates, so no strip shows it. In run-3 the later, in-progress benchmark session was told; with the forecast fix it now ends open.
2. Story quality still uneven: bookkeeping stories still win selection sometimes ("Stale launchers, nothing to act"); some panels restate the previous one; chronology can invert inside a strip (aftermath "started the audit" after climax "audit finished"); final panels are always labelled WIN even when the result is "none passed".
3. Selection varies between runs on the same window (episode 3 changed across run-2/3/final).
4. Self-graded evals: the paraphrase cases were written by the producer. An independent held-out caption set is needed.

Evidence: ~/handoffs/agent-story-replay/build-evidence/M1-r10/


## Round 10b — fixes for Quan's review (t_0ea810b2), head 6a74259 (installed)
- QAR10-01: cast names stay legal vocabulary but a caption naming one must find it in the cited evidence; refused before any model call (tests/test_r10b_review_fixes.py, no-model and always-yes-model paths).
- QAR10-02: numbers compared as whole canonical figures (4 vs 14, 2.8 vs 2.85, 1,152 vs 81,152, 9:4 vs 09:40, 87 vs 87.3), before any model call.
- QAR10-03: every caption carries caption_source_event_ids (panel events + thread facts that support it); each episode ships episode-N-trace.json with its arc, beats, facts and re-gated evidence for every cited id; every episode (not only the first) is validated. A vacuous test (`or True`) in test_pipeline.py replaced with real assertions.
- QAR10-04 (medium): accepted as a documented limitation, not fixed — the 50% vocabulary floor still refuses some synonym-heavy true paraphrases (11/12 on our set, 21/23 on Quan's).
- Measured: 370 tests pass; ctx.llm grounding eval 44/44 invented refused; run-week-2 and run-sept-2 both 3/3 episodes, all 6 scripts traceable with matching arcs; 12 caption traces in build-evidence/M1-r10b/caption-traces.md.


## Round 10c — Quan's r10b re-review (t_8645faf5) fixed; final PASS (t_13eb5c20) at f2ccfbb
- Actor names bound to their action per cited event (blank-line event blocks, sentence split otherwise; semicolons keep a clause together); case-insensitive; allow-only callers get the check.
- Figures compared as whole tokens including sign, ordinal and version forms (-4/4, 14th/4th, v14/v4).
- Captions also cite the episode event that states them most directly (best overlap, at least two shared words).
- Measured by Quan: 395 tests; frozen 24-case set 24/24 inventions refused, 21/23 valid paraphrases; 18/18 caption traces supported; Quan's regressions 2/2 and 10/10.
- Known: 2 of 3 week-run titles fell back to "A session" (fixed in M2 P0: sentence-case titles, three options).
