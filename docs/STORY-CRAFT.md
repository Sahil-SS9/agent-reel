# Story craft for Scrollback Reel (research notes, 25/10/26)

Why this exists: Sahil reviewed the first M2 strips: "the images look good but it tells an extremely boring story… so stale". The approved bake-off r2 worked for three reasons:
- **Personified problem.** "The Orphans" stood for orphaned processes.
- **Visual metaphor.** Fixes became fights.
- **A real arc.** It went launch → hidden drain → diagnosis → reaper fight → win + cliffhanger.

The M2 pipeline had drifted back to a literal record: two people in an office, eye-level medium shots, admin sessions.

Owner decisions, 25/10/26:
- **V1.** The pictures may dramatise (monsters, fights, chases, big locations). Every caption and line stays factually true and grounded, as before.
- **V2.** Stories are chosen automatically, scored for drama: a problem, a fight, a result.
- **V3.** Every episode has a villain or problem, rising stakes, and a payoff or cliffhanger.

## What the craft says (sources)

### Structure
- **Kishōtenketsu (yonkoma, 4 panels).** Ki sets the scene; shō develops it; ten is the climax, "an unforeseen development"; ketsu shows its effects. (Wikipedia, *Yonkoma*.) This is our 4-panel strip.
- **Western arc (6 panels).** Setup → inciting problem → escalation → climax → aftermath → payoff or hook. Each panel must cause the next. This matches the approved r2 shape.
- **Webtoon.** One beat per panel. The episode ends on a final image timed to the bottom of the scroll, which is the cliffhanger engine. Gaps of empty space create a beat of silence. (Capgun Comics, *Webtoon vertical scroll panel grammar*.)

### Pacing and layout
- **Panel size is time and weight.** A big panel slows time and marks the important moment; a small panel speeds it up. The climax gets the biggest panel. (Gootaku, *Manga panel composition rules*.)
- **Action unit: buildup → impact → result.** Impact is the biggest panel, with a dynamic angle (Dutch tilt, low angle), motion lines and debris. Result shows where everyone ended up, then a beat of stillness. (Gootaku, *Action manga choreography*.)
- **"Repetition kills momentum."** Vary the camera angle every panel. (Gootaku.)

### Camera vocabulary (Multic, *Dynamic camera angles*)
- **Extreme close-up:** emotional peaks and key objects. Use rarely.
- **Close-up:** reactions.
- **Medium:** "the safe, boring choice. Use intentionally, not by default." This was our default for every panel, which is the staleness.
- **Full / long / extreme long:** establishing shots, scale, isolation.
- **Angle carries meaning:** low = power (hero, villain entrance); high = vulnerability (overwhelmed, defeated); Dutch = chaos and surprise; eye level = calm.

### Transitions (McCloud, *Understanding Comics*)
The six transitions are moment-to-moment, action-to-action, subject-to-subject, scene-to-scene, aspect-to-aspect and non-sequitur.
- Western action leans on action-to-action.
- Manga uses aspect-to-aspect for mood.
- A strip of six subject-to-subject "people talking" panels reads static.

## Rules we adopt (implemented in M2 "story pass")

1. **Pick stories with conflict (V2).** Score each candidate thread for:
   - a problem: error, fail, broke, blocked, bug, leak, crash, timeout, limit, regression, refused
   - a struggle: several attempts or turns
   - a result: fixed, passed, shipped, figures, or honestly open

   Bookkeeping stays excluded. Drama comes first in the ranking; the old score breaks ties.
2. **Name the villain (V3).** The episode's problem becomes a creature or antagonist, for example orphaned processes → The Orphans, a rate limit → a toll-gate wraith, a flaky test → a gremlin.
   - The villain is drawn, never named in captions unless the facts name it.
   - Its sheet is generated once per villain and reused, so it stays on-model across panels and episodes.
3. **Write a visual treatment per panel (V1).** A director pass on the writer model gets the episode's grounded facts and returns, per panel:
   - the location (a dramatised world mapped from the real one: the rig → a neon command deck; a bug hunt → server catacombs)
   - the action
   - the villain's presence
   - the shot size and camera angle

   The treatment adds **no text**. Captions and lines are unchanged and still pass the grounding gate.
4. **Shape the arc by role (V3).**
   - **setup:** wide or extreme long establishing shot, eye level
   - **hidden problem / villain reveal:** high angle or Dutch, the villain partly hidden
   - **diagnosis:** close-up or extreme close-up on the clue
   - **climax:** the largest panel, low angle, full action, impact effects
   - **aftermath:** medium, stillness
   - **win or hook:** low hero shot for a win; the villain's silhouette or "To be continued…" for a hook
5. **Never repeat a shot.** No two consecutive panels share both shot size and angle.
6. **Lay out the climax big.** On the page export, the climax panel spans the full width.

## Truth boundary (unchanged)
Pictures may exaggerate how it *felt*; words may only say what *happened*.
- A caption or line never names the villain as a fact.
- A caption or line never claims a fight, a weapon or a place that is not in the evidence.

The approved r2 strip followed exactly this split.

## Two layers: facts and story (story layer)

A caption that must be entailed word for word by the log can only restate the log, which is why chapters read like a playback. Narration now runs on its own grounding layer (`ClaimGate.check(..., layer="story")`):

- **What it may do:** interpret. What was at stake, what a moment felt like, why it mattered, a character's motive or mood, humour, a rhetorical question.
- **What it may not do:** add anything that happened. Names and numbers are checked deterministically against the cited evidence, a named character must be in that evidence, an outcome or cause must bind to its actor, and a model judge refuses any new action, result, cause, time or place (`ClaimGate.STORY_PROMPT`).
- **No model, no story voice.** With no model to tell a feeling from a new event, the story layer is exactly as strict as a caption.
- **Facts keep the strict layer.** The "behind the panels" notes and the trace still cite source events, and `--strict-captions` keeps narrator captions literal.

Dialogue is unchanged: it already allowed tone and was claim-checked. The synopsis and the story-mode scene captions use the story layer by default.

## Real lines, a cold open, and no readouts

Three changes that give a chapter a voice instead of a transcript:

- **Real lines.** The owner's blunt, dry messages are better dialogue than anything a model invents. For each panel, `canon/reallines.py` offers the speakers' punchiest short sentences, taken verbatim from the *gated* (already redacted) text of that panel's own messages, as candidate lines (`real_lines`). The writer may use one unchanged; whatever it writes still goes through the grounding gate, so a real line is cited to the event that said it. Code, links, paths, ids, jargon, redaction masks and assistant filler are never offered. Turn it off with `hermes reel plan --no-real-lines`.
- **A cold open.** The synopsis now has a `hook`: the single most gripping moment, line or question of the story. The setup panel opens on it before it introduces anyone.
- **No readouts.** A caption that is only a statistic or a status ("LCM-X wins by 10 to 16 points.", "Zero failures.") reports a result without telling the reader why it matters. The editor now flags these deterministically (`readout_problem`) and caps a generous score at 3 so the one rewrite pass runs, and the writer is told a result caption says what the number meant to the hero.

The caption policy that stops a *caption* from quoting the owner for more than 8 words is unchanged: it governs narrator boxes. Dialogue attributed to the owner may now be his own words.
