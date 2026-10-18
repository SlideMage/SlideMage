# Reveal-step slider under the slide view: findings and plan

Status: plan only (no code). Base: develop @ b3acd47 (v8.23.1).

## 1. Does SlideMage already show reveal steps? Partly. No slider.

| Piece | Exists? | Where |
|---|---|---|
| Steps defined in slides (plain beamer overlays: `\pause`, `\only<n>`, `\item<n->`, `\uncover`, `\textcolor<n>`) | yes | README.md:2946-2948 |
| A deck picks steps per call and version: `\slidestep{id}[versions]{steps}` becomes `\begin{frame}<steps>` | yes | README.md:2943-2970; parsed in `deck_editor.py:68` (regex), `SlideCall.steps` `deck_editor.py:82`, `normalize_steps` `deck_editor.py:236`, step grammar `_STEPS_RE` `deck_editor.py:232` (`1`, `1,2`, `2-`, `1-2,4`) |
| Student decks keep only the last overlay page (`\SMFinalStateForStudents`) | yes | README.md:2985-2998 |
| Editing a call's steps in the app | yes | slide list "Reveal steps…" `ui/workspace/slide_list.py:58,583-596`; Details matrix shows "Steps 1,2" per call `ui/workspace/panels/visibility.py:61` |
| Preview renders every overlay as one PDF page | yes (single-slide wrapper, no overlay restriction gives all pages) | `slide_preview.py:463-528`, `_overlay_line` `:639-657` |
| Main Preview shows steps | **only the last page** (final state) or **one step chosen in a menu** | last page: `slide_snapshot.py:254-278,287`; `preview_view.py:361-388` (`_image`); menu "Reveal step: N…" is a typed number, `preview_view.py:466,481-485`; `overlay` reaches `slide_preview._overlay_line` (`\gdef\beamer@whichframes{N}`) via `preview_target.py:110-121`, `preview_requests.py:91-104` |
| Paging through steps | **only in the "Compare rendered" dialog** (‹ › / arrow keys, "Page n of N"); reads all PDF pages as PNGs | `ui/workspace/compare_rendered.py:11,39-41,139-176,209-241` |
| Slider / ticks / step label under the slide view | **no** | none |
| Showing which steps a deck/version includes, in the preview | **no** (the preview of a `\slidestep` call just contains the restricted pages) | `preview_target.py:105`; `slide_preview.py:515-518` |

Gaps against the request: no step slider in the main Preview; the user cannot see all steps and which are in the current deck/version at once; the menu overlay is a typed number and re-renders every time.

## 2. Recommendation (answer to the owner's question)

**Slide through ALL steps of the slide, and mark the ones the current deck/version includes. Add a "Deck steps only" toggle.** Default: all steps, because the owner needs to see excluded steps to decide what to include. Reasons:

- A deck-only slider can never reveal a step the deck hides, so it cannot support the decision.
- All-steps plus marking answers both questions (what exists, what is in) in one control; the toggle covers "show me what the student sees".
- Render cost is the same either way: one compile gives all pages (section 5).

Behaviour:
- Slider positions 1..N (N = PDF page count). Ticks: **filled/accent** = included by the deck in the current view, **hollow/dim** = excluded. Label: `Step 3 of 5 · in Students` / `· not in Students`.
- If the slide is not in the open deck, or is called with a plain `\slide`/`\conditionalslide`, all steps count as included (no tick distinction, label "all steps").
- "Deck steps only" restricts slider positions to the included steps (M positions; the label still shows the true step number).
- Later (not v1): clicking a tick toggles that step's inclusion by rewriting `\slidestep` through `deck_editor` (path of `slide_list.py:583-596`). v1 stays read-only so a slider never edits the deck.

## 3. How pages map to steps

- A single-slide preview compiles the slide in a wrapper (`slide_preview.py:517-528`); beamer emits one page per overlay slide, so with **no restriction page k = overlay k**. N = the highest overlay number used. This holds unless the slide's own frame has a frame-level `<spec>` or `allowframebreaks` (the latter is already refused in `_overlay_line`, `slide_preview.py:655-657`).
- **The slider needs an unrestricted render.** A `\slidestep` target compiles with `steps`, so only the included pages exist (`preview_target.py:105`). For the slider, compile the same target with `steps=None` (branch at `slide_preview.py:518`). The normal displayed page stays as today.
- Fallback: if the source has its own frame-level overlay spec (page index differs from overlay number), label "Page k" instead of "Step k" and drop included/excluded marks.
- Included set: expand the spec against 1..N (`a-b`, `a-`, comma list; grammar at `deck_editor.py:232`). New pure helper `expand_steps(spec, n) -> frozenset[int]` beside `normalize_steps`. A call without `steps` includes all; a version under `\SMFinalStateForStudents` includes only N (detect the flag in the slide source).
- Which calls/version: `SlideCall.included_in(view)` (`deck_editor.py:103`) says whether a call is active in a version. Active steps for a view = union of `expand_steps` over the slide's calls in the open deck that are `included_in(view)`. The Preview already has the row and view (`preview_view.py:241,324`; `state.view`). Union answers "does this deck show step 3 in this version?".

