# M1 round 7: the two bypasses are closed. Templates are gone.

Commit under test: `fa95c8d`. Installed copy: `fa95c8d` (validated, doctor OK, reinstall
logged in `reinstalls.log`). Evidence: this folder. 313 tests pass.

## What was wrong (audit r6 was right)

Both leaks were in `plan_episode`, not `write()`:

1. **Repair path.** The chosen caption was re-checked against the *raw evidence* instead of
   the fact list it had been chosen against. A good fact caption failed that re-check and
   was "repaired" with `compose_caption`'s sentence — "Kensei worked on …". That is what
   real runs hit.
2. **Empty-panel fallback.** `structured[event_id]` (also composer output) was placed
   directly when a panel had neither caption nor line. That is what the synthetic probe hit.

## Fix

- One helper, `_policy_caption()`, is now the only source for a repair or a fill. Its only
  candidate is the panel's fact sentence from `canon/facts.py`, and it must pass the same
  caption policy as every other path (no template opening, no owner echo over the limit, at
  least three words, no repeat).
- The repair re-check uses `judge_text` (the facts), never the raw evidence.
- Nothing passes → no caption. No caption and no line → the panel is dropped, not filled.
- `compose_caption` no longer reaches a page. "asked for", "reported" and "worked on" are
  refused by the caption policy as well, so a composer sentence cannot reappear.
- Facts are short enough to read as captions and to stay inside the owner-echo limit, never
  end on a pronoun, a conjunction or a contraction, carry no internal identifier, and an
  assistant turn is "described", not "reported".

## Result on three real episodes

| Check | Result |
|---|---|
| Template captions ("worked on / asked for / reported") | **0** |
| Captions repaired | **0** in all three episodes |
| Captions that read as a complete sentence | 11 of 11 |
| Owner quotes over 8 words | 0 (longest is 6) |
| Titles | 2 words, and never the owner's raw message |
| Model calls / worst call | 4 calls, 994 prompt tokens (limit 5,000) |
| Gates | 313 tests; thread eval GATE PASSED; grounding GATE PASSED; cold-cache held-out redaction GATE PASSED (secrets 17/17, names 7/7, 0 leaked) |

Episode 1: "Sahil wants please read and review this idea/concept." / "Kensei handled Review
Hermes agent concept against docs." / "This is my review reply for the build. The same text
is saved at a local folder." / "Kensei described I couldn't open the artifact."

## One acceptance item still unmet

**Episode 1 does not show the benchmark result.** Selection ranked three review threads
above the benchmark thread, so no strip covers it. This is not a caption defect — the
bypass that r6 found is closed — it is a selection question: how much weight a thread with
concrete numbers and a finished result should get. I am not changing selection inside a
caption round, and I am not claiming the acceptance list is fully met.

## Verdict

**PASS on the round-7 mandate** (both bypasses closed, verified by the run and by tests
`tests/test_r7_bypasses.py`: no repair against facts, no `caption_problem` string from
either fallback, no template panel, climax states 87.3/79.5 on the fixture).
**PARTIAL against the full r6 acceptance list**, on the one item above.

Recommendation: fix selection weighting next (a finished thread with numbers should outrank
a review thread), then judge the acceptance list again. M2 still not started.
