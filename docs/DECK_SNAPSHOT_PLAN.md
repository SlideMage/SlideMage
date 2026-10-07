# Deck snapshots: a frozen, self-contained copy of a deck

Status: implemented in SlideMage v5.33.0 (2026-10-07); see "Implementation
status" right below for what differs from this plan.
Date: 2026-10-07. Revised the same day: a new **Decks** menu (with
*Create deck snapshot…* and *Import PPTX/ODP…*), a dialog that takes several
decks, a snapshot prompt when archiving, and output into `snapshots/` (out of
git), with names carrying the date and time, several snapshots allowed per
deck, and a question on each run about deleting older ones.

## Implementation status (v5.33.0)

Code: `src/slidemage/deck_snapshot.py` (core and command line),
`qt_snapshot_dialog.py`, `qt_gui.py` (Decks menu, run, archive question,
banner), `project.py` (`snapshot_info`, `snapshot_compile_env`), `compiler.py`
(snapshot mode), guards in `compat.py`, `bundled_copies.py` and `cli.py`.
Tests: `tests/test_deck_snapshot.py`, `tests/test_deck_snapshot_gui.py`.

Built as planned: phases 1 and 3, and from phase 4 the app copy. Not built
from phase 4: a cited-entries-only bibliography, editable media sources and
transcripts (the command line has no `--bib`, `--sources`, `--transcripts`).
The command line also has no `--versions` (always every version) and no
`render` subcommand: the snapshot's own `render.bat`/`render.sh` render it;
`create`, `verify` and `list` exist.
Where it differs:

- **Read-only editing and "Unfreeze…" were not built.** A snapshot opened
  in SlideMage shows a banner saying edits change the snapshot; SlideMage
  itself never changes it. `verify` detects edited or missing files from the
  manifest's hashes.
