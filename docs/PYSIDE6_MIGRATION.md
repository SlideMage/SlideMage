> **Historical (SlideMage 6.0).** This is the log of the 2026-08 move from Tkinter to
> PySide6. The `qt_*` modules it names (`qt_gui.py`, `qt_deck_table.py`,
> `qt_deck_editor_tab.py`, `qt_slide_source_tab.py`, ...) no longer exist: SlideMage 6.0
> replaced that window of tabs and tables with one workspace per deck (`src/slidemage/ui/`;
> see `UI_REDESIGN_PLAN.md` for the redesign and `SlideMage.md` for how the app is built
> now). Read this file only for why the app left Tkinter and how that move went.

# SlideMage: migrating the GUI from Tkinter/ttk to PySide6

**Status (2026-08-09): Migration complete, all 10 phases done.** `__main__.py`
now launches qt_gui.py; the Tk gui.py/theme.py/scrollable.py/
deck_editor_tab.py/slide_source_tab.py/add_slide_dialog.py files are left in
place (not deleted) as a fallback/reference, still fully working on their
own if ever run directly. SlideMage.bat updated to launch via the
project-local .venv's own pythonw.exe (PySide6 isn't installed system-wide,
see the venv-setup note below) instead of the system `pythonw`. A
feature-parity pass cross-checked every toolbar action, dialog (including
the three-way Save/Discard/Cancel close prompt), compile-status lifecycle,
and log-parsing regex against the Tk source line-for-line before the swap.
This is a large, deliberate rewrite of the GUI layer, done as its own
tracked effort across sessions -- not a quick patch. Update the Status line
above as phases complete.

## Context

Repeated, permanent ttk limitations motivated this: no per-tab colors
(confirmed directly -- `ttk.Notebook.tab()` accepts no `background`/
`foreground`/`style` option at all, only `text`/`image`/`compound`/
`padding`/`sticky`/`state`/`underline`), dark mode only works today by
forcing the `clam` ttk theme plus hand-registering every plain `tk.*` widget
for manual recoloring (`theme.py`'s whole weakref-registry mechanism exists
only because of this), and the overall look is inherently "basic" -- ttk
draws native OS chrome, not a customizable one. PySide6 (Qt for Python)
directly solves the problem that started this (native per-tab text color:
`tabBar().setTabTextColor(index, QColor(...))`) plus several others that
were being separately worked around -- tab-scroll-on-overflow and
max-tab-width are both native `QTabWidget` behavior, meaning the
previously-requested "tabs wrap under the search box" fix comes essentially
for free as part of this migration rather than needing its own ttk-specific
workaround.

## What's confirmed reusable as-is (no Qt changes needed)

Every business-logic module was read in full and grepped for `tkinter`/`tk`/
`ttk` -- zero matches outside the GUI-layer files. These stay untouched:

`deck_scan.py`, `compiler.py`, `slide_source.py`, `deck_editor.py`,
`archive.py`, `slide_ids.py`, `deck_headers.py`, `unused_content.py`,
`slide_preview.py`, `version.py`, `__init__.py`.

The only coupling points are plain `log: Callable[[str], None]` parameters
(`compiler.run_job`/`run_jobs`, `unused_content.archive_unused_content`,
`slide_preview.render_slide_to_pdf`/`render_slide_text_to_pdf`) -- in Qt
these just need an equivalent callable (see threading section below).
`compiler.CancelToken`'s `threading.Event`/`threading.Lock`, and
`deck_headers.py`'s module-level `threading.Lock`, are portable unchanged --
OS-level primitives independent of whether the calling thread is a plain
`threading.Thread` (kept, see below) or a `QThread`.

## GUI-layer files being rewritten (1:1 replacement)

