# Image sources: how a panel becomes a picture

Every image in a reel comes from one of five sources. All of them satisfy the same small
contract, so the rest of the pipeline does not care which one you use:

```
generate(prompt, references: list[Path], aspect: "landscape" | "portrait" | "square") -> Path
```

`references` are character reference sheets (already approved); `aspect` is the frame shape
the letterer expects. Return an image; the caller handles caching, retries and the
per-panel quality check.

## The five sources

| Key | Class | Where the model runs | Needs |
|---|---|---|---|
| `host` | the harness's own image tool | your Hermes provider | nothing beyond a working image tool in your harness |
| `comfyui` | local ComfyUI server | your GPU | a running ComfyUI at `127.0.0.1:8188` and an API-format workflow |
| `openai` | GPT Image | OpenAI API | `OPENAI_API_KEY` |
| `gemini` | Nano Banana | Google Gemini API | `GEMINI_API_KEY` |
| `fal` | FLUX / Nano Banana | fal.ai | `FAL_KEY` |

`hermes reel sources` prints this table live, including which are **tested** with real
images and which are only **mapped** (request shape implemented, never run for real).
`hermes reel sources --check <key>` makes exactly one real request and reports the outcome;
use it before a long render.

Set a default once:

```bash
hermes reel sources --set comfyui
hermes reel render --plan-dir <plan> --episode 1        # uses the saved default
```

Per-render override:

```bash
hermes reel render --plan-dir <plan> --episode 1 --source openai --model gpt-image-1
hermes reel render --plan-dir <plan> --episode 1 --source comfyui --workflow my-workflow
```

## Porting to another harness

Three things to do, none of them Hermes-specific:

1. **Implement the contract.** Copy the shape of any entry in `canon/providers.py`
   (`openai_generator`, `gemini_generator`, `fal_generator`, `comfyui_generator`). Keep the
   same signature and return a `Path`.
2. **Register it.** Add the key to `SOURCES` with a label, cost note and how many reference
   sheets it accepts. That is what `hermes reel sources` lists and what the render accepts.
3. **Prove it once.** Run `--check` (or one real panel) before trusting a whole episode.
   A source that has never produced a real image is labelled `mapped`, never `tested`.

For a harness with no image tool of its own, the usual route is a local model: point the
`comfyui` source at any server that can run a ComfyUI API-format workflow, or write a
generator that shells out to your own script. Both are a few dozen lines.

## Cost and limits

- Per-panel cost is shown in `hermes reel sources` (rough guide: 3-20p per image on the paid
  APIs; free on a local GPU).
- `--budget N` caps new images for one episode. Cached images (same prompt, same source) are
  free and count as cache hits, so re-lettering or re-laying out a page costs nothing.
- A chapter with fillers needs roughly 20 images; give `--budget` room for retries.
- `--retries N` regenerates a panel that fails the quality check. The check itself is a
  vision-model call; if it cannot run, the panel is flagged rather than silently accepted.

## What the pipeline adds around your model

- A **villain reference sheet**, drawn once per (villain, style) and reused.
- **Character sheets** from `kits/`: identity is fixed by approved reference art, not by
  prompt wording.
- **Staging** (left/right/centre, headroom kept for balloons), **action grammar**
  (motion, impact, reaction, camera) and a **full-bleed climax**.
- **No text in the art**: the negative block forbids letters, captions and logos, because
  lettering is drawn afterwards with licensed fonts.