- **"Include LaTeX package files" stores the files; it doesn't use them.**
  They go to `texmf/` (with the fonts the PDFs embed, found with kpsewhich,
  because fonts don't appear in the `.fls`), and `texmf/README.txt` explains
  how to put them on the search path by hand. The render scripts and
  SlideMage compile with the installed TeX. Tested by hand on the manual:
  with `TEXINPUTS`/`LUAINPUTS`/`OPENTYPEFONTS` pointing at `texmf//`, 323 of
  the files read came from the copy and the PDF was identical; fonts still came
  through luaotfload's database of the installed TeX.
- **Which compiles:** every version and the presenter PDF; per-chapter PDFs
  are not captured. The footer timestamp and the appendix TOC follow the
  main window's toolbar checkboxes, as for an ordinary compile.
- **Open decisions, taken as the exact option:** alt-text store, bibliography
  and `slide_ids.csv` are copied whole; reference PDFs on; app off by default;
  uncommitted changes allowed and recorded in the manifest.
- **Stricter than an ordinary compile:** a reference compile whose biber run
  failed is rejected. This was found in testing: a full disk made biber
  fail, and the compile still produced a PDF with the citation as its key.
- Verification builds go to the project's `.build/`, not `%TEMP%`. Git for
  Windows' perl, which runs latexmk, maps `%TEMP%` to `/tmp`, a path the native
  TeX engine can't resolve.

Tested end to end on the SlideMage manual (all three versions and the
presenter PDF, about 30 minutes): the snapshot rendered from its own folder
matches the reference PDFs.

## Objective

Add **Decks → Create deck snapshot…** to SlideMage. It exports one or more
decks into stand-alone snapshots, one per deck, in the project's `snapshots/`
folder. Each snapshot is a folder or a zip file. It holds everything needed
to compile that deck later exactly as it compiled on the day of the snapshot:

- the deck's `.tex` file and any fragments it `\input`s;
- every slide file it uses, as it is on the day of the snapshot;
- every media file and snippet those slides use;
- the institution preamble, project macros and scheme assets;
- the bibliography and the alt-text store;
- the LaTeX framework (`SlideMage/latex`);
- `.latexmkrc`, a render script and a manifest;
- optionally, the SlideMage executable of the day and the PDFs built at
  snapshot time.

Later edits to the project, new SlideMage releases (including BREAKING ones)
and framework changes must not affect a snapshot.

Archiving a deck also offers a snapshot first, because that is when a deck
stops being maintained (see "Archiving a deck").

## What "exactly as it was" can and cannot promise

| Layer | Frozen by the snapshot? | How |
|---|---|---|
| Project content (deck, slides, media, snippets, bib, alt text) | Yes | Copied |
| LaTeX framework (`Slidemaster_preamble_base.tex`, Gotham `.sty`, `.lua`) | Yes | Copied |
| SlideMage app | Optional | Copied exe (Windows only, ~90 MB) + version/commit recorded |
| Footer compile timestamp, PDF dates | Yes | Seeded `.timestamp` files + `SOURCE_DATE_EPOCH` (see below) |
| TeX distribution (MiKTeX packages, fonts, LuaTeX engine, format) | **Only partly** | Always recorded; package files optionally vendored (tier 2) |
| Reference output | Yes | Built PDFs included (optional, on by default) |

The engine and the LaTeX format file (`lualatex.fmt`) cannot be shipped in a
portable way. Making a snapshot fully immune to TeX-distribution changes
would need a pinned distribution, such as a TeX Live ISO or a container
image. That is outside this feature. The design mitigates the risk in three
ways:

1. It records the full TeX environment, so a later render can say exactly
   what differs.
2. It can vendor package files (tier 2).
3. It always ships the reference PDFs, so the deck *as it was* survives even
   if a future TeX can no longer render it.

## Confirmed starting point (2026-10-07)

How a deck finds its files today:

- **Decks** (`decks/<name>.tex`) `\input{Slidemaster_preamble_<inst>}`. They
  fall back to the project root through `\input@path{{../}}` and
  `\graphicspath{{../}}`.
- **The framework** is found through `TEXINPUTS`. `.latexmkrc` (and its copy
  in `decks/.latexmkrc`) adds the project root and
  `$ENV{SLIDEMASTER_LATEX} // <root>/../SlideMage/latex`. So the project
  expects the framework in a **sibling** `SlideMage/latex` folder, unless the
  environment variable is set.
- **Slides** are referenced as `\slide{id-slug}` → `slides/<id>-current.tex`
  and `\slideversion{…}{X}` → `slides/<id>-vX.tex`, plus `\slidestep`,
  `\conditionalslide` and `\omitslide`. `unused_content.py` already has the
  complete macro list.
- **Media** is mostly a literal `media/<name>`, sometimes without an
  extension. A vector source (`.svg`) sits next to the derived `.pdf` in a
  "stem group" (`unused_content.py`).
- **Snippets** (`snippets/<id>-N.tex`) are loaded by `\SMCodeFile` through
  the TeX search path.
- **Alt text**: `Slidemaster_alt.lua` is found through `kpse`, but it reads
  `media/alt-text.csv` with plain `io.open`. latexmk's `-recorder` (`.fls`)
  does **not** see that read.
- **Bibliography**: `\SMUseBibliography` + biber read `Slidemaster.bib`
  through `BIBINPUTS`. biber's reads are not in the `.fls` either; the
  `.bcf` and `.blg` name them.
- **Footer timestamp**: computed with `os.date("*t")` and cached in
  `.build/<jobname>.timestamp`. `compiler.py` deletes that file before every
  job. `SOURCE_DATE_EPOCH` alone does **not** freeze it, but a pre-seeded
  `.timestamp` file does.
- **`\deckoutputfolder{D:/…}`** holds absolute paths. They are meaningless
  inside a snapshot and must be ignored there.
- **On open, SlideMage changes projects on its own.** `compat.py` can migrate
  files, and `bundled_copies.py` replaces framework and manual files with the
  bundled versions. Both are wrong for a snapshot and must be switched off
  there (see "Snapshot mode").
- **Sizes**: `media/` is 218 MB for the whole project. A deck uses a
  fraction of it. The framework is about 1 MB.

## Snapshot layout

The snapshot mirrors today's sibling layout, so **no copied file needs
rewriting**. The unchanged `.latexmkrc` finds `../SlideMage/latex` on its own.

```
<project>/snapshots/t-Uni-FM2-2027s_2026-10-07_14-12/   (or …_14-12.zip with the same tree)
├── README.txt                    how to render, what's inside, environment recorded
├── render.bat / render.sh        sets SOURCE_DATE_EPOCH, runs latexmk per version
├── snapshot.json                 manifest (below)
├── reference-pdf/                PDFs built at snapshot time (optional, default on)
│   ├── t-Uni-FM2-2027s-instructor.pdf
│   └── …
├── app/                          optional: SlideMage.exe of the day (+ version.txt)
├── SlideMage/
│   └── latex/                    the framework, copied verbatim
├── texmf/                        optional: LaTeX package files (dialog checkbox, tier 2)
└── Slidemaster/                  the project subset, same relative paths as the source
    ├── .latexmkrc, decks/.latexmkrc
    ├── .slidemage/project.json   includes "snapshot": {…}
    ├── .build/<jobname>.timestamp   seeded so footers show the original time
    ├── slide_ids.csv             trimmed to the ids in use (keeps it a valid project)
    ├── Slidemaster_preamble_uni-graz.tex, Slidemaster_project_macros.tex
    ├── Slidemaster.bib           full by default, or only cited entries
    ├── decks/t-Uni-FM2-2027s.tex (+ any \input fragments)
    ├── slides/…  snippets/…  media/…  schemes/scheme_uni_graz/…
    └── transcripts/…             optional
```

The inner folder takes the source project's folder name, so error messages
and log paths look the same. `SlideMage/latex` keeps its name because
`.latexmkrc` depends on it.

## Manifest (`snapshot.json`)

```json
{
  "snapshot_format": 1,
  "created": "2026-10-07T14:12:03+02:00",
  "deck": "decks/t-Uni-FM2-2027s.tex",
  "versions": ["instructor", "during-course", "after-course", "presenter"],
  "options": {"appendix_toc": true, "footer_timestamp": true, "bib": "full",
              "app_included": true, "texmf_vendored": false},
  "slidemage": {"version": "v5.32.3", "commit": "e01db58", "dirty": false},
  "project":   {"name": "Slidemaster", "commit": "cf988c0", "dirty": true,
                "dirty_files_in_snapshot": ["slides/…-current.tex"]},
  "tex": {"engine": "LuaHBTeX 1.22.0", "format": "LaTeX2e <2026-06-01>",
          "distribution": "MiKTeX 26.x", "latexmk": "4.8x", "biber": "2.2x",
          "packages": {"beamer": "2026/…  v3.7x", "pgfplots": "…", "…": "…"},
          "files": [{"path": "…/fira/FiraSans-Light.otf", "sha256": "…"}]},
  "source_date_epoch": 1791367923,
  "timestamps": {"t-Uni-FM2-2027s-instructor": "2026-10-07 14:12"},
  "files": [{"path": "Slidemaster/slides/…", "sha256": "…", "bytes": 1234,
             "origin": "project|framework|texmf|generated"}],
  "reference_pdfs": [{"path": "reference-pdf/…", "sha256": "…", "pages": 212}]
}
```

`files` lets SlideMage, or anyone, check that a snapshot is intact (`verify`).

## How the files are found: compile, then cross-check

Static scanning alone misses things: `\IfFileExists`, files without an
extension, `\input` inside macros, and Lua reads. A compile alone misses
biber and the Lua `io.open` read. So the snapshot uses both.

1. **Recorded compile, authoritative.** Compile each selected version through
   the normal `compiler.CompileJob` path, with latexmk `-recorder` and a
   private `$aux_dir`, and keep the `.fls`. Every `INPUT` line is sorted into:
   - *project*: under the project root → copied, same relative path;
   - *framework*: under the `SlideMage/latex` in use → copied;
   - *TeX distribution*: anything else → recorded (path, sha256, and the
     version from the `.log` `Package:`/`File:` lines), and copied only with
     tier 2;
   - *build artifacts* (`.aux`, `.nav`, `.toc`, `.bbl`, `.timestamp`, …) →
     ignored, except `.timestamp`, which is kept for seeding.
2. **Things the recorder misses**, added explicitly:
   - `media/alt-text.csv` and `.json`, filtered to rows for images that are
     copied, or copied whole (open decision 2);
   - bib files named in the `.bcf`/`.blg`;
   - `slide_ids.csv` (trimmed), `.latexmkrc` and `decks/.latexmkrc`;
   - `.slidemage/project.json` (rewritten, see below).
3. **Static cross-check, warnings only.** Run `unused_content`'s
   slide/media scan, limited to this deck, and `deck_scan`'s fragment
   detection. If a file shows up statically but not in the recorded compile,
   for example a slide used only in a version that wasn't selected, report it
   and offer to include it. If a file shows up in the compile but not
   statically, include it silently: the compile wins.
4. **Optional extras**:
   - editable sources: the stem-group siblings of each used media file (the
     `.svg` next to the `.pdf`), and `tikz_render` sources;
   - transcripts;
   - **all** versions of the slides used (`-vX.tex`), not only the referenced
     ones.

Versions: compile every selected version, because `\conditionalslide` and
student versions differ. The union of their `.fls` files is the file set.
Including the presenter or appendix-TOC variants follows the deck's own
settings in `deck_settings.py`.

The compile in step 1 is also the reference compile. Its PDFs go to
`reference-pdf/` and its `.timestamp` files are seeded.

## Freezing the time

- The footer stamp is pre-seeded in `Slidemaster/.build/<jobname>.timestamp`
  from the reference compile. The preamble already reads that cache first
  (`\IfFileExists{\jobname.timestamp}` …), so a snapshot render shows the
  original stamp and needs **no framework change**. The render scripts must
  not delete it, unlike `compiler.py`. If the reference compile ran with the
  timestamp turned off, the setting is kept instead.
- `render.bat` / `render.sh` export `SOURCE_DATE_EPOCH=<epoch>` and
  `FORCE_SOURCE_DATE=1`, so PDF `/CreationDate`, `/ModDate`, `/ID` and
  `\today` match the reference.
- The wrapper `\def`s for each version (`\deckversionoverride`,
  `\SMPresenterModeOverride`, `\SMAppendixTocOverride`,
  `\SMFooterTimestampOverride`) are written as small `wrap-<version>.tex`
  files into `Slidemaster/decks/`. They come from `compiler._wrapper_text()`
  itself, so the snapshot renders the same way SlideMage compiled. For
  appendix-TOC decks, `_wrapper_text` inlines a generated appendix. That
  generated text is frozen into the wrapper, which is exactly what we want.

## TeX distribution tiers

- **Tier 1, default: record and compare.** `snapshot.json.tex` lists the
  engine, format, distribution and latexmk/biber versions, plus each package
  file's version and hash. Before rendering, `render.*` and SlideMage's
  "Render snapshot" compare them with the local TeX and list the
  differences. After rendering, they compare pages against `reference-pdf/`
  (see Verify).
- **Tier 2, opt-in: the dialog's "Include LaTeX package files" checkbox.**
  Every TeX-distribution file in the union `.fls` (`.sty`, `.cls`, `.def`,
  `.lua`, `.otf`, `.tfm`, …) is copied into a TDS-shaped `texmf/`. Expected
  size: tens of MB, mostly Fira fonts and pgf. What happens to the copied
  files depends on a **spike, done before the dialog ships**:
  - *Spike succeeds* → the files are **active**. `.latexmkrc` gets a
    `SLIDEMASTER_SNAPSHOT_TEXMF` hook, a small, backward-compatible framework
    change. It puts `texmf/` first on the search path, so a snapshot renders
    with its own package versions.
  - *Spike fails* → the files are **stored only**. They are kept in the
    snapshot as an exact record, for a manual reinstall or a diff, but not
    put on the search path. The checkbox stays, and its tooltip says so.

  The spike answers three questions: does MiKTeX's kpathsea honor
  per-process `TEXINPUTS`/`LUAINPUTS`/`OPENTYPEFONTS` over its own roots;
  does luaotfload's font cache pick up vendored fonts; and do vendored
  package files work with a *different* format file (`latex.ltx` version
  skew)? Where they don't, active vendoring would make things worse than
  tier 1.
- **Out of scope**: shipping the engine/format, or a whole portable MiKTeX.
  `README.txt` names the recorded MiKTeX version for anyone who needs to
  reinstall it.

## The SlideMage executable (optional)

- **Include**: copy the running app's own exe (or the `dist\SlideMage.exe`
  release build) to `app/SlideMage.exe`, plus `app/version.txt` and the
  version-history entry. Started with `--project <snapshot>/Slidemaster`, it
  opens the snapshot with the same app that made it.
