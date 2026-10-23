# Hermes Scrollback Reel: Spec v2

Name decided 23/10/26: "Hermes Scrollback Reel". No clash in the plugin catalog.

Ready-made cast decided 23/10/26. Two paths:
- (a) self-created or generated through the user's own image source
- (b) Hermes Multiverse repo characters. Their rights are "unknown-not-cleared", so private use only until cleared.

The first bake-off was GPT Image only; its results are in bakeoff-gpt-image/.

Rewritten 23/10/26 from "Hermes Chronicle: Handoff Spec" (21/10/26) after:
- a cross-check against upstream hermes-agent main a4072ce7e6 (22/10/26),
- a 5-question grill with Sahil,
- a source-quality research pass.

Kanban card: t_ec1754fc

## 1. What it is

A fun way to replay what you built and did with your AI. It turns your AI history into a short comic/manga you can share, and it keeps going week after week with the same characters and running storylines.

Goal: shareable output that people want to post. A book collection comes later.

Out of scope for V1: video, podcast, written prose chapters, a hosted gallery, and other AI tools (Claude Code, Codex, ...). The engine must not block these later.

## 2. Decisions (from the grill)

| # | Decision |
|---|----------|
| D1 | V1 is a comic/manga. |
| D2 | Built for other people, not only Sahil. Harness-agnostic core; Hermes is the first adapter. |
| D3 | Generation uses whatever the user has: local models or their own paid account. Sahil tests locally on 2x RTX 3090. |
| D4 | Styles: a few built-in styles to pick from, plus user-supplied custom styles. Built-ins must meet the quality bar (§7). |
| D5 | Likeness: the default is a ready-made character. Users can opt in to a character made from their own photo (consent step; photo stays local unless their provider needs it, with a warning). |
| D6 | Sharing: image files plus ready-to-post versions (X, LinkedIn, Discord, vertical strip) with a caption draft. Never posts automatically. |
| D7 | Episodes: a weekly 4-6 panel strip (automatic once the user enables it), plus an on-demand 8-12 panel chapter for big weeks. |
| D8 | Rename: "chronicle" is taken in the Hermes plugin catalog. Avoid "journey" too (Hermes Labyrinth uses it). |

## 3. Hermes integration (verified against source)

| Need | Use this (verified) | Not this |
|------|---------------------|----------|
| Sessions | every profile's `state.db`: tables `sessions`, `messages`. Tool calls are JSON in `messages.tool_calls` (+ `tool_name`, `tool_call_id`). `sessions` has `tool_call_count`, `cwd`, `git_branch`, tokens | only `~/.hermes/state.db`; a separate tool-calls table (none exists) |
| Fleet / profiles | iterate `~/.hermes/profiles/*/state.db` (66 profiles here), the same way hermes-quest does | single profile |
| Teamwork / rivalry | `kanban.db` plus the hooks `kanban_task_claimed/completed/blocked` | `a2a_audit.jsonl` (only exists if the A2A plugin is used; absent here) |
| Skill level-ups | hook `on_skill_lifecycle` (live) plus `~/.hermes/skills/.usage.json` and curator state (backfill) | scraping the skills dir |
| Memory facts | MEMORY.md / USER.md diffs, facts only | full contents |
| Cron rituals | the cron executions ledger (`hermes cron runs`) | parsing job output |
| LLM calls | `ctx.llm.complete_structured()` with JSON schema | own API keys |
| Redaction (deterministic pass) | `agent/redact.py` + `ctx.register_redaction_patterns()` | a new regex pack |
| Images | the Hermes image_gen provider plugins, plus a ComfyUI adapter for local | a parallel ImageProvider stack |
| Storage | `plugin_data_dir()` / `plugin_db()` → `~/.hermes/plugin-data/<name>/` | `~/.hermes/story/` |
| Weekly schedule | `ctx.register_automation_blueprint()`; the user enables it | writing cron jobs directly |
| Commands | `ctx.register_command()` (CLI + gateway) | — |
| Dashboard tab (optional) | `dashboard/manifest.json` + `plugin_api.py` (see the kanban and hermes-achievements plugins) | — |
| Manifest / CI | `manifest_version` 1 or 2, `api_version: 1`; `hermes plugins validate .` and `hermes plugins doctor . --ci` | — |

Prior art to study (not copy):
- **hermes-achievements**: bundled with Hermes; scans session history for badges. Reuse its detection ideas for the "level-up" beats.
- **hermes-quest**: catalog plugin; an RPG view of kanban and worker activity; reads every profile.

