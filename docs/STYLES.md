# Styles: 55 looks, and how to add your own

A style is a folder under `styles/` (or `<data-dir>/styles/` for your own). Two forms:

## `style.json` (structured)

```json
{
  "name": "anime",
  "title": "Modern anime",
  "prompt_block": "Single comic panel, full-colour modern anime / manga illustration ...",
  "negative_block": "No text, letters, words, numbers, speech bubbles, captions or logos ...",
  "tested_on": ["openai-codex gpt-image-2 (bake-off r2)"],
  "status": "approved",
  "refs": ["../../kits/kensei/anime.jpg"],
  "staging_rules": "Keep the top 25 percent of the frame uncluttered for speech balloons.",
  "licence": "Prompt text: MIT (this repo). Reference sheets: generated for this project."
}
```

## `style.md` (raw prompt template)

```markdown
---
name: my-style
title: My Style
summary: one line describing the look
status: experimental
tested_on: []
source: written by me
licence: MIT
negative: No text, letters, words, speech bubbles, captions, logos or watermarks.
staging: Keep the top quarter of the frame quiet for balloons.
---

Create a single comic panel in the style of ...

**[INSERT CHARACTERS, ACTION AND SCENE HERE]**
```

The insert line is mandatory: the prompt builder replaces it with the staged characters,
action and scene for that panel.

## Tested vs experimental

- `status: approved` **and** a non-empty `tested_on` means tested: a real image was made
  through the source you are using.
- Anything else is `experimental`. The render refuses an experimental style unless you
  pass `--allow-untested-style` (or clear `--strict-styles`), so nobody is told a look is
  proven when it is not.

Of the 55 shipped styles, **anime** and **ink-pen-sketch** are tested. The other 53 are
experimental on purpose. Every style works with every character kit: identity comes from
the approved reference sheets, not from the style's wording.

## The catalogue

Styles are grouped loosely by family, so you can pick a register quickly:

- **Comic and manga:** anime, ink-pen-sketch, mono-anime, ligne-claire, noir-webtoon, gekiga-grain
- **Ink and print:** sumi-e-brush, ukiyo-e-folktale, woodblock-mono, wood-engraving-dore,
  chiaroscuro-etching, colour-engraving, blueprint-technical
- **Design and poster:** art-nouveau-poster, bauhaus-poster, constructivist-power,
  art-deco-metropolis, pop-art-bubble, psychedelic-folk, vintage-print
- **Digital futures:** cyberpunk-hud, cyber-noir-rain, cassette-futurism, vapourwave-grid,
  technical-diorama, chromatic-institute, cosmic-postcard, ninth-observatory
- **Craft and folk:** madhubani-line, persian-miniature, tapestry-millefleurs,
  stained-glass-legend, mosaic-byzantine, chinese-ink-panorama
- **Painting:** watercolour-wash, gouache-storybook, fauvist-colour, expressionist-charcoal,
  cubist-facets, futurist-motive
- **Building and landscape:** brutalist-concrete, deconstructivist-line, solarpunk-bloom,
  biopunk-anatomy, dieselpunk-aviation, atompunk-optimism
- **Working sketches:** pencil-rough, crayon-zine

Run `hermes reel styles` for the live list with tested state.

## Tone is separate

Tone (witty, comical, serious, quirky, epic, wholesome, noir, or a blend such as
`comical:70,serious:30`) changes the writing and the visual mood. It never changes the
facts. `hermes reel tones` lists the options.

## Fonts

Balloons and captions use Comic Neue Bold; titles use Bangers. Both are SIL OFL 1.1 —
`assets/fonts/FONTS.md` and `assets/fonts/OFL.txt`. Comic-lettering fonts that are not free
for commercial use are deliberately not bundled.
