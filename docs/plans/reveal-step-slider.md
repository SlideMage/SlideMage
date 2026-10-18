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

**Slide through ALL steps of the slide, and mark the ones the selected call includes. Add a "Deck steps only" toggle, and let the slider expand into one timeline per deck version.** The owner needs to see excluded steps to decide what to include, and a deck-only slider can never show them.

Behaviour (decided with the owner):
- **Scope is one call.** The slide is selected at one position in the deck; the ticks show the reveal logic of THAT call only (no union across calls). A slide that appears in several places shows each position's logic when that position is selected.
- Collapsed slider = the current view (the top-bar version). Positions 1..N (N = page count of the unrestricted render in that view). Filled tick = included by the selected call in that view, hollow = excluded. Label: `Step 3 of 5 · in Students` / `· not in Students`.
- A plain `\slide`/`\conditionalslide` call (no `steps`) includes all steps; a slide not in the open deck shows no distinction ("all steps").
- "Deck steps only" restricts slider positions to included steps (the label still shows the true step number).
- The slide opens on its **last** step (today's behaviour).
- Expanded slider = one row per deck version of the open deck (instructor / during-course / after-course), same tick vocabulary (section 4b). Editing ticks is a later phase (section 4c).

## 3. How steps are counted and mapped to pages

### 3.1 What creates reveal steps

All of these are counted by beamer itself, so SlideMage must not re-implement them:
- overlay specs on any command or environment: `<6>`, `<2->`, `<-3>`, `<1,3-5>`, `<+->`, `<.->`, `<+(1)->`, incremental `[<+->]` options on `itemize`/`enumerate`, `\begin{env}<..>` variants;
- `\pause`, `\onslide`, `\only`, `\uncover`, `\visible`, `\invisible`, `\alt`, `\temporal`, `\alert<..>`, `\item<..>`, `\action`/`actionenv`, `overprint`;
- TikZ: the project defines `visible on=<..>` as a TikZ style (`latex/Slidemaster_preamble_base.tex:18-28`).

Slidemaster's own macros expand to the above and depend on the deck version `\SMDeckVersion` (`Slidemaster_preamble_base.tex:1485`):
- `\conditionalpause[versions]`: `\pause` only in the listed versions, **no step at all** elsewhere (`:1795-1800`);
- `\deckonly<n>[versions]{..}` (`:1704-1766`), `\deckuncover`, `\deckvisible`: like `\only/\uncover/\visible`, content gated by version;
- `\deckitem<n->`, `\deckreveal[n]{..}` (omitted from during-course), `\deckrevealfinal[n]{..}` (`:1846-1861`; instructor builds from overlay n, the others show it at once, so no extra pages); see `example/slides/1th-EN-Version-Dependent-Reveals-current.tex`;
- `\ifSMInstructorVersion`, `\ifSMDuringCourseVersion`, `\ifSMAfterCourseVersion` can wrap anything, including overlay specs;
- `\slidefinal{id}` shadows `\conditionalpause` to a no-op for that call (`:1403-1406`);
- `\SMFinalStateForStudents`: non-instructor versions typeset only the last overlay page (`:1937-1952`; README.md:2985-2998). On the first run of a fresh job all pages still appear because the `.ovl` file does not exist yet (README.md:2995-2997).

### 3.2 Step count: the PDF is the truth

- **N_v = number of pages of an unrestricted single-slide render for deck version v.** Beamer emits one page per overlay slide, so page k = overlay k (`slide_preview.py:517-528`). This needs no parsing, so `<+->` counters, `\alt`, `actionenv`, TikZ styles and every custom macro are right by construction, including version dependence (the render is done as version v via the existing view/`deck_version` parameter).
- The unrestricted render must neutralise two restrictions: `steps` (a `\slidestep` target currently compiles restricted, `preview_target.py:105`, `slide_preview.py:518`) and `\SMFinalStateForStudents` (the wrapper switches the flag off so student views are not cut to one page; verify the switch name, `\SMFinalOnlytrue`, `:1952`, when implementing).
- Per-version numbering matters: step k of the during-course timeline is overlay k of the during-course compile. With two `\conditionalpause[instructor]`, instructor N=3 and students N=1; `\slidestep{..}[during-course]{1}` means student overlay 1, not instructor step 1. Rows therefore have their own length and are labelled with their own numbering.
- Fallbacks: if the slide's own frame has a frame-level `<spec>` (page index != overlay number) or `allowframebreaks` (already refused, `slide_preview.py:655-657`), label "Page k", show no included/excluded marks, keep rows read-only.

### 3.3 What static parsing is still needed for (small, best effort)

A lint-style scan of the slide source (`latex_lint.py` already masks comments/verbatim) is used only for:
1. **Version-dependence flag**: does the slide use any of `\conditionalpause`, `\deck*`, `\ifSM*Version`, `\SMFinalStateForStudents`? If not, N_v is the same in all versions, the three version renders collapse into the one already needed (saves up to two compiles), and all rows are editable.
2. **Marking rows read-only ("version logic in the slide")** when the flag is set and N_v differs between versions, or `\SMFinalStateForStudents` applies and no `\slidestep` call overrides it (a `\slidestep` call has priority over the flag, README.md:2998).
3. **Tooltips** (optional): hint such as "`\conditionalpause` at line 12" from first occurrences. Never used to compute N.

Not needed: parsing overlay specs, counting pauses, evaluating `<+->`.

### 3.4 Included set for the selected call

`expand_steps(spec, n) -> frozenset[int]` (new, beside `normalize_steps`, grammar `deck_editor.py:232`): `a`, `a-b`, `a-`, comma lists, clipped to 1..N_v. Row for version v = `expand_steps(call.steps, N_v)` if `call.included_in(v)` (`deck_editor.py:103`) and the call has steps; all of 1..N_v for a call without steps; empty ("slide not shown in this version") if the call is not included in v. Final-state flag and no `steps`: only N_v.

## 4. UI

- A thin bar below `PageView` in `PreviewPane` (`ui/workspace/preview_view.py`; `PageView` at `:166-228`): `‹  [slider with ticks]  ›   "Step 3 of 5 · in Students"   [Deck steps only]`. Hidden when N == 1, so most slides look as today.
- New widget `RevealSlider` (own file in `ui/workspace/`): `QSlider` (horizontal) that paints ticks in `paintEvent` from `ui/kit/tokens.py` colors (no hardcoded colors). Signal `stepChanged(int)`.
- Keyboard: Left/Right, PageUp/PageDown, Home/End when the slider has focus; also Alt+Left/Alt+Right as pane-level step shortcuts (bare arrows are used by the slide list and editor). Compare rendered already uses Left/Right inside its own dialog (`compare_rendered.py:173-176`), no conflict.
- Accessibility: accessible name "Reveal step", value text "Step 3 of 5, included".
- Selected step is kept in memory per slide (not persisted); a slide opens on its last step.

### 4a. Unsaved editor-buffer renders

The slider also works for buffer renders (Ctrl+Enter, `preview_view.py:692-716`). Proposed marking: when the displayed pages come from the buffer, **ticks get a dashed outline and the track uses the existing "draft" chip tone** (the buffer chip in `chips_for`, `preview_view.py:68`), and the label ends `· from the editor buffer`. Saved render: solid ticks. If the buffer's N differs from the saved N, tick clicks are disabled (the deck edit would refer to a step count that is not on disk), tooltip "Save to edit steps".

### 4b. Expandable per-version timelines

- A chevron at the right end of the bar expands it into up to three rows (instructor, during-course, after-course) for the selected call, with the version name in its chip tone (as the visibility matrix, `panels/visibility.py:40-60`). The row of the current view is highlighted; clicking a row's tick shows that step in that version (switches the view for the preview, as the top bar does).
- Row length is N_v; rows with a different N get a "numbered separately" note and a tooltip naming the version-dependent macro found (3.3).
- Rendering: without the version-dependence flag no extra compile. With it, the other versions are rendered lazily when the bar is first expanded (up to two extra unrestricted compiles, cached as in section 5); rows show "counting…" meanwhile.

### 4c. Editing ticks (phase 3)

Click on a tick toggles step k for version v in the **selected call's position**. Writes go through the deck mutators (`deck_editor.py` stale-check-then-write path, `:645-647`; one undo step each, `:722`; GUI wrapper `actions.edit_deck` as in `visibility.py:_set`, which also refreshes when refused). The tick shows a pending state until the write returns.

Model: at one position the deck holds one or more adjacent calls of the same id; each version has at most one active call there (alternatives, README.md:2961-2964). Let S_v be the new included set.

Rules, in order:
1. **No-op if the text already expresses S_v** (`expand_steps(old spec) == S_v`): round-trip safe.
2. **Call serves only v** (`versions == [v]`): rewrite only its `{steps}`.
3. **Call serves v and other versions**: split. The old call keeps the other versions and its spec text untouched; a new `\slidestep{id}[v]{spec}` is inserted directly after it (same indentation). Versions are written in canonical order (instructor, during-course, after-course).
4. **Call has no `steps`** (`\slide`, `\conditionalslide`): the part for v becomes a `\slidestep` call; the rest stays as the old macro with `versions` reduced (`\slide` for all versions becomes `\conditionalslide[others]`). `set_calls_visibility` already does such conversions (`deck_editor.py:426-449`; `format_call` `:269-281`).
5. **Merge after the edit**: if the changed call now has the same spec as an adjacent call of the same id at this position with disjoint versions, merge into one call with the union of versions. If every step is covered again and the call was originally plain, convert back to that macro (undo-exact). Only adjacent calls of this position are touched.
6. **Canonical spec text**: ranges where possible (`1-2,4`); keep an open-ended `m-` if the old spec was open-ended and the set still reaches N_v; tokens that name only steps beyond N_v are preserved verbatim.
7. **Emptying a version** (last tick removed) is refused: that is hiding the slide, which the visibility matrix does. Tooltip points there.
8. **Not editable** (ticks drawn, reason tooltip like `call.readonly_reason`, `visibility.py:68`): pinned versions (`\slideversion`, `\slidefinal`: no `\slidestep` form); rows marked in 3.3(2), i.e. version logic inside the slide (`\conditionalpause`-style numbering that differs per version, or `\SMFinalStateForStudents` without a `\slidestep` override); "Page k" fallback slides; unsaved-buffer N mismatch (4a).

Safety:
- **While a compile runs**: the deck is only read when a compile starts, so the write is safe, but the running full-deck compile's result is then older than the deck; the existing stale marking covers that. The unrestricted preview render does not depend on `steps`, so it is not re-run. Clicks are disabled while a previous tick write is in progress and while an AI task holds the deck (same refusal path as other deck edits).
- **Undo**: one undo step per click via the slide-list undo stack (`deck_editor.py:645-647`). Split/merge is one text replacement over the call lines, so undo restores byte-identical text.
- **Stale file**: refused, with a refresh, if the deck changed on disk meanwhile.

### 4d. Phases

1. Basic slider: collapsed bar, current view, selected call, ticks, toggle, buffer styling.
2. Expandable per-version rows, read-only, with the version-dependence scan and per-version renders.
3. Tick editing with the rules of 4c.

## 5. Caching and render cost

- One compile yields all pages. Do **not** use the existing `overlay=N` path for the slider: that is one compile per step.
- Raster: today `prepare_preview` rasterises only the last page at pane width (`slide_snapshot.py:254-278`; `_preview_pngs` LRU of 16 at `:232-251`). For the slider, rasterise all pages once with `preview_raster_client.read_document(pdf, "pdf_images", 1, MAX_PAGES, dpi)` (what `compare_rendered.read_pages` does, `:39-41`; lift it to a shared helper), in the worker of `_run` (`preview_view.py:545`). Show the last step first, rasterise the rest right after or on first slider use. Keep `list[QPixmap]` per cache key, cap `MAX_PAGES=60`, drop with the `_pixmaps` LRU (`preview_view.py:361-388`).
- Cache key for the unrestricted render: source path, mtime, view, language (without steps). `PreviewTarget.key` includes `steps` (`preview_target.py:60`), so add a steps-free key; two calls of the same slide then share one render.
- No snapshot side effects: the unrestricted render must not publish canonical snapshots/thumbnails (`slide_preview.py:528`, `preview_requests.py:104` already skip them when `overlay` is set; add the same condition for the new flag), so snapshots keep showing the deck's own final state.
- A plain `\slide`/`\conditionalslide` target already renders every page, so reuse its PDF: no second compile. Only `\slidestep` targets need the extra unrestricted compile (once per slide edit, via the existing `RenderService` queue).
- Slides with N == 1 pay nothing.

## 6. Files to touch

- `src/slidemage/deck_editor.py`: `expand_steps()`; in phase 3 `set_call_steps_for_version(...)` implementing 4c (split, merge, convert, canonical spec), reusing `format_call`, `normalize_steps` and the stale-check path.
- new `src/slidemage/reveal_scan.py` (or in `latex_lint.py`): version-dependence scan of a slide source (3.3).
- `src/slidemage/preview_target.py`, `preview_requests.py`, `slide_preview.py`: all-steps render per view for any target (no `steps`, final-state flag off), no snapshot capture, steps-free cache key.
- `src/slidemage/ui/workspace/preview_view.py`: page lists per (view, source), current step, bar, toggle, label, buffer styling, expand.
- new `src/slidemage/ui/workspace/reveal_slider.py`: the bar widget (collapsed and expanded rows); shared page-reading helper moved from `compare_rendered.py:39`.
- Phase 3: wire clicks through `actions.edit_deck` (`panels/visibility.py` pattern) with the undo entry.
- `src/slidemage/ui/kit/`: tokens/QSS for solid, hollow and dashed ticks if needed.
- `CHANGELOG.md`, `README.md` (Preview and `\slidestep` sections), version bump per repo convention.
- Keep the "Reveal step: N…" menu item (`preview_view.py:466,481`) until the slider has shipped, then remove it.

## 7. Tests (pytest, `QT_QPA_PLATFORM=offscreen`, style of `tests/test_compare_rendered_gui.py` and `tests/test_centre_gui.py`)

- Unit: `expand_steps("1-2,4", 5) == {1,2,4}`, `"2-"`, `"1"`, out-of-range clipped, invalid raises ValueError.
- Unit: included set per version for a call (`included_in`, no-steps call, call not in version, final-state flag).
- Unit: the version-dependence scan finds `\conditionalpause`, `\deckitem<3->`, `\deckreveal`, `\deckonly`, `\ifSM*Version`, `\SMFinalStateForStudents`, ignores comments/verbatim, and says "plain" for `\pause`, `\only<2>`, `<+->`.
- Unit (phase 3), table-driven on deck text: single-version rewrite; split of a shared call (new call after, canonical version order); plain `\slide` conversion; merge back to the original text; no-op when the set is unchanged; refusal on emptying; open-ended spec preserved; beyond-N tokens preserved; calls of another position untouched; round trip (off then on gives the original text or text that re-expands to the same set); undo restores bytes; stale file refused.
- `tests/test_reveal_slider_gui.py`: fake render service (like the stub at `test_compare_rendered_gui.py:62-78`) returning N pages per view; slider range, tick flags, Left/Right, label, toggle skipping excluded steps, hidden for one page, opens on the last step, resets on slide change, expand shows three rows with their own N, per-position logic (two calls of one id), buffer render uses dashed style and disables clicks on N mismatch, read-only rows show their reason, a tick click writes the deck and one undo restores it.
- Request tests (`test_preview_requests.py`, `test_preview_target.py`): the all-steps render has no steps and no snapshot and shares its cache key across calls; a slide without version dependence does one compile for three rows.
- Real-TeX tests (skipped without LaTeX, like `test_preview_build.py`): two `\pause` give 3 pages; `\conditionalpause[instructor]` gives 2 pages instructor and 1 student; a `\SMFinalStateForStudents` slide gives all pages in a student slider render.

## 8. Open questions for the owner

1. Student rows of a slide with `\SMFinalStateForStudents`: read-only (proposed) or editable, where the first edit writes a `\slidestep` call that overrides the flag?
2. Slides with version-dependent numbering (`\conditionalpause[instructor]`): read-only rows as proposed, or editable with a warning that step numbers are per version?
3. When a version is fully ticked again after edits, revert the call to the plain `\slide`/`\conditionalslide` (undo-exact, proposed) or keep `\slidestep ... 1-`?
4. Extra compiles for version rows (up to two, only for slides with version-dependent macros): lazy on expand (proposed) or always?
5. Slides with their own frame-level overlay spec: accept the "Page k", read-only fallback?
6. Slider hidden in transcript/presenter views (recommended)?
