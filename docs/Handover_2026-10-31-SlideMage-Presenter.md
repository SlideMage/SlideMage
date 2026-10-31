# Handover: SlideMage Presenter

Written 2026-10-31 for the session that builds SlideMage Presenter, to be started once the framework redesign
(`docs/Handover_2026-10-26-Framework-Redesign.md`) is finished and merged into `develop`. Nothing of this work has
been implemented yet.

## 1. What and why

**SlideMage Presenter** is a second, small program built from the SlideMage repository. It presents a PDF without a
project: a SlideMage presenter PDF with its notes, or any plain PDF. It must start quickly, be small, and get every
improvement to SlideMage's presentation mode with no porting.

The authoritative plan is **`docs/plans/presenter-app.md`**. Read it in full before anything else; this handover
adds the decisions, the working rules and what to check first. Where the two disagree, the plan wins on content
and this handover on process.

## 2. Decisions already made by the user

| Topic | Decision |
|---|---|
| Approach | One repository, two build targets. **No git fork.** The Presenter is a second entry point and a second PyInstaller spec; the build leaves out what the entry point never imports. |
| Name | "SlideMage Presenter"; executables `SlideMagePresenter.exe` (Windows), `SlideMage Presenter.app` (macOS), `SlideMagePresenter` (Linux). |
| Icon | Draft **A (Play)**: `docs/plans/presenter-icon/a-play.svg`. SlideMage's three-card stack with a play triangle on the front card; dark mode via the same `prefers-color-scheme` block as `src/slidemage/assets/icon.svg`. Still needs `.ico` and `.icns` versions. B and C were rejected; their files and `preview.png` may be deleted when A is moved into `assets/`. |
| Platforms | Windows, Linux, **and macOS**. SlideMage itself stays without a macOS build. |
| Apple Developer account | **None for now.** The macOS build ships unsigned; the download page and the release notes say to open it once with right-click → Open. |
| Plan step 5a | Approved: "Open with SlideMage Presenter" for PDFs on all three platforms. |
| Plan step 5b | Approved: slide numbers and reveal steps without a project (page labels first, embedded frame list as fallback). |
| Plan step 5c | Approved, **in both programs**: remember where a talk stopped and offer to continue there, also after the deck was recompiled under the same name (slide number plus a fingerprint of the slide; see the plan). |
| SlideMage's own presentation mode | Stays. SlideMage does not start the Presenter program; both run the same code. |
| Timing | After the framework redesign is merged into `develop`. |

## 3. Working rules (from the user, standing)

- **Nothing is implemented without the user's explicit go.** A "yes" covers one step only. Plans, drafts and
  documents are fine without asking.
- **Stop after each step** and report; the user checks usage before saying go.
- Answers and plans first, then implementation. Use sub-agents only where they save tokens.
- Each step is its own branch and PR into `develop`. Ask before merging, and run `gh pr merge …` as a plain command
  (not in a loop, not after `cd`).
- Work in a worktree, never on the main checkout: the real Slidemaster project compiles against the main
  checkout's `latex/`.
- Every app-code change bumps `VERSION_NUMBER` in `src/slidemage/version.py` and adds a `CHANGELOG.md` entry in the
  same commit. No parentheses inside the entry's reason. Check it with
  `PYTHONIOENCODING=utf-8 PYTHONPATH=src python packaging/release_notes.py --previous <prev tag> <new version>`.
