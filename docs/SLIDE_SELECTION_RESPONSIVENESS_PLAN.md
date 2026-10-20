# Instant slide selection: implementation plan

Status: proposed; application code has not been changed for this work.
Date: 20 October 2026. Revised the same day against `develop` at 7f04f94
(v8.39.1), after a critical review of the first draft.

## Objective and acceptance criteria

Selecting a slide in the left panel must show its available preview on the next
paint, without waiting for editor creation, project scans or cache validation.
The preview must belong to the selected occurrence, view, language and scope.

Input timestamp: the mouse press (which changes the tree's current item), or the
key press for keyboard navigation. Not the mouse release.

Performance targets are provisional until step 1 reports a real baseline. Start
with: for an already decoded, matching image on the reference Linux machine,
median input-to-paint latency of at most 33 ms and p95 of at most 50 ms; tighten
toward 16/33 ms only if the baseline shows that the remaining work (paint
included) leaves room. Measure the actual new image's paint, not just the return
from the selection handler or a paint containing the previous slide.

Also require:

- One focus transition per selection, carrying the occurrence key; plain clicks
  preserve the current mode.
- No editor construction or linting for a normal click in Preview mode, except
  where a pending panel edit must be written through the Source view (step 5
  states how that case is handled).
- No project-wide deck/translation scans, render-store dependency checks or
  dependency hashing on the GUI thread before the preview paints.
- Returning to a matching image in memory does not wait for validation.
- Rapid navigation publishes only the newest selection. Work queues stay bounded;
  GUI-thread panel rebuilds are debounced, not run once per intermediate row.
- Selection starts no slide render. A reveal-step count that selection
  currently starts in the foreground is deferred until the selection settles
  (see step 4); idle reveal-step prefetch remains a separate, lower-priority
  operation.
- Pending edits, autosave, frozen versions, translations and occurrence identity
  remain correct. Deferred panels cannot apply actions to the previous slide.

An image not available in memory is a separate case: keep input responsive,
load/decode a matching persisted image off-thread, and display it on arrival.
For a missing preview, show the selected slide's explicit missing state promptly.
Do not display the previous slide as though it were the new selection.

## Evidence and scope

The investigation used a temporary copy of the working tree before v8.34.0,
including its then uncommitted changes. It exercised 24 selections in the
82-row example deck, with a ready-made 1920 x 1080 pixmap supplied to isolate
selection overhead. The following runs did not use cProfile:

| Diagnostic substitution | Median synchronous work | Including queued Qt events |
| --- | ---: | ---: |
| Current click path | 245.4 ms | 275.8 ms |
| Bypass opening the source editor | 62.2 ms | 77.4 ms |
| Reuse resolved rows | 160.9 ms | 208.5 ms |
| Bypass sidebar refresh | 141.3 ms | 169.6 ms |
| Combine all three substitutions | 16.7 ms | 30.3 ms |

These experiments establish the expensive paths; their times are not additive,
and the combined substitution is not a finished implementation. In particular,
the real sidebar still needs to update, and the substitutions supplied a decoded
pixmap, so they exclude decoding, the render-store lookup and the paint itself.
A separate probe confirmed that a pixmap already present in
`PreviewPane._pixmaps` is not shown while validation is pending.

Caveats for the numbers:

- The clicks were synthetic: press and release ran back to back. In a real click
  the tree's current item changes on press (`_on_current_changed`) and
  `_on_item_clicked` runs on release, about 100 ms later. The editor is built on
  release, so most of its cost may delay the next input rather than the first
  paint. Step 1 re-measures with realistic press/release spacing.
- Keyboard navigation only changes the current item and never opens the editor;
  comparing keyboard and mouse runs isolates the editor's share.
- v8.34.0-v8.39.1 changed rendering (parallel renders, one shared render budget,
  a raster pool, background-store fixes) and the Linux idle watcher. They did
  not change the selection path described below, but the baseline must be
  retaken on current `develop`.

What current `develop` does on a selection (verified at 7f04f94):

- `SlideList._on_current_changed` sets focus with the occurrence key. On release,
  `_on_item_clicked` -> `open_slide_editor(keep_mode=True)` (v8.39.0, PR #7) ->
  `CentreColumn.open_file`, which calls `set_focused_slide(bare_id)` without the
  key and always calls `source.show_path`, building a `SourceFile` even in
  Preview. Every focus listener (side panels, assistant header, top bar,
  background previews) runs twice; the centre skips the second via `_opening`
  but its own `refresh()` then resolves the *first* occurrence. For a slide the
  deck calls twice, the release can switch the preview target to the other
  occurrence and restart validation. This is a correctness bug.
- `PreviewPane.show_slide` -> `_invalidate` clears `_selection_result` for every
  target change, so A -> B -> A waits for validation again. Until validation
  finishes the pane shows "No preview for the ... view yet".
- `_pixmaps` holds up to 12 full-size (1920 x 1080) pixmaps, about 100 MB, and
  is never read.
- `_image` -> `_stored_pixmap` -> `BackgroundPreviews.stored_page` runs
  `renderer.resolver.lookup` (`fast_key`, `manifest_current`, `tex_current`)
  and decodes the PNG on the GUI thread. `_update_reveal` ->
  `_adopt_stored_steps` -> `stored_pages` does the same and reads every step
  PNG.
- `_update_reveal` queues `_request_steps(..., FOREGROUND)`, an all-steps
  render, when a slide that may reveal has no counted steps.
- `_refresh` calls `translation_link`, which builds a new `TranslationLinks`
  (a glob of the slides folder and header reads) on every refresh. A 5 s
  `_validation_poll` re-runs `_refresh`, including the PNG decode, the chips
  and the menu rebuild.
- `PageView.paintEvent` scales the full-size pixmap with
  `SmoothPixmapTransform` on every paint.
- `SidePanels.refresh` flushes then rebuilds the shown panel. `SidePanel`
  resolves the outline separately in `deck_calls`, `_focused_row`, `id_slug`
  and `slide_path`, and ignores the occurrence key. `NotesPanel.flush` writes
  through `CentreColumn.edit_slide_text`, which calls `source.show_path(old
  path)`: it builds an editor and leaves the Source view on the old slide.
- On Linux, `_InputWatcher` polls `QApplication.allWidgets()` every 250 ms on
  the GUI thread (v8.39.0); its gaps belong in the benchmark's event-loop
  measurements.
- `preview_requests.cache_identity` reads the PyMuPDF package version on every
  call.

This work concerns selection and display, not changes to LaTeX compilation,
view-equivalence rules, animation support, the render budget or the presentation
engine. Reuse the existing preview selection policy, background workers,
render store and result-generation guards. Avoid introducing a replacement
scheduler, a general event framework or another independent image cache.

## 1. Establish a repeatable input-to-paint benchmark

Extend `tools/preview_benchmark/` (its fixtures and project copying) with a
selection benchmark using a copied example project. Record the press timestamp,
focus signal count, first matching preview paint, longest event-loop gap, editor
constructions, row resolutions, render-store lookups, PNG decodes on the GUI
thread and sidebar scans. Time worker validation separately. Profiling runs
locate costs; timing runs disable the profiler and avoid unrelated builds and
tests running concurrently. Commit the diagnostic probe so the "before" numbers
can be reproduced.

Exercise the real mouse and keyboard paths with:

- Mouse clicks with press and release about 100 ms apart, and keyboard arrows,
  including held-key auto-repeat.
- A -> B -> A with both images decoded in memory.
- First visits to previews present only in the render store or preview cache.
- Rapid selections while an earlier validation worker is deliberately blocked.
- A slide the deck calls twice, clicking the second occurrence.
- The example deck and a 600-1,000-occurrence deck with repeated calls,
  translations and distinct reveal rules.
- Preview, Source and Split modes, with expensive panels visible and hidden,
  and the Notes panel with a pending edit.

Use a completed Qt paint of the selected image as the automated endpoint.
Perform a packaged-app smoke check on a physical display as well; offscreen Qt
measurements do not measure compositor/display latency.

Deliverable: a reproducible baseline, a split of the cost between press and
release, the validation time per case, and machine-readable before/after
results. Set the final latency targets from this baseline.

## 2. Keep the occurrence, change focus once and keep the editor lazy

Primary files: `ui/workspace/slide_list.py`, `centre.py`, `window.py` and
`source_view.py`.

First fix the occurrence bug as its own change with its own test: opening the
already selected occurrence must keep its key, so the release cannot switch the
preview to another occurrence of the same slide. Selecting a different
occurrence of the same slide must still produce a real focus change.

Unify the tree's current-item and click handling around one resolved occurrence,
so a click emits one focus transition. Avoid performing the same centre refresh
twice for one click.

Separate selecting a slide for Preview from constructing its source editor.
In Preview mode, update the selected path, preview target and visible workspace
page without creating a `SourceFile`. Instantiate/synchronize the editor when
Source or Split is shown, or an operation explicitly requires an editing buffer.
Keep `open_slide_editor` callbacks, `keep_mode` and line positioning working for
explicit opens.

Preserve Enter/double-click opening Source, Ctrl/Shift selection (which still
moves the current item on press), returning from the Images page, pinned files,
translation-partner navigation and clicks on an already selected row after an
explicit file was opened.

Keep pending source buffers attached to their own paths. Preserve the existing
write/conflict/version behavior when leaving an edited file, including the
deferred Update Version offer in `_set_path`; skipping a hidden editor must not
discard edits or accidentally save them to the new target.

Acceptance: the second occurrence stays selected and previewed after release;
one focus signal for a changed occurrence; zero new `SourceFile` objects for
Preview navigation without pending panel edits; no repeated centre refresh
caused by the same mouse click.

## 3. Reuse resolved selection metadata

Primary files: `slide_list.py`, `centre.py`, `panels/base.py`, `preview_view.py`,
`deck_outline.py`, `preview_target.py` and `slide_language.py`.

Expose a small lookup over the resolved outline the list already owns. Identify
the snapshot by project, deck revision, view and language; index occurrences by
their existing keys. Centre, panel and preview-pane lookups should use this
snapshot rather than independently resolving all deck slots and translation
headers. `SidePanel` should resolve its row once per refresh and use the focused
occurrence rather than the first match.

Include the effective frame number, hidden state and Instructor frame number
needed by `PreviewTarget.for_call`. Resolve Instructor numbering once per
snapshot instead of recomputing it for every selected target. Preserve target
identity for preambles, frozen versions and deck-dependent slides.

Keep one `TranslationLinks` per snapshot (or per slides-folder change) instead
of building one in every `PreviewPane._refresh`; the chips and the language
partner read from it.

Invalidate/rebuild on deck edits, rescans, view/language changes and relevant
source/translation changes. Integrate with existing change notifications;
selection itself is not an invalidation event. Initially fall back to the
existing resolver when a snapshot is absent or stale. Standalone files and
translation partners outside the list retain their existing resolution path.

As a small separate change, cache the installed raster-library version used by
`preview_requests.cache_identity` for the process lifetime. Preserve the same
identity value and retain test control over that dependency.

Acceptance: selecting among rows of an unchanged outline does not invoke a
full-deck resolver or glob the slides folder, and duplicate/translated/hidden
rows retain their metadata.

## 4. Show matching cached pixels before validation

Primary files: `preview_view.py` and `background_previews.py`, with narrowly
scoped additions to `preview_selection.py` if shared display-result metadata is
needed.

Start with the smallest change and widen it only where tests show a need:

1. Stop `_invalidate` from discarding displayed pixels on a selection change;
   separate selection invalidation from clearing stored display entries.
2. Make `_pixmaps` the read side of the display cache, keyed by the existing
   `(target.key, view, language)` plus the source/buffer revision it was made
   from. On selection, `_image` shows a hit at once as "previous / Checking
   current source and settings…" while the validator runs, and as current only
   once validation confirms it. Keep visibility and missing-translation rules
   authoritative.
3. Store pixmaps at display size (for example 1280 px wide, or the page's size
   times the device pixel ratio), not full size, and bound the cache by bytes
   (start with 64 MiB) as well as entries. Use the same scaled pixmap for
   painting so `paintEvent` does not rescale a full-size image on every paint.
4. Widen the key (render scope, chosen reveal step, preamble, version,
   frame/deck context) only where whole slides, regions, elements, individual
   steps and draft renders would otherwise overwrite one another. Preserve the
   existing final-page selection rules.

Move the render-store path off the GUI thread: `stored_page` and `stored_pages`
(`resolver.lookup`, store reads) and PNG decoding run in the existing selection
executor on captured, immutable inputs and return `QImage`; create the
`QPixmap` and publish on the GUI thread only if selection identity, generation
and source/buffer revision still match. The preview cache and the render store
remain the two persisted sources; the display cache only holds decoded pixels
from either.

Reveal steps: when the chosen step is not the last page, the displayed image is
the step page, so it is looked up in the display cache by step as well. The
foreground all-steps count that `_update_reveal` starts on selection is
deferred until the selection has settled (the same debounce as the panels in
step 5), showing "Counting…" meanwhile. It must not hold back the slide image.
Decision for the owner: keep this deferred foreground count, or leave counting
to idle prefetch only.

The 5 s `_validation_poll` must reuse the decoded pixmap instead of decoding
the PNG again, and a poll that finds the image unchanged must not rebuild the
chips and menu.

Keep historical display behavior within the boundaries already established by
the shared selection policy. A previous image cannot satisfy a fresh render
request or authorize a PDF from another view. Do not replace dependency
validation with mtime-only freshness checks. Reuse already running validation
for matching requests and cancel obsolete queued requests. Prefetch is optional
until measured selection meets the target; do not make it a prerequisite for the
first improvement.

Acceptance: a blocked validator cannot prevent a matching RAM image from
painting; return visits reuse decoded pixels; the render store is not queried on
the GUI thread; stale completions never replace the selected slide; freshness
labels and PDF provenance remain correct; decoded-cache memory stays within its
budget.

## 5. Move auxiliary work off the preview display path

Primary files: `side_panels.py`, `panels/base.py`, `panels/notes.py`,
`panels/used.py`, `assistant_header.py`, `centre.py` and the relevant pure-data
usage/translation helpers.

Split pending-edit handling from panel presentation. Flush dirty notes and
transcript state against the captured old target before rebinding controls.
`NotesPanel.flush` writes through `CentreColumn.edit_slide_text`, which today
switches the Source view to the old slide. Give that path a way to change the
old file's buffer without making it the Source view's current file (or to edit
a buffer-less file under the same autosave and conflict rules), so the Source
view stays on the new slide. Preserve conflict handling. Immediately disable or
rebind actions belonging to old content so a quick click cannot modify a
previously selected slide; `UsedInDecks._open` should pass the occurrence.

Defer only the expensive data queries and widget reconstruction. Use captured
immutable project/deck/language inputs for worker-side usage and translation
queries. Reuse the window's known decks where valid. Cache/index per-deck
results and invalidate them on relevant writes/rescans, rather than scanning and
resolving every deck on each focus signal. Discard stale results with a
selection ticket.

Debounce the GUI-thread panel rebuild (about 100-150 ms after the selection
stops changing) so held-down arrow keys do not rebuild the panel for every
intermediate row; coalesce workers to the latest pending target. A zero-delay
Qt timer alone is insufficient: its callback may still run before the next
paint. The first preview paint must not depend on auxiliary queries
completing.

Keep Qt widget construction on the GUI thread and do only the bounded final
update there. Apply the same treatment to the assistant offer computation
(`AssistantHeader.schedule`) and other panels if measurement shows them on the
critical path. Hidden panels should not perform full refreshes.

Acceptance: a slow usage query leaves the selected preview and navigation
responsive, the displayed panel eventually matches the newest target, held-key
navigation does not rebuild the panel per row, pending edits remain attached to
the correct file, and the Source view does not switch to the old slide.

## 6. Regression tests and performance verification

Extend existing suites instead of creating timing-sensitive unit tests that
depend on a particular CI machine's speed:

| Suite | Required coverage |
| --- | --- |
| `test_slide_list_gui.py` | One focus transition; second-occurrence identity kept after release; Ctrl/Shift; Enter/double-click; Preview stays visible. |
| `test_centre_gui.py` | Lazy source opening; Source/Split behavior; explicit opens and callbacks; translation partners; pending buffers and version prompts. |
| `test_preview_queue.py` | A -> B -> A with blocked validation; memory/store/cache misses; stale completions; view/language/preamble/version/scope/step boundaries; old-source labels; correct PDF provenance; decoded-cache byte budget. |
| `test_background_previews_gui.py` | `stored_page`/`stored_pages` answered off the GUI thread; stale results discarded. |
| `test_reveal_bar_gui.py` | Deferred step count after selection settles; step page shown from the display cache. |
| `test_slide_list_gui.py` / metadata resolver tests | Reusing outline metadata and invalidating it after deck, language and translation changes; frame numbering and repeated calls. |
| `test_side_panels_gui.py` and panel tests | Slow queries; debounced latest-target publication; pending notes/transcript edits; Source view stays on the new slide; no actions against stale content; hidden panels. |
| `test_workspace_window.py` / `test_palette_gui.py` | Return from other workspace pages and navigation initiated outside the tree. |

Use deterministic guards: fail if the Preview click constructs an editor, runs
lint, scans every deck, globs the slides folder, queries the render store or
performs validation on the GUI thread. Block workers with synchronization
events and verify that the new image paints before release. Keep clock
thresholds in the dedicated benchmark, not ordinary unit assertions.

Run focused tests after each stage. Once the final implementation is stable, run
the full suite and Ruff once, recording pre-existing failures separately. Replay
the benchmark without diagnostic substitutions using real cached images, then
perform a packaged Linux smoke test. Validate Windows/macOS behavior through
available CI/manual environments and report coverage explicitly.

Performance report: median/p95 input-to-paint, the press/release split,
event-loop gaps (with and without the Linux input watcher's poll), first visit
versus return visit, rapid and held-key navigation, large deck, cache hit/miss,
validation time, decoded-cache memory, and whether any compilation/rasterization
occurred.

## Delivery order

Each numbered step below is one application-code commit on `develop` with its
own version bump and changelog entry (`vX.Y.Z (date, reason): …` plus the
user-facing "NEW:" paragraph, following the repository rules). Stop after each
step for review before starting the next.

1. Benchmark and baseline on current `develop`; set the final targets. Preserve
   existing uncommitted user work in the checkout.
2. Fix occurrence identity on click (patch release).
3. One focus transition and the lazy editor; run navigation/source tests.
4. Reuse resolved row/target metadata and one `TranslationLinks` per snapshot;
   cache the raster-library version; run identity and invalidation tests.
5. Immediate cached display, the off-thread render-store lookup and decode,
   display-size pixmaps and the deferred step count; run preview publication,
   reveal and provenance tests.
6. Panel flush without switching the Source view, debounced/coalesced auxiliary
   queries; rerun the benchmark.
7. Complete integration tests, full-suite/lint checks and packaged
   measurements; write the performance report.

The investigation's diagnostic substitutions must not ship. Completion means
the real selection path meets the latency target set after step 1, while
source, sidebar and cache correctness remain covered.
