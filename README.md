# SlideMaster

LaTeX/beamer setup for research and teaching slides, built on the
[Gotham beamer theme](https://github.com/) with a Uni Graz color/logo
customization, plus SlideMage, a PySide6 GUI for compiling decks and
managing slide IDs, image descriptions, and accessible transcripts.

> **This is a trimmed copy** of a larger private project, prepared to share
> the framework itself: the Gotham theme, the Uni Graz institution layer,
> SlideMage, and one small demo deck (`decks/test.tex`/`test-student.tex`,
> `slides/ZZ*`) in place of hundreds of real course slides. Read
> [PROJECT_OVERVIEW.md](docs/PROJECT_OVERVIEW.md) first -- it covers the core
> concepts (slide IDs, deck versions, accessibility, Ollama) at a higher
> level than this file, plus what to install before compiling anything.
> This file (README.md) is the same detailed reference the original
> project uses day to day; a few passages illustrate a point with a file
> that isn't part of this copy (another institution's preamble, a real
> course deck, a working-log file like `CONVERSION_NOTES.md`) -- the
> mechanism being explained still applies regardless.

## Repository layout

| Path | Contents |
| --- | --- |
| `latex/` | The framework: Gotham beamer theme (`beamer*themegotham.sty`, `gotham.dtx`), `Slidemaster_preamble_base.tex`, `Slidemaster_alt.lua`. Institution-independent. |
| `example/` | A complete Slidemaster project: `slides/`, `decks/`, `media/`, the Uni Graz layer (`Slidemaster_preamble_uni-graz.tex`, `schemes/`), `Slidemaster.bib`, `.latexmkrc`, and `slide_ids.csv`, which marks a project's root. |
| `src/slidemage/` | SlideMage, the PySide6 app (formerly its own repo, merged with its history). |
| `docs/` | Project overview, deck-version manual, SlideMage internals. |
| `tests/` | Smoke tests, run in CI together with a compile of the demo decks. |

**Paths in the rest of this file (`decks/…`, `slides/…`, `media/…`,
`.latexmkrc`) are relative to the project folder** — `example/` in this
repo.

## Quick start

```bash
python3 -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
slidemage --project example          # the GUI
cd example/decks && latexmk test.tex # or compile directly
```

For your own project, copy `example/` anywhere; if it doesn't sit next to
`latex/`, point `SLIDEMASTER_LATEX` at this repo's `latex/` folder. See
[docs/PROJECT_OVERVIEW.md](docs/PROJECT_OVERVIEW.md) for prerequisites
(LuaLaTeX, biber, optional Ollama).

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
  this file, swap the `c_*` colors and `\gothamInstituteLogoPath`, keep
  the trailing `\input{Slidemaster_preamble_base}` line.
- `slides/` — one set of files per slide, named by a permanent, opaque ID
  (see below). This is where actual slide content lives.
- `media/` — images referenced from `slides/` (charts, chapter logos,
  Midjourney illustrations, etc.), named `<type>-<slug>[-cropped].<ext>` so
  the kind of image is obvious from the filename alone — `chapter-logo-...`,
  `midjourney-...`, `chart-...`, `photo-...`, `screenshot-...`.
- `media/alt-text.json` — the store for everything about every image in the
  project: role (`decorative`/`informative`), confirmation status, short/long
  description, a default takeaway, and per-slide state (which slides use it,
  each with its own takeaway override and reviewed stamp). Edited through
  SlideMage's "Images" tab. See "Screen-reader accessibility" below.
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
  a side effect of any compile that touches that slide, or in bulk via
  SlideMage's "Update previews" button. A best-effort cache for
  SlideMage's own Preview button/hover tooltip/thumbnail grid, not a
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
- `src/slidemage/` — SlideMage, a PySide6 (Qt) GUI for compiling decks (any
  combination of instructor/during-course/after-course, whole deck or one
  PDF per chapter), for archiving a finished deck's `.tex` file into
  `decks/archive/` while keeping it compilable, and for describing images
  and generating accessible transcripts. Install with `pip install -e .`,
  start with `slidemage`; see [docs/SlideMage.md](docs/SlideMage.md) for
  how it works and [docs/PYSIDE6_MIGRATION.md](docs/PYSIDE6_MIGRATION.md)
  for why it is no longer Tkinter.
