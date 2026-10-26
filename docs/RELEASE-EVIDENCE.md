# Release evidence, 26/10/2026

What has actually been run, what has not, and what that means for publishing. No claim in
this file is inferred: every line points at a command that was run or a file that exists.

## Tested and working

| Area | Evidence |
|---|---|
| Test suite | `pytest`: **559 passed** at d32a5d0. |
| Plugin validation | `hermes plugins validate .` → **Validation passed**; manifest v2, `pillow>=10.0,<14` declared. |
| Upstream admission | Clean clone of `NousResearch/hermes-agent` at `9b904dcc`, its own venv: `doctor_plugin()` → **ok? True, findings: []**. |
| Lettering readability | Real chapter page: smallest placed line **18.9pt**, against a 15.8pt floor (independent review, t_951f7939). Font floor now a named constant with a geometric test. |
| Balloon placement | Best dense-page run: **12 of 12 lines placed, 0 unplaced** (was 3 placed / 7 dropped before the tier fix). |
| Deterministic villain | Villain named from the chapter's deck archetype; the reference sheet is drawn once per (villain, style) and reused. Tests pin both. |
| Story variety | Two chapters planned back to back in one week: different story, thread, world, villain, genre, conflict (was the same story four runs running). |
| Idea deck | 50/51/50/51/51/51 entries → **16,913,002,500** frames; tests pin the 50 minimum and check reach over 59 chapters. |
| Styles | **55** style cards (anime and ink-pen-sketch tested; 53 experimental and refused unless opted in). Two new style/release tests pin the catalogue size and the insert mark. |
| ComfyUI soak | Three consecutive real generations: **260s, 278s, 260s**, all 1536×1024, zero failures, via the local GPU. |
| Character sheet (`kit create`) | Real sheet produced from the set-up answers (`anime.png`) through the host image source. |
| Contribution bundle (`kit contribute`) | Bundle built with 2 style previews and PR text; scanned: **no absolute paths, no prompts, no credentials**. |
| Fonts | Comic Neue Bold + Bangers, both SIL OFL 1.1, licence files shipped (`assets/fonts/OFL.txt`, `FONTS.md`); commercial-only comic fonts deliberately excluded. |
| Read-only history | `scripts/readonly_proof.sh` (strace): no file created, renamed, truncated or deleted under the Hermes home. |

## Tested, with findings

| Area | Finding |
|---|---|
| ComfyUI quality | One soak panel rated **3/5**: no text, no anatomy defects, but a close-up framing left **no headroom for balloons**. The prompt asks for headroom; the local model ignored it on a close-up. Actionable: enforce headroom in the panel prompt or regenerate close-ups with explicit empty space. |
| Meaning-mode rewrite yield | 6/8 to 7/8 true plain-English rewrites accepted across runs. Refusals are the safe direction, and the deterministic floor added on 26/10/26 refused none of the accepted ones. |
| Lettering at large font | Two dense lines per chapter can still fail to place and are dropped (recorded in the sidecar, never replaced). The full 13-panel zero-drop page is not yet reproducible because the art underneath changed every render; the villain fix is what makes it stable now. |

## Not tested / not working

| Area | State |
|---|---|
| `jsonl` / other-harness stories | **Fixed 26/10/26.** Claude Code starts a session per invocation (10,475 files, ~2 messages each), so one-session-per-thread gave 10,472 threads and no arc. A thread is now the work, not the process: Claude groups by project folder and a jsonl mapping can name a thread field (`"thread": "cwd"`). Real-log probe: 10,472 threads → 30, arcs 0 → 2. A real `hermes reel plan --harness jsonl` now returns **1 episode, 6 panels, exit 0**. |
| `codex` harness | Reads **633 real log files (2,552 messages)** read-only, but this machine's Codex corpus is prompt-only and yields no arc. Honest limitation, not a support claim. |
| `pi` harness | No Pi logs exist on this machine; fixture-only. Documented as untested. |
| Paid image sources | `openai`, `gemini`, `fal`: request shapes implemented, live calls reached billing and stopped (no credit). **Mapped, not tested.** |
| 53 of 55 styles | Never rendered. Marked experimental; the render refuses them unless opted in. |
| Monthly book, schedule blueprints | Book built from real renders once; schedules register but no automation was created. |

## Publication gate

Ready to publish as a plugin: suite, validation, upstream admission, fonts, privacy proof,
manifest, README, licence.

Honest gaps a user can meet on day one: the experimental styles are unrendered, the paid
image routes are unproven, and non-Hermes harnesses do not yet produce stories. All three
are stated in the docs rather than hidden; the harness gap is carded as a blocker for the
"works with other agents" claim.
