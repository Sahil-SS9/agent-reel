# M1 round 4 audit by KENSEI: PARTIAL. Story selection fixed; the writing still isn't readable.

Audited 23/10/26 at 240c64e. The builder reports 272 tests and all eval gates green. KENSEI read all three real scripts.

## What improved (keep it)

- **Stories are now real work, not bookkeeping.** The LCM-X vs Severian benchmark, the Chronicle spec review, the Dev Radio spec review.
- **Thread briefs exist and are rich.** The benchmark brief's outcome holds a genuinely good story: Severian 87.3 vs LCM-X 79.5 on LoCoMo, a tie on BEAM, LongMemEval in progress, a guard stopping a fallback.
- **The output is clean of junk.** No "Okay.", no raw `event:` captions, no masks.

## Findings

| ID | Severity | Finding | Required outcome |
|----|----------|---------|------------------|
| R4-F1 | **P1** | **Speaker roles are wrong.** The user's own messages are captioned "Kensei asked for … yes I approve 2", "Kensei asked for you seen to have conradicted yourself". Sahil asked, not Kensei. An unmapped "Assistant" appears as a character. | `role=user` → the owner (Sahil). `role=assistant` → the profile's character. "Asked" is only ever said of the owner. No "Assistant" character. |
| R4-F2 | **P1** | **Captions are truncated raw quotes of the owner's messages**, typos included ("docuement content =", "a link + a link cs/user_memory/results"). This is the r4 deviation "brief lines quoted verbatim, grounded by construction". It is safe but unreadable, and it publishes the owner's raw text. The rich outcome facts in the brief go unused. | Captions **paraphrase** facts from the brief in at most 20 words, checked by entailment on a raw model call (see R4-F4). Never quote the owner's raw text over 8 words. Anchor the climax and win on the brief's outcome facts (numbers, results), which are the story. |
| R4-F3 | P2 | **Dialogue is generic interjections** ("Typical.", "Ugh.", "Naturally.") unrelated to the panel. Episode 3 is fully silent; episode 2 is half silent. | Each line reacts to its panel's fact (e.g. "Seven points clear.", claim-checked). At most 1 generic interjection per episode. |
| R4-F4 | **P1 (root cause of the refusals)** | **The writer and judge go through the Hermes API server, which is a full agent.** Each call carries the Hermes system prompt: 2.04M prompt tokens for 36 calls (~57k per call), and the "judge" is an agent persona, not a clean model. That likely explains "entailment refused 5 of 6 briefs". The production `ctx.llm` is a raw model call. | Use the production path. A minimal plugin skeleton exposes `hermes reel plan --dry-run` (CLI only: no hooks, no schedule, no tools), which calls `ctx.llm`. KENSEI installs it into live Hermes (owner decision D12, brought forward; the builder still never writes `~/.hermes`). The builder runs dev rounds through that command. Log tokens per call. Target: under 5k prompt tokens per call. |
| R4-F5 | P2 | **Report accuracy.** "Three model titles of six words or fewer", but the headers are 15–20 words (thread title + model title). Episodes 2 and 3 share panels 2–3, both anchored on the same session opening, so they are not three distinct threads. | Count what is shown. Episodes in one run never share anchor events. |
| R4-F6 | P2 | Money figures ("$21.45 of $30") pass ungated in briefs and metrics. Financial masking only runs in `--deep`. | Fine for private mode. Public mode must mask money and health (D13), with a test. |

## Next

Round 5 is the last writer round before M2. If R4-F1..F5 pass, M1 closes and M2 starts. M2 also takes the owner's new decisions in `OWNER-DECISIONS-2026-10-23.md`.
