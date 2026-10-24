# M1 round 9: tool payloads are out of briefs. Yield is still one story of three.

Verdict: **PARTIAL.** R8-F2 (the round's first instruction) is done and proven. The yield
target is not met: a fresh 7-day run tells **one** story, and the per-story reasons are now
recorded. Do not start M2.

Candidate `cdac413`, installed at the same commit (reinstall logged). Tests **333 passed**.
Gates unchanged: thread eval GATE PASSED, grounding GATE PASSED, cold-cache held-out
redaction GATE PASSED (secrets 17/17, names 7/7, 0 leaked).

## R8-F2 — tool payloads out of briefs (done)

`canon/brief.py` now builds goal, turns and outcome only from user/assistant prose and task
titles/comments (`STORY_KINDS`), refuses any text that looks like a payload (JSON, a table
row) even when its kind is allowed, and leaves out `tool.call` / `message.tool_result`
entirely. RED-first tests (`tests/test_brief_tools.py`) use a session containing tool results
and a tool-only turn: the `not_found` receipt, the table listing and the JSON never appear in
the brief, and the prose still does.

Also in this round, per the instruction:
- the writer is handed the panel's facts **plus its gated evidence**, and climax/win are asked
  explicitly for the RESULT sentence including any score;
- the ending is judged against the brief outcome **and the panels' own gated evidence**
  (nothing loosened: a claim in neither source is still refused);
- a turn that repeats the goal is not a second fact, and climax and win take different result
  material, so identical captions no longer drop panels;
- a panel with no unused fact gets its own evidence as its source, so the writer is not starved;
- P2: a session id is stripped from brief goal/outcome, and brief text in `metrics.json` is
  truncated to 160 characters;
- a refused caption and a refused story now record **why**.

## The yield, measured on a fresh cache (no cached model answers)

`dev-round-5.log`, `run-final/metrics.json`, generated 2026-10-24T15:49:07Z: **1 episode**,
5 panels, 1 caption, 5 lines, 44 writer calls. The other eligible stories, with the reason
recorded for each:

- `local-539a874f…` — fewer than three panels (2 kept; aftermath dropped, win caption refused)
- `t_ec1754fc` — fewer than three panels (0 kept; aftermath caption refused)
- `local-a387557f…` — fewer than three panels (2 kept; climax dropped, win caption refused)
- `t_36e485d6` — finished thread with no visible outcome (1 panel kept; win caption refused)
- `local-028c8e58…` — brief not usable (6 turns)

Every caption-level refusal now reads the same: **"not supported by the panel evidence"**. The
model writes a correct result sentence and the claim checker rejects it. The checker asks the
model whether an outcome or a cause is entailed; on these panels it says no. That is the
single cause of the yield loss, and it is a checker question, not a writing question.

## What I did not do

I did not relax the claim gate to make the numbers look better, and I did not fabricate a
third strip. No strip proves the benchmark result yet: the benchmark thread is not among the
selected stories in this window, and the instruction is explicit that a different episode may
not be relabelled as it.

## Recommended next step

Diagnose the entailment check on the four refused captions specifically: the same model both
writes the caption and judges it, and it is rejecting its own true sentences. Either give the
checker the panel's evidence as its only input with a narrower question ("does this sentence
state only what this text says?"), or run the outcome claim check deterministically against
the panel evidence. Then re-measure yield; only then prove the benchmark strip.

## Evidence

`build-evidence/M1-r9/`: `dev-round-1..5.log`, `run/` (cached round), `run-fresh/`,
`run-final/` (fresh cache, the numbers above), `reinstalls.log`, `tests.txt`,
`eval-threads.txt`, `eval-grounding.txt`, `benchmark-heldout-deep.txt`.

Scripts produced this round:
- `build-evidence/M1-r9/run-final/episode-1-script.md`
- `build-evidence/M1-r9/run-fresh/episode-1-script.md`
- `build-evidence/M1-r9/run/episode-1-script.md` and `run/episode-2-script.md`

There are not three scripts: that is the finding of this round, not an omission in the report.
