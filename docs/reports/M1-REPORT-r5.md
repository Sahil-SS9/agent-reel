# M1 round 5 report: PARTIAL

Round 5 (last writer round). The production path landed and the attribution is fixed; the
captions are still too sparse for the strip to read as a comic.

Commit under test: `5cb391b`. Installed copy pinned to the same sha (see
`reinstalls.log`). 298 tests pass. Evidence: `build-evidence/M1-r5/`.

## Step 0: plugin skeleton (R4-F4)

`plugin.yaml` + `__init__.py` at the repo root register ONE surface: the CLI command
`hermes reel plan --dry-run [--days N] [--episodes N]`. No hooks, no slash commands, no
tools, no blueprint, no schedule.

- writer, title and entailment run on `ctx.llm` (`adapters/hermes/plugin_llm.py`);
  redaction stays on the local model (127.0.0.1:8091), so only post-gate text leaves the
  process.
- the API-server writer route is deleted.
- `--data-dir` defaults to `plugin_data_dir("scrollback-reel")`; dev rounds always pass an
  explicit directory outside `~/.hermes`.
- `hermes plugins validate .` → **Validation passed**; `hermes plugins doctor . --ci` →
  **OK** (0 tools, 0 hooks).

**Tokens per call**: 18–31 calls per round, **max 2,219 prompt tokens in a single call**
in the final round (limit 5k), 4,310 prompt / 396 completion tokens in total. Compare r4:
2.04M prompt tokens for 36 calls, ~57k per call.

Install note, stated plainly: the authorised `hermes plugins install … --ref … --force`
was refused twice, non-interactively, because a `pyproject.toml` beside `plugin.yaml` makes
the installer ask a Python-dependency-consent question. `canon/` and the adapter are
stdlib-only, so the packaging file was replaced with `pytest.ini` + `ruff.toml`; the same
authorised command then succeeded. Each reinstall is logged in `reinstalls.log`.

## Items

| ID | Required | Result |
|----|----------|--------|
| R4-F1 | role=user → the owner; role=assistant → the profile's character; "asked" only of the owner; no "Assistant" | **DONE** — `tests/test_speakers.py` (6). All three scripts name only Sahil and Kensei; no line says "asked" of anyone else; no "Assistant" character |
| R4-F2 | captions paraphrase brief facts ≤20 words, entailment-checked; never quote the owner >8 words; climax/win on outcome facts | **PARTIAL** — policy and entailment are in place and enforced (`tests/test_caption_policy.py`, 7), the outcome is chosen for its result content (`tests/test_brief.py`), but **caption coverage is 2/6, 3/6, 3/6 panels**: the model's paraphrase is refused and the composed fallback is refused by the owner-quote rule, so most panels carry dialogue only |
| R4-F3 | each line reacts to its panel's fact; ≤1 generic interjection per episode | **DONE** — `tests/test_reactions.py` (5). 4–7 lines per episode, every line tied to its panel's fact; the template writer derives its line from the panel fact and stays silent otherwise |
| R4-F5 | report what is shown; episodes never share anchor events | **DONE** — `title_words`, `header_title`, `header_title_words` per episode; a candidate sharing anchors is skipped and recorded |
| R4-F6 | public mode masks money and health; private unchanged | **DONE** — `tests/test_privacy_and_reporting.py` (6): `$21.45 of $30` and an NHS number are masked in public, kept in private; the rules are pure regex |

## Measured on the three real scripts

| | ep 1 | ep 2 | ep 3 |
|---|---|---|---|
| title (words) | Benchmark LCM-X against Severian Memory (5) | please read and review this idea/concept (6) | Reviewing Hermes Dev Radio against source (6) |
| header line (words) | 10 | 17 | 18 |
| panels | 6 | 6 | 6 |
| captions shown | 2 | 3 | 3 |
| dialogue lines | 7 | 4 | 5 |
| speakers | Sahil, Kensei | Sahil, Kensei | Sahil, Kensei |
| raw event strings / masks | 0 / 0 | 0 / 0 | 0 / 0 |
| misattributed speakers | 0 | 0 | 0 |
| silent episodes | none | none | none |

Gates, all green at this commit: 298 tests; 30-thread eval GATE PASSED (120/120
adversarial refusals); grounding eval 32/32 accepted, 32/32 refused; redaction held-out
deep GATE PASSED (secrets 100%, names ≥95%).

## Why it is still PARTIAL

1. **Caption coverage.** Two to three panels per episode have a caption; the rest are
   dialogue-only. The model's paraphrase is refused often enough that the composed
   fallback decides the strip, and the composed fallback is now refused whenever it echoes
   the owner for four consecutive words - which is most of them, because the panel's
   evidence *is* the owner's message.
2. **Episode 2's title** came back ungrounded, so the derived title is a fragment
   ("please read and review this idea/concept").
3. **Header lines are 10-18 words**; reported honestly, but the H1 is a sentence, not a
   title.

## What I would do next

1. Give the caption layer a *paraphrase* it can trust without a model: compose from the
   brief's structured facts (actor + result) rather than from the panel's raw evidence, so
   the owner's words are never the source.
2. Anchor captions on the brief's goal/outcome sentence for the outer panels (setup, win),
   which are the ones usually left bare.
3. Only then raise the caption count - a panel with no caption should be rare, not half
   the strip.

## Reproduce

```bash
cd /home/kensei/repos/hermes-scrollback-reel
hermes reel plan --dry-run --days 7 --episodes 3 --data-dir <dir outside ~/.hermes> --json
.venv/bin/python eval/threads/run.py && .venv/bin/python eval/grounding/run.py
.venv/bin/python -m pytest -p no:cacheprovider
```
