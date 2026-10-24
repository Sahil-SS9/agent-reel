# M1 round 9 — KENSEI audit

Verdict: PARTIAL (agrees with the builder). R8-F2 (tool payloads out of briefs) accepted. Yield is still 1 story out of 3. M1 not closed; M2 not started.

Bound: repo 2f8fdfc clean; code identical to installed cdac413. Read run-final/episode-1-script.md, metrics.json and skipped_stories.

## What the evidence shows
- 5 of 6 captions in the surviving strip were refused ("not supported by the panel evidence"). Every refusal in the 7 other candidates has the same reason. The entailment judge is now the single bottleneck.
- The surviving strip does not read as a story. Its title is "Agentic Gaming Platform Plugin for Hermes"; its climax is a timed-out approval prompt, and its "win" is the owner picking option one. The win does not show a result.
- The builder's claim that the refused captions are true is plausible, but it is NOT verified: the refused sentences are not recorded with their evidence.

## Programme finding (controller)
This is the ninth round of M1, and since r5 each round has moved the failure to a new place: templates, then fragments, then empty endings, then judge refusals. The design asks one model to write and a second strict model pass to approve every sentence, with no human in the loop. The spec already requires human sign-off before anything goes public. So the strict automatic judge duplicates a gate that already exists, and it is the part that does not converge.

Recommended direction (owner decision):
- The owner chooses the story from a ranked shortlist (`hermes reel plan --list`, then `--story <key>`). Automatic weekly selection stays optional.
- Keep deterministic fact checks: every name, number, project alias and outcome claim in a caption or line must appear in that story's gated evidence. The redaction gate is unchanged.
- Replace the model-entailment veto with a preview the owner approves (or edits) before M2 renders anything. Unsupported-claim warnings are shown, not silently dropped.
- Acceptance: three owner-chosen stories, including the benchmark session, each produce a readable 4–6 panel script with a visible outcome, and the owner approves them.