## 4. Engine (Canon): unchanged in shape, trimmed for V1

Ingest → Redact (hard gate) → Beats → Arcs → Canon update → Episode plan → Script IR.

The schemas from v1 are kept, with two additions:
- **Panel** in Script IR: `{id, shot: wide|medium|close|insert, cast[], pose, expression, setting, caption?, lines[{speaker, text, source_event_ids[]}]}`. Lettering stays separate from the art.
- **Cache**: every model call is keyed by `(stage, model, prompt-hash, input-hash)`. The same input gives the same canon. This replaces the v1 promise, which no model can keep without a cache.

Privacy:
- Levels: private, internal, public.
- Public export needs the user to sign off on every named entity, as well as a clean redaction scan.
- The cast allowlist is unchanged.

## 5. Comic renderer (V1)

The pipeline treats characters as **reusable assets**, not as fresh prompts for every panel. The pattern is proven by Kumanga (MIT) and the DiffSensei research.

1. **Character kit, made once per character and style:**
   - reference sheet: front, 3/4 and side views
   - 6-8 expressions
   - 4-6 key poses
   - the user approves the kit before any episode uses it
2. **Layout:** a page or strip template is chosen per episode. Use presets: 4-koma, 6-panel grid, webtoon vertical. ComfyUI-PanelComposer has 45+ presets and is a candidate for local use.
3. **Panel art:**
   - each panel is generated by a multi-reference model, conditioned on the character kit, the style card and the setting reference
   - no text is drawn inside the image
4. **Auto-check per panel:**
   - a vision model compares the panel against the kit (face, hair, outfit, colours)
   - panels that fail are regenerated, up to N tries; if they still fail, the episode is flagged
5. **Lettering:**
   - bubbles, captions and sound effects are added afterwards as SVG, never drawn into the art
   - fonts must be licence-clean. CC Wild Words and Anime Ace are NOT free for commercial use, so pick open or commercially licensed fonts and record the licence.
6. **Export:**
   - PNG pages
   - a vertical strip
   - social crops: X 16:9 / 1:1, LinkedIn 1.91:1 / 4:5, Discord
   - a caption draft
   - a sidecar JSON with the source event ids per line

**Style card** (built-in or user-supplied) contains:
- a name and a prompt block
- a negative block
- 3-6 reference images
- which models it was tested on
- a licence note

Built-ins can start from Sahil's existing style skills (Saga Noir, Ink & Ember, Baoyu Comic) and the style-registry format.

## 6. Generation sources (researched 23/10/26)

Quality ranks come from the Artificial Analysis text-to-image arena (human preference Elo, Oct 2026). These measure general image quality, not manga consistency, so the shortlist **must** be proven by our own bake-off (§7).

