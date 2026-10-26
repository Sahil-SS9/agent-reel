# M1 round 7 — bounded KENSEI audit

Verdict: PARTIAL. Accept the two specific repair-path corrections; M1 writing acceptance remains open. Do not start M2.

Candidate inspected: bcabf69, clean worktree. Installed plugin: fa95c8d9452ba9e5c86f36f15ef29d5232aff362. `git diff --quiet fa95c8d HEAD -- canon adapters tests` exits 0, so inspected production/test bytes match the installed commit. No installs, restarts, commits or model calls performed by this audit.

Fresh execution: `.venv/bin/python -m pytest -p no:cacheprovider tests/test_r7_bypasses.py` -> 4 passed, exit 0. `git diff --check` -> exit 0. The full suite and privacy/model evaluations were NOT re-executed; their reported results remain builder evidence, not fresh independent measurements.

Read all three numbered scripts and corresponding IR files under ~/handoffs/agent-story-replay/build-evidence/M1-r7/run/; inspected the r6-to-r7 diff, canon/facts.py, canon/selection.py, and the four regression tests.

## Accepted correction

The second grounding check now uses judge_text, and the repair/empty-panel paths route through _policy_caption rather than directly selecting structured[event_id]. Retain these corrections. The inspected artifacts contain no old worked-on/asked-for/reported caption templates.

## Findings against existing acceptance (not new scope)

### R7-F1 — P1: complete-sentence claim contradicted by actual scripts

Episode 1 panel 1: "Sahil wants please read and review this idea/concept."
Episode 1 panel 4: "Kensei described I couldn't open the artifact."
Episode 2 climax: "The GPT Image test is done: 2 comic."
Episode 3 panel 1: "Sahil wants the session a session broke i think."
Episode 3 panel 2: "Kensei handled Fix broken a session..."

These are clipped input fragments with a new verb, not polished narrator sentences. Replacing 'reported' with 'described' avoided a forbidden string without solving the underlying writing requirement. Root seam: canon/facts.py Fact.sentence (lines 73–85) mechanically concatenates actor/action/object; _first_clause shortens raw input to seven words. Keep facts as evidence, not automatically page-ready prose. Generate grammatical paraphrases under unchanged factual/echo limits. If none pass, refuse that candidate rather than claim readable output.

Done when: three real scripts read naturally without the constructions above; goal/turn/outcome inputs include imperative requests, first-person assistant messages and truncated titles in regression tests. Do not special-case the quoted strings.

### R7-F2 — P1: dropping empty panels removes the ending

Episode 1 IR has roles setup, hidden_problem, climax, aftermath; its win was dropped, while cliffhanger=false. Episode 3 also drops win and has cliffhanger=false. Episode 2 labels a request to explain more simply as WIN; the visible text does not establish a win. A minimum panel count is not an ending.

Root seam: canon/episode.py empty-panel drop near 790, followed by cliffhanger determined solely from arc.status near 821. Keep fail-closed panel dropping, but validate the resulting episode: visible sourced outcome, or genuinely unresolved story with an explicit continuation. If neither is supported, skip/refuse the episode with a reason; never invent a win or reclassify a finished thread as unfinished simply to satisfy a checkbox.

Done when: a finished arc whose result panel is rejected cannot export as a completed story without a visible outcome; ordinary complete stories still export. Three real scripts have intelligible supported endings.

### R7-F3 — P1: requested real outcome still unproven; ranking diagnosis only partly established

No selected script covers the benchmark, so 87.3/79.5 in the synthetic fixture does not satisfy the real-script requirement. canon/selection.py score (104–106) gives user_turns first priority; its outcome flag merely checks that some last assistant text exists (157–158), not that work finished. Long conversations can therefore outrank concrete results. The actual selected review conversations are not automatically invalid stories: the defect is poor substantive selection, not the word 'review'.

Done when: general ranking favours substantive supported outcomes over conversation length/bookkeeping, without hard-coding benchmark names or rewarding arbitrary digits. Include qualitative completed work as a positive control. Separately use a fixed existing benchmark thread/window to demonstrate that the real pipeline preserves and displays the requested scores with their subjects, metric and outcome status. If that source is outside the current window, state that and use its recorded window; do not fabricate/relabel a different episode.

## Proof gap in the new regression test

`tests/test_r7_bypasses.py::plan` supplies no grounder. Thus its 'passes against facts is not repaired' test does not exercise the repaired second-grounding-check branch at all. Add a deterministic recording grounder which accepts fact evidence and rejects the raw-evidence alternative; assert the actual branch calls and emitted result. This is affected-path proof, not a request to repeat unchanged full-system evaluations.

## Controller correction

My earlier statement that one more small fix would finish M1 was premature. The repair bypass was real, but its closure does not prove readable prose or preserved endings. Also, `hermes reel plan --dry-run` produces scripts/IR, not rendered comics. M2 remains unstarted. No M1 closure or M2 approval granted.