- **When run from source (venv)**: offer `git archive` of the SlideMage
  commit instead, as `app/SlideMage-src-<version>.zip`, or record the commit
  only.
- Rendering never *needs* the app. `render.*` is plain latexmk.

## Snapshot mode in SlideMage

A snapshot is a valid project (it has `slide_ids.csv`), so SlideMage can open
it. `.slidemage/project.json` gets:

```json
"snapshot": {"of": "decks/t-Uni-FM2-2027s.tex", "created": "…", "read_only": true}
```

When that key is present:

- `compat.py`: no startup dialog and no migrations. Info → Project
  compatibility explains that snapshots are frozen.
- `bundled_copies.py`: never offers framework or manual updates.
- `compiler.py`: ignores `\deckoutputfolder` (PDFs go to `Slidemaster/pdf/`),
  never deletes the seeded `.timestamp`, and exports `SOURCE_DATE_EPOCH`.
- The project's `format`/`last_app_version` bookkeeping is not updated.
- The editor is read-only by default, with a banner: "Snapshot of … taken
  2026-10-07 with SlideMage v5.32.3". **Unfreeze…** removes the flag, turning
  the snapshot into an ordinary, editable fork.
- A newer SlideMage opening an older snapshot does the same: the snapshot
  stays as it was. Rendering it uses the snapshot's own `SlideMage/latex`,
  because `.latexmkrc` resolves the sibling. `SLIDEMASTER_LATEX` must
  therefore be **unset** for snapshot compiles: SlideMage clears it in
  `_build_env()`, and `render.*` clears it explicitly.