- Any new TeX name starts with uppercase `SM` + CamelCase (relevant only if 5b's fallback adds a TeX macro).
- New handovers go to `docs/Handover_YYYY-MM-DD-Speaking-Label.md`, one per topic.

## 4. Environment

- Build and test venv: `C:\Users\ms\SlideMage\venv` (Python 3.13, PySide6, PyInstaller). Do not create another.
  It has SlideMage installed editable from the **main** checkout, so in a worktree always run
  `PYTHONPATH="$(pwd -W)/src" C:/Users/ms/SlideMage/venv/Scripts/python.exe -m pytest tests -n auto`, and check
  PyInstaller's `Analysis-00.toc` to make sure it bundled the worktree's code.
- Before a build, compare `pyproject.toml`'s dependencies with `pip list` in the venv.
- Scripts that open real windows outside pytest write to the user's real `%APPDATA%\SlideMage\layout.json`: patch
  `layout_settings.STORE_PATH` first. This matters more here, since the Presenter shares that settings file.
- SlideMage's folder build for comparison: `SLIDEMAGE_BUILD=folder …/pyinstaller.exe --noconfirm
  packaging/slidemage.spec` → `dist/SlideMage-folder/` (655 MB on 2026-10-31).
- macOS and Linux can only be built and tested on GitHub Actions runners unless the user has a machine; ask before
  relying on one. A real two-screen test (laptop and projector) on macOS needs the user.

## 5. First: check the plan against the code after the redesign

The plan was written against `develop` at 6d1fbf8c (v9.4.1). The redesign touches a lot, so before step 1:

1. Re-check the coupling table in the plan ("Where the code stands today"): re-run the import listing over
   `src/slidemage/presentation/` and `src/slidemage/ui/presentation/`, and the imports of `ui/kit/theme.py`,
   `ui/kit/widgets.py`, `ui/layout_settings.py`, `app_settings.py`, `project.py`. Update the table where it changed.
2. Check that "Present a PDF…" on the start screen (`cli.py` → `ui/presentation/launch.py:present_pdf_file`) still
   exists and works; it is the code path the Presenter grows from.
3. Measure a baseline: how long `python -c "import slidemage.ui.presentation.launch"` takes and which heavy modules
   it pulls in (`python -X importtime`). Record it in the plan.
4. Check whether a real SlideMage presenter PDF carries beamer's page labels (needed for 5b): compile one deck's
   Presenter PDF, then `pymupdf.open(path)[i].get_label()` for the first pages. All reveal steps of one frame
   should share a label. Record the result in the plan; it decides 5b's approach.
5. Report the findings and the proposed step order to the user, then wait for the go.

## 6. Proposed step order

The plan numbers the steps 1–5. Suggested order of the PRs, each with its own go:

1. **Step 1**: cut the remaining links, import-boundary test. No behaviour change.
2. **Step 5b**: slide numbers without a project. It helps SlideMage's "Present a PDF…" at once, and 5c needs it.
3. **Step 5c**: continue where you stopped, in SlideMage. Shared module `presentation/resume.py`.
4. **Step 2**: the Presenter entry point (`presenter_app.py`, start window, recent PDFs, `--self-test`, macOS
   `QFileOpenEvent`, 5c's question in the start path).
5. **Step 3**: the PyInstaller spec, icon A in `assets/` with `.ico`/`.icns`. Measure size and start time against
   the goals (under 100 MB unpacked, window under 1 s warm / 2 s cold).
6. **Step 4**: release workflow for Windows, Linux and macOS (unsigned), updater flavour, CI size check, macOS
   keep-awake.
7. **Step 5a**: "Open with" on all three platforms.

The user may reorder; 5b and 5c need nothing from steps 2–4.

## 7. Things to watch

- **Shared settings file.** Both programs read and write the same `layout.json` (presentation settings, and 5c's
  remembered places). They may run at the same time. Writes must stay atomic, and a program must re-read before
  writing instead of overwriting the whole file with what it loaded at start, or one program wipes the other's
  changes.
- **One-file vs folder build.** The one-file exe unpacks itself on every start, which defeats the fast start. The
  folder build is the main asset. Offer a one-file build only if the user asks for it.
- **PyMuPDF stays below 2.0** (`pymupdf<2` in `pyproject.toml`): 2.0 loads a layout model at import that
  PyInstaller does not bundle. The Presenter's `--self-test` in the release workflow guards this as SlideMage's does.
- **Keep the presenter modules clean.** The import-boundary test from step 1 is the guard. When it fails later, the
  fix is a lazy import or moving project-specific code out of `presentation/`, never loosening the deny list
  without asking.
- **Frame-map naming.** In the code, "frames" are beamer frames (slides) and their reveal steps, from beamer's
  `.nav` file (`presentation/frames.py`). They are not the picture frames in `assets/frames`.
- **macOS specifics:** Gatekeeper on an unsigned app, Apple silicon vs Intel (a second runner or universal2),
  `keep_awake.py` has no macOS branch yet, the updater replaces a `.app` folder.

## 8. Files

| File | State on 2026-10-31 |
|---|---|
| `docs/plans/presenter-app.md` | The plan with all decisions, **uncommitted** in the main checkout |
| `docs/plans/presenter-icon/a-play.svg` | Chosen icon draft, uncommitted |
| `docs/plans/presenter-icon/b-pointer.svg`, `c-screen.svg`, `preview.png` | Rejected drafts and the comparison sheet, uncommitted |
| `docs/Handover_2026-10-31-SlideMage-Presenter.md` | This file, uncommitted |

Commit the plan, the icon and this handover first (on a branch, with the user's go), so the work branches have them.
