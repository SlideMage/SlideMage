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
- **A needs one full compile of the version first** (owner accepted), and **the helper files A restores are kept with the compile record** (owner decision). This is already how `compile_records.py` works:
  - *Where*: `.build/compile-records/<jobname>.json` (the record) and **`.build/compile-records/<jobname>/`** (`aux_dir`, `compile_records.py:220-230`) holding copies of `.aux .nav .toc .snm .out .bbl .top .ovl .timestamp` (`AUX_EXTENSIONS`, `:58`) plus `deck.tex`, the deck as compiled (`DECK_COPY_NAME`, `:57`; copied at `:296-314`). That is every file A restores (`partial_compile._RESTORED_EXTENSIONS`) and a bit more. `<jobname>` is per deck and version, so each deck version has its own set.
  - *Size*: small text files; typically tens to a few hundred KB per deck version (the `.aux`/`.nav`/`.toc` grow with the number of slides). To be measured on the manual deck at implementation time. The PDF is not copied: the record stores its path and SHA-256 (`:296-299`); it lives in the normal output folder (`pdf/`).
  - *When replaced*: after every successful whole-deck compile of that deck version, the aux folder is deleted and rewritten (`shutil.rmtree(aux)` then copy, `:252-254`), the record rewritten; a failed copy removes the aux folder again (`:285`), after which the warning returns until the next compile.
  - *What leaves them alone*: the build cleanup behind "Remove temp files" lists `.build` children but excludes `compile-records` entirely, aux folders included (`removable_build_entries`, `compiler.py:94-119`, direct instruction 2026-10-08 "They are small and would be good to keep"); `housekeeping.py` works from that list and cleans only `build`/`wrappers`/`scratch` items (`housekeeping.py:23,55-63`).
  - *Survives closing and reopening SlideMage*: yes, it is on disk.
  - *When the warning would come back*: no whole-deck compile of that version yet; the user deleted `.build` or `compile-records` by hand; the deck changed after the compile (records are then stale, `partial_compile._first_change`, but still usable by the "B" titles scan below); the published PDF was deleted or replaced (A cannot map pages without it, `partial_compile.plan`); a snapshot-mode project (copies elsewhere).
- Views: contexts are per version (`compile_records` is keyed by job/version), so the view being previewed must have a record; else fall back.
- Buffer renders (unsaved text) use the same wrapper with the buffer text as the slide body, as `slide_preview.render_slide_source` does today.

### B. Lightweight skeleton with ALL sections (fallback and for decks never compiled)

Wrapper text: the deck preamble, then (1) the deck's `\section`/`\subsection` commands **up to the slide's position**, in order, with nothing between them (no frames); (2) `\setcounter{framenumber}`/`{page}`; (3) the slide call; (4) the **remaining `\section`/`\subsection` commands after the slide's position**, again with no frames; then `\end{document}`. The commands are parsed from the deck text as `partial_compile.wrapper_text` already walks it (`:347-404`). Two passes (as A): on the second pass beamer reads the `.toc` written in pass 1, which now lists every section, so a `\tableofcontents` slide shows the later sections too, while `\insertsection` and the current-section highlight at the slide are correct because the sections before it were executed before the slide.

