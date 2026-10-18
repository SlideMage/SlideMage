# Deck-context previews: slides that depend on the rest of the deck

Status: plan only (no code). Base: develop @ b3acd47 (v8.23.1). Companion of `docs/plans/reveal-step-slider.md`.

## 1. The problem

A single-slide preview compiles one slide alone. Slides that show deck-wide information look wrong or empty:
- agenda / contents slides (`\tableofcontents`, e.g. `example/slides/1r2-EN-Contents-current.tex:26,36`, which also warns it needs "the first pass, before the .toc exists"), `\SMDeckAgenda`, `\deckappendixtoc`;
- chapter dividers and their agenda (`sectionframe`, `Slidemaster_preamble_base.tex:6295`, `\SMChapterAgenda`, `:6769`; `\SMAgendaFrametitleHook` records titles of the section's frames, `:962`);
- anything using the current section: `\insertsection` in a slide's own body (the one use in `Slidemaster_preamble_base.tex:2679-2682` is in the `gothampresenter` **notes page** template, `:2651-2699`, i.e. the breadcrumb of the presenter notes, not the slide footer; the frame footer, `:2778`, does not use it), `\insertsectionhead`/`\insertsubsectionhead` (`beamerfontthemegotham.sty:219-253`), `\insertsectionnumber` (`beamerinnerthemegotham.sty:744-751`), section navigation, `\secname`;
- frame and page numbers: `\insertframenumber` in every frame footer (`:2778-2786`), `\inserttotalframenumber`, the progress strip (`\progressstrip`, `:3805`);
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

Every frame footer prints `\insertframenumber`, which the frame-number line already handles, so the "numbers" row only counts when the slide body itself uses these macros. The slide footer does not print `\insertsection`, so section macros count only when the slide's own content uses them (owner decision: only slides whose own content needs it get the deck-context render).

Also used: an "unresolved reference" signal from the preview log (`LaTeX Warning: Reference ... undefined`, `??` in text) as a backstop: the lint already reads logs; a render with such a warning is flagged "may differ" even if the scan missed it.

## 5. Approaches

### A. Reuse the partial-compile machinery (recommended for contents/agenda/section slides)

Render the slide through `partial_compile`-style `wrapper_text`: the deck's preamble and body with all other slide calls removed, counters set, the last full compile's aux files restored. The preview then shows the real contents list, real section name, real frame/page numbers and citations, because those come from the full compile's files.

- Precondition: a **fresh whole-deck compile of the same version exists** and the deck file is unchanged since (`plan()` / `_first_change`). If the slide itself changed after that compile, the slide is rendered from its current text but numbers and section structure come from the old aux data (acceptable and exactly what `partial_compile` documents). If the deck changed (a slide added/moved), the numbers may be off: fall back to B and say so.
- **A needs one full compile of the version first** (owner accepted). The compile records and the aux files that approach A restores live **on disk** in `.build/compile-records/<jobname>.json` plus the compile's build folder, so they **survive closing and reopening SlideMage**; the warning only comes back when they are gone or stale. What removes them: a new whole-deck compile of that version replaces them (then they are fresh again); deleting `.build` or its job folder by hand; "Remove temp files"/build cleanup removes the *build folders* (`compiler.removable_build_entries`, `compiler.py:94-118`, `housekeeping.py`) but deliberately **keeps** `.build/compile-records/` (`compiler.py:107-109`). Caveat to check at implementation: the records store hashes and the PDF path, while the restored `.aux/.toc/.nav` come from the full compile's build folder, which that cleanup does remove, so after "Remove temp files" the warning probably returns until the next full compile; verify and, if so, either keep the aux files with the records or state it in the tooltip. A deck edit makes the records stale (`partial_compile._first_change`) without deleting them.
- Views: contexts are per version (`compile_records` is keyed by job/version), so the view being previewed must have a record; else fall back.
- Buffer renders (unsaved text) use the same wrapper with the buffer text as the slide body, as `slide_preview.render_slide_source` does today.

### B. Lightweight skeleton with ALL sections (fallback and for decks never compiled)

Wrapper text: the deck preamble, then (1) the deck's `\section`/`\subsection` commands **up to the slide's position**, in order, with nothing between them (no frames); (2) `\setcounter{framenumber}`/`{page}`; (3) the slide call; (4) the **remaining `\section`/`\subsection` commands after the slide's position**, again with no frames; then `\end{document}`. The commands are parsed from the deck text as `partial_compile.wrapper_text` already walks it (`:347-404`). Two passes (as A): on the second pass beamer reads the `.toc` written in pass 1, which now lists every section, so a `\tableofcontents` slide shows the later sections too, while `\insertsection` and the current-section highlight at the slide are correct because the sections before it were executed before the slide.

Checked in the installed beamer (`beamerbasesection.sty`, MiKTeX):
- `\section` writes its `.toc` entry (`\beamer@sectionintoc{number}{title}{\c@page}{part}{tocnumber}`, line 195) and its `.nav` entries (`\beamer@sectionpages`, `\sectionentry`, lines 199-202) **at the point of the command, with no frame required**; `\subsection` likewise (lines 272-277). So section-only wrappers do produce a complete `.toc`/`.nav`.
- What breaks or is wrong: (a) each entry records `\the\c@page` at the moment of the command, so every section after the slide gets the **same page number** as the slide (and earlier ones the starting page), not its real page: section page numbers in a contents slide, and the hyperlinks `Navigation<page>` that `\insertsectionhead` builds (`beamerfontthemegotham.sty:219-253`), point at that page; harmless in a single-slide PDF, but not the real numbers; (b) `\beamer@sectionpages` / progress data (`.nav`) are computed from those fake pages, so section-progress bars and "sections x of y" navigation are not faithful; (c) `\SMChapterAgenda` (`:6769`) lists the frame titles of its section, recorded by `\SMAgendaFrametitleHook` (`:962`) while frames are typeset; no frames, no titles, so chapter agendas are empty or incomplete in B (A is needed; optional later improvement: emit empty placeholder frames with the real titles taken from the slide files, one `\begin{frame}{title}\end{frame}` per call, at the cost of many more pages and compile time); (d) citations and `\ref`s are not resolved in B; (e) the page counter: the skeleton leaves `page` at the slide's page and the trailing sections add nothing, so the slide itself keeps the right number.
- Hypothesis to test early (cheap): with trailing `\section`s, the first pass ends with a `.toc` whose entries after the slide have the slide's page; confirm that `\tableofcontents[currentsection]` still highlights the right entry because highlighting uses section numbers, not pages.

`\addtocontents`-style seeding of invented page numbers is still not worth it; real numbers only come from A.

### C. Seed only the auxiliary files into the existing preview build

Copy `.toc/.nav/.aux/.snm` from the full compile into `.build/preview-cache/<slide>/` before each preview, leaving the wrapper as today. Cheapest, reuses the incremental latexmk state, but then `\section` is never executed in the preview, so `\insertsection` in the footer stays empty and beamer's `\tableofcontents` works while the "current section" does not. Needs approach B's `\section` lines anyway. Use as an optimisation of A: keep A's wrapper but run through the preview-cache build instead of a fresh two-pass build (see cost).

**Recommendation:** A where a matching full-compile record exists, B as the fallback, and the visible warning (section 6) whenever neither fully applies.

## 6. UI

- Normal slides: unchanged (single-slide render).
- Slides flagged by the scan: the Preview chips (`chips_for`, `preview_view.py:68`) get **"Deck context"** (info tone) when rendered by A, and **"Rendered without deck context: may differ from the full deck"** (warning tone) when rendered by B or neither, with a tooltip naming the reasons (contents, section, references) and a button "Compile the deck first" when A needs a fresh full compile (starts the normal deck compile for the view).
- Footer snapshot rule: only A renders may refresh the canonical snapshot/thumbnail (`slide_preview.py:528`, instructor view only); B/no-context renders never overwrite a good deck-context snapshot, because a context-less contents slide would degrade the slide list thumbnails.

## 7. Cost, caching, interactions

- **A**: two lualatex passes of a deck-sized wrapper (the deck preamble loads once; only the one slide is typeset). Roughly the cost of a partial compile of one page (reported in `partial_compile` as seconds, to be measured; measure with `tools/preview_benchmark`), more than a single-slide preview because the aux data is larger. Mitigation: only for flagged slides; cache the PDF by key (slide source hash, deck hash, compile-record id, view, language) and reuse until one of them changes; the compile-record id comes from `compile_records.read_run_id`/record path.
- **B**: the cost of a normal single-slide preview plus two passes and a few lines.
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
- Unit: B wrapper text: all `\section`/`\subsection` commands of the deck present in order, those before the slide position placed before the slide call, those after it placed after the slide call and before `\end{document}`, no frames, counters set, subsections included.
- Real-TeX (skipped without LaTeX): a three-section deck, slide in section 2: the context-free B render of a `\tableofcontents` slide lists all three sections, highlights section 2, and the footer-independent `\insertsection` in the body shows section 2.
- `partial_compile`-based: with a fake compile record, the context render picks A; with a changed deck, B; without a record, B + warning chip (GUI test in the style of `tests/test_centre_gui.py`).
- Snapshot gating: a B render never writes the canonical snapshot.
- Real-TeX (skipped without LaTeX): a two-section deck with a `\tableofcontents` slide: context render lists both sections and the right current section in the footer; the single-slide render does not.

## 11. Open questions for the owner

Decided: only slides whose own content needs it get the deck-context render (no footer-based trigger); approach A requires one full compile of the version first; approach B emits all sections (before and after the slide); no manual "Render with deck context" switch.

1. After "Remove temp files" the build folders (and with them the aux files A restores) are removed while the records stay. Is it acceptable that the warning then returns until the next full compile, or should the aux files needed by A be kept with the records (a few small files per version)?
2. Chapter agendas (`\SMChapterAgenda`) stay empty in B. Accept, or add placeholder frames with real titles as a later improvement?