`project.PROJECT_FORMAT` does not change. The key is additive, and older apps
ignore it.

## Output: folder or zip

- **Name**: `<deck>_<YYYY-MM-DD>_<HH-MM>`, the deck's name (without `.tex`)
  plus the local date and time the snapshot was started, for example
  `t-Uni-FM2-2027s_2026-10-07_14-12`. There are no colons, because Windows
  doesn't allow them in names. The names sort by deck, then
  chronologically. An archived deck gets the same name pattern.
- **Folder**: `snapshots/<name>/`. It is written to a temporary sibling
  (`snapshots/.partial-<name>/`) and renamed when complete, so a cancelled
  run leaves nothing half-written.
- **Zip**: `snapshots/<name>.zip`. It is built from the `.partial-<name>/`
  folder, which is then removed. The zip is deterministic: sorted entries,
  fixed mtimes, and `snapshot.json` first, so the same inputs give the same
  bytes. `ZIP_DEFLATED`; media is already compressed. Inside, the tree
  starts at `<name>/`, so extracting it gives exactly the folder form. On
  open, SlideMage accepts a snapshot zip directly: it extracts next to the
  zip and opens the project.
- **Several snapshots per deck.** Any number of snapshots of one deck can
  coexist, in folder form, zip form, or both. A folder and a zip from the
  same minute differ by extension and don't clash. A second snapshot of the
  same form within the same minute gets `_2`, `_3`, … appended.
