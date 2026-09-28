# Slidemaster / SlideMage — project overview

Slidemaster is a LaTeX/beamer framework for research and teaching slides,
built on the [Gotham beamer theme](https://github.com/) with an
institution-specific color/logo layer (Uni Graz, in this copy). SlideMage
is a PySide6 (Qt) desktop app that sits on top of it: compiling decks,
managing slide IDs and versions, drafting/reviewing image descriptions via
a local Ollama model, and generating accessible transcripts.

This repository holds the framework and the app, not course content:
real slides and decks live in separate project folders (the original one
has hundreds of course slides, two more institution templates and several
real course decks) that SlideMage opens. What's here: the Gotham theme, the Uni Graz institution layer, and one
small demo deck (~20 slides, all with uppercase test IDs — see "Slide IDs"
below) that exercises every layout, the deck-version/reveal-step system,
and the image-accessibility pipeline end to end. Everything below was
verified against an actual working copy while preparing it, not just
described.

**One repo, three parts.** `latex/` is the institution-independent
framework (Gotham theme, `Slidemaster_preamble_base.tex`,
`Slidemaster_alt.lua`); `example/` is a complete Slidemaster *project* —
slides, decks, media, the Uni Graz institution layer and `slide_ids.csv`,
which marks a project's root; `src/slidemage/` is SlideMage, the app. Paths like
`decks/…`, `slides/…` or `media/…` in these docs are relative to the
project folder, i.e. `example/` here.

Start here, then go to `README.md` for the full reference (it documents
several things — layouts, footnotes, multi-language slides, bibliography
integration — this overview only summarizes) and `SlidemasterManual.md`
for a quick-lookup table of the deck-version commands.

## Core concepts

### Slide IDs and versioning

Every slide is a file in `slides/`, named by a permanent, opaque 3-character
ID plus a human-readable slug: `slides/<id>-<slug>-current.tex` is the live
content you actually edit. Real slides use lowercase IDs; test/demo slides
(like this copy's own `ZZ*` ones) use uppercase, so it's obvious at a
glance which is which. The ID never changes even if the slide's content
does, so it's safe to reference in notes or cite across decks; `slide_ids.csv`
is the registry that keeps new IDs from colliding.

Content is versioned only when it's about to change significantly: right
before a real revision, the outgoing content is frozen as
`<id>-<slug>-v<major>-<minor>-<patch>.tex` (a snapshot, never touched again),
and `current.tex` keeps changing. A deck can load either the live version
(`\slide{ID-slug}`) or a pinned one (`\slideversion{ID-slug}{1-2-0}`), so
one course can keep using an older edition while another moves on. SlideMage's
own slide-editor **Save** button asks Major/Minor/Patch (or "Overwrite" for
a change not worth recording) and does the freeze-then-bump automatically;
see `slides/ZZX-EN-Definition-formula-current.tex` for a slide that's
already been through one real version bump.

### Deck versions and `\slidestep`

A course deck compiles into up to three versions: **instructor** (everything),
**during-course** (given to students at the start of term), and **after-course**
(given at the end). `\omitslide{}`/`\conditionalslide{}` drop whole slides
from specific versions; `\deckonly{}`/`\conditionalpause{}` control individual
reveal steps within a slide. `\slidestep{ID-slug}[versions]{steps}` is the
mechanism for the same multi-step slide appearing in different places with
different steps shown, per version — e.g. an instructor sees a full
build-up including the answer, while students only ever see the question.

This copy includes a **live, compilable worked example**:
`slides/ZZH-EN-Deck-Version-Reveal-Steps-current.tex`, wired into
`decks/test.tex` via two `\slidestep{}` calls (see `decks/test-slides.tex`).
Compile `decks/test.tex` as instructor and it shows all 3 of that slide's
reveal steps; compile it as during-course or after-course (see "Getting
started" below) and it shows only step 1 — the same deck file, the same
slide file, two different outputs.

### Bibliography (`\fullcite{}`/`Slidemaster.bib`)

A deck opts into biblatex+biber (it's not loaded globally) by adding
`\usepackage{biblatex}` and `\addbibresource{Slidemaster.bib}` itself; a
slide then pulls a fully formatted reference straight out of
`Slidemaster.bib` with `\fullcite{key}` — usually inside a `\footnote{}`
or a `\source{}` line, not as a separate references slide (this project
never uses `\printbibliography`). `decks/test.tex` demonstrates this with
plain biblatex defaults, no custom citation-format style — see
`slides/ZZZ-EN-Standard-content-current.tex`'s own
`\fullcite{markowitz1952}` footnote and this copy's trimmed
`Slidemaster.bib` (a single entry; add your own the same way). Compiling
a deck that uses this needs one extra step beyond the usual two `lualatex`
passes — `biber`, run in between them — see "Getting started" below and
README.md's "Decks with a bibliography" section for the full sequence and
what it looks like when that step is accidentally skipped.

### Accessibility: image descriptions and transcripts

Every image used from `slides/` is classified **decorative** (adds nothing
to the text — skipped by screen readers, no alt text) or **informative**
(a chart/screenshot/photo that needs describing), plus a short and long
description, a source citation, and a per-slide "takeaway" (why *this*
image is on *this* slide). All of it lives in one place, `media/alt-text.json`
— an image only needs describing once, however many slides use it — and is
edited entirely through SlideMage's **Images** tab, never by hand.
`media/alt-text.csv` alongside it is a generated projection of the same
data that the LaTeX/Lua side reads at compile time (LuaTeX has no JSON
library); never edit it directly, it's overwritten on every save.

This copy's one real example, `media/correlation-matrix-example.png` (used
on `slides/ZZP-EN-Figure-only`), already has a full description in both
English and German — open it in SlideMage's Images tab to see the actual
shape of a finished entry.

A hand-drawn `tikz` diagram gets the same treatment by wrapping it in
`\tikzillustration{ID}` instead of a bare `tikzpicture` — SlideMage renders
it to a PNG on demand and it shows up in the Images tab exactly like a real
image file.

Beyond the PDF itself (which marks decorative images as PDF artifacts and
types an informative image's alt text invisibly for text extraction — see
README.md's "Screen-reader accessibility" for the verified detail), a whole
deck's **accessible transcript** — Markdown + HTML, one entry per slide,
resolving deck versions/omitted slides exactly like the PDF compile does —
generates from the Images tab or the deck table's own "Create Transcript"
button, for the during-course/after-course versions only.

### The Ollama connection

Drafting image descriptions runs against a **local** Ollama server
(`http://localhost:11434` by default — see `src/slidemage/alt_draft.py`), not
a cloud API: no API key, no per-image cost, nothing leaves the machine.
"Draft all…" in the Images tab queues every image still needing a
description, runs a vision-capable model over each one, and is resumable —
stop it, close the app, come back later. The original project uses
`qwen3-vl:32b` for drafting and `translategemma:12b` (a dedicated
machine-translation model) for the optional English→German translation
pass; any vision-capable Ollama model works, but a 32B model needs a real
GPU with enough VRAM — a smaller model (e.g. `llama3.2-vision` or
`qwen2.5vl:7b`) is a reasonable starting point on more modest hardware,
just expect lower-quality drafts on dense charts. **Drafts are never
trustworthy until reviewed against the actual image** — the tab shows it
at full size for exactly that reason; two known failure modes (fabricated
values on faint scanned charts, worst readings on a chart's flat early
region) are documented in README.md's "Describing images" section.

SlideMage serializes every Ollama call (drafting and translation alike)
through a single app-wide mutex — running two at once has been observed to
crash a local Ollama server, apparently from two models being loaded into
VRAM simultaneously.

### SlideMage itself

Launch with `slidemage` (see below for environment setup). Three tabs: **Active decks** (one row per deck,
checkboxes for Instructor/During-course/After-course plus
After-course-per-chapter, each an independent compile via `latexmk`),
**Archived decks**, and the green **Images** tab covering everything above.
The **Info** menu action opens a window with two tabs: **Version history**
(this app's own dated changelog) and **License** (this project's CC BY-SA
license, read live from the `LICENSE` file).

## Getting started / system requirements

1. **Clone the repo:**
   ```bash
   git clone https://github.com/stpalan/SlideMage.git
   cd SlideMage
   ```
2. **A LaTeX distribution with LuaLaTeX.** TeX Live is the natural choice
   on Linux/macOS; MiKTeX on Windows. `lualatex` is the *only* supported
   engine — the Gotham theme loads Fira Sans via `fontspec`, which plain
   `pdflatex` silently mis-renders instead of erroring, and slide content
   uses Unicode math comparison characters `xelatex` doesn't handle out of
   the box. Let your distribution auto-install missing packages on first
   compile (or install the `fira`/Fira Sans font package up front) —
   `beamerfontthemegotham.sty` checks for the Fira Sans `.otf` files
   directly and needs them findable. `biber` is needed too — `decks/test.tex`
   itself now exercises the bibliography mechanism (see "Bibliography"
   above); plain `lualatex test.tex` alone leaves its one citation showing
   as the raw key `markowitz1952` instead of a formatted reference.
3. **Python 3.11+** with a virtual environment, installing SlideMage from
   this repo:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate   # Windows: .venv\Scripts\activate
   pip install -e .            # add ".[dev]" for pytest/ruff
   ```
   This installs PySide6 (the GUI), PyMuPDF (PDF-to-PNG rendering for slide
   previews and tikz-illustration drafting), python-pptx (the Export-PPTX
   feature), and Pillow, plus the `slidemage` command (on Windows it opens without a console
   window).
4. **[Ollama](https://ollama.com/)**, running locally, with at least one
   vision-capable model pulled (`ollama pull qwen3-vl:32b`, or a smaller
   vision model — see above) — only needed for drafting image descriptions
   via SlideMage's Images tab; everything else (compiling, slide IDs,
   deck versions) works without it, although some capabilities requirements
   a local model (e.g., syntax check, AI drafting of changes on slides).

`.gitattributes`/`.gitignore` are already here and set up to normalize
line endings and exclude generated output (`.build/`, `transcripts/`,
`.previews/`, compiled PDFs, `__pycache__/`) — nothing to configure.

Then:

```bash
# Compile the demo deck directly (instructor version, the default).
# Four passes, not two -- the deck's own bibliography needs biber run
# in between (see "Bibliography" above); latexmk (or SlideMage) detects
# and runs this whole sequence automatically, so this is only spelling
# it out by hand:
cd example/decks
lualatex test.tex
biber test
lualatex test.tex
lualatex test.tex
# or, in one line: latexmk -lualatex test.tex

# Or launch SlideMage and use its checkboxes instead (also gives you
# During-course/After-course compiles, the Images tab, etc.) -- these
# four passes run automatically either way:
cd ../..
slidemage --project example
```

SlideMage picks its project from `--project`, else `$SLIDEMASTER_PROJECT`,
else by searching upward from the current directory for `slide_ids.csv`,
else the last project it opened — and otherwise asks for a folder. Its
per-project settings live in `<project>/.slidemage/`.

**Your own project:** copy `example/` anywhere. Its `.latexmkrc` files
look for the framework in `../latex`; for a project kept elsewhere, set
`SLIDEMASTER_LATEX` to this repo's `latex/` folder.

The very first `lualatex` run of `decks/test.tex` (or `test-student.tex`)
will be slow while your TeX distribution fetches whatever packages it's
missing; subsequent compiles are fast. Note that decks typically require
four compile passes to get all layout and citation details right, but
these four passes run automatically when using SlideMage.

## Where to go next

- `README.md` — the full reference: directory layout, layouts/frame types,
  the naming/versioning convention, multi-language slides, accessibility
  in full detail, and more.
- `docs/SlidemasterManual.md` — a quick-lookup table for the deck-version
  commands (`\slide`, `\omitslide`, `\conditionalslide`, `\slidestep`,
  `\deckonly`, `\conditionalpause`, `\deckversion`).
- `docs/SlideMage.md` — how the app itself is built, module by module,
  including gotchas hit while building it.
- `LICENSE` — this project is CC BY-SA 4.0.
