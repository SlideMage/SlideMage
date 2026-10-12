# UI extensions and big fixes plan

Status: draft, 2026-10-10. Follows the UI redesign, finished on branch `ui-redesign`
(SlideMage 6.0.0). Each item needs the user's go before it starts; pause after each committed item.

Cost figures are rough, from the usage calibration of ~5% of a 5-hour window per ~100k agent tokens.

## 1. Big change: the DE switch follows translations

Status: implemented in SlideMage 7.0.0, 2026-10-11.

With **DE** selected in the top bar, every slide that has a German partner shows that partner in the slide
list, the preview and the editor. Slides without one stay English and keep the "No DE version" flag.

Cost: ~200-400k agent tokens, ~10-20% of a window. Do it after section 2.

**Before this change.** A translation is a separate slide with its own id (`1f8-EN-...` and `tks-DE-...`), linked by
`%% Translation of:` / `%% DE translation:` header comments. `\slide{X}` always typesets the file X, so
nothing swaps in the partner at compile time. The DE button only sets the compile language and the
"no DE" flags; the `EN + DE` chip is informational.

**Wanted.**

- The list, preview, render and editor resolve each row to its German partner when DE is active.
- A translation is no longer a second row to look for at the end of the deck.
- Edits in DE mode write to the German file, never to the English one.

**Implemented decisions.**

- Deck files stay unchanged. One logical slot resolves to its partner; separately listed linked
  translations are folded into the original slot, in both EN and DE.
- A missing translation typesets the called slide, with the existing no-version flag.
- Translation versions are independent. EN keeps an English pin; DE uses the current German translation.
- The original deck call controls placement, visibility, conditions and reveal steps.
- Keep the "Translation outdated" chip and Language panel; panels follow the displayed file.

**Touches.** `deck_outline.py`, preview target and render, source editor, Details and Language panels, the
compile path for a single slide, and the GUI tests that assume the English row.

## 2. Small translation fixes

~3-4% together; both keep working after item 1.

| Fix | What it does | Cost |
| --- | --- | --- |
| Placement | `add_slide` with `translation_of` and no `after` puts the DE call directly after the source slide, so EN and DE sit as neighbours. | ~15-25k tokens, ~1% |
| Chip jump | The `EN + DE` chip above the preview selects the German slide; the DE slide's chip jumps back. One slide at a time; the top-bar buttons stay as they are. | ~30-60k tokens, ~2-3% |

Already done: `add_slide` takes `translation_of` and writes both header links (commit `2f5ffe2`).

## BIG CHANGE 2: make slide previews fast

Status: done; required review fixes implemented and verified in SlideMage 6.1.1, 2026-10-11. Unchanged saved
previews went from a median of 0.234 s to 0.138 s; build reuse makes a typical one-slide edit about 3× faster than
a fresh job. Benchmark tooling: `tools/preview_benchmark/`.

## 3. Release work for 6.0.0

In this order:

- [ ] Regenerate the screenshots that show sheets or form controls (Settings, Deck settings, Add slide,
  Images page); add one line about the restyle to the v6.0.0 entry in `version.py` (~50-80k tokens).
- [ ] CI libraries for QtWebEngine in `.github/workflows/ci.yml` and `release.yml`; confirm with one CI run.
- [ ] Merge `ui-redesign` into `main` and tag `v6.0.0` (outward-facing; the user decides).
- [ ] User-side checks: a local tool-capable model in the Chat on a real slide edit; the Claude Code tab
  once (focused slide visible, an edit of a slide header blocked by the hook).

## 4. Other open points

- [x] Generated preview wrappers entered deck-membership header scans. `deck_headers.py` now excludes
  underscore-prefixed generated wrappers; an isolated regeneration test confirms only real deck names remain.
  Existing working example slides were preserved during implementation.
- [ ] Let one tool edit the example project at a time: Claude Code and Codex both changed it in one
  session and undid each other's links.