**Hosted (the user's own account):**

| Model | Why it's on the list | Notes |
|-------|----------------------|-------|
| GPT Image 2.5 / GPT Image 2 | #1-3 on the arena; strong edits that keep details consistent | already configured here (openai-codex gpt-image-2); most expensive (~$0.21/img via API) |
| Nano Banana 2.1 (Google) | #4 on the arena; multi-reference input | ~$0.03/img; best quality per pound |
| FLUX 3 / FLUX.2 (BFL) | official multi-reference character consistency (up to 8 refs) | ~$0.05/img |
| Seedream 5.0 Pro | strong on illustration | ~$0.09/img |

**Local (free, runs on 2x 3090):**

| Model | Why | Status here | Licence |
|-------|-----|-------------|---------|
| Qwen-Image-Edit-2511 | built for character consistency, multi-person scenes and multi-reference edits | **already installed** (fp8) in the running ComfyUI | Apache-2.0 ✅ |
| Krea 2 (turbo) | strong general generation | already installed | check before shipping |
| Illustrious XL / NoobAI XL + a character LoRA | best pure anime/manga line work; huge LoRA ecosystem | not installed | check per checkpoint |
| Qwen-Image-2.1 | strong unified gen + edit | not installed | research-only ❌ for a public product |

**Fallback for flagship characters:** train a small character LoRA (Ostris ai-toolkit) from the approved kit. Use it only if the bake-off shows multi-reference models drift.

**Watch, don't depend on:**
- DiffSensei (CVPR 2025): black-and-white manga, multi-character, fits on 24 GB
- MangaFlow (arXiv May 2026): an agentic story-to-manga pipeline with layout and lettering; check whether its code is out

## 7. Quality bar: "not half-baked" made testable

This is the bake-off, and it runs before any plugin code:
- Fixed test script: one 6-panel strip from a real week of Sahil's history, 2 characters, plus 1 close-up and 1 wide shot.
- Run it on at least 4 sources: GPT Image 2.x, Nano Banana 2.1, FLUX, and Qwen-Image-Edit-2511 local. Use 2 built-in styles.
- Score each run blind, by Sahil:
  - character consistency (1-5)
  - art quality (1-5)
  - "would I post this?" (yes/no)
  - also record cost and time per strip
- **Pass:** at least one hosted source AND at least one local source score ≥4 on consistency and get "yes, I'd post it" on 3 of 3 runs.
- **If nothing passes:** add the LoRA path and re-run once. If that also fails, stop the project. Don't build on weak art.

## 7a. Bake-off results (23/10/26), GPT Image only by Sahil's choice

**Round 1:**
- Art was approved ("pretty awesome").
- Story felt random: 6 unrelated highlights, because the Beats→Arcs stage was skipped.
- Balloons were badly placed: blind placement at fixed corners.

**Round 2: Sahil approved everything ("much better, happy with all of this output").**

Changes that fixed it, now part of the spec:
1. **One arc per episode.** Setup → hidden problem → diagnosis → climax → aftermath → win plus cliffhanger. Each panel causes the next. Add a recurring villain with its own sheet; Ep.1 introduced "The Orphans".
2. **Staging in every panel prompt.** Say who is LEFT/RIGHT/CENTRE, keep 25% headroom, and ban text in the image.
3. **Letterer v2** (reference implementation: `bakeoff-gpt-image/r2/letterer.py` + `episode.json`):
   - vision-detected head boxes, plus keep-out boxes for key objects
   - search over font size × wrap width
   - reading order: the next balloon sits right of the last on the same row, or below it
   - tails aimed at the speaker's face; rectangular "comms" balloon for off-screen or hologram speakers
4. **Automatic letterer check by vision.** It runs per panel and per page. Fail → re-place. All 12 panels passed after 3 iterations.

New requirements found:
- Re-query tight head boxes when the first boxes are coarse. They were coarse on 3 of 12 panels.
- Flag unscripted cast: the image model added Sahil to panels he wasn't in.
- Retry with backoff on provider 5xx (one 503 from Codex images).
- Layouts must accept the returned size: the provider ignores the requested aspect when given reference images.
- Aux vision must work. It is now openai-codex gpt-6.1-sol; the previous free route returned 403.

**Status:**
- §7 bar met for GPT Image on both styles (Sahil's sign-off).
- Local (Qwen-Image-Edit-2511) and the other hosted sources are untested, by choice. Run them before M3, so that V1 can honestly claim support for "whatever the user has".

## 8. Milestones

- **M0, spike, private:**
  - read-only adapter that prints the last 50 sessions plus skill events across all profiles
  - the §7 bake-off
  - exit when the bake-off passes
- **M1, engine:**
  - ingest, redaction gate, beats, arcs, canon, Script IR with source ids, cache
  - accept: 100% recall on secrets in the redaction benchmark, ≥95% on names, every line traceable to its events, same input → same canon
- **M2, comic V1:**
  - character kits
  - 3 built-in styles plus a custom style loader
  - layout, panels, auto-check, SVG lettering, social exports
  - the weekly blueprint and the commands
  - accept: a 4-week synthetic history plus 1 real week give consistent strips (human review of 24 panels), nothing unapproved is named, and Sahil posts at least 1
- **M3, release:**
  - per-episode cost and time budgets
  - privacy review of public mode
  - docs and a demo strip
  - catalog submission under the new name
  - `doctor --ci` green
- **Later, only if M2 strips get shared:** monthly/yearly book (PDF), more harness adapters, then video and podcast.

Kill test: after 4 real weekly strips, if Sahil isn't reading or posting them, stop.

## 9. Open items

1. The final name (catalog check).
2. Ready-made cast source:
   - Mike's care package is 3D Blender/Godot models with no licence found
   - Sahil's hermes-multiverse states "not a reuse licence"
   - so V1 may need an original default cast, designed for us
3. The lettering font choice, with its licence.
4. Whether Krea 2 and the Illustrious/NoobAI checkpoints may be used commercially.
5. Whether the photo-based likeness is allowed under each hosted provider's terms (check per provider).
