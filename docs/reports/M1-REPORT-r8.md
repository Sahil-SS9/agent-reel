# M1 round 8: captions are prose and endings are earned — but the run now tells one story, not three

Verdict: **PARTIAL, and a regression in strip yield.** The three writing/ending corrections
are in and proven by tests; the real run produces **one** episode instead of three, and that
one carries no visible result. Do not start M2.

Candidate: `407e783` (installed at the same commit, reinstall logged). Tests: **328 passed**.
Gates unchanged: thread eval GATE PASSED, grounding GATE PASSED, cold-cache held-out
redaction GATE PASSED (secrets 17/17, names 7/7, 0 leaked).

## What was asked and what happened

| Item | State |
|---|---|
| R8-1 natural captions: facts are evidence, not page text | **done** — the planner never writes a caption. The only page source is the writer's own sentence; it is handed the panel's facts and told to return one grammatical sentence of at most eighteen words, or nothing. The template writer writes no caption and no line. `captions_repaired` is 0 by construction. Tests cover an imperative request, a first-person assistant message and a truncated title. |
| R8-2 preserve the story after panel rejection | **implemented** — a resolved thread may not export without a visible outcome (its numbers, its content words, or a completion cue must appear in a caption or a line). Otherwise the episode is refused with a reason and recorded in `skipped_stories`. An unfinished thread still ends with an explicit continuation label. |
| R8-3 selection: substance outranks length | **done, controls proven, real benchmark not proven** — score is substance first (`is_substantive_outcome`), then user involvement, text, size. A receipt ("Go received."), a background-process notice and a bare number do not count. Tests: qualitative completed work beats verbose bookkeeping; length still breaks ties. |
| R8-4 regression proof for the repaired re-check | **done** — `RecordingGrounder` rejects the offered caption and records every check; the test asserts the rejected caption is checked, never reaches the page, and that every check carries the fact list. |

## Why the run yields one episode

Three separate causes, all measured, none of them a reason to loosen a safety rule:

1. **A caption must state the panel's evidence, and the model's captions often name things a
   short fact does not contain.** Fixed by judging against the fact list *plus that panel's
   own gated evidence* (a claim in neither is still refused). This raised caption survival
   but did not restore yield.
2. **The ending rule refuses finished threads whose result panel does not name the result.**
   In this window most finished threads end on a summary message whose content never appears
   in any surviving caption, so they are refused with "no panel states it". That is the rule
   working as specified — and it is why the run now tells one story instead of three.
3. **Two candidates resolving to the same thread** produced the same strip twice; a thread is
   now told once ("thread already told").

The single episode that survives (`ev_2cf85891a09fe933482b225a`) has four panels, two
captions and two lines, and its climax states a real qualitative result: "Every re-run
finished, the full suite passed, and no skill made the AI worse for any persona." Its
aftermath caption is unrelated to the ending ("the chat history lookup tool is not currently
available"), so the strip reads as complete without showing the work's result.

## The acceptance item still not met

**No strip proves the benchmark result** (subjects, scores, metric, completion status). The
benchmark thread is not selected in this window; selection now ranks by substance, and the
benchmark thread's own outcome text does not survive the ending rule. I did not fabricate a
strip or relabel a different episode.

## What I recommend

1. Give the writer the whole panel evidence as well as the facts, and ask it for the result
   sentence on climax/win explicitly — the current prompt asks for "the facts line", which
   for a long outcome is one clause.
2. Judge the ending against the *brief's* outcome sentence and the panel evidence, not only
   the caption text, and count a line as evidence (it already does) — then re-measure yield.
3. Only after yield recovers, prove the benchmark strip on its recorded window.

## Evidence

`build-evidence/M1-r8/`: `dev-round-1..6.log`, `run/` (metrics, IR, the one script),
`reinstalls.log`, `tests.txt`, `eval-threads.txt`, `eval-grounding.txt`,
`benchmark-heldout-deep.txt`.

Exact commands:
- `hermes reel plan --dry-run --days 7 --episodes 3 --data-dir "$E/run" --json`
- `.venv/bin/python -m pytest -p no:cacheprovider`
- `.venv/bin/python eval/threads/run.py` · `eval/grounding/run.py` · `eval/redaction/run.py --deep --dataset eval/redaction/dataset-heldout.jsonl`