| Current (Tkinter/ttk) | New (Qt) | Notes |
|---|---|---|
| `gui.py` (`SlideMageApp`, `DeckRow`) | new `qt_gui.py` (`SlideMageWindow(QMainWindow)`, a `DeckRow`-equivalent row builder) | Keep `gui.py` untouched throughout the migration -- new file, swapped into `__main__.py`'s import only once verified equivalent, so the working app stays available as a fallback the whole time. |
| `theme.py` (`ThemeManager`) | rewritten: same `PALETTES` dict (data unchanged), replaces `_configure_styles`/the 5 weakref registries/`register_*` methods with one QSS stylesheet string built from the palette and applied via `QApplication.instance().setStyleSheet(...)` | Qt widgets all accept stylesheets uniformly, so the entire "plain tk widgets need manual per-widget registration because ttk can't style them" problem disappears. Dark/light toggling becomes "rebuild the QSS string, reapply it" -- no registries, no `winfo_exists()`-pruning, no weakrefs. |
| `scrollable.py` (`ScrollableFrame`, 157 lines) | **deleted** | `QScrollArea` with `setWidgetResizable(True)` + per-axis `Qt.ScrollBarAsNeeded`/`Qt.ScrollBarAlwaysOff` policies does everything this module hand-builds (canvas+scrollbar packing order, show/hide-on-overflow, mouse wheel routing) natively. |
| `deck_editor_tab.py` (`DeckEditorTab`) | `DeckEditorTab(QWidget)`, a `QTabWidget` page | Rows via `QGridLayout` inside a `QScrollArea` (both axes, matching today's `horizontal=True, vertical=True`); same columns (position/id-slug link/variant combo/conditions/Apply/±before/±after/Remove/Render). Undo stack (`self._undo_stack: list[str]`, `record_undo_snapshot`, `_on_undo`) ports directly -- plain Python state, not Tk-specific. |
| `slide_source_tab.py` (`SlideSourceTab`) | `SlideSourceTab(QWidget)` tab page | `scrolledtext.ScrolledText` → `QPlainTextEdit`; the 3-regex syntax highlighting (`COMMENT_RE`/`COMMAND_RE`/`BRACE_RE`) reimplemented as a `QSyntaxHighlighter` subclass. `_wrap_or_insert`/`_replace_selection_or_insert` port to `QTextCursor` (`.selectedText()`, `.insertText()`, `.setPosition()`), wrapped in `cursor.beginEditBlock()`/`endEditBlock()` for the same single-atomic-undo-step guarantee `.replace()` gives today. Both toolbar rows port 1:1 to `QPushButton`/`QComboBox`. |
| `add_slide_dialog.py` (`AddSlideDialog`) | `AddSlideDialog(QDialog)` | Modality via `setModal(True)` + `.exec()`; `tk.Listbox` live-filter → `QListWidget` + `QLineEdit.textChanged`, same substring filter logic. |

## Widget/mechanism mapping

| Tkinter/ttk | Qt |
|---|---|
| `ttk.Frame` | `QWidget` / `QFrame` |
| `ttk.Label` | `QLabel` |
| `ttk.Button` / `tk.Button` | `QPushButton` (no more "plain tk.Button because ttk ignores style overrides" workaround -- every `QPushButton` is stylable uniformly, so `gui.py`'s `_style_stop_button`/`_apply_tk_button_borders` hand-rolled hex-color logic also goes away) |
| `ttk.Checkbutton` | `QCheckBox` |
| `ttk.Entry` | `QLineEdit` |
| `ttk.Combobox` | `QComboBox` |
| `ttk.Notebook` | `QTabWidget` |
| `ScrollableFrame` | `QScrollArea` (native) |
| `scrolledtext.ScrolledText` | `QPlainTextEdit` |
| `tk.Listbox` | `QListWidget` |
| `tk.Toplevel` (modal dialog) | `QDialog` |
| `tk.Toplevel` (slide-search popup, `overrideredirect`) | `QCompleter` on the search `QLineEdit` -- replaces `gui.py`'s ~130 lines of hand-built popup/positioning/focus-tracking code |
| `tk.StringVar`/`BooleanVar` | not needed -- Qt widgets hold their own state directly |
| `messagebox.askyesno` | `QMessageBox.question(...)`, compare to `QMessageBox.Yes` |
| `messagebox.showerror` | `QMessageBox.critical(...)` |
| `messagebox.showinfo` | `QMessageBox.information(...)` |
| `messagebox.askyesnocancel` | `QMessageBox.question(..., buttons=Yes\|No\|Cancel)`, map Cancel→`None`/Yes→`True`/No→`False` to preserve `slide_source_tab.py`'s existing three-way branching |
| `root.after(100, _drain_log_queue)` polling a `queue.Queue` | a `QObject` with `Signal(str)`, emitted from the worker thread, connected to a slot -- Qt's cross-thread signal delivery is automatically queued onto the receiver's thread, replacing manual 100ms polling with real event-driven delivery |
| `root.after(400, _tick_spinner)` | `QTimer`, `.timeout.connect(...)`, `.start(400)` |

**Threading model**: keep plain `threading.Thread` for compile jobs (no
forced move to `QThread` -- `CancelToken`'s primitives don't care). Only the
`log` callback changes: `self.log_queue.put(line)` becomes
`self.log_signal.emit(line)` on a small `QObject` subclass; the connected
slot (on the GUI thread automatically) does what `_log()` does today. This
deletes `_drain_log_queue` and the `queue.Queue` plumbing entirely.

## New capabilities this migration unlocks

- **Per-tab text color**: `tabBar().setTabTextColor(index, QColor(...))` -- gives Active/Archived and deck-editor/slide-editor tabs distinct colors natively.
- **Bold the selected tab**: `QTabBar::tab:selected { font-weight: bold; }` in QSS.
- **Tab scroll-on-overflow**: `QTabWidget.setUsesScrollButtons(True)` (on by default in most styles) -- no custom scrolling code needed.
- **Max tab width with real ellipsis**: `QTabBar::tab { max-width: Npx; }`, Qt elides overflowing text with "…" automatically.
- **Corner widget for the search box**: `QTabWidget.setCornerWidget(...)` is the actual API for "put a widget in the tab strip's spare space" -- replaces `gui.py`'s current `place(relx=1.0, x=-8, y=4, anchor="ne")` hack.

## Dependency/distribution impact

- New pip dependency: `PySide6` (~50-100MB installed; LGPL-licensed). This
  project had no `requirements.txt`/`pyproject.toml` before this migration --
  now added as the first formal dependency declaration.
- `SlideMage.bat`/`python -m slidemage` stays the same shape;
  `__main__.py` only needs its `from .gui import main` swapped once the Qt
  version is verified complete.
- The "every code change takes effect on next launch, no build step" loop
  this project's whole iteration style relies on is unaffected -- still
  plain Python. (Orthogonal to the separately-discussed idea of eventually
  packaging into a standalone `.exe` via PyInstaller.)

## Phased approach

1. **Scaffold**: PySide6 as a dependency, a minimal empty `QMainWindow` that launches.
2. **Theme**: port `PALETTES` → QSS-string builder.
3. **Main window shell**: `QTabWidget` with "Active decks"/"Archived decks" pages, search box as a corner widget.
4. **Deck table**: per-deck rows, compile-job threading + signal wiring, Compile-selected/Stop-compilation buttons.
5. **Deck editor tab**: scrollable per-slide row list, Undo stack, Refresh/Source/Close.
6. **Slide editor tab**: `QPlainTextEdit` + `QSyntaxHighlighter`, both toolbar rows, wrap-or-insert logic, Render-to-PDF threading.
7. **Add-slide dialog**: `QDialog`, `QListWidget` live filter, variant/condition UI.
8. **Remaining toolbar bits**: Empty pdf/folder, Remove temp files, Archive unused content, footer-timestamp/auto-open/dark-mode checkboxes, version label, slide-search `QCompleter`.
9. **Polish pass**: tab coloring/bold-selected/scroll/max-width -- the features that motivated this migration.
10. **Cutover**: side-by-side feature-parity check against the still-intact Tk `gui.py`; only then swap `__main__.py`'s import and decide whether to archive or delete the Tk version.

## Verification approach

- Each phase: confirm `python -c "import PySide6"` succeeds, then launch and
  visually confirm the new shell.
- Live verification stays to read-only capture (a `PrintWindow`-style
  screenshot of the known window handle) or asking for direct confirmation --
  not scripted clicking/typing into a live desktop, after this project saw
  synthetic keyboard/mouse automation twice land on the wrong foreground
  window in one session (once nearly costing a full Outlook inbox).
- Final acceptance before cutover: a feature-parity checklist walking every
  button/dropdown/dialog in the current Tk app and confirming the Qt
  equivalent behaves the same way.

## PyInstaller packaging (2026-08-11)

The "separately-discussed idea" above became necessary, not just
desirable, once this project's `.venv` itself turned out to be the
problem: this whole project folder is synced across two machines by
Dropbox/SyncBackPro, and a venv is tens of thousands of small files whose
absolute base-interpreter path is baked in per-machine anyway. A venv
synced over from the second machine pointed at a `python.exe` that
doesn't exist here and failed outright; the sync clients also
locked/indexed its files badly enough that even deleting it repeatedly
timed out (confirmed directly: a plain `rm -rf .venv` didn't finish in
120+ seconds, throwing hundreds of "Permission denied" errors mid-delete).

Fix, two parts:
- The venv moved out of the synced folder entirely, to
  `%USERPROFILE%\SlideMaster\venv` (machine-local, never synced -- see
  `requirements.txt`'s own header comment; not `%LOCALAPPDATA%`, tried
  first and found to be virtualized per-app on a machine whose system
  Python is the Microsoft Store package, silently breaking venv isolation
  entirely -- confirmed directly, 2026-08-11). `SlideMage.bat` now
  auto-creates or auto-migrates it on first run per machine.
- `dist/SlideMage.exe` (`SlideMage.spec` +
  `build_slidemage_exe.bat`, project root) is now the actual day-to-day
  way to launch the app: a **one-file** build specifically (not
  PyInstaller's own default one-dir), so it's a single ~50MB file that
  syncs as one bulk transfer once built on either machine, rather than the
  hundreds of loose files a one-dir build would still churn the same way
  the venv did. `build/`'s own intermediate PyInstaller cache is likewise
  redirected outside the synced folder (`--workpath`); only `dist/` itself
  (the shippable output) stays inside it, gitignored from *git* (a large
  frequently-rebuilt binary doesn't belong in history) but not from
  Dropbox's own sync.

One real code fix this required: `deck_scan.py`'s `PROJECT_ROOT = Path(
__file__).resolve().parent.parent` assumed running from source, where
`__file__` really does sit two levels under the real project root. Frozen
by PyInstaller, `__file__` instead points into the bundle's own temp
extraction dir -- so `PROJECT_ROOT` needed a `sys.frozen` branch that
starts from `sys.executable`'s own location instead and walks upward
looking for `slide_ids.csv` (a marker unique to this project's real root),
so the exe keeps finding the actual, live `decks/`/`slides/`/`media/`
regardless of exactly where it's placed. Verified two ways after
building: the compiled exe's own window title includes a live,
git-derived version string (`version.py`'s `_run_git(..., cwd=
PROJECT_ROOT)` only succeeds against a real git checkout, so this alone
confirms `PROJECT_ROOT` resolved correctly), and the deck table visibly
populated with real content on launch.

**Near-miss repeating this file's own documented warning above** (the
"nearly costing a full Outlook inbox" one): verifying that populated deck
table used a `SetForegroundWindow` PowerShell one-liner to bring the app
window forward before screenshotting it; a typo made that call silently
fail, so the screenshot that got taken was of the *entire desktop*
instead, mid-capture, over an open Outlook draft with private
correspondence and photos. Caught immediately, the file was deleted
without being described or reused, and no further screenshot was taken --
the window-title check (`tasklist /v`, no foregrounding needed) turned out
to be sufficient confirmation on its own. Re-confirms this file's own
standing rule: prefer read-only, non-focus-stealing verification
(window-title text, log output, a version string) over anything that
depends on successfully foregrounding the right window first.
