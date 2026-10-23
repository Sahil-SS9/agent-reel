# M1 round 3 audit by KENSEI: CHANGES REQUIRED. The story source has to change, not the wording rules.

Audited 23/10/26 at c2e6627. 228 tests and both eval gates reported green. The builder's PARTIAL is honest.

## What the three real scripts show

- Every dialogue line in all three episodes is "Okay."
- 7 of 13 captions are raw provenance dumps (`event: kanban.task.status gave_up octacon octacon {"failures": 2 ...`).
- Titles read like queue entries ("octacon completed t_d0b2ff6f: octacon gave_up").
- **The threads chosen are kanban admin plumbing**: a review gate blocked a card, a dispatcher gave up, a reviewer finished. They are not the week's real work.

The safety machinery is right: claim-level grounding, actor-only speakers, private aliases, proper endings, adversarial control 240/240 refused.
The problem is upstream of the writer. The selected beats carry almost no gated text, so there is nothing true to say, and every layer falls back.

## Root cause

1. **Selection scores lifecycle noise, not meaning.** Kanban status churn (blocked, gave_up, finished, governance-guard notes) produces the strongest "struggle → resolution" signal, but it is fleet bookkeeping. The real story lives in sessions and work tasks: what the user asked for, what was built, what broke, what shipped. The bake-off strip that Sahil approved was written from exactly that (session titles plus outcomes).
2. **Panels are anchored on events with no gated text.** A beat with nothing to say cannot anchor a panel.
3. **The writer model is the small local model.** In the real plugin, `ctx.llm` uses the owner's main Hermes model. The dev runs judge prose quality with a much weaker writer than users will get.

## Required changes (round 4)

| ID | Change |
|----|--------|
| R3-F1 | **Story selection by meaning.** Candidate threads are sessions with a user-stated goal and an outcome, and kanban task families whose titles describe real work. Governance and admin plumbing (review gates, triage, governance-guard blocks, dispatcher gave_up/retries, "Needs Sahil's decision" meta cards) is excluded as a story, and is allowed only as a detail inside a real work thread. Rank by user involvement, size, and having a clear outcome. |
| R3-F2 | **Thread brief.** For each selected thread, build a gated brief from its gated text: goal (first user message or task body), 3–6 key turns, outcome (final assistant summary or completion summary). Every brief fact is entailment-checked against the events. Captions and dialogue are checked against brief plus events at claim level. |
| R3-F3 | **No panel without text.** A panel's anchor beat must carry gated text in the brief, otherwise the beat is skipped. |
| R3-F4 | **Captions never print provenance.** The repair composes a plain sentence from structured facts (actor, action, object, status) or drops the caption. Never `event: …`. |
| R3-F5 | **Dialogue.** A panel may be silent; silence beats "Okay.". No reaction line repeats within an episode. A line may name any thread cast member who appears in the thread's evidence (not only panel actors); everyone else gets an alias. |
| R3-F6 | **Writer model** (needs the owner's OK, see below): writer, title and entailment calls use the owner's main model through the local Hermes API server (`http://127.0.0.1:8642/v1`, key read at runtime from `API_SERVER_KEY` in `~/.hermes/.env`, held only in process memory, never written, logged or printed). Redaction stays on the local model. Only post-gate text leaves the machine. Log call counts and tokens. This matches production, where `ctx.llm` uses the main model. |

## Acceptance (KENSEI readability check on 3 real scripts from 3 different threads)

- Each script reads as goal → problem → outcome (or a labelled cliffhanger) about real work, not bookkeeping.
- 0 raw event strings, 0 "Okay." or any other repeated filler, at most 1 repaired caption per episode.
- Titles are 6 words or fewer and human-readable.
- Grounding adversarial control still 100% refused. Secrets/names held-out unchanged.
