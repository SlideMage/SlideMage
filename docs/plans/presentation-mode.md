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
| `session.py` | `PresentationSession(QObject)`: current page (what the presenter sees), the audience state (`black` flag, `frozen_page` or none, hence `audience_page`, see 4.12), laser position, strokes per page; signals `page_changed`, `audience_changed`, `pointer_moved`, `strokes_changed`. **Single source of truth both windows listen to.** All coordinates normalized to the slide (0..1). |
| `screens.py` | `choose_screens(screens, preferred) -> ScreenPlan(presenter, audience or None)`, mirror detection (4.3); pure function over QScreen-like data, tested with fakes. |
| `locate.py` | `find_presenter_pdf(ctx, deck) -> (DeckPdf or None, stale: bool)` using `compiler.deck_pdfs`. |
| `layout.py` | Layout profile model: the split tree, element names, JSON load/save/validate, the built-in profiles (4.10). No Qt widgets. |
| `timer.py` | `PresentationTimer`: optional end-time or duration countdown with start/pause/reset and an injectable clock (4.5). |
| `settings.py` | `PresentationSettings` dataclass (colours, link confirmation, timer defaults, audience screen, active profile) read/written through `app_settings` (4.11). |

UI, `src/slidemage/ui/presentation/`:

| File | Content |
|---|---|
| `slide_canvas.py` | `SlideCanvas(QWidget)`: paints the rendered slide letterboxed, then the overlay layer (laser dot, strokes) from the session. Used by the audience window, the current view and the next view (overlay off for the latter). |
| `audience_window.py` | Frameless black window, `showFullScreen()` on the audience screen, hidden cursor, keys forwarded to the controller. |
| `presenter_window.py` | The presenter screen. It owns no fixed layout: it builds its content from the active layout profile (4.10) through `layout_view.py` and can rebuild it when another profile is picked. |
| `layout_view.py` | Turns a profile (split tree) into nested `QSplitter`s and element widgets: current-slide view, next-slide view, notes view, clock, timer, slide counter, toolbar. |
| `controller.py` | `PresentationController`: builds the session, picks the screen plan, opens/closes windows, watches `screenAdded/Removed`, owns the key table. |
| `link_handler.py` | Hit-testing clicks against page links. |
| `settings_page.py` | The "Presentation" page of the settings dialog, including the profile editor with preview (4.11). |

Touched files:
* `ui/workspace/actions.py`: command `present` ("Present deck", DECK group, `F5`, `enabled=_active_deck`) beside `open_pdf`; `present_from_here` (`Shift+F5`, M3). Handler `deck_actions.on_present(window, deck)`.
* `ui/workspace/menus.py`: add `present` to the ⋮ "This deck" section and the Compile caret menu; ⌘K picks it up from the registry.
* `ui/workspace/preview_view.py`: "Present" beside the "Presenter PDF" item (M3, optional).
* `app_settings.py` and `ui/dialogs/settings.py`: a new "Presentation" page (4.11); the values live in `PresentationSettings`.
* `README.md` ("Presenting live": built-in mode first, pympress as an alternative), `CHANGELOG.md`, `version.py` per the repo's bump routine. No change to the LaTeX template in the MVP.

### 4.2 PDF rendering
PyMuPDF in `renderer.py`: `page.get_pixmap(matrix, clip=rect, alpha=False)` -> `QImage` (copy). Render at `widget size × devicePixelRatio`. On a page change render the audience image first, then current, next, notes; prefetch neighbours. Keep an LRU of ~10 pages (a 1080p RGB image is ~6 MB; do not pre-render the whole deck). Measure on slides with heavy TikZ in M1.

### 4.3 Windows and screen detection (QScreen), per platform
Windows, macOS and Linux (X11 and Wayland) are all required.

Common logic (`screens.choose_screens`, pure and tested with fakes):
1. Presenter window on the screen holding the SlideMage window (else primary); audience window on another screen.
2. Fewer than 2 screens -> audience-only mode.
3. Mirrored/duplicated -> audience-only mode (per-platform detection below).
4. Otherwise the audience is the first screen not equivalent to the presenter screen; the setting "Audience screen" (stored by `name()` + `serialNumber()`) overrides it, with a chooser when 3+ screens exist.
5. Audience-only mode: one full-screen `SlideCanvas` on the main window's screen, same keys and mouse wheel, toast "Only one screen: showing the slide full-screen"; key `Tab` swaps into the presenter layout and back (M3); `B` works, `F` (freeze) is disabled there because presenter and audience are the same screen.
6. Hot-plug (M3): re-plan on `screenAdded/Removed` and `geometryChanged`. Render each window with its own `devicePixelRatio` (mixed scaling).

