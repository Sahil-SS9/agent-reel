# Scrollback Reel: to-do list

Last updated 25/10/2026. Branch `m2-kensei` holds M2; `main` holds the accepted M1.

## Where things stand

- **M1 (story engine):** accepted by Quan (t_13eb5c20). Merged to `main`.
- **M2 (comic V1 + the widened scope):** Quan's re-review at `b0ed224` says it may close on conditions (t_d7d78e52, `QA-REVIEW-M2-v2`). Every gate passed at that exact version. That covers 520 tests, the frozen 24-case safety set, two meaning runs, the bundle and import checks, and plugin validate and doctor.
- **Installed:** `~/.hermes/plugins/scrollback-reel` is at `b0ed224`, with a clean tree.

## Next, in order

1. **Fix the last citation flaw (card t_6950a3d0, parked on purpose).** One true line pointed to the wrong messages as its proof. Quan's done-when:
   - Statement lines prefer the events that actually state them, over the panel's own ids.
   - In meaning mode, refuse a line when its cited events share none of its content words.
   - Add a regression test for the plan-v2 p1.1 shape.
   - A fresh plan re-trace shows zero misses, then Quan samples 5 lines plus 1 caption.
2. **Render one dense chapter page** and confirm the bigger lettering is readable at full-page size (QAR-M2-07). This needs an image run.
3. **Merge `m2-kensei` into `main`** once 1 and 2 pass. Owner decision.
4. **M2 acceptance (plan P8):** Sahil reviews 24 real panels and posts at least one himself. No auto-posting.

Items 1 and 2 must be done before any rendered page goes public.

## Waiting on Sahil

- Credit on OpenAI, Gemini or fal, so that each image source can move from mapped to tested. Each one reached billing on 25/10/26.
- Go-ahead for item 1 above.
- Whether the repo stays private (current state) or goes public ahead of plugin submission.

## Release (M3), not started

- Render the 11 experimental styles at least once each. Only anime and ink-pen-sketch are tested.
- Run `kit create` and `kit contribute` for real, producing one real sheet and one bundle.
- Test the Pi harness and the generic JSONL harness on real logs. Both are fixture-only today.
- Soak and batch runs on ComfyUI. So far there is one image, rated 4/5, with faint sign squiggles.
- Font licences and consent records for every named real person.
- Plugin catalogue submission.

## Parked for V2 (owner decision)

- Podcasts and motion episodes.
- The online space where users upload and share.

## Known limits (documented, not defects)

- In meaning mode, the plain-English rewrite yield is 6/8 to 7/8. Some true rewordings are refused, which is the safe direction.
- The meaning judge can accept a loose retelling. Item 1 adds a deterministic floor under it.

## Resume

```
cd ~/repos/hermes-scrollback-reel
.venv/bin/pytest -p no:cacheprovider -o addopts="" -q     # expect 520 passed
hermes plugins validate ~/.hermes/plugins/scrollback-reel
```

Evidence: `~/handoffs/agent-story-replay/build-evidence/M2/qa-fix/`. Status counts: `docs/m2-status.json`.