- `decks/test.tex`/`decks/test-student.tex` — a minimal example deck; also
  a working demo of every layout/frame type, not a real course. This copy's
  one demo deck — see "Getting started" in
  [PROJECT_OVERVIEW.md](docs/PROJECT_OVERVIEW.md).

A deck for a specific course or talk is a `.tex` file in `decks/`, e.g.:

```latex
\documentclass[aspectratio=169]{beamer}
\usetheme{gotham}
\input{Slidemaster_preamble_uni-graz}
\newcommand{\FooterText}{KS Financial Markets | Stefan Palan | 2027s}

\begin{document}
	\slide{ZZZ-Standard-content}
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
`decks/test.tex` has this already; copy it into any new deck under `decks/`.

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

`slidemage` compiles any deck via `latexmk` directly, through a GUI table
of checkboxes rather than a hand-edited `DECKS=` line -- see
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
ground with a GUI on top, and neither is needed alongside it.

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

Each active deck's row in SlideMage has an **Export PPTX** button:
compiles the deck (instructor version) and writes a real `.pptx` next to
its PDF in `pdf/`. Every beamer overlay/reveal step belonging to one
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

SlideMage's deck tables group decks under separators -- the workdeck on top,
then "Course decks", "Research presentations" and "Test decks" -- and click
a heading to collapse or expand that group. Which group a deck is in is
decided by its own tag, never by its filename:

```latex
\decktags{test}
```

placed just before `\begin{document}` (after the preamble `\input{}`, which
defines it as an inert no-op like `\deckoutputfolder`). The group tags are
`work`, `course`, `research` and `test`; a deck with none of them is a
course deck, and if it carries several the first in that order wins. Other
tags are allowed and ignored for now. Set it from SlideMage rather than by
hand: the **Tags** button on a deck row, or the group choice in the
**Duplicate** dialog when creating a copy.

### Decks with a bibliography (`\fullcite{}`/`Slidemaster.bib`)

biblatex+biber is opt-in per deck (not loaded globally), for any deck that
`\usepackage{biblatex}`s and `\addbibresource{Slidemaster.bib}`s itself.
`decks/test.tex` is this copy's own live example -- plain biblatex
defaults (no custom citation-format drivers, unlike a real course deck's
own house style), just enough to resolve
`slides/ZZZ-EN-Standard-content-current.tex`'s one
`\fullcite{markowitz1952}` footnote against this copy's trimmed
`Slidemaster.bib` (a single entry -- see that file's own header comment).
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

Every top-level compilable file (`decks/test.tex`, `decks/test-student.tex`,
`decks/test-mci.tex`, `decks/test-ibk.tex`, `decks/t-Uni-FM2-2027s.tex`,
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

Every slide has a permanent, opaque **ID** (3 characters, e.g. `ZZZ`, minted
by `slide.new.id()` — see below). The ID never changes, even if the slide's
description or content changes, so it's safe to reference in your own notes
("see slide `xyz`") or to cite across decks. IDs deliberately avoid
confusable characters (no `l`/`1`, `o`/`0`, etc.).

By convention, **testing/demo slides use uppercase IDs** (e.g. `ZZZ`, `ZZY`
— pass `use_uppercase = TRUE, use_lowercase = FALSE` to `slide.new()`/
`slide.new.id()`), while **real slides use lowercase IDs** (the default).
This makes it obvious at a glance, from the filename alone, whether a slide
is throwaway test content or actual course/research material.

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
another deck follows whatever is current. SlideMage's own Save button
does this freeze-then-bump step automatically (see "Creating and revising a
slide" below) -- R's `slide.archive()` is still there for anyone editing
outside SlideMage.

The tracked version, when there is one, shows in the compiled footer next to
the slide id -- `(slide id: xyz | v1.2.0 | instructor deck)` -- for both a
bare `\slide{}` (whatever `current.tex` is currently tracked as) and a
pinned `\slideversion{ID-slug}{X-Y-Z}` (always that call's own `X-Y-Z`,
regardless of what `current.tex` has moved on to since). A slide with no
tracked version yet just omits that segment.

In your deck file:

```latex
\slide{ZZZ-Standard-content}              % loads current.tex, i.e. the live content
\slideversion{ZZZ-Standard-content}{1-0-0} % loads a specific frozen version instead
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
included in (e.g. `%% Included in decks: t-Uni-FM2-2027s, test-slides`). This is
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
dialog with a real bump choice has no tracked version at all -- its footer
shows no `v...` segment, and its first bump treats the untracked content as
if it were already `1.0.0` (so a first-ever Minor save freezes `v1-0-0` and
leaves `current.tex` at `1.1.0`). `current.tex` itself is never renamed --
only the frozen snapshot gets the `-v<version>.tex` suffix, exactly as in
the manual workflow.