| | Windows | macOS | Linux X11 | Linux Wayland |
|---|---|---|---|---|
| Mirror seen by Qt as | one QScreen (duplicate mode) | one QScreen when "Mirror Displays" is on | usually two screens with identical geometry (xrandr `--same-as`) | compositor-dependent: often two outputs with identical geometry, sometimes one |
| Detection | rule 2 | rule 2 | identical `geometry()` (origin too), or `virtualSiblings()` with identical geometry | same geometric test; the manual setting is the fallback |
| Full screen on the audience screen | `setScreen()` + `setGeometry(screen.geometry())` before `showFullScreen()` (else it can land on the wrong monitor) | frameless window sized to the screen rather than native full screen (native full screen creates a Space; with "Displays have separate Spaces" on it can blank the other screens); hiding Dock and menu bar needs a small `NSApplicationPresentationOptions` helper (M3) | frameless, `setGeometry`, `showFullScreen()`; window-manager dependent | **clients cannot position windows**; `move()`/`setGeometry()` is ignored. Set `windowHandle().setScreen(s)` before showing, then `showFullScreen()`, which Qt turns into a fullscreen-on-output request; compositor support must be verified |
| Keep awake (M3) | `SetThreadExecutionState` via ctypes | `caffeinate -d` subprocess or an IOKit assertion | `org.freedesktop.ScreenSaver.Inhibit` over D-Bus | `org.freedesktop.portal.Inhibit` |

