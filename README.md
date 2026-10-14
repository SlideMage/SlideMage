# SlideMage

LaTeX/beamer setup for research and teaching slides, built on the
[Gotham beamer theme](https://github.com/) with a Uni Graz color/logo
customization, plus SlideMage, a PySide6 desktop app (one workspace per deck, with an
AI assistant) for compiling decks and managing slide IDs, image descriptions, and
accessible transcripts.

> **This repository is self-contained**: the framework, the app and a small
> demo project (`example/`: the SlideMage manual,
> `decks/slidemage-manual.tex`, which explains SlideMage and shows every
> feature working) -- everything needed to compile slides and to start a
> project of your own. Real course content lives in separate project
> folders (any folder with a `slide_ids.csv`), which SlideMage opens. Read
> [PROJECT_OVERVIEW.md](docs/PROJECT_OVERVIEW.md) first -- it covers the core
> concepts (slide IDs, deck versions, accessibility, Ollama) at a higher
> level than this file, plus what to install before compiling anything.
> This file (README.md) is the detailed day-to-day reference; a few
> passages illustrate a point with a file that isn't part of the demo
> (another institution's preamble, a real course deck, a working-log file
> like `CONVERSION_NOTES.md`) -- the mechanism being explained still
> applies regardless.

`stpalan/SlideMage` is the authoritative repository (it was a flat copy of
the app folder before v4.0.0, when it took over the `latex/`/`example/`/
`src/` structure from Jürgen Fleiß's fork, `JuergenFleiss/slidemage`,
merged with that fork's history).

## Repository layout

| Path | Contents |
| --- | --- |
| `latex/` | The framework: Gotham beamer theme (`beamer*themegotham.sty`, `gotham.dtx`), `Slidemaster_preamble_base.tex`, `Slidemaster_alt.lua`. Institution-independent. |
| `example/` | A complete Slidemaster project: `slides/`, `decks/`, `media/`, the Uni Graz layer (`Slidemaster_preamble_uni-graz.tex`, `schemes/`), `Slidemaster.bib`, `.latexmkrc`, and `slide_ids.csv`, which marks a project's root. Also the template for a new project created from SlideMage. |
| `src/slidemage/` | SlideMage, the PySide6 app, an installable Python package (`pyproject.toml`): the workspace window, its dialogs and pages under `ui/` (`ui/kit/` is the widget kit), the AI layer (providers, agent, tools, MCP server) under `ai/`, and the backend modules beside them. |
| `packaging/` | The PyInstaller spec for the one-file executable, and a Linux `.desktop` template. |
| `.github/workflows/` | `release.yml` builds the Windows and Linux executables for every version tag; `ci.yml` (run by hand) runs the tests and compiles the demo decks. |
| `docs/` | Project overview, deck-version manual, SlideMage internals. |
| `tests/` | Smoke tests, run in CI together with a compile of the demo decks. |

**Paths in the rest of this file (`decks/…`, `slides/…`, `media/…`,
`.latexmkrc`) are relative to the project folder** — `example/` in this
repo.

## Quick start

```bash
python3 -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
slidemage --project example          # the app
cd example/decks && latexmk test.tex # or compile directly
```

For your own project, copy `example/` anywhere; if it doesn't sit next to
`latex/`, point `SLIDEMASTER_LATEX` at this repo's `latex/` folder. See
[docs/PROJECT_OVERVIEW.md](docs/PROJECT_OVERVIEW.md) for prerequisites
(LuaLaTeX, biber, optional Ollama).

No Python install needed: build a stand-alone executable once
(`pip install -e ".[build]"; pyinstaller packaging/slidemage.spec` — see
[docs/SlideMage.md](docs/SlideMage.md)) and start it directly:

```bash
./dist/SlideMage --project example       # Linux/macOS
dist\SlideMage.exe --project example     # Windows
```

The one-file build is about 300 MB: besides Qt it carries QtWebEngine (the Claude Code
tab's terminal is xterm.js in a web view), the bundled fonts and the `anthropic` client.
It was built and started on Linux (Python 3.14); Windows and macOS builds are untested. On
a bare Linux QtWebEngine needs more system libraries than Qt's base set (for instance
`libnss3`, `libxcomposite1`, `libxdamage1`, `libxrandr2`, `libxtst6` and an ALSA
library); install them with the package manager. The **Claude Code** route is optional: it
runs the user's own `claude` command (installed and logged in); without it the assistant
says so and nothing is sent, and everything else works. A cloud model in the chat needs an
Anthropic API key (`ANTHROPIC_API_KEY`, else the system keychain through the optional
`keyring` package, else the settings file); local models need Ollama.

## The workspace

SlideMage (6.0) opens one deck at a time in a single workspace window; the full reference
is [docs/SlideMage.md](docs/SlideMage.md), the SlideMage manual (`example/`) shows it with
screenshots.

- **Top bar:** deck switcher (decks grouped by their tag), *View as* Instructor / During
  course / After course and EN / DE (what the Preview shows and the slide list marks as
  hidden), the save state, **Preview | Split | Source | Details**, **Compile PDF** (the arrow
  offers every view, chapters, presenter, pages, several decks, transcripts, Stop and Build
  options), a **Local | Cloud** AI switch (see below) and the ⋮ menu (two columns: this deck | project incl. Images, housekeeping, info; Settings… at the bottom; everything else is in `Ctrl+K`).
- **Left:** the slide list in sections (find, drag and drop, multi-select, *Call as*
  variants, undo); **centre:** the focused slide as a page, as source (with lint, Insert,
  Cite, Ask AI to fix), side by side, or as facts (rename, duplicate, delete);
  **right:** one side panel for the slide (used in decks, versions, visibility,
  citations, language, image descriptions, transcript entry, speaker notes) above the AI
  assistant.
- **Ctrl+K** (or Ctrl+Shift+F) opens the command palette: every command, every slide, and
  full-text search over slides, deck files and the bibliography.
- **Compile card and log:** a compile run shows as a card at the bottom of the window (one
  line per job, Stop, Retry failed, Open PDFs); **Ctrl+L** opens the log drawer, which
  opens by itself on a failure.
- **Images page:** a full-window page for describing, drafting, translating and reviewing
  image descriptions (see "Describing images").
- **AI assistant** (one card under the side panels, 360 px column; *Focus assistant* hides the
  panels). Its header names the route (Local · Ollama, Cloud · Claude Code, Cloud ·
  Anthropic API) and what the conversation runs on, has a scope (*This slide* | *Whole deck*)
  with its target, the two most relevant tasks the route can run (Translate, Fix LaTeX
  errors, Make more concise, ...; the others are in Ctrl+K) and *New conversation*, which
  clears this route's conversation only. A task on one slide (also the Language panel's
  Translate) opens a **task card** in place of the conversation: Generate, then Review
  (the proposed change as a diff, nothing written yet; **Apply** writes it, or it is
  written at once in *Edit automatically* mode), Apply and Check preview (the slide is
  rendered again); it ends done (with **Undo** where the change can be taken back),
  as a conflict (the slide changed meanwhile: the proposal is kept, not applied),
  with a failed preview, stopped, or asking for setup (the route cannot run it: nothing
  is sent). In Review, Conflict and Done the card, and every edit card of the chat, has
  **Compare rendered**: the slide typeset before and after the change, side by side, in the
  view and language of the top bar (‹ › or the arrow keys step through the reveal steps of
  both, *Text diff* shows the source diff, Esc closes it; nothing is written). A slide
  Claude Code changed in the terminal is marked *Not reviewed*; Ctrl+K → **Compare rendered
  with last AI edit** (and the button in the slide's Details) shows it against the text it
  had before, which SlideMage keeps for every slide's last AI edit in `.slidemage/ai-before/`.
  **Check readability** (Ctrl+K → *Check readability of this slide* / *of this deck*, and a header
  button when no AI task is on show) asks whether an audience can read the slides, on every route, with no
  AI: it measures the rendered pages and lists the findings per slide in the assistant (measured value,
  threshold, the text or image concerned and a suggestion; a click takes you to the slide; *Check
  again*). A slide is typeset as a draft; a deck is read from its compiled PDF, only while nothing it was
  made from has changed (otherwise *Compile the deck first*, and the check runs when the compile ends).
  Sizes are judged against the slide height, so projected slides count, not LaTeX points: body text
  ≥ 3.3 % (about 18 pt on a 7.5 in slide; an error below, a warning within 5 %), headings not smaller than
  that or than the slide's body, sources and footnotes ≥ 2.2 %, text in figures ≥ 2.6 %; an image under 25 %
  of the slide area (or 35 % of its width) "may be too small to read"; contrast under 4.5:1 (3:1 for
  headings); text cut off by the page or running into the footer, overlapping lines; more than 90 words or
  14 lines of body text, or lines set closer than the font size (warnings). The assistant has the same check
  as the tool `check_readability`.
  *Back to conversation* leaves a pill in the header while it runs. On Local and Cloud · API the body is the chat: the
  chat is an agent that works on the focused
  slide or the whole deck with tools (read, search, edit, lint, render a preview, add a
  slide or a bibliography entry, compile, refresh cached previews). Edits wait for **Apply** / **Reject** in
  *Ask before edits* mode, or apply at once with **Undo** in *Edit automatically* mode; a
  slide's header comment, `\setSlideVersion` line, `\vbox to 0pt` blocks and frozen
  versions can never be edited. The model is a local Ollama model that can call tools or,
  with an Anthropic API key, a Claude model. Every AI request goes through one setting,
  the **Local | Cloud** switch after the deck switcher in the top bar (it asks before it
  stops running AI work, ends a live Claude Code terminal or sends a Local project to the
  cloud; its ▾ opens **AI setup**: the default model of every task for each side, "Cloud
  means" Claude Code or the Anthropic API, and the project's setting, where the switch
  starts when the project opens; the Settings and Deck settings dialogs and the other
  AI dialogs show the route read-only as a small badge under their title); each route keeps its own models and its own chat draft
  and conversation, a task a route cannot do is
  refused instead of using another route, and the first cloud request in a project says
  what will be sent. On Cloud · Claude Code the body is a terminal running the user's own installed `claude`
  in the project folder (permissions and its model are Claude Code's); SlideMage serves it
  the focused slide over a local MCP server and blocks edits to protected parts with a hook.
  If `claude` is missing or signed out, an amber card says so and offers to sign in.
- **Settings** (⋮ → Settings…): General, AI (German address of translations), Cloud (the API
  key), Ollama (models, updating, deleting), Prompts (image-description and translation
  prompts). The model of each task is in AI setup, not here.

## Releases and updates

Pushing a tag `vX.Y.Z` to `stpalan/SlideMage` makes GitHub build the
Windows and Linux executables (`.github/workflows/release.yml`) and attach
them, zipped, to that tag's release page. The workflow refuses a tag that
doesn't equal `VERSION_NUMBER` in `src/slidemage/version.py`, so a release
always says which code it was built from:

1. Bump `VERSION_NUMBER` in `src/slidemage/version.py` and append its history
   entry to `src/slidemage/CHANGELOG.md`, commit.
   The entry ends with a paragraph starting `NEW:` -- a one-sentence
   summary, then one `- ` bullet per change users notice, in plain words:
   ```
   NEW: Faster compiles for small edits.
   - Compile only some pages of a deck: type them into the Pages field.
   - Fixed: the progress bar no longer keeps running after a page compile.
   ```
2. `git tag vX.Y.Z && git push origin HEAD vX.Y.Z` (the branch and the tag).
3. A few minutes later the release has `SlideMage-windows.zip` and
   `SlideMage-linux.zip`, and its release notes
   (`packaging/release_notes.py`) list the `NEW:` bullets of every version
   since the previous release, with the tagged version's summary on top,
   then any breaking changes and a link to the full changelog. The
   workflow refuses a release whose versions lack a `NEW:` paragraph.

**Breaking releases.** A release that breaks with the past -- a project,
deck, setting or workflow that worked before no longer does, or now
behaves differently -- raises the major number (`v5.0.0`), and its
history entry in `src/slidemage/CHANGELOG.md` gets a paragraph of its own
starting `BREAKING:` that says what changes and what to do about it. The release
workflow refuses a major bump without that paragraph. Try it before
tagging: `python packaging/release_notes.py vX.Y.Z`.

A downloaded executable can update itself. **⋮ → Settings… → General →
Updates** chooses what happens when SlideMage starts (per user and
machine, stored next to the token, not in the project):

- **Don't check for updates.**
- **Check for updates and ask before installing** (the default): a newer
  release offers *Install now*, *Not now*, *Always install automatically*
  or *Stop checking for updates*.
- **Check for updates and install them automatically**: downloads and
  installs, then asks before restarting.

A failed check (offline, say) or an up-to-date copy only writes a line to
the log. A breaking release -- a `BREAKING:` paragraph in its notes, or a
higher major number -- is **always asked about, even in automatic mode**:
the dialog shows the `BREAKING:` paragraphs and offers *Install anyway*,
*Stay on vN.x* (installs the newest non-breaking release instead, if there
is one) or *Not now*. **Check for updates…** (⋮ menu, *Info*) works in every mode.
Because the repository is private, all of this needs a GitHub token with
read access to it (Settings → General → Updates, or
`$SLIDEMAGE_GITHUB_TOKEN`). A source checkout is updated with `git pull`
instead and never checks on start.

**Project format.** Opening a project writes
`<project>/.slidemage/project.json` (`{"format": 1, "last_app_version":
"vX.Y.Z"}`) -- commit it with the project. If a project was last used
with a SlideMage whose project format is newer than this one's, SlideMage
warns before opening it (*Open anyway* / *Quit*) and leaves the file as it
is. Raising the format is always a breaking release; a future release that
migrates an older project backs up every file it rewrites first.

The executable does not contain LaTeX: a project's decks still compile
with the machine's own LuaLaTeX/biber, against the framework in this
repository's `latex/` folder (see "Quick start" above) -- keep that
checkout updated alongside the executable.

**The project's copies of the framework and the manual** (since v5.19.0,
`src/slidemage/bundled_copies.py`). A project created by SlideMage gets
copies of the framework (the `latex/` folder beside it) and of the example
project, i.e. the SlideMage manual; `.slidemage/bundled_copies.json` records
a hash of every copied file (commit it with the project). When a later
SlideMage carries newer versions, it asks on start -- *Update*, *Not now* or
*Don't ask again for this version* -- and then updates the files changed
only upstream, adds new ones and removes the ones it no longer ships, after
copying everything it replaces or removes to
`.slidemage/backups/<time>/`. Files changed in the project are kept (and
listed), files deleted in the project stay deleted; new slide ids go into
`slide_ids.csv`, image descriptions the project doesn't have yet into its
`media/alt-text.json` (unreviewed ones of replaced images are refreshed). A
project made before v5.19.0: a sibling `latex/` that is not part of a git
checkout is adopted (whatever differs from this version is replaced, backed
up first); a git checkout -- a developer's `SlideMage/latex` -- is never
touched. A project without the manual is offered to add it (only missing
files are added, nothing is overwritten): the way to get the manual into a
project of your own.

## Project compatibility (since v5.29.0)

A newer SlideMage can change something a project depends on: a LaTeX command
is renamed, a file layout moves, a design is calculated differently. Every such
change is registered in `src/slidemage/compat.py` (one `Change` per change, added in
the same commit; a test fails a release with a `BREAKING:` paragraph in
`version.py` and no entry). When a project is opened, SlideMage compares the
registry with the version whose changes you have dealt with (kept in
`.slidemage/project.json`, key `compat`, so it follows the project to other PCs):

- Changes that **may stop the project compiling** or change a **file layout** open a
  dialog: **Update project** (runs the automatic fixes, after backing up every file it
  changes to `.slidemage/backups/<time>/compat/`; `decks/#workdeck.tex` included),
  **Show report**, **Not now** (nothing is recorded, so the dialog is back the next time
  the project is opened) and **Don't ask again** (remembered per change).
- Changes that only make slides **look different** never open a dialog; they are
  listed under ⋮ → Info → Project compatibility… (**Mark all as read** stops listing them).
- A change with a detector is pending only while the detector finds something in the
  project, so fixing it by hand makes it disappear. Where no automatic fix exists, the
  report says what to do.
- If the project was last used by a **newer** SlideMage than the one running (a second
  PC with an older exe), a notice says so (**Not now** / **Don't ask again**);
  `highest_app_version` in `project.json` never goes down.

The **report** (`.slidemage/compat-report.md` and `.json`) lists every pending change
with file and line, what changed, how to fix it, and a ready-made prompt for an AI tool.
From the command line, without a window:

    slidemage --check-project --project <folder> [--fix] [--json]

prints the report, exits with 1 if something may break, and with `--fix` runs the
automatic updates first. A migration is plain planning (`migrate(root)` returns the new
bytes of each file to rewrite), idempotent, and written atomically, with
line endings kept.

The first registered change is not a breaking one but the worked example of a
migration (`src/slidemage/compat_bibliography.py`, v5.32.0): course decks that carry
their own copy of the house citation format get it replaced by `\SMUseBibliography`,
and the format is written into the deck's template file. It only touches decks whose
copy is the house format line for line, leaves variants alone, and waits until the
framework next to the project has the new command.

## Deck snapshots (since v5.33.0)

A snapshot is a self-contained copy of a deck that compiles exactly as the deck
compiles today, whatever later happens to the project, the framework or SlideMage.
**⋮ → This deck → Create deck snapshot…** takes one or more decks (each gets its own
snapshot; they are made one after the other), **Folder** or **.zip file**, and whether
to **include the LaTeX package files** and **the SlideMage app**. Archiving a deck asks
first: **Snapshot, then archive** / **Archive only** / Cancel (the snapshot uses the
dialog's last settings and is taken before the deck moves).

Snapshots go to `<project>/snapshots/`, named `<deck>_<YYYY-MM-DD>_<HH-MM>` (folder) or
`….zip`; a deck can have any number of them. When the selected decks already have
snapshots, SlideMage asks once per run whether to delete them: they go to the Recycle
Bin, and only after the deck's new snapshot has been made and checked. `snapshots/` is
added to the project's `.gitignore` (binary copies of files git already has).

What a snapshot holds:

    render.bat, render.sh, README.txt
    snapshot.json        manifest: every file with its hash, the TeX and SlideMage versions
    reference-pdf/       the PDFs compiled when the snapshot was taken
    SlideMage/latex/     the framework, copied whole
    <project>/           the files the deck uses, at their usual paths
    texmf/, app/         optional (see above)

Which files a deck uses is decided by compiling it: every version (and the presenter
PDF) is compiled with latexmk's `-recorder`, and everything the compile read is copied
-- project files and the framework; the TeX distribution's files (and the fonts the
PDFs embed) are recorded with version and hash, and copied only with "Include LaTeX
package files". The footer timestamps of those compiles are kept and
`SOURCE_DATE_EPOCH` fixes the PDF dates, so rendering the snapshot later reproduces
the reference PDFs. Then the snapshot is rendered from its own folder: every file that
compile reads must lie inside the snapshot (or the TeX distribution), and every page
must equal the reference PDF -- otherwise the snapshot is discarded and the log says
why. That doubles the compile time; a large deck takes a while, on the compile slot.

Versions that are already current aren't compiled again (since v5.34.0). After every
successful whole-deck compile SlideMage records, in `.build/compile-records/<jobname>.json`,
the SHA-256 of every file the compile read (latexmk's `.fls`, plus the `.bib` files from
biber's `.blg`), of its settings (the wrapper: version, presenter, footer timestamp,
appendix), the TeX engine version, the footer timestamp, and the published PDF's path
and hash. A snapshot checks each version against its record: if nothing changed and the
PDF is still the one published, that PDF is the snapshot's reference; otherwise the
version is compiled, and the log says why ("1aa-EN-...-current.tex changed", "no compile
on record", ...). Only the verification render then runs. A compile during which one
of its files changed, or whose bibliography failed, is not recorded; "Remove temp files"
keeps the records. `--recompile` ignores them.

The same records spare needless compiles from **Compile PDF**: when a version
hasn't changed since its last compile, and that PDF is still where this compile would
put it, SlideMage asks first -- **Compile anyway**, **Skip unchanged** (the default) or
Cancel.

A snapshot's `<project>/` folder can be opened in SlideMage as a project: a line above
the workspace says it is a snapshot, SlideMage never changes it by itself (no compatibility
migrations, no framework or manual updates, no `project.json` bookkeeping), and compiles
use the snapshot's framework, PDF dates and footer timestamps, with PDFs in its own
`pdf/` (its `\deckoutputfolder` paths belong to the original project). Edits made there
do change the snapshot. From the command line:

    python -m slidemage.deck_snapshot create <deck> [<deck> ...] [--zip] [--texmf] [--with-app] [--delete-old]
    python -m slidemage.deck_snapshot verify <snapshot folder or .zip>
    python -m slidemage.deck_snapshot list

The TeX distribution itself (engine, format, packages) is the one thing a snapshot
cannot freeze: a much newer MiKTeX may render it differently. The reference PDFs keep
the deck as it was in any case, `verify` lists which TeX versions differ, and the
copied package files in `texmf/` record the exact originals.

## Directory layout

- `beamerthemegotham.sty` and friends, `gotham.dtx`/`gotham.ins` — the Gotham
  theme itself. Don't edit; these are the upstream theme sources.
- `Slidemaster_preamble_base.tex` — the project's shared customization
  layer: the footer (course name + slide ID + frame number), the
  `\slide{}`/`\slideversion{}` loading commands (and their student-version-
  excludable counterparts, `\omitslide{}`/`\omitslideversion{}`), the
  `standardframe` layout, and the special-purpose frame types built on
  top of it (title slide, section overview, quote, figure-only,
  presenter-attention — see "Special frame types" below). Institution-
  agnostic: everything here refers to colors/logos only through the names
  the institution layer below defines.
- `Slidemaster_preamble_uni-graz.tex` — a thin institution layer: the `c_*`
  color palette definitions, the institute logo path, and the per-logo
  calibration lengths, followed by `\input{Slidemaster_preamble_base}`. A
  deck picks its institution by `\input{}`ing this file (never the base
  file directly). The original project has two more of these (for two
  other institutions), each following exactly this same pattern with its
  own colors/logo and nothing else different — not included in this copy,
  but add your own the same way if you need a second institution: copy
  this file, swap the `c_*` colors and `\SMInstituteLogoPath`, keep
  the trailing `\input{Slidemaster_preamble_base}` line.
- `latex/Slidemaster_preamble_slidemage.tex` (with `latex/slidemage-logo.pdf`)
  — the generic **SlideMage template** (since v5.7.0; part of the framework
  since v5.9.0), for decks that don't belong to an institution: the
  SlideMage logo (a vector copy of the app icon), dark title and footer
  boxes with white text (the splash screen's `#1e1e1e`), the app's button
  blue `#0066cc` as highlight colour (bullets, image borders, table rules)
  and the app's other colours as the `c_*` palette, each pair the framework
  combines checked against WCAG 2.1 (see the file's comments). Same
  structure as the Graz layer, but in `latex/` rather than in a project:
  every project finds it on the same search path as
  `Slidemaster_preamble_base.tex`, so any deck can select it with
  `\input{Slidemaster_preamble_slidemage}` without a copy of its own (a
  project's own copy would win). SlideMage keeps its previews apart from
  the institutions' (template name "SlideMage"); the manual,
  `decks/slidemage-manual.tex`, is the demo deck in it.
  **Default render template** (since v5.8.0): a slide rendered outside a
  deck -- the Source view's Render menu and the Preview, tikz
  illustration renders -- uses the template chosen under Settings → General
  → Slide rendering, which lists every template a deck of the project can
  find: the project's own `Slidemaster_preamble_<name>.tex` files plus the
  framework's SlideMage template. Out of the box that is the SlideMage
  template; if it can't be found, Graz, then whichever template there is.
  A deck's own renders always use the deck's template.
- `slides/` — one set of files per slide, named by a permanent, opaque ID
  (see below). This is where actual slide content lives.
- `media/` — images referenced from `slides/` (charts, chapter logos,
  Midjourney illustrations, etc.), named `<type>-<slug>[-cropped].<ext>` so
  the kind of image is obvious from the filename alone — `chapter-logo-...`,
  `midjourney-...`, `chart-...`, `photo-...`, `screenshot-...`.
- `snippets/` — small LaTeX source files a slide shows as code with
  `\SMCodeFile{snippets/<slide id>-<n>.tex}` (the SlideMage manual's code
  panels; see "Layout helpers").
- `media/alt-text.json` — the store for everything about every image in the
  project: role (`decorative`/`informative`), confirmation status, short/long
  description, a default takeaway, and per-slide state (which slides use it,
  each with its own takeaway override and reviewed stamp). Edited through
  SlideMage's Images page. See "Screen-reader accessibility" below.
- `media/alt-text.csv` — a **generated** compile-time projection of the JSON
  store above (image, role, status, short alt only), rewritten automatically
  every time the store saves. Exists only because `Slidemaster_alt.lua` reads
  it directly at compile time with a hand-rolled CSV parser and LuaTeX has no
  JSON library — never hand-edit it, and don't be surprised to see it change
  on every save; it is derived, the same as `transcripts/` below.
- `Slidemaster_alt.lua` — the compile-time half of the alt-text system: parses
  `media/alt-text.csv` and tells the `\includegraphics` wrapper in
  `Slidemaster_preamble_base.tex` what to do with each image. In its own file
  rather than inline in `\directlua{}` because TeX tokenizes that argument
  first, so a `%` in a Lua string pattern would silently truncate the line.
- `transcripts/` — generated accessible transcripts (Markdown + HTML), one per
  deck and student version. Gitignored: it is derived from the deck, the
  slide files and `media/alt-text.json`, and is regenerated on demand.
- `.previews/slide_previews/` — two PNGs per slide per institution template
  (`<bare id>-<TemplateName>-<width>-<height>.png`, e.g.
  `22s-UniGraz-1920-1080.png` and `22s-UniGraz-304-171.png` — bare id
  first, to sort/glob-match by slide before institution), refreshed as
  a side effect of any compile that touches that slide, for one deck via
  **⋮ → This deck → Rerender all previews for this deck**, or for the whole project via
  SlideMage's "Update slide previews" (⋮ → *Housekeeping…*). A best-effort cache for
  SlideMage's own Preview view and slide-list thumbnails, not a
  guaranteed-fresh one. Gitignored, same category as `transcripts/`.
- `slide_ids.csv` — registry of all slide IDs in use, so new IDs never collide.
- `.scripts/R_Slidemaster/inst/templates/slide-template.tex` — the starter
  template a brand-new slide is seeded from. The original project mints new
  IDs and scaffolds files from an R package at this same path
  (`RSlidemaster`, not included here); this copy doesn't need R at all —
  SlideMage's own `slide_ids.py` reimplements the same ID-minting logic in
  pure Python and reads this one template file directly, keeping only its
  path (not the rest of the R package) so neither side needs to change.
- `decks/` — one `.tex` file per real course/talk deck, each pulling in
  whichever slides it needs from `slides/`. This copy has only the demo
  deck below; a real project accumulates one file per course/talk here
  (e.g. `t-Uni-FM2-2027s.tex`), plus `decks/#workdeck.tex`, a single,
  reusable, throwaway scratch deck for quick iteration on whichever slides
  are currently being worked on, without recompiling a whole real deck.
- [SlidemasterManual.md](docs/SlidemasterManual.md) — concise reference for core
  functionality, including the deck version system for instructor/during-course/
  after-course decks.
- `src/slidemage/` — SlideMage, a PySide6 (Qt) app: one workspace per deck
  (slide list, Preview/Source/Split/Details, side panels, an AI assistant)
  for compiling decks (any combination of instructor/during-course/
  after-course, whole deck or one PDF per chapter), for archiving a finished
  deck's `.tex` file into `decks/archive/` while keeping it compilable, and
  for describing images and generating accessible transcripts. Install with
  `pip install -e .`, start with `slidemage`; see
  [docs/SlideMage.md](docs/SlideMage.md) for how it works.
- `decks/slidemage-manual.tex` — the SlideMage manual: how SlideMage
  works, and a working demo of every frame type and feature, compiled in
  every deck version (since v5.16.0; it replaced the `test.tex`/
  `test-student.tex` demo decks and the `ZZ*` demo slides). See "Getting
  started" in [PROJECT_OVERVIEW.md](docs/PROJECT_OVERVIEW.md).

A deck for a specific course or talk is a `.tex` file in `decks/`, e.g.:

```latex
\documentclass[aspectratio=169]{beamer}
\usetheme{gotham}
\input{Slidemaster_preamble_uni-graz}
\newcommand{\FooterText}{KS Financial Markets | Stefan Palan | 2027s}

\begin{document}
	\slide{k7f-EN-Standard-content}
	\slide{...}
\end{document}
```

Relative paths inside `Slidemaster_preamble_uni-graz.tex` (and `\slide{}`'s own
`\input{slides/...}`) assume the project root as the working directory. Every
deck lives one level down, in `decks/`, so needs two extra lines right after
`\documentclass` so it can *also* be compiled from inside `decks/` itself,
not just from the root:

```latex
\makeatletter
\def\input@path{{../}}
\makeatother
\graphicspath{{../}}
```

This adds the project root as a *fallback* search location — tried only if
the plain relative path isn't found relative to wherever the compiler was
actually invoked from — so every `\input`/`\slide{}`/`\includegraphics`
call throughout `Slidemaster_preamble_uni-graz.tex` and the slide files themselves
(not just the deck file's own `\input{Slidemaster_preamble_uni-graz}`) resolves
correctly either way, with no changes needed to any of those other files.
`decks/slidemage-manual.tex` has this already; copy it into any new deck under `decks/`.

Each `\slide{...}` call pulls in one slide file from `slides/`, so the same
slide can be reused across multiple decks (e.g. a definition slide used in
both a lecture and a research talk) without copy-pasting content.

## Compiling

Compile with `lualatex` — the Gotham theme loads Fira Sans via `fontspec`,
which plain `pdflatex` can't handle. This fails *silently* under `pdflatex`:
instead of erroring, it falls back to Computer Modern, which can subtly
mis-render things (e.g. a literal `|` in `\FooterText` came out as an em
dash under the wrong engine, with no warning). Also compile twice — see
"Title bar and logo" below for why.

`xelatex` was previously listed here as a supported alternative, but never
actually was: slide content uses Unicode math comparison characters (e.g.
`≤`) directly, which plain `xelatex` doesn't handle out of the box (`! LaTeX
Error: Unicode character ≤ (U+2264) not set up for use with LaTeX`) --
discovered only once someone actually tried compiling with it, not caught by
anything before that. `lualatex` handles these natively, and the project has
settled on it as the one supported engine rather than chasing xelatex
compatibility for its own sake.

### Compiling without TeXstudio (SlideMage)

`slidemage` compiles any deck via `latexmk` directly, through the workspace's
**Compile PDF** button and its menu rather than a hand-edited `DECKS=` line -- see
[docs/SlideMage.md](docs/SlideMage.md) for the full picture. It
exists specifically so compiling doesn't depend on TeXstudio's own local
settings at all (see "TeXstudio setup" below for how much those drift
between machines); its own correctness only depends on files committed to
this repo (`.latexmkrc`, the magic comments), plus whatever's on the
machine's normal PATH, so it behaves identically on any PC without
per-machine setup.

This project previously had a `compile-all.bat` for the same command-line
purpose (plus a `compile-all-versions.bat` for compiling all three deck
versions in one go) -- both retired once SlideMage covered the same
ground with an app on top, and neither is needed alongside it.

Two non-obvious things `src/slidemage/compiler.py` does, both confirmed
necessary by hitting the failure directly rather than assumed (carried over
from those retired scripts, which hit the same two problems first):

- **Windows/MiKTeX only:** prepends Git for Windows' `usr\bin\` (wherever
  `where git` says Git is installed) to `PATH` before running `latexmk`.
  MiKTeX's `latexmk.exe` is a thin launcher that shells out to a real Perl
  interpreter, which isn't bundled with MiKTeX itself; the only `perl.exe`
  this project has ever found on either Windows machine is the one bundled
  with Git for Windows, under a folder (`usr\bin\`) that Git's own
  installer does *not* add to the system PATH (only `cmd\` and
  `mingw64\bin\` are) -- so a plain `latexmk` call from a fresh
  `cmd.exe`/PowerShell process (unlike from TeXstudio or Git Bash, both of
  which have a working Perl some other way) fails outright with "MiKTeX
  could not find the script engine 'perl'". On Linux this code path is a
  harmless no-op: it looks specifically for a `perl.exe` file, which never
  exists there, so nothing is prepended -- fine, since TeX Live's own
  `latexmk`/`perl` are already on PATH regardless.
- Checks each deck's own `.build\<jobname>.log` for an actual fatal error
  (a line starting with `!`) rather than trusting `latexmk`'s own exit code.
  A genuinely from-scratch compile of a large deck (measured on the
  since-retired `t-Uni-FM2-2027s-preview.tex`, whose role `#workdeck.tex`
  now fills)
  (deleting every existing build output first, not just an incremental
  recompile) has `lualatex` return a nonzero exit code on *every* pass, from
  harmless Fira-Sans font-shape-substitution warnings unrelated to whether
  the compile actually converged (confirmed directly: the `.aux` file
  stabilizes byte-for-byte after enough passes, and the resulting PDF is
  correct and complete) -- so exit code alone can't distinguish a real
  problem from this deck's normal cosmetic warnings, but scanning the log
  for an actual `!`-prefixed error can, and is confirmed to read clean on
  this same compile.

### Compiling only some pages (since v5.34.0)

In the arrow menu of **Compile PDF**, **Pages of the selected slides** takes the slides
selected in the slide list, and **Pages by number…** the numbers printed in the slide
footers, e.g. `4, 5, 7-10, 15`. The view being compiled (or the presenter PDF) then
compiles only those slides, each slide whole with all its reveal steps, numbered exactly
as in the whole deck. It builds on the version's last whole-deck compile (`src/slidemage/partial_compile.py`):

- that compile's PDF says which slide each number is, and its auxiliary files (kept in
  `.build/compile-records/<jobname>/`, see "Deck snapshots") supply the contents slide,
  chapter agendas, citations and links of the whole deck;
- the deck is compiled without the other slide calls, with the frame and page counters
  set before each kept slide, in two single passes;
- with **Pages replace theirs in the full PDF** (Build options, on by default) the new pages
  are drawn onto the old ones in that PDF -- bookmarks and links into them keep working,
  links on them are re-targeted. Otherwise they go to `<pdf>-pages-<numbers>.pdf`.

A slide whose number of pages changed (an added `\pause`) can't be swapped in place: its
pages go to the separate file, and the log says to compile the whole deck. A page compile
is refused when there is no whole-deck compile on record (compile the whole deck once
with v5.34.0 or later), when the deck file changed in its preamble or before the end of the
last slide asked for since that compile (a slide added, moved or removed there shifts the
numbers after it; changes further down are fine -- the record keeps a copy of the deck file
as compiled, since v5.35.0), or when the PDF was changed. Each version gets the slides with
its own reveal steps. It doesn't update other pages
that show something of the changed slides (a new title in the contents slide, an
appendix thumbnail); the log lists slides that changed but weren't asked for.

Before an ordinary compile, SlideMage asks when a version hasn't changed since its
last compile (see "Deck snapshots").

Every PDF of one click on **Compile PDF** carries the moment of that click in its PDF info
dictionary (`/SlideMageRun`; a page compile that swaps pages in stamps its own). **Open
latest PDF** (`Ctrl+K`) opens the deck's usual PDF -- the instructor version, or
another one chosen in the **Deck settings** ("Open pdf opens", stored as
`%% SlideMage open PDF: <version>` in the preamble) -- unless a newer PDF of the deck comes
from a later click (or carries no stamp, i.e. predates v5.34.0); then it asks which one to
open.

### Custom output folder (`\deckoutputfolder`)

Every compiled PDF lands in the shared `pdf/` folder by default, named
`<deck>-<version>.pdf`. A deck can redirect its own compiles elsewhere —
straight into a specific teaching folder, per semester or per course —
by declaring `\deckoutputfolder` near the top of its own preamble
(before `\begin{document}`; it's a real, inert macro SlideMage's own
`deck_scan.py` reads directly out of the source text, never expanded by
LaTeX itself, so it's harmless in a plain TeXstudio/`latexmk` compile
too):

```latex
\deckoutputfolder{D:/Teaching/IA2 2026w}                    % every version
\deckoutputfolder[instructor]{D:/Teaching/IA2 2026w/Instructor}
\deckoutputfolder[during-course]{D:/Teaching/IA2 2026w/Students}
\deckoutputfolder[presenter]{D:/Teaching/IA2 2026w/Instructor/Presenter.pdf}
\deckoutputfolder[transcript]{D:/Teaching/IA2 2026w/Transcripts}
```

- Forward slashes required, same reason every other path in this
  project's own `.tex` files already uses `/` (a LaTeX brace argument,
  and `\` has its own meaning there).
- The bare (no `[version]`) form is the fallback for any version with no
  more specific line of its own — write only that one line to send every
  version to the same folder.
- **`[presenter]`** — a presenter compile's own `.version` is already
  "instructor" (it always uses full, unrestricted content), so without
  its own key it would otherwise silently share the plain instructor
  PDF's own folder/filename with no way to tell them apart. Falls back to
  `[instructor]`, then the bare form, if not declared on its own.
- A relative path resolves against the project root
  (`D:\uniCLOUD\Slidemaster`), the same base every relative
  `\includegraphics` path in this project already resolves against.
- When configured, the compiled PDF goes **only** to that folder, not
  also to `pdf/` — auto-open and the compile log both follow the real
  destination.
- A commented-out `\deckoutputfolder` line (`% \deckoutputfolder{...}`) is
  correctly ignored — it doesn't apply just because the text is still
  present in the file.
- If the path itself names a full file rather than a folder (has a file
  extension, e.g. `D:/Teaching/IA2 2026w/Handout.pdf`), that exact
  filename is used for the generated output instead of the usual
  `<deck>-<version>` naming.
- `[transcript]` is for **Generate transcript**'s own output (see
  "Accessible transcripts" below); with no `[transcript]` line of its
  own, a transcript falls back to the deck's bare `\deckoutputfolder{...}`
  (its "every output" fallback, same as any PDF version without a more
  specific line), not straight to `transcripts/` — declare `[transcript]`
  only if transcripts genuinely need to land somewhere else. A
  full-filename override here names one shared stem for both the `.md`
  and `.html` file it writes.

### Exporting to PowerPoint

**Export PPTX…** (⋮ menu, *This deck*) compiles the open deck (instructor version)
and writes a real `.pptx` next to its PDF in `pdf/`. Every beamer overlay/reveal step belonging to one
`\slide{}` call is stacked full-page onto a *single* PowerPoint slide
(topmost = first reveal step) instead of getting its own slide, with each
image but the last given a click-triggered "Fade" ("Verblassen") exit
animation that peels it away to reveal the one underneath. This exists so
PowerPoint's own recording/presenter tools can be used with a SlideMaster
deck, since PowerPoint can't open a compiled PDF directly -- and since
PowerPoint's ink annotations paint in a layer above everything on a slide,
an annotation drawn during a live recording stays visible across that
slide's own later reveal steps instead of disappearing when the deck
advances past it. Built via the `python-pptx` package
(`src/slidemage/pptx_export.py`) -- the one other deliberate exception to
this project's stdlib-first dependency policy, alongside PyMuPDF.
python-pptx itself has no animation API, so the click-triggered timing is
hand-assembled OOXML, verified directly against a real PowerPoint
installation (see the module's own docstring for how).

### Deck tags (`\decktags`)

SlideMage's deck switcher (top left) groups decks under headings -- the workdeck on top,
then "Course decks", "Research presentations", "SlideMage manual" and
"Test decks", with the archived decks at the foot. Which group a deck is in is
decided by its own tag, never by its filename:

```latex
\decktags{test}
```

placed just before `\begin{document}` (after the preamble `\input{}`, which
defines it as an inert no-op like `\deckoutputfolder`). The group tags are
`work`, `course`, `research` and `test`; a deck with none of them is a
course deck, and if it carries several the first in that order wins. Other
tags are allowed and ignored for now. Set it from SlideMage rather than by
hand: **Tags…** in the ⋮ menu (*This deck*), or the group choice in the
**Duplicate deck…** sheet when creating a copy.

The SlideMage manual (`decks/slidemage-manual.tex`) carries a fifth group
tag, `manual` (since v5.18.0): it always sits in its own "SlideMage manual"
section (above the test decks), wins over any other group tag, is never offered in
the Tags or Duplicate sheets, and **Tags…** is disabled for the manual -- the
manual can't be moved into another group by accident. A copy made with
**Duplicate deck…** starts out as a course deck.

### Deck settings and course links

**Deck settings…** (⋮ menu, *This deck*) opens a sheet with the deck-wide settings
(General, PDF output and Admin slides tabs). They are written into the deck's own
.tex file, all in one go when you press **Save**, so they stay with the deck when
it is moved, copied or archived:

- **Template**: the institution template the deck loads
  (`\input{Slidemaster_preamble_<name>}`), chosen from the templates the
  project can find.
- **Language**: `\decklanguage[en]` or `[de]`.
- **Footer text**: `\FooterText`, the left part of the footer.
- **Course link**: a full HTTP or HTTPS URL; **Open** saves the settings and
  opens the page in your default browser. Clear the field to remove the link.
- **Where the PDFs go**: the `\deckoutputfolder` of all outputs and of each
  version, the presenter PDF and the transcript (**Browse...** picks a folder; a
  name ending in `.pdf` fixes the file name).
- **Always add the slide-preview appendix**: `\deckappendixtoc`.

The group is still chosen with **Tags…**. **Deck settings…** is disabled for the
SlideMage manual: app updates replace the manual.

SlideMage stores the course URL just before \begin{document}, as a LaTeX
comment:

    %% SlideMage course URL: https://online.uni-graz.at/kfu_online/...

The comment does not change the compiled slides. The link stays with the
deck when it is moved or archived.

For a linked Uni Graz course, open the **Admin slides** tab of the Deck settings.
SlideMage reads the course's Abhaltungstermine page when the tab is first shown, asks
which group to use when several are listed (**Course sessions**), and previews the LaTeX
table. Choose a deck position and click **Insert slides** to create an editable schedule
slide.

The table follows the deck's `\decklanguage`: a German deck gets
"Abhaltungstermine" with Datum/Zeit/Ort/Termin, an English deck (also one
with no `\decklanguage`, which compiles in English) gets "Course sessions"
with Date/Time/Location/Session, and the new slide is named
`<id>-EN-Course-Sessions` instead of `<id>-DE-Course-Sessions`. For an
English deck, group names ("Standardgruppe"), session types ("Abhaltung",
"Prüfung", ...) and remarks are translated from a fixed word list in
`course_schedule.py`; a remark with a word that isn't on the list stays
German rather than half-translated, and dates, times and rooms are kept as
UNIGRAZonline lists them.

### Decks with a bibliography (`\fullcite{}`/`Slidemaster.bib`)

biblatex+biber is opt-in per deck (not loaded globally): a deck that wants
references puts **`\SMUseBibliography`** in its preamble, after the template
is `\input`. That one command loads biblatex with the template's options,
registers `Slidemaster.bib` (or `\SMUseBibliography[other.bib]`) so that biber
finds it whether the compile starts in the project root or in `decks/`, and
applies the template's citation format. The format is the template's job:
the institution template redefines `\SMBiblatexOptions` (package options) and
`\SMBibliographyStyle` (name format, field formats, bibliography drivers) --
`Slidemaster_preamble_uni-graz.tex` and the SlideMage template
(`latex/Slidemaster_preamble_slidemage.tex`) carry the author's house format,
`Markowitz, H., 1952. "Portfolio Selection", Journal of Finance 7(1), 77--91.`
(every author as "Family, Initials.", year unparenthesized, title in quotes,
type-specific tail for books, articles, online sources and reports). A
template that sets nothing gets biblatex's stock authoryear style. A deck
that wants a format of its own redefines the two macros before
`\SMUseBibliography`, or skips the command and loads biblatex itself.
`decks/slidemage-manual.tex` is this copy's own live example, enough to
resolve the manual's one `\fullcite{markowitz1952}` (slide `1nz`) against this
copy's trimmed `Slidemaster.bib` (a single entry -- see that file's own header
comment).
This needs one extra step beyond the usual two `lualatex` passes above —
**`biber`, run in between them**:

```
cd decks
lualatex test.tex   # 1st pass -- also tells biber what to fetch
biber test           # resolves citations from Slidemaster.bib into .bbl
lualatex test.tex   # 2nd pass -- typesets the resolved citations
lualatex test.tex   # 3rd pass -- for the tikz "remember picture" bits, as usual (not exercised by this deck's demo slides, but harmless to always run)
```

The same sequence for the original project's own real course deck looked
like this:

```
lualatex t-Uni-FM2-2027s.tex   # 1st pass -- also tells biber what to fetch
biber t-Uni-FM2-2027s          # resolves citations from Slidemaster.bib into .bbl
lualatex t-Uni-FM2-2027s.tex   # 2nd pass -- typesets the resolved citations
lualatex t-Uni-FM2-2027s.tex   # 3rd pass -- for the tikz "remember picture" bits, as usual
```

Skipping the `biber` step (e.g. an editor's default "build" button often
only runs the LaTeX engine) doesn't error outright — it produces an *empty*
`.bbl`, so every `\fullcite{key}` silently falls back to printing the raw
citation key instead of a formatted reference, plus
`LaTeX Warning: Citation '...' undefined` and
`Package biblatex Warning: Please (re)run Biber` in the log. If you see
those, the fix is exactly the missing `biber` step above, not a code
problem — most editors (TeXstudio, VS Code's LaTeX Workshop, Overleaf, ...)
can be configured to run this sequence automatically as their default build
command; check that setting first so it isn't forgotten on every edit.

Since `biber` (unlike `lualatex`, which follows this deck's own
`\input@path`/`\graphicspath` fallback above) reads `Slidemaster.bib`'s path
literally from wherever it was invoked, `\addbibresource{}` resolves it at
`lualatex`-compile time based on the *actual* working directory, so the
`biber` step above works whether the whole sequence runs from the project
root or from inside `decks/`.

### TeXstudio setup

> Optional. SlideMage compiles through `latexmk` directly and needs none
> of this; it only matters if you also want to edit/compile from
> TeXstudio itself, which -- like these specific menu paths -- is a
> Windows/cross-platform desktop app, not something this section assumes
> you're using.

[`.latexmkrc`](example/.latexmkrc) (also duplicated in `decks/`, for the same
compile-from-either-location reason as the `\input@path`/`\graphicspath`
fallback above) configures `latexmk` to use `lualatex`, and to handle the
whole lualatex/biber rerun loop above automatically and correctly per deck
(most decks don't use biblatex at all; `latexmk` detects that from the
`.bcf` file rather than always running `biber` regardless).

1. **Options → Configure TeXstudio → Commands**: set **both** the `LaTeX`
   *and* the `LuaLaTeX` command rows to `latexmk %.tex` (no `-pdf` flag —
   that flag forces `pdflatex` mode specifically, silently overriding
   `.latexmkrc`'s engine choice). Both rows, not just one: which row
   actually gets used depends on a given file's magic comment (see below),
   and this project's files now standardize on the `lualatex` keyword rather
   than `latex` — but keeping both rows correctly bound is cheap insurance
   against either keyword being used anywhere, and against whichever row a
   future TeXstudio default/Quick Build falls back to.
2. **Options → Configure TeXstudio → Build**: set "Default Compiler" to
   `LaTeX` — **not** `PdfLaTeX` (corrected 2026-07-07; this section
   previously, wrongly, said the opposite — see below for how that was
   actually caught). This is a *separate* setting from step 1's Commands
   entry, and it does exactly what its name says: it runs the literal
   command bound to whichever row it names (`PdfLaTeX` → bare
   `pdflatex.exe ...`, `LaTeX` → the `latexmk %.tex` from step 1,
   `XeLaTeX`/`LuaLaTeX` → their own bare, untouched commands) — there is no
   special "PdfLaTeX means generic/whatever-LaTeX-says" behavior. Left at
   `PdfLaTeX` (TeXstudio's own factory default), every compile silently runs
   bare `pdflatex.exe -synctex=1 -interaction=nonstopmode %.tex`, bypassing
   `latexmk`/`lualatex`/`biber` entirely — which, on this Fira Sans/fontspec
   theme, doesn't error, it just silently substitutes Computer Modern (see
   "Compiling" above) *and*, on a large multi-hundred-slide deck, has to
   METAFONT-generate every distinct legacy bitmap font size the deck
   happens to use, one at a time — slow enough on `t-Uni-FM2-2027s.tex`
   specifically to look exactly like "TeXstudio starts compiling and never
   finishes," rather than the fast, clean failure a smaller file would show.
   As documented below, every top-level file's own `% !TeX program = lualatex`
   magic comment *does* reliably override this setting as long as it names a
   keyword TeXstudio actually recognizes (confirmed directly: TeXstudio only
   falls back to this Build-panel setting when a file's magic comment is
   missing or unrecognized) — so this setting mainly matters as a sane
   default for any `.tex` file that doesn't carry that magic comment yet.
   Set it correctly anyway, both as that fallback and because **this exact
   setting is local to each TeXstudio installation, not saved anywhere in
   this repo** — it silently drifts out of sync between machines (e.g. a
   laptop vs. a desktop install) unless set the same way, deliberately, on
   each one.
3. **Options → Configure TeXstudio → Build**: set "Default Bibliography
   Tool" to `Biber`, not the default `BibTeX` — a separate setting from
   steps 1-2 again, and one `latexmk` itself has no say over. With "Check
   and update bibliography before compiling" switched on (also in this
   same Build panel), TeXstudio runs whatever this is set to *directly*
   against the `.aux` file as its own independent step, regardless of
   `latexmk` correctly auto-detecting and invoking `biber` on its own. Left
   at its default `BibTeX`, this fails outright on a `biblatex`-based deck
   like `t-Uni-FM2-2027s.tex` — plain `bibtex` expects `\citation`/
   `\bibdata`/`\bibstyle` commands in the `.aux` file, which a
   `biblatex`-produced `.aux` never contains (it uses its own
   `\abx@aux@...` commands instead) — producing exactly "I found no
   \citation commands" and a subsequent fallback to raw citation keys
   instead of formatted references, even though `Biber` itself is already
   available and correctly configured as its own separate command in the
   Commands panel from step 1.

Every top-level compilable file (`decks/slidemage-manual.tex`,
`decks/test.tex`, `decks/test-student.tex`, `decks/test-mci.tex`, `decks/test-ibk.tex`, `decks/t-Uni-FM2-2027s.tex`,
`decks/t-Uni-IA2-2026w.tex`, `decks/#workdeck.tex`) also starts
with a `% !TeX program = lualatex` magic comment as a per-file safety net
independent of both settings above: most editors that recognize it
(TeXstudio included) use the named command for that specific file regardless
of the global "Default Compiler" setting. Keep this comment as the literal
first line of any new top-level deck file. This is also the one thing that
makes compiling reliable **across multiple machines**: everything else in
this section (the Commands-row bindings, Default Compiler, Default
Bibliography Tool) is local TeXstudio state, stored per-installation and
never synced by this repo, so it silently drifts out of step between e.g. a
work PC and a home PC unless set identically, by hand, on each one. This
magic comment, by contrast, *is* committed to the repo -- so as long as each
machine's `LuaLaTeX` Commands row (step 1 above) is bound to `latexmk %.tex`,
every file here compiles the same way on any machine regardless of whatever
else that machine's Default Compiler/Quick Build happens to be set to
(confirmed directly: TeXstudio only falls back to those settings when a
magic comment is missing or unrecognized, never when it names a valid
engine keyword).

**This must say `lualatex`, not `latex`** (corrected 2026-07-08, superseding
this section's two earlier, each-wrong-in-a-different-way write-ups below --
kept rather than deleted, since the same wrong turns are easy to re-take).

The *first* wrong write-up claimed the capitalized form `LaTeX` was
required -- caught only once a real TeXstudio instance actually hit it: the
log printed `%!TeX program not recognized! (LaTeX). Using default.`, then
ran bare `pdflatex.exe` directly. TeXstudio's magic-comment parser matches
against a small *fixed* set of lowercase engine keywords (`latex`,
`pdflatex`, `xelatex`, `lualatex`, ...) -- it is not matching against the
*display label* of whichever Commands-page row (`LaTeX`, `PdfLaTeX`,
`XeLaTeX`, `LuaLaTeX`, ...) happens to share that spelling, and it is not a
free-form reference to an arbitrary Commands-row name either -- only that
small fixed keyword set is ever recognized, no matter what rows exist or
what they're named. A custom/renamed row (e.g. a `LaTeXmk` row bound to
`latexmk %.tex`) can *only* be reached by binding one of the fixed
keywords' own rows to that same command, never by writing that row's own
name into the magic comment -- confirmed directly: writing
`% !TeX program = latexmk` produced `%!TeX program not recognized!
(latexmk). Using default.`, exactly the same failure as the capitalization
mistake, just with a different bad keyword.

The *second* wrong write-up (this section's previous version) got the
keyword casing right -- lowercase `latex` -- but not the choice of keyword:
it correctly maps to whichever command the row historically labeled "LaTeX"
is bound to (`latexmk %.tex`, correctly running `lualatex` under the hood),
and that command *does* run and succeed. But the `latex` keyword is also
what TeXstudio uses, independently of that row's actual bound command, to
choose which *viewer* to auto-launch afterward: TeXstudio classifies engine
keywords into internal "kind" buckets (visible in `texstudio.ini` as
`Tools\Kind\LaTeX` vs. `Tools\Kind\Pdf`), and `latex` is bucketed as a
legacy DVI-producing engine there regardless of what its row is actually
bound to. So even with the command itself fully correct, TeXstudio still
tries to auto-view a `<jobname>.dvi` that a `latexmk %.tex`/lualatex
pipeline never produces -- surfacing as a MiKTeX "Windows API error 2"
problem report unable to locate that nonexistent `.dvi`, *after* the actual
compile has already finished successfully (confirmed directly: the `.log`
this produced shows a clean, complete lualatex run with no errors, just the
usual harmless "rerun" warnings).

`lualatex` is the one keyword that is simultaneously (a) one of the small
fixed set TeXstudio's magic-comment parser actually recognizes, and (b)
already bucketed under `Tools\Kind\Pdf`, so the auto-view step correctly
expects a PDF instead of a DVI -- as long as its own Commands row is bound
to `latexmk %.tex` rather than TeXstudio's own factory-default bare
`lualatex.exe -synctex=1 -interaction=nonstopmode %.tex` (which would skip
latexmk's own biber-detection/rerun handling entirely, the same class of
bypass the wrong-Commands-row and wrong-Default-Compiler mistakes above both
warn about). The giveaway of a bypass either way, in the log: a real
`latexmk` run is full of `Latexmk: applying rule '...'`/`Run number N of
rule '...'` wrapper lines; a bypassed one is bare engine output with none of
those.

### Build output location (`.build/`)

Compiling through `latexmk` (the setup above, whether via TeXstudio or the
command line) writes every auxiliary file — `.aux`, `.log`, `.bbl`/`.bcf`/
`.blg`, `.nav`/`.snm`/`.toc`, `.fdb_latexmk` — into a single shared
`.build/` at the project root, regardless of whether you compile from the
project root or from inside `decks/`. Only the final `.pdf` and its
`.synctex.gz` stay next to the `.tex` source, so double-clicking a deck's
PDF still works the same way it always has.

This needs both `.latexmkrc` copies (root and `decks/`, same
compile-from-either-location reason as everywhere else in this section) to
set two things together — setting only one half reproduces one of the two
messes this is meant to fix:

- `$aux_dir`, set to an **absolute** path to the shared `.build/`. A plain
  relative `'.build'` is read relative to whatever directory is current at
  the moment `latexmk` applies it, which (see next point) is the *compiled
  file's own* directory — so a relative path here would silently create a
  second, empty `.build/` *inside* `decks/` when compiling a `decks/` file
  from the project root, instead of sharing the one at the project root.
  Built from `$abs_rc`, a variable `latexmk` itself sets to the current rc
  file's own absolute path before evaluating it — plain `__FILE__` does
  *not* work for this, since `latexmk` evaluates rc files as a string rather
  than loading them as a real Perl file, so `__FILE__` inside one just
  reads as `(eval N)`, not a real path.
- `$do_cd = 1`, which makes `latexmk` change into the compiled file's own
  directory before doing anything, rather than using whatever directory
  `latexmk` itself was invoked from. Without this, `latexmk decks/foo.tex`
  run from the project root puts the PDF in the *project root*, not next to
  `foo.tex` in `decks/` — the exact "build files show up in the wrong
  folder" problem this setup exists to fix in the first place.

Compiling directly with `lualatex` (bypassing `latexmk` entirely) does not
read `.latexmkrc` at all, so none of this applies — always compile through
`latexmk` (or TeXstudio's `LaTeX` command, which is configured to do the
same thing above) rather than invoking `lualatex`/`biber` by hand.

## Naming and versioning convention

Every slide has a permanent, opaque **ID** (3 characters, e.g. `k7f`, minted
by `slide.new.id()` — see below). The ID never changes, even if the slide's
description or content changes, so it's safe to reference in your own notes
("see slide `xyz`") or to cite across decks. IDs deliberately avoid
confusable characters (no `l`/`1`, `o`/`0`, etc.).

**Regular slide IDs start with a letter** (since v5.10.0; SlideMage and
`slide.new.id()` only mint such IDs). IDs **starting with a digit are
reserved**: `1` + a letter other than `e` + one more character for the
SlideMage manual, `2` + a letter other than `e` + one more character for
demo/test slides
(`slide_ids.mint_slide_id(reserved="1")` / `"2"`). This makes it obvious at
a glance, from the filename alone, whether a slide is manual/demo content
or actual course/research material. IDs are compared without regard to
case when minting or renaming, since Windows file names can't tell `zzh`
from `ZZH`. (The manual's slides carry `1..` IDs and the demo/reference
slides `2..`; the uppercase `ZZ*` demo slides were retired or renamed in
v5.16.0. Existing digit-first IDs keep working, they are just no longer
minted.)
To give an existing slide a new ID, use `slide_rename.rename_slide_id(old,
new)`: it moves the files, rewrites every deck reference and
`\hyperlink{old}`, and updates `slide_ids.csv`, `media/alt-text.json` and
the cached previews.

Each slide also has a short, human-readable **slug** (hyphenated, e.g.
`MM-Theorem`). The slide's live content lives directly in its
`-current.tex` file — that's what you actually edit day to day:

```
slides/<id>-<slug>-current.tex                    # the live content -- edit this
slides/<id>-<slug>-v<major>-<minor>-<patch>.tex    # a frozen snapshot of *outgoing* content, taken at a past revision
```

Content is versioned only at the moment it's about to be revised, not on
every edit: right before making a significant change to a slide, freeze the
outgoing content as a numbered version, then keep editing `current.tex` for
the revision itself. A version file is a point-in-time snapshot, never
touched again once written; `current.tex` is the only file that changes day
to day. This means old versions stay usable: you can pin a specific version
in one deck (e.g. an older lecture you don't want to silently change) while
another deck follows whatever is current. SlideMage's own Save (in the Source view)
does this freeze-then-bump step automatically (see "Creating and revising a
slide" below) -- R's `slide.archive()` is still there for anyone editing
outside SlideMage.

When a save creates a new version of a slide that is used in more than one
deck, is pinned somewhere, or has a translation, SlideMage first shows
"Where this slide is used": per deck, *Move to current* (the default: a pinned
`\slideversion` / `\omitslideversion` becomes `\slide` / `\omitslide`; a call
that follows `current.tex` already moves on) or *Keep vX-Y-Z* (the call is
pinned to the version just frozen). Decks that only use `\slidefinal`,
`\conditionalslide` or `\slidestep` always follow `current.tex` and have
nothing to choose. A translation is named, with its decks, as a reminder to
update it too (it can be opened right after the save). A frozen version opened
from *Previous versions* has *Make this the current version*: the current
content is archived as a version first, and the old content comes back under a
new, higher version number.

The tracked version, when there is one, shows in the compiled footer next to
the slide id -- `(slide id: xyz | v1.2.0 | instructor deck)` -- for both a
bare `\slide{}` (whatever `current.tex` is currently tracked as) and a
pinned `\slideversion{ID-slug}{X-Y-Z}` (always that call's own `X-Y-Z`,
regardless of what `current.tex` has moved on to since). A slide with no
tracked version yet just omits that segment.

In your deck file:

```latex
\slide{k7f-EN-Standard-content}              % loads current.tex, i.e. the live content
\slideversion{k7f-EN-Standard-content}{1-0-0} % loads a specific frozen version instead
```

(`\slide{ID-slug}` extracts the ID for the footer by taking everything before
the first hyphen, so the slug can itself contain hyphens freely.)

### Slides with a course-specific date

A slide whose content includes a concrete date functioning as a deadline,
class date, or event date (e.g. "The deadline is March 31, 2026") is
otherwise-identical, reusable content across courses -- exactly the kind of
slide this project's versioning exists to share -- except that each course
genuinely needs its *own* date shown, permanently, not as a temporary
before/after revision. Referencing such a slide via a bare `\slide{ID-slug}`
from more than one deck is a trap: whichever course last edits
`current.tex` for its own date silently changes what every *other* course's
still-active deck displays too, with no warning.

The rule: **a slide with a course-specific date is never referenced by a
bare `\slide{}`** -- every deck that uses it pins an explicit
`\slideversion{ID-slug}{X-Y-Z}` to its own course's edition, even the course
that happens to have most recently edited `current.tex`. `current.tex`
itself is then just scratch space for whichever course next needs its own
dated edition -- edit it, then immediately freeze it as a new version
before pointing that course's deck at it, per the normal archive-then-edit
workflow above. This way every deck's own display is pinned and immune to
any other course's later edit, while the ID/file-naming still makes clear
at a glance that they're all editions of the same underlying slide.

`slides/qxr-Introduction-to-R-Assignments-current.tex` is a worked example:
FM2 pins `\slideversion{qxr-Introduction-to-R-Assignments}{1-0-0}` (deadline
March 31, 2026), IA2 pins `\slideversion{qxr-Introduction-to-R-Assignments}{1-2-0}`
(deadline October 31, 2025) -- see that slide's own header comment for the
full story.

### Deck inclusion tracking

Each slide file in `slides/` includes a header comment listing which decks it is
included in (e.g. `%% Included in decks: t-Uni-FM2-2027s, slidemage-manual`). This is
automatically maintained by the project's tooling.

When adding a new slide to a deck:

1. **For converted slides**: Add the `\slide{ID-slug}` call to the appropriate
   deck file in `decks/`. The deck inclusion header will be updated automatically
   on the next run of `.scripts/add_deck_headers.py`.
2. **For new slides**: After creating the slide with `slide.new()`, add it to
   the relevant deck(s) by adding `\slide{ID-slug}` calls.

**Note about `decks/#workdeck.tex`**: this project's single, reusable
scratch deck (see the directory-layout section above) is temporary and
freely rewritten by hand as work moves between slides/batches/decks --
unlike the retired per-deck `<deck>-preview.tex` convention it replaced
(which was regenerated automatically from the main deck file, never
hand-edited), `#workdeck.tex`'s own slide list is meant to be edited
directly: add whichever slides are currently being fine-tuned so they can
be reviewed without recompiling a real course deck.

## Creating and revising a slide

From R (after installing/loading the `RSlidemaster` package):

```r
# Brand new slide, fresh ID: seeds slides/<id>-MM-Theorem-current.tex
# from the starter template. Then just edit that file directly.
slide.new("MM-Theorem")

# Before making a significant revision to an existing slide, freeze the
# outgoing content -- copies current.tex to ab3-MM-Theorem-v1-0-0.tex
# without touching current.tex itself:
slide.archive("MM-Theorem", version = "1-0-0", id = "ab3")
# ...then edit slides/ab3-MM-Theorem-current.tex for the revision.
```

Picking the version number -- in particular, whether a revision is a
major/minor/patch bump -- is a judgment call: e.g. a reveal/animation-only
edit is a patch bump, not a minor one.

`slide.new()` mints an ID via `SPslide()` (only when `id` isn't supplied);
`slide_ids.csv` is kept up to date automatically.

If `slide_ids.csv` and the files on disk ever drift apart, rebuild the
registry from whatever's actually in `slides/`:

```r
SPslide(refresh = TRUE)
```

From SlideMage (the normal day-to-day path, 2026-08-20): every **Save**
of a slide's own `current.tex` asks how significant the change is --
**Major**, **Minor**, or **Patch** (each shown with the version number it
would bump to), or **Overwrite** for a change not worth recording at all
(a typo fix, tightening a sentence). Picking a bump level freezes whatever
was on disk immediately before the save as `<id>-<slug>-v<old-version>.tex`
(byte-for-byte, same as the manual R workflow above) and moves
`current.tex`'s own tracked version forward; **Overwrite** just saves, with
no freeze and no version change. A slide that has never been through this
prompt with a real bump choice has no tracked version at all -- its footer
shows no `v...` segment, and its first bump treats the untracked content as
if it were already `1.0.0` (so a first-ever Minor save freezes `v1-0-0` and
leaves `current.tex` at `1.1.0`). `current.tex` itself is never renamed --
only the frozen snapshot gets the `-v<version>.tex` suffix, exactly as in
the manual workflow. The **Slide versions** panel adds **Freeze as vX.Y.Z** (Major,
Minor or Patch): it freezes the current content under its own version and moves the slide
on, without a change to the text.

## Multi-language (EN/DE) slides

Added 2026-08-24 — this section covers the
day-to-day workflow. Every slide's id-slug now carries a language
segment as its second hyphen-delimited part —
`slides/<id>-<LANG>-<slug>-current.tex`, `LANG` one of `EN`, `DE`, or
`mult` (multilingual, see below) — parsed at compile time by
`Slidemaster_preamble_base.tex`'s `\setSlideLanguageFromSlug` and shown
in the footer appended directly to the tracked version:
`v1.1.0` becomes `v1.1.0EN`/`v1.1.0DE` (only once a version is tracked at
all — an untracked slide's footer still shows no `v...` segment).

A deck's default language is set near the top of the deck file
next to `\deckversion` (same `\ifdefined`-override pattern, for
SlideMage's own one-off render preview and ad-hoc testing):

```latex
\ifdefined\decklanguageoverride
	\decklanguage[\decklanguageoverride]
\else
	\decklanguage[en]           % options: en, de
\fi
```

In SlideMage, the top bar's **EN / DE** switch overrides this default for
the open deck. The slide list, preview, source editor, Details, side panels
and Compile PDF follow the linked slide in that language. A missing partner
keeps the called file and shows **No DE version** (or **No EN version**).
Unsaved edits are retained separately for each file when switching languages.

A linked translation occupies its original's place in the deck; an older
deck that also lists the translation elsewhere shows and compiles one slot.
The original call controls visibility and reveal steps. Translations have
independent version histories: an English pin still applies in EN, while DE
uses the German translation's current file. Alternate-language PDFs add
`-de` or `-en` to their usual name. SlideMage resolves calls in temporary
compile wrappers; compiling the raw deck outside the app keeps its literal
calls. For a deck that deliberately typesets both languages separately,
use independent copies without translation links.

### Creating a German translation of an existing slide

A German translation of a slide with real body text gets its **own,
new slide ID** — not a shared ID, not an inline conditional — since the
content genuinely differs and this project's whole versioning model
assumes one ID's `current.tex` is one evolving content stream. In
SlideMage, choose **Translate slide…** in the slide's right-click menu in the slide
list (or **+ Slide**, source **Translate**), pick **DE** and the English original: this
seeds the new file from the English slide's own body (machine-translated by a local or
cloud model if you choose one, else a starting point to translate from, not a finished
translation), adds the copy to the open deck right after the original, and writes both
cross-reference header comments automatically —
`%% Translation of: <english id-slug>` on the new file, `%% DE
translation: <german id-slug>` back on the English one. Then just edit
the new slide's body directly, same as any other slide.

If a slide's language needs to change later (including migrating an
older, not-yet-tagged slide), select it and use the
**Language** panel's language choice — this renames the file (and any frozen
versions) and rewrites every deck reference for you; it asks for
confirmation first, naming how many references will change. **Reestablish broken
translation links** (⋮ → *Housekeeping…*) refreshes every `Translation
of:`/`... translation:` comment from current disk state — safe to run
any time, e.g. after a manual rename elsewhere.

### Light, bilingual slides (image-only/title-only)

A slide whose only per-language difference is a short title or caption
(a figure-only slide, say) doesn't need a second file: give it the
`mult` language segment and switch its text with
`\multilingualtext{English text}{German text}`, which reads whichever
language the *deck* is compiling as. Pick **Multilingual** as the language in the Add
slide sheet to create one directly.

For more than two languages, or just for readability, use the keyed form:
`\multilingualtext*{EN={Hello}, DE={Hallo}, FR={Bonjour}}`. One `key={text}`
pair per language, the key being the deck's `\decklanguage` code (`EN` and
`en` are the same); the pair whose key is the deck's language is typeset. A
deck in a language the list lacks gets the `EN` text, or the first one if
there is no `EN`. Text with a comma or `=` in it needs its braces, as shown.
A deck in another language than English or German just says
`\decklanguage[fr]`; its PDF's language is then `fr`. (The two-argument form
is unchanged: English, then German.)

### Translating image descriptions/citations

The Images page's per-image form has a **DE** side (short/long
description, source, takeaway; the **EN | DE** switch at the page's top right) with a
**Translate** button that machine-translates the current English text via a
local or cloud model — review and edit before saving, same as any drafted
description. A German source citation is optional: leave it blank to
reuse the English one (most citations are proper nouns/publication names
that don't need translating), or fill it in only where it should read
differently.

The page's **Translate with** picker (any
model installed in Ollama, not just vision-capable ones — translation is
text-only) and its **Translate all…** button that batch-translates every
image whose English text is new or has changed since its last German
translation, same resumable/no-persisted-job-state design as **Draft
all…**. As of 2026-08-25 every existing image has a German translation.

Exactly what gets sent to the model — the instruction text, and how many
blank lines separate it from the text to translate — is configurable per
model and per language pair from **⋮ → Settings… → Prompts**, since different models expect different prompt shapes (a
dedicated MT model wants a short bare instruction; a general
instruction-tuned model tolerates a longer one). A model/pair with no
specific entry there falls back to that same tab's single editable
**default prompt**. The same Settings sheet also holds the dark-mode
toggle (General) and an **Ollama** tab for
freeing disk space — lists every installed model with its on-disk size
and can delete one via Ollama's own reference-counted deletion, which
only removes files no other installed model still shares.

## Available layouts

Defined in `Slidemaster_preamble_base.tex` (the shared layer — not in any
institution file, since none of this depends on the palette):

- `standardframe` — the default content slide (yellow dot bullets, matching PowerPoint):
  ```latex
  \begin{standardframe}{Title}
  	\begin{itemize}
  		\item ...
  	\end{itemize}
  \end{standardframe}
  ```
- Tall items for stacked fractions — a `\frac{...}{...}`/`\dfrac{...}{...}`
  bullet is visibly taller than a plain-text line (the fraction bar sits on
  the baseline with the numerator/denominator stacked around it), so it
  reads as cramped against plain-text neighbors without extra headroom.
  `\tallitem` (`Slidemaster_preamble_base.tex`) is a drop-in `\item`
  replacement that adds that headroom — use it in place of `\item` both on
  the fraction's own line *and* on whichever item renders immediately after
  it (the fraction extends below its own line too, not just above), unless
  that next item is itself already a `\tallitem` for its own fraction, or
  there is no next item in the list:
  ```latex
  \begin{itemize}
  	\tallitem $\dfrac{a}{b} = c$
  	\tallitem Whatever comes right after it
  \end{itemize}
  ```
  Takes an optional leading multiplier, default `1` (0.3em of whatever font
  is active at the call site — 3pt at this deck's usual level-2 itemize
  font, scaling automatically at other levels/font sizes): `\tallitem[1.5]`
  for 1.5x that, for a formula tall enough that the default doesn't read as
  enough room. Only reach for it on a genuine stacked display fraction, not
  any small inline `\frac` embedded mid-sentence. If the optional argument is
  not a number it is taken as the bullet label instead (2026-09-26):
  `\tallitem[\SMBulletEllipsis]` is an `\item[\SMBulletEllipsis]` with
  the default extra headroom (`\tallitem[]` gives a label-less one) — a custom
  label cannot be combined with a custom multiplier. A line that needs an empty
  `\item[]` label *and* the extra
  spacing (e.g. a display equation continuing the previous `\item`'s own
  sentence rather than starting a new bulleted point) uses `\tallitemnobullet`
  instead — same drop-in replacement, same optional multiplier
  (`\tallitemnobullet[1.5]`), just ending `\item[]` rather than `\item`. See
  `slides/nub-Disposition-Effect-Evidence-current.tex` for a worked example.
- Two columns — nest beamer's own `columns` *inside* `standardframe` (don't
  wrap `columns` in its own custom environment; see the comment above the
  `standardframe` definition for why that breaks beamer's per-frame overlay
  collection):
  ```latex
  \begin{standardframe}{Title}
  	\begin{columns}[t,onlytextwidth]
  		\begin{column}{0.48\linewidth} ... \end{column}
  		\begin{column}{0.48\linewidth} ... \end{column}
  	\end{columns}
  \end{standardframe}
  ```
  Avoid `columns` when one side has `\pause`/overlay-revealed content *and*
  the other side holds something bulky (an image, a diagram): beamer
  reserves layout space for a `\pause`'d item's full eventual height on
  *every* overlay step, even the ones where it's not shown yet, so a
  same-column image ends up competing for space with the text's fully-
  revealed height, not just whatever's currently visible — this can silently
  push later bullets off the bottom of the slide even though the log clearly
  says `Overfull \vbox`. If that happens: place the bulky content via a
  zero-space absolute tikz overlay instead (the same `\vbox to 0pt{\vss
  ...}` technique the footer/logo/title bar use), and — if it would
  otherwise overlap wrapped text, since a zero-space overlay draws over the
  normal flow rather than reserving room in it — wrap the text itself in a
  width-limited `minipage` (not `columns`, which is what caused the
  problem) so it doesn't wrap underneath the overlay's position.
  `slides/igr-Budgeting-current.tex` and
  `slides/bdh-Working-Capital-Example-current.tex` are worked examples of
  this pattern.

  The same space-reservation problem isn't unique to `columns`: a `minipage`
  placed inline in the normal text flow, with `\pause`-revealed content
  inside it, reserves that minipage's *full* final height from the first
  overlay step onward too — visually, this can make an ordinary text line
  placed right before the minipage appear to split apart around a large
  invisible gap. Same fix as above: move the `\pause`-revealed pieces into
  the zero-space absolute tikz overlay instead, using `\only<N->{...}`
  (removes the node's content, and its reserved space, entirely below step
  `N`) rather than a bare `\pause` in normal flow.
  `slides/ha9-Monacorp-Truck-Lease-Breakeven-Rent-current.tex` is a worked
  example (two independent `\only<2->`/`\only<3->` reveal steps, both
  inside one overlay `tikzpicture`).

  **A zero-space absolute overlay placed *after* a `\pause`/
  `\conditionalpause` is invisible on every overlay step but the last —
  put `\onslide<1->\relax` right before it.** This has now been
  root-caused three separate times in this project (2026-07-06 on
  `p33-Just-in-Time-vs-Just-in-Sequence`, again on
  `6ux-Example-51-BMA-Payback-Table`, and again 2026-08-11 on
  `sas`/`66w`/`dsk`, where two earlier sessions burned substantial time on
  it), so it belongs here rather than only in slide comments. `\pause`
  expands to `\onslide<n->\relax`, and that no-argument form of `\onslide`
  closes whatever `onlyenv` is open and opens a new `onlyenv<n->` that
  stays open **until `\end{frame}`** — so everything lexically after the
  last pause is *covered* on the earlier steps, however it is written.
  Beamer renders covered material by shifting it 2000bp off the page
  (pgf's `\pgfsys@begininvisible`), not by omitting it, so the symptom is
  a picture that silently doesn't appear even though the PDF content
  stream still holds a plausible-looking `Do` for it. Lexical position,
  not visual position, drives this — which is easy to miss precisely
  because an absolute overlay's own code can sit anywhere in the frame
  body without moving what it draws.

  Two fixes that look right and are *not* (both confirmed failing, twice):
  moving the picture to before the pauses instead — that does fix
  visibility, but a leading `\vbox to 0pt{}` in the frame body triggers
  the same `\topskip`/leading-box vertical shift documented for a leading
  minipage, so the body text then sits measurably lower (and can shift
  *between* overlay steps); and wrapping it in the `\onslide<1->{content}`
  *argument* form, which layers on top of the ambient `onlyenv` and can
  therefore only ever narrow visibility further, never widen it back out.
  Only the no-argument declaration form `\onslide<1->\relax` closes the
  open region. `slides/p33-Just-in-Time-vs-Just-in-Sequence-current.tex`
  (original investigation) and
  `slides/sas-Reference-Point-Parable-Father-Doctor-Dialogue-current.tex`'s
  own v1-7-0 comment (content-stream evidence, and the project-wide scan
  for other instances) are the worked write-ups.

  The corollary is worth stating separately, since it cuts the other way:
  when an overlay *should* sync with the last reveal step, placing it
  after the pauses and writing no overlay spec at all is a legitimate,
  deliberate idiom — `slides/6ux-Example-51-BMA-Payback-Table-current.tex`
  uses exactly that for its summary chart. Don't "fix" those.
- Definitions/formulas/examples/caveats — plain beamer blocks, themed by
  Gotham: `block`, `exampleblock`, `alertblock`, plus three project-added
  ones — `referenceblock` for reference/citation-style callouts,
  `definitionblock` for a definition that should stand out from an
  ordinary `block` at a glance: same colors/margins/font as `block`, just
  with a `$\triangleq$` symbol flush right in its own title bar; and
  `infoblock` for a supplementary/informational aside, blue-themed
  (`bg=c_secondary_blue`) with a circled-i marker flush right in its own
  title bar. `slides/4uq-Definition-of-Capital-Market-Efficiency-current.tex`,
  `slides/dny-Leasing-Definition-current.tex`, and
  the manual's slide `1x6` (Blocks, all six side by side) are worked
  examples. All six span the full frame
  width like any other block; for one narrow enough to place freely (e.g.
  beside a table, inside a tikz overlay `\node`), use `gothamfloatingblock`
  instead — same title/body colors and font as `block`, just wrapped in an
  extra minipage of the caller's own chosen width:
  `\begin{gothamfloatingblock}{5cm}{Title} ... \end{gothamfloatingblock}`.
  `slides/ha9-Monacorp-Truck-Lease-Breakeven-Rent-current.tex` is a worked
  example. `infoblock`'s own floating counterpart is
  `gothamfloatinginfoblock` (same two-argument call shape), typically
  anchored top-right against the institute logo via the same absolute-tikz-
  overlay corner pattern the institute logo itself uses, with a fixed
  `-\SMContentTopAlign+6.02pt` intrinsic gap correction on the anchor
  node (confirmed empirically, not derived — see
  `\SMFloatingInfoblockRightAlign`'s own comment in
  `Slidemaster_preamble_base.tex`) —
  `slides/k4p-Introductory-Question-Answer-current.tex` and
  `slides/2s4-EN-Groups-SE-COF-current.tex` are worked examples.
- Title slide: `\titleframe{Title}{Author\\Term}` — see "Special frame types"
  below (this replaces the older
  `\begin{frame}[plain,noframenumbering]\titlepage\end{frame}` convention).
- Section dividers: use `sectionframe` (see "Special frame types" below),
  loaded like any other slide via `\slide{}` — **not** plain beamer/gotham's
  own automatic section-divider frame. `\section{Title}` (placed right
  before that chapter's `sectionframe` `\slide{}` call, titled to match it
  exactly) is still worth adding on top, purely so the chapter feeds
  `\tableofcontents`/the outline (see `slides/nkj-Agenda-current.tex` for
  a slide built entirely from `\tableofcontents`) — but gotham's own
  default behavior on `\section{}` is to *also* auto-insert its own plain,
  unstyled divider frame plus a mini current-section-highlighted outline
  frame, which would otherwise show up redundantly right next to this
  project's own hand-styled `sectionframe`. `Slidemaster_preamble_base.tex` turns
  that default off (`\gothamset{sectionframe default=false}`) so
  `\section{}` only feeds the outline, without side effects on the frame
  sequence itself.
- Single key-statement slide: `\begin{frame}[standout]{...}\end{frame}`.

The manual's chapters "Frame types" and "Content and layout" demonstrate
all of the above, one layout per slide, each with its own source beside it
(`1y8` standardframe, `1wa` columns and tables, `1x6` blocks, `1xf`
standout) — copy from whichever's closest when starting a new slide.

`standardframe` content is top-aligned (not beamer's default vertical
centering) and its first itemize level sits flush with the frame title, with
each deeper level indented just enough for its dash to land under the text
of the level above. Pass `[c]` explicitly (`\begin{standardframe}[c]{Title}`)
if you want a particular slide vertically centered instead.

## Layout helpers (instead of per-slide adjustments)

**Names:** everything this framework adds is named `\SM...` (`\SMContentTopAlign`,
`\ifSMInstructorVersion`, TikZ style `SMImageBorder`); `\gotham...` names belong
to the vendored Gotham theme only. Up to v5.2.0 the framework's own names were
`\gotham...` too -- a project still using them is migrated with
`python -m slidemage.sm_rename <project folder>` (`--dry-run` first to see the
counts).

Added 2026-09-30, after an audit found the same hand-measured fixes repeated
across hundreds of slides (and silently going stale whenever a central value
changed). Existing slides were switched over where the result is
pixel-identical; everything below is what new slides should use.

- **Top Margin is automatic.** Every top-aligned `standardframe` (and
  `figureframe`, `highlightframe`, `sideimageframe`) measures where its first
  visible content landed -- a text line's top, an image's or a table rule's
  top edge -- and moves its body onto the Top Margin line on the next compile
  (recorded in `<jobname>.top`, the way `\SMFinalStateForStudents` uses
  `<jobname>.ovl`; latexmk reruns by itself). No more
  `\SMIncreaseContentTopShift`/`\SMReduceContentTopShift` values:
  they still compile but no longer matter. A slide that is full never gets
  pushed down into its footnotes/footer -- the correction stops 1pt above
  them. Absolute overlays (corner images) are not moved; they are placed on
  the margin by `\cornerfigure` already. Exceptions: `[c]` frames,
  `sectionframe`, a `\progressstrip` frame, and any frame preceded by
  `\SMManualTopMargin` (keeps the hand-placed position). A deck can
  switch the whole mechanism off with `\SMAutoTopMarginfalse`.
- **`\cornerfigure[height=5cm, border]{media/chart-x.png}`** -- an image in a
  corner of the content area as a zero-space overlay. Give `width=` or
  `height=` (the other follows from the aspect ratio) and the argument is the
  image file; `border` adds the yellow image border. Other keys:
  `corner=ne|nw|se|sw|e|w` (default `ne`; `e`/`w` = on the Right/Left Margin,
  centred between Top and Bottom Margin), `xshift=`, `yshift=`, `node={...}`.
  Without `width`/`height` the argument is arbitrary content; `block` for a
  `gothamfloatinginfoblock` (lifts it by its own top padding, aligns its
  visible right edge with the logo).
- **Borders position the figure:** a node with the `SMImageBorder` style has
  its anchors on the border's *outer* edge, so a bordered figure anchored at a
  margin has its border on the margin; without a border the image's own edge
  is on it.
- **`\begin{besidefigure}[height=5cm, border]{media/chart-x.png} ... \end{besidefigure}`**
  -- text next to a corner figure (same keys as `\cornerfigure`, plus
  `gap=`, default 12pt); the text column is exactly as wide as the room left
  of the figure, measured from the figure itself. Since v5.27.0 the figure's
  top edge is lowered by `\SMBesideFigureTopGap` (0.2em) so that it meets the top of the
  first line's *letters* instead of that line's box (which sits on the Top
  Margin and starts about 0.2em above the letters); `yshift=0pt` among the keys
  puts the figure on the margin again.
- **`\fitfigure[top=here|margin, gap=6pt, valign=, halign=, bottom=, node=]{file}`**
  -- an image as large as it fits (aspect ratio kept) between the current
  position (or the Top Margin) and the Bottom Margin, Left to Right Margin.
- **Bottom Margin** is now a length, `\SMContentBottomAlign`: the footer
  box plus the same gap the Top Margin leaves below the title bar.
- **`\begin{gothamtable}[gap=12pt]{lccc}`** -- flush table edges (rules end
  at the text) with the column gap built in; after a `p`/`m`/`b` column the
  gap is a real separator. Without the option a gothamtable is unchanged.
  Inside any block the rules are dark automatically.
- **Floating blocks** (`gothamfloatingblock`/`...exampleblock`/`...infoblock`)
  pad their body themselves: `[top=2mm, bottom=1.2mm]` by default, `0pt`
  for none.
- **Reveals:** `\deckitem<3->` (an item revealed in the instructor deck, a
  plain `\item` in the student decks -- no more writing the item twice);
  `\deckreveal*`/`\deckrevealfinal*` keep the content's space on the earlier
  steps (nothing jumps when it appears); TikZ `visible on=<3->` does the same
  for a drawing element.
- **Small ones:** `\shrinklists{1|2|3}` (all list levels one/two/three sizes smaller; 3 is
  `\scriptsize` throughout, the floor),
  `\EUR` (euro sign in text and math), `\SMTikzmark{name}`, TikZ styles
  `gotham highlight`, `gotham dotted highlight`, `gotham arrow`.
- **`\SMCodeFile[keys]{snippets/abc-1.tex}`** (since v5.11.0) -- LaTeX
  source on a slide, read from its own small file at the project root (the
  slide then needs no `[fragile]` frame, and the code is exactly the text
  in that file): Fira Mono on a light gray panel, every control sequence and
  every comment in its own colour. The three colours are named colours a
  template sets before `\input{Slidemaster_preamble_base}` (since v5.17.0):
  `SMCodeKeywordColor`, `SMCodeCommentColor`, `SMCodeBackgroundColor`; a
  template that doesn't set them gets the highlight colour, `c_primary_gray`
  and `c_tertiary_gray`, which is unreadable with a yellow or orange
  highlight colour -- so the Graz, MCI and Innsbruck templates set a dark
  blue, a dark gray and (MCI, Innsbruck) a lighter panel, all at least 5:1
  contrast. The keys go to `\lstinputlisting`
  (`firstline=`, `lastline=`, `basicstyle=\SMCodeFont\tiny`, ...); the size
  is `\SMCodeSize`. Write the files in ASCII (umlauts, dashes, `·`, `…` and
  `→` are mapped). The transcript shows the file as a code block, and the
  pre-render check reports a missing file. Name them after the slide:
  `snippets/<slide id>-<n>.tex`. The panel is a box that holds everything it
  draws (since v5.14.1), so beside text in `columns[T]` both start on the
  Top Margin.
- **`\SMCode{text}`, `\SMCmd{name}`** (since v5.13.0) -- code in running
  text: Fira Mono Regular at 90% (`\texttt` is the theme's Fira Mono Bold,
  heavy and wide next to the Fira Sans Light body text). `\SMCmd{slide}`
  prints `\slide`; the argument is typeset, so write `\_`, `\{`, `\}` as in
  any text. The transcript shows both as `code`.
- **`\SMTikzword{name}{text}`** -- a word as a named TikZ node, so an
  overlay arrow can point at it (`(name.south)`, ...) and follows it when the
  layout moves; transcripts keep the word.
- **Text column beside a figure (two minipages):** align them at the top --
  `\begin{minipage}[t]{...}\vspace{0pt}` for both -- and start the text's first
  line with `\SMLineTop`; text and figure then both start on the Top Margin.
  Without `[t]` the minipages are vertically *centred* (LaTeX's default) and the
  shorter column starts lower.
- **`\sectionfigure[keys]{image}`** (in a `sectionframe`) -- the side image
  from the title bar to the footer, flush with the right edge; the frame's
  footnotes (image source included) go into the rotated strip beside it.
- **Footnotes inside a minipage/column** now join the frame's other footnotes
  at the bottom (beamer's `[frame]` footnotes are the default).

## Special frame types

Five more frame types, all converted from `ExampleSlides.pptx`. All five
deliberately reuse as much of `standardframe` — and of each other — as
possible: `sectionframe`,
`figureframe`, and `highlightframe` are literally thin wrappers around
`standardframe` itself (same title bar, logo, footer, bullet styling —
only what's documented below differs); `titleframe` and `quoteframe` can't
be `standardframe` wrappers (both are title-less, and `quoteframe` replaces
the whole body layout) but still reuse its palette, fonts, and margins.
The manual's slides `1jh`, `1y9`, `1i4`, `1rb` and `1mb` are working
demos of all five, one each, in that order (slide `1td` is a gallery of
every frame type).

### Title slide (`titleframe`)

The deck's own title slide — typically used exactly once, at the very start
of a course's first deck. One continuous yellow box — like standardframe's
own title bar — flush with the page's top and left edges and reaching down
far enough to hold both the title and a second line below it (author/term/
whatever), stopping short of the institute logo on the right (same margin as
elsewhere); black text, no footer or frame number:

```latex
\titleframe{Financial Markets}{Stefan Palan\\Summer term 2026}
```

`\titleframe` is a *command*, not an environment — its second argument
becomes the second line's content (plain text, `\\` for line breaks, not an
itemize). This has to be a command rather than an environment with the
content as its body: beamer's frame body is captured by a delimited-argument
macro (`\beamer@collect@@body`) hunting for a literal `\end{frame}`, and a
custom environment whose begin code opens something (a `beamercolorbox`, a
`vbox`, ...) that its end code closes confuses that hunt exactly like the
`columns` example above (same root cause, different environment): compiling
ends in "`! File ended while scanning use of \beamer@collect@@body.`" every
time, however short the body. Taking the content as a normal brace argument
sidesteps the issue entirely, since the whole construction is then
self-contained inside one macro invocation with no begin/end split for
beamer's collector to trip over. `quoteframe` below hits the same constraint
for the same reason.

The box's height (`\SMTitleframeBoxHeight`) is a fixed target for its
*bottom* edge, not for the blank space above the text — that space is
derived from it instead (box height minus the title+subtitle content's own
measured height), so the bottom edge stays put even if a longer title ever
wraps onto a second line; the blank space above just shrinks to compensate
(if a title were long enough to overflow the box entirely, the text would
start above the page's top edge — there's no fallback for that case, since
`titleframe` is normally used once with short, predictable copy). The text
itself doesn't sit flush with the box's bottom edge either — a further
length, `\SMTitleframeBottomPad`, reserves about 1.5 line-heights of
blank box below the last line, empirically calibrated the same way (both
these lengths need re-measuring if the title/subtitle font sizes change).

Two gotchas hit while building this, both fixed and left commented in the
source: `\\` inside the subtitle's text (for a line break) silently breaks,
since beamer redefines `\\` inside every frame to peek for an overlay spec
(`\\<2->`) and that redefinition doesn't expect to run outside its own
frame-body machinery — fixed by locally restoring plain LaTeX's `\\` just
for this construction. And a bare `tikzpicture` used as a page-corner
overlay (for the yellow box and the logo) behaves like an hbox and silently
opens an implicit paragraph, which broke the vertical spacing computed
just after it (glue meant to push the text down came out as *horizontal*
space instead) — fixed the same way the footer's own yellow box already
does, by wrapping each in `\vbox to 0pt{\vss ...}`.

### Section overview (`sectionframe`)

Same layout as `standardframe` — footer, logo, bullet styling all completely
unchanged — except the title bar is much taller (about a third of the page)
and set in a bigger font, and the body text is a step bigger too, so it
reads as "somewhat greater focus" and is unmistakable at a glance when
flipping through slides. Still the deck's usual yellow-background/black-text
look, not an inverted color scheme:

```latex
\begin{sectionframe}{Efficient Market Theory}
	\begin{itemize}
		\item Definition
		\begin{itemize}
			\item Implications
			\item Forms
		\end{itemize}
		\item Tests
		\item Evidence
	\end{itemize}
\end{sectionframe}
```

The taller bar isn't a second box drawn on top the way `titleframe`'s is —
it grows the gotham theme's *own* title box instead, by locally overriding
the length that theme already sizes it from
(`\gothamFrametitleBottompading`) plus the title font size, calibrated
against the rendered PDF to land the bar at almost exactly a third of the
page. Growing the theme's own box like this (rather than fighting it with a
separately-drawn one) means the white-patch-behind-the-logo machinery keeps
working *mostly* unmodified — except for one part of it that had to be
switched off: alongside the small patch that clears the logo's own column,
that machinery also paints white, full page width, from the logo's bottom
edge down to the title box's true bottom edge, to trim away what's normally
just a ~1-2pt sliver of yellow poking out past the logo on an ordinary short
bar. On a bar this tall, that "sliver" is most of the box — silently wiping
out nearly all the yellow with white the first time this was built.
`\SMFrametitleFullHeightYellow` is `sectionframe`'s opt-out for that
specific patch (set the same way, and reset the same way, as
`\chapterlogo{}`'s path).

The title text is bottom-anchored within the bar — sitting about half a
line height above the bar's bottom edge, growing *upward* for a title long
enough to wrap onto a second line, rather than top-anchored the way
gotham's own template flows by default (which would instead leave a
growing gap *below* a wrapped title). gotham's template has no built-in way
to do this — its only two knobs are the top/bottom padding struts, both
anchored to one end of a single top-down flow — so
`\gothamFrametitleToppading` is computed fresh for every `sectionframe`,
from a separate measurement of the title text's own rendered height
(`\SMSectionframeTitleBox`, built with the same font/approximate width
gotham gives it) rather than left at a fixed value:
`toppading = boxHeight - bottompading - measuredTitleHeight` (plus a small
empirically-measured correction — gotham's real leading strut doesn't
behave quite like a plain measured `\vbox`, see the comment above
`sectionframe`). A longer/wrapped title therefore shrinks toppading
automatically, pushing the whole title block up rather than changing the
gap below it.

**Since v5.28.0 every `sectionframe` bar is 85.04 bp tall, whatever the title.** The
title measurement now starts with a `\strut` (one line height for every title, so tall
letters like f/l/d no longer shift the bar) and the formula subtracts a fixed
reference depth, `\SMSectionframeRefDepth` (4.42pt), instead of the title's own depth;
`\SMSectionframeHeightCorrection` was recalibrated to 16.03pt for that. `\sectionfigure` and
`\SMSectionframeTrueBoxBottom` use the same constant. The body text starts 1.5pt lower than
before (`\SMSectionframeContentDrop` 11.5pt). Put the chapter intro in a top-aligned
`minipage[t]` and call `\sectionfigure` last in the body (it starts a paragraph line of its
own). The next paragraphs describe the behavior before v5.28.0, where this was
title-dependent.

**This toppading formula has a real, confirmed side effect: the bar's own
visible height depends on whether the title text has any descenders (`g j p
q y`), not just on `\SMSectionframeBoxHeight` (2026-07-25, direct
instruction: "the image extends into the title box" on
[neb](example/slides/neb-Market-Environment-Section-Overview-current.tex)/
[u97](example/slides/u97-Household-Finance-Section-Overview-current.tex) — root-caused
after their own images, placed flush against `\SMSectionframeBoxHeight`
directly, turned out to sit ~4.2pt too high; see those two files' own header
comments for the fix actually applied).** `\SMSectionframeBoxHeight`
(85.04pt) is only the *target* this formula solves for — by construction,
`toppading + measuredTitleHeight + measuredTitleDepth + bottompading` should
algebraically equal `\SMSectionframeBoxHeight + \SMSectionframeHeightCorrection`
regardless of title content, since the formula solves for toppading from the
other three. In practice it doesn't stay constant, because gotham's own
`\gotham@frametitlestrut@start`/`@end` (`gotham.dtx`) don't actually implement
"toppading + title + bottompading" as three independently-stacked lengths the
way that algebra assumes:
- `@start` is a zero-depth `\rule` of height `toppading + \totalheightof{X}` —
  a *fixed reference glyph* ("X", no descender), not the real title text. Its
  height dominates the line, so the line's rendered height ends up
  `≈ toppading + capheight`, not `toppading + <real title's own ht>`.
- `@end` is a zero-height `\rule` of depth `bottompading` (19.90pt for
  `sectionframe`, `\SMSectionframeBottomGap+\SMSectionframeBottomPadCorrection`)
  — a *fixed* depth, not the real title's own depth.
- The real title text (`\insertframetitle`) sits between these two struts and
  contributes its own real height/depth to the same line — but a line's
  rendered depth is the *max* of every contributor's depth, not a sum. Since
  `bottompading` (19.90pt) is far bigger than any real title's own descender
  depth (measured directly: `0.25pt` for a title with none, e.g. "Market
  Environment"/"Household Finance"; `4.42pt` for one with any, e.g. "Capital
  asset pricing model"/"Measuring and managing risk" — the exact letter or
  count of descenders doesn't matter, only whether at least one is present),
  `bottompading` always wins there — so the real title's own depth is *never*
  actually given back anywhere in the rendered box.

Net effect: the toppading formula's own `- measuredTitleDepth` term shrinks
toppading (and therefore the strut's own height, and therefore the whole
box) by the title's real descender depth, but nothing anywhere else adds
that same amount back. A title with **no** descenders renders the bar at
its full, undiminished height (confirmed directly, PyMuPDF vector-fill
measurement: 89.19pt); a title with **any** descender renders it ~4.15pt
*shorter*, landing almost exactly on the 85.04pt target instead (confirmed
the same way, both
[tyn](example/slides/tyn-Capital-Asset-Pricing-Model-Section-Overview-current.tex)
("Capital asset pricing model") and
[vtm](example/slides/vtm-Measuring-and-Managing-Risk-Section-Overview-current.tex)
("Measuring and managing risk") land at 85.04pt too, both titles with a
descender). This is presumably a coincidence of whichever title was on
screen when `\SMSectionframeHeightCorrection` was originally calibrated
(a descender'd one), not a design choice — but it means
**`\SMSectionframeBoxHeight` was never actually a title-independent
constant**, and anything anchoring itself directly against it (as neb/u97's
own decorative-image overlay does, the `sideimageframe` technique from
"Side image" below applied to `sectionframe`'s own box) needs the bar's real,
per-title rendered height, not this target.
`\SMSectionframeTrueBoxBottom` (`Slidemaster_preamble_base.tex`, right
after `\SMSectionframeBoxHeight`'s own definition) is that measured
value — but it's **only valid for a title with no descenders**, matching the
two slides (neb/u97) that currently use it; a *different* sectionframe with
a descender'd title (like tyn/vtm above) should keep anchoring against
`\SMSectionframeBoxHeight` directly instead (already correct for them,
confirmed the same way), and a sectionframe whose title text might change
in the future should re-measure (real vector fill, not a visual guess) as
part of that edit rather than assume either constant still applies.

The institute logo, though, stays exactly where it sits on every other
frame type — even though gotham normally vertically centers it against the
title's own baseline (which would otherwise drag it down along with a
bottom-anchored title). `\SMFrametitleLogoFixed` is `sectionframe`'s
opt-in for the frametitle hook to redraw the logo at a fixed page-corner
position instead of wherever the title line puts it (same
set-before/reset-after mechanism as `\SMChapterLogoPath`/
`\SMFrametitleFullHeightYellow` above) — the white patch behind it
already covers the logo's full column down to the bar's bottom edge
regardless of which position is used, so this doesn't need any patch
changes of its own. `\SMSectionframeContentDrop` adds a little extra
room below the bar before the body content starts, on top of
`standardframe`'s usual pull-up.

A long title (long enough to wrap onto a second line, which is common at
`\huge`) needed one more piece: gotham's own frametitle template puts the
institute logo directly after the title text on the *same paragraph line*,
with a forbidden break point between them, and `sectionframe` doesn't use
that inline logo at all (it draws its own, at a fixed position, as above) —
so `sectionframe` switches to its own frametitle template variant,
`uni_graz_no_inline_logo`, that drops the inline logo entirely and instead
reserves the same horizontal margin for it via `rightskip` (kept ragged, not
justified, so a wrapped line doesn't stretch its word-gaps to fill that
reserved margin). Hyphenation is also switched off for the whole
environment, so a line break only ever lands between words.

### Quote (`quoteframe`)

No title (a quote doesn't need one), but the institute logo shows as usual,
and the usual footer still shows too (unlike `titleframe`, which drops it —
a title slide is a one-off outside any particular course content, while a
quote is still one slide *among* a deck's others, worth being able to
reference by its footer slide ID like any other). The quote itself is
large, italic, and black on a yellow full-bleed block — the same style as
`titleframe`/`sectionframe`'s own title boxes (flush top-left, stopping
short of the logo), reaching down to 80% of the page — with opening/closing
curly quotes added automatically; write the quote text with none of its own:

```latex
\quoteframe{One of the funny things about the stock market is that every
	time one person buys, another sells, and both think they are astute.}%
	{William Feather, 1889-1981}
```

The second argument is the person it's from, set smaller/plain/italic,
below the yellow block and right-aligned to *its* right edge (not the
page's usual text margin) — pass an empty second argument (`{}`) for an
unattributed quote.

Two rules for the rest of the slide:

- **Source line:** put `\quotesource{...}` *before* `\quoteframe`, as every
  quote slide does. A plain `\source{}` after it lands outside the frame
  and produces an extra, nearly empty page carrying only the footer.
- **Reveal steps:** the quote text may contain `\conditionalpause`,
  `\uncover` and the like, to reveal it sentence by sentence. It is set in
  a `\parbox` (rather than the node's own `text width`) precisely so that
  works, and so the reveal doesn't cover the source line and footer that
  follow it; see the comment above that node in
  `Slidemaster_preamble_base.tex` for the two beamer/TikZ failures this
  avoids. Existing quote slides render pixel-identically.

Every piece of this — box, logo, quote text, attribution — is drawn as a
zero-space overlay anchored to absolute page coordinates, rather than any
of it flowing through the frame's normal vertical list (the same
`\vbox to 0pt{\vss ...}` pattern used elsewhere in this file). That
sidesteps needing to know or cancel out beamer's own default top-of-frame
spacing, since nothing here is positioned relative to the frame's own flow
at all. Like the other page-corner overlays in this file, this needs the
usual second compile pass (see "Title bar and logo" above).

### Figure only (`figureframe`)

Same `standardframe` layout (title, footer, `\source{}` for the usual
"Source: ..."/"Image source: ..." line), but meant for a slide that's just
a figure, with the figure positioned via `\figurecenter` (call inside the
frame body, right before the figure) rather than left-aligned, which is the
default:

```latex
\begin{figureframe}{Correlation between DJIA stock returns over 15 years}
	\includegraphics[height=0.7\textheight]{correlation-matrix}
	\source{Source: Own illustration, data from Yahoo! Finance, 24.02.2026.}
\end{figureframe}
```

```latex
\begin{figureframe}{Title}
	\figurecenter
	\includegraphics[width=0.6\linewidth]{diagram}
\end{figureframe}
```

`\figurecenter` is plain `\centering` under a more discoverable name,
nothing more — unlike `\chapterlogo{}`/`\sidefootnotes`, it isn't an opt-in
flag called *before* `\begin{figureframe}`, since there's nothing here for
the frame's own opening code to read: it just needs to take effect exactly
where it's called, like any other formatting declaration. Vertical
placement is `standardframe`'s own `[t]`/`[c]` (figureframe's optional
argument passes straight through), so `\begin{figureframe}[c]{Title}`
vertically centers exactly like `\begin{standardframe}[c]{Title}` already
does; `\figurecenter` only ever affects the horizontal axis.

### Full-bleed image (`fullbleedframe`)

For a slide that's *only* a full-screen image — no title, no footer, no
logo — unlike `figureframe`, which always keeps `standardframe`'s usual
chrome:

```latex
\fullbleedframe{media/photo-recruitment-flyer.png}
```

The image is scaled to fit the slide while keeping its own aspect ratio
(`\includegraphics`'s `keepaspectratio`, capped by width *and* height
together); whatever's left over on the binding axis is filled by a solid
black backdrop (`\SMFullBleedBlack`, a fixed HTML black — deliberately
*not* a `\colorlet` of `c_primary_dark`, so this stays neutral even if
that color is ever restyled) rather than showing the frame's usual white
canvas. A single command, not an environment — same reasoning as
`\titleframe`/`\quoteframe`.

### Side image (`sideimageframe`)

A `standardframe` that always carries one auto-placed image — formalizes
the ad-hoc "side filler image" technique used on e.g.
`slides/dfc-Angel-Investors-current.tex` into a reusable frame type,
rather than hand-repeating the same overlay/positioning math per slide:

```latex
\begin{sideimageframe}{Title}{media/photo-example}
	\begin{itemize}
		\item ...
	\end{itemize}
	\source{...}
\end{sideimageframe}
```

The image is positioned flush to three edges: top against the title bar's
own bottom edge, right against the page's own right edge, bottom against
the footer box's own top edge — scaled by *height* to exactly fill that
gap (`keepaspectratio`, so width follows from the image's own aspect ratio
rather than being forced to some separate target), anchored at the page's
north-east corner so the top/right touches come for free and the height
alone guarantees the bottom touch too.

Footnotes on a `sideimageframe` are automatically rotated along the page's
left-of-image margin (`\sidefootnotes` under the hood, switched on by the
frame type itself, not something the caller needs to opt into) — with the
strip's own horizontal position computed from the image's actual rendered
width, so it always sits immediately left of the image rather than at the
page's raw right edge (which would run underneath the image instead, the
same collision `sidefootnotes` has to actively avoid on
`slides/u29-Implications-of-Capital-Market-Efficiency-Prices-current.tex`).
`slides/xmp-Implications-of-Capital-Market-Efficiency-Considerations-current.tex`
is a worked example.

### Presenter-attention slide (`highlightframe`)

A `standardframe` with two things about it made unmistakably different — the
title bar's *and* the footer's background color, both together — so a
presenter can never flip to it without immediately noticing:

```latex
\begin{highlightframe}{Implications of Share Repurchases}
	\begin{itemize}
		\item Share repurchase is equivalent to dividend if there are no taxes
	\end{itemize}
\end{highlightframe}
```

Everything else — body, logo, bullet styling — is exactly `standardframe`'s
own. The accent color is the named color `SMHighlightColor`, set via
`\colorlet` rather than baked directly into the environment, so retargeting
every `highlightframe` in a deck to a different color — title bar and
footer both — is still a one-line change
(`\colorlet{SMHighlightColor}{...}`).

### Step strip (`\progressstrip`)

An edge-to-edge strip in the institution's tertiary yellow, flush below the
title bar, that lists a short chain of steps joined by arrows and underlines
the current one, for a run of slides that walk through the same chain
(written for the Publishing masterdeck's "Field > Topic > Question" slides).
Call it as the very first thing in a `standardframe`:

```latex
\begin{standardframe}{General research strategy}
	\progressstrip{Field,Topic,Question}{1}   % 1 = "Field" underlined
	\begin{itemize} ... \end{itemize}
\end{standardframe}
```

The strip is a zero-space absolute overlay (so it can span the whole page
width); the macro's trailing `\vspace` reserves its height, so no
`\SMIncreaseContentTopShift` is needed.

## Title bar and logo

The Uni Graz logo (`scheme_uni_graz/Logo Uni Graz 4c-cropped.png` — a version of
`Logo Uni Graz 4c.png` with its hidden transparent margin trimmed off, so its
margins are exact rather than inflated) sits vertically centered in the
yellow title bar, with the same small margin on all sides. The yellow bar is
made to visually stop short of the page's right edge by painting a white
patch (sized to the logo, spanning the full height of the bar) over that
corner and redrawing the logo on top of it, so the logo ends up on white
instead of on yellow. A second white patch spans the *full width* of the bar
from the logo's bottom edge down to the bar's actual bottom edge, so the
yellow appears to end flush with the logo's bottom rather than extending
further down under the title text too (width and top position unchanged).

**This requires compiling twice.** The white patch is positioned using a
tikz `remember picture` node that marks the bottom of the title bar; like any
`remember picture`, its coordinates are only available in the `.aux` file
written by the previous run, so the very first compile of a new/cleaned deck
will be missing the patch and logo on the title bar (compile it again and
they'll appear). This matches normal LaTeX practice for cross-references and
the table of contents, which also need a second pass.

### Chapter logo

Any `standardframe` can optionally show a second, topic-specific logo (e.g.
an icon for the current chapter/section) immediately to the left of the main
institute logo, on its own white patch. Opt one frame in by calling
`\chapterlogo{path/to/image.png}` *before* that frame's `\begin{standardframe}`
(it must come before, since the frame title — and the logo drawing it
triggers — is typeset as part of `\begin{frame}` itself, before any frame-body
content runs):

```latex
\chapterlogo{media/chapter-logo-sustainable-investment-cropped.png}
\begin{standardframe}{PAIs}
	...
\end{standardframe}
```

`standardframe` automatically resets this on `\end{frame}`, so it only
applies to the one frame that follows the `\chapterlogo{}` call — every other
slide is unaffected unless it opts in the same way. The chapter logo is drawn
at the same height as the main logo, with exactly one `\gothamFrametitleRightpading`
of margin on both sides (to the main logo, and to where the yellow bar
resumes) — the same length already used around the main logo, not a new
constant.

**Crop the source image first**, the same way `scheme_uni_graz/Logo Uni Graz 4c-cropped.png`
already is for the main logo: `\chapterlogo{}`'s margins are measured against
the image file's own edges (via `\settowidth`), not against whatever icon is
visually drawn inside it. A source image with baked-in whitespace around the
icon (common — the sustainable-investment icon above had ~30% padding on each
side, asymmetric) makes the two margins visibly unequal despite the code
being exactly symmetric. Crop to the icon's tight bounding box before using
it (keep the original alongside it, as `media/` does here: the plain filename
is the untouched source, `-cropped` is what slides actually reference).

### Color palette

Every color the preamble defines follows a `c_<tier>_<hue>` naming scheme
(e.g. `c_secondary_blue`), usable anywhere a color name is expected
(`\textcolor{c_secondary_blue}{...}`, `fill=c_secondary_blue`
in tikz, etc. — see the manual's slide
[slides/1u5-EN-Color-and-Emphasis-current.tex](example/slides/1u5-EN-Color-and-Emphasis-current.tex)
for `\textcolor{}` in body text). These names are shared machinery, defined
once per institution in that institution's own `Slidemaster_preamble_*.tex`
(see the directory layout above for the base/institution-layer split) with
different hex values — a slide
that uses `c_secondary_blue` renders in Graz's blue, MCI's blue, or
Innsbruck's blue depending only on which preamble the deck `\input{}`s, with
no change to the slide itself. For a visual reference of all of them under
whichever preamble is currently loaded — see the swatches on the manual's
slide [slides/1pf-EN-One-Look-Several-Institutions-current.tex](example/slides/1pf-EN-One-Look-Several-Institutions-current.tex)
(until v5.16.0 a demo slide, `ZZM`, showed a tikz `\foreach` grid of
colored boxes, one loop over all the color names). Watch for one gotcha if
extending that list: a multi-line `\foreach ... in {...}` list needs a
trailing `%` at the end of every line (including the last item before the
closing `}`) — without it, the newline before the closing brace becomes part
of the last item as a literal trailing space, breaking that one color's name
("Undefined color" from `xcolor`, easy to misdiagnose as a typo in the color
name itself rather than stray whitespace).

The list is sorted by relevance, not alphabetically or definition order: the
four primary colors first (`c_primary_dark`, `c_primary_highlight`,
`c_primary_gray`, `c_primary_white`), then the secondary colors (six hues,
each paired with its tertiary/lighter variant), and finally the three
`c_custom_*` colors last — unlike every other color here, not part of any
institution's official palette, just supporting colors this project defines
itself (see each one's own `\definecolor` comment in whichever
`Slidemaster_preamble_*.tex` is current); the name flags that on sight, so
it doesn't get mistaken for an official palette color when picking one for
something new.

### Footnote markers

Footnotes use symbol markers — by default a currency-sign sequence, `£`, `¥`,
`₹`, `₽`, `₺`, `₴`, `₪`, `₫`, `₦`, `₡`, `₩`, `ƒ`, `¢`, `€` — rather than
numbers, restarting from the top of the sequence on every slide — unlike
plain LaTeX/beamer, where footnote numbering runs cumulatively across the
whole deck by default. `\source{}` counts as a footnote for this purpose but
never shows a marker of its own, so it doesn't take a slot in the sequence
for that slide's real footnotes.

The markers are plain Unicode characters typeset in the slide's own text font
(Fira Sans), not LaTeX's `\fnsymbol` (which renders in math mode, and this
theme deliberately leaves math on LaTeX's Computer Modern default — see
`beamerfontthemegotham.sty`'s `no-math` option to fontspec — so `\fnsymbol`'s
markers would visibly mismatch the surrounding Fira Sans text, most obvious
as a marker that looks shifted out of alignment next to flush-left text like
a `\source{}` line with no marker of its own).

The sequence itself is a plain list, overridable with `\setfootnotesymbols{}`
(comma-separated, any length, any order):

```latex
\setfootnotesymbols{†,‡,§}     % from here to the end of the deck
```

Call it once per deck (e.g. right after `\input{Slidemaster_preamble_uni-graz}`) for a
project-wide style, or partway through to change the marker set from that
point on. If a slide has more footnotes than the list has entries, indexing
wraps back around to the start rather than erroring.
[slides/2rg-EN-Footnote-symbol-options-current.tex](example/slides/2rg-EN-Footnote-symbol-options-current.tex)
(in the manual's appendix; `ZZU` until v5.16.0)
is a reference sheet of candidate symbols — every character on it was checked
to actually exist in Fira Sans (many "obvious" choices, like card suits or
star dingbats, silently render as a blank box in this font and were left
off); it also shows each candidate at actual footnote size, since a symbol
that reads fine at slide-title size can turn into an illegible smudge at
3.2pt. When adding to that list, check new candidates the same way: drop them
into a throwaway frame, compile, and grep the log for "Missing character".
`verify_footnotesymbols.tex` is a compilable regression deck for the override
mechanism itself (default sequence, a custom short list with wrap-around, and
an arbitrary custom list).

### Source citations

For a "Source: ..."/"Image source: ..."/etc. citation line — common at the
bottom/edge of a converted PowerPoint slide, but not anchored to one specific
word the way a real footnote is — use `\source{citation}` inside a
`standardframe`:

```latex
\source{Source: Regulation (EU) 2019/2088, \href{https://...}{https://...}, in the version of 09.01.2024.}
```

This renders exactly like the slide's other footnotes (same font, spacing,
right-alignment, and the same stretch-to-sit-just-above-the-footer behaviour),
but with no marker — neither inline in the body text nor next to the note
itself. Unlike a real footnote, no label is added automatically — write
"Source:"/"Image source:"/whatever fits as part of the argument yourself, since
it varies. When converting a PowerPoint slide, any bottom/edge source or
citation text should use `\source{}` rather than plain body text.

### Side footnotes

Calling `\sidefootnotes` *before* a `standardframe` (same pattern as
`\chapterlogo{}`) moves that one frame's footnotes — including `\source{}`
lines, which are footnotes underneath — from their usual spot above the
footer to a vertical strip along the right edge of the page, rotated 90°
counter-clockwise: the text starts just above the footer's yellow box and
reads bottom-to-top (left-aligned in the rotated frame, so short footnotes
sit at the bottom of the strip rather than hanging from the title bar), and
the usual bottom footnote area stays empty for content.

```latex
\sidefootnotes
\begin{standardframe}{Title}
	Some claim\footnote{Now typeset along the right page edge.}
	\source{Source: also ends up in the rotated strip.}
\end{standardframe}
```

The switch resets automatically on `\end{standardframe}`, so it opts in only
the frame that follows, and any frame type derived from `standardframe`
inherits it. Two things to know: the strip is drawn as an overlay in the
page margin, so unlike bottom footnotes it doesn't reserve body space — a
frame with very many side footnotes can see the strip encroach on the body
text's right margin; and a footnote with an overlay spec (`\footnote<2->{}`)
shows on *every* overlay slide of its frame in side mode. Like the title-bar
patches, the strip is positioned via a remembered tikz coordinate, so it too
needs the usual second compile pass. The strip's geometry (its vertical run,
top gap, and inset from the page edge) is set by
`\SMSideFootnoteHsize`/`\SMSideFootnoteTopSep`/`\SMSideFootnoteRightInset`
in `Slidemaster_preamble_base.tex`; the first is calibrated against the measured
title-bar position and needs re-measuring if the title bar ever changes.

`verify_sidefootnotes.tex` is a compilable demo/regression deck for this:
one frame with normal bottom footnotes, one with side footnotes, one
checking the switch resets.

## Student-version decks (the older two-way mechanism)

> **Which mechanism to use.** This section describes the original
> two-way instructor/handout split. Both real course decks
> (`t-Uni-FM2-2027s.tex`, `t-Uni-IA2-2026w.tex`) instead use the newer
> **three-way deck version system** — `\deckversion[...]` plus
> `\conditionalslide{}`/`\conditionalpause`/`\deckreveal{}` — described
> under "Deck version system" at the end of this file and in
> [SlidemasterManual.md](docs/SlidemasterManual.md). Reach for that one when
> setting up a new course deck. What's below is still live (the demo
> decks `test.tex`/`test-student.tex` that showed it in `example/` were
> retired in v5.16.0). The two do not interoperate:
> `\omitslide{}` is gated on `\ifSMStudentVersion`, which only
> `\studentversion` ever sets, so an `\omitslide{}` in a deck that uses
> `\deckversion[...]` silently does nothing at all — include such a slide
> with `\conditionalslide[versions]{}` instead.

For a course where some prepared slides (answer keys, solutions, internal
notes, ...) should stay out of the version handed to students: `\omitslide{}`
and `\omitslideversion{}` are drop-in replacements for
`\slide{}`/`\slideversion{}` that tag a slide as excludable —

```latex
\omitslide{xyz-Answer-key}                  % instead of \slide{...}
\omitslideversion{xyz-Answer-key}{1-0-0}    % instead of \slideversion{...}{...}
```

— and `\studentversion`, called anywhere in a deck (e.g. right after
`\input{Slidemaster_preamble_uni-graz}`), switches that one compile into the "handout"
variant: every tagged slide is skipped entirely (not blanked out or hidden,
but never `\input` at all, so it produces no frame and no blank page), *and*
it forces beamer's own `handout` mode (normally only reachable via the
`\documentclass[handout]{beamer}` class option, too early for a command
called later from a deck's own preamble to use directly -- `\studentversion`
instead late-redefines the same internal switch, `\beamer@currentmode`,
which beamer's overlay decoder reads at frame-processing time, not just once
at class-loading time, so this is safe rather than order-dependent luck).
That collapses every `\pause`/overlay-spec'd frame to a single page showing
the fully revealed state -- verified directly (isolated tests plus this
project's own `standardframe`/footnote machinery combined with `\pause`),
not assumed: no slide converted so far actually uses `\pause`, so until this
was checked, "the student deck has no reveal steps" was true only by
coincidence, not because anything enforced it.
The printed slide *number* still advances for it, though, so numbering stays
in sync between the two decks -- if instructor slide 12 is omitted, the
student deck jumps straight from 11 to 13 rather than renumbering everything
after it down by one. That way "see slide 12" points at the same physical
slide for both audiences, whichever deck someone has open. Without
`\studentversion` (the normal/instructor compile), a tagged slide loads
exactly like any other, with one difference: its footer's slide ID carries an
extra marker, e.g. `(slide id: q4m | omitted from student deck)`, as a
visible reminder while reviewing the instructor deck of what won't reach
students.

The tag lives at the call site in the *deck* file, not inside the slide's own
`slides/ID-slug-current.tex` — so the same slide can be tagged in one deck
and included normally in another, and, more usefully, the exact same slide
*list* can drive both variants of one course. Factor the `\slide{}`/
`\omitslide{}` calls into their own file and `\input` it from two thin
wrapper decks — one plain, one calling `\studentversion` first — so the two
variants can never drift apart on which slides they contain:

```latex
% course-content.tex -- shared by both decks below
\slide{k7f-EN-Standard-content}
\omitslide{xyz-Answer-key}
```

```latex
% course.tex (instructor)          % course-student.tex (handout)
\input{Slidemaster_preamble_uni-graz}          \input{Slidemaster_preamble_uni-graz}
...                                \studentversion
                                    ...
\begin{document}                   \begin{document}
  \input{course-content}             \input{course-content}
\end{document}                     \end{document}
```

Until v5.16.0 `example/`'s `test.tex`/`test-student.tex` (sharing
`test-slides.tex`) were a working example of exactly this pattern.

## Speaker notes

Plain beamer `\note{...}`, called anywhere inside a frame's body (or, for
`\titleframe`/`\quoteframe` — single commands with no body for it to sit
inside — right after the command itself; verified this still attaches to
the right frame, not assumed):

```latex
\begin{standardframe}{Title}
	...
	\note{Remind them the deadline moved to Friday.}
\end{standardframe}
```

Invisible by default in *every* compile, instructor or student — no deck's
own `.tex` sets `\setbeameroption{show notes}`/`{show notes on second
screen=...}` itself, so `\note{}` content sits harmlessly in the source
until a compile explicitly turns one of those on (see "Presenting live"
below for the one way that happens: SlideMage's own "Presenter"
entry, never a deck file's own hardcoded setting). That also means it
doesn't need any special handling to keep it out of the student deck — it's
already out of *every* deck by default; only that one specific, separate
compile output ever shows it.

When converting a PPTX slide with real speaker-note content (check
`ppt/notesSlides/notesSlideN.xml`, resolved per slide via that slide's own
`_rels/slideN.xml.rels`, *not* assumed to be `notesSlideN` for `slideN`),
carry it over via `\note{}` — but only the actual content, not PowerPoint's
own auto-generated page-number/date placeholder text every notes page gets
by default (skip slides where the notes are *only* that).

## Presenting live (dual-screen presenter mode)

For actually giving a lecture — projector on one screen, your own notes on
another — choose **Presenter** in the arrow menu of **Compile PDF** (any
deck, independent of the view chosen at the top) and compile. It produces
a separate `<deck>-instructor-presenter.pdf` in `pdf/` alongside whatever
else you compiled in the same run; the plain Instructor PDF, if you also
compile it, is completely unaffected.

This turns on beamer's own built-in `\setbeameroption{show notes on second
screen=right}` — every real slide becomes one wide page, the slide itself
on the left and a notes panel on the right holding that slide's own
`\note{}` text (blank if it has none — see "Speaker notes" above), plus a
compact one-line breadcrumb above it (current section/subsection/frame
title, whichever apply) if this deck uses `\section{}`. The note-page
template is customized (`Slidemaster_preamble_base.tex`'s own
`\SMPresenterModeOverride` block) to drop beamer's own default
thumbnail-of-the-current-slide and printed compile-date from that
panel — redundant since presenter software already shows the current
slide on its own — leaving the panel almost entirely for note text.
Always instructor-version content, regardless of the view chosen at the top
or other versions compiled in the same run: full `\pause` reveals
and every authored note only make sense against the instructor's own
content, so there's no During-course/After-course Presenter variant to
choose.

A genuinely very long `\note{}` can still run past the bottom of its own
panel and get silently cut off (LaTeX doesn't reflow a note page onto a
second physical page) — if you're writing a long one, compile and check
its actual notes page rather than assuming it fits.

**You need presenter software that knows this layout to actually use it
live** — opening the PDF in a plain viewer just shows the wide combined
page on both screens, which defeats the point. This project's own
recommendation is **[pympress](https://github.com/Cimbali/pympress)** (free,
open source, actively maintained, native Windows support): point it at the
presenter PDF, tell it which physical screen is the projector, and it shows
the plain slide there while your own screen gets the current slide, the
next slide, your notes, and a timer. **pdfpc** is the other name worth
knowing (same idea, well-regarded), but it's Linux/GTK-first and
noticeably less smooth to get running on Windows.

Not every slide needs a note — beamer's own layout handles a slide with no
`\note{}` call fine (an empty panel, nothing breaks), so write one only
where you actually want a reminder.

## Non-linear navigation and the generated appendix

**Every real slide is a jump target.** `\setSlideID` — the single choke
point every `\slide{}`/`\slidefinal{}`/`\slideversion{}`/`\omitslide{}`/
`\omitslideversion{}`/`\conditionalslide{}` call already passes through,
regardless of frame type — plants a `\hypertarget{<bare id>}{}` there, so
any slide can be linked to by its own three-character id with no per-slide
authoring. Use this directly for an excursus/"jump to details and back"
pattern:

```latex
% On the origin slide:
\hyperlink{nai}{\beamergotobutton{Details}}

% On the excursus slide itself (slides/nai-...-current.tex):
\hyperlink{2fw}{\beamerreturnbutton{Back}}
```

**Link text in running text**: `\SMLink{<slide id>}{text}` (since v5.27.0) is a
`\hyperlink` whose text is underlined like an `\href`, so readers can see it is a
link; a bare `\hyperlink` has no underline (it is meant for buttons). One line only,
so keep the link text short.

There's no "back" stack — a slide reachable from multiple places needs its
own judgment call (or multiple return buttons) about where "back" means.
If the exact same slide id is genuinely `\slide{}`'d twice in one deck
(e.g. a recap via `\slidefinal{}`), hyperref just warns "multiply defined"
and a link lands on whichever occurrence is *last* in the document —
inherent to any permanent-id-based target scheme, not something to design
around.

**"Generate appendix TOC"** (SlideMage's Build options, next to
"Include footer timestamp") adds a clickable appendix to every whole-deck
compile — Presenter, Instructor, During-course and After-course (since
v5.5.0; before, the Instructor/version-less and Presenter compiles only) —
but not to a per-chapter compile, whose PDF holds one chapter only. Each
version's appendix lists the slides that version shows
(`\conditionalslide`/`\slidestep` conditions). The PDF keeps the name it has
without the appendix (the `-appendix` ending of earlier versions is gone: a
compile with the checkbox on replaces the one without). It comes after the
deck's last slide, so after the deck's own
appendix slides (a `\section{Appendix}`, say). It is an agenda slide —
one entry per chapter plus a leading "Front matter" entry for whatever
comes before the first `\section{}` — followed by a 4×5 thumbnail grid per
chapter (paginated "(2/3)"-style once a chapter exceeds 20 slides), using
the same cached preview PNGs the slide list's thumbnails already
rely on. Clicking a chapter on the agenda jumps to that chapter's own grid;
clicking a thumbnail jumps straight to the real slide. The institute logo
on every slide becomes an invisible link back to the appendix agenda, but
only on a compile that actually generated one.

**Visible navigation for readers** (since v5.12.0, opt-in per deck; written
for the SlideMage manual, whose readers can't know that the logo is a
link):

- **`\SMNavigationBar[Contents,Chapter contents,Slide previews]`** in the
  deck preamble turns the footer's left text into
  "`\FooterText` | Navigation: Contents · Chapter contents · Slide previews"
  -- three underlined links to the deck's contents slide, the current
  chapter's agenda and the generated appendix agenda (the labels are the
  optional argument, e.g. `\SMNavigationBar[Kapitel,Kapitelinhalt,Folienvorschau]`;
  the word before them is `\SMNavigationLead`). A link whose target isn't in
  the PDF is left out rather than dead: "Slide previews" exists only on a
  compile with the generated appendix; "Chapter contents" falls back to the
  contents slide before the first `\section` and in a chapter without an
  agenda. Frames without a footer (`\titleframe`, `\fullbleedframe`) have no
  bar; every other deck's footer is unchanged.
- **`\SMDeckAgenda`** marks the contents slide (put it next to its
  `\tableofcontents`) as the target of the first link.
- **`\SMChapterAgenda[width]`** (in a chapter's `sectionframe` body) lists
  the slides of the current `\section` in two columns, each entry a link to
  that slide -- its frame title, or the slug for a title-less frame unless
  the slide file sets `\SMAgendaTitle{text}` before its frame. Built from the
  `.aux` like a table of contents (latexmk's rerun fills it in), in
  `\normalsize`, else `\small`, else `\footnotesize`, the first that fits (`\SMChapterAgendaMaxHeight`,
  default: the room below a `sectionframe` title bar). A `\slidestep` slide
  is listed once; the agenda's own slide is not listed. `[width]` leaves
  room for a `\sectionfigure`. In the transcript it becomes the list of the
  chapter's slides with their numbers.
- **`\SMSubsectionAgenda[width]`** (since v5.36.0) is the same for a chapter
  that is divided into `\subsection`s: it lists their titles instead of every
  slide, each entry a link to the first slide of its subsection (in this deck
  version; a subsection with no slide there is left out, and so are slides
  before the chapter's first `\subsection`). Same columns, font steps and
  `[width]`, and the same "Chapter contents" target. Put it in the divider's
  body, after `\sectionfigure`, and give it the room the figure leaves:
  `\SMSubsectionAgenda[\dimexpr\linewidth-\SMSectionFigureWidth-12pt\relax]`.
  In the transcript: "This chapter's sections:" with the number of each
  subsection's first slide.
- **`\deckappendixtoc`** (deck preamble, inert for LaTeX like `\decktags`)
  makes SlideMage generate the appendix for that deck on every whole-deck
  compile, whatever the Build options checkbox says -- so the "Slide previews"
  link always has a target.

The grid's own size isn't a fixed cm value — it's computed in LaTeX from
this project's real per-institution length registers (paper size, logo
padding, title-bar/footer height), left-aligned to the text margin and
scaled up until either the row height or the logo's own right edge binds,
so it looks right under Graz/Innsbruck/MCI alike without separate tuning.

## Screen-reader accessibility

> **Image descriptions and per-deck accessible transcripts were built on
> 2026-08-14** — see "Describing images" and "Accessible transcripts" below
> for how to use them.

**Status: partial**, scoped to the student/handout deck (see "Student-version
decks" above for why that's the meaningful target: `\studentversion` now
actually forces beamer's `handout` mode, so that compile has no multi-page
`\pause` builds to worry about re-reading). The footer, and
`titleframe`'s/`quoteframe`'s decorative background boxes, are marked as PDF
`/Artifact`s — a screen reader skips them — and every frame type's
content-stream order was verified (not just assumed) to read top-to-bottom
sensibly. This is *not* a fully tagged, PDF/UA-conformant document: there's
no structure tree, so no true semantic headings and no *enforced* reading
order — it relies on plain content-stream order, checked to already be
correct rather than fixed to be correct.

This is deliberately a low-level, package-free fix, not LaTeX's usual kernel
tagging (`\DocumentMetadata` + `tagpdf`): **beamer refuses to compile at all
under `\DocumentMetadata`** ("The beamer class is not compatible with
`\DocumentMetadata` ... switch to the new `ltx-talk` class if you require
tagged output" — beamer's own error message). `ltx-talk` is a from-scratch
class, not beamer-based, with no theme/template system — this framework
can't realistically migrate to it. Force-loading the underlying package
before `\documentclass` gets further (past hyperref) but then hits a genuine
internal error in `tagpdf`'s LuaTeX backend, from the non-standard load
order — not something to build real coursework on.

**LuaTeX-only**, same as the rest of this project (see "Compiling" above —
`lualatex` is the one supported engine). `\SMArtifactBegin`/
`\SMArtifactEnd` are `\ifluatex`-guarded and silently do nothing under
any other engine, a leftover safety net from when xelatex was still (nominally,
if not actually) supported: an unguarded first version hard-failed every
frame under xelatex with `! Undefined control sequence: \pdfextension`. Not
a real concern day-to-day now that xelatex isn't a target at all, but kept
rather than removed — cheap insurance against ever compiling this with the
wrong engine by accident.

What actually works: `/Artifact` is a standalone PDF
marked-content tag (PDF spec 14.8.2.2), valid in *any* PDF with or without a
structure tree — no `/Properties` resource entry or MCID needed.
`\SMArtifactBegin{dict}`/`\SMArtifactEnd` (in
`Slidemaster_preamble_base.tex`, "PDF accessibility" comment) wrap a region in
`/Artifact <<dict>> BDC ... EMC` via LuaTeX's raw
`\pdfextension literal direct{...}` primitive, e.g.
`\SMArtifactBegin{/Type /Pagination /Subtype /Footer}` for the footer,
`\SMArtifactBegin{/Type /Background}` for a plain decorative fill (the
PDF spec's own two different standard artifact types — not hardcoded to one,
since a background color fill isn't a "Pagination" artifact).

Per frame type:
- **`standardframe`** (and its thin wrappers **`figureframe`**,
  **`highlightframe`**): footer marked, content-stream order verified as
  title → body → footnotes → footer.
- **`sectionframe`**: same, via `standardframe` underneath — its taller/
  differently-positioned title bar doesn't change *when* the title text
  itself enters the stream, only how it's laid out.
- **`titleframe`**: no footer to mark (it's a `[plain]` frame, no footline at
  all) — its own decorative yellow background box is marked instead; title/
  subtitle text stays unmarked and reads in order.
- **`quoteframe`**: decorative yellow background box marked, plus the usual
  footer (this frame type keeps one); quote text and attribution stay
  unmarked, confirmed to read in the right order (quote, then attribution).
- **`fullbleedframe`**: its black letterboxing backdrop is marked; the image
  itself (the slide's entire real content) stays unmarked, same reasoning
  as an informative image anywhere else.
- **`sideimageframe`**: footer marked as usual, plus its own auto-placed
  "side filler image" — unlike `fullbleedframe`'s or `figureframe`'s
  images, which *are* each slide's real content and so stay deliberately
  unmarked, this one is explicitly decorative filler, marked unconditionally
  regardless of which image file the slide happens to use.

**Verification.** In the Slidemaster project, `decks/verify_accessibility.tex`
is a compilable regression deck exercising every frame type above, including
one real `sideimageframe` slide and one real `fullbleedframe` slide, on top of
that project's shared demo slide list `test-slides.tex` (`example/` had a copy
that never compiled there, removed 2026-10-05).
`.scripts/verify_accessibility_pikepdf.py` compiles that deck and
checks, directly against the compiled PDF's content streams via
[pikepdf](https://github.com/pikepdf/pikepdf): every `/Artifact` span is
balanced and contains only the kind of operator its own `/Type`/`/Subtype`
claims (no real text inside a `/Background` span, an image `Do` inside a
`/Pagination` one), plus the same text-matrix-Y-coordinate reading-order
check described above, reproduced programmatically rather than only by
one-off hand inspection:

```
latexmk -f -jobname=verify_accessibility -outdir=<absolute path to .build> decks/verify_accessibility.tex
python .scripts/verify_accessibility_pikepdf.py
```

Rerun both after any change to a frame type's own PDF-accessibility code.
`.scripts/check_color_contrast.py` is a separate audit: WCAG 2.1
contrast ratios for this project's actual color pairs (frame-title text on
the yellow title bar, footer text, hyperlink text, plus non-text UI
components like the bullet dot and hyperlink underline under WCAG 1.4.11).
Rerun after any palette change.

**Images** (since 2026-08-14): every image in the project has a row in
`media/alt-text.json` marking it `decorative` or `informative` (mirrored at
compile time into `media/alt-text.csv`, since that's what the LaTeX/Lua side
actually reads), and the `\includegraphics` wrapper in
`Slidemaster_preamble_base.tex` ("Alt-text manifest" comment) wraps every
decorative one in `/Artifact <</Type /Layout>>` so screen readers skip it
instead of announcing a bare filename. An **informative** image with a short
alt also gets that text typeset beside it in PDF text rendering mode 3 — invisible on the page,
but returned by text extraction, which is how an untagged PDF reaches a
screen reader at all. Verified by extraction (`pdftotext`, PyMuPDF) and by
rendering the page with and without it and confirming the two are
pixel-identical; **not** yet verified against a real screen reader, so treat
the companion transcript as the route that is known to work. Side effect,
accepted deliberately: the alt text appears in copy-paste and Ctrl-F.
The institute logo — which appears on every frame type via the shared
frametitle hook, and which this section previously left as an open question
— is covered by that: **decided decorative, marked, no alt text.**

Verified directly against each compiled PDF's content stream (via
[pikepdf](https://github.com/pikepdf/pikepdf), not just visual inspection):
artifact-marked regions checked to contain exactly the intended decorative
box-fill/text operators (and nothing else), and text-matrix Y-coordinates
checked to confirm reading order on every frame type above.

## Describing images

Everything about an image — role, short/long description, source
citation, a default takeaway — lives in one place, `media/alt-text.json`,
shared across every slide that uses it: an image only needs describing
(or crediting) once, however many slides show it. Never hand-edit it —
SlideMage writes it.

**Source** is independent of role: a decorative illustration still needs
attribution even though it carries no alt text (Midjourney-generated
images are a real example). It's a plain free-text citation field in the
Images page, automatically pulled into a compiled slide's own footnote —
every distinct source among a frame's images, de-duplicated, prefixed
"Image source(s):" — so a hand-authored `\source{}` is no longer needed
for image attribution specifically (it still is for anything else, e.g.
a data source for a table).

The same **Source (citation or attribution)** field (**Quelle** on the DE
side) is the **Reference / citation** box of the *Image descriptions* side
panel, so a citation can be written next to the slide without opening the
Images page. The box follows the language in the top bar (EN: Source, DE:
Quelle, which falls back to the English one when blank), and is saved with
the description, like every other field of the panel. Both views edit the
same store entry: what one saved shows in the other the next time it is
shown (opening the Images page saves the panel's pending edit first, and
going back to the workspace shows what the page saved).

**A citation has its own review state**, apart from the description's:
*To review* (amber) or *Reviewed* (green), shown next to the field in both
views, with a **Mark reviewed** button under it (enabled once the change
is saved). Any change to either language's source puts it back to *To review*
and clears its reviewed state: typing in either view, but also the assistant
or Claude Code editing `media/alt-text.json` (including a bundled manual
update that brings a different credit). It is one state for the English and
German citation together. Marking the description reviewed does not mark the
citation reviewed, and the other way round. A store from before this existed
loads with its citations as *Reviewed*, and an image without a citation has
nothing to review. A slide's review state and the Images page's "Needs
attention" list are about the descriptions only; the filter **Source to
review** lists the slides with a citation still to review.

Two things stay per-slide rather than shared, because they're genuinely
contextual:

- **Takeaway** — why *this* image is on *this* slide. An image has a default
  takeaway (set automatically the first time you write one for it); a slide
  can override it independently, or a "Set as default" button pushes its
  current text up to become the new default for every slide that hasn't
  written its own.
- **Reviewed** — confirming an image's description happens once; confirming
  that a given slide's *use* of it (its context, its takeaway) is right is a
  separate, per-slide check. A slide is only fully done when both are true.

(Before 2026-08-14 this was split across `media/alt-text.csv`, role/status
only, and a `%%ALT` comment block at the bottom of each slide file for
everything else — a CSV cell can't hold a 400-word description with an
embedded Markdown table. JSON has no such limit, so the split no longer
earns its complexity. `media/alt-text.csv` still exists, but only as a
generated compile-time projection — see "Repository layout" above.)

**The workflow**, all on SlideMage's **Images** page (**Image descriptions** in the ⋮ menu (Project)
and the palette; the list on its left is
slide-centric, filtered by state, and the top bar's **Close images** returns to the deck):

1. **Draft all…** runs a vision model (a local Ollama model, or a Claude model when the AI switch is
   on Cloud) over every image that
   still needs a description — once per image, not once per slide it appears
   on. It writes each one as it finishes and derives its queue from the
   store, so it is resumable — stop it, close the app, come back tomorrow.
   The list updates as it goes, so you can review the early ones while the
   rest run. It asks first, naming the model and, on Cloud, what is sent
   ("sends each image and its slide text to the cloud"); on Cloud the buttons that send
   content say "· cloud", and a note under each picker names the route's model. A batch
   keeps the route it started on even if you move the switch meanwhile ("Image 2 of 4 ·
   chart.png · Claude Code · Haiku · effort medium"). When it ends, is stopped or
   is cancelled by the switch, a results panel lists every image — drafted · needs
   review, "You edited it during the run · your text kept" (text you wrote or reviewed
   meanwhile is never overwritten), failed with the reason, or cancelled · not sent —
   with **Retry failed (n)**, which runs only the failed ones as a new batch on the
   current route. The assistant's *Describe images* and *Translate image descriptions*
   tasks end in the same panel.
2. **Review each one against the image**, which the page shows at full size.
   This is not optional; see the warnings below.
3. **Save and mark reviewed** stamps the slide — both the image's
   description and this slide's own use of it (its takeaway). Editing the
   slide's own `.tex` afterwards moves it to "needs re-check" rather than
   silently keeping the old description; editing the description *itself*
   and clicking plain **Save draft** un-reviews this slide's use of it
   immediately (2026-08-25; leaving the slide, the filter or the page saves a pending edit as
   such a draft) — a hand-edited description shouldn't keep
   showing as reviewed against text nobody has actually re-checked. On a
   slide with more than one image the button itself relabels to **Save and
   mark all images reviewed** (underlined in the app, 2026-09-15) — a
   direct-report fix for how easy it is to confirm just the one image you
   were looking at and not notice the button quietly marked every other
   image on the slide reviewed too; the emphasis only appears when there's
   more than one image to miss, so it doesn't become background noise on
   every slide.

**Two failure modes to know about before trusting a draft:**

- On **faint scanned multi-bar charts** the model fabricates plausible-looking
  values — measured on slide 4r7, it got 26 country names in the right order
  and then invented every number as an evenly-spaced ramp. A detector strips
  tables whose numbers rise in near-equal steps and leaves a warning in place,
  but treat any scanned figure as needing manual description.
- On a linear-axis chart the **flat early region** is where readings are worst.
  Look hardest there.

**Tune prompt…** re-drafts a single image with an editable prompt and a
per-image hint, iterating without writing anything until you accept. The hint
is the reliable lever (it persists, and future redrafts reuse it); editing the
system prompt tends to make the model abandon the required output format.

## Describing tikz illustrations

A hand-drawn `tikz` diagram (a timeline, a payoff chart, a flowchart —
anything drawn directly in a slide's own `.tex` rather than an
`\includegraphics`-ed file) joins the exact same workflow above. Wrap it in
`\tikzillustration{ID}` (`Slidemaster_preamble_base.tex`) instead of a bare
`tikzpicture`:

```latex
\begin{tikzillustration}{svp-Growth-Timeline}
	\draw[thick,->] (0,0) -- (4,0) node[right] {Time};
	...
\end{tikzillustration}
```

`ID` is a permanent, opaque, SlideMage-assigned identifier — the same
"never hand-invented" convention slide IDs themselves use — so the
illustration's own description survives edits to the drawing itself.

**Not every `tikzpicture` is a candidate.** Wrap a diagram that is real,
describable content — a timeline, a payoff chart, a flowchart, anything a
sighted reader learns something from. Leave a bare `tikzpicture` alone
when it's the `overlay`/absolute-page-position idiom (the footer/logo/
background pattern — wrapping one would try to typeset it in-flow instead,
breaking its own positioning), when it's nested inside *another*
tikzpicture's own node content (a `\scalebox{}{\begin{tikzpicture}...}`
used as one `\node`'s content), or when its only content is a single
`\node[SMImageBorder]{\includegraphics{...}}`/`\SMMugshot{}` call
— a decorative border around one real image, which already has its own
alt-text entry; wrapping the border too would just duplicate it.

It shows up on the Images page's per-slide list exactly like a real image (as
`tikz:ID`), with the same role choice, short/long/takeaway/source fields,
and **Draft…**/**Tune prompt…** buttons — none of that UI needed to change,
since the page already treats "which images does this slide reference" as
one flat list of opaque reference strings.

Two things work differently under the hood, both because there is no
file behind a tikz illustration for the rest of the system to read:

- **Role lookup, not a second place to author it.** Marking one
  **decorative** wraps its own drawing in the same `/Artifact` type
  `sideimageframe`'s filler image uses (see "Screen-reader accessibility"
  above), via the exact same `media/alt-text.csv` lookup
  `\includegraphics`'s own wrapper already makes — SlideMage writes this
  illustration's row keyed `tikz:ID` instead of a real path, nothing else
  about that mechanism needed to change. An **informative** one is left
  completely unmarked, same as real content in `figureframe`; unlike an
  informative *image*, it never gets the invisible-text alt layer (phase 5)
  — that layer's positioning math is built around `\includegraphics`'s own
  bounding box, which a freeform `tikzpicture` doesn't have. The per-deck
  accessible transcript is this illustration's own route to a screen reader
  instead.
- **Render, then draft.** A vision model needs pixels, not tikz source, to
  describe a diagram fairly. SlideMage compiles the illustration's own
  *current* body to a small standalone PDF, rasterizes it, and auto-crops
  it down to just the drawing (`tikz_render.py`) — cached by a hash of the
  tikz source itself, so re-opening or re-drafting an unchanged
  illustration is instant. This happens automatically the first time an
  illustration's preview is shown or it is queued for drafting; no separate
  "render" step to remember.

## Accessible transcripts

The transcript is the delivery route that is **known** to work — the
invisible-text layer above is likely but unverified against a real screen
reader. Generate a whole deck's transcript from the arrow menu of **Compile PDF** (**Accessible
transcript → Write transcript · During course** or **After course**; **Several decks…**
covers more than one deck) and
Markdown + HTML land in `transcripts/` (or the deck's own
`\deckoutputfolder[transcript]{...}`, see above).

- **Student versions only** (during-course, after-course). The instructor
  deck's multi-page `\pause` builds are a separate unsolved problem, and
  generating one would produce a transcript of a deck no student has.
- Deck versions resolve exactly as the PDF compile does (`\omitslide`,
  `\conditionalslide`, `\deckonly`/`\deckuncover`/`\deckvisible`), and slide
  numbering matches the PDF — so "slide 34" in the transcript is slide 34 in
  the deck.
- A German deck (`\decklanguage[de]`, see "Multi-language (EN/DE) slides"
  above) produces a transcript entirely in German — UI strings, image
  descriptions/takeaways (the German fields, falling back to English for
  any not yet translated), and the source citation (German if set,
  English otherwise) — driven by the deck's own fixed language, not a
  separate transcript-time choice.
- `\note{}` content never reaches it. Citations resolve against
  `Slidemaster.bib`.
- Colour is omitted: `\textcolor{...}{text}`, `\colorbox`, `\fcolorbox`,
  `\color{...}`, `\cellcolor`/`\rowcolor`/`\columncolor` keep only their
  text.
- Images with no description yet are flagged **in place** rather than silently
  omitted, so a half-described deck produces an honest transcript.
- A slide can also carry a free-text **summary**, independent of any image
  — shown at the top of that slide's transcript entry, before its own body.
  Set it in the **Transcript entry** panel ("Summary", its own **Save summary**
  button), not on the Images page: it needs to work for any
  slide, including ones with no images at all, which the Images page's own
  list never shows.
- **Previewing one slide's own entry** (no deck, no file written): the Images page's
  transcript button, or **Render → Render transcript** in the Preview, renders just the
  selected slide (from the text in the Source view) and opens it in a sheet of its
  own — nothing is saved to `transcripts/`, or anywhere else.

## Pre-render syntax check

Every path that starts a PDF render first runs a fast static check (`src/slidemage/latex_lint.py`,
GUI in `ui/workspace/render_check.py`) over exactly the LaTeX that render will read, and only asks
before rendering when it finds an **error**:

- **Render ▾ → Render the buffer** (Source view): the editor buffer (unsaved edits included).
- **Render** in the Preview: the saved slide file.
- **Compile PDF** (any view, all views, chapters, presenter, pages, several decks) and **Export PPTX**:
  the deck file (for a per-chapter job only its preamble and that chapter) plus the slide
  files its `\slide`-family calls load in that version -- a `\conditionalslide` or
  `\slidestep` left out of the version is not checked -- plus any `\input`ed deck fragment
  such as `test-slides.tex`.
- **Update slide previews:** every slide any deck uses.
- **Rerender all previews for this deck:** every slide of the current deck.

No findings: the render simply starts (one log line). Warnings only: listed in the log, the
render starts. Errors: a sheet lists them; **Cancel** (the default), **Show in editor**
(opens the file at that line) or **Render anyway**. The Source view runs the same check on
its text as you type (a status line, a red badge on **Source**, and **Ask AI to fix**, which
hands the findings to the chat). It is lexical -- no macro is expanded --
so it only reports things that are wrong whatever the project's own macros do. Cost: about
0.1 ms per slide file (a 395-slide deck: ~300 ms cold including reading the files, ~65 ms
when nothing changed); it was run over all ~930 slide/deck files and tuned until it was quiet
on everything that compiles.

| Check | Level | What it finds |
|---|---|---|
| `encoding` | error | control characters (e.g. a stray backspace/form feed) or invalid UTF-8 -- LuaTeX: "Text line contains an invalid character" |
| `braces` | error | an opening `{` never closed, a closing `}` with nothing to close (`\{`, `\}` and comments ignored) |
| `environments` | error | `\begin{x}` without `\end{x}`, `\end{x}` without `\begin{x}`, wrong nesting order |
| `math-dollar` | error | odd number of `$` (math left open), or `$...$` still open at a blank line |
| `math-delims` | error | unpaired `\[ \]` or `\( \)`, different number of `\left` and `\right` |
| `ampersand` | error | unescaped `&` in running text (allowed in tabular/array/align/matrix/tikz and in URLs) |
| `hash` | error | unescaped `#` outside macro definitions and URLs |
| `citation` | error | `\fullcite`/`\cite`/`\textcite`/`\parencite`/... with a key that is not in `Slidemaster.bib` |
| `image` | error | `\includegraphics`, `\chapterlogo`, `\fullbleedframe`, `sideimageframe`, `\cornerfigure`, `besidefigure`, `\fitfigure`, `\sectionfigure` pointing at a file that does not exist (extension optional) |
| `code-file` | error | `\SMCodeFile{path}` pointing at a file that does not exist (path relative to the project root) |
| `slide-file` | error | a deck call whose `slides/<id>-current.tex` / `-vX-Y-Z.tex` does not exist |
| `underscore` | warning | `_` in running text outside math, tikz and name/path arguments ("Missing $ inserted") |
| `caret` | warning | `^` in running text outside math (`10^6` typed without `$...$`) |
| `percent` | warning | `5% growth`: a `%` right after a digit followed by more text -- the rest of the line becomes a comment |
| `overlay` | warning | `\only<2-{...}` -- overlay specification without its closing `>` |
| `optional-arg` | warning | `\item[label` without `]` on that line |
| `heading-text` | warning | a content frame whose first line is a bare `\textbf{...}` directly above its list -- make it the list's first `\item` |
| `table-edges` | warning | `\begin{gothamtable}{...}` with neither `[gap=...]` nor `@{}` edges: the rules run past the text on both sides (write `\begin{gothamtable}[gap=12pt]{lcc}`) |

Inside `verbatim`/`lstlisting`, `\verb`, `\iffalse ... \fi`, `\ExplSyntaxOn`/`\makeatletter`
regions and macro-definition bodies the character checks are skipped. Not checked (needs a
real TeX run): undefined macros, wrong argument counts, missing packages, anything that
depends on macro expansion.

### Layout check after a compile

`tools/check_layout.py` measures a compiled PDF against the framework's margins
(since v5.14.1 in this repository; it lived in the Slidemaster project before):

```bash
python tools/check_layout.py [--project DIR] [--checks top,coltop,...] deck.pdf
```

Per page it reports content that misses the Top Margin (`top`), a text column
that starts below it beside a figure (`coltop`), content past the Left/Right
Margin or into the footer (`left`, `right`, `bottom`), table rules longer than
their text (`bleed`) and anything that moves between overlay steps (`jitter`).
A slide exempts itself from a check with a comment line in its own file,
`%% layout-check: skip top -- why` (several checks comma-separated, or `all`);
the exemptions are read from the slide files of the PDF's project (`--project`,
else the folder with `slide_ids.csv` above the PDF, else
`$SLIDEMASTER_PROJECT`). Exit code 1 if anything is reported. The Right Margin
is the logo's visible right edge, measured on the rendered page (since
v5.15.1); in every template it coincides with the framework's own Right Margin,
`\gothamFrametitleRightpading` from the page edge.

## Slide previews

Every compile that touches a slide — rendering it on its own, or compiling
a whole deck (instructor version) — refreshes a cached pair of PNGs of how
it last looked (full-size and thumbnail, see below), so you can glance at
a slide without paying a LaTeX compile to do it. Previews are specific to
the institution template that produced them: a Uni Graz deck and a Uni
Innsbruck deck compiling the same slide keep separate caches, and each
deck's workspace always shows its own template's previews. Two ways to
see them, both reading the same cache:

- The **slide list** shows a thumbnail on every row; a row says "preview old" when the
  slide's source is newer than its preview.
- The **Preview** view (and the right half of **Split**) shows the cached page at once,
  with chips for what it is not showing (a pinned version, another language, a missing
  translation, a view that does not typeset the slide) and a **Render** button that makes
  a fresh one in the View as / language chosen at the top. (The cache holds the instructor
  view only; the other views render on demand.)

The old deck editor's hover tooltip, Thumbnail and Grid views, and chapter dropdown are
gone: the slide list's sections and its **Find slide** field replace the dropdown.

This is a best-effort cache, not a guaranteed-fresh one — it only updates
when something actually compiles that slide, so it can lag behind an
unsaved (or even a saved but never recompiled) edit. **Render ▾ → Render the buffer**
always compiles your current text directly and is unaffected by any of this.

To refresh every slide's preview in one pass (e.g. after a preamble/theme
change), choose **Update slide previews** (⋮ → *Housekeeping…*) and confirm — no
institution to pick any more: it scans every deck (active and archived)
for which slides it actually uses under which template, compiles one
throwaway deck per template containing exactly that template's own
needed slides, and deletes any cached preview no deck uses any more
(e.g. a slide removed from every deck, or moved to a different
institution). This is one long compile (well over an hour is plausible
for the whole project) that occupies the compile slot until it finishes,
so no other compile can start in the meantime.

To refresh only the current deck's previews, choose **⋮ → This deck → Rerender all
previews for this deck** (also in ⌘K / Ctrl+K). It asks first, then runs the same
compile for just this deck's slides (both languages) with the same job panel and Log; it
deletes nothing, and the cached previews of other decks are left as they are. It is
distinct from **Render** in the Preview (one slide) and from **Update slide previews**
(every deck, with the clean-up). The agent has the same two jobs as tools:
`refresh_preview` (one slide, default the focused one) and `refresh_deck_previews` (one
deck, default the open one), which report what was refreshed and what failed.

## Deck version system

This project supports three deck versions for each course:

- **instructor** — all slides and all reveal steps (for the instructor)
- **during-course** — restricted content (given to students at start of term)
- **after-course** — intermediate content (given to students at end of term)

See `SlidemasterManual.md` for details on how to use the deck version system,
including how to mark slides/steps for specific versions and how to compile
each variant.

### `\slidestep` — one slide, several places, different reveal steps

`\slidestep{ID-slug}[versions]{steps}` is `\conditionalslide{}` plus a restriction of
which reveal (overlay) steps are typeset. The slide file is written once, with plain
overlay specifications (`\textcolor<2>{...}{...}`, `\only<3>{...}`, `\pause`), and the
deck decides where it appears and which steps show, per deck version:

```latex
\slidestep{egk-EN-Structure-of-a-Scientific-Paper-Overview}[instructor]{1,2}
\slidestep{egk-EN-Structure-of-a-Scientific-Paper-Overview}[during-course,after-course]{1}
...
\slidestep{egk-EN-Structure-of-a-Scientific-Paper-Overview}[instructor]{3}
\slidestep{egk-EN-Structure-of-a-Scientific-Paper-Overview}[during-course,after-course]{1}
```

- `steps` is a beamer overlay specification without the angle brackets (`1,2`, `3`,
  `2-`, `1-2,4`); it becomes the frame-level `\begin{frame}<steps>`, so only those
  overlay pages reach the PDF. `[versions]` defaults to all three. A presenter compile
  runs as version `instructor`.
- A call whose version list does not contain the current deck version does nothing,
  **not even a frame-counter step** (unlike `\conditionalslide`): two calls at one
  position are alternatives, so every version has exactly one frame there and the
  slide numbers after it agree across versions.
- The first `\slidestep` of an id defines its `\hypertarget` (`\hyperlink{egk}{...}`
  lands there); later ones do not, so there is no "multiply defined" warning.
- SlideMage: the slide list shows the calls (with their versions and steps as a chip),
  `Included in decks` headers count them, a transcript numbers them like
  `\conditionalslide`, the appendix TOC shows the slide once, and slide rename follows the
  id. Since 2026-09-26 the way a slide is called (a row's **Call as** menu and the **Add
  slide** sheet) offers `\slidestep`, with the version choice and a "steps" field
  (`1,2`, `2-`, `1-2,4`) next to it.

### List labels: where they start

A list label starts at the left edge of the bullet dot of its own level (12.76pt for level 1, then +8.84pt per
level), the way the source PowerPoint places it: enumerate numerals (level 1 additionally puts the item text at
27.9pt, nested bullets unchanged; `\SMEnumerateTextExtra`), ellipsis labels via `\item[\SMBulletEllipsis]`,
and a bullet template that is itself an ellipsis via `\setbeamertemplate{itemize subitem}{\SMBulletEllipsisScript}`.
Hand-tuned label environments (`gothamnum*`/`gothamalpha*` itemize, `\SMTocLabelFlushLeft`, ...) keep their own
measured geometry. `python .scripts/check_list_labels.py <compiled.pdf>` measures every label of a compiled deck
against this rule and lists the exceptions.

### `\SMFinalStateForStudents` — student decks show only the final state

Put `\SMFinalStateForStudents` in a slide file, right before its frame environment (after
`\setSlideVersion`): the instructor and presenter compiles are unchanged, every other deck version then
typesets only the frame's **last overlay page** -- the state that is left after all reveal steps, including
steps that hide things again. It needs no change to the slide body, so it covers `\pause`, `\only<n>`,
`\item<n->`, `\uncover`, `\textcolor<n>`, `\alt` alike, unlike `\conditionalpause`/`\deckrevealfinal`, which turn
one construct off. Mechanism: beamer's frame-level overlay restriction `\begin{frame}<N>` with N the frame's
overlay count; a student compile records N per frame in `<jobname>.ovl` (next to the `.aux`) and the next run
reads it, so the first run of a fresh job still shows all pages and latexmk's rerun restricts them.
A `\slidestep` call keeps priority over the flag. Finding candidates: compile the deck in a student version and
list slides with consecutive pages of the same id (`decks/zz-student.tex` = `\def\deckversionoverride{after-course}`
+ `\input` of the deck was used for that).

### Interactive preview builds

Single-slide previews retain a separate latexmk dependency graph and auxiliary
files under `.build/preview-cache/`, so subsequent edits can reuse resolved
references and bibliography work. Concurrent requests for the same slide and
preamble are serialized; each caller gets its own temporary PDF. Failed edits
never return a previously successful PDF. “Remove temp files” clears these
builds and their `_slidemage_preview-*` wrappers.

The Source view's **Render** menu also offers **Selection as frame** (a complete
frame, or self-contained text wrapped in a frame) and **Selection as element**
(a cropped formula, graphic or text fragment using `preview.sty`). Select the
source before rendering. An overlay value of zero renders all overlays; a
positive value requests that overlay of each frame. Element and partial-frame
previews do not replace the full-slide snapshot.

For a saved source with automatic rebuilds:

```sh
SLIDEMASTER_PROJECT=/path/to/project python -m slidemage.preview_cli \
  /path/to/project/slides/abc-EN-Example-current.tex \
  --deck my-deck --watch --open
```

Use `--lines 12:30 --mode region` for a source region, `--mode element` for a
self-contained fragment, `--overlay 2` for one reveal state, or `--no-cache` to
use fresh build files. Watch mode follows the source, owning deck, project latexmk configuration and recorded
inputs such as included preambles, graphics and bibliography files. Use `--profile`
to print build-stage and TeX/bibliography-pass timings as JSON.
See `tools/preview_benchmark/README.md` for the reproducible manual benchmark.

The BIG CHANGE 2 comparison (2026-10-11) measured all 81 calls in the current manual with real visible edits and unchanged requests.
Unchanged previews improve from a median of 0.234 s to 0.138 s; interleaved controls
show essentially unchanged real-edit speed. The report retains the full-run timing variation
and the compatible combinations. Reusable builds plus
in-memory source rendering are the default editor path; choose an overlay when
only one reveal state is needed. The `.fmt` preamble-cache probes failed with
the tested LuaLaTeX installation, so no `.fmt` cache is enabled.

BIG CHANGE 2 queues the latest render while one is running and debounces automatic
renders after saving by 300 ms. Editor changes update an older-buffer notice after
typing pauses, without compiling on a keystroke. A superseded result cannot replace the page, open a
presenter PDF or publish a canonical snapshot. Image preparation is shared between
the display and snapshots, with a bounded cache keyed by PDF content. A reusable
child process rasterizes PDFs so MuPDF objects stay out of GUI/worker threads. Cached scratch
previews skip SyncTeX output. Cleanup and build reservations share locks that also protect previews
in other processes. Timestamp changes mark older accepted images stale, and disk thumbnails
request verification by rendering. Actual pane destruction discards late results safely. A stalled
raster helper is killed after 15 seconds and restarted by the next request.
The v6.1.1 review fixes passed 1,491 tests and the four-slide subset benchmark
completed 80 requests in 7 minutes 54 seconds without failures or PDF mismatches.
Saved unchanged median improved from 0.235 s to 0.138 s; visible-edit speed was
essentially unchanged.
