# Hermes integration surfaces (verified)

Verified 23/10/26 against upstream `NousResearch/hermes-agent` main **a4072ce7e67313eda344de4e4d691b6a5ba50164** (22/10/26).
The read-only clone is at `~/repos/hermes-agent-vanilla` (ref `upstream/main`; local `main` is stale, so use `git show upstream/main:<path>`).

The live install is the KenseiAgent fork: `hermes --version` → v0.22.2+…, install dir `/home/kensei/repos/KenseiAgent`.
Target the upstream API. If the live fork differs on anything you depend on, record it in your report; do not patch either repo.

| Need | Surface | Where it is defined |
|------|---------|---------------------|
| Manifest | `plugin.yaml`: `name`, `version`, `description`, `manifest_version` (1, or 2 max), `api_version: 1`, `requires_hermes`, `provides_hooks`, … | `hermes_cli/plugins_manifest.py`; docs `website/docs/developer-guide/plugins/index.md` §manifest (≈L609) |
| Validation | `hermes plugins validate .` and `hermes plugins doctor . --ci` | `hermes_cli/subcommands/plugins.py`, `hermes_cli/plugin_validate.py`, `hermes_cli/plugin_dev.py` |
| Slash command | `ctx.register_command(name, handler, description, args_hint)` (CLI + gateway) | docs §Register slash commands (≈L1738) |
| Call Hermes tools (image gen, vision) | `ctx.dispatch_tool("image_generate", {...})`, `ctx.dispatch_tool("vision_analyze", {...})`. These follow the user's configured `image_gen` and `auxiliary.vision` (D3). | docs ≈L925, L1856; `hermes_cli/plugins.py` `dispatch_tool` |
| `image_generate` args | `prompt`, `aspect_ratio` (landscape/square/portrait), `image_url`, `reference_image_urls` (≤16) | live tool schema |
| LLM calls | `ctx.llm.complete(...)`, `ctx.llm.complete_structured(...)` (JSON schema, `purpose=`) | `website/docs/developer-guide/plugin-llm-access.md` |
| Redaction (deterministic) | `agent/redact.py`; `ctx.register_redaction_patterns(patterns)` | `agent/redact.py`, `hermes_cli/plugins*.py` |
| Skill level-ups | hook `on_skill_lifecycle` (action, skill_name, provenance, session_id, use_count…) live; backfill from `~/.hermes/skills/.usage.json` | `tools/skill_usage.py` `_emit_skill_lifecycle`; `hermes_cli/plugins.py` `VALID_HOOKS` |
| Kanban teamwork | hooks `kanban_task_claimed/completed/blocked`; read `~/.hermes/kanban.db` read-only | `hermes_cli/plugins.py` `VALID_HOOKS` |
| Sessions | `state.db` tables `sessions` (id, source, title, started_at, ended_at, message_count, tool_call_count, cwd, git_branch, tokens…) and `messages` (session_id, role, content, tool_calls JSON, tool_name, tool_call_id, timestamp…). **No separate tool-calls table.** | `hermes_state_common.py` (`CREATE TABLE IF NOT EXISTS sessions` ≈L461, `messages` ≈L531) |
| Fleet | `~/.hermes/state.db` plus `~/.hermes/profiles/*/state.db` (66 profiles on this rig; 65 have a state.db) | — |
| Memory facts | `MEMORY.md` / `USER.md` (facts only, never full contents) | `tools/memory_tool.py` |
| Cron history | executions ledger (`hermes cron runs`) | docs ≈L1906–1914 |
| Weekly schedule | `ctx.register_automation_blueprint(key, title, description, schedule_template, prompt_template, …)`; the user enables it. **No direct cron writes.** | `hermes_cli/plugins_content.py`; docs ≈L1932 |
| Storage | `from plugins.plugin_storage import plugin_data_dir, plugin_db` → `<HERMES_HOME>/plugin-data/<name>/` | docs ≈L1152 |
| Dashboard tab (optional, not V1) | `dashboard/manifest.json` + `plugin_api.py` | `plugins/kanban/dashboard/`, `plugins/hermes-achievements/dashboard/` |
| A2A | `~/.hermes/a2a_audit.jsonl` exists only if the a2a plugin is used. It is **absent on this rig**, so treat it as optional input. | `plugins/platforms/a2a/security.py` |

Prior art (study, don't copy): `plugins/hermes-achievements` (bundled; session-history badges), catalog `hermes-quest` (RPG view of kanban; reads all profiles), Kumanga (MIT; reusable character-asset approach), DiffSensei (CVPR 2025).
