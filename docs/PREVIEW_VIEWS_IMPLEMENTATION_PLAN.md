# Preview views: implementation plan

Follow-up: [Preview rendering optimization plan](PREVIEW_RENDER_OPTIMIZATION_PLAN.md)
starts the next phase, including pre-render reuse across views whose supported
rules and effective deck context are equivalent. The completed work below records
the earlier render-first approach.

Source: `small_ui_todos.md`, “Optimize preview rendering across Instructor / During course / After course views.”

Goal: render the selected view or all three views, reuse verified identical output, and make successful
GUI and Claude Code tool renders available in the main Preview pane. Each numbered
step was implemented and reviewed separately, in order.

Status (v8.21.0, 2026-10-15): steps 1–8 are complete. The real LuaLaTeX gate and
224 integrated preview tests passed; the final Source/Details palette regressions
also passed. Full-suite and packaged-build evidence, benchmark counts and the four
remaining unrelated GUI failures are recorded in
[Preview views validation](PREVIEW_VIEWS_VALIDATION.md). The full suite is not
reported as clean. Whole-deck all-view refresh and cross-view reuse for scoped or
presenter previews remain outside this implementation.

## Baseline behaviour and confirmed gaps (before implementation)

- `preview_target.py` captures the slide call, preamble and frame number. Resolve a target separately for
  each view: filtering can change visibility and numbering.
- `preview_requests.RenderService` shares identical in-flight requests, with the view in the key. It
  removes completed requests; it is not a completed-result cache.
- `PreviewPane` keeps a small per-view pixmap cache. Its disk fallback uses instructor snapshots only.
- `render_preview` in `ai/tools/slidemage.py` uses the workspace's selected view. The GUI workspace routes
  it through `request_render` / `finish_render`, with checks against stale source, context and generation.
- `refresh_preview` in `ai/tools/previews.py` explicitly renders instructor output, writes snapshots, and
  reports success without notifying the pane. An older in-memory image can continue to take precedence;
  During/After course do not read this snapshot. Existing tests explicitly enforce instructor rendering.
- A render can therefore succeed without updating the visible pane. That is a confirmed code-path gap,
  although the specific tool used in the reported Claude Code session has not been identified.

## Behaviour decisions

- Use existing canonical values: `instructor`, `during-course`, `after-course`; add `all` for requests.
  An omitted view means the currently selected view for `render_preview`.
- “Render all views” initially applies to the focused slide, using one captured source revision. Existing
  whole-deck preview refresh remains available; extending deck batches to all views is a follow-up.
- A hidden slide is reported as hidden, with no image for that view. Do not quietly render it standalone.
- Reuse means identical complete preview output, including footers, frame numbers, page sizes and reveal
  steps. A visible deck label normally makes the three views different. Do not crop out footer differences.
- Arbitrary TeX cannot safely be classified by searching for a few conditional macros. First render each
  missing view to establish equality; retain that evidence only while its inputs are unchanged.
  This saves subsequent renders and duplicate image storage, not necessarily the first three compiles.
- Keep per-view PDFs for links, text and metadata even when their raster images match. Pixel equality
  alone does not establish that the PDFs are interchangeable.
- Presenter, region, element and explicit-overlay renders retain separate identities. Start cross-view
  reuse with ordinary full-slide previews only.

## 1. Fix tool-result publication and make success messages accurate

Files: `ai/tools/previews.py`, `ai/workspace.py`, `ui/workspace/chat/gui_workspace.py`,
`ui/workspace/preview_view.py`; tests in `test_agent_tools.py` and `test_preview_queue.py`.

- Route single-slide refresh completion through a workspace notification/publication method on the GUI
  thread. Retain headless support. Carry the target, view, language, revision and rendered artifact.
- Invalidate or replace the matching older pixmap when a snapshot refresh completes. Repaint only if the
  visible target matches. Never replace a newer draft with a saved-source render.
- Return distinct outcomes: rendered, cached, displayed, hidden, failed, or superseded. A successful build
  whose display was superseded must not claim it updated the visible pane.
- Keep the existing instructor default of `refresh_preview` during this repair and state it in its result.

Done when: a refresh of the focused instructor slide replaces an existing older pixmap; a refresh of another
slide or view leaves the current page alone; a source edit during rendering prevents stale publication.
Test through the tool-to-GUI route, including the MCP response, rather than only mocking the renderer.

## 2. Introduce a shared request/result model and per-view target resolution

Files: `preview_target.py`, `preview_requests.py`, `deck_outline.py`, `ai/tools/slidemage.py`.

- Add immutable request and result records, including source revision, canonical view, target, language,
  render options, PDF, page images, dependencies, and publication status.
- Add a resolver for one requested view or `all`. Resolve calls, translations, visibility and frame numbers
  separately for each view; preserve pinned versions and restricted reveal steps.
- Identify the selected deck occurrence when a slide is included more than once. A slide-id-only tool
  request should use the focused occurrence when applicable, otherwise document a deterministic choice.
- Capture the source once for an all-view request. Do not switch the workspace's selected view to render.

Done when: tests cover hidden conditionals, omitted slides, pinned versions, translations, duplicate calls,
and different frame numbers. Invalid view values fail before any compile starts.

## 3. Add a completed-result cache with dependency validation

Files: new `preview_cache.py`, `preview_requests.py`, `preview_build.py`, `preview_format.py`.

- Store results by full render identity: project, source content, target/call, deck preamble, view, language,
  frame number, footer options, mode, overlay, presenter flag, and renderer/cache schema version.
- Persist artifacts and manifests under a new `.previews/` subdirectory. Keep the existing instructor
  thumbnail paths and their consumers compatible; they are not evidence of a view-specific cache hit.
