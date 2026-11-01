# SlideMage Presenter: a small, fast app for presenting a PDF

Status: draft plan, 2026-10-31. Nothing implemented yet.

## Goal

A second program, **SlideMage Presenter**, that

- needs no project: it opens a PDF (a SlideMage presenter PDF with notes, or any plain PDF) and presents it,
- starts quickly (target: presenter window up in under 1 s on a warm start, under 2 s cold),
- is small (target: under 100 MB unpacked, about 40 MB zipped, against 655 MB for `dist/SlideMage-folder`),
- gets every improvement to SlideMage's presentation mode automatically, with no porting work.

## Recommendation: one repository, two build targets, not a fork

A git fork that strips everything out would meet the size goal on day one, but it breaks the last goal: every
change to the presenter code would have to be merged or cherry-picked from SlideMage into the fork, and the fork's
stripped files would conflict with every merge. Over time the two drift apart.

What the user is after with "fork and strip" can be had without a second copy of the code:

- **Same source tree.** The presenter lives where it lives now (`presentation/`, `ui/presentation/`). SlideMage
  Presenter is a second entry point (`presenter_app.py`) plus a second PyInstaller spec
  (`packaging/slidemage_presenter.spec`).
- **Stripping is done by the build, not by deleting files.** PyInstaller only bundles what the entry point
  imports. Started from a small entry point that never imports the workspace, the compiler, the AI code or
  QtWebEngine, the build leaves them out by itself. An `excludes` list in the spec is the safety net.
- **A test keeps it stripped.** An import-boundary test fails as soon as presenter code starts pulling in a heavy
  module, so the presenter stays small without anyone having to remember.
- **Same release.** The release workflow builds both and attaches both to the same GitHub release, with the same
  version number.

So a change to, say, the timer or the laser pointer is made once, tested once and shipped in both programs in the
same release.

## Where the code stands today

The presenter is already well separated (about 2,100 lines in 19 files), and SlideMage already presents a PDF
without a project ("Present a PDF…" on the start screen, `ui/presentation/launch.py:present_pdf_file`).
The remaining links into the rest of the app:

| Module | Imports | Needed by the Presenter app? |
|---|---|---|
| `presentation/frames.py` | `compiler`, `compile_records`, `project`, `deck_scan`, `deck_settings` | No: frame maps come from a project's compile records |
| `presentation/locate.py` | `compiler`, `project`, `deck_scan` | No: finding a deck's PDF in a project |
| `ui/presentation/controller.py` | `presentation.frames.FrameMap` (type only) | The type only, so frames.py must not drag the compiler in |
| `ui/presentation/launch.py` | `compiler.DeckPdf`, `deck_scan`, `workspace.compile_actions` (lazy) | Only `present_pdf_file` |
| `presentation/settings.py` | `ui.layout_settings` → `project.config_dir`, `fileio` | Yes; `project.py` imports only the standard library, so this is light |
| `ui/presentation/settings_page.py` | `ui.kit.widgets` | Yes, for a settings dialog; the kit is light |
| `ui/kit/theme.py` | `app_settings`, `project.ProjectContext` | For the theme; check that `app_settings` stays light |
| `cli.py` | `project`, `splash` at the top | Not used: the Presenter app gets its own entry point |

Heavy things the Presenter must never import: `ui.app`, `ui.workspace` (QtWebEngine terminal, chat, panels), `ai`,
`compiler` and the compile pipeline, the preview/render machinery, `plugins`, `lxml`, `python-pptx`, `odfpy`,
`segno`, `pywinpty`/`ptyprocess`.

Bundled data: only `assets/icon.*` and those fonts from `assets/fonts` (12 MB) that the kit actually uses for the
presenter's few dialogs. Not `example/`, `latex/`, `assets/terminal`, `assets/frames`, the wizard poses.

## Findings before step 1 (2026-10-31, develop at 7e15ba99, v0.11.0)

