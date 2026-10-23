# M1 round 4 report: PASS on the acceptance list, with one caveat

Round 4 (writer only), against docs/reviews/M1-AUDIT-r3.md. Nothing loosened: claim
grounding, actor-only speakers, private aliases and the redaction rules are untouched.

Commit under test: `0675f7e`. 272 tests pass. Evidence: `build-evidence/M1-r4/`.

## Acceptance, measured on the three real scripts

| Check | Required | Result |
|---|---|---|
| 3 real scripts, 3 different real-work threads | yes | **3 session stories**, 6 panels each |
| reads goal → problem → outcome | yes | yes: each strip opens on the ask, turns on the problem, ends on the report |
| raw event strings | 0 | **0 / 0 / 0** |
| "Okay." or other repeated filler | 0 | **0 / 0 / 0**, and no line repeats inside an episode |
| repaired captions | at most 1 per episode | **0 / 0 / 0** |
| titles, 6 words or fewer, readable | yes | **3 model titles**: "Benchmark LCM-X against Severian Memory", "Hermes Chronicle spec checked against Hermes", "Hermes Dev Radio spec" |
| adversarial grounding control | 100% refused | **240/240 refused, 0 released** (`eval-threads.txt`) |
| secrets / names held-out | unchanged | **GATE PASSED**, secrets 100%, names ≥95% (`benchmark-heldout-deep.txt`) |
| masks or URLs in a script | none | **0 / 0 / 0** |

Episodes: 6 / 6 / 6 panels, captions 6/6 supported each, dialogue lines 6/6, 4/4 and 0/0.
86,552 events gated, 546 threads, 11 eligible stories, 1 skipped (no thread).

**Caveat.** Episode 3 is silent: six grounded captions, no dialogue. That is the rules
working (silence beats filler) rather than a failure, but a caption-only strip is weaker
than the other two and the audit should see that stated rather than buried.

## Items

| ID | Change | Commit | Tests |
|----|--------|--------|-------|
| R3-F1 | Story selection by meaning. Sessions with a user goal and an outcome, or task families whose titles describe real work. Review gates, triage, governance blocks, dispatcher give-ups, "Needs Sahil's decision" cards and bare ids are never a story; their events stay available as detail. Ranked by user involvement, then a clear outcome, then text, then size. | `aa33f64` | `tests/test_selection.py` (10) |
| R3-F2 | Thread brief from gated text: goal (first user message or task title), 3–6 key turns, outcome (completion summary or final assistant message). Every line entailment-checked before use. | `4b395b4` | `tests/test_brief.py` (8) |
| R3-F3 | No panel without text: a beat only anchors a panel when the brief carries its gated text; otherwise the beat is skipped. A thread that cannot fill a strip is skipped with its reason recorded. | `94432c9` | `tests/test_anchors.py` (3) |
| R3-F4 | Captions never print provenance. A caption is composed from structured facts (actor, action, object, status) and dropped when there is nothing to say; `event:`, `key=value` dumps, uuids and bare task ids are rejected by a detector, and evidence no longer carries a provenance header. | `8f489b4`, `4b439d7`, `0675f7e` | `tests/test_caption.py` (9) |
| R3-F5 | Dialogue: the template writer uses each reaction once per episode and then goes silent ("Okay." and "Right." removed); a line may name any thread cast member who appears in the thread's evidence; a silent panel is valid. | `b9754e3` | `tests/test_dialogue_rules.py` (6) |
| R3-F6 | Writer, title and entailment calls go to the owner's main model on `http://127.0.0.1:8642/v1`; the key is read from `~/.hermes/.env` at call time, held in memory, and cannot appear in a repr, a log or a metric. Redaction stays on the local model (8091). Calls are counted against a 150 budget and tokens are counted per endpoint. | `bec022d` | `tests/test_api_writer.py` (8) |

Integration: `8d4d846` (selection → brief → story beats → panels), `fd40ecd` (two
corrections found by the first real run), `93eaa38`, `06af41b` (title and logline polish).

## Cost

36 API-server calls of a 150 budget, 2,038,869 prompt tokens, 4,716 completion tokens.
The prompt figure is large because each call carries the Hermes system prompt; it is
counted, not hidden.

## Deviations, stated plainly

1. **A brief line is quoted verbatim, so it is grounded by construction.** Asking the
   model to entail a quote refused whole briefs (5 of 6 candidates in the first run) and
   cost 65 calls for one episode. A paraphrase would still be checked; `build_brief` never
   paraphrases.
2. **A title is claim-checked, not word-for-word.** Word-for-word refused every model
   title and fell back to queue entries; a title may compress, it may not claim a name, a
   number, an outcome or a cause the thread does not contain.
3. **A caption is the composed sentence; a model caption is an improvement** used only
   when it passes the strict caption check. This is what makes "at most 1 repair" a real
   measure rather than counting the primary path as a repair.
4. **The owner may react with a claim-free line when nobody in the panel is an actor.**
   Kept from round 3; a reaction cannot misattribute a fact.
5. **Session stories get beats from the brief**, because a session has no kanban lifecycle
   to draw a climax from. Roles are assigned by position so a three-turn brief still fills
   three panels.
6. **An empty run still writes metrics** and says "no episode could be planned", so a thin
   week is visible instead of silent.

## What I would do next (not started)

1. Give the dialogue layer a thread-level fallback so a strip like episode 3 is not fully
   silent: one line per panel chosen from the brief's turns, claim-checked.
2. Caption wording: "Kensei worked on benchmarking LCM-X…" is true and readable but flat;
   the composed sentence could pick the verb from the beat's role rather than the event
   kind.
3. M2 (renderer) is not started and should not start until this is signed off.

## Reproduce

```bash
cd /home/kensei/repos/hermes-scrollback-reel
.venv/bin/python -m pytest                                    # 272 passed
.venv/bin/python eval/threads/run.py                          # 30 threads, GATE PASSED
.venv/bin/python eval/grounding/run.py                        # 32 cases, GATE PASSED
.venv/bin/python eval/redaction/run.py --llm local \
    --llm-url http://127.0.0.1:8091/v1 --deep \
    --dataset eval/redaction/dataset-heldout.jsonl            # GATE PASSED
.venv/bin/python -m adapters.hermes.pipeline --data-dir "$TMPDIR/r4" --days 7 \
    --llm local --llm-url http://127.0.0.1:8091/v1 --writer api --episodes 3 \
    --max-vocabulary 240 --max-deep-events 90
```
