# Release evidence, 26/10/2026

What has been run and what it returned. No claim here is inferred: every line points at a
command that was run or a file that exists.

## Verified

| Area | Evidence |
|---|---|
| Test suite | `pytest`: **662 passed** at `6a66353` (was 559 at the start of the release pass). |
| Plugin validation | `hermes plugins validate .` → **Validation passed**; manifest v2, `pillow>=10.0,<14` declared, no hooks and no tools. |
| Upstream admission | Clean clone of `NousResearch/hermes-agent` at `9b904dcc`, its own venv: `doctor_plugin()` → **ok? True, findings: []**. |
| Lettering readability | Real chapter page: smallest placed line **18.9pt** against a 15.8pt floor (independent review, t_951f7939). The floor is a named constant with a geometric test. |
| Balloon placement | Dense page: **12 of 12 lines placed, 0 unplaced** after the tier fix (3 placed / 7 dropped before it). Tails now stop short of a neighbouring balloon instead of crossing it. |
| Dialogue line budget | Long lines split at sentence or clause ends to fit a balloon at page font size; a line with no such boundary runs up to 35% over rather than being cut mid-phrase. |
| Story layer | Narration may interpret; new events are refused. Names and numbers are checked deterministically before any model sees them, and with no model the engine falls back to strict captions. |
| Real lines | Where a message already says the thing, the comic uses those words; the cold-open hook and the editor's readout check are covered by their own tests. |
| Arc variety | Each thread is told in the shape it has, not always as a monster fight. |
| Deterministic villain | Villain named from the chapter's deck archetype; the reference sheet is drawn once per (villain, style) and reused. Tests pin both. |
| Story variety | Two chapters planned back to back in one week: different story, thread, world, villain, genre, conflict (previously the same story four runs running). |
| Idea deck | 50/51/50/51/51/51 entries → **16,913,002,500** frames; tests pin the 50 minimum and check reach over 59 chapters. |
| Styles | **55** style cards. `ligne-claire`, `halftone-noir` and `risograph-print` carry their own world, composition, impact frame and lettering; a contrast test fails if any two converge. |
| Harness readers | Hermes, Claude Code, OpenAI Codex CLI and OpenCode have built-in readers; Pi and any JSONL harness are covered by a mapping file. |
| Claude Code, end to end | Real log corpus: 10,472 raw sessions → **30 threads → 2 arcs → a 6-panel episode, exit 0**. Grouping sessions into the work they were about is what produced the arc. |
| ComfyUI soak | Three consecutive real generations: **260s, 278s, 260s**, all 1536×1024, zero failures, on the local GPU. |
| Character sheet | `reel kit create` produced a real sheet from the set-up answers through the host image source. |
| Contribution bundle | Built with two style previews and PR text; scanned: **no absolute paths, no prompts, no credentials**. |
| Fonts | Comic Neue Bold and Bangers, both SIL OFL 1.1, licence files shipped (`assets/fonts/OFL.txt`, `FONTS.md`). |
| Read-only history | `scripts/readonly_proof.sh` (strace): no file created, renamed, truncated or deleted under the Hermes home. |

## Tuned during release

| Area | What the evidence showed | What changed |
|---|---|---|
| ComfyUI framing | One soak panel rated 3/5: no text or anatomy defects, but a close-up left no headroom for balloons. | The panel prompt asks for headroom; close-ups with no empty space are regenerated rather than shipped. |
| Meaning-mode rewrite yield | 6/8 → 7/8 → 8/8 true plain-English rewrites accepted across runs; refusals are the safe direction. | A deterministic content-word floor now refuses unsupported meaning rewrites before the judge is paid for. |
| Lettering at page scale | Dense pages needed a larger page font; some lines had no pocket at the old scale. | Page font measured rather than panel-derived (`PAGE_FONT_SCALE 2.0`), three-tier placement, and any line that still cannot be placed is recorded in the sidecar and reported, never silently replaced. |

## Coverage

| Area | State |
|---|---|
| Styles | All 55 are renderable. Two carry a recorded bake-off and are marked as such; `--strict-styles` limits a render to those. |
| Image routes | `host` and `comfyui` are exercised in normal use; `openai`, `gemini` and `fal` are implemented against each vendor's Images API and need a key Hermes holds. |
| Harnesses | Hermes, Claude Code, Codex and OpenCode ship readers; Pi ships a reader built from its documented session format; anything else is a JSON mapping file. |
| Book and schedules | `reel book` built a real monthly book from renders; schedules are user-created crons, nothing is registered by the plugin. |

## Publication gate

Ready to publish as a plugin: suite, validation, upstream admission, fonts, privacy proof,
manifest, README, licence.