The handover's section 5 checks, after the framework redesign was merged:

- **Coupling:** unchanged by the redesign; the table above is still accurate.
- **"Present a PDF…"** still exists (`cli.py` → `ui/presentation/launch.py:present_pdf_file`).
- **Import baseline:** `import slidemage.ui.presentation.launch` takes 584 ms cold, 272 ms warm, loads 52
  SlideMage modules, and among them `compiler`, `plugins`, `deck_scan` and `compile_records`, all of which
  the Presenter must not need. Step 1 should bring the standalone path well below this.
- **Page labels (decides 5b):**
  - A plain SlideMage PDF (`#workdeck-mini-instructor.pdf`) has correct beamer page labels: one per frame, shared by
    its reveal steps (`1, 2, 2, 2, 3, 4`). PyMuPDF returns them still encoded as UTF-16 hex strings
    (`<FEFF0032>` for "2"), so the reader must decode them.
  - A **presenter** PDF has broken labels. `p-DoctoralSchool-…-presenter.pdf` has 40 pages but 80 label rules: the
    slide and its note page each get one, and only the slide's rule is right. The result alternates: page 0 gets
    the slide label of frame 1, page 1 gets the note page's plain counter, and so on.
  - So for 5b: reading labels works for plain PDFs, including most beamer PDFs from other people. For presenter
    PDFs, the labels must be fixed. Done in v0.12.1 without touching `latex/`: after every presenter compile,
    `compiler.label_presenter_pages` rewrites the labels from beamer's `.nav` (one slide number per page)
    before the PDF is published. Patching hyperref's labels inside pgfpages in TeX would have been more
    fragile. Older presenter PDFs, with more label rules than pages, are recognised and ignored.

## Steps

Each step is one PR into `develop`, small enough to review alone. Stop after each step.

### 1. Cut the remaining links (no behaviour change)

- `presentation/frames.py`: move `FrameMap` (the data type and its lookups) into a module without project imports,
  for example `presentation/frame_map.py`; `frames.py` keeps `load_for` (project → FrameMap) and imports it.
  The controller imports only `frame_map`.
- `ui/presentation/launch.py`: move `present_pdf_file` into `ui/presentation/standalone.py`, which imports only
  `presentation.*` and `ui.presentation.controller`. `launch.py` and `cli.py` import it from there.
- `ui/kit/theme.py`: needed no change. `project` and `app_settings`, which it imports, use only the standard
  library (checked in step 1).
- Done in v0.11.1: the standalone path loads 32 SlideMage modules, none of them heavy (52 before, with the
  compiler and the plugins).
- **Import-boundary test** `tests/test_presenter_imports.py`: in a fresh subprocess, import
  `slidemage.ui.presentation.standalone` and fail if any of a deny list (`slidemage.compiler`, `slidemage.ui.app`,
  `slidemage.ui.workspace`, `slidemage.ai`, `slidemage.plugins`, `PySide6.QtWebEngineCore`, `lxml`, `pptx`, `odf`,
  `segno`, `winpty`, …) ended up in `sys.modules`.

### 2. The Presenter entry point

`src/slidemage/presenter_app.py` with `main()`:

- `SlideMagePresenter talk.pdf` presents at once (also what a file association or drag onto the exe gives).
- Without an argument: a small start window with "Open PDF…", a list of recently presented PDFs, drag and drop of a
  PDF, "Presentation settings…" (the existing `PresentationTab` in a dialog) and the version.
