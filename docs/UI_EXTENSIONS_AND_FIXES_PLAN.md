# UI extensions and big fixes plan

Status: draft, 2026-10-10. Follows `docs/UI_REDESIGN_PLAN.md`, which is finished on branch `ui-redesign`
(SlideMage 6.0.0). Each item needs the user's go before it starts; pause after each committed item.

Cost figures are rough, from the usage calibration of ~5% of a 5-hour window per ~100k agent tokens.

## 1. Big change: the DE switch follows translations

Status: implemented in SlideMage 7.0.0, 2026-10-11. Design decisions and validation:
[BIG CHANGE 1 implementation](BIG_CHANGE_1_IMPLEMENTATION.md).

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

Status: required review fixes implemented and verified (SlideMage 6.1.1), 2026-10-11.
See the [independent Astra review and concrete commit plan](BIG_CHANGE_2_ASTRA_REVIEW.md)
for the lifecycle, freshness, cleanup and reproducibility findings resolved here. New benchmark
gates use a fixed subset targeting about ten minutes. The
[implemented review fixes](BIG_CHANGE_2_REVIEW_FIXES.md) cover lifecycle, timestamp freshness,
atomic cleanup, raster deadlines and reproducible benchmark evidence.
Detailed design, file changes and original validation:
[BIG CHANGE 2 implementation](BIG_CHANGE_2_IMPLEMENTATION.md). Keep LuaLaTeX, the manual's fonts and theme,
and correct slide output. Use the established preview research results. Experimental component-level
rendering and box/background caches are outside this change.

**Review-fix verification.** The [four-call subset report](preview-benchmark-review-fixes-2026-10-11.md)
passed 80 requests in 7 minutes 54 seconds: zero failures/mismatches, 40 visible
edits, 64 matching candidate PDFs. Saved unchanged median is 0.235 s before and
0.138 s after; edit means are 5.766 s and 5.729 s. The fastest observed full-slide
path is 1; the selected-overlay leader on this subset is 1+3+4. Small differences
are not repeatable rankings. Saved/buffer and full-slide/overlay semantics stay
explicit. Final automated suite: 1,488 passed, 6 skipped.

**Typical user-facing gains against the original fresh-job behavior.** These are
saved-file, full-slide previews after an initial build. Each row averages two
actual successive edits, measured on the same input with and without build reuse.
The title example changes only its heading; bullet/formula/figure examples keep
that heading unchanged. They include compilation, display-image preparation and
snapshot work; automatic-save debounce, lint and Qt painting are excluded.

| Typical action | Original fresh job, s | Optimized preview, s | Seconds saved | Speedup | Less time |
| --- | ---: | ---: | ---: | ---: | ---: |
| Edit one bullet | 7.645 | 2.387 | 5.258 | 3.20× | 68.8% |
| Change the slide title | 7.352 | 4.624 | 2.728 | 1.59× | 37.1% |
| Edit a formula | 7.433 | 2.376 | 5.056 | 3.13× | 68.0% |
| Resize a figure | 7.352 | 2.429 | 4.923 | 3.03× | 67.0% |

The three new examples took **2 minutes 19 seconds**, adding 24 requests to the
earlier bullet probe. Across all four examples, 16 candidate PDFs matched the
original at 72 dpi and 1920-pixel display width, and all 16 edits were visible.
Title edits need two TeX passes; the other tested edits need one. Initial builds
still take about 7–8 s, and difficult fresh-fallback slides remain slower.
[Typical editing report](preview-user-edits-2026-10-11.md),
[raw evidence](preview-user-edits-2026-10-11.json). These examples demonstrate
build reuse's gain over original fresh builds. The incremental BIG CHANGE 2
comparison below starts from an already cached path.

**Historical BIG CHANGE 2 results (2026-10-11).** All 81 active calls in the current manual were measured before and after the change, including two visible edits and an unchanged request. [Final report](preview-benchmark-2026-10-11.md), [raw data](preview-benchmark-2026-10-11.json).

| Path | Cold median, s | Real-edit mean, s | Unchanged median, s |
| --- | ---: | ---: | ---: |
| Before: cached saved file | 7.747 | 4.907 | 0.234 |
| 1: saved file | 7.854 | 5.255 | 0.138 |
| 1+3: complete buffer | 7.783 | 5.257 | 0.137 |
| 1+4: saved overlay 1 | 7.797 | 5.234 | 0.136 |
| 1+3+4: buffer overlay 1 | 7.777 | 5.243 | 0.137 |

Unchanged saved previews improve from 0.234 s to 0.138 s (41%). The full-run edit means include a slower TeX interval; interleaved controls on four calls average 4.857 s before and 4.818 s after. This does not establish a substantial or repeatable real-edit gain. The measured leaders are 1 for saved files and 1+4 for saved overlays, with leads of only 2 ms and 9 ms over the buffer paths. Use 1+3 when the current buffer is requested, 1+3+4 for its selected overlay, and 1+2 for cropped elements. Existing render semantics are preserved.

Verification: 1,461 tests passed, 6 skipped; 11 live TeX scenarios passed; 1,288 comparable matrix PDFs matched; all 810 edits visibly changed their output; four isolated elements matched at 144 dpi. No experimental component renderer is enabled. Both `.fmt` probes still fail in LuaHBTeX, so build-state reuse remains the fallback.

