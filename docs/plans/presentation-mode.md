# Presentation mode: presenting a deck from SlideMage

Status: plan only, no code written. Branch `claude/plan-presentation-mode-9d1ca5`.

## 1. Licence check (done before any pympress code was read)

* **pympress** is licensed **GPL-2.0** (`LICENSE.txt`: "GNU GENERAL PUBLIC LICENSE Version 2, June 1991"). Only the licence text was read; no pympress source file was opened.
* **SlideMage** is licensed **CC BY-SA 4.0** (`LICENSE`: free to share and adapt, even commercially, with attribution and share-alike, "no additional restrictions").
* Consequences:
  * GPL is strong copyleft. Copying or adapting pympress code would make the combined work a GPL derivative, so GPLv2 would have to cover the whole of SlideMage. That collides with the CC BY-SA terms: CC BY-SA 4.0 is one-way compatible only with GPLv3, not with GPLv2-only code, and adapted code could not be relicensed.
  * It would close off closed-source or dual-licensed distribution, and any later relicensing would need the consent of every pympress contributor.
* **Verdict: copyleft, so pympress implementation code must not be read or adapted.** This plan rests only on pympress's user-facing behaviour (current slide, next slide, notes, timer, as the README of SlideMage already describes it) and on my own design from Qt and MuPDF knowledge. The implementer must follow the same rule (also for pdfpc, which is GPL too). Ideas and feature lists are not copyrightable; code and its structure are.
* Libraries SlideMage already uses are separate: PySide6 is LGPL. **pymupdf is AGPL/commercial**, already a dependency, so nothing new, but it matters for any closed-source release (open question 9).

## 2. How SlideMage builds the presenter PDF (findings)

