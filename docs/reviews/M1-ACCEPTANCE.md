# M1 (story engine) — acceptance record

Accepted 24/10/26 on an independent QA PASS from Quan (kanban t_13eb5c20). Quan's reports are attached to that card; the earlier rounds are on cards t_0ea810b2 and t_8645faf5.

- Accepted code: f2ccfbb69ab80d2dd64659c50f08c36e50787c93, branch m1-r10-kensei. Built by KENSEI directly after Sahil's override on 24/10. This is also the version installed in live Hermes.
- Not yet merged into main. The branch merge is Sahil's call.

## Evidence (independent)
- 395 tests pass on a clean clone.
- Quan's frozen 24-case trick set, run through the production judge (ctx.llm): all 24 false lines refused; 21 of 23 valid rewordings accepted.
- Quan's unchanged regression files pass: 2/2 and 10/10.
- Independent caption trace: 18/18 sampled captions supported by the events they cite, including who did what.
- Real runs at f2ccfbb produced 3/3 episodes for the current week and for 10–12 September.

## Known limits (carried into M2, not blockers)
- Two of the three week-run titles fall back to "A session" (P2; card t_3c0902f0, parked until M2).
- The 50% vocabulary floor still refuses some synonym-heavy true captions (QAR10-04, documented).
- Story quality: bookkeeping stories are still sometimes chosen; some panels restate each other; final panels are always labelled WIN.
- The finished benchmark result (87.3 vs 79.5) has not appeared on a strip. The in-progress benchmark session is told and ends "to be continued".
