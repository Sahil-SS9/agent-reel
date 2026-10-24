# M1 round 8 — KENSEI audit

Verdict: PARTIAL (agrees with builder). Keep R8-1, R8-2, R8-4 and the selection controls. M1 not closed; M2 not started.

Bound: repo 3cbcd0e clean; code identical to installed 407e783 (`git diff --quiet 407e783 HEAD -- canon adapters tests __init__.py plugin.yaml` exit 0). Builder test log: 328 passed. KENSEI read the one surviving script, metrics.json briefs and skipped_stories. No reinstall, restart or model calls by this audit.

## Accepted
- Captions now read as written sentences (climax: "Every re-run finished, the full suite passed, and no skill made the AI worse for any persona."). No template text.
- Finished stories without a visible outcome are refused, not exported ending-less.
- Duplicate-thread guard, recording-grounder test.

## Findings
R8-F1 P1 — yield 1 of 3. Seven candidates refused because climax/win panels were dropped ("nothing written survived"). The ending rule is right; the writer is starved on exactly the panels that matter.

R8-F2 P1 — tool output inside briefs. The surviving episode's brief turns include raw tool-result JSON (a tool_search "not_found" result, a terminal result with redaction markers, a list of state.db table names). The aftermath caption "Kensei found that the chat history lookup tool is not currently available" comes from one. Earlier rounds established tool results are not story; that rule is not applied in canon/brief.py turn building. Turns must come from user/assistant prose only (and task titles/comments), never tool-call/tool-result payloads. Likely the main reason the aftermath is off-topic, and part of why outcome panels starve.

R8-F3 P2 — the brief goal contains an internal session id; facts remove it, but brief/goal text used for titles/logline should too.

R8-F4 P2 — evidence metrics.json carries full gated brief text (long outcome paragraphs). It is post-gate, but keep evidence to what review needs: truncate brief text in metrics to 160 chars as selection.as_dict already does.

## Next round (r9) — builder's own steps endorsed, plus F2 first
1. Exclude tool payloads from brief turns (F2); test with a session containing tool results.
2. Writer gets the panel facts plus the panel's gated evidence and is asked explicitly for the result sentence on climax/win.
3. Judge the ending against the brief outcome and panel evidence (no loosening). Re-measure yield; target 3 of 3 on the 7-day window, or a written reason per refusal that a human agrees with.
4. Then prove the benchmark strip on its recorded window.