- Reuse recorded TeX dependencies (`.inputs.json`, recorder and format inputs) to validate freshness.
  Cover framework, included files, graphics, bibliography, toolchain/configuration and missing inputs;
  invalidate when resolution changes, including a newly added file that shadows a former input.
- Use atomic manifest writes and the existing locking/cleanup conventions. Bound cache size and age;
  do not remove artifacts still used by consumers. Missing or corrupt manifests are cache misses.
- Specify timestamp handling: cache hits retain the original render timestamp; a forced rerender generates
  a new one. Use one timestamp for a batch so sequential jobs do not differ merely by starting time.

Done when: unchanged requests hit across pane switches and app restarts; edits to any relevant input miss.
Include a regression for updating an external project framework without changing the slide source.

## 4. Detect identical outputs and share their image artifacts

Files: `preview_cache.py`, `preview_raster.py`, `preview_raster_client.py`, `slide_snapshot.py`.

- In the raster worker, compute deterministic signatures of every page at a fixed rendering configuration,
  including dimensions and page order. Compare all reveal steps, not just the last displayed page.
- Store matching page images once and let separate view records reference them. Keep each view's own
  render metadata and PDF. Validate the signatures' configuration through a schema version.
- Record which views are equivalent for this exact revision and dependency set. Reuse those records on
  later requests; clear the relationship when any participating input changes.
- Do not infer equivalence from slide text alone or propagate old equality across a source edit.

Done when: identical outputs share image storage; different footer labels, frame numbers, intermediate
steps or page counts remain separate. Metrics distinguish compile avoidance from post-render deduplication.

## 5. Add shared orchestration for rendering all views

Files: `preview_requests.py`, `ai/workspace.py`, `ui/workspace/chat/gui_workspace.py`.

- Add a batch API returning ordered results for Instructor, During course and After course.
- Resolve all targets, use validated cache hits, then render missing views through the existing service.
  Start with sequential compiles and share matching in-flight work; avoid three independent TeX processes.
- Preserve valid results for non-visible views in the cache. Display publication remains conditional on
  the current selection, but switching views must not discard useful completed batch results.
- Track cancellation per consumer. Currently a cancelled consumer can cancel a shared RenderRequest;
  detach that consumer and stop work only when no consumer needs it or the service closes.
- Report progress and partial failures. One failed view must not discard successful views. Stop cancels
  unfinished work and retains completed valid results.

Done when: a mixed cached/rendered/hidden batch returns correctly; switching views during the batch shows
only matching output; cancellation of one tool consumer does not abort a pane consumer's shared render.

## 6. Add the Preview UI actions

Files: `ui/workspace/preview_view.py`, `actions.py`, `menus.py`; GUI queue tests.

- Keep the primary Render action for the selected view. Add **Render all views** to the split-button menu
  and command palette for the focused slide. Clearly separate saved-file and editor-buffer actions.
- Add a forced rerender action that bypasses completed-result reuse for troubleshooting.
- Show progress such as “Rendering During course · 2/3”, and summarize hidden or failed views.
- Switching the view selector loads the exact matching cached result immediately. Label verified reuse
  where useful, and retain the existing stale/draft notices when no valid match exists.
- Disable all-view rendering for presenter/region/element scopes initially, with an explanatory tooltip.

Done when: render all once, switch among all three views, and see the right result with no new compiles.
Test partial failure, source changes during the batch, and leaving/closing the pane.

## 7. Expose specific/all views to Claude Code and chat tools

Files: `ai/tools/slidemage.py`, `ai/tools/previews.py`, workspace adapters, tool documentation;
`test_agent_tools.py`, `test_mcp_server.py`, `test_preview_queue.py`.

- Extend `render_preview` with `view`: `instructor`, `during-course`, `after-course`, or `all`.
  Omission preserves selected-view behaviour. Route it through the batch service from step 5.
- Return explicitly labelled images and per-view statuses in stable order. Test the image-to-view mapping
  through the actual MCP serialization, including hidden views and partial failures.
- Extend `refresh_preview` with the same explicit choices; preserve its instructor default for compatibility
  and document it clearly. Instructor renders update legacy thumbnails; other views update the new cache.
- Make rendered output available in the pane without changing the user's selected slide/view. Report
  “cached for After course” when that view is not currently visible, instead of implying it was displayed.
- Update Claude tool guidance to use `render_preview(view=...)` for visual checking and `view=all` to check
  all course variants. Document that refresh and visual inspection are different operations.

Done when: Claude Code requests During course and gets the corresponding image; `all` returns three labelled
outcomes; omitted arguments remain compatible; a successful current-view render reaches the visible pane.

## 8. Validate end to end and document the behaviour

- Add real-LaTeX fixtures: identical views with the deck footer label hidden; default differing labels;
  deck-only content; conditional pauses/reveals; hidden slides; numbering changes; translations; pinned slides.
- Verify complete page sequences for equality tests and the final displayed image for pane tests.
- Measure cold all-view rendering, warm all-view rendering, view switching and invalidation after an image
  or framework edit. Record compile count, raster count, cache hits and elapsed time with preview metrics.
- Run the focused tests after each step; run the full suite and lint once integration is complete, noting
  pre-existing failures separately. Update the manual, tool help and changelog using repository conventions.
- Build and smoke-test the packaged executable against a separate project copy, including its external
  framework and the Claude Code MCP route. No copy to the user's installed app is part of this plan.

Final acceptance: successful tool renders are visible when their context matches; all-view rendering fills
all applicable view caches; unchanged repeated requests require no LaTeX run; only verified identical
images are shared; source, dependency and context changes never show an old result as current.

Follow-up v8.21.2: the compatibility default for `refresh_preview` was changed to
`all` after Claude Code requests were observed refreshing only Instructor. An
explicit view still restricts the render; the visible workspace view is preserved.
