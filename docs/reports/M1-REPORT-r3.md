# M1-r3 report: PARTIAL

Round 3 (writer only), against docs/reviews/M1-AUDIT-r2.md. Verdict first, then the
honest reason it is not a pass.

**The mechanism is built and tested; the real scripts are still not readable as comics.**
Everything the audit asked for exists and is gated, but two of the three real scripts
still fall back to literal evidence for some captions, and the dialogue collapses to the
same template reaction panel after panel. The audit's human-readability spot check would
not pass that, so this stage is PARTIAL rather than PASS.

Commit: written into this line after the r3 commits. Branch `main`. Nothing pushed,
nothing installed in Hermes. 228 tests pass.

## What is done, item by item

| Item | Result | Evidence |
|---|---|---|
| 1. Two layers per panel, claim-level grounding (not word overlap) | **DONE** — caption layer is a fact sentence (all content words + entailment); dialogue layer is claim-checked, and a reaction with no claim passes | `canon/grounding.py` (`ClaimGate`, `extract_claims`), `canon/episode.py`; 17 tests |
| 2. R2-F2 speaker attribution | **DONE** — a speaker must be an actor of a cited event; otherwise the line becomes narrator text or is dropped. The owner may react only with a claim-free line. Writers are given each panel's actors | `canon/episode.py`; `tests/test_grounding.py::test_a_speaker_who_is_not_an_actor_is_not_given_words` |
| 3. Stable fictional aliases, no markers in a script | **DONE** — masks carry a value digest, the alias book is private (mode 600) and persistent, names become fictional names, contact details and money become plain descriptions, two values never collide | `canon/aliases.py`; 8 tests; pipeline reports any surviving marker |
| 4. Arcs end properly | **DONE** — threads record completion and rank first by it; an unfinished thread's last panel is labelled "To be continued…" and the IR carries `cliffhanger: true` | `canon/threads.py`, `canon/arcs.py`, `canon/episode.py`; 3 tests |
| 5. Titles short, alias-safe, entailed | **DONE** (mechanism) — 6-word cap, alias resolved, marker refused, claims checked against the thread's evidence | `canon/titling.py`; 3 tests |
| 6. R2-F3 thinking off by default | **DONE** — the constructor defaults to thinking off, with a test for the default, the opt-in and the empty-content retry | `adapters/hermes/llm.py`; `tests/test_llm_client.py` |
| 7. Eval: 30 synthetic threads, 0 unsupported claims, no long verbatim quotes | **DONE** — 30 threads (20 completed, 10 open); template runs clean; an adversarial writer that smuggles a cause, a number and a name is refused 240 times with 0 released; 10/10 open threads end on a cliffhanger | `eval/threads/run.py`, `eval/threads/results.json`; `tests/test_threads_eval.py` |
| 8. Three real scripts from three different threads | **DONE, PARTIAL QUALITY** — three task threads, all grounded, no markers, no problems | `build-evidence/M1-r3/run/episode-{1,2,3}-script.md` |

## The three real scripts, measured

| # | thread | panels | grounding | captions repaired | lines dropped | title source |
|---|---|---|---|---|---|---|
| 1 | task | 5 | 1.0 (5/5 captions, 5/5 lines) | 2 of 5 | 4 | ungrounded → derived |
| 2 | task | 4 | 1.0 (4/4, 4/4) | 3 of 4 | 3 | model |
| 3 | task | 4 | 1.0 (4/4, 4/4) | 2 of 4 | 3 | model |

Every line carries its source event ids; no script shows a `[REDACTED:` marker; the
pipeline reports `problems: []`.

## Why it is still not readable

1. **Captions fall back to evidence.** When the model's caption is refused, the repair
   is a literal slice of the panel's evidence, and for a kanban event that slice starts
   `event: kanban.task.status …`. Two of five captions in episode 1 read that way. The
   repair is safe and ugly; the right fix is a caption repair that rewrites the line
   using only the evidence's *facts* rather than quoting its provenance block.
2. **Dialogue collapses to one reaction.** The model's lines are refused (they name
   actors who were not in the panel, or add a claim), so the template fallback answers
   every panel with the same "Okay.", and dedupe then drops 3-4 of them per episode.
   The strip currently reads as a caption sequence with one repeated interjection.
3. **Titles.** Episode 1's model title was refused as ungrounded, so the derived title
   ("Needs Sahil's decision Investigate FEB-30 intrin") reads like a task queue entry.
   Episodes 2 and 3 did use model titles.

None of that is a safety failure. All of it is the R2-F1 readability problem, partly
solved: the mechanism is right, the writing is not there yet.

## Deviations

1. **The template writer speaks as the hero when nobody in the panel is an actor**,
   provided the line carries no claim. Reading R2-F2 strictly ("a speaker must be the
   actor of a cited event") would forbid all dialogue for fleet events such as cron runs,
   which have no actor at all. A claim-free reaction cannot misattribute a fact, so I
   allowed it and recorded the reasoning in the code.
2. **`--episodes N` was added** so three scripts come from three different threads in one
   run. It writes `episode-{n}-script.md` and `script-ir-{n}.json` beside the existing
   single-episode artefacts.
3. **A caption's multi-word alias now covers its own words** ("The Reviewer" allows
   "reviewer"), otherwise every caption that used an alias looked ungrounded. Without
   this, captions were being replaced wholesale.
4. **A bad speaker drops one line, not the panel.** The LLM writer previously raised on
   an unknown speaker, which threw away the caption too.

## What I recommend for the next round

1. **A caption repair that writes a sentence, not a quote.** Given the evidence's facts
   (event kind, actor, task title, status), compose "<Actor> <verb> <object>" and check
   it as a caption. That removes the `event: kanban.task.status …` dumps.
2. **Give the dialogue layer a safe fallback that varies.** One reaction per panel, chosen
   by role, is fine; the same word five times is not.
3. **Let the caption carry more of the week.** Most panels' evidence has no text because
   the deep-gated subset is 60 events; captions will read better when the beats they cite
   carry gated text, which is a selection question, not a writer question.

## Reproduce

```bash
cd /home/kensei/repos/hermes-scrollback-reel
export TMPDIR="${TMPDIR:-$HOME/.hermes/cache/scratch}"
.venv/bin/python -m pytest                              # 228 passed
.venv/bin/python eval/threads/run.py                     # 30 threads, GATE PASSED
.venv/bin/python eval/grounding/run.py                   # 32 cases, 0 released
.venv/bin/python -m adapters.hermes.pipeline --data-dir "$TMPDIR/r3" --days 7 \
    --llm local --llm-url http://127.0.0.1:8091/v1 --episodes 3 \
    --max-vocabulary 240 --max-deep-events 60
```