Checked in the installed beamer (`beamerbasesection.sty`, MiKTeX):
- `\section` writes its `.toc` entry (`\beamer@sectionintoc{number}{title}{\c@page}{part}{tocnumber}`, line 195) and its `.nav` entries (`\beamer@sectionpages`, `\sectionentry`, lines 199-202) **at the point of the command, with no frame required**; `\subsection` likewise (lines 272-277). So section-only wrappers do produce a complete `.toc`/`.nav`.
- What breaks or is wrong: (a) each entry records `\the\c@page` at the moment of the command, so every section after the slide gets the **same page number** as the slide (and earlier ones the starting page), not its real page: section page numbers in a contents slide, and the hyperlinks `Navigation<page>` that `\insertsectionhead` builds (`beamerfontthemegotham.sty:219-253`), point at that page; harmless in a single-slide PDF, but not the real numbers; (b) `\beamer@sectionpages` / progress data (`.nav`) are computed from those fake pages, so section-progress bars and "sections x of y" navigation are not faithful; (c) `\SMChapterAgenda` (`:6769`) needs per-slide title records; plain B has none, which B2 below supplies without frames; (d) citations and `\ref`s are not resolved in B; (e) the page counter: the skeleton leaves `page` at the slide's page and the trailing sections add nothing, so the slide itself keeps the right number.
- Hypothesis to test early (cheap): with trailing `\section`s, the first pass ends with a `.toc` whose entries after the slide have the slide's page; confirm that `\tableofcontents[currentsection]` still highlights the right entry because highlighting uses section numbers, not pages.

`\addtocontents`-style seeding of invented page numbers is still not worth it; real numbers only come from A.

#### B2. Frameless agenda records: real titles for `\SMChapterAgenda` and friends