- **Deleting older snapshots: always asked, never automatic.** Before a run
  starts (from the dialog or the archive prompt), SlideMage looks for
  existing snapshots of the selected decks. A snapshot belongs to a deck
  when its `snapshot.json` names that deck; the name prefix is not trusted.
  If there are any, it asks once for the whole run:

  ```
  Older snapshots exist
  t-Uni-FM2-2027s    2026-09-30 10-05  folder   212 MB
                     2026-10-02 16-40  zip      148 MB
  t-Uni-IA2-2026w    2026-09-12 09-20  folder   180 MB

  Delete these older snapshots once the new ones have been created?

        [Delete old snapshots]   [Keep them]   [Cancel]
  ```

  - **Delete old snapshots** removes a deck's older snapshots only *after
    that deck's new snapshot has been written and verified*. If the new one
    fails or is cancelled, that deck's older snapshots stay. "Older" means
    the ones listed in this question; anything created in the meantime is
    left alone.
  - Deletion goes to the **Recycle Bin** (`QFile.moveToTrash()`), so a
    mistake can be undone; it is never a permanent delete. If the trash is
    unavailable (for example on some network drives), that snapshot is kept
    and the log says so.
  - The result dialog and the log list what was deleted.
  - CLI: older snapshots are kept unless `--delete-old` is given, which uses
    the same trash function (it needs `PySide6.QtCore` only, not a GUI).
- **Destination**: always `<project>/snapshots/`, created on first use.
  There is no destination field.
  - **No recursion.** A snapshot only copies files its reference compile
    *read*, so earlier snapshots are never copied into new ones.
  - **No double counting.** Today `deck_scan` (`decks/`, `decks/archive/`),
    `unused_content` (`slides/`, `media/`) and `sm_rename`'s
    `PROJECT_GLOBS` never look at `snapshots/`. A test pins that down, so a
    future recursive scan can't start finding a snapshot's copies of slides,
    decks or `slide_ids.csv`.
  - **Not in git.** `snapshots/` is in `.gitignore` (decided 2026-10-07). A
    snapshot is a few to a few hundred MB of binary copies of files git
    already tracks. The uniCLOUD sync still backs it up.
  - **Not part of the project's housekeeping.** *Housekeeping* (clean
    `.build`, archive unused content) never touches `snapshots/`.

## Verify

Every snapshot (from the dialog, the archive prompt or the CLI) ends with a
check, on by default:

1. Copy (or extract) the finished snapshot to a scratch folder **with no
   sibling project or framework nearby**, and unset `SLIDEMASTER_LATEX`.
2. Render every version from there with `-recorder`.
3. **Self-containment**: every `INPUT` in the new `.fls` must be inside the
   snapshot or under the TeX distribution. Anything that resolves to the
   source project or the live `SlideMage/latex` is a hard failure.
