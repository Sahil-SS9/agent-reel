# Hermes Scrollback Reel

Turns your AI agent's real history into a weekly comic strip with continuing characters and storylines.

Status: M0 complete (read-only history adapter, normalised event stream, synthetic fixture). M1 and M2 not started; nothing is installed in Hermes.

## Document map (read in this order)

1. `docs/HANDOFF.md`: build instructions, ground rules, stages, gates, report format. **Build agents start here.**
2. `docs/decisions.md`: binding owner decisions and the proven method.
3. `docs/SPEC.md`: full spec (engine, renderer, sources, quality bar, bake-off results).
4. `docs/hermes-surfaces.md`: verified Hermes integration points (upstream a4072ce7e6).
5. `reference/bakeoff-r2/`: the round-2 bake-off letterer, episode layout and prompts (proof of method, not production code).
6. `canon/HERMES_SCHEMA.md`: how each Hermes table/field becomes an `Event` (M0 deliverable).
7. `docs/reports/`: stage reports written by the build agent.

## Code map

```
canon/                  pure core, no Hermes imports (events.py, source.py, HERMES_SCHEMA.md)
adapters/hermes/        the only Hermes-aware code: history.py (ingest + CLI), ro.py and
                        stores.py (read-only access), paths.py, leakscan.py
fixtures/               synthetic Hermes home generator (4 profiles, 4 weeks)
tests/                  67 tests, pytest, no network and no real history
scripts/readonly_proof.sh   strace-based proof that no file is created, renamed,
                            truncated or deleted under ~/.hermes
```

Run it:

```bash
uv venv .venv --python 3.12 && uv pip install --python .venv/bin/python pillow pytest jsonschema pyyaml
.venv/bin/python -m adapters.hermes.history --days 7 --summary
.venv/bin/python -m pytest
bash scripts/readonly_proof.sh
```

Evidence for real-data runs lives outside the repo, in
`/home/kensei/handoffs/agent-story-replay/build-evidence/<stage>/`.

Bake-off images: `/home/kensei/handoffs/agent-story-replay/bakeoff-gpt-image/` (r1 in `out/`, r2 in `r2/out/`).
Kanban: t_ec1754fc.