## Multi-language (EN/DE) slides

Added 2026-08-24 — full design/implementation history in
[LANGUAGE_NOTES.md](LANGUAGE_NOTES.md); this section covers the
day-to-day workflow. Every slide's id-slug now carries a language
segment as its second hyphen-delimited part —
`slides/<id>-<LANG>-<slug>-current.tex`, `LANG` one of `EN`, `DE`, or
`mult` (multilingual, see below) — parsed at compile time by
`Slidemaster_preamble_base.tex`'s `\setSlideLanguageFromSlug` and shown
in the footer appended directly to the tracked version:
`v1.1.0` becomes `v1.1.0EN`/`v1.1.0DE` (only once a version is tracked at
all — an untracked slide's footer still shows no `v...` segment).

A deck's own language is fixed, set once near the top of the deck file
next to `\deckversion` (same `\ifdefined`-override pattern, for
SlideMage's own one-off render preview and ad-hoc testing):

```latex
\ifdefined\decklanguageoverride
	\decklanguage[\decklanguageoverride]
\else
	\decklanguage[en]           % options: en, de
\fi
```

### Creating a German translation of an existing slide

A German translation of a slide with real body text gets its **own,
new slide ID** — not a shared ID, not an inline conditional — since the
content genuinely differs and this project's whole versioning model
assumes one ID's `current.tex` is one evolving content stream. In
SlideMage's "Add slide" dialog (from a deck editor tab's `+ before`/
`+ after` buttons), choose **Create new slide**, set **Language: DE**,
tick **Base on existing slide** and pick the English original: this
seeds the new file from the English slide's own body (a starting point
to translate from, not a finished translation) and writes both
cross-reference header comments automatically —
`%% Translation of: <english id-slug>` on the new file, `%% DE
translation: <german id-slug>` back on the English one. Then just edit
the new slide's body directly, same as any other slide.

