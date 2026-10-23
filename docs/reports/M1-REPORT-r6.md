# M1 round 6 report: FAILED on the writing acceptance, one defect open

Final writer round. The atomic-fact machinery is built and the dialogue fallbacks are
gone, but a real run still prints the old composer sentences as captions. I am not
claiming this round.

Commit under test: `888c7bc`. Installed copy: `06762fa` (code identical apart from the
caption-source experiments). 309 tests pass.

## What is done

| Item | Result |
|---|---|
| Atomic facts (the endorsed fix) | **built** — `canon/facts.py` turns a brief into goal/turn/outcome facts (actor, action, object, result, numbers). Outcome clauses keep their numbers. 6 tests. The pipeline builds them per thread and passes them to the planner, and records them in the metrics so a reader can see what a strip was allowed to say. Facts for episode 1 of the run: 8, including the goal and the turn chain. |
| R5-F1 dialogue fallbacks | **done** — `TemplateDialogueWriter` no longer invents a line. A panel speaks only when the writer wrote a line. A speaker's eligibility now comes from the fact list as well as the raw text (the facts name who did what). |
| R5-F2 caption policy | **done in the checker** — `caption_problem` refuses "X asked for …" and "X reported …" on every caption path, at most 20 words, and an owner echo over the limit. 8 tests. |
| R5-F4 header | **done** — the header is the title and nothing else; a title that fails grounding falls back to the thread title trimmed to six words, never to the owner's message. |
| R5-F3 climax shows the result | **built, not proven** — the planner gives climax and win the outcome facts, which carry "87.3" and "79.5" in the test fixture. In the real run the panels still showed the old strings, so this is not proven on real data. |

## The open defect

A real run still prints captions like `Kensei worked on benchmarking LCM-X against
Severian Memory.` and `Sahil asked for …`, even though:

- `build_facts` produces 8 facts for that thread (`goal`, `turn`, `turn`, `turn`, `outcome`…),
- the planner receives them (verified with a wrapper that prints `len(facts)` inside the
  call: 8),
- `caption_problem` refuses the "asked for" shape when called directly on the same
  string (verified in the installed copy),
- and `TemplateDialogueWriter.caption_for` now returns the fact sentence or nothing.

So the caption is arriving from a path neither the checker nor the writer explains. The
reproducer is in the evidence folder: `synth-probe.log` shows a deterministic run with no
model in the loop producing composer captions while the fact list is present. That is the
first thing to fix next round, and it is a code path I have not yet isolated.

## Measured on the last real run (before the final caption change)

- 29 calls, **max 2,750 prompt tokens per call**, 35,805 prompt / 2,857 completion.
- Three episodes, 6 panels each; headers 5–6 words (correct after R5-F4).
- Dialogue in character and correctly attributed (only Sahil and Kensei speak).
- Captions: 4/4, 3/3, 3/3 present but **the wrong text** — composer sentences.

## What I recommend

1. Isolate the caption path with the deterministic reproducer in `synth-probe.log`; fix
   it; then re-run the three scripts and check the acceptance list again.
2. Keep the atomic facts — they are the right model and the tests prove they carry the
   numbers.
3. Do not start M2 on the strength of this round.

## Evidence

`build-evidence/M1-r6/`: `run/` (metrics, IRs, scripts from the last real run),
`dev-round-1.log`, `synth-probe.log` (deterministic reproducer), `reinstalls.log`.