4. **Fidelity**: page-by-page comparison against `reference-pdf/`. Use the
   same page count, then the PyMuPDF text with the footer `slide id:`, then a
   pixel diff at low DPI (the `compare_render.py` approach). Report any page
   that differs.

The same check is available later as `slidemage snapshot verify <path>`. It
first checks file hashes against `snapshot.json`, then does the render plus
the fidelity steps.

## User interface

### New "Decks" menu

The menu bar becomes **System · Decks · Tabs · Housekeeping · Info**. The
new **Decks** menu sits right after System and holds:

- **Import PPTX/ODP…**, *moved* from System. It is the same action
  (`_on_import_presentation`); only its place changes. System keeps
  *Open Project…*, *Preferences…* and *Exit SlideMage*.
- **Create deck snapshot…**: opens the dialog below.

The `qt_gui.py` docstring that lists the menus is updated to match. The
SlideMage manual slide that shows the menus, and any slide that says
"System → Import PPTX/ODP…", are updated in the same commit. Moving a menu
item changes a habit, not a project or file, so it is a minor-version change
rather than a BREAKING one. The version-history entry still says where the
item moved to.

### "Create deck snapshot" dialog (`qt_snapshot_dialog.py`)

```
┌ Create deck snapshot ───────────────────────────────────────┐
│ Decks                                        [Select all]   │
│ ☑ t-Uni-FM2-2027s                                           │
│ ☐ t-Uni-FMA2-2027s                                          │
│ ☑ t-Uni-IA2-2026w                                           │
│ ☐ …                       (archived decks: [☐ show])        │
│                                                             │
│ Output      (•) Folder   ( ) .zip file                      │
│ ☐ Include LaTeX package files  (≈ +30–80 MB per snapshot)   │
│ ☐ Include SlideMage app        (≈ +90 MB per snapshot)      │
│                                                             │
│ Saved to: <project>/snapshots/                [Open folder] │
│                              [Create snapshots]  [Cancel]   │
└─────────────────────────────────────────────────────────────┘
```

- **Decks**: one checkbox per deck from `deck_scan.scan_decks()`, in the
  deck table's order. Test decks are listed too. Archived decks are hidden
  until *show* is ticked. The decks selected in the deck table start
  checked.
- **Output**: folder or `.zip`.
- **Include LaTeX package files**: tier 2 (see "TeX distribution tiers").
  The tooltip says whether the files are *active* or *stored only*,
  depending on the spike's outcome.
- **Include SlideMage app**: the optional app copy from the original brief.
  Off by default.
- Everything else uses its default and appears only in the CLI: reference
  PDFs on, all of each deck's configured versions, full bibliography,
  filtered alt text, no editable media sources or transcripts, verify on.
- The three settings are remembered in `app_settings.py`
  (`snapshot_output`, `snapshot_texmf`, `snapshot_app`). The archive prompt
  reuses them.
- **Create snapshots** is disabled while no deck is checked, or while a
  compile run is in progress. In that case the existing "Busy" message
  explains why: snapshots compile, and the two must not share `.build/`.

### Several decks: one at a time

The selected decks are snapshotted **one after the other**, in list order.
Each deck goes through the whole pipeline (compile → collect → copy → zip →
verify) before the next one starts.

- **Progress**: the existing compile progress UI (`compile_progress.py`)
  shows "Snapshot 2 of 3: t-Uni-IA2-2026w — compiling during-course…".
- **Cancel**: stops the current deck through the existing `CancelToken` and
  removes its `.partial-…` folder. Finished snapshots are kept, and the
  decks still waiting are skipped.
- **Failure**: one deck's failure, for example a compile error or a failed
  verify, does **not** stop the others. The deck is marked failed, its
  partial output is removed, and the run moves on.
- **Shared copies**: each snapshot is fully self-contained, so no files are
  shared between snapshots, even when decks use the same slides.
- **Result dialog**: one row per deck, showing ✓/✗, the size, the path, the
  file counts by origin and any warnings, plus *Open folder*. The same
  summary goes to the log pane.
- **Uncommitted changes**: if project files used by a selected deck have
  uncommitted git changes, the dialog lists them before starting. They are
  included, and each manifest records them.

### Archiving a deck

