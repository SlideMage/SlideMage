# UI extensions and big fixes plan

Status: draft, 2026-10-10. Follows `docs/UI_REDESIGN_PLAN.md`, which is finished on branch `ui-redesign`
(SlideMage 6.0.0). Each item needs the user's go before it starts; pause after each committed item.

Cost figures are rough, from the usage calibration of ~5% of a 5-hour window per ~100k agent tokens.

## 1. Big change: the DE switch follows translations

With **DE** selected in the top bar, every slide that has a German partner shows that partner in the slide
list, the preview and the editor. Slides without one stay English and keep the "No DE version" flag.

Cost: ~200-400k agent tokens, ~10-20% of a window. Do it after section 2.

**Today.** A translation is a separate slide with its own id (`1f8-EN-...` and `tks-DE-...`), linked by
`%% Translation of:` / `%% DE translation:` header comments. `\slide{X}` always typesets the file X, so
nothing swaps in the partner at compile time. The DE button only sets the compile language and the
"no DE" flags; the `EN + DE` chip is informational.

**Wanted.**

- The list, preview, render and editor resolve each row to its German partner when DE is active.
- A translation is no longer a second row to look for at the end of the deck.
- Edits in DE mode write to the German file, never to the English one.

**Design questions to settle first.**

- Does the deck keep both calls and DE mode hides the EN one, or does it keep one call and resolve the partner?
- What does a DE compile typeset for a slide with no translation: the English slide, or a placeholder?
- A call that pins a version of the English slide: does the German partner follow the pin?
- Hidden-in-view and conditional slides: which file's visibility rules apply?
- Keep the "Translation outdated" chip and the Language panel as they are?

**Touches.** `deck_outline.py`, preview target and render, source editor, Details and Language panels, the
compile path for a single slide, and the GUI tests that assume the English row.

## 2. Small translation fixes

~3-4% together; both keep working after item 1.

| Fix | What it does | Cost |
| --- | --- | --- |
| Placement | `add_slide` with `translation_of` and no `after` puts the DE call directly after the source slide, so EN and DE sit as neighbours. | ~15-25k tokens, ~1% |
| Chip jump | The `EN + DE` chip above the preview selects the German slide; the DE slide's chip jumps back. One slide at a time; the top-bar buttons stay as they are. | ~30-60k tokens, ~2-3% |

Already done: `add_slide` takes `translation_of` and writes both header links (commit `2f5ffe2`).

## 3. Release work for 6.0.0

In this order:

- [ ] Regenerate the screenshots that show sheets or form controls (Settings, Deck settings, Add slide,
  Images page); add one line about the restyle to the v6.0.0 entry in `version.py` (~50-80k tokens).
- [ ] CI libraries for QtWebEngine in `.github/workflows/ci.yml` and `release.yml`; confirm with one CI run.
- [ ] Merge `ui-redesign` into `main` and tag `v6.0.0` (outward-facing; the user decides).
- [ ] User-side checks: a local tool-capable model in the Chat on a real slide edit; the Claude Code tab
  once (focused slide visible, an edit of a slide header blocked by the hook).

## 4. Other open points

- [ ] A preview compile writes a `_slidemage_preview-...` entry into a slide's "Included in decks" header
  (seen on `1y9`, `1us`, `1f8`). Find out why and stop it modifying tracked slides.
- [ ] Let one tool edit the example project at a time: Claude Code and Codex both changed it in one
  session and undid each other's links.
- [ ] Decide whether `add_slide` with `translation_of` should also machine-translate the body with the
  configured model, as the Translate dialog does, instead of leaving a copy for Claude to translate.