**Measured starting point (2026-10-09).** All 77 active manual slide calls were timed sequentially,
including repeated slidestep variants. Baseline came before implementation. Methodology, rendering
checks and raw timings are in [the benchmark report](preview-benchmark-2026-10-09.md) and
[its data](preview-benchmark-2026-10-09.json).

| Implemented result / combination | Mean per call, s | Total for 77 calls, s | Speedup |
| --- | ---: | ---: | ---: |
| Baseline: fresh job | 7.485 | 576.33 | 1.00x |
| 1: reusable latexmk build state | 2.492 | 191.85 | 3.00x |
| 3: complete source region | 7.406 | 570.28 | 1.01x |
| 4: selected overlay 1 | 7.390 | 569.05 | 1.01x |
| 1 + 3 | 2.440 | 187.89 | 3.07x |
| 1 + 4 | 2.424 | 186.66 | 3.09x |
| 3 + 4 | 7.409 | 570.52 | 1.01x |
| 1 + 3 + 4 | 2.423 | 186.56 | 3.09x |

**Choices from the 9 October run.** Keep **1 + 3** for ordinary editor previews with all overlays. Use
**1 + 3 + 4** when the user explicitly requests one overlay. This was the fastest measured overlay
combination, but its 0.10 s total lead over 1 + 4 is too small to establish a repeatable advantage.
Result 2 (`preview.sty` element selection) is a separate scope: four real manual elements averaged
7.249 s fresh and 2.281 s with build reuse (1 + 2). It cannot replace the complete-slide benchmark
or combine meaningfully with the mutually exclusive frame-region scope and overlay selector.

**Limits of the measurements.** Cached rows measure warm rebuilds forced by a harmless source change,
not unchanged cache hits or real text edits across every slide. Initial builds still had medians of
7.226-7.271 s; unchanged requests had medians of 0.116-0.171 s. One real title edit took 4.492 s after
a 7.345 s initial build. One pass per configuration was measured; small differences can be noise.
Full-slide output has 89 pages; overlay-only output has 77. Comparable PDFs matched the original
standalone previews in pixels and dimensions; this does not establish whole-deck equivalence.
Region previews also omit canonical PNG refresh, so timings include different snapshot work.

**Implemented before BIG CHANGE 2.** Reuse of latexmk auxiliary state and dependency tracking, in-memory source
and selected-region previews, isolated element previews, explicit overlay selection, and a CLI
watch mode for the selected source file. True precompiled preamble (`.fmt`) caching is **not working**:
both manual and Beamer-only probes failed in the installed LuaHBTeX font-loading code. Result 1 uses
build-state reuse as its fallback. Existing PDF graphics are already pre-rendered. The spacing-reference
slide requires a fresh-build fallback because its auxiliary state does not converge.

**Implementation sequence.** The stages below are implemented; the detailed implementation document
records the code and checks. The new report compares the combined backend changes across all compatible
preview modes, with GUI queue behavior verified separately.

1. **Measure where time goes.** Extend the benchmark to record wrapper preparation, each TeX pass,
   bibliography work, PDF copy, PNG generation and display latency. Separate cold builds, unchanged
   requests and real edits. Include text, formulas, lists, graphics, references and overlay edits.
   Run sequentially and repeat configurations in alternating order; report medians and p95 alongside
   totals. Pin the corpus to the measured deck revision so later manual changes remain visible.
2. **Keep the editor responsive.** Audit the GUI compile path and move remaining blocking work to
   a worker. Debounce repeated preview requests, keep the last successful PDF visible while compiling,
   and publish only the newest requested result. Serialize work sharing a build cache and discard
   obsolete results. Show compile errors without presenting an older PDF as if the edit succeeded.
   Measure edit-to-visible-preview latency as well as backend duration.
3. **Remove measured repeat work.** Use the profile to reduce redundant wrapper writes, PDF rendering
   and snapshot generation. Invalidate from source, preamble, dependencies, environment and toolchain
   changes; refresh timestamps correctly. Let latexmk decide required TeX/bibliography passes and
   retain extra passes when references need them. Keep fresh-build fallback for unstable state and
   test broken-edit recovery. Extend watch invalidation to relevant dependencies if needed.
4. **Reduce first-build cost with proven compatibility.** Investigate the observed `.fmt` failure
   in a separate compatibility probe. Adopt preamble caching only if it works with the required
   LuaLaTeX/fontspec/Gotham setup and preserves rendering and invalidation. Otherwise retain the current
   fallback and report that limitation. Cache expensive independent graphics only where profiling
   justifies it; do not blanket-externalize theme TikZ with page-position dependencies.
5. **Rerun the full comparison and select defaults.** Benchmark every compatible implemented
   combination on all manual calls, including actual edits and repeated runs. Keep element selections
   in a separate table. Compare all full-slide pages against fresh previews, and selected overlays
   against their corresponding reference pages. Check errors, recovery, timestamps, references and
   cache invalidation. Publish cold/warm/unchanged tables and choose the fastest repeatable combination
   for each preview scope, preserving all overlays in the ordinary preview.

**Completion criteria.** Every manual call succeeds; comparable output remains unchanged; failed or
superseded edits cannot publish stale results; GUI requests remain responsive. The final table must
show whether each change improves first-build or real-edit latency, with remaining slow cases
identified. Set further speed targets after profiling rather than promise a subsecond TeX compile
from the current measurements.

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
Prototype and benchmark first (step 1). Details: [Claude Code tasks plan](CLAUDE_CODE_TASKS_PLAN.md)
(~315-465k tokens, 16-24% of a window, estimate). Pause after each committed step.
