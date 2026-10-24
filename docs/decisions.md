# Decisions (binding: these win every conflict with other docs)

Owner: Sahil. Decided 23/10/26 in the KENSEI intake grill and the bake-off review.
Kanban card: t_ec1754fc.

## Owner decisions (Accepted, do not re-open)

| # | Decision |
|---|----------|
| D1 | V1 is a **comic/manga**. Video, podcast, prose and the book come later and are out of scope. |
| D2 | Built for other people too, not only Sahil. The core is **harness-agnostic**; Hermes is the first adapter. The Canon core must not import Hermes. |
| D3 | Image/vision generation uses **whatever the user has configured in Hermes**, local or their own paid account. The plugin calls Hermes' configured tools and never holds its own keys. |
| D4 | Styles: **a few built-in styles plus user-supplied custom styles**. Built-ins must meet the quality bar; custom styles are best-effort. |
| D5 | Likeness: the default is a ready-made character. Users can opt in to a character from their own photo: consent step, photo stays local unless the user's provider needs it (warn when it does), only the user's own likeness. |
| D6 | Sharing: image files plus ready-to-post versions (X, LinkedIn, Discord, vertical strip) with a caption draft. **Never posts automatically.** No hosted gallery. |
| D7 | Episodes: a **weekly 4-6 panel strip** (automatic only after the user enables it) plus an **on-demand 8-12 panel chapter**. |
| D8 | Name: **Hermes Scrollback Reel**. Plugin id `scrollback-reel`, command `/reel`. Do not use "chronicle" (taken in the catalog) or "journey" (Hermes Labyrinth). |
| D9 | Ready-made cast has two paths: (a) self-created/generated through the user's image source; (b) Hermes Multiverse characters. Multiverse rights are `unknown-not-cleared`, so **private renders only** until cleared. |
| D10 | Bake-off passed for GPT Image (openai-codex gpt-image-2) in anime-colour and ink-manga styles. The round-2 method is mandatory: one arc per episode, staged prompts, vision-placed balloons, vision letterer check. |

## Proven method (from the bake-off, binding)

1. **One story arc per episode**, never a highlight reel: setup → hidden problem → diagnosis → climax → aftermath → win + cliffhanger. Every panel causes the next. Recurring problems become villains with reference sheets.
2. **Character kit before panels**: one reference sheet per character per style.
3. **Every panel prompt carries staging**: who is LEFT/RIGHT/CENTRE, shot type, top 25% kept clear, "no text in image".
4. **Lettering is never baked into the art.** Use OFL fonts (Comic Neue, Bangers). CC Wild Words and Anime Ace are banned (not free commercially).
5. **Balloons placed from vision.** Head boxes, keep-out boxes, free regions. Search font size × wrap width. Reading order: right of the last balloon on the same row, or below it. Tails aimed at the face. Rectangular balloon for off-screen or hologram speakers. Reference: `reference/bakeoff-r2/letterer.py`.
6. **Vision letterer check** on every panel and page. Fail → re-place; re-query tight boxes if a tail misses.
7. **Flag unscripted cast**: the image model sometimes adds characters.
8. **Retry with backoff** on provider 5xx.
9. **Accept whatever size the provider returns**: openai-codex ignores aspect when references are passed.

## KENSEI defaults (Proposed: the builder may proceed on these but must flag them in reports)

- P1: Storage via `plugin_data_dir("scrollback-reel")` / `plugin_db()`.
- P2: Built-in styles for V1: `anime-colour`, `ink-manga`, plus one more chosen by the builder from Sahil's style skills (Saga Noir, Ink & Ember, Baoyu Comic). Name it in the M2 report.
- P3: The default original cast (non-Multiverse, licence-clean) is generated via the user's image source at `/reel setup`.
- P4: Privacy default `private`. Public export requires every named entity to be approved, plus a clean redaction scan.


## Owner decisions 23/10/26 (folded in at M2 start)

| # | Decision | Effect |
|---|----------|--------|
| D7 (amended) | The schedule is **optional, daily or weekly**, chosen by the user. Still off until the user enables it. | M2: the automation blueprint offers both cadences. A daily strip uses the same arc rules, with a 24 h window. A quiet day produces no episode rather than filler. |
| D9 (amended) | Hermes Multiverse characters **may be shown publicly** (owner approval). | Public mode may use Multiverse sheets. **Caveat:** most Multiverse characters depict real community members (e.g. teknium, nousgirl, 123mikeyd), and the repo NOTICE says inclusion is not a reuse licence. Sahil's own character is cleared by his decision. Before any **public** render, each other real person's consent should be recorded per character (an allowlist file). Private renders are unaffected. |
| D12 | **Install into live Hermes is approved.** | KENSEI installs after the M2 audit passes: a plugin install into the default profile, verified with `hermes plugins doctor`. The weekly/daily blueprint stays disabled until Sahil enables it. |
| D13 | **Public publication** = submission to the Hermes plugin catalog **and/or** a hosted community site. | Catalog submission is M3. The site is a separate product (below). |
| D14 (follow-up product, not V1) | **Scrollback Reel Hub**: a hosted website where users publish their stories and series, with a news feed, following, likes and comments. | Needs its own grill and spec after M2. It is a step up from a plugin: accounts/login, storage, hosting cost, moderation and reporting, takedowns. Also UK Online Safety Act duties, because users post content and comment on each other's. The plugin's "publish" button would push a strip (already redaction-checked and owner-approved) to the Hub. Nothing is ever auto-posted. |
