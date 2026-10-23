# HANDOFF: build Hermes Scrollback Reel (M0 → M2)

You are the build agent. KENSEI (the owner's controller agent) audits your work after each stage.
Read this file fully, then `docs/decisions.md`, `docs/SPEC.md`, `docs/hermes-surfaces.md` and `reference/bakeoff-r2/`.
`docs/decisions.md` wins every conflict.

## 0. What you are building

A Hermes plugin that turns a user's real agent history into a **weekly comic strip** with continuing characters and storylines, plus on-demand longer chapters.

Pipeline: history → redacted events → beats → story arcs → episode script → character kits → staged panel art → vision-placed lettering → share-ready exports.

The art style and letterer method are already proven (bake-off round 2, approved by the owner). Your job is to turn that proof into a tested, reusable plugin.

## 1. Ground rules (hard; breaking one fails the stage)

1. **Run as the `kensei` user.** Work only in `/home/kensei/repos/hermes-scrollback-reel`. Commit locally on `main` or a feature branch.
   - **No push, no remote, no publishing, no catalog submission, no PRs.**
2. **Hermes state is read-only.** Open every SQLite DB with `sqlite3.connect("file:<path>?mode=ro", uri=True)`.
   - Never write to `~/.hermes` (config.yaml, .env, auth, plugins, skills, memories, cron, kanban, state.db).
   - Never install or enable this plugin in the live Hermes.
   - No gateway or service restarts, no sudo, no systemd, no crontab.
3. **Don't touch other repos**: `~/repos/KenseiAgent`, `~/repos/hermes-agent-vanilla` (read only via `git show upstream/main:<path>`), the Hermes Multiverse folders (read only).
4. **No secrets in code, logs, fixtures or commits.** Never copy credentials or auth files anywhere.
5. **Real history never enters the repo.**
   - Fixtures are synthetic.
   - Outputs from real-data runs go to `/home/kensei/handoffs/agent-story-replay/build-evidence/<stage>/` and must pass the redaction gate first.
6. **Image budget.** Generate images only through your own Hermes `image_generate` tool, which uses the owner's configured provider (openai-codex gpt-image-2).
   - Max **40 images per stage**. Log each call (prompt hash, refs, output path, time) to the stage evidence folder.
   - No other paid APIs.
7. **No GUI on the owner's display.** Headless only. If you need to show something, write files and say where.
8. **Licences.** Fonts are OFL only (Comic Neue, Bangers). Do not add a LICENSE file to the repo; the owner decides the licence.
9. **Stop after each stage** (§4) and write the report. Do not start the next stage until KENSEI or the owner says GO.
10. **Honesty.**
    - Never claim a test, run or image you didn't produce.
    - Label every result VERIFIED (you ran it), PARTIAL, or NOT DONE.
    - A blocked step is reported as blocked, never faked.

## 2. Architecture you must keep

```
hermes-scrollback-reel/
  canon/            # pure Python core. NO Hermes imports (decision D2). Ingest, redact, beats, arcs, canon, script IR
  render/           # comic renderer core: kits, staging prompts, layout, letterer, checks, exports. NO Hermes imports
  adapters/hermes/  # the ONLY place that imports Hermes: state.db/kanban/skills/memory/cron readers,
                    # ctx.llm client, dispatch_tool image + vision backends, plugin registration
  plugin.yaml  __init__.py   # thin plugin entry -> adapters/hermes
  styles/           # style cards: anime-colour, ink-manga, +1 (decision P2)
  fixtures/         # synthetic 4-week multi-profile history
  eval/             # redaction benchmark, letterer benchmark
  tests/
```

- **Interfaces**: `LLMClient`, `ImageBackend`, `VisionBackend`, `HistorySource`. Tests use fakes. The plugin uses Hermes implementations: `ctx.llm`, and `ctx.dispatch_tool("image_generate"|"vision_analyze")`.
- **Two-phase render for real runs outside the live plugin**:
  - `reel plan` writes `render-plan.json` (panel prompts, refs, staging).
  - **You** generate the images with your own `image_generate` tool into a folder.
  - `reel assemble` checks the panels with vision, letters them and exports.
  - This is how you smoke-test without installing into live Hermes.
- **Every script line** carries `source_event_ids`.
- **Every model call** is cached by `(stage, model, prompt_hash, input_hash)`. The same input gives the same canon.
- Use a repo-local venv: `uv venv .venv --python 3.12 && uv pip install --python .venv pillow pytest jsonschema pyyaml`. Add other deps only if needed, and list them in the report.

## 3. State verification (run first; paste the outputs in the M0 report)

```bash
cd /home/kensei/repos/hermes-scrollback-reel && git log --oneline -1   # expect the pack commit KENSEI gave you
git -C ~/repos/hermes-agent-vanilla merge-base --is-ancestor a4072ce7e67313eda344de4e4d691b6a5ba50164 upstream/main; echo $?   # expect 0 (surfaces were verified at a4072ce7e6; upstream/main moves, so check ancestry, not equality)
hermes --version                                                        # expect v0.22.2+... KenseiAgent fork
hermes plugins --help | grep -E 'validate|doctor'                       # expect both listed
ls ~/.hermes/profiles/*/state.db | wc -l                                # expect ~65
sqlite3 "file:$HOME/.hermes/state.db?mode=ro" "select count(*) from sessions"   # expect a positive number
ls "/home/sahil/Pictures/Hermes Multiverse/sahil/styles/anime/"         # expect sahil__sheet__anime__v01.png
```

If any expectation fails, stop and report. Don't work around it.

## 4. Stages, gates and evidence

### Stage M0: history adapter (read-only)

- `adapters/hermes/history.py` reads all profiles (sessions + messages + tool calls from `messages.tool_calls` JSON), `kanban.db` (tasks, assignee, status changes), skills `.usage.json`, cron runs and MEMORY/USER fact diffs into one normalised `Event` stream. Schema per SPEC §4.
- Write `canon/HERMES_SCHEMA.md` mapping each source table/field → Event.
- CLI: `python -m adapters.hermes.history --days 7 --summary` prints counts per profile and source, plus the last 50 sessions (title, profile, time, message count). It must not print message content.
- Synthetic fixture generator: 4 weeks, 4 profiles, kanban + skills + cron.

**Gate:**
- the read-only proof: run under `strace -f -e trace=openat` or equivalent and show no write opens under `~/.hermes`, OR prove every DB open uses `mode=ro` and no other file is opened for writing
- a real-data summary run
- tests green

### Stage M1: Canon core

1. **Ingest**, idempotent on re-run.
2. **Redaction gate:**
   - deterministic pass: secrets, high-entropy strings, emails, phones, IPs, out-of-project paths, tokenised URLs; reuse Hermes' `agent/redact.py` patterns through the adapter
   - model pass: client names, non-allowlisted people, internal project names, financial or health details
   - quarantine for failures
3. **Beats → arcs**, using the arc template in decisions "Proven method" #1.
4. **Canon**: entities, facts with event ids, a retcon log that never overwrites a fact silently.
5. **Episode planner + Script IR**, for both the weekly 6-panel strip and the 8–12 panel chapter. Panels carry staging and speaker per line.
6. **Cache.**

**Gate:**
- redaction benchmark (`eval/redaction/`, synthetic, ≥200 labelled items): **100% recall on secrets, ≥95% on names**
- every IR line resolves to real event ids
- the same input twice gives byte-identical canon and IR
- a real-data dry run produces one episode script from the last 7 days. Script only, no images; save it to evidence after redaction.
- KENSEI audit question for the report: does the script read as ONE story where each panel causes the next?

### Stage M2: comic renderer + plugin

1. **Style cards** (`styles/*.yaml`): prompt block, negative block, 3–6 reference images, tested-on models, licence note. Ship anime-colour, ink-manga and one more (P2). Support a custom style loader.
2. **Character kits:**
   - Multiverse loader (private-only flag, D9)
   - generated original cast (P3)
   - photo opt-in flow with consent and a warning (D5); no real photo is needed in tests
3. **Staged panel prompts** from the IR (decisions "Proven method" #3).
4. **Port and harden the letterer** (`reference/bakeoff-r2/letterer.py` is the proof, not production code):
   - tight-box re-query
   - keep-outs
   - reading order
   - comms balloons
   - SFX
   - **unit tests on fixed fixtures** with synthetic boxes
5. **Checks**: vision letterer check, unscripted-cast flag, consistency check against the kit, retry with backoff on 5xx.
6. **Exports**: PNG/JPEG page (2×3), X 3×2, vertical strip, LinkedIn 4:5, Discord, caption draft, `episode_sources.json`.
7. **Plugin wiring:**
   - `plugin.yaml`
   - `/reel status|next [--chapter]|special <arc>|cast approve|rename|hide <entity>|privacy <level>|retcon <fact>|setup`
   - a weekly automation blueprint via `register_automation_blueprint`, **disabled until the user enables it**
   - storage via `plugin_data_dir`
   - `hermes plugins validate .` and `hermes plugins doctor . --ci` pass. Run doctor against the repo path only; do not install.

**Gate:**
- tests green
- validate + doctor output pasted
- **real smoke**: one weekly strip from the last 7 days in **both** built-in styles via `reel plan` → your `image_generate` → `reel assemble` (≤40 images)
- the vision letterer check passes on all panels
- outputs in evidence plus a `index.html` gallery

Stop. The owner reviews the art.

## 5. Report (write `docs/reports/M<n>-REPORT.md`, commit it, then stop)

```
# M<n> report: <PASS | PARTIAL | BLOCKED>
Plain-English summary (3-5 bullets, no jargon).
Commit: <full sha>   Branch: <name>
Gate results: one line per gate item, labelled VERIFIED / PARTIAL / NOT DONE, with evidence path.
Commands to reproduce: exact commands + expected output.
Tests: <count passed/failed>, command used.
Images generated: <n>/40, log path.
Deviations from SPEC/decisions, and why.
KENSEI defaults (P1-P4) you relied on.
Open questions for the owner (max 5, each with your recommendation).
Known gaps / not checked.
```

## 6. Out of scope (do not build)

- video, podcast, prose, the book
- a dashboard tab
- other harness adapters
- a hosted gallery
- auto-posting
- catalog submission
- M3 (release hardening)
- installing into live Hermes
