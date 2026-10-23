# M1 round 5 audit by KENSEI: PARTIAL (agrees with the builder). One focused round, then M1 closes.

Audited 23/10/26 at 7844adf. The installed plugin is pinned to 5cb391b (same code), enabled, and the gateway is unaffected. The reinstall log is complete (2 refusals explained, 3 successes).

## Wins (keep)

- **Production path.** `ctx.llm` is in use, max 2,219 prompt tokens per call (down from about 57k).
- **Roles fixed.** The owner's lines now have real voice: "Number two in the world, they say? Let's see those numbers hold up under a real light." / "Fair benchmarks. Not a cent more. And don't burn my rainy-day credits." This is the target tone.
- **Aliases work.** "Project Lantern" replaced the Chronicle name.
- Public-mode masking of money and health is in place.

## Findings

| ID | Severity | Finding | Required outcome |
|----|----------|---------|------------------|
| R5-F1 | P1 | **Kensei's lines are broken template fragments**: "Worked on Benchmark LCM-X against Severian Memory.", "Reported I couldn't open the artifact, so.", "Reported Go received.", "Is my review reply for the build.", "Run is healthy and on schedule..". These are fallbacks that truncate the evidence mid-sentence. | Kill the `Worked on …` / `Reported …` dialogue fallbacks. Kensei's lines are written like Sahil's (in character, reacting) and claim-checked against the brief's facts. If they fail, the panel has no Kensei line. |
| R5-F2 | P1 | **Captions still quote the owner raw**: ep2 p4 "Sahil asked for see docuement content = Project Lantern: Handoff Spec Oct 21, 2026.", ep2 p6, ep3 p2. This contradicts the report's "a composed caption never echoes the owner". The "asked for" composer bypasses the echo check. | Every caption path goes through the same echo and length check. No caption starts "X asked for …" or "X reported …". |
| R5-F3 | P1 | **The real result is missing.** Episode 1's brief holds the outcome (Severian 87.3 vs LCM-X 79.5 on LoCoMo, a tie on BEAM), but the climax/win shows "Run is healthy and on schedule..". | The climax and win panels must state the brief's outcome facts (numbers, results). |
| R5-F4 | P2 | Header titles are 10–18 words and ep2's title is a raw owner fragment ("please read and review this idea/concept — Sahil asked for simplify…"). | The header is the 6-word model title only. If the title fails grounding, use the thread title, shortened on a word boundary. Never the owner's raw message. |

## How (the builder's own proposed fix, endorsed)

1. Turn each brief into a short list of **atomic facts** (actor, action, object, result, numbers). Each one is already entailed by its events.
2. Captions and lines are judged against that fact list (short, clean), not against long raw evidence. That should lift caption coverage and stop the fallbacks.

## Acceptance (final for M1)

- Every panel has a caption **or** a line that reads as a complete sentence.
- 0 `Worked on`/`Reported`/`asked for` templates.
- 0 owner quotes over 8 words.
- Episode 1's win shows the benchmark result.
- Titles of 6 words or fewer.
- All safety gates unchanged.