Wayland specifics: the presenter window cannot be placed on a chosen screen; it opens where the compositor puts it (normally the main window's screen), and the user moves it if needed (documented). Only the audience window is placed, via the fullscreen-output request. If a compositor ignores that, show a hint "Move the audience window to the projector, then press F11", and treat two windows on one screen as audience-only. The XWayland platform (`QT_QPA_PLATFORM=xcb`) is not relied on.

Manual test per platform (checklist in the PR): (a) laptop plus one projector in extended mode: audience on the projector, presenter on the laptop; (b) duplicate mode: only the full-screen slide appears; (c) single screen; (d) unplug and replug the projector mid-show (M3); (e) mixed scaling (100% + 150%); (f) Windows 11, macOS (an external display), Ubuntu GNOME on Wayland and on X11, KDE if available; (g) clicker keys and the mouse wheel.

### 4.4 Keyboard, mouse wheel and clicker controls
Both windows forward input to the controller, which uses one table. Clickers send PageUp/PageDown, sometimes arrows, `.`, F5, Esc.

| Input | Action |
|---|---|
| Right, Down, PageDown, Space, Enter | next page |
| Left, Up, PageUp, Backspace | previous page |
| Mouse wheel down / up | next / previous page, in the presenter window (any view) and on the audience screen in audience-only mode. One page per wheel notch; touchpad deltas are accumulated to a threshold of 120 `angleDelta` units, so one swipe does not skip many pages |
| Home / End | first / last |
| digits + Enter | jump to slide/page number (typed number shown in the bar) |
| G | slide grid in the presenter window (M3) |
| B or `.` | black out the projector; pressing it again, or any navigation, restores it (4.12) |
| F | freeze / unfreeze the projector (4.12); navigation does not unfreeze |
| Tab | audience-only mode: swap between full-screen slide and presenter layout (M3) |
| Ctrl + left mouse button held on the current-slide view | laser pointer while held (M2; 4.8) |
| D / E | pen on/off, eraser (M2) |
| T / Shift+T | timer start-pause / reset (4.5; only when a timer is configured) |
| P | cycle to the next layout profile (M3) |
| Ctrl+Z | undo last stroke on this page (M2) |
| Delete or the Clear button | clear drawings of this page; Shift+Delete clears all pages (M2) |
| Alt+Left | back to where a link jump started (M2) |
| Esc | ends the presentation immediately, no confirmation |

"Next" always advances to the next reveal step, which is the next PDF page. "Skip reveals" is not planned (an optional idea only).

### 4.5 Clock and timer (both optional, presenter window only)
Both are elements of the layout profile (4.10): if the active profile does not contain them, nothing is drawn and no timer runs. Neither ever appears on the audience screen.

**Clock.** Read-only label with the current time, `QLocale` format (24 h or 12 h by system locale; settings can force one), updated by a 1 s `QTimer`. No state.

**Timer.** Two modes, set in the timer element and defaulted in the settings page (4.11):
* **End time of day (default).** The presenter enters e.g. 11:45. The timer shows the remaining time until then (and the target time in small text) and needs no start: it counts from the moment it is set. If the entered time has already passed today it is rejected with a hint (open question 5).
* **Duration.** The presenter enters e.g. 45 min. It starts on the first forward navigation (setting "Start on first slide change", default on) or via Start; **T** starts/pauses, **Shift+T** resets to the full duration and stops. Pause freezes the remaining time.
* Setting it: click the timer element (or the toolbar button) to open a small popover with the mode switch, a time or minutes field and OK/Clear. The settings page holds the defaults (mode, default end time offset or duration); the last used value is remembered but never auto-started.
* **Flashing:** when the remaining time reaches 0 the timer element flashes red (background alternating red / normal at 1 Hz) for 10 s, then stays solid red and counts the overrun as "+mm:ss". Settings: "Flash when time is up" (on by default), "Solid red only" for people who dislike flashing (also chosen automatically when the OS asks for reduced motion). An optional amber warning at 5 min remaining (setting, default on). The flash is a repaint of the presenter element only: it never touches the audience window.
* Logic lives in `presentation/timer.py` with an injected monotonic clock and a `now()` for the time of day, so all of it is unit-testable without waiting.
* Fully optional: no timer element in the profile, or the timer left unset, means no timer exists and nothing runs.

### 4.6 Reveal steps / overlays
One PDF page per overlay; the page index is the state. To show "slide 12/40, step 2/4" the frame grouping is needed. In preference order: (a) the `\hypertarget{<slide id>}` that `\setSlideID` plants for every slide (README: "every real slide is a jump target"): `doc.resolve_names()` maps ids to pages, pages between two ids are the steps, and the ids give titles for the jump list; (b) page labels or the footer frame number if M0 shows them readable; (c) fallback "page n / N". Check in M0 that ids exist for non-`\slide` frames.

### 4.7 Link handling
* A click on the current-slide view is converted to normalized slide coordinates and tested against `page.get_links()` (rects converted with the same transform as the rendering). Internal links (GOTO/NAMED, used by SlideMage's non-linear navigation and generated appendix) jump the session to the target page, with "back" (Alt+Left) to return. External URIs: confirm (setting can disable), only `http(s)`/`mailto`, via `QDesktopServices.openUrl`; local file links always prompt. The audience screen shows nothing for a URL.
* Pointing-hand cursor over a link; optional faint link rectangles on `K`.
* **Risk:** pgfpages re-places the logical page, so annotation rectangles may be off. M0 tests one real deck (URL, internal link, appendix link). Fallback if broken: take link rectangles from the normal PDF at the same page index, for this feature only.

### 4.8 Laser pointer and drawing, synced to the audience
* The session owns `pointer` and `strokes` (normalized coordinates); both windows paint from it in the same process and Qt thread, so syncing is just a signal.
* **Laser pointer: Ctrl + left mouse button held on the current-slide view.** The dot follows the mouse while both are held and disappears when either is released or the mouse leaves the view. There is no toggle key. The current-slide view decides on **button press**, in this order: (1) Ctrl held -> laser mode for this press (never a link click, never a stroke); (2) else pen tool on -> stroke; (3) else a plain press-and-release without movement beyond a few pixels -> link click (4.7). So a plain click still follows links, and Ctrl never conflicts with the pen, because Ctrl wins at press time. Link activation happens on release only if the press was not a laser/stroke press. If Ctrl is released while the button is still down the laser ends (the dot disappears) and the rest of that press is ignored. The pointer stays in `session.set_pointer(x, y)` (normalized, through the letterboxed slide rectangle) and is cleared by `session.clear_pointer()`.
* **macOS note:** Qt maps the Command key to `Qt::ControlModifier` by default (Ctrl and Meta are swapped), and a physical Ctrl+click is turned into a right click by the OS. The code therefore tests `ControlModifier` through Qt and the docs say "Ctrl (⌘ on macOS)"; manual test on a Mac (open question 3).
* Pen: with the pen tool on, a press without Ctrl starts a stroke.
* Painting in `SlideCanvas.paintEvent` over the cached slide image: antialiased polylines, points added only when moved ≥1 px; laser = disc in the configured laser colour (default red) with halo, sized as a fraction of slide height so it looks the same on both screens; highlighter = wide semi-transparent stroke in the configured pen colour. Use `update(dirtyRect)` for pointer moves.
* **Drawings persist per page for the whole session.** The session keeps `strokes: dict[page, list[Stroke]]`; going back to a page shows its drawings again on both screens. They are discarded only when (a) the presented deck changes or its PDF is reloaded (a new `PresentationSession`), (b) the presentation ends, or (c) the user clears them.
* **Clear interaction (proposal):** a visible **Clear** button in the presenter toolbar (shortcut Delete) clears the drawings of the current page; Shift+Delete or Shift-clicking the button clears every page; Ctrl+Z undoes single strokes. Why this and not "click somewhere": a plain click on the slide is already link activation, and with the pen tool a click starts a stroke. A click on the area outside the slide (letterbox margin or notes column) would be easy to hit by accident and invisible to a new user. A button plus a key is unambiguous, cannot conflict with links or the pen, and is quick to reach. Optional extra (M3): right-click on the current-slide view clears that page, since right-click has no other use there.
* The audience window ignores mouse buttons, except in audience-only mode where it also accepts the wheel, Ctrl+left laser and the pen. **The audience screen shows only the slide plus laser and drawings**: no clock, timer, counter or toolbar there; everything else is defined by the profile in the presenter window.

### 4.9 Decks without a compiled presenter PDF
`on_present` calls `locate.find_presenter_pdf` and handles:
1. **None:** dialog "No presenter PDF yet": **Compile and present** (run `CompileJob(deck, version, None, presenter=True)` through the existing compile controller, `ui/workspace/compile_controller.py`/`compile_actions.py`, and start when it succeeds), **Present the normal PDF without notes** (single-width pages, `notes_rect = None`, the next-slide view stays, the notes area shows "No notes in this PDF"), or Cancel.
2. **Stale** (older than the deck sources or the instructor PDF): "Recompile first / Present anyway".
3. **Not a presenter layout** (page not ~2× a 16:9/4:3 slide ratio; exact test from M0): treat as a normal PDF (case 1, second option).
4. Several presenter PDFs (language variants): ask once, as "Open pdf" does.
No automatic compile without asking; compiles are slow and visible.

### 4.10 Layout profiles (presenter window)
The presenter window layout and the elements it shows come from a named **profile**; the user picks the profile and the profile sets the layout.

**Elements:** `current` (current slide, interactive: links, laser, pen), `next` (next slide), `notes`, `clock`, `timer`, `counter` (slide n / N and step), `audience` (optional small thumbnail of what the projector shows, useful while frozen or black; M3), `toolbar` (pen, eraser, clear, black, freeze, profile menu, end).

**Recommended layout model: a split tree.** A profile is a binary tree of splits, each node `{split: "h"|"v", ratio: 0..1, a: node, b: node}` and each leaf either one big element (`current`, `next`, `notes`) or an **info strip**, an ordered list of the small elements (`clock`, `timer`, `counter`, `toolbar`). It maps one-to-one onto nested `QSplitter`s, can express every layout the owner described, always fills the window with no overlaps or gaps, resizes cleanly on any screen, and is trivial to validate and serialize. Rejected: free-form drag-anywhere canvases (overlaps, off-screen elements, hard to test, bad at different resolutions) and fixed templates only (cannot express the owner's layout without special cases).

Rules: each big element at most once; an element absent from the tree is simply not shown; `current` is mandatory (a profile without it is invalid); ratios clamp to 0.1-0.9; unknown elements are dropped on load with a warning.

Stored as JSON:
```json
{"name": "Current large", "version": 1,
 "tree": {"split": "v", "ratio": 0.94,
   "a": {"split": "h", "ratio": 0.62,
         "a": {"leaf": "current"},
         "b": {"split": "v", "ratio": 0.35,
               "a": {"leaf": "next"}, "b": {"leaf": "notes"}}},
   "b": {"leaf": ["counter", "clock", "timer", "toolbar"]}}}
```

**Built-in profiles** (code, read-only):
1. **Current large** (the owner's): current slide large on the left, next slide smaller at top right, notes at bottom right, info strip along the bottom.
2. **Next large**: next slide large on the left (about 65%), current slide small at top right, notes below it, info strip at the bottom (the originally planned layout).
3. **Notes focus**: notes large, current and next small (M3).
4. **Slide only**: current slide with the toolbar strip, nothing else (M3; handy for a lone laptop).

**Storage:** per user, not per project: the layout depends on the presenter's screen and taste, not on the deck, and project folders may be shared or synced. Custom profiles in one JSON file next to the application settings (`presentation_profiles.json` in the same directory `app_settings.py` uses; the implementer checks the exact helper), the chosen profile name in `PresentationSettings`. Built-ins are never written to disk; "copy" creates an editable custom profile. A deleted or invalid active profile falls back to "Current large". Optional (open question 4): a per-deck override stored in the deck's settings.

**Operations:** create (from a built-in or blank), copy, rename, delete (custom only). **Editing:**
* Live, in the presenter window: the splitter handles are always draggable. Dragging on a custom profile updates its ratios (saved on exit or profile switch); dragging on a built-in profile shows a small "Save as my profile…" prompt the first time and then edits the copy. This is cheap (QSplitter does the work) and fits the "keep it simple" goal.
* In the settings page (4.11): which element sits where, with a **live preview** (the profile rendered with placeholder boxes or the first pages of the last presented deck/the fixture), plus a tree editor: pick a region, split it horizontally/vertically, assign an element, remove. Later milestone.
* `P` in the presenter window (and a toolbar menu) switches profiles during the show.

**What this changes in the milestones:** M1 ships the layout engine (`layout.py`, `layout_view.py`) with the two fixed built-ins "Current large" and "Next large" and a profile menu, no editing; M2 does not change; M3 adds the other built-ins, live splitter-saving, create/copy/rename/delete and the settings-page editor with preview.

### 4.11 Presentation settings (one page)
All presentation options live in one **"Presentation"** page of the existing settings dialog (`ui/dialogs/settings.py`, new `ui/presentation/settings_page.py`), stored in `PresentationSettings`:
* **Layout:** active profile (drop-down), profile list with New / Copy / Rename / Delete and the preview editor (M3).
* **Pointer and drawing:** laser colour (default red), pen colour (default yellow highlighter), pen width.
* **Timer:** default mode (end time of day, default; or duration), default duration, start on first slide change (on), flash when time is up (on, or solid red only), amber warning at 5 min (on). Clock format (system / 12 h / 24 h).
* **Links:** confirm before opening external links (default on); internal jumps never ask.
* **Screens:** audience screen (Automatic, or a named screen), keep the computer awake while presenting (M3).
* Every setting has a default, so presenting works with the page never opened; a "Reset to defaults" button.

### 4.12 Projector control: black and freeze
The audience screen is controlled by two independent states in the session: `black` (bool) and `frozen_page` (page number or none). The page the audience shows is `audience_page = frozen_page if frozen else current page`; black overrides everything on the projector.

| Action | Effect |
|---|---|
| **B** or **`.`** (alias; many clickers send either) | Toggles `black`. The projector goes fully black (no laser, no drawings). |
| Navigation while black | Clears `black` (the projector shows `audience_page` again: the new page if live, the frozen page if frozen). |
| **F** | Toggles freeze. Freezing sets `frozen_page` to the page the audience currently has (`audience_page`, which is the presenter's page at that moment), and the strokes visible at that moment are kept as a snapshot. While frozen, laser and drawing changes are **not** mirrored: the presenter still sees them in the presenter window, the projector keeps the snapshot. |
| Navigation while frozen | Moves only the presenter's `page`; it does **not** unfreeze and does not touch the projector. Link clicks and jumps behave the same way. |
| **F** again (unfreeze) | The projector jumps to the presenter's current page and gets its current strokes (the laser is live again). |
| **B while frozen** | Allowed and independent: the projector goes black, the freeze stays set. Navigation clears the black only, so the projector returns to the frozen slide, never to the presenter's new page. **B** again also returns to the frozen slide. |
| **F while black** | Freezes at the page the projector showed before it went black and stays black; the next B or navigation shows that frozen slide. |
| Black and frozen both on | Badge shows both. |
| Presentation start / end, or a PDF reload | Both states reset. |

**Presenter feedback (always on, not removable by a profile):** the current-slide view draws a coloured frame and a label on a corner badge: "PROJECTOR BLACK" (red frame) or "PROJECTOR FROZEN: slide N" (amber frame); both states stack in one label ("BLACK · FROZEN: slide N"); nothing is drawn when live. The same toolbar buttons (black, freeze) are shown as checked. The state is also in the window title bar tooltip for screen readers. Colours come from the theme tokens and are accessible by shape (label text), not by colour alone.

**Optional (M3): `audience` profile element**, a small live thumbnail of what the projector shows (the frozen page with its snapshot strokes, or a black tile), so the presenter can see the difference between the audience page and the presenter's current page. It is not needed for the badge to work.

**White screen (W, `,`) is dropped.** The owner asked for black and freeze only, a white projector is blinding in a dark lecture hall and adds a third state to the state machine, tests and badge. It can be added later as a one-line variant of `black` if someone asks.

**Audience-only mode** (one screen or mirrored): B works (the full-screen window goes black); F is disabled because there is no separate presenter view whose page could diverge (the toolbar button is hidden and the key is ignored with a short toast).

## 5. Milestones

* **M0 spike (≈0.5-1 day).** Compile a real deck with Presenter; measure page size, the slide and note rectangles, whether the note appears on every overlay page, link rectangles, named destinations for slide ids. Append findings to this file. Gate for M2 and for 4.6.
* **M1 MVP (≈4 days).** `pdf_source`, `renderer`, `session`, `screens`, `locate`, `layout` + `layout_view` with two built-in profiles ("Current large", "Next large") and a profile menu; `settings` with defaults; audience and presenter windows (current, next, notes, counter, toolbar); optional clock and timer elements (`timer.py`, 4.5); key table plus mouse wheel with next/prev/first/last/black/freeze/jump-by-number/exit (Esc exits at once); `present` command and menu entries; no/stale PDF dialogs; single-screen and mirrored fallback; **B (black) with the presenter badge in M1; F (freeze) also in M1 because it is a few lines in the session's `audience_page` logic and the canvas already reads that**; tests.
* **M2 interaction (≈2-3 days).** (F moves here if it turns out not to be cheap in M1.) Link clicks (internal jump with return, external with confirmation), Ctrl+left-button laser, pen/highlighter with undo and the Clear button/Delete key (per-page persistent drawings), all synced to the audience; the "Presentation" settings page with colours and link confirmation (profile editing not yet).
* **M3 polish.** More built-in profiles; profile create/copy/rename/delete, live splitter saving and the settings-page editor with preview (4.10); slide grid/jump list with titles, hot-plug, per-platform keep-awake (4.3), macOS full-screen helper, audience chooser, `present_from_here`.
* **M4 optional.** Notes as text with adjustable size, phone remote, skip-reveals idea, per-deck profile override.

## 6. Test approach

pytest with `QT_QPA_PLATFORM=offscreen` (already set in `tests/conftest.py`, `qapp` fixture). New: `tests/test_presentation_source.py`, `_session.py`, `_screens.py`, `_gui.py`.
* **Fixture PDF without LaTeX:** build a small presenter-like PDF with `pymupdf` in the test (6 double-width pages: left half a coloured block with the number, right half "note n", `insert_link` for a URI and an internal link). Deterministic; no TeX needed. An optional test on a real compiled PDF skips when absent.
* `pdf_source`: split rectangles, sampled colours of both halves, link normalization, destination -> page.
* `session`: bounds, jump by number, link jump and return, per-page stroke persistence across navigation, clear page / clear all, a reload discards strokes, pointer, signals; black/freeze state machine (4.12): B toggles; navigation clears black but never frozen; frozen audience page stays while `page` moves; B while frozen blacks over the frozen slide and B again returns to the frozen slide; F again jumps the audience to the current page; strokes and laser are not mirrored while frozen and resync on unfreeze; the audience canvas never shows the presenter page while frozen; the presenter badge text for live/black/frozen/both.
* `layout`: profile JSON round-trip, validation (missing `current`, duplicate element, bad ratio, unknown element), built-ins valid, invalid/deleted active profile falls back.
* `timer`: end-time mode (today/tomorrow/rejected), duration mode with start on first navigation, pause/resume/reset, flash state and overrun with an injected clock; an unset timer does nothing.
* `screens.choose_screens` with fakes: 1 screen, 2 distinct, 2 identical geometry (mirror), 3 screens with a preferred name, preferred screen missing.
* GUI (offscreen): controller creates two windows for two fake screens and one for one; `QTest.keyClick` changes the page in both canvases; a wheel event steps pages (one touchpad swipe steps once); B/`.` blacks and navigation restores, F freezes and the audience canvas keeps its page and strokes while the presenter navigates, the badge and frame appear on the current-slide view; a mouse move over the current view puts the pointer at the same normalized spot on the audience canvas (check via `grab()` pixel sampling); the presenter window builds the right splitters for each built-in profile and switches profile on `P`; Ctrl+left press-move shows the dot on the audience canvas and release hides it, a plain click on a link area jumps, a Ctrl press on a link area does not, and with the pen on a plain drag draws while Ctrl+drag lasers; Delete clears the page's drawings; the audience window contains no clock or timer widget; Esc closes windows and joins the render thread without leftovers.
* Not covered offscreen, manual checklist in the PR: the per-platform checklist of section 4.3 (placement, duplicate mode, hot-plug, clicker keys, wheel, projector smoothness) on Windows, macOS, X11 and Wayland.

## 7. Risks

1. Link geometry in pgfpages output (4.7), decided by M0.
2. The note may not appear on every overlay page of a frame; mitigation: show the note of the nearest page of the same frame (needs 4.6).
3. Very long notes are cut at the bottom of the note page (README already warns); the viewer cannot fix it.
4. MuPDF threading and crashes: one owner thread (or reuse the raster process); render failures show a placeholder instead of crashing a live show.
5. Render latency for 4K or heavy TikZ slides: cache and prefetch; measure in M1.
6. Platform quirks (4.3): Windows wrong-monitor placement and mixed DPI; macOS Spaces, native full screen, Dock/menu bar; Wayland cannot place windows, so the presenter window position is up to the compositor and audience placement depends on it honouring fullscreen-on-output; X11 window-manager differences. Each needs the manual checklist on real hardware.
7. Mirror detection is heuristic outside Windows/macOS (and on Wayland); the audience-screen setting is the escape hatch.
8. Clicking URLs during a live show: confirm first.
9. Template changes (`gothampresenter`) can shift the split: keep detection geometric, covered by a LaTeX-free test.
10. Ctrl+click on macOS and some trackpads (4.8); the laser needs a mouse button held, which is awkward on touchpads (tap-and-hold works; a toggle key could be added later if reported).
11. Profile editing scope creep: keep the split-tree model and ship editing late (M3).
12. Licence hygiene: nothing from pympress/pdfpc (section 1).

## 8. Open questions for the owner

1. When the presenter PDF is missing or stale: compile automatically (one click) or always ask first? (Plan: ask.)
2. pymupdf is AGPL: acceptable for your distribution plans? If a closed-source release is ever planned, `renderer.py` is the one place to swap the engine (QtPdf or pdfium), but links and named destinations would then need their own source.
3. Ctrl+left-button laser on macOS means Command in Qt's mapping (a physical Ctrl+click is a right click there): fine to document "Ctrl (⌘ on macOS)", or do you want another gesture on Mac?
4. Should a deck be able to override the layout profile (stored in its settings), or is one profile per user enough? (Plan: per user only.)
5. Timer in end-time mode: if the time has already passed today, reject (plan) or assume tomorrow?

## 9. M0 findings (measured on a real presenter compile)

Compiled with SlideMage's own compiler (`build_jobs(deck, "presenter")`) from a scratch copy of `example/` plus `latex/` (a path under `/tmp` made biber fail, so the scratch project lived in a short path; nothing of the owner's decks was touched), deck `slidemage-manual`, 90 pages, plus a small scratch deck with real overlays and notes.

* **Page geometry:** every page is 907.09 x 255.12 pt, which is exactly **2 x 453.54 pt (16:9) wide**. The slide is the left half, the note page the right half, no scaling by pgfpages. So the split is simply `width / 2`; `pdf_source` still decides "presenter layout" by the page ratio (>= 2.2), so a normal PDF is shown as one slide without notes.
* **Links work.** Link rectangles of the left half are in unscaled slide coordinates (footer navigation links at y 248-255 and 4.5-16 on a 255 pt page; URI and internal links both appear). `get_links()` gives kind, rect and a resolved target page for internal links. Links in the right half do not occur in practice and are ignored.
* **Notes are on every overlay page.** In the scratch deck a frame with three reveal steps had its note on all three pages, so the notes view needs no carry-forward (risk 2 is closed).
* **Named destinations exist for every page** (281 names covering all 90 pages: slide ids, agenda and navigation targets, and overlay pages). They therefore cannot tell reveal steps from slides, so section 4.6 "slide n, step m" grouping is **not feasible from the PDF alone**. The counter shows "Page n / N". Titles for a jump list can come from the first text line of the slide half (`PresentationDeck.title`).
* **Page labels** are the printed footer numbers but come out as odd UTF-16 strings, not usable.
* **Render time:** ten 1920 px slide renders took 0.13 s, about 13 ms each. A worker thread is not needed; rendering is synchronous with a 24-image cache, which also keeps MuPDF in one thread. (Plan 4.2/4.1 `renderer.py` was dropped for that reason; the cache is inside `PdfSource`.)
* **Only 2 of the 90 pages of the manual carry long notes**, so most real note panes are short or empty.
* In the presenter job `\pause` produced no extra pages in my scratch frame while `\item<2->` did; the example deck's own reveal slides use the `<n->` form. Not related to this feature, noted in case it surprises someone.

## 10. Implementation notes (what was built, and where it differs from the plan)

* Code: `src/slidemage/presentation/` (`pdf_source`, `session`, `screens`, `settings`, `locate`, `layout`, `timer`, `keep_awake`) and `src/slidemage/ui/presentation/` (`slide_canvas`, `slide_input`, `views`, `layout_view`, `audience_window` with both windows, `timer_widget`, `controller`, `launch`). Tests: `tests/test_presentation_core.py`, `_gui.py`, `_launch.py`, fixture builder `tests/presentation_fixtures.py` (a LaTeX-free presenter-like PDF).
* **Keep awake (added on the owner's request):** `presentation/keep_awake.py`, started with the presentation and released when it ends (and at process exit). Windows: `SetThreadExecutionState` for display and system, plus the screensaver switched off for the session and restored (not saved to the profile), because the execution-state call alone does not stop a configured screensaver; macOS: a `caffeinate -d -i -w <pid>` child that ends with the app; Linux X11/Wayland: the session bus's `org.freedesktop.ScreenSaver.Inhibit` (KDE, GNOME and others), else GNOME's `org.gnome.SessionManager.Inhibit`; released by cookie. All failures are swallowed so a missing bus never stops a show. Closing a laptop lid or pressing the power button still suspends the machine. The idea set came from reading only the discussion text (prose) of the pympress pull request about this; no pympress code was read. Not testable here beyond a fake backend: manual check on each OS that the display stays on past the system's idle time and the screensaver does not start (and that the screensaver setting is back afterwards on Windows). The xdg portal Inhibit (for sandboxed Flatpak builds) is not implemented.
* The "Present deck" command (F5) is in the palette, the ⋮ menu and the Compile menu (section 13).
* Presentation settings are stored per user (see section 13).
* The Ctrl+left-button laser, the pen, the eraser, Clear/Delete, link clicks with a way back (Alt+Left), black (B or .), freeze (F), the timer (T, Shift+T) and the wheel were all built in the first pass; the milestone split below says what is covered by which commit.
* The window is placed with `setGeometry` of the chosen screen plus `windowHandle().setScreen()` before `showFullScreen()` (audience) or `showMaximized()` (presenter); on Wayland only the screen request is honoured.

## 11. Changelog draft

> **Present from SlideMage.** `F5` (or Ctrl+K, "Present deck") presents the deck from its Presenter PDF: the audience screen shows the slide full-screen; your own screen shows the current slide, the next slide and the notes, with an optional clock and timer, in a layout you can switch (`P`). The mouse wheel, arrow and clicker keys move through the reveal steps; `B` or `.` blacks out the projector and `F` freezes it on the slide it shows while you move on; Ctrl + left button is a laser pointer, `D` draws, `Delete` clears. Links in the slide work, with `Alt+Left` to go back. The computer stays awake and the screensaver off while you present. With one screen, or mirrored screens, only the full-screen slide is shown. A deck without a Presenter PDF offers to compile one, or to present the normal PDF without notes.

## 12. Status after implementation

* **M0** done (section 9). **M1** done: windows, screen plan with fallback, keys, wheel, black, freeze with badge, two built-in layouts, clock and timer, keep-awake, no/stale-PDF dialogs, the `present` command (F5, palette). **M2** done: link clicks with Alt+Left back, Ctrl+left laser, pen, eraser, Clear/Delete, per-page drawings synced to the projector, and the "Presentation" tab of the Settings sheet (layout, laser and pen colours and width, link confirmation, timer defaults and behaviour, clock format, projector screen, reset).
* **Left for M3 (not started):** the ⋮/Compile menu entry; "present from the selected slide" (Shift+F5; the PDF's named destinations carry the slide ids, so this is a lookup); the slide grid / jump list (G) with titles; re-planning the screens when one is plugged in or removed during a show; more built-in layouts (Notes focus, Slide only), custom layouts (create, copy, rename, delete, live splitter saving, the editor with preview); the optional `audience` thumbnail element; macOS Dock/menu-bar hiding; the xdg portal inhibit for sandboxed Linux builds; the right-click clear.
* **Manual checklist for the owner** (multi-screen behaviour is only tested with made-up screens): section 4.3's list on Windows, macOS, X11 and Wayland, and for keep-awake: leave a presentation running past the system's idle/sleep time with the display and screensaver timeouts set short, confirm the display stays on and the screensaver does not start, end with Esc, and confirm normal sleep behaviour (and, on Windows, the screensaver setting) is back.
* **Different screen sizes (owner's request):** strokes and the laser are stored as fractions of the slide (0..1) and the stroke width and laser size as fractions of the slide height; every canvas draws them inside its own letterboxed slide rectangle, so a 900x640 presenter view and a 1000x800 or 4K projector show the same spot, at the same relative size. Points pressed in the margin around the slide are clamped to the slide's edge. Covered by `test_a_drawing_lands_on_the_same_spot_of_the_slide_on_screens_of_different_size_and_shape`.

## 13. Follow-up round (before the merge)

* **Typed number = slide number.** Digits + Enter jump to the slide whose number is printed in the footer (the frame number), landing on its first reveal step. The frame to pages mapping comes from beamer's `.nav` file: one `\beamer@framepages {first}{last}` line per frame (1-based pages; checked on the example deck: 78 frames over 90 pages). `presentation/frames.py` looks for the Presenter compile's kept `.nav` (`.build/compile-records/<jobname>/`, then any `.build/<jobname>-*/`) under the deck's presenter job names (own language, the other language, the PDF's own name) and only uses a file that fits the PDF (starts on page 1, frames in order, the last one ends on the last page). Without a fitting file the number is a PDF page and the indicator says "Go to page 12". With the map the counter reads "Slide n / N · step k / K" and a typed number shows "Go to slide 12 (Enter)" in the counter and as a short message.
* **Settings are per user and machine**, not per project: `PresentationSettings` is stored in `layout.json` beside the window layout (`ui/layout_settings.py`, key `presentation`); tests use the existing isolation in `conftest.py`.
* **"Present deck" is now in the ⋮ menu ("This deck", first entry) and in the Compile caret menu (own "Present" section)**; the menu tests were updated.
* `test_chat_gui.py::test_create_slide_shows_its_returned_preview_in_the_real_window` is flaky on develop `b3acd47` too (3 failures in 13 isolated runs, each a Windows `PermissionError` writing a file in the temp folder), so it is not caused by this branch.