If a slide's language needs to change later (including migrating an
older, not-yet-tagged slide), open it in the slide-source editor and use
its **Language:** control — this renames the file (and any frozen
versions) and rewrites every deck reference for you; it asks for
confirmation first, naming how many references will change. "Sync
translation links" (main toolbar) refreshes every `Translation
of:`/`... translation:` comment from current disk state — safe to run
any time, e.g. after a manual rename elsewhere.

### Light, bilingual slides (image-only/title-only)

A slide whose only per-language difference is a short title or caption
(a figure-only slide, say) doesn't need a second file: give it the
`mult` language segment and switch its text with
`\multilingualtext{English text}{German text}`, which reads whichever
language the *deck* is compiling as. Pick **Multilingual** in the Add
slide dialog's language radio to create one directly.

### Translating image descriptions/citations

The Images tab's per-image editor has a **German** section (short/long
description, source, takeaway) below the English one, with a **Translate
now** button that machine-translates the current English text via a
local Ollama model — review and edit before saving, same as any drafted
description. A German source citation is optional: leave it blank to
reuse the English one (most citations are proper nouns/publication names
that don't need translating), or fill it in only where it should read
differently.

The Images tab's toolbar also has a **Translation model:** picker (any
model installed in Ollama, not just vision-capable ones — translation is
text-only) and a **Translate all…** button that batch-translates every
image whose English text is new or has changed since its last German
translation, same resumable/no-persisted-job-state design as **Draft
all…**. As of 2026-08-25 every existing image has a German translation.

Exactly what gets sent to the model — the instruction text, and how many
blank lines separate it from the text to translate — is configurable per
model and per language pair from **System → Preferences… → Translation
prompts**, since different models expect different prompt shapes (a
dedicated MT model wants a short bare instruction; a general
instruction-tuned model tolerates a longer one). A model/pair with no
specific entry there falls back to that same dialog's single editable
**default prompt**. The same Preferences dialog also holds the dark-mode
toggle (moved off the main toolbar) and an **Ollama models** tab for
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
  any small inline `\frac` embedded mid-sentence. `\tallitem`'s own optional
  argument is the multiplier, not a pass-through to `\item`'s own custom
  label — a line that needs both an empty `\item[]` label *and* the extra
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
  `slides/ZZX-EN-Definition-formula-current.tex` (the demo slide showing
  all six side by side) are worked examples. All six span the full frame
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
  `-\gothamContentTopAlign+6.02pt` intrinsic gap correction on the anchor
  node (confirmed empirically, not derived — see
  `\gothamFloatingInfoblockRightAlign`'s own comment in
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

The `s-ZZ[ZYXW]-*-current.tex` files in `slides/` demonstrate all of the
above, one layout per slide (`ZZZ` standard content, `ZZY` two columns,
`ZZX` definition/example/caveat blocks, `ZZW` standout) — copy from
whichever's closest when starting a new slide.

`standardframe` content is top-aligned (not beamer's default vertical
centering) and its first itemize level sits flush with the frame title, with
each deeper level indented just enough for its dash to land under the text
of the level above. Pass `[c]` explicitly (`\begin{standardframe}[c]{Title}`)
if you want a particular slide vertically centered instead.

## Special frame types

Five more frame types, all converted from `ExampleSlides.pptx`. All five
deliberately reuse as much of `standardframe` — and of each other — as
possible: `sectionframe`,
`figureframe`, and `highlightframe` are literally thin wrappers around
`standardframe` itself (same title bar, logo, footer, bullet styling —
only what's documented below differs); `titleframe` and `quoteframe` can't
be `standardframe` wrappers (both are title-less, and `quoteframe` replaces
the whole body layout) but still reuse its palette, fonts, and margins.
`s-ZZS/ZZR/ZZQ/ZZP/ZZN-*-current.tex` in `slides/` are working demos of all
five, one each, in that order.

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

The box's height (`\gothamTitleframeBoxHeight`) is a fixed target for its
*bottom* edge, not for the blank space above the text — that space is
derived from it instead (box height minus the title+subtitle content's own
measured height), so the bottom edge stays put even if a longer title ever
wraps onto a second line; the blank space above just shrinks to compensate
(if a title were long enough to overflow the box entirely, the text would
start above the page's top edge — there's no fallback for that case, since
`titleframe` is normally used once with short, predictable copy). The text
itself doesn't sit flush with the box's bottom edge either — a further
length, `\gothamTitleframeBottomPad`, reserves about 1.5 line-heights of
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
`\gothamFrametitleFullHeightYellow` is `sectionframe`'s opt-out for that
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
(`\gothamSectionframeTitleBox`, built with the same font/approximate width
gotham gives it) rather than left at a fixed value:
`toppading = boxHeight - bottompading - measuredTitleHeight` (plus a small
empirically-measured correction — gotham's real leading strut doesn't
behave quite like a plain measured `\vbox`, see the comment above
`sectionframe`). A longer/wrapped title therefore shrinks toppading
automatically, pushing the whole title block up rather than changing the
gap below it.

**This toppading formula has a real, confirmed side effect: the bar's own
visible height depends on whether the title text has any descenders (`g j p
q y`), not just on `\gothamSectionframeBoxHeight` (2026-07-25, direct
instruction: "the image extends into the title box" on
[neb](example/slides/neb-Market-Environment-Section-Overview-current.tex)/
[u97](example/slides/u97-Household-Finance-Section-Overview-current.tex) — root-caused
after their own images, placed flush against `\gothamSectionframeBoxHeight`
directly, turned out to sit ~4.2pt too high; see those two files' own header
comments for the fix actually applied).** `\gothamSectionframeBoxHeight`
(85.04pt) is only the *target* this formula solves for — by construction,
`toppading + measuredTitleHeight + measuredTitleDepth + bottompading` should
algebraically equal `\gothamSectionframeBoxHeight + \gothamSectionframeHeightCorrection`
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
  `sectionframe`, `\gothamSectionframeBottomGap+\gothamSectionframeBottomPadCorrection`)
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
screen when `\gothamSectionframeHeightCorrection` was originally calibrated
(a descender'd one), not a design choice — but it means
**`\gothamSectionframeBoxHeight` was never actually a title-independent
constant**, and anything anchoring itself directly against it (as neb/u97's
own decorative-image overlay does, the `sideimageframe` technique from
"Side image" below applied to `sectionframe`'s own box) needs the bar's real,
per-title rendered height, not this target.
`\gothamSectionframeTrueBoxBottom` (`Slidemaster_preamble_base.tex`, right
after `\gothamSectionframeBoxHeight`'s own definition) is that measured
value — but it's **only valid for a title with no descenders**, matching the
two slides (neb/u97) that currently use it; a *different* sectionframe with
a descender'd title (like tyn/vtm above) should keep anchoring against
`\gothamSectionframeBoxHeight` directly instead (already correct for them,
confirmed the same way), and a sectionframe whose title text might change
in the future should re-measure (real vector fill, not a visual guess) as
part of that edit rather than assume either constant still applies.

The institute logo, though, stays exactly where it sits on every other
frame type — even though gotham normally vertically centers it against the
title's own baseline (which would otherwise drag it down along with a
bottom-anchored title). `\gothamFrametitleLogoFixed` is `sectionframe`'s
opt-in for the frametitle hook to redraw the logo at a fixed page-corner
position instead of wherever the title line puts it (same
set-before/reset-after mechanism as `\gothamChapterLogoPath`/
`\gothamFrametitleFullHeightYellow` above) — the white patch behind it
already covers the logo's full column down to the bar's bottom edge
regardless of which position is used, so this doesn't need any patch
changes of its own. `\gothamSectionframeContentDrop` adds a little extra
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
black backdrop (`\gothamFullBleedBlack`, a fixed HTML black — deliberately
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
own. The accent color is the named color `gothamHighlightColor`, set via
`\colorlet` rather than baked directly into the environment, so retargeting
every `highlightframe` in a deck to a different color — title bar and
footer both — is still a one-line change
(`\colorlet{gothamHighlightColor}{...}`).

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
`\gothamIncreaseContentTopShift` is needed.

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
in tikz, etc. — see the demo slide
[slides/ZZZ-EN-Standard-content-current.tex](example/slides/ZZZ-EN-Standard-content-current.tex)
for `\textcolor{}` in body text). These names are shared machinery, defined
once per institution in that institution's own `Slidemaster_preamble_*.tex`
(see the directory layout above for the base/institution-layer split) with
different hex values — a slide
that uses `c_secondary_blue` renders in Graz's blue, MCI's blue, or
Innsbruck's blue depending only on which preamble the deck `\input{}`s, with
no change to the slide itself. For a visual reference of all of them under
whichever preamble is currently loaded — see
[slides/ZZM-EN-Slidemaster-colors-current.tex](example/slides/ZZM-EN-Slidemaster-colors-current.tex),
a `standardframe` with a tikz `\foreach` grid of colored boxes (one loop over
all the color names, rather than one `\node` per color, so adding a new
color later just means adding one name to the list). Watch for one gotcha if
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
[slides/ZZU-EN-Footnote-symbol-options-current.tex](example/slides/ZZU-EN-Footnote-symbol-options-current.tex)
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
`\gothamSideFootnoteHsize`/`\gothamSideFootnoteTopSep`/`\gothamSideFootnoteRightInset`
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
> setting up a new course deck. What's below is still live, but only
> `decks/test.tex`/`test-student.tex` use it, as the worked demo of the
> shared-slide-list pattern. The two do not interoperate:
> `\omitslide{}` is gated on `\ifgothamStudentVersion`, which only
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
extra marker, e.g. `(slide id: ZZT | omitted from student deck)`, as a
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
\slide{ZZZ-Standard-content}
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

`test.tex`/`test-student.tex` (sharing `test-slides.tex`) are a working
example of exactly this pattern, including one `\omitslide{}`'d demo slide
(`ZZT`).

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
checkbox, never a deck file's own hardcoded setting). That also means it
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
another — check **Presenter** in SlideMage's Active decks table (any
deck, independent of every other checkbox there) and compile. It produces
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
`\gothamPresenterModeOverride` block) to drop beamer's own default
thumbnail-of-the-current-slide and printed compile-date from that
panel — redundant since presenter software already shows the current
slide on its own — leaving the panel almost entirely for note text.
Always instructor-version content, regardless of which other version
checkboxes happen to be ticked in the same batch: full `\pause` reveals
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

There's no "back" stack — a slide reachable from multiple places needs its
own judgment call (or multiple return buttons) about where "back" means.
If the exact same slide id is genuinely `\slide{}`'d twice in one deck
(e.g. a recap via `\slidefinal{}`), hyperref just warns "multiply defined"
and a link lands on whichever occurrence is *last* in the document —
inherent to any permanent-id-based target scheme, not something to design
around.

**"Generate appendix TOC"** (SlideMage's Active decks toolbar, next to
"Include footer timestamp") adds a clickable appendix to the Instructor/
version-less and Presenter compiles only (a no-op, no jobname suffix, on
During-course/After-course or a per-chapter compile): an agenda slide —
one entry per chapter plus a leading "Front matter" entry for whatever
comes before the first `\section{}` — followed by a 4×5 thumbnail grid per
chapter (paginated "(2/3)"-style once a chapter exceeds 20 slides), using
the same cached preview PNGs the deck editor's own hover tooltips already
rely on. Clicking a chapter on the agenda jumps to that chapter's own grid;
clicking a thumbnail jumps straight to the real slide. The institute logo
on every slide becomes an invisible link back to the appendix agenda, but
only on a compile that actually generated one.

The grid's own size isn't a fixed cm value — it's computed in LaTeX from
this project's real per-institution length registers (paper size, logo
padding, title-bar/footer height), left-aligned to the text margin and
scaled up until either the row height or the logo's own right edge binds,
so it looks right under Graz/Innsbruck/MCI alike without separate tuning.

## Screen-reader accessibility

> **Image descriptions and per-deck accessible transcripts were built on
> 2026-08-14** — see "Describing images" and "Accessible transcripts" below
> for how to use them, and [ALT_TEXT_NOTES.md](ALT_TEXT_NOTES.md) for the
> design, the decisions behind it and the measured findings (including the
> failure modes worth knowing about before trusting a drafted description).

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
`lualatex` is the one supported engine). `\gothamArtifactBegin`/
`\gothamArtifactEnd` are `\ifluatex`-guarded and silently do nothing under
any other engine, a leftover safety net from when xelatex was still (nominally,
if not actually) supported: an unguarded first version hard-failed every
frame under xelatex with `! Undefined control sequence: \pdfextension`. Not
a real concern day-to-day now that xelatex isn't a target at all, but kept
rather than removed — cheap insurance against ever compiling this with the
wrong engine by accident.

What actually works: `/Artifact` is a standalone PDF
marked-content tag (PDF spec 14.8.2.2), valid in *any* PDF with or without a
structure tree — no `/Properties` resource entry or MCID needed.
`\gothamArtifactBegin{dict}`/`\gothamArtifactEnd` (in
`Slidemaster_preamble_base.tex`, "PDF accessibility" comment) wrap a region in
`/Artifact <<dict>> BDC ... EMC` via LuaTeX's raw
`\pdfextension literal direct{...}` primitive, e.g.
`\gothamArtifactBegin{/Type /Pagination /Subtype /Footer}` for the footer,
`\gothamArtifactBegin{/Type /Background}` for a plain decorative fill (the
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

**Verification.** `decks/verify_accessibility.tex` is a compilable regression
deck (same idiom as `decks/test.tex`) exercising every frame type above,
including one real `sideimageframe` slide and one real `fullbleedframe`
slide that `test-slides.tex`'s own demo slides predate and don't cover.
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
Images tab, automatically pulled into a compiled slide's own footnote —
every distinct source among a frame's images, de-duplicated, prefixed
"Image source(s):" — so a hand-authored `\source{}` is no longer needed
for image attribution specifically (it still is for anything else, e.g.
a data source for a table). See `ALT_TEXT_NOTES.md` for how.

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

**The workflow**, all in SlideMage's green **Images** tab:

1. **Draft all…** runs a local vision model (Ollama) over every image that
   still needs a description — once per image, not once per slide it appears
   on. It writes each one as it finishes and derives its queue from the
   store, so it is resumable — stop it, close the app, come back tomorrow.
   The list updates as it goes, so you can review the early ones while the
   rest run.
2. **Review each one against the image**, which the tab shows at full size.
   This is not optional; see the warnings below.
3. **Save and mark reviewed** stamps the slide — both the image's
   description and this slide's own use of it (its takeaway). Editing the
   slide's own `.tex` afterwards moves it to "needs re-check" rather than
   silently keeping the old description; editing the description *itself*
   and clicking plain **Save draft** un-reviews this slide's use of it
   immediately (2026-08-25) — a hand-edited description shouldn't keep
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
`\node[gothamImageBorder]{\includegraphics{...}}`/`\gothamMugshot{}` call
— a decorative border around one real image, which already has its own
alt-text entry; wrapping the border too would just duplicate it.

It shows up in the Images tab's per-slide list exactly like a real image (as
`tikz:ID`), with the same role radios, short/long/takeaway/source fields,
and **Draft…**/**Tune prompt…** buttons — none of that UI needed to change,
since the tab already treats "which images does this slide reference" as
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
reader. Generate a whole deck's transcript from either the deck-editor
tab's own **Transcript** button (next to **Source**) or the main deck
table's **Create Transcript** button (next to **Stop creation**, which
also asks which deck) — either way, pick a **version** when prompted and
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
- Images with no description yet are flagged **in place** rather than silently
  omitted, so a half-described deck produces an honest transcript.
- A slide can also carry a free-text **summary**, independent of any image
  — shown at the top of that slide's transcript entry, before its own body.
  Set it from the **slide-source editor** ("Transcript summary" field, its
  own "Save summary" button), not the Images tab: it needs to work for any
  slide, including ones with no images at all, which the Images tab's own
  list never shows.
- **Previewing one slide's own entry** (no deck, no file written): the
  Images tab's own **Transcript version** dropdown + **Generate transcript**
  button (also on the slide-source editor's own "Render transcript"
  button) renders just the currently-selected slide and opens it in its
  own preview tab — nothing is saved to `transcripts/`, or anywhere else.

## Slide previews

Every compile that touches a slide — rendering it on its own, or compiling
a whole deck (instructor version) — refreshes a cached pair of PNGs of how
it last looked (full-size and thumbnail, see below), so you can glance at
a slide without paying a LaTeX compile to do it. Previews are specific to
the institution template that produced them: a Uni Graz deck and a Uni
Innsbruck deck compiling the same slide keep separate caches, and each
deck's editor always shows its own template's previews. Several ways to
see them, all reading the same cache:

- **Hover** over a slide's id in the deck editor (or the deck table) for an
  instant preview tooltip.
- Click **Preview** (deck editor's per-row button, or the slide-source
  editor's own button next to "Render to PDF") for a larger look, with a
  "Render now" fallback if nothing's cached yet for that slide.
- Switch **View: List / Thumbnail / Grid** (radio buttons, top right of
  the deck editor's toolbar). **Thumbnail** shows a rendered thumbnail
  below each slide's id — every other control (variant, remove,
  +before/+after, Preview) stays exactly where it is; this only adds an
  image, it doesn't replace the row. **Grid** is a separate, purely
  visual browsing view: a card per slide, grouped by chapter, click to
  open — no row controls, for a quick overview rather than editing.
- The **chapter dropdown** (top toolbar, between Undo and Close) jumps
  straight to a chapter in whichever view you're in, its heading landing
  at the top of the view,
  without hunting for it by scrolling.

This is a best-effort cache, not a guaranteed-fresh one — it only updates
when something actually compiles that slide, so it can lag behind an
unsaved (or even a saved but never recompiled) edit. The slide-source
editor's own "Render to PDF" always compiles your current buffer directly
and is unaffected by any of this.

To refresh every slide's preview in one pass (e.g. after a preamble/theme
change), click **Update previews** in the main toolbar and confirm — no
institution to pick any more: it scans every deck (active and archived)
for which slides it actually uses under which template, compiles one
throwaway deck per template containing exactly that template's own
needed slides, and deletes any cached preview no deck uses any more
(e.g. a slide removed from every deck, or moved to a different
institution). This is one long compile (well over an hour is plausible
for the whole project) that occupies the compile slot until it finishes,
so no other compile can start in the meantime.

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
- SlideMage: the deck editor lists the calls (with their versions), `Included in decks`
  headers count them, a transcript numbers them like `\conditionalslide`, the appendix
  TOC shows the slide once, and slide rename follows the id. Steps are edited in the deck
  file (the variant dropdown does not offer `\slidestep`).

### List labels: where they start

A list label starts at the left edge of the bullet dot of its own level (12.76pt for level 1, then +8.84pt per
level), the way the source PowerPoint places it: enumerate numerals (level 1 additionally puts the item text at
27.9pt, nested bullets unchanged; `\gothamEnumerateTextExtra`), ellipsis labels via `\item[\gothamBulletEllipsis]`,
and a bullet template that is itself an ellipsis via `\setbeamertemplate{itemize subitem}{\gothamBulletEllipsisScript}`.
Hand-tuned label environments (`gothamnum*`/`gothamalpha*` itemize, `\gothamTocLabelFlushLeft`, ...) keep their own
measured geometry. `python .scripts/check_list_labels.py <compiled.pdf>` measures every label of a compiled deck
against this rule and lists the exceptions.

### `\gothamFinalStateForStudents` — student decks show only the final state

Put `\gothamFinalStateForStudents` in a slide file, right before its frame environment (after
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
