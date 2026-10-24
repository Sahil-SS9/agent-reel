# M2 plan: comic V1 (KENSEI direct build, Sahil go 24/10/26)

Base: main @ 98f9688 (M1 accepted, Quan t_13eb5c20). Branch: m2-kensei. Each phase ends with tests green, a commit, and a logged reinstall. Independent review (Quan) is required at the end of M2; a phase review comes earlier only where a phase changes a safety gate.

Host surfaces (verified in hermes_cli/plugins.py):
- `ctx.dispatch_tool("image_generate", {...})` renders images on the user's own configured provider. In the bake-off this was GPT Image via openai-codex.
- `ctx.dispatch_tool("vision_analyze", {...})` runs the per-panel auto-check and finds head boxes for the letterer.
- `ctx.llm` stays the writer and judge. Redaction stays local.

## Phases

| # | What | Done when |
|---|------|-----------|
| P0 | M1 polish (card t_3c0902f0): real titles instead of "A session"; report addendum for r10c; actor-cast derivation case-insensitive | Week run: model titles on 3/3; tests green |
| P1 | Style cards + character kits as data: `styles/<name>/style.yaml` (prompt block, negative block, 3-6 refs, tested-on, licence) with 2 built-ins from the approved bake-off (anime, ink-pen-sketch) plus 1 more; a custom-style loader from the plugin data dir; a kit approval file (no unapproved kit renders) | Loader + validation tests; unapproved kit refused |
| P2 | Panel prompt builder: IR panel → prompt with staging (LEFT/RIGHT/CENTRE), 25% headroom, no text, character refs, scripted cast only | Deterministic tests; prompts match the approved bake-off r2 shape |
| P3 | Renderer: `image_generate` via the host with retry/backoff on 5xx; accepts whatever size the provider returns; cache by prompt hash; per-episode image budget | Fake-provider tests; one real 6-panel render |
| P4 | Auto-check per panel (vision): on-model (face/hair/outfit/colours), unscripted-cast flag, no text in the art; regenerate up to N, else flag the episode | Tests with a fake judge; real run report |
| P5 | Letterer: port bake-off r2 letterer v2 (head boxes + tight re-query, keep-outs, size × wrap search, reading order, tails to faces, comms balloon) as SVG over the art; OFL fonts with the licence recorded; vision letterer check | Real strip passes the letterer check; fonts licence-clean |
| P6 | Exports: PNG page, vertical strip, X 16:9 / 1:1, LinkedIn 1.91:1 / 4:5, Discord; caption draft; sidecar JSON with source ids per line | Files produced and size-checked |
| P7 | Commands + schedule: `hermes reel render --episode N`, `hermes reel kit ...`; automation blueprint offering daily or weekly, **disabled by default** (D7 amended) | `hermes plugins doctor --ci` OK; blueprint off |
| P8 | Acceptance: 4-week synthetic history + 1 real week → strips; human review of 24 panels (Sahil); nothing unapproved named; Sahil posts at least 1 | Sahil's sign-off + Quan review |

## Guards carried from M1 (unchanged)
- Nothing renders unless it has passed the redaction gate.
- Every line keeps its source ids.
- No auto-posting.

New in M2:
- Public mode refuses any real person without a consent record (D9 caveat: a per-character allowlist file). Sahil and Kensei are cleared.

## Cost
- GPT Image runs about $0.21 per image.
- P3–P8 real renders: about 60–90 images including regenerations, roughly £10–15 in total.
- A per-episode budget cap is enforced in code.
- Any spend beyond the acceptance run is gated on Sahil.