`_archive_deck()` (the deck table's archive button) currently asks
"Move <deck>.tex to decks/archive/?" with Yes/No. It becomes one question
with three buttons:

```
Archive deck
Move t-Uni-FM2-2027s.tex to decks/archive/?

Create a snapshot first? It keeps a self-contained copy of the deck as
it compiles today in snapshots/ (folder, without LaTeX package files —
change in Decks → Create deck snapshot…).

     [Snapshot, then archive]   [Archive only]   [Cancel]
```

- The snapshot settings line shows the remembered dialog settings. The
  default button is **Snapshot, then archive**.
- If the deck already has snapshots, choosing *Snapshot, then archive*
  leads to the same "Older snapshots exist" question as the dialog (see
  "Output: folder or zip").
- **Order matters**: the snapshot runs *before* `archive.archive_deck()`.
  Archiving moves the file and rewrites its `\input@path`/`\graphicspath`/
  `\addbibresource` lines. A snapshot taken before the move captures the
  deck exactly as it was in use.
- Because the snapshot compiles, it runs asynchronously with the same
  progress UI. Archiving happens when it finishes:
  - **Snapshot succeeds** → archive, then log both.
  - **Snapshot fails or is cancelled** → ask "The snapshot failed (<reason>).
    Archive the deck anyway?" with Yes/No. Nothing is archived silently.
- If a compile run is in progress, *Snapshot, then archive* reports "Busy",
  as above. *Archive only* stays available.
- The *Archived decks* tab's un-archive action does not ask for a snapshot,
  because it doesn't remove anything.

## Command line

```
python -m slidemage.deck_snapshot create <project> <deck.tex> [<deck.tex> …]
    [--zip] [--texmf] [--with-app] [--delete-old] [--versions instructor,during-course]
    [--no-reference-pdfs] [--bib cited] [--sources] [--transcripts] [--no-verify]
python -m slidemage.deck_snapshot verify <snapshot folder or zip>
python -m slidemage.deck_snapshot render <snapshot folder or zip> [--versions …]
```

Free of Qt, like `compat.py`. Several decks are processed one at a time,
like in the app, and each lands in `<project>/snapshots/`. The exit code is
nonzero if any deck failed.

## Implementation outline

New module `deck_snapshot.py`, free of Qt:

- `plan_snapshot(deck, options) -> SnapshotPlan`: runs the reference compiles
  and collects the files (the `.fls` union + extras + cross-check warnings).
  It does no writing outside a temporary build dir.
- `write_snapshot(plan, dest) -> Path`: copies files, writes the manifest,
  wrappers, render scripts, README, seeded timestamps and trimmed
  `slide_ids.csv`, then the optional zip.
- `verify_snapshot(path) -> VerifyReport`.
- `snapshot_decks(decks, options, progress, cancel) -> list[SnapshotResult]`:
  the one-at-a-time loop, shared by the dialog, the archive prompt and the
  CLI. It records each deck's failure and carries on, and it stops at
  cancel.
- `SNAPSHOTS_DIR = PROJECT_ROOT / "snapshots"`.
- Helpers: `parse_fls()`, `classify_input()`, `tex_environment()` (runs
  `lualatex --version`, `latexmk -v`, `biber -v`, `initexmf --version`, and
  parses the `.log` package lines), and `cited_bib_subset()` (biber
  `--output-format=bibtex` on the `.bcf`).

GUI:

- `qt_gui.py`:
  - add the **Decks** menu after System, with *Import PPTX/ODP…* moved
    there and *Create deck snapshot…* added;
  - update the menu docstring;
  - `_archive_deck()` gets the three-button question and the
    snapshot-then-archive flow;
  - a worker thread runs `snapshot_decks()` the way compile runs are run,
    and sets `self.compiling` so the two can't overlap.
- `qt_snapshot_dialog.py`: new. It holds the deck checklist, the folder/zip
  choice, the two include checkboxes and the result table.
- `app_settings.py`: the three remembered settings.

Small changes elsewhere:

- `compiler.py`: a `CompileJob.recorder_dir` (keep the `.fls` and aux
  files), and snapshot mode in `_build_env()` / the `.timestamp` deletion /
  output location.
- `project.py`: read the `snapshot` key and expose `is_snapshot()`.
- `compat.py`, `bundled_copies.py`, `updater`-adjacent project bookkeeping:
  skip when `is_snapshot()`.
- `deck_scan.py`, `unused_content.py`, `slide_usage.py`, `sm_rename.py`,
  housekeeping: never look inside `snapshots/`. They don't today; a test
  keeps it that way.
- Project template / `init_project()`: add `snapshots/` to the new project's
  `.gitignore`. An existing project gets the line when it creates its first
  snapshot, and the log says so.
- `.latexmkrc`, only if the tier-2 spike makes package files *active*:
  `SLIDEMASTER_SNAPSHOT_TEXMF` hook.
- `version.py`: minor bump (new feature, plus a menu item moved). Not
  breaking: no project, deck or file stops working.
- Manual: a new slide on snapshots, the menu slide updated for the Decks
  menu, and the import slide's menu path updated.

Tests (`tests/test_deck_snapshot.py`, using the `example/` project):

- `.fls` parsing and classification on Windows and POSIX paths;
- the snapshot of the manual deck compiles from an isolated temp dir with no
  inputs outside the snapshot;
- a seeded timestamp reproduces the footer stamp;
- the zip is deterministic (two runs → same bytes);
- in snapshot mode, compat and bundled-copies are inert, and
  `\deckoutputfolder` is ignored;
- a missing or altered file is caught by `verify`;
- alt-text filtering keeps exactly the used images' rows;
- `snapshot_decks()` with three decks where the second fails: the first and
  third snapshots exist, the second has no leftover `.partial-…`, and the
  results list says so;
- cancelling during deck 2 keeps deck 1, removes deck 2's partial folder and
  skips deck 3;
- naming: `decks/t-X.tex` and `decks/archive/t-X.tex` both snapshot to
  `snapshots/t-X_<date>_<HH-MM>/` (or `….zip`, whose tree starts at that
  name); a second same-form snapshot in the same minute gets `_2`; a folder
  and a zip in the same minute coexist;
- older snapshots are found by `snapshot.json`'s deck, not by the name
  prefix (`t-X` vs `t-X-extra`);
- deleting older snapshots: nothing is deleted without the "Delete old
  snapshots" answer (or `--delete-old`); a deck's old snapshots go to the
  trash only after its new one is verified; when the new one fails, they
  stay; snapshots created after the question are never touched;
- the project's `.gitignore` gains `snapshots/` exactly once;
- archive flow: *Snapshot, then archive* runs the snapshot before
  `archive_deck()` (the snapshot holds the un-archived `\input@path`); a
  failed snapshot archives nothing without a second yes;
- after a snapshot exists in `snapshots/`, `scan_decks()`, unused-content
  and slide-usage results are unchanged;
- menu structure: Decks comes after System, and Import PPTX/ODP is in Decks,
  not System.

## Phases

1. **Core**: `deck_snapshot.py` plan/write/verify and `snapshot_decks()`;
   folder and zip output into `snapshots/`; tier 1; reference PDFs; CLI.
   This alone delivers the feature from the command line.
2. **TeX package spike**: decides *active* vs *stored only* for the
   "Include LaTeX package files" checkbox, then implements the copying (and
   the `.latexmkrc` hook if active). It comes before phase 3 because the
   dialog shows the checkbox.
3. **App integration**: the Decks menu (with the Import PPTX/ODP move), the
   snapshot dialog, the archive prompt, snapshot mode (read-only banner,
   compat/bundled-copies guards, compiler env), and opening zips.
4. **Extras**: include the app exe, cited-only bibliography, editable media
   sources, transcripts.

## Open decisions

Settled 2026-10-07:

- one snapshot per deck;
- several decks are processed one at a time;
- output goes to `<project>/snapshots/`, which stays out of git;
- each snapshot is named after its deck plus date and time
  (`snapshots/<deck>_<YYYY-MM-DD>_<HH-MM>/` or `….zip`); a deck can have any
  number of snapshots, in folder and zip form;
- each run asks whether older snapshots of the selected decks should be
  deleted (to the Recycle Bin, only after the new one is verified);
- the dialog offers deck selection, folder or zip, and LaTeX package files;
- archiving asks first.

Still open:

1. **Reference PDFs on by default?** They're the only guarantee against TeX
   drift, at a few MB each. Recommendation: yes.
2. **Alt text: filter or copy whole?** Filtered is smaller and keeps unrelated
   descriptions out. Whole is simpler and byte-identical to the source.
   Recommendation: filter, with the original row order kept.
3. **App exe by default?** It's about 90 MB and Windows-only.
   Recommendation: off, but always record version + commit.
4. **Bibliography**: full (exact, simple) or cited-only (smaller, and doesn't
   leak unrelated entries). Recommendation: full by default, because a
   biber/biblatex style change could otherwise surface differences.
5. **Dirty working tree**: allow with a warning (proposed), or require a clean
   tree / auto-commit first?
6. **Slide id file**: trim `slide_ids.csv` to the ids used (proposed) or copy
   whole? A trimmed file keeps the snapshot small, but if it is unfrozen, new
   slides could then collide with ids used in the main project. Copying it
   whole avoids that.