* `compiler.CompileJob.presenter=True` (compiler.py ~l.489); `wrapper_text` defines `\def\SMPresenterModeOverride{1}` (~l.588). File name: `<deck>[-<version>]-presenter.pdf`, in practice `<deck>-instructor-presenter.pdf`.
* Location: `ctx.pdf_dir` (the project's `pdf/`), unless the deck declares `\deckoutputfolder[presenter]{...}` (folder or full file name). `compiler.resolve_output_location(ctx, job)` resolves it, and **`compiler.deck_pdfs(ctx, deck)`** already lists every PDF on disk for a deck with labels (the presenter one is labelled "Presenter", language variants add " · DE"). Snapshots keep their PDFs inside the snapshot.
* Content (`latex/Slidemaster_preamble_base.tex` ~l.2574-2700): `pgfpages` + `\setbeameroption{show notes on second screen=right}` + the `gothampresenter` note-page template. **Every PDF page is one double-width page: slide on the left, note page (breadcrumb + `\insertnote`, no thumbnail) on the right.** Each beamer overlay (`\pause`, `<2->`) is its own page, as in a normal PDF. Instructor-version content only.
* Preview/snapshot refresh is deliberately skipped for presenter jobs, so nothing in the preview cache can be reused.
* Today the preview's "Presenter PDF" item (`ui/workspace/preview_view.py`, `render_buffer(presenter=True)`) only compiles/opens it; README "Presenting live" recommends pympress. There is no in-app presenter.
* **PDF rendering today:** PyMuPDF (`pymupdf`, already a dependency), with MuPDF kept in a private raster process for previews (`preview_raster.py`). **QtPdf is not used anywhere and `from PySide6 import QtPdf` fails on this machine**, so the plan uses PyMuPDF and adds no dependency.
* Entry points today: commands are registered in `ui/workspace/actions.py` (e.g. `open_pdf`, l.239) and laid out by `ui/workspace/menus.py`; deck handlers live in `ui/workspace/deck_actions.py`.

## 3. Decision: presenter PDF alone, or paired with the normal PDF?

**Use the presenter PDF alone**: slide = left half of page *n*, notes = right half of page *n*, "next" = left half of page *n+1*.

Why:
* The normal PDF may be missing, stale, or built from a different state (partial compiles, language variants, per-chapter outputs). Pairing needs page counts and overlay structure to match, and nothing guarantees it. One file is self-consistent: slide and note belong together by construction.
* The owner's flow already is "compile Presenter"; a single input keeps the fallback logic to one case (section 4.9).
* Cost: the audience image is a clip of a double-width page, which MuPDF does natively with vector quality (`clip=`). Notes are shown as the rendered right half (typeset as authored, math and all); plain text via `page.get_text(clip=...)` stays possible later (M4).
* Rejected: normal PDF for slides plus presenter PDF only for notes. Marginally different pixels are not worth the sync risk.
* Check in M0: pgfpages may scale the logical page, so the slide half need not be exactly page-width/2. Derive the slide and note rectangles from the page geometry, tested against a real compile.

## 4. Architecture

### 4.1 New files

Non-UI, `src/slidemage/presentation/` (testable without a display):

| File | Content |
|---|---|
| `pdf_source.py` | `PresentationDeck`: opens the PDF; `page_count`, `slide_rect(page)`, `notes_rect(page)`, `render(page, part, size_px) -> QImage`, `links(page)` (rects in normalized slide units, kind, target), named destinations -> page, slide ids/titles for the jump list. |
| `renderer.py` | One worker thread owning the MuPDF document (MuPDF objects never cross threads, the rule `preview_raster.py` states). LRU cache keyed `(page, part, w, h, dpr)`, prefetch of page±1, invalidation on resize/DPI change. |
| `session.py` | `PresentationSession(QObject)`: current page, black/white flag, laser position, strokes, timer state; signals `page_changed`, `blank_changed`, `pointer_moved`, `strokes_changed`. **Single source of truth both windows listen to.** All coordinates normalized to the slide (0..1). |
| `screens.py` | `choose_screens(screens, preferred) -> ScreenPlan(presenter, audience or None)`, mirror detection (4.3); pure function over QScreen-like data, tested with fakes. |
| `locate.py` | `find_presenter_pdf(ctx, deck) -> (DeckPdf or None, stale: bool)` using `compiler.deck_pdfs`. |

UI, `src/slidemage/ui/presentation/`:

| File | Content |
|---|---|
| `slide_canvas.py` | `SlideCanvas(QWidget)`: paints the rendered slide letterboxed, then the overlay layer (laser dot, strokes) from the session. Used by the audience window, the current view and the next view (overlay off for the latter). |
| `audience_window.py` | Frameless black window, `showFullScreen()` on the audience screen, hidden cursor, keys forwarded to the controller. |
| `presenter_window.py` | Large next-slide view (left, ~65%); right column: small current-slide view (clickable, pointer, drawing) with the notes view below (scrollable image scaled to column width); top bar with timer, clock, "slide n / N"; tool buttons. |
| `controller.py` | `PresentationController`: builds the session, picks the screen plan, opens/closes windows, watches `screenAdded/Removed`, owns the key table. |
| `link_handler.py` | Hit-testing clicks against page links. |

Touched files:
* `ui/workspace/actions.py`: command `present` ("Present deck", DECK group, `F5`, `enabled=_active_deck`) beside `open_pdf`; `present_from_here` (`Shift+F5`, M3). Handler `deck_actions.on_present(window, deck)`.
* `ui/workspace/menus.py`: add `present` to the ⋮ "This deck" section and the Compile caret menu; ⌘K picks it up from the registry.
* `ui/workspace/preview_view.py`: "Present" beside the "Presenter PDF" item (M3, optional).
* `app_settings.py` and the settings dialog: preferred audience screen, timer target, laser/pen colours.
* `README.md` ("Presenting live": built-in mode first, pympress as an alternative), `CHANGELOG.md`, `version.py` per the repo's bump routine. No change to the LaTeX template in the MVP.

### 4.2 PDF rendering
PyMuPDF in `renderer.py`: `page.get_pixmap(matrix, clip=rect, alpha=False)` -> `QImage` (copy). Render at `widget size × devicePixelRatio`. On a page change render the audience image first, then current, next, notes; prefetch neighbours. Keep an LRU of ~10 pages (a 1080p RGB image is ~6 MB; do not pre-render the whole deck). Measure on slides with heavy TikZ in M1.

### 4.3 Windows and screen detection (QScreen)
* `QGuiApplication.screens()`. Presenter window on the screen holding the SlideMage window (else primary); audience window on another screen.
* `choose_screens` rules:
  1. fewer than 2 screens -> audience-only mode;
  2. mirrored/duplicated -> audience-only mode. On Windows and macOS a duplicated display normally appears to Qt as **one** QScreen, so rule 1 covers it. Where a mirror appears as two screens (X11/Wayland), treat screens with identical `geometry()` (origin included), or `virtualSiblings()` members with identical geometry, as one screen;
  3. otherwise the audience is the first screen that is not equivalent to the presenter screen; the setting "Audience screen" (stored by `name()` + `serialNumber()`) overrides, with a chooser when 3+ screens exist.
* Audience-only mode: one full-screen `SlideCanvas` on the main window's screen with the same keys, a toast "Only one screen: showing the slide full-screen" and (M3) key `F` to swap into presenter layout.
* Hot-plug (M3): re-plan on `screenAdded/Removed` and `geometryChanged`.
* Windows: set `setScreen(audience)` and `setGeometry(screen.geometry())` before `showFullScreen()` (otherwise it can land on the wrong monitor); render each window with its own `devicePixelRatio` (mixed 100%/150% scaling). Optional (M3): `SetThreadExecutionState` via ctypes to block sleep, guarded by `sys.platform`.

### 4.4 Keyboard and clicker controls
Both windows forward keys to the controller, which uses one table. Clickers send PageUp/PageDown, sometimes arrows, `.`, F5, Esc.

| Key | Action |
|---|---|
| Right, Down, PageDown, Space, Enter | next page (reveal step or slide) |
| Left, Up, PageUp, Backspace | previous page |
| Home / End | first / last |
| digits + Enter | jump to slide/page number (typed number shown in the bar) |
| G | slide grid in the presenter window (M3) |
| B or `.` | toggle black screen (any navigation also restores) |
| W or `,` | white screen |
| L | laser on/off (M2) |
| D / E / C / Ctrl+Z | pen on/off, eraser, clear, undo stroke (M2) |
| Alt+Left | back to where a link jump started (M2) |
| T / Shift+T | reset / pause timer |
| Esc | first closes overlays and clears drawing; then exits (confirmation only if a timer is running, see open question 3) |

MVP "next" steps one PDF page at a time (each reveal step is a page); M3 adds "next slide, skipping reveal steps".

### 4.5 Timer and clock
`QTimer(1000)` in the session; elapsed time since the first forward navigation (or a Start button), pause/reset, wall clock, optional countdown to a target duration with amber at 5 min and red at 0. Based on an injectable monotonic clock for tests.

### 4.6 Reveal steps / overlays
One PDF page per overlay; the page index is the state. To show "slide 12/40, step 2/4" the frame grouping is needed. In preference order: (a) the `\hypertarget{<slide id>}` that `\setSlideID` plants for every slide (README: "every real slide is a jump target"): `doc.resolve_names()` maps ids to pages, pages between two ids are the steps, and the ids give titles for the jump list; (b) page labels or the footer frame number if M0 shows them readable; (c) fallback "page n / N". Check in M0 that ids exist for non-`\slide` frames.

### 4.7 Link handling
* A click on the current-slide view is converted to normalized slide coordinates and tested against `page.get_links()` (rects converted with the same transform as the rendering). Internal links (GOTO/NAMED, used by SlideMage's non-linear navigation and generated appendix) jump the session to the target page, with "back" (Alt+Left) to return. External URIs: confirm (setting can disable), only `http(s)`/`mailto`, via `QDesktopServices.openUrl`; local file links always prompt. The audience screen shows nothing for a URL.
* Pointing-hand cursor over a link; optional faint link rectangles on `K`.
* **Risk:** pgfpages re-places the logical page, so annotation rectangles may be off. M0 tests one real deck (URL, internal link, appendix link). Fallback if broken: take link rectangles from the normal PDF at the same page index, for this feature only.

### 4.8 Laser pointer and drawing, synced to the audience
* The session owns `pointer` and `strokes` (normalized coordinates); both windows paint from it in the same process and Qt thread, so syncing is just a signal.
* The current-slide view converts mouse moves (through its letterboxed slide rectangle) into `session.set_pointer(x, y)` (laser on) or stroke points (pen on, button down). Leaving the view hides the dot.
* Painting in `SlideCanvas.paintEvent` over the cached slide image: antialiased polylines, points added only when moved ≥1 px; laser = red disc with halo, sized as a fraction of slide height so it looks the same on both screens; highlighter = wide semi-transparent stroke. Use `update(dirtyRect)` for pointer moves.
* Strokes belong to a page and clear on navigation by default; setting "keep drawings per slide" stores `dict[page, strokes]`.
* The audience window ignores the mouse, except in audience-only mode where it also accepts laser/pen.

### 4.9 Decks without a compiled presenter PDF
`on_present` calls `locate.find_presenter_pdf` and handles:
1. **None:** dialog "No presenter PDF yet": **Compile and present** (run `CompileJob(deck, version, None, presenter=True)` through the existing compile controller, `ui/workspace/compile_controller.py`/`compile_actions.py`, and start when it succeeds), **Present the normal PDF without notes** (single-width pages, `notes_rect = None`, the next-slide view stays, the notes area shows "No notes in this PDF"), or Cancel.
2. **Stale** (older than the deck sources or the instructor PDF): "Recompile first / Present anyway".
3. **Not a presenter layout** (page not ~2× a 16:9/4:3 slide ratio; exact test from M0): treat as a normal PDF (case 1, second option).
4. Several presenter PDFs (language variants): ask once, as "Open pdf" does.
No automatic compile without asking; compiles are slow and visible.

## 5. Milestones

* **M0 spike (≈0.5-1 day).** Compile a real deck with Presenter; measure page size, the slide and note rectangles, whether the note appears on every overlay page, link rectangles, named destinations for slide ids. Append findings to this file. Gate for M2 and for 4.6.
* **M1 MVP (≈3 days).** `pdf_source`, `renderer`, `session`, `screens`, `locate`; audience and presenter windows (large next, small current, notes, page counter, timer, clock); key table with next/prev/first/last/black/white/jump-by-number/exit; `present` command and menu entries; no/stale PDF dialogs; single-screen and mirrored fallback; tests.
* **M2 interaction (≈2-3 days).** Link clicks (internal jump with return, external with confirmation), laser, pen/highlighter with undo/clear, all synced to the audience; colour settings.
* **M3 polish.** Slide grid/jump list with titles, "skip reveals", hot-plug, countdown colours, keep-awake, audience chooser, `present_from_here`, remember layout.
* **M4 optional.** Notes as text with adjustable size, per-slide timing log, phone remote.

## 6. Test approach

pytest with `QT_QPA_PLATFORM=offscreen` (already set in `tests/conftest.py`, `qapp` fixture). New: `tests/test_presentation_source.py`, `_session.py`, `_screens.py`, `_gui.py`.
* **Fixture PDF without LaTeX:** build a small presenter-like PDF with `pymupdf` in the test (6 double-width pages: left half a coloured block with the number, right half "note n", `insert_link` for a URI and an internal link). Deterministic; no TeX needed. An optional test on a real compiled PDF skips when absent.
* `pdf_source`: split rectangles, sampled colours of both halves, link normalization, destination -> page.
* `session`: bounds, black/white, jump by number, link jump and return, timer with injected clock, strokes/pointer, signals.
* `screens.choose_screens` with fakes: 1 screen, 2 distinct, 2 identical geometry (mirror), 3 screens with a preferred name, preferred screen missing.
* GUI (offscreen): controller creates two windows for two fake screens and one for one; `QTest.keyClick` changes the page in both canvases; a mouse move over the current view puts the pointer at the same normalized spot on the audience canvas (check via `grab()` pixel sampling); a link click jumps; Esc closes windows and joins the render thread without leftovers.
* Not covered offscreen, manual checklist in the PR: real second monitor placement, duplicate mode, hot-plug, clicker keys, projector smoothness.

## 7. Risks

1. Link geometry in pgfpages output (4.7), decided by M0.
2. The note may not appear on every overlay page of a frame; mitigation: show the note of the nearest page of the same frame (needs 4.6).
3. Very long notes are cut at the bottom of the note page (README already warns); the viewer cannot fix it.
4. MuPDF threading and crashes: one owner thread (or reuse the raster process); render failures show a placeholder instead of crashing a live show.
5. Render latency for 4K or heavy TikZ slides: cache and prefetch; measure in M1.
6. Windows full-screen quirks (wrong monitor, mixed DPI): see 4.3; needs the owner's real setup.
7. Mirror detection is heuristic off Windows; the audience-screen setting is the escape hatch.
8. Clicking URLs during a live show: confirm first.
9. Template changes (`gothampresenter`) can shift the split: keep detection geometric, covered by a LaTeX-free test.
10. Licence hygiene: nothing from pympress/pdfpc (section 1).

## 8. Open questions for the owner

1. When the presenter PDF is missing or stale: compile automatically (one click) or always ask first? (Plan: ask.)
2. "Next" = next reveal step (page) or next slide? (Plan: page, with a skip-reveals option later.)
3. Esc: end at once, or confirm when a timer is running?
4. Drawings: clear on every slide change, or keep per slide during the session? (Plan: clear.)
5. Timer: count up only, or a target duration with countdown and end time?
6. Laser: toggle with `L` (plan, so link clicks stay unaffected), or always while the mouse is over the small view?
7. Is it fine that notes and next-slide need the presenter PDF, with a "no notes" fallback for a normal PDF?
8. Which OS and projector setups matter (Windows only, or macOS too; duplicate-mode projectors)?
9. pymupdf is AGPL: acceptable for your distribution plans? If a closed-source release is ever planned, `renderer.py` is the one place to swap the engine (QtPdf or pdfium), but links and named destinations would then need their own source.
10. Should the audience screen show anything beyond the slide (slide number, clock)? (Plan: nothing.)