Question from the owner: can B carry the correct slide titles so that chapter agendas show real titles? **Yes, and without placeholder frames.** How `\SMChapterAgenda` gets its data (`Slidemaster_preamble_base.tex:6769-6935`): it reads the `.aux` at `\begin{document}` (second pass). Two kinds of lines feed it:
- `\SMAgendaSlide{section}{id}{label}`, written by `\setSlideID` through `\SM@agenda@slide` (`:1242-1280,6877+`) for **every slide call, with no frame needed**;
- `\SMAgendaEntryTitle{id}{title}`, written by the frame-title hook (`\SMAgendaFrametitleHook` -> `\SM@agenda@frametitle`, `:6849-6852`) when a frame with a title is typeset, **or by `\SMAgendaTitle{text}`, callable anywhere** (`:6890`, it writes for the current `\slideID`).
So the skeleton can emit, for each slide call of the previewed view in deck order, at its position between the `\section`/`\subsection` commands:
`\global\SMSuppressSlideTargettrue\setSlideID{<id-slug>}\global\SMSuppressSlideTargetfalse\SMAgendaTitle{<title verbatim>}`
(suppressing the `\hypertarget` so the real slide's target is not duplicated), with no frame and therefore **no change to `framenumber` or `page`**. Pass 1 writes the full agenda records, pass 2 shows them. Placeholder frames would add pages, shift counters and need `\setcounter` bookkeeping for nothing, so they are rejected (kept only as a fallback if a hook turns out to need a frame, which the code above does not).

Which calls: each slide call of the deck that is included in the previewed version/view (`SlideCall.included_in(view)`, `deck_editor.py:103`; `\omitslide`/`\conditionalslide` not listing the view are skipped), in order; the previewed slide itself is skipped (it is the real call; the agenda does not list its own slide, `:6780-6781`); a slide called twice (`\slidestep`) is listed once at its first place, which `\SM@agenda@slide` already guarantees.

Where the title comes from (read from the slide file; **no LaTeX**):
- the first `\begin{<x>frame}[opts]{Title}` argument for the Slidemaster frame environments whose second argument is the title (`standardframe`, `sectionframe`, `figureframe`, `highlightframe`, `sideimageframe` takes `[#1]{#2}{#3}`: signatures from the `\newenvironment` lines at `:3861,6109,6295,6608,6636`; a small table of "title argument index" per environment), brace-matched with the same masking `latex_lint.py` uses; also plain `\begin{frame}{Title}` and `\frametitle{Title}`;
- a `\SMAgendaTitle{text}` in the slide wins over the frame title (as in the real recording, where the first writer for an id wins: `\SM@agenda@title` guards with `SM@ag@titled@<id>`; the scan applies the same precedence by order of appearance);
- frames without a title (`\quoteframe`, `\fullbleedframe`, ...): no `\SMAgendaTitle`; the agenda falls back to the slug label exactly as the real deck does (`\SM@ag@entry`, `:6900-6905`);
- multi-frame slide files: only the first titled frame counts (the real recording is once per id);
- titles with macros: kept verbatim (detokenized by the recording macro just as in the real compile), compiled in the same preamble; a macro defined inside the same slide file (`\newcommand` before the frame) would be undefined in the skeleton; the scan then takes the title recorded by the last full compile's aux (even if stale; owner decision) and falls back to the slug/ID label only when no such title exists;
- language variants: read the file the call resolves to (`deck_language.resolve_call`, `deck_language.py`, with the previewed language), the same function `preview_target.for_call` uses (`preview_target.py:66-71`);
- pinned versions: `\slideversion`/`\slidefinal` -> read the frozen file the call names (`SlideCall.source_filename`, `deck_editor.py:95-101`).

Cost: reading and scanning one small file per slide call (hundreds of files at most), no extra LaTeX beyond B's two passes. Caching: keep a per-deck dict {call -> (slide file mtime and size, title)} in memory; a title is re-read only when its file's mtime changed; the whole skeleton text is cached by (deck hash, previewed position, view, language, set of those mtimes).

Titles from the last full compile's aux instead? If a record exists (even stale), its `.aux` already contains `\SMAgendaSlide`/`\SMAgendaEntryTitle` lines for every slide of the last compile (`compile-records/<jobname>/<jobname>.aux`). Pros: titles exactly as typeset (macros expanded by the real compile, `\SMAgendaTitle` honoured). Cons: stale for slides added or retitled since; absent when no compile exists, which is precisely when B is used; and the aux's section numbers refer to the old structure. **Recommendation: scan the slide files as the primary source (always available, always current for the previewed deck), and use the stale aux only as a per-slide fallback when the scan cannot produce a safe title (macro-built title) or finds none.** When a *fresh* record exists, approach A is used anyway and none of this applies.

Page numbers in the contents. Section entries record `\the\c@page` at the `\section` command (`beamerbasesection.sty:195`), so with no frames every section would show the slide's page. To get real numbers:
- Placeholder frames would only help if each emitted exactly as many pages as the real slide (a slide has 1 page unless it has reveal steps or several frames), and that count is not known from the source. Rejected as the means.
- The page counts are known from a previous full compile: `partial_compile.page_infos(pdf)` maps every page of the last full PDF to (slide id, frame), and `slide_snapshot.slide_runs` groups pages by slide (`slide_snapshot.py:317-330`), giving each slide's page count and first page. So when a record + its PDF exist (even for a changed deck), the skeleton can run `\setcounter{page}{<first page of the slide that opens this section in the old compile>}` before each `\section` instead of faking frames: entries then carry the real old page numbers, exact for unchanged decks, approximate (but plausible) for edited ones. Without any compile, page numbers stay at the slide's own page; the warning chip says so.
- The A compile record supplies these numbers directly (its PDF path and the `.toc` itself with the real section pages); if a record is fresh, A is used and the question disappears.

Recommendation for B in total: all sections, frameless agenda records with scanned titles, `\setcounter{page}` from the last compile's PDF when available. Chapter and deck agendas then show real entries (titles, order, section structure); only page-number-dependent items (progress bars from `.nav`, "page x" labels) are approximate without a compile.

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

Decided: only slides whose own content needs it get the deck-context render; approach A needs one full compile of the version first and keeps its helper files with the compile record (already so, section 5A); approach B emits all sections and, via B2, frameless agenda records with scanned titles; a title built from a macro defined inside the slide file is taken from the last full compile's aux (even if stale), and only when none exists does the slug/ID label show; no manual "Render with deck context" switch.

1. B2 relies on `\SMAgendaTitle`/`\setSlideID` writing the agenda records without a frame. This is read from the source (`Slidemaster_preamble_base.tex:6849-6935`); confirm with one real-TeX experiment before building (a three-section deck, `\SMChapterAgenda` slide in section 2).
