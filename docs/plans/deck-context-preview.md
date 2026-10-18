# Deck-context previews: slides that depend on the rest of the deck

Status: plan only (no code). Base: develop @ b3acd47 (v8.23.1). Companion of `docs/plans/reveal-step-slider.md`.

## 1. The problem

A single-slide preview compiles one slide alone. Slides that show deck-wide information look wrong or empty:
- agenda / contents slides (`\tableofcontents`, e.g. `example/slides/1r2-EN-Contents-current.tex:26,36`, which also warns it needs "the first pass, before the .toc exists"), `\SMDeckAgenda`, `\deckappendixtoc`;
- chapter dividers and their agenda (`sectionframe`, `Slidemaster_preamble_base.tex:6295`, `\SMChapterAgenda`, `:6769`; `\SMAgendaFrametitleHook` records titles of the section's frames, `:962`);
- anything using the current section: `\insertsection` (the footer, `:2679-2682`), `\insertsectionhead`/`\insertsubsectionhead` (`beamerfontthemegotham.sty:219-253`), `\insertsectionnumber` (`beamerinnerthemegotham.sty:744-751`), section navigation, `\secname`;
- frame and page numbers: `\insertframenumber` in every footer (`:2786`), `\inserttotalframenumber`, the progress strip (`\progressstrip`, `:3805`);
- deck-level references: `\ref`, `\pageref`, `\hyperlink` to other slides (`\SMDeckAgenda` target, README.md "Manual chapters" link), `\cite`/bibliography numbers (`example/slides/1nz-EN-Footnotes-Sources-Citations-current.tex`).

## 2. What the single-slide wrapper provides today

`slide_preview.py` writes a wrapper = the deck's preamble (or the default template's, `default_preamble`, `:272-277`) + `\setcounter{framenumber}{N-1}` when the caller knows the deck position (`_frame_number_line`, `:280-297`) + view/language/timestamp overrides + `\setSlideID`/`\setSlideLanguageFromSlug` + the slide call (`slide_preview.py:515-528`, `:610-621`). `PreviewTarget.frame_number` is the call's **position** in the deck (`preview_target.py:70`), a good approximation of the frame number only when each earlier call has exactly one frame. It does **not** provide: `\section`/`\subsection` commands, any `.aux`/`.toc`/`.nav`/`.snm` data, the total frame count, bibliography results, or other slides' labels. Previews reuse a latexmk dependency graph per slide in `.build/preview-cache/` (`preview_build.py`), so each preview starts with no `.toc`.

## 3. What already exists that can be reused

`partial_compile.py` (v5.35.0) already does the hard part for page compiles: it compiles "the deck with every other slide call removed" (`wrapper_text`, `:347-404`: the deck text is kept, including all its `\section{}` commands, and only the other slide calls are dropped), sets `framenumber` and `page` to their full-deck values, and runs two lualatex passes on top of the **last whole-deck compile's** `.aux/.toc/.nav/.snm/.out/.bbl/.ovl` (`_RESTORED_EXTENSIONS`, `:41-42`, restored between passes by `_restore_full_aux`, `:407-428`). Those files and the full PDF are kept per version by `compile_records.py` (`.build/compile-records/<jobname>.json`). `plan()` (`:271`) finds the slide's frames in the full PDF and verifies "the deck file itself must be unchanged since that compile" (`_first_change`, `:322`). So a faithful deck-context render of one slide is, in effect, a one-slide partial compile that is not patched into the PDF.

## 4. Detecting slides that need context

A new scan `deck_context.needs_context(slide_source) -> set[str]` over the slide text (comments and verbatim masked as `latex_lint.py` does) returning reasons from a table:

| Reason | Triggers |
|---|---|
| contents | `\tableofcontents`, `\SMDeckAgenda`, `\deckappendixtoc`, `\SMChapterAgenda` |
| section | `\insertsection*`, `\insertsubsection*`, `\secname`, `\SMChapterAgenda`, `\begin{sectionframe}` |
| numbers | `\insertframenumber`, `\inserttotalframenumber`, `\insertpagenumber`, `\progressstrip` |
| references | `\ref`, `\pageref`, `\cref`, `\autoref`, `\hyperlink` to another id, `\cite*`, `\nocite`, `\printbibliography` |

