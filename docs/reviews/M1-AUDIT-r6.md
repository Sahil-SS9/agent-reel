# M1 round 6 audit by KENSEI: FAILED, as the builder says. Root cause located.

Audited 23/10/26 at 93665fa. The builder's report is honest. The builder narrowed the defect to "inside `write()`". KENSEI traced the exact path, and it is in `plan_episode`, not `write()`.

## Root cause (two bypasses in `canon/episode.py`, layer 1)

The pipeline builds a per-event `structured` map with `compose_caption(event, …)` (`adapters/hermes/pipeline.py:505`). That is the composer that writes "Kensei worked on …", "Sahil asked for …", "Kensei reported …". `plan_episode` puts it on the page through two paths that never call `acceptable()` / `caption_problem()`:

1. **Repair path, ~L662–680.** After a caption is chosen, it is re-checked with `grounder.check(caption, evidence_text, …)`. That is the **raw evidence**, not `judge_text` (the fact list) used everywhere else. So a good fact-based caption that passed against the facts is re-judged against long raw evidence, usually fails, and is "repaired" with `structured[event_id]`, the composer sentence. **This is what happens on real runs.**
2. **Empty-panel fallback, ~L735–745.** When a panel has no caption and no lines, `structural = structured.get(event_id)` is placed directly as the caption. This is what the synthetic probe shows (no model).

## Required fix (round 7, small)

- The repair re-check uses `judge_text` (facts when present), never raw `evidence_text`.
- Both paths may only place text that passes `acceptable(…, composed=True)`.
- The source for both becomes the **fact-list sentence** for that panel (from `canon/facts.py`), not `structured[event_id]` from `compose_caption`.
- If nothing passes, the panel has no caption. A panel with neither caption nor line is dropped.
- Delete or quarantine `compose_caption`'s "asked for / reported / worked on" verbs from any page-facing path. Keep them only for internal debug output.
- Tests:
  - a caption that passes against facts is not "repaired"
  - neither fallback can emit a `caption_problem` string
  - the synth probe produces 0 "worked on/asked for/reported" panels

## Acceptance

Unchanged from r6. KENSEI reads the 3 real scripts:
- every panel reads as a complete sentence
- 0 templates
- 0 owner quotes over 8 words
- episode 1 shows the benchmark result
- titles of 6 words or fewer
- all gates unchanged