- [ ] Decide whether `add_slide` with `translation_of` should also machine-translate the body with the
  configured model, as the Translate dialog does, instead of leaving a copy for Claude to translate.

## 5. Version graph for a slide and its translations

Status: idea, 2026-10-12. Needs the user's go; pause after each committed step.

A graph like VS Code's git graph, per slide: the original's versions as a main line, each translation as a
branch that starts at the version it was translated from, and where a translation fell behind.

```
 EN 1f8  Installing SlideMage                          used by
 ●  current  v1.1.1   Oct 11 14:20                     manual (follows current)
 │
 ●  v1.1.0   Oct 11 13:10   ─────────┐
 │                                    │  DE tks  Installation (Übersetzung)
 │                                    ●  current  v1.0.0   Oct 11 13:40
 │                                    ┊  ⚠ outdated since EN v1.1.1 (Oct 11 14:20)
 ●  v1.0.0   Oct 2                                     course-2025 pins v1.0.0
```

- Main line: the original's frozen versions and its current one, with the time each was frozen.
- Branch per translation, from the original's version it was made from, with its own versions.
- Dashed while a translation is behind ("outdated since EN v…"), solid while in sync.
- Labels on the right like git refs: which deck pins which version, which follows "current".
- Click a node: open that version (frozen ones read-only); two selected nodes: show the diff, e.g. what
  changed in EN since DE was translated.

**What exists.** Versions and their order (frozen `-vX-Y-Z.tex` files, `\setSlideVersion`); when each
change happened (`slides/.backups/`, one full copy per save, version line included, named by its time);
which slide translates which (`%% Translation of:`, `slide_language.TranslationLinks`); "outdated"
(`translation_link().outdated`); which deck pins or follows which version (`slide_usage`).

**What is missing.**

- The branch point: a translation records *which slide* it translates, not *which version*. Record it from
  now on (`%% Translation of: <id-slug> v1.1.0`, written when the translation is made); older links fall
  back to a guess from the backups' times, shown as approximate.
- An explicit "Mark in sync with EN v…" action: today saving a translation (even a typo fix) clears
  "outdated".
- Edits made outside SlideMage leave no backup; in a project under git, `git log` of the slide file can
  fill the gap (optional).

| Step | What it does | Cost |
| --- | --- | --- |
| G1 History model | Per slide and its translations: version nodes with times, branch points, in-sync/outdated spans and deck labels, built from frozen files, backups and links. No UI; tested on the demo project. | ~40-60k, 2-3% |
| G2 Record the source version | The translation header carries the original's version; written when translating; a "Mark in sync" command updates it and is what clears "outdated". Old headers keep working. | ~30-50k, 2-3% |
| G3 Graph widget | A painted Qt view (like the slide list's delegate): lanes, nodes, dashed/solid lines, labels; light and dark. | ~60-90k, 3-5% |
| G4 In the Versions panel | The graph above the panel's existing actions; click opens a version, two selected nodes open a diff. | ~40-60k, 2-3% |
| G5 git history (optional) | In projects under git, saves made outside SlideMage appear as nodes from `git log`. | ~30-50k, 2-3% |

**Decisions (recommendation first).**

- Where it lives: **the Versions side panel** (compact) with an "Open large" view in the centre column;
  or only a full-size view.
- Old translations without a recorded source version: **show the guessed branch point, marked "approx."**;
  or show them unbranched until marked in sync once.
- Mockup first: a clickable HTML mockup of the graph before G3, to settle the look.

## 6. Claude Code does SlideMage's AI tasks, fast

Status: plan, 2026-10-12, revised after review. Suggestion bubbles in the Claude Code tab run each task as
its own `claude -p` with structured output (Haiku, effort medium by default); SlideMage validates the
result and applies it only if the slide is unchanged; a translation is created only after it succeeded.
Done 2026-10-12: steps 0-6 committed. Follow-up: [CLAUDE_CODE_REVIEWS_PLAN.md](CLAUDE_CODE_REVIEWS_PLAN.md).