Every footer prints `\insertframenumber`, which the frame-number line already handles, so the "numbers" row only counts when the slide body itself uses these macros. Likewise the footer may print `\insertsection` (`:2679-2682`); the scan looks at the slide file only, and whether every slide of a sectioned deck should count is open question 1.

Also used: an "unresolved reference" signal from the preview log (`LaTeX Warning: Reference ... undefined`, `??` in text) as a backstop: the lint already reads logs; a render with such a warning is flagged "may differ" even if the scan missed it.

## 5. Approaches

### A. Reuse the partial-compile machinery (recommended for contents/agenda/section slides)

Render the slide through `partial_compile`-style `wrapper_text`: the deck's preamble and body with all other slide calls removed, counters set, the last full compile's aux files restored. The preview then shows the real contents list, real section name, real frame/page numbers and citations, because those come from the full compile's files.

- Precondition: a **fresh whole-deck compile of the same version exists** and the deck file is unchanged since (`plan()` / `_first_change`). If the slide itself changed after that compile, the slide is rendered from its current text but numbers and section structure come from the old aux data (acceptable and exactly what `partial_compile` documents). If the deck changed (a slide added/moved), the numbers may be off: fall back to B and say so.
- Views: contexts are per version (`compile_records` is keyed by job/version), so the view being previewed must have a record; else fall back.
- Buffer renders (unsaved text) use the same wrapper with the buffer text as the slide body, as `slide_preview.render_slide_source` does today.

### B. Lightweight skeleton (fallback and for decks never compiled)

Emit into the single-slide wrapper, before the slide call: the deck's `\section`/`\subsection` commands **up to and including** the slide's position (parsed from the deck text, as `partial_compile` already walks it), each followed by nothing (no frames), plus `\setcounter{framenumber}`/`{page}`. Gives: correct `\insertsection`, section numbers, and a `\tableofcontents` that lists sections up to this slide. Does not give: later sections in a contents slide (so "Part B on the right" is empty), chapter-agenda entries (`\SMChapterAgenda` needs the frame titles of its section, recorded via `\SMAgendaFrametitleHook`, so it would be empty), total frame count, citations, cross-references.

`\addtocontents`-style tricks are possible to seed later sections: write all `\section` entries of the whole deck into the `.toc` before the slide with `\addtocontents{toc}{...}`, or generate the `.toc`/`.nav` text ourselves, but the section page numbers and the agenda link targets are guesses without a full compile, and beamer reads `.toc` at `\begin{document}` (first pass) only. It is not worth reimplementing what approach A gets from real files.

### C. Seed only the auxiliary files into the existing preview build

Copy `.toc/.nav/.aux/.snm` from the full compile into `.build/preview-cache/<slide>/` before each preview, leaving the wrapper as today. Cheapest, reuses the incremental latexmk state, but then `\section` is never executed in the preview, so `\insertsection` in the footer stays empty and beamer's `\tableofcontents` works while the "current section" does not. Needs approach B's `\section` lines anyway. Use as an optimisation of A: keep A's wrapper but run through the preview-cache build instead of a fresh two-pass build (see cost).

**Recommendation:** A where a matching full-compile record exists, B as the fallback, and the visible warning (section 6) whenever neither fully applies.

## 6. UI

- Normal slides: unchanged (single-slide render).
- Slides flagged by the scan: the Preview chips (`chips_for`, `preview_view.py:68`) get **"Deck context"** (info tone) when rendered by A, and **"Rendered without deck context: may differ from the full deck"** (warning tone) when rendered by B or neither, with a tooltip naming the reasons (contents, section, references) and a button "Compile the deck first" when A needs a fresh full compile (starts the normal deck compile for the view).
- Footer snapshot rule: only A renders may refresh the canonical snapshot/thumbnail (`slide_preview.py:528`, instructor view only); B/no-context renders never overwrite a good deck-context snapshot, because a context-less contents slide would degrade the slide list thumbnails.