## 4. UI

- A thin bar below `PageView` in `PreviewPane` (`ui/workspace/preview_view.py`; `PageView` at `:166-228`): `‹  [slider with ticks]  ›   "Step 3 of 5 · in Students"   [Deck steps only]`. Hidden when N == 1, so most slides look as today.
- New widget `RevealSlider` (own file in `ui/workspace/`): `QSlider` (horizontal) that paints ticks in `paintEvent` from `ui/kit/tokens.py` colors (no hardcoded colors). Signal `stepChanged(int)`.
- Keyboard: Left/Right, PageUp/PageDown, Home/End when the slider has focus; also Alt+Left/Alt+Right as pane-level step shortcuts (bare arrows are used by the slide list and editor). Compare rendered already uses Left/Right inside its own dialog (`compare_rendered.py:173-176`), no conflict.
- Accessibility: accessible name "Reveal step", value text "Step 3 of 5, included".
- Selected step is kept in memory per slide (not persisted); default is the last step (today's behaviour).

## 5. Caching and render cost

- One compile yields all pages. Do **not** use the existing `overlay=N` path for the slider: that is one compile per step.
- Raster: today `prepare_preview` rasterises only the last page at pane width (`slide_snapshot.py:254-278`; `_preview_pngs` LRU of 16 at `:232-251`). For the slider, rasterise all pages once with `preview_raster_client.read_document(pdf, "pdf_images", 1, MAX_PAGES, dpi)` (what `compare_rendered.read_pages` does, `:39-41`; lift it to a shared helper), in the worker of `_run` (`preview_view.py:545`). Show the last step first, rasterise the rest right after or on first slider use. Keep `list[QPixmap]` per cache key, cap `MAX_PAGES=60`, drop with the `_pixmaps` LRU (`preview_view.py:361-388`).
- Cache key for the unrestricted render: source path, mtime, view, language (without steps). `PreviewTarget.key` includes `steps` (`preview_target.py:60`), so add a steps-free key; two calls of the same slide then share one render.
- No snapshot side effects: the unrestricted render must not publish canonical snapshots/thumbnails (`slide_preview.py:528`, `preview_requests.py:104` already skip them when `overlay` is set; add the same condition for the new flag), so snapshots keep showing the deck's own final state.
- A plain `\slide`/`\conditionalslide` target already renders every page, so reuse its PDF: no second compile. Only `\slidestep` targets need the extra unrestricted compile (once per slide edit, via the existing `RenderService` queue).
- Slides with N == 1 pay nothing.

## 6. Files to touch

- `src/slidemage/deck_editor.py`: `expand_steps()`, optional `SlideCall.active_steps(n)`.
- `src/slidemage/preview_target.py`, `preview_requests.py`, `slide_preview.py`: all-steps render flag for `\slidestep` targets, no snapshots, steps-free key.
- `src/slidemage/ui/workspace/preview_view.py`: keep page list and current step, add slider bar, toggle, label; `_image` returns the page for the step.
- new `src/slidemage/ui/workspace/reveal_slider.py`: the widget; shared page-reading helper (moved from `compare_rendered.py:39`).
- `src/slidemage/ui/kit/`: tokens/QSS only if no suitable muted/accent pair exists.
- `src/slidemage/CHANGELOG.md`, `README.md` (Preview section), version bump per repo convention.
- Keep the menu item "Reveal step: N…" (`preview_view.py:466,481`) for buffer renders until the slider covers them (open question 3).

## 7. Tests (pytest, `QT_QPA_PLATFORM=offscreen`, style of `tests/test_compare_rendered_gui.py` and `tests/test_centre_gui.py`)

- Unit: `expand_steps("1-2,4", 5) == {1,2,4}`, `"2-"`, `"1"`, out-of-range ignored, invalid raises ValueError.
- Unit: union of active steps over several calls and views; `\SMFinalStateForStudents`; non-`\slidestep` call includes all.
- `tests/test_reveal_slider_gui.py`: fake render service (like the stub at `test_compare_rendered_gui.py:62-78`) returning N pages; assert slider range 1..N, tick flags, Left/Right change the shown pixmap and label, "Deck steps only" skips excluded steps, hidden for one page, resets on slide change.
- Request tests (`test_preview_requests.py`, `test_preview_target.py`): the all-steps render of a `\slidestep` target has no steps, creates no snapshot, and shares the cache key across two calls.
- One real-TeX test, skipped without LaTeX like `test_preview_build.py`: a slide with two `\pause` gives 3 pages, page k = step k.

## 8. Open questions for the owner

1. A slide with several calls in one deck (README example: steps `1,2` in one place, `3` in another): union across the version's calls (recommended) or only the focused call?
2. Should clicking a tick toggle that step's inclusion (writes `\slidestep`)? Suggested as a follow-up.
3. Unsaved editor-buffer renders (Ctrl+Enter, `preview_view.py:692-716`): slider in v1, or saved-file renders only?
4. Default step on opening a slide: last (today's behaviour, recommended) or step 1?
5. Slides with their own frame-level overlay spec: accept the "Page k" fallback labelling?
6. Slider hidden in transcript/presenter views (recommended)?
