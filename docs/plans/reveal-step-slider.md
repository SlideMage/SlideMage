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
- **Slides with their own frame-level overlay spec** (the owner's Q5; plain explanation: a slide author may write `\begin{frame}<2-4>` so that beamer emits only overlays 2 to 4, and then PDF page 1 is not overlay 1). Plan, in order of preference:
  1. *Override for the slider render.* `slide_preview._overlay_line` already sets `\beamer@whichframes` after the preamble and its docstring says this applies "including to raw Beamer frames" and "overrides a slidestep filter" (`slide_preview.py:639-657`). The slider's unrestricted render sets it to `1-`, so page k = overlay k even for such frames. To be verified by one experiment at implementation time (does a raw `\begin{frame}<2-4>` still honour the override?).
  2. *Parse the spec* (digits, commas, ranges, open end; same grammar as `_STEPS_RE`, `deck_editor.py:232`) from the slide's `\begin{...frame}<spec>` to mark steps the **slide itself** excludes (third tick style: crossed/grey, not clickable) and, for the ordinary restricted render, to map page j to the j-th overlay of the spec in ascending order (pages are the spec's overlays up to the frame's maximum, in order, so the open end continues 2,3,4,...).
  3. *Fallback only if the spec cannot be parsed* (macro-built spec, `\begin{frame}<\mychoice>`): label "Page k", no marks, read-only.
- **How `\slidestep` combines with a frame's own spec.** `\slidestep` sets `\SMSlideSteps` and `\SMOpenFrame` puts it into `\begin{frame}<steps>` (`Slidemaster_preamble_base.tex:1985-1991`, `:2001`). Slidemaster's frame environments (`standardframe` etc., `:3861`) all open through `\SMOpenFrame` and take no spec of their own, so for them the only frame spec is the deck's (or the final-state `\SMFinalSpec`, `:1975-1984`; the `\slidestep` spec wins, `:1988`). A raw `\begin{frame}<spec>` in a slide bypasses `\SMOpenFrame`, so `\slidestep` has **no effect on it** (to confirm by test); the slider must then say "this slide's own frame spec decides" and make its ticks read-only. Beamer takes one spec per frame, so the two never intersect.
- Other fallback: `allowframebreaks` (already refused, `slide_preview.py:655-657`): "Page k", read-only.

### 3.3 What static parsing is still needed for (small, best effort)

A lint-style scan of the slide source (`latex_lint.py` already masks comments/verbatim) is used only for:
1. **Version-dependence flag**: does the slide use any of `\conditionalpause`, `\deck*`, `\ifSM*Version`, `\SMFinalStateForStudents`? If not, N_v is the same in all versions, the three version renders collapse into the one already needed (saves up to two compiles), and all rows are editable.
2. **Warning on rows with version-dependent numbering**: when the flag is set and N_v differs between versions, the row header shows "numbered per version (instructor N=3, during-course N=1)". Editing stays allowed with that warning (section 3.5 explains why numbering stays per version). `\SMFinalStateForStudents` rows are marked "final state only (flag); an edit overrides it" (see 4c rule 9).
3. **Tooltips** (optional): hint such as "`\conditionalpause` at line 12" from first occurrences. Never used to compute N.

Not needed: parsing overlay specs, counting pauses, evaluating `<+->`.

### 3.4 Included set for the selected call

`expand_steps(spec, n) -> frozenset[int]` (new, beside `normalize_steps`, grammar `deck_editor.py:232`): `a`, `a-b`, `a-`, comma lists, clipped to 1..N_v. Row for version v = `expand_steps(call.steps, N_v)` if `call.included_in(v)` (`deck_editor.py:103`) and the call has steps; all of 1..N_v for a call without steps; empty ("slide not shown in this version") if the call is not included in v. Final-state flag and no `steps`: only N_v.

### 3.5 Master list of all steps across versions: evaluation

Idea: one master list of reveal steps; each version's timeline shows only its selected master steps, so step 3 is "step 3" everywhere.

**What a mapping would need.** Version v's pages are overlays 1..N_v of v's own compile. A master variant would render with every version-conditional macro active (a `master` pseudo-version where `\ifdeckversioninlist` is true, `\conditionalpause` always pauses). Then each v-page must be mapped to master step(s).

**Why it is not well defined in general.**
- *Pauses are relative, explicit specs absolute.* `\pause`/`\conditionalpause` number by position (the k-th active pause), while `\only<3>`, `\item<2->`, `\uncover<4>` use fixed numbers. Removing a pause in a student version shifts later pauses but not the explicit specs, so the same content appears at overlay 3 in one version and 2 in another, and in the student render some pages can be identical to their neighbours. There is no monotone relation to recover from.
- *Many-to-one.* Several master steps fold into one student page (three instructor pauses that are no-ops for students leave one page). A student "tick" would be shared by master steps 1, 2 and 3: toggling them separately is meaningless.
- *Content differences.* `\deckreveal` (omitted from during-course), `\deckonly[versions]`, `\ifSM*Version` change page contents, not only counts, so comparing renders (images or `pdftotext`) cannot align pages: a student page is neither equal to nor a superset of a master page. Image/text alignment is fragile (animations in TikZ, timestamps in footers, hyphenation shifts).
- *Instrumentation can fix part of it.* A hook in `\conditionalpause`, `\deck*` and `\ifSM*Version` that, on the first overlay of a frame (`\beamer@slideinframe = 1`, as `\SMRecordOverlays` does, `:1964-1968`), appends "occurrence i, condition c, active in v, pause counter p" to a file would give an exact master-step identity for the *Slidemaster* macros, and the existing `.ovl` mechanism shows that writing such data during compilation works (`:1960-1990`). It covers nothing written with plain beamer specs after a version-dependent pause (the shifting problem above), needs a new compile mode (`master`) in the preamble, i.e. a change to every project's copy of `Slidemaster_preamble_base.tex`, and costs one more render of every slide with version logic.

**Ticks back to `\slidestep` specs.** Specs are in each version's own numbering, so a master tick must be translated master step -> v-overlay j via the map, and a master step that has no page in v (a skipped pause) has no representation: it cannot be ticked, only "n/a". Round trips through a many-to-one map cannot be exact.

**Verdict: not robust; do not build a master list.** Recommended instead: **per-version numbering** (a row's step k is overlay k of that version's compile, which is exactly what `\slidestep` means, so ticks map 1:1 to specs), with
- a visible **warning** on slides flagged by the scan (3.3): "Steps are numbered per version here: this slide has version-dependent pauses (instructor N=3, during-course N=1)";
- row headers showing each version's own N;
- optionally, later and only for slides whose version logic consists solely of `\conditionalpause`, a thin **alignment hint** (small connector or tooltip "this student step = instructor steps 1-3") from the instrumentation above. Treat that as a separate research item after phase 3; no editing depends on it.

## 4. UI

- A thin bar below `PageView` in `PreviewPane` (`ui/workspace/preview_view.py`; `PageView` at `:166-228`): `‹  [slider with ticks]  ›   "Step 3 of 5 · in Students"   [Deck steps only]`. Hidden when N == 1, so most slides look as today.
- New widget `RevealSlider` (own file in `ui/workspace/`): `QSlider` (horizontal) that paints ticks in `paintEvent` from `ui/kit/tokens.py` colors (no hardcoded colors). Signal `stepChanged(int)`.
- Keyboard: Left/Right, PageUp/PageDown, Home/End when the slider has focus; also Alt+Left/Alt+Right as pane-level step shortcuts (bare arrows are used by the slide list and editor). Compare rendered already uses Left/Right inside its own dialog (`compare_rendered.py:173-176`), no conflict.
- Accessibility: accessible name "Reveal step", value text "Step 3 of 5, included".
- Selected step is kept in memory per slide (not persisted); a slide opens on its last step.

### 4a. Where the slider shows, and unsaved editor-buffer renders

The slider is **hidden in the transcript and presenter views** (owner decision): their PDFs are not per-overlay slides (`preview_view.py:759` transcript; presenter output is a dual-screen layout, `preview_requests.py:100-101`).

The slider also works for buffer renders (Ctrl+Enter, `preview_view.py:692-716`). Proposed marking: when the displayed pages come from the buffer, **ticks get a dashed outline and the track uses the existing "draft" chip tone** (the buffer chip in `chips_for`, `preview_view.py:68`), and the label ends `· from the editor buffer`. Saved render: solid ticks. If the buffer's N differs from the saved N, tick clicks are disabled (the deck edit would refer to a step count that is not on disk), tooltip "Save to edit steps".

### 4b. Expandable per-version timelines

- A chevron at the right end of the bar expands it into up to three rows (instructor, during-course, after-course) for the selected call, with the version name in its chip tone (as the visibility matrix, `panels/visibility.py:40-60`). The row of the current view is highlighted; clicking a row's tick shows that step in that version (switches the view for the preview, as the top bar does).
- Row length is N_v; rows with a different N get a "numbered separately" note and a tooltip naming the version-dependent macro found (3.3).
- Rendering: without the version-dependence flag no extra compile. With it, the other versions are rendered **in the background** (section 5.1) so they are normally ready when the bar is expanded; if not, the row shows "counting…" and its render is promoted to foreground priority.

### 4c. Editing ticks (phase 3)

Click on a tick toggles step k for version v in the **selected call's position**. Writes go through the deck mutators (`deck_editor.py` stale-check-then-write path, `:645-647`; one undo step each, `:722`; GUI wrapper `actions.edit_deck` as in `visibility.py:_set`, which also refreshes when refused). The tick shows a pending state until the write returns.

Model: at one position the deck holds one or more adjacent calls of the same id; each version has at most one active call there (alternatives, README.md:2961-2964). Let S_v be the new included set.

Rules, in order:
1. **No-op if the text already expresses S_v** (`expand_steps(old spec) == S_v`): round-trip safe.
2. **Call serves only v** (`versions == [v]`): rewrite only its `{steps}`.
3. **Call serves v and other versions**: split. The old call keeps the other versions and its spec text untouched; a new `\slidestep{id}[v]{spec}` is inserted directly after it (same indentation). Versions are written in canonical order (instructor, during-course, after-course).
4. **Call has no `steps`** (`\slide`, `\conditionalslide`): the part for v becomes a `\slidestep` call; the rest stays as the old macro with `versions` reduced (`\slide` for all versions becomes `\conditionalslide[others]`). `set_calls_visibility` already does such conversions (`deck_editor.py:426-449`; `format_call` `:269-281`).
5. **Merge after the edit**: if the changed call now has the same spec as an adjacent call of the same id at this position with disjoint versions, merge into one call with the union of versions. **When every step 1..N_v is ticked again for every version the call serves, revert it to the plain macro it started as** (`\slide` or `\conditionalslide[versions]`; owner decision). The previous macro is recovered from the call that was converted (kept in the edit record for undo) or, when the deck was already a `\slidestep` with all steps, `\conditionalslide` if it had a version list differing from all three, else `\slide`. Not applied to the final-state case of rule 9. Only adjacent calls of this position are touched.
6. **Canonical spec text**: ranges where possible (`1-2,4`); keep an open-ended `m-` if the old spec was open-ended and the set still reaches N_v; tokens that name only steps beyond N_v are preserved verbatim.
7. **Emptying a version** (last tick removed) is refused: that is hiding the slide, which the visibility matrix does. Tooltip points there.
8. **Not editable** (ticks drawn, reason tooltip like `call.readonly_reason`, `visibility.py:68`): pinned versions (`\slideversion`, `\slidefinal`: no `\slidestep` form); slides whose own raw `\begin{frame}<spec>` decides (3.2, a `\slidestep` call has no effect on it); the unparsable-spec / `allowframebreaks` "Page k" fallback; unsaved-buffer N mismatch (4a).
9. **`\SMFinalStateForStudents` slides are editable.** Today every non-instructor version shows only the last overlay page by the flag, and a `\slidestep` call has priority over it (README.md:2998; `\SMOpenFrame`, `Slidemaster_preamble_base.tex:1988`). The student row therefore starts with only the last step ticked (flag state, drawn with a small "flag" marker). The first tick click writes an ordinary `\slidestep{id}[during-course]{spec}` (and/or `[after-course]`) for that version, whose `spec` is the old state (last step N_v) plus or minus the clicked step; from then on that call, not the flag, decides for that version, and the flag in the slide file is left untouched by the edit itself; it is removed silently later, once no deck needs it (4c.1). The row then shows ordinary solid ticks. Un-ticking back to "last step only" does not remove the call (the call is explicit, and the flag could be removed from the slide separately); the tooltip says so. Rule 5 (merge back to the plain macro) does not apply in that case, because a plain `\slide` would restore the flag behaviour, not "all steps".
10. **Version-dependent numbering** (`\conditionalpause`, `\deck*`): editable, with the warning of 3.3(2). The rewrite uses the row version's own numbering, so it is exact; the warning exists because the same step number means different content in different versions, and because a shared call is split by rule 3 (a spec shared between versions with different numbering is always split).

Safety:
- **While a compile runs**: the deck is only read when a compile starts, so the write is safe, but the running full-deck compile's result is then older than the deck; the existing stale marking covers that. The unrestricted preview render does not depend on `steps`, so it is not re-run. Clicks are disabled while a previous tick write is in progress and while an AI task holds the deck (same refusal path as other deck edits).
- **Undo**: one undo step per click via the slide-list undo stack (`deck_editor.py:645-647`). Split/merge is one text replacement over the call lines, so undo restores byte-identical text.
- **Stale file**: refused, with a refresh, if the deck changed on disk meanwhile.

#### 4c.1 Silent removal of `\SMFinalStateForStudents`

When the flag no longer has any function, SlideMage removes it from the slide file **silently** (no prompt). The flag lives in the slide file, so "no longer functional" is judged across **every deck that includes the slide**, not just the open one.

The flag (`Slidemaster_preamble_base.tex:1951-1952,1975-1990`) only acts for non-instructor deck versions (`during-course`, `after-course`; presenter compiles run as instructor) when a frame is opened by `\SMOpenFrame` without a `\SMSlideSteps` value; a `\slidestep` call overrides it (README.md:2998). So it is non-functional exactly when, for **every deck D that calls the slide** (`slide_usage.find_usage`, `slide_usage.py:92`, which includes archived decks and, with `language`, the folded translation slots of `deck_language.deck_slots`), **every call c of it in D**, and **each student version v in {during-course, after-course}**, at least one holds:
1. c is a `\slidestep` call whose versions include v (its `steps` decide, `deck_editor.SlideCall.steps`, `included_in(v)`); or
2. c is not included in v at all (`\conditionalslide`/`\omitslide` without v, `SlideCall.included_in`, `deck_editor.py:103`): the frame is never opened in v; or
3. c is a pinned call (`\slideversion`/`\slidefinal` of a frozen file): it loads another file, so the flag in `current.tex` is irrelevant to it (frozen files keep their own text and are never edited by this rule).

Any plain `\slide` call (or `\conditionalslide` including a student version) in any deck keeps the flag **functional**. A slide that no deck calls is also kept (no usage, nothing proves the flag is dead; a future call would need it). Decks that cannot be scanned (parse error) make the check answer "functional" (never remove on doubt).

When the check runs: after any deck write that creates, converts, removes or retargets a call of that id (tick edits, slide-list "Call as", visibility matrix, delete, Add slide), only for slides whose source contains the flag (cheap text test), in the same background task as the edit's refresh.

Effects of the removal (owner decision: **no version bump, no frozen file**; the rendering is identical in every deck, so it is a no-op edit):
- The line `\SMFinalStateForStudents` (and a comment line that exists only for it) is deleted from the slide's **current** file; nothing else changes. **Frozen version files (`-vM-m-p.tex`) are never read for writing, edited or created by this rule**: decks that pin an older version keep its text, flag included, which is correct for them.
- **No `update_version`, no `freeze_slide`** (so no new patch version; README.md:1166-1167 is not invoked).
- **How the write must go**, because the normal in-app write path would mark the slide as edited and could freeze it: `slide_versioning.save_slide` with default `mark=True` runs `prepare_autosave`, which writes the version line with "+" (`set_marker(..., changed=True)`) and, for a slide that has no "+" and no frozen file for its version yet, **freezes the outgoing text first** (`freeze_slide`, `slide_versioning.py:174-185,211-232`). Both are unwanted here. The removal therefore writes with **`mark=False`** (the path undo and rollback already use: "an earlier text put back exactly", `:211-215`) through the same stale-checked `save_slide_source(..., expected_text=...)`. The version line is left exactly as it was: a "+" the slide already carries stays, no "+" is added, no freeze happens.
- **Would the "+" / "Update version" machinery still flag the slide?** Yes, by two other routes, if nothing is done: (a) `plan_update` calls a slide changed when its content differs from its frozen version (`slide_versioning.py:286-300`, via `_content`, `:280`), and since the frozen file still has the flag line the slide would look edited, and the "Ask about Update Version when leaving a changed slide" flow (v8.22.0) would trigger; (b) `mark_external_edit` (called from `ui/workspace/source_file.py:294`) puts a "+" on a current file whose content differs from its frozen version and has none. **Recommendation: neutralise exactly this difference and nothing else.** In the content comparison used by both (`_content`, `slide_versioning.py:280`), when the frozen text contains the flag line and the current text does not, drop the flag line from the frozen side before comparing (and the reverse is NOT neutralised: adding the flag to a slide is a real behaviour change for students and must still count as a change). The "+" is therefore not acceptable as a side effect of this edit, and no marker is written. A later real edit of the slide behaves as usual (autosave adds the "+", Update version freezes the outgoing text, which by then no longer has the flag in the frozen copy of the *previous* version only).
- **One undo step if possible**: the slide-list undo stack today holds deck text only. Extend its entry for this edit to a composite record: deck text before/after and slide text before/after (no frozen file in it). Undo restores the deck and writes the slide text back with `mark=False`, guarded by `expected_text`, so the slide returns byte-identical including its version line. If the slide changed on disk since (stale), undo reverts the deck part only and tells the user.
- If the flag cannot be removed (file changed meanwhile, protected region, read-only), nothing is written and the flag stays; the next trigger retries.

### 4d. Phases

1. Basic slider: collapsed bar, current view, selected call, ticks, toggle, buffer styling.
2. Expandable per-version rows (read-only), background renders, with the version-dependence scan and per-version renders.
3. Tick editing with the rules of 4c.

## 5. Caching and render cost

- One compile yields all pages. Do **not** use the existing `overlay=N` path for the slider: that is one compile per step.
- Raster: today `prepare_preview` rasterises only the last page at pane width (`slide_snapshot.py:254-278`; `_preview_pngs` LRU of 16 at `:232-251`). For the slider, rasterise all pages once with `preview_raster_client.read_document(pdf, "pdf_images", 1, MAX_PAGES, dpi)` (what `compare_rendered.read_pages` does, `:39-41`; lift it to a shared helper), in the worker of `_run` (`preview_view.py:545`). Show the last step first, rasterise the rest right after or on first slider use. Keep `list[QPixmap]` per cache key, cap `MAX_PAGES=60`, drop with the `_pixmaps` LRU (`preview_view.py:361-388`).
- Cache key for the unrestricted render: source path, mtime, view, language (without steps). `PreviewTarget.key` includes `steps` (`preview_target.py:60`), so add a steps-free key; two calls of the same slide then share one render.
- No snapshot side effects: the unrestricted render must not publish canonical snapshots/thumbnails (`slide_preview.py:528`, `preview_requests.py:104` already skip them when `overlay` is set; add the same condition for the new flag), so snapshots keep showing the deck's own final state.
- A plain `\slide`/`\conditionalslide` target already renders every page, so reuse its PDF: no second compile. Only `\slidestep` targets need the extra unrestricted compile (once per slide edit, via the existing `RenderService` queue).
- Slides with N == 1 pay nothing.

### 5.1 Background renders for the version rows

Goal: the per-version page counts are usually ready before the user expands the bar, without slowing foreground work.

- **What is rendered**: for the selected slide, the unrestricted render of each *other* view (up to two), only for slides the scan flags as version-dependent (3.3). Slides without version logic need none.
- **Where**: a small `BackgroundRenders` scheduler next to `RenderService` (`preview_requests.py`). `RenderService` today only de-duplicates identical in-flight requests by key and starts a thread when someone `wait()`s on a request (`preview_requests.py:39-60,80-120`); it has no priority. The scheduler wraps it: one worker thread, one job at a time, taking jobs from a priority queue (foreground priority 0: any render the user triggered through `PreviewPane._start`; background priority 1: version rows; idle priority 2: neighbour prefetch).
- **Yielding**: before each job, and via the existing `CancelToken` during it (`preview_build.check_cancel`, `preview_requests.py:23-31`), a background job stops when a foreground render is queued or running, and is re-queued (a half-built latexmk run is cancelled; the reusable build cache of `preview_build` keeps most of the work). A foreground render and a background one never run at once, so TeX is never doubled. Compile slot and build locks are the Preview pane's, as for Compare rendered (`compare_rendered.py:5-8`).
- **When started**: ~1.5 s after the pane has shown the selected slide and no foreground render is pending/queued (a `QTimer`, like the 300 ms debounce, `preview_view.py:236-239`), only while the app is not busy with a deck compile (the compile status already exists in `compile_actions`).
- **Limits** (accepted by the owner: selected slide plus 4 neighbours, 1 process): at most 1 background process; look-ahead of the selected slide first, then its neighbours (the 4 nearest rows in the slide list, version-dependent ones only), at most 4 slides per idle period, each at most 2 renders; the whole idle queue is dropped when the user changes slide, selects another view, edits, or types in the editor (cancel on first keystroke if it is a buffer render). Total memory: page lists are kept by the `_pixmaps`-style LRU only for the selected slide; neighbours store only N_v (an int), not images, until they are shown.
- **Invalidation**: key = (source path, mtime, view, language, timestamp setting). A save (mtime change) drops that slide's entries and re-queues the selected slide. Buffer renders are never prefetched. A deck edit never invalidates unrestricted renders (they do not depend on `steps`). A change of the preamble or template (configuration key, `preview_build.configuration_key`) clears all.
- **Disable**: a Settings switch "Prepare version timelines in the background", default on; automatically off on battery saver or when the previous background render took more than 60 s.

## 6. Files to touch

- `src/slidemage/deck_editor.py`: `expand_steps()`; in phase 3 `set_call_steps_for_version(...)` implementing 4c (split, merge, convert, canonical spec), reusing `format_call`, `normalize_steps` and the stale-check path.
- new `src/slidemage/reveal_scan.py` (or in `latex_lint.py`): version-dependence scan of a slide source (3.3).
- `src/slidemage/preview_requests.py`: `BackgroundRenders` scheduler (5.1).
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

- Additional tests (flag removal): non-functional-flag decision table (plain `\slide` in any deck keeps it; `\slidestep` for both student versions removes; `\conditionalslide` excluding a version; pinned call; unused slide keeps it; unparsable deck keeps it; archived deck counts; translation slot counts); the write goes with `mark=False`: version line byte-identical, no "+" added, a "+" already present stays, **no frozen file is created and existing frozen files are byte-identical** afterwards; `plan_update`/`mark_external_edit` do not report the slide as changed after the removal, but do report it when the flag is **added**; one undo restores deck and slide bytes; stale slide refuses.
- Additional tests: frame-spec parsing (`<2-4>`, `<1,3->`, unparsable) and page-to-overlay mapping; slide with a raw `\begin{frame}<2-4>`: override gives pages = overlays, `\slidestep` shows no effect and ticks are read-only; final-state student row: first click writes a `\slidestep` call and the flag line is untouched; all-ticked reverts to the plain macro and undo restores bytes; background scheduler: a foreground request cancels and requeues a running background job, only one process at a time, invalidation on save, none for buffer renders, off in transcript/presenter.

## 8. Open questions for the owner

Decided: scope per call; opens on the last step; buffer renders get dashed ticks; student `\SMFinalStateForStudents` rows and version-dependent rows are editable; the flag is removed silently when no deck needs it (4c.1); fully ticked reverts to the plain macro; background renders (selected slide plus 4 neighbours, 1 process); hidden in transcript and presenter views; per-version numbering (not a master list, 3.5).

Open research item (the owner is being briefed separately):
1. The optional cross-version "alignment hint" for `\conditionalpause`-only slides (3.5, instrumentation in the preamble).

To confirm by experiment before building:
2. Does `\beamer@whichframes` override a raw `\begin{frame}<spec>`, and does `\slidestep` really have no effect on a raw frame (3.2)?

## Implementation notes and results

Experiments (2026-10-18, scratch project copied from `example/`):
- A raw `\begin{frame}<2-3>` emits only its own overlays (2 pages); `\gdef\beamer@whichframes{1-}` (the `all_steps` line) makes it 4 pages, page k = overlay k. Confirmed.
- `\slidestep` (`\SMSlideSteps`) restricts `standardframe` (1 page for `{1}`) but has **no effect on a raw `\begin{frame}<spec>`**, as planned; the `1-` override beats both and the final-state flag. So the plan's parsing of the slide's own spec is only used to *mark* steps the slide itself drops (crossed ticks), not to number pages.
- `\conditionalpause`: 2 pages instructor, 1 page during-course. Confirmed with real TeX (`tests/test_reveal_steps_tex.py`).

Design changes while building:
- No pass over the slide's frame spec is needed for numbering: the all-steps render makes page k = step k always, so "Page k" fallbacks exist only for `allowframebreaks` slides (bar marks them unreliable).
- The bar's status text is an elided label ("Step 3 of 5 · in During"), the version names are toggle chips; the bar is two lines so it fits narrow Preview panes.
- Neighbour look-ahead counts the steps of the current view only (4 slides), not of other versions.

Phase 3 (tick editing) as built, and where it differs from 4c:
- Rule 5's "revert to the plain macro" goes only to `\slide`, and only when the place serves all three versions with every step. A lone `\slidestep[V]` does nothing in the other versions (no frame-counter step) while a `\conditionalslide[V]` steps the counter, so turning one into the other would renumber the frames of the other versions. For the same reason a `\conditionalslide` that is not in every version is **read-only** in the bar, with the reason "use Call as -> Reveal steps first"; nothing is converted silently.
- The place of a call is the run of `\slidestep` calls of the same slide with only blank or comment lines between them (`deck_editor.step_block`); a plain `\slide` stands alone. The rewrite works on that block: the versions are regrouped by the steps each typesets, calls that already say exactly the right thing stay byte for byte, the first replaced call is changed in place (a trailing comment survives), further groups follow as new lines with the same indent and line ending.
- Runs of two steps are written `1,2`, longer runs `1-3`, as the README shows; an open `2-` stays open while the set still reaches the end.
- The page lists are keyed without the call's macro, versions or steps (`target.key[1:3] + target.key[5:]`), so an edit of the deck does not throw the counted steps away.
- The flag clean-up (4c.1) runs after tick edits and after the slide list's variant and visibility edits (`SlideList._flag_cleanup`). It writes through `slide_versioning.save_slide(mark=False)`: no "+", no freeze; the backup copy under `slides/.backups/` that every write of a slide makes still happens. `slide_versioning._changed_since` ignores exactly one difference between a slide and its frozen version: the flag line present in the frozen text and gone from the current one, so `plan_update` and `mark_external_edit` do not call the slide changed. The undo record is a `str` subclass (`DeckUndo`) carrying the slide's text before and after, so existing undo stacks and tests keep seeing plain strings.
- Not done: refusing tick edits while an AI task holds the deck (the slide list has no such flag to ask; a stale deck file is refused by the ordinary stale check).

## Changelog draft

- Preview: a reveal-step bar under the slide: slider, tick marks for the steps the selected deck call includes, "Deck steps only", dashed ticks for editor-buffer renders, keyboard stepping, a slide opens on its last step; expandable into one timeline per deck version.
- Reveal steps are counted by an all-steps render in the background while the Preview is idle (selected slide plus 4 neighbours, one process, never during a render of your own).
- Preview step bar, ticks of each version editable: click a tick to add or remove that step for that version; the deck's `\slidestep` calls are split, merged or created as needed, one Undo step per click.
- `\SMFinalStateForStudents` is taken out of a slide automatically once every call of it in every deck overrides it or skips the student versions (no new version, no "+", no frozen file; Undo restores it).