## 7. Cost, caching, interactions

- **A**: two lualatex passes of a deck-sized wrapper (the deck preamble loads once; only the one slide is typeset). Roughly the cost of a partial compile of one page (reported in `partial_compile` as seconds, to be measured; measure with `tools/preview_benchmark`), more than a single-slide preview because the aux data is larger. Mitigation: only for flagged slides; cache the PDF by key (slide source hash, deck hash, compile-record id, view, language) and reuse until one of them changes; the compile-record id comes from `compile_records.read_run_id`/record path.
- **B**: the cost of a normal single-slide preview plus a few lines.
- **C** (as optimisation of A): reuse `preview_build` incremental state for the one-slide wrapper, restoring the aux files only when the compile-record id changes.
- **Invalidation**: a new whole-deck compile of that version, an edited deck (hash), an edited slide (mtime), a template change.
- **Reveal slider** (`reveal-step-slider.md`): context only changes numbering/section data, not overlays, so the slider's unrestricted render and per-version renders use the same wrapper type as the normal render of that slide (A for flagged slides) and share the cache key part for context. Background version renders (5.1 there) skip flagged slides when no record exists. The page count N is unaffected by context except for agenda slides whose entries use overlays (the context makes the real list appear: do the count from the context render).
- **Snapshots**: see section 6; `capture_deck` (`slide_snapshot.py:317-345`) already derives snapshots from full compiles and stays the authority for flagged slides.
- **Transcript/presenter**: unchanged.

## 8. Risks

- Stale aux data gives plausible but wrong numbers; mitigate with the freshness check and the chip showing "from the compile of <time>".
- Slides that mutate global state (counters, `\SMDeckAgenda` registering targets) behave as in the real deck in A, but as nothing in B.
- `partial_compile` removes other slide calls using the deck's own call parser; decks with raw frames or unusual `\input`s may not plan (`PartialError`): fall back to B with the warning.
- Two-pass A while a full compile is running: use the existing compile slot/build locks; do not start A while a deck compile of the same job is running (show "waiting for the deck compile").
- Disk: A writes a build folder like a page compile; use the same temp/sweep policy (`slide_preview.sweep_renders`).

## 9. Files to touch

- new `src/slidemage/deck_context.py`: `needs_context()` scan, the choice A/B/none, cache key.
- `src/slidemage/partial_compile.py`: factor a function that renders one kept slide to a PDF without patching (reusing `plan`, `wrapper_text`, `_restore_full_aux`, `run`).
- `src/slidemage/slide_preview.py`, `preview_target.py`, `preview_requests.py`: a context-aware render entry for flagged targets; snapshots gated.
- `src/slidemage/ui/workspace/preview_view.py` (`chips_for`): the chips and the "Compile the deck first" action.
- `CHANGELOG.md`, `README.md` (Interactive preview builds section), version bump.

## 10. Tests

- Unit: `needs_context` table (each trigger, masked comments, plain footer macros not flagged).
- Unit: B wrapper text: `\section` lines up to the slide position only, counters set, subsections included.
- `partial_compile`-based: with a fake compile record, the context render picks A; with a changed deck, B; without a record, B + warning chip (GUI test in the style of `tests/test_centre_gui.py`).
- Snapshot gating: a B render never writes the canonical snapshot.
- Real-TeX (skipped without LaTeX): a two-section deck with a `\tableofcontents` slide: context render lists both sections and the right current section in the footer; the single-slide render does not.

## 11. Open questions for the owner

1. The footer of the Gotham template prints `\insertsection` (a conditional at `:2679`). Should every slide of a deck with sections count as "needs context" (so every preview shows the real section name), or only slides that use these macros in their own body (proposed)? The former costs a two-pass render for most previews.
2. Is it acceptable that A needs a full compile of the version first (one-time per deck state), with the warning until then?
3. Contents slides listing later sections and chapter agendas are only right in A. Is B's partial result (sections up to this slide) better than showing the warning only?
4. Should the Preview offer a manual toggle "Render with deck context" for any slide, not just flagged ones?
