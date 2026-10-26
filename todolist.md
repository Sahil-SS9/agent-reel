# Scrollback Reel: to-do list

Last updated 26/10/2026. `main` and `m2-kensei` are the same commit (f222ac1); the installed plugin matches.

## Where things stand

- **M1 (story engine):** accepted by Quan (t_13eb5c20). On `main`.
- **M2 (comic V1 + widened scope):** Quan's re-review says it may close on conditions (t_d7d78e52). Every gate passed at the reviewed version: 520 tests, frozen 24-case safety set, two meaning runs, bundle and import checks, plugin validate and doctor.
- **Citation proof trails:** Quan re-sampled and passed the fix (t_dc519def); his four follow-up findings are fixed and approved (t_abdaa3a9). 549 tests now.
- **Lettering:** Quan conditional pass at 6368f0c — smallest line 18.9pt against his 15.8pt bar. His two conditions are fixed (a dead middle tier; the missing font-floor test). His third condition (a full 13-panel page at 0 unplaced) has a redraw in flight.
- **Variety and continuity (M3 work):** built and proven. Two chapters planned back to back in the same week:
  - chapter 1 "No Candidate Passes the Rule" — desert relay, parasite villain, quiet drama, silent regression;
  - chapter 2 "Make It Fail Before It Airs" — drowned archive, last-commit villain, survival siege, hidden fault.
  Before this, four consecutive runs all told the same "Four Lost" story.
- **Idea deck:** 50 conflicts, 51 worlds, 50 genres, 51 villains, 51 motifs, 51 shots — 16,913,002,500 frames. Vocabulary informed by the local Midlibrary catalogue; wording is ours. Tests pin the 50 minimum and check reach over 59 chapters.

## Next, in order

1. **Finish the lettering proof (Quan's D2):** one dense page, all 13 panels, zero dropped lines, exit 0. The redraw is running now. Nothing needs your input.
2. **M2 acceptance (plan P8):** you review 24 real panels and post at least one yourself. No auto-posting. This is the gate before anything goes public.
3. **Decide on publishing:** the repo is private. Going public, and the plugin catalogue submission, are your calls.

## Waiting on Sahil

- Credit on OpenAI, Gemini or fal, so those image sources move from mapped to tested. All three reached billing on 25/10/26.
- Whether the repo stays private or goes public ahead of submission.
- Your panel review for acceptance (item 2 above).

## Release stage, not started

- Render the 11 experimental styles at least once each. Only anime and ink-pen-sketch are tested.
- Run `kit create` and `kit contribute` for real: one real sheet, one bundle.
- Test the Pi harness and the generic JSONL harness on real logs. Both are fixture-only.
- Soak and batch runs on ComfyUI. One image so far, rated 4/5, with faint sign squiggles.
- Font licences and consent records for every named real person.
- Plugin catalogue submission.

## Parked for V2 (owner decision)

- Podcasts and motion episodes.
- The online space where users upload and share.

## Known limits (documented, not defects)

- In meaning mode the plain-English rewrite yield is 6/8 to 7/8. Some true rewordings are refused, which is the safe direction.
- Tone and metaphor lines cite their panel's messages as loose context. They assert no fact, so the meaning judge decides them.
- At the larger page font, two dense lines per chapter can fail to fit and are dropped (recorded, never replaced). The redraw in item 1 is measuring this.

## Resume

```
cd ~/repos/hermes-scrollback-reel
.venv/bin/pytest -p no:cacheprovider -o addopts="" -q     # expect 549 passed
hermes plugins validate ~/.hermes/plugins/scrollback-reel
```

To view a rendered page over SSH:

```
ssh -N -L 8770:127.0.0.1:8770 sahil@100.93.30.36
# then, on the rig, in the render folder:
python3 -m http.server 8770 --bind 127.0.0.1
# then open http://localhost:8770/
```

Evidence: `~/handoffs/agent-story-replay/build-evidence/M2/qa-fix/`. Status counts: `docs/m2-status.json`.
