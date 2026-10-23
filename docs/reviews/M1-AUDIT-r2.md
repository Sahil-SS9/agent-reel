# M1 rework (r2) audit by KENSEI: PASS on safety and grounding; the story writer needs one owner decision before M2

Audited 23/10/26 at fae5740.

## Confirmed by the auditor

- **Tests:** 203 passed, twice, in a fresh clone (no venv state, no cache).
- **Hygiene:** no leftover copies in `~/.cache/scrollback-reel`, no stray processes. The three `memory-facts.json` dumps are deleted, and no email address appears anywhere in the evidence tree.
- **KENSEI's private held-out set** (27 items, never shared with the builder):
  - deterministic pass: **all 8 secrets caught**, including the Discord webhook token that leaked in r1, plus every contact, path, IP and URL item
  - deep pass with thinking off (the pipeline's configuration): every name, client, project, money and health item caught, 0 quarantined, 9 s for the 6 hardest items
  - Earlier quarantines in this audit came from the auditor's own harness, which built the client without `enable_thinking: False`. See R2-F3.
- **Threads:** the live episode is one thread, the Modernisation Engine slice task family on Sun 18 Oct night. The r1 cross-agent stitching is gone.
- **Grounding:** every line is a literal quote from its cited events. No invented facts.

## Findings

| ID | Severity | Finding | Required outcome |
|----|----------|---------|------------------|
| R2-F1 | **Blocking for M2 (owner decision)** | **The script is safe but unreadable as a comic.** The dialogue is truncated kanban task titles split mid-word across two speakers ("implement the bounded f..."). Redaction markers show in the title and dialogue (`[REDACTED:project_name]`). The 4-panel strip stops at the climax with no aftermath, win or labelled cliffhanger. The grounding gate checks word overlap, so only literal quotes can pass. | Owner chooses how creative the writer may be. KENSEI's recommendation: **"creative inside the evidence"**, below. |
| R2-F2 | P1 | **Speaker attribution is not grounded.** Kanban task bodies written by Kensei or the orchestrator are put in Sahil's mouth. Who said something is a fact too. | A line's speaker must be the actor of a cited event, or the line becomes a narrator caption. |
| R2-F3 | P2 | `OpenAICompatLLMClient(...)` defaults to thinking **on**. Only `.local()` and the pipeline/benchmark callers pass `enable_thinking: False`. Any new caller (the M2 ctx path) can silently hit the empty-content quarantine. | Make thinking-off the constructor default for JSON tasks. Add a test. |

## Recommended writer design ("creative inside the evidence")

1. **Two layers per panel.**
   - A **fact caption** (narrator box): plain words, entailment-checked against the cited events. Use claim extraction plus model entailment, not word overlap.
   - **Dialogue** may dramatise tone, emotion and metaphor, but must not add any new fact: no new names, numbers, causes, outcomes or tools. Check it by extracting claims from the dialogue; every extracted claim must be entailed by the cited events. Pure emotion or banter carries no claim and passes.
2. **Speakers** follow R2-F2.
3. **Redacted terms** get stable fictional aliases from canon (for example a project becomes "Project Lantern"). They are never shown as `[REDACTED:…]`. The alias map is private and consistent across episodes.
4. **Arcs end properly.** Prefer threads with a completion. Otherwise the last panel is a labelled cliffhanger ("To be continued…"), never a bare climax.
5. **Titles** follow the same rules: short, alias-safe, entailed.
6. **Eval:**
   - 30 synthetic threads
   - 0 unsupported claims in captions or dialogue
   - dialogue must not be a verbatim quote over 12 words
   - human-readability spot check: KENSEI audits 3 real scripts

This keeps the M1 safety guarantees and lets the strip read like round-2 of the bake-off, which Sahil approved.