- After the talk the start window comes back; closing it quits.
- `--self-test`: import everything, exit 0 (as SlideMage's, for the release workflow).
- Imports kept lazy and few: Qt, the kit, `presentation.*`, `pymupdf` only when a PDF is opened.
- Shares the presentation settings with SlideMage (same `config_dir()` and settings key), so screens, layout and
  timer set up in one apply in the other. Recent PDFs go under their own key.
- Add `slidemage-presenter = "slidemage.presenter_app:main"` to `[project.gui-scripts]` so it runs from the dev
  venv too.

Done in v0.12.4: `presenter_app.py` (entry point, `--self-test`, macOS `QFileOpenEvent` filter),
`ui/presentation/presenter_window.py` (start window), `presentation/recent.py` (recent PDFs, key
`presenter_recent`), icon A as `assets/presenter-icon.svg`. Runs from the source as `python -m
slidemage.presenter_app`. Measured: `import slidemage.presenter_app` 82 ms (2 SlideMage modules),
`--self-test` 401 ms with everything imported (39 SlideMage modules, PyMuPDF). The SVG icon needs QtSvg, so
step 3 must bundle QtSvg and its iconengines/imageformats plugins.

### 3. The build

`packaging/slidemage_presenter.spec`:

- Entry point `presenter_app.py`; hidden imports only `PySide6.QtCore`, `QtGui`, `QtWidgets`.
- `excludes`: QtWebEngine*, QtNetwork, QtQml/QtQuick, QtMultimedia, QtPdf, Qt3D, QtCharts, lxml, pptx, odf,
  segno, winpty, tkinter, unittest, and SlideMage's heavy packages.
- Drop unneeded Qt plugins and translations from the collected binaries (keep platforms, imageformats for PNG/JPEG,
  styles, and on Linux xcb/wayland).
- **Folder build as the main asset**, not one-file: a one-file exe unpacks itself to a temp folder on every start,
  which costs a second or more and is exactly the slow start we want to avoid. A one-file build may be offered
  beside it if users ask for a single file.
- Name `SlideMage Presenter` (executable `SlideMagePresenter.exe`, `SlideMage Presenter.app`), with its own icon
  so both can sit side by side. Drafts: `docs/plans/presenter-icon/` (A Play, B Laser pointer, C Screen;
  `preview.png` compares them with today's icon, light and dark, down to 16 px). Chosen: A, which keeps the
  SlideMage card stack and puts a play mark on the front card. The chosen one also needs `.ico` (Windows) and
  `.icns` (macOS) versions.
- Measure size and start time; record them here. If still too large, look at PyMuPDF (the largest remaining part)
  and UPX for the Qt libraries.

Done in v0.13.2: `packaging/slidemage_presenter.spec` and `packaging/launch_presenter.py`, icons from
`tools/make_presenter_icons.py`. A folder build only, no one-file exe and no splash.

**Building SlideMage Presenter**

    pyinstaller --noconfirm packaging/slidemage_presenter.spec      # from the repo root, about 1 minute

Output: `dist/SlideMagePresenter/` with `SlideMagePresenter.exe` and `_internal/`. `SlideMagePresenter.exe --self-test`
prints its result and exits 0 (also from a windowed exe). `python tools/make_presenter_icons.py` renders
`assets/presenter-icon.svg` into `presenter-icon.ico`, `.icns` and `-256.png` (committed; re-run after the SVG
changes). With `SLIDEMAGE_PRESENTER_TIMING=1` (and `SLIDEMAGE_PRESENTER_TIMING_FILE=<path>`) the program shows the
start window, writes the seconds since the process was created and quits, without writing any settings.

Measured on Windows 11, Python 3.13, PySide6 and PyMuPDF as pinned:

| Build | Unpacked |
|---|---|
| Entry point only, no strip | 148 MiB |
| Without Qt Quick/Qml/Pdf/Network/OpenGL/DBus libraries, Pillow (11 MB), ssl, Direct2D and minimal platform plugins | 111 MiB |
| Without 28 of 37 font files (9 MB) and `_hashlib` with libcrypto (5 MB) | **99 MiB**, 139 files |

Zipped: 44 MiB. Largest files: `mupdfcpp64.dll` 25 MiB, `_mupdf.pyd` 12.5 MiB, `Qt6Core.dll` 9.9 MiB, `Qt6Gui.dll` 9.1 MiB,
`Qt6Widgets.dll` 6.2 MiB; PyMuPDF is 37 MiB of the total and PySide6 41 MiB. Start window shown, counted from the
process's creation: 0.58 s on the first run, 0.36 to 0.38 s on three warm runs (targets: under 2 s and under 1 s).
Qt's translations, `opengl32sw.dll` and `d3dcompiler_47.dll` were not collected in the first place (PySide6's hook only
adds them for QML/OpenGL modules); the spec still filters them for other platforms and PySide6 versions. The further
saving, if wanted: PyMuPDF's DLLs are about 38 MiB and not strippable; UPX on the Qt libraries was not tried.

Note for step 4: the step 3 build excludes `ssl`/`_ssl` (and `_hashlib`) to stay under 100 MB. The Presenter's
self-update downloads from GitHub over HTTPS, so step 4 must put `ssl` back (about 6 MB) and test an update
from the frozen build.

### 4. Release and updates

- `release.yml`: build the Presenter in the same matrix, run its `--self-test`, attach
  `SlideMagePresenter-windows.zip`, `SlideMagePresenter-linux.zip` and `SlideMagePresenter-macos.zip` to the same
  release.
- macOS (in scope, Presenter only; SlideMage itself has no macOS build): a `macos-latest` runner (Apple silicon),
  PyInstaller's `BUNDLE` step makes `SlideMage Presenter.app`. Things to settle in this step:
  - Code signing and notarisation: an unsigned app downloaded from the web is blocked by Gatekeeper and must be
    opened with right-click → Open (or `xattr -d com.apple.quarantine`). Signing needs an Apple Developer account
    (99 USD a year). Ship unsigned first, with that instruction on the download page, and decide on an account
    later.
  - Intel Macs: an Apple-silicon build does not run on them. A second `macos-13` (Intel) runner, or a universal2
    build if PyMuPDF and PySide6 wheels allow it.
  - `keep_awake.py` needs a macOS branch (`caffeinate -d -w <pid>` or IOKit's power assertion); screens and full
    screen across two displays need testing on a real Mac with a projector.
  - Self-update on macOS replaces the `.app` folder; `updater.py` gets a macOS asset name.
- `updater.py`: a third flavour with those asset names, so the Presenter can update itself the same way; same
  version number as SlideMage.
- Changelog: one `CHANGELOG.md`, as now. Entries that change presenting already say so; the Presenter's update
  notice can show just those (a tag in the entry, decided in this step).
- CI: a size check (fail if the Presenter folder grows past a limit, e.g. 120 MB) so a stray import cannot
  silently bring QtWebEngine back.

### 5. Presenter-only polish (optional, later)

**5a. "Open with SlideMage Presenter" for PDFs.** Double-clicking a PDF or right-click → Open with should be able to
start the Presenter.
- macOS: comes almost free. The `.app`'s `Info.plist` declares that it opens PDFs (`CFBundleDocumentTypes`), and
  it appears under Open With. The file arrives as a Qt `QFileOpenEvent`, not as a command-line argument, so step 2's
  entry point must handle that event too.
- Windows: the Presenter is unpacked from a zip, not installed, so nothing registers it. A button in the start
  window, "Offer SlideMage Presenter for PDFs", writes the per-user registry keys
  (`HKCU\Software\Classes\Applications\SlideMagePresenter.exe` and an `OpenWithProgids` entry for `.pdf`). No admin
  rights are needed and the default PDF viewer is not changed: it only adds the Presenter to Open with. A second
  button removes it. If the folder is moved, the keys point to the old place, so the start window re-checks them.
- Linux: the `.desktop` file gets `MimeType=application/pdf;`.

**5b. Slide numbers and reveal steps without a project.** A beamer slide with reveals (`\pause`, `\only<2>`, …)
becomes several PDF pages, one per step. When SlideMage presents a deck from a project, it reads beamer's `.nav`
file from the compile records (`presentation/frames.py`) and so knows which pages belong together. The presenter
then shows "Slide 5 / 20 · step 2 / 3", and "Go to slide" takes a slide number. A PDF opened on its own has no
`.nav` next to it, so the Presenter can only show "Page 37 / 112" and jump by page. The fixes, cheapest first:
- Beamer normally sets PDF page labels to the frame number, so all steps of slide 5 carry the label "5". If the
  presenter PDFs SlideMage produces have them (to be checked on a real presenter PDF, as the repo holds no
  compiled deck), the frame map can be built from the labels with PyMuPDF (`page.get_label()`), with no change to
  the compile, and it works for most beamer PDFs from other people too.
- If not: SlideMage's Presenter compile embeds the `.nav` (or just the frame list) in the PDF as a small attached
  file, and the Presenter reads it from there.
SlideMage's own "Present a PDF…" gains from the same change.

**5c. Continue where you stopped, in both programs.** When a presentation ends (or the program is closed or
crashes mid-talk), the place is remembered; presenting the same deck again asks "Continue at slide 23 (Results)?"
with "Continue" and "Start from the beginning". For a lecture continued after a break or the next week.

- *Which deck counts as "the same":* the Presenter keys by the PDF's full path, so a PDF recompiled under the same
  name is still the same deck. SlideMage keys by the project and the deck file, so it does not matter which PDF
  (presenter, plain, language variant) is shown.
- *Finding the slide again after a recompile:* a page number alone would be wrong as soon as a slide was added or
  removed before it. So the place is stored as the slide number (from the frame map of 5b; the page number when
  there is none) together with a fingerprint of that slide: its title and a short hash of its text. On reopening:
  1. the slide at the stored number still has that fingerprint → continue there;
  2. otherwise the slide with that fingerprint elsewhere in the deck (the nearest one, if it is there twice) →
     continue there, the question naming the new number;
  3. otherwise (the slide was changed or deleted) → offer the stored number, saying the slide has changed.
  Always on the first step of that slide, not in the middle of its reveals.
- *Not offered* when the stored place is slide 1 or the last slide (the talk was finished), or older than a set time
  (default 30 days).
- *Shared code:* the remembering and the matching live in `presentation/resume.py` (no Qt, no project imports, unit
  tested); the controller saves the place, both entry points ask the question. A setting on the presentation
  settings page turns the question off ("Always start at the beginning").
- *Stored* per user and machine with the other presentation settings, at most the last 50 decks; never in the PDF
  or the project, so it does not travel through the sync.

Done in v0.12.2 (`presentation/resume.py`, `ui/presentation/resume_ui.py`). The place is worked out whenever
the slide changes, because the controller closes the PDF before `finished` fires; it is written after 1.5 s on a
slide and when the talk ends.

This is not Presenter-only: it can be done in SlideMage first (it needs no part of steps 1–4) and comes to the
Presenter with the shared code.

## Development workflow afterwards

- Presenter features are developed in SlideMage as now, in `presentation/` and `ui/presentation/`, and tried in
  either program (`slidemage` or `slidemage-presenter` from the dev venv).
- The import-boundary test and the CI size check tell a developer at once when a change would make the Presenter
  heavy; the fix is a lazy import or moving the project-specific part out of the presenter modules.
- Nothing is ported by hand, nothing is merged between forks.

## Open questions

Decided 2026-10-31:
- The name is "SlideMage Presenter".
- macOS is in scope (step 4), shipped unsigned: no Apple Developer account for now.
- Icon: draft A (Play).
- 5a, 5b and 5c are approved as described; 5c also in SlideMage itself.
- Nothing is implemented without the user's explicit go, step by step.
- SlideMage keeps its own built-in presentation mode; it does not hand over to the Presenter program (both run the
  same code).
- The work starts after the framework redesign is finished and merged, because step 1 touches `ui/kit/theme.py`,
  which the redesign also changes.

Handover for the session that does the work: `docs/Handover_2026-10-31-SlideMage-Presenter.md`.
