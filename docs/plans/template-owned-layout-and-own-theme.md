# Plan: templates own the look, fonts come as profiles, SlideMage owns its theme

Status: planned 2026-10-25, not started. Asked for (2026-10-23): "enable users to use different templates (like Uni
Graz, SlideMage, Uni Innsbruck) with as much flexibility as possible. This means that only those commands that are
really relevant for all are defined in SlideMage or its framework, and the remainder are all defined in the
individual templates, so box sizes, positions, etc. can be configured per template". Follow-ups the same day,
both answered "yes": font metrics must be font-specific, so that another font adjusts every font-dependent value
on its own; and Gotham goes, its necessary parts re-created in SlideMage's own framework (as a renamed,
pruned fork, not a rewrite from scratch).

Decided in the conversation:

- Reveal-step and deck-version commands, slide ids, versions, languages and every other logic command stay in the
  framework and are never template-configurable.
- The framework keeps the frame-type commands (`\titleframe`, `\quoteframe`, ...). Templates set the values those
  commands read: sizes, positions, spacing, colors, fonts. They never carry copies of the commands.
- Font-dependent values live in a layout profile. A template picks a profile, and switching it switches all of them
  together.
- Gotham is replaced by a fork pruned to what SlideMage uses, renamed into SlideMage's namespace and owned by the
  framework from then on.
- (2026-10-25) Everything is named SlideMage: no more "Slidemaster" in file names, environment variables, macros,
  Lua tables or documentation (section 0).
- (2026-10-25) The lowercase `gotham...` content names (`gothamtable`, `gothamfloatinginfoblock`, `gotham arrow`,
  ...) are renamed too, with no permanent aliases. Projects are migrated through Project compatibility.

## Today

### Layers

1. **Deck** (`decks/<name>.tex`): `\documentclass[aspectratio=169]{beamer}`, `\usetheme{gotham}`, then
   `\input{Slidemaster_preamble_<template>}`. Every deck in every project has that `\usetheme` line. The app
   writes it in `deck_new.py:17` (`DECK_TEXT`) and `slide_preview.py:192` (the generic preamble), and
   `tools/preview_benchmark/views.py:62` does too.
2. **Vendored Gotham theme** (`latex/beamer{,color,font,inner,outer}themegotham.sty`, `gotham.dtx`, `gotham.ins`,
   `gotham-*.pdf`): © Romain Noël, LPPL 1.3c. `latex/LICENSE` says it is shipped unchanged from v1.2.5.a, and
   `REUSE.toml:45` covers it.
3. **Template** (`Slidemaster_preamble_<key>.tex`): in the framework, `latex/..._slidemage.tex`; in a project,
   `example/..._uni-graz.tex` and the real project `D:\uniCLOUD\Slidemaster`'s `_mci`, `_uni-ibk` and `_uni-graz`.
   Before `\input{Slidemaster_preamble_base}` a template sets:
   - the `c_*` colors
   - `\SMInstituteLogoPath`
   - `\newlength{\SMLogoHeight}` plus `\setlength`
   - `\setlength{\gothamFrametitleRightpading}{0.28cm}`. This works only because the deck loaded the theme
     first; all four templates use the same value.
   - `\SMBulletColor`, `\SMTitleBoxColor`/`TextColor`, `\SMFooterBoxColorDefault`/`TextColor`, `SMCode*Color`

   After the base file it sets `\SMBiblatexOptions`/`\SMBibliographyStyle`, plus optional dark-mode overrides.
   The real project also `\input`s `Slidemaster_project_macros` after the base.
4. **Base** (`latex/Slidemaster_preamble_base.tex`, 6992 lines): everything else. It also replaces a large part
   of Gotham after loading it: footer, block templates, itemize items, footnote template, TOC, logo macro,
   frametitle hooks and text margins.

The app finds templates by file name alone (`slide_snapshot.available_templates`). Any
`Slidemaster_preamble_<key>.tex` except `base` is a template, and its label comes from a
`% SlideMage template name:` line. A new template needs no Python change. The base file shares the template prefix,
so the app has to exclude it by name (`_NOT_TEMPLATES`). Section 0 gives templates a prefix of their own, which
removes that special case.

### Geometry

Almost all geometry already sits in named lengths or macros. The trouble is that their values are hardcoded in the
base file or the theme, and nothing tells a template it may change them. From the inventory:

- **Base**: title frame (`\SMTitleframeBoxHeight` 187.147pt, `TextSep` 2.5ex, `BandGap` 0.8ex, `BottomPad` 41pt,
  :5732-5758), section frame (:6136-6232), quote frame (:6367-6370), footer (`\SMFooterBoxHeight` 7.26pt,
  :2500-2758), footnotes and side footnotes (:2940-3009), blocks (:4898-4972), progress strip (:6597), and the
  text margins `.45cm` (:397).
- **Base, list spacing**: bare ratio macros (`\SMItemsepRatioI-IV`, `\SMItemizeLevelDropSpaceRatioI-IV`,
  `\SMItemizeLevelOpenSpaceRatioI-III`, `\SMTallItemBaseRatio`).
- **Gotham**: `\gothamFrametitle{Top,Bottom,Left,Right}pading` 2.2ex, footline lengths, footer paddings.
- **Font-calibrated (the risky ones)**, in pt measured against Fira Sans:
  - `\SMContentTopAlign` 41.58, `\SMTitleBarBottomAlign` 25.32, `\SMContentTopShift`
  - `\SMColumnsTopCorrection`, `\SMColumnsTTopCompensation`
  - `\SMMinipage*Correction`, `\SMSideImageFrameMinipageCorrection`, `\SMFlatItemizeTopCorrection`
  - the section-frame corrections
  - `\SMFooterRightShift`/`TextDrop`, `\SMFootnoteRightShift`, `\SMSideFootnoteMarkerShift`
  - the `\gothamFootlineVOffset` recalibration (:2480-2493)
- **Lua**: `Slidemaster_layout.lua` hardcodes `TOP_MARGIN_BP = 41.58` and `ASCENDER = 0.935` ("Fira Sans'
  ascender"). Base hardcodes `\SMLineTop` = `\rule{0pt}{0.935em}` (:485).

The automatic Top Margin (base:3730-3800, Lua `top_measure_page`) measures each frame's first content at
shipout and corrects it on the next run. Base's own comment says the older manual top shifts "no longer matter"
under it, so several of the correction lengths above may now do nothing.

### What of Gotham is actually used

SlideMage sets only `\gothamset{background=light}`, `sectionframe default=false` and
`subsectionframe default=false`, and never `\maketitle`, `\part` or `\subsubsection`. Of 5,626 theme lines about
1,530 (27%) are reachable, and once you remove what base replaces anyway, roughly 600-800 lines carry behaviour.

| File | Lines | Reachable | Main dead regions |
|---|---|---|---|
| beamerthemegotham.sty | 191 | ~130 | `\gothamreset` |
| beamercolorthemegotham.sty | 386 | ~300 | red/dark/transparent/fill variants |
| beamerfontthemegotham.sty | 701 | ~300 | non-Lua and "OT" fallbacks, every non-regular format branch (~300) |
| beamerinnerthemegotham.sty | 2160 | ~350 | title-page variants, part/section pages (~630), TOC (~370), blocks, itemize, footnote |
| beamerouterthemegotham.sty | 2188 | ~450 | mini-frames and progress bars (723-2163, ~1440), rotated footer, circle numbering |

Live behaviour that must survive:

- the `\gothamset` key plumbing (it becomes unnecessary once the keys are fixed)
- the color reload and lightBG beamer color roles
- the Fira font setup and the `\setbeamerfont` sizes
- `\parskip 0.5em` and `\linespread{1.15}` (inner:2066-2069)
- the redefined frame `[c]` key (inner:552-558)
- the `[standout]` template and background (inner:560-592)
- the frame-key mechanism with per-frame background and sidebar resets
- empty navigation symbols and headline
- the subsameline frametitle with its struts and logo slot (outer:287-367)
- the footline with its lengths (outer:487-534)
- `numbering=none`
- the caption template

Base relies on packages Gotham loads without loading them itself: fontspec, expl3, calc (`\totalheightof`),
ifluatex/iftex, xcolor, tikz and xfp.

### Who depends on Gotham names

- **Theme names used in the framework and templates**:
  - `\gothamFrametitleRightpading`: 36× base, in every template, slide 1gr, and in Python
    (`appendix_toc.py:43` writes it)
  - `\gothamFrametitleLeftpading`: 15× base, slide 1gr
  - `\gothamFootlineVOffset`, `\gothamFrametitle{Top,Bottom}pading`
  - `\gothamInstituteLogoSquare`
  - `\gotham@frametitlestrut@start/@end`, `\gothamFrameSubtitleSep`, `\gothamFramesubtitleStrutend`
  - `[standout]`: slide 1xf, snippet 1mb-2, base :2661, and the uni-graz template :146
- **Project-defined names with a lowercase `gotham` prefix**, not the theme's: environments `gothamtable`,
  `gothamfloating*`, `gothamalpha/numitemize` and `gothamtightflalign`; tikz styles `gotham arrow`/`highlight`;
  beamer templates `gothampresenter`, `gothamfn` and `gotham plain enumerate`. They appear in hundreds of slides
  and in `latex_lint.py`, `transcript.py`, `latex_edit.py`, `slide_import.py`, `course_schedule.py`,
  `ai/guides.py` and `preview_equivalence.py`.
- **App code tied to the theme**:
  - `preview_equivalence.py:296-318` requires exactly one `\usetheme{gotham}` and strips it
  - `AUDITED_FRAMEWORK` (:22-34) pins SHA-256 hashes of every framework file, the five `.sty` files included
  - `AUDITED_PROJECT_TEMPLATES` pins the template hashes
  - `sm_rename.THEME_NAMES` lists the theme's names
  - `latex_export.THEME_RE` maps `\usetheme{x}` to `beamerthemex.sty` and works for any name
- **Tests**: `test_templates.py:24`, `test_latex_export.py:22,91`, `test_preview_equivalence.py:17,124`,
  `test_deck_snapshot.py:67,95,270,624`, `test_compat_bibliography.py:48`, `test_deck_settings.py:12`,
  `test_readability.py:596`, `test_sm_rename.py`.
- **`tools/check_layout.py`** hardcodes `TOP_MARGIN = 41.58` and `LEFT_MARGIN = 12.55` ("the same in every
  template").

### Bibliography

The ~150-line house format is byte-identical in both shipped templates. This is deliberate:
`bibliography_house.BLOCK` is the canonical text, `compat_bibliography.migrate` inserts it into project templates,
and `tests/test_bibliography_template.py` keeps the copies equal and checks that base keeps *stock* defaults. The
format belongs to the template by design, but the copying is avoidable.

## Goal

- A template author can change every design choice (colors, logo, fonts, box sizes, positions, paddings, list
  spacing, text sizes) in their template file, using names documented in one catalog, without touching the
  framework.
- Switching a template's layout profile adjusts every font-dependent value.
- The framework's own beamer theme holds only what SlideMage uses, under SlideMage names, with correct LPPL
  attribution.
- Every existing deck and template renders pixel-identically after each step until a template deliberately
  changes something. Existing projects are migrated through Project compatibility (`compat.py`).
- Decks never name the theme again, so later theme changes never touch decks.

## Design

### 0. One name: SlideMage

"Slidemaster" was the framework's name before SlideMage became a stand-alone app. On 2026-10-25 it appeared about
680 times: 238 lines in `src/slidemage`, 185 in `tests`, 38 in `latex`, 26 in the example slides and decks, 98 in
`docs`, 61 in README.md, 31 in `tools` and 2 in `packaging`. All of it goes:

| Today | After |
|---|---|
| `Slidemaster_preamble_<key>.tex` (template) | `SlideMage_template_<key>.tex` |
| `Slidemaster_preamble_base.tex` | `SlideMage_base.tex` |
| (new) setup layer | `SlideMage_setup.tex` |
| (new) layout profiles | `SlideMage_layout_<name>.tex` |
| (new) house citation format | `SlideMage_bibliography_default.tex` |
| `Slidemaster_alt.lua`, `Slidemaster_layout.lua` | `SlideMage_alt.lua`, `SlideMage_measure.lua` (not `_layout`, which would read like a layout profile) |
| `Slidemaster_project_macros.tex` (project file) | `SlideMage_project_macros.tex` |
| `Slidemaster.bib` (project file, default of `\SMUseBibliography`) | `SlideMage.bib` |
| `$SLIDEMASTER_LATEX`, `$SLIDEMASTER_PROJECT` | `$SLIDEMAGE_LATEX`, `$SLIDEMAGE_PROJECT` |
| Gotham theme | `beamerthemeSlideMage.sty`, `\usetheme{SlideMage}` (only setup names it) |
| Lua global `gotham_layout`, callback "gotham top margin" | `slidemage_measure`, "slidemage top margin" |
| `docs/SlidemasterManual.md`, "Slidemaster" in prose | `docs/SlideMageCommands.md` or similar, "SlideMage framework" |

Notes:

- **Templates get their own prefix.** `TEMPLATE_PREFIX`/`TEMPLATE_RE` in `slide_snapshot.py` become
  `SlideMage_template_`, and `_NOT_TEMPLATES` goes away. Template *keys* stay as they are (`slidemage`, `uni-graz`,
  `mci`, `uni-ibk`), so cached previews (`<id>-<Template>-<w>-<h>.png`) and the "Default template" setting keep
  working. The theme is `SlideMage` and a template key is `slidemage`; authors never see the theme: setup loads
  it and decks don't name it.
- **Environment variables.** The app reads only the new names. If an old one is set and the new one isn't, it says
  so once in the log and in Info → Project compatibility, then ignores the old one.
- **Macros stay `\SM...`**, which already reads as SlideMage.
- **`sm_rename.py`** (the 2026-10-01 gotham→SM rename) is the model: one identifier mapping, applied to the text of
  slides, snippets, decks, templates, project macros and Lua.
- **History stays as it is.** CHANGELOG entries and dated plan documents are records and keep their wording. Only
  current documentation, comments and code change.
- Grep the whole repository case-insensitively for "slidemaster" when done. The only hits left should be history,
  the compat migration's old→new table, and the compat tests.

### 1. The new load order

```latex
% deck (unchanged apart from the missing \usetheme line)
\documentclass[aspectratio=169]{beamer}
\makeatletter\def\input@path{{../}}\makeatother
\graphicspath{{../}}
\input{SlideMage_template_uni-ibk}

% template: SlideMage_template_uni-ibk.tex
% SlideMage template name: University of Innsbruck
\newcommand{\SMLayoutProfile}{fira}          % optional; fira is the default
%\newcommand{\SMDarkMode}{}               % optional, as today
\input{SlideMage_setup}                   % profile, theme, every hook with its default
\definecolor{c_primary_dark}{HTML}{...}   % ... colors as today
\renewcommand{\SMInstituteLogoPath}{schemes/scheme_uni_ibk/Logo_Uni_Innsbruck-cropped.pdf}
\setlength{\SMLogoHeight}{3ex}
\setlength{\SMFrametitleRightPadding}{0.28cm}
\renewcommand{\SMTitleBoxColor}{c_secondary_blue}
\setlength{\SMTitleframeBoxHeight}{170pt} % any hook from the catalog
\input{SlideMage_base}                    % derives, then defines everything else
\input{SlideMage_project_macros}          % optional, as today
```

The rules a template author follows:

1. Things chosen before `SlideMage_setup`: `\SMLayoutProfile` and `\SMDarkMode`. Both decide which defaults setup
   computes.
2. Between setup and base: `\setlength`/`\renewcommand`/`\definecolor`/`\colorlet` on catalog names only. All of
   them exist already, so a typo is an error (`\renewcommand` of an undefined name) instead of a silent no-op.
3. After base: additions only (dark-mode beamer colors, bibliography format, project macros).

`SlideMage_setup.tex` (new, in `latex/`) does this, in order:

1. `\providecommand{\SMLayoutProfile}{fira}`, then `\input{SlideMage_layout_\SMLayoutProfile}`, with a clear
   `\PackageError` naming the available profiles when the file is missing.
2. `\usetheme{SlideMage}` (section 3).
3. **The hook catalog**: every template-settable name with its default and a one-line comment. These are lengths
   (`\newlength` + `\setlength`), macros (`\newcommand`) and colors (`\definecolor`, including a default palette,
   the SlideMage one). The catalog is the documentation, and its file is the one place a template author reads.
   Values in `ex`/`em` are evaluated here, in the profile's font, so they keep today's meaning.

Base then:

- computes every derived value from the hooks (`\SMTitleframeBoxWidth`, `\SMLogoWidth`,
  `\SMContentBottomAlign`, the theme's frametitle/paperheight temporaries, ...), so template values propagate
- and never `\setlength`s a hook.

Theme computations that depend on hooks and run at load today (outer:773/788, the `\gotham@temp@...` lengths)
move to base or to the point of use.

`\gothamset{background=light}` has to run after the color definitions today (base:345). In the own theme the
color roles are assigned in base, after the template, the same way.

### 2. The hook catalog: what is a hook, what is not

Every length and number now hardcoded in base and the theme goes into exactly one class:

| Class | Lives in | Template may change it | Examples (initial assignment; step 5 completes and verifies it) |
|---|---|---|---|
| Design hook | setup catalog | yes | logo path and height; frametitle top/bottom/left/right padding; title, footer and bullet colors; title-frame box height, text sep, band gap, bottom pad; section-frame box height; quote box height and attribution gap; footer box height; side-footnote width; block side margin and title-marker width; progress-strip height; text margins (.45cm); list spacing ratios; image border width; Top Margin (41.58pt); text sizes of footer, slide id, footnotes, code, block titles |
| Font metric | layout profile | no, it picks a profile | font files and weight mapping; ascender ratio (0.935); line-box top strut; code/inline-code fonts and scale; card heading font; math-font handling; `\parskip`, `\linespread` (`\SMParskip`, `\SMLinespread`; user decision 2026-10-27, they are not hooks); each calibration that stays font-dependent after step 5 |
| Derived | base | no (follows its inputs) | title-frame box width, logo width, content bottom, section-frame true bottom, left margin (= frametitle left padding + strut, today 12.55pt) |
| Internal | base or theme, private `\SM@...` | no | struts, temporaries, bookkeeping |
| Obsolete | deleted | n/a | calibrations the automatic Top Margin already corrects; prove each with a pixel-identical render before deleting |

The current public names stay where a slide or template reads them, so slides that use `\SMContentTopAlign` or
`\SMFooterBoxHeight` keep working. Theme names templates need get `SM` names (section 3).

### 3. The own theme: `SlideMage`, a pruned and renamed Gotham fork

- **Name.** `\usetheme{SlideMage}`, file `latex/beamerthemeSlideMage.sty`. Use one file with sections
  (colors, fonts, inner, outer) rather than five, since the live part is small. Only `SlideMage_setup.tex` loads
  it.
- **Content.** Only the live behaviour listed under "Today", plus three optional features the user chose to keep
  (2026-10-25; see below). Fixed configuration, no `\gothamset` keys. Drop everything else: the title-page
  variants, TOC templates and automatic TOC frames, side strips and edging, rotated footer, section headline,
  round logo, the subnewline frametitle, the continuation-title variants, frame-numbering styles (circle
  included; `numbering=none` stays), the `standin` frame, the dark, red and transparent colorsets and block
  styles, the title/heading format and shape switches, `\gothamreset`, the non-Lua branches and the
  section/subsection tikz styles that could collide. Base keeps compiling only under LuaLaTeX, as today.
- **Kept optional features**, renamed like everything else but otherwise as they are, and off by default so
  nothing changes visibly:
  - mini-frames (outer:723-1500 or so)
  - progress bars (outer:~1500-2163)
  - automatic part/section/subsection divider slides with all their looks (inner:966-1590: simple,
    progressbar, splitvert, progressvert), which `sectionframe default=false` and `subsectionframe
    default=false` keep off today
  - the watermark background (inner:420-545)

  Their `\gothamset` keys (`mini frames ...`, `progressbar ...`, `partframe/sectionframe/... template` and
  `default`, `watermark template/default`) go; a template turns a feature on with catalog hooks or
  `\setbeamertemplate` instead. Decide the exact switches in step 2, and add one manual slide showing how to
  enable each. Mini-frames, progress bars and divider slides read the `\part`/`\section`/`\subsection`
  structure, so check what they show in a SlideMage deck and how divider slides interact with SlideMage's own
  `\sectionframe`, slide ids and reveal steps before documenting them. In step 7 the stress-test template turns
  all of them on, so they keep compiling.
- **Fonts move out of the theme into the layout profile** (section 4). The theme sets sizes only.
- **Identifiers.** Rename every `\gotham...`/`\gotham@...` the theme defines to `\SM...`/`\SM@...`. Lengths
  templates or slides use get the clearer names below. Fix the "pading" spelling while renaming.

  | Old | New |
  |---|---|
  | `\gothamFrametitleRightpading` | `\SMFrametitleRightPadding` |
  | `\gothamFrametitleLeftpading` | `\SMFrametitleLeftPadding` |
  | `\gothamFrametitleToppading` | `\SMFrametitleTopPadding` |
  | `\gothamFrametitleBottompading` | `\SMFrametitleBottomPadding` |
  | `\gothamFootlineVOffset` | `\SMFootlineVOffset` |
  | `\gothamInstituteLogoSquare` | `\SMInstituteLogo` |
  | `\gothamFrameSubtitleSep`, `\gothamFramesubtitleStrutend` | `\SMFrameSubtitleSep`, `\SMFrameSubtitleStrutEnd` |
  | `\gotham@frametitlestrut@start/@end` | `\SM@frametitlestrut@start/@end` |

  The complete table goes into `sm_rename.py` as a second mapping, `THEME_RENAMES`, together with the content
  names below. The compat migration uses it for project files.
- **Rename the lowercase project names too, with no aliases.** They are SlideMage's own content API, in hundreds
  of slides, but they carry Gotham's name.

  **Naming rule (user, 2026-10-25): every SlideMage name starts with an uppercase `SM`, never `sm`.** That
  already holds for the macros (`\SM...`), the counter `SMUnderbraceCounter` and the tikz styles `SMCard`,
  `SMImageBorder` and `SMProcess`, and it now holds for environments, counters, tikz styles, beamer templates,
  csnames and expl3 variables too. After `SM` comes CamelCase, as in the existing names. Mapping approved by the user on 2026-10-26 (the list below is the approved one; it is also `sm_rename.THEME_RENAMES`); show
  the user the full list before step 2 and use their spelling if they change it:

  | Old | New |
  |---|---|
  | `gothamtable` | `SMTable` |
  | `gothamfloatingblock`, `gothamfloatinginfoblock`, `gothamfloatingexampleblock` | `SMFloatingBlock`, `SMFloatingInfoBlock`, `SMFloatingExampleBlock` |
  | `gothamalphaitemize`, `gothamnumitemize`, `gothamalphaperioditemize`, `gothamnumperioditemize` | `SMAlphaItemize`, `SMNumItemize`, `SMAlphaPeriodItemize`, `SMNumPeriodItemize` |
  | counters `gothamalphaitem`, `gothamnumitem`, `gothamalphaperioditem`, `gothamnumperioditem` | `SMAlphaItemCounter`, `SMNumItemCounter`, `SMAlphaPeriodItemCounter`, `SMNumPeriodItemCounter` (the macros `\SMAlphaItem` etc. exist already as labels, so the counters take a `Counter` suffix; approved 2026-10-26) |
  | `gothamtightflalign*` | `SMTightFlalign*` |
  | tikz styles `gotham arrow`, `gotham highlight`, `gotham dotted highlight` | `SMArrow`, `SMHighlight`, `SMDottedHighlight` |
  | beamer templates `gothampresenter`, `gothamfn`, `gotham plain enumerate`, `gotham_no_inline_logo` | `SMPresenter`, `SMFootnote`, `SMPlainEnumerate`, `SMNoInlineLogo` |
  | internal csnames `\gothamtable@spec`, `@gap`, `@begin`; pgfkeys `/gothamcorner`, `/gothamfit`; TikZ coordinates and nodes `gothamfit@top`, `@bl`, `@r`, `gothamfit<n>` | `\SMTable@spec`, `@gap`, `@begin`; `/SMCorner`, `/SMFit`; `SMFit@top`, `@bl`, `@r`, `SMFit<n>` |
  | `\gotham@block` (the theme's own, not a content name) | `\SM@block`, in step 2b with the theme |
  | expl3 `\g_gotham_footnote_symbols_seq` | `\g_SM_footnote_symbols_seq` (expl3 syntax keeps the `\g_`/`\l_` scope prefix; the module part is `SM`) |
  | Lua globals `gothamalt`, `gotham_layout`, `gotham_list_has_no_visible_box`; callback "gotham top margin"; Python `_GOTHAMTABLE_RE` | `slidemage_alt`, `slidemage_measure`, `slidemage_list_has_no_visible_box`; "slidemage top margin"; `_SMTABLE_RE` |

  Lua is not TeX and keeps Lua's own lowercase convention: the global `gotham_layout` becomes `slidemage_measure`
  (matching `SlideMage_measure.lua`) and the callback "gotham top margin" becomes "slidemage top margin".

  The table above is from a grep of base and the Lua files on 2026-10-25 (`gothamalt` 47×, `gothamtable` 40×,
  `gotham_layout` 36×, ...). Redo the grep across `latex/`, `example/`, `src/`, `tests/` and `tools/` and complete
  it under the same rule. Check the new names for collisions with packages SlideMage loads (verify with a
  compile). The app code that matches these names must match the new spelling exactly, since environment names
  are case-sensitive.

  The app code that names these environments changes in the same step: `latex_lint.py`, `transcript.py`
  (`_BLOCK_ENVIRONMENTS`, `_TABLE_SPEC_ARGS`, the itemize map), `latex_edit.py`, `slide_import.py`,
  `course_schedule.py`, `ai/guides.py`, `preview_equivalence.py` (`_SOURCE_SAFE`), and the AI assistant's tool
  descriptions.

  After the migration, no `gotham` identifier is left anywhere outside history and the compat mapping.
- **Consolidation (a separate step after the pruning).** Where base replaces a theme part (footer, block
  templates, itemize items, footnote template, TOC, logo macro, frametitle hooks, text margins, button and
  footnote colors), the final definition moves into the theme and the dead original goes. That leaves one
  definition per thing. Base also loads explicitly what it uses: fontspec, calc, iftex, xcolor, tikz and xfp.
- **LPPL.** The fork is a modified LPPL work and must:
  - keep Noël's copyright notice
  - say clearly in its header that it is a modified version, derived from beamertheme-gotham v1.2.5.a
  - list the changes in a change section in the file
  - point to the unmodified original (https://gitlab.com/RomainNOEL/beamertheme-gotham, the URL in README.md:4)
  - not use Gotham's file names, which renaming handles
  - not suggest Noël maintains it

  Read `lppl.txt` from the TeX distribution and confirm these points before committing; the list above is from
  memory of LPPL 1.3c §6. Also update:
  - `latex/LICENSE` (drop "shipped unchanged", describe the fork)
  - `REUSE.toml` (new file: LPPL-1.3c, both copyrights; drop the gotham entries)
  - the third-party notices (`tools/third_party_notices.py`)

  Then remove `gotham.dtx`, `gotham.ins`, the five `.sty` files and the `gotham-*.pdf` files nothing uses
  (grep first: `gotham-logo.pdf` is mentioned in template comments).
- **No shim named `beamerthemegotham.sty`.** That would pass a non-Gotham file off under Gotham's file name.
  An un-migrated deck fails with "file beamerthemegotham.sty not found" once the project's framework copy has
  dropped the files; Project compatibility (section 6) fixes it when the project is opened. Base should also
  detect a missing `\SMSetupLoaded` and stop with a `\PackageError` that says what to change.

### 4. Layout profiles

`latex/SlideMage_layout_<name>.tex`. A project may add its own next to its templates; the TeX search path finds
it. A profile:

- loads the fonts: `fontspec` with `no-math`, the sans with its weight mapping (today Light regular, LightItalic,
  Regular as "bold", Italic as bold italic), mono, `\SMCodeFont`, `\SMInlineCodeFont` (scale 0.9, TeX ligatures
  off), `\SMCardHeadingFont`/medium weight, the monospaced numbers in tabular, and the onlymath serif handling
  (base:40-79)
- defines the metrics the framework needs:
  - `\SMFontAscender` (0.935 for Fira Sans Light): base builds `\SMLineTop` from it, and setup hands it, with
    the Top Margin hook, to Lua (`slidemage_measure.configure{top_margin_bp=..., ascender=...}`) in place of the
    two Lua constants
  - default `\linespread` and `\parskip`
  - every calibration that step 5 finds is still font-dependent

**Derive instead of storing, where possible.** The ascender should come from the loaded font: luaotfload keeps
the OpenType metrics on the font table. Find the field (hhea/OS/2 ascender and units per em) and check that it
gives 0.935±0.002 for FiraSans-Light. If it does, the profile's value becomes a fallback. If it doesn't, keep the
profile value. A calibration that can be written as an expression in `\fontcharht`, `\ht\strutbox`,
`\dp\strutbox`, ex or em becomes that expression in base; only what can't stays a profile number.

Ship two profiles:

- `fira` (today's look, the default)
- `lmsans` (Latin Modern Sans: in every TeX distribution, so it also works without Fira). This is the proof
  that the mechanism works, built in step 7.

**Recipe for a new profile**, documented in the catalog's header and in README:

1. Copy `fira` and change the fonts.
2. Compile the calibration deck (step 7) with a test template that uses the profile.
3. Run `tools/check_layout.py` on it.
4. Adjust the profile's numbers until the report is clean.

`tools/calibrate_font_profile.py` (step 7) prints suggested values from that same measurement.

### 5. Consumers that must follow the effective values

- `tools/check_layout.py`: read the margins from the PDF. Base writes `SMTopMargin`/`SMLeftMargin` (pt) as
  custom PDF info keys through `\hypersetup{pdfinfo={...}}`; the tool reads them with PyMuPDF and falls back to
  today's constants.
- `appendix_toc.py:43`: `\SMFrametitleRightPadding`.
- `latex_export.py`: the profile file's name is built from a macro, which the export's token scan can't see.
  Read `\SMLayoutProfile` from the template (or default to `fira`) and add that file. Test it.
- `deck_snapshot.py`: records the files a compile read, so it needs no change. Check its tests.
- `preview_equivalence.py`:
  - the `\usetheme` rule (require none)
  - `AUDITED_GENERIC_PREAMBLE`
  - `AUDITED_FRAMEWORK` (new file list: setup, theme, profiles)
  - `AUDITED_PROJECT_TEMPLATES` (template hashes change)

  Follow `docs/PREVIEW_RENDER_EQUIVALENCE_CONTRACT.md` for what a re-audit means. The setup catalog contains no
  view-dependent rule, so the audit is about proving that.
- `deck_new.DECK_TEXT`, `slide_preview` (generic preamble), `update_all_previews._preamble_for`,
  `tools/preview_benchmark/views.py`: no `\usetheme` line.
- `sm_rename.THEME_NAMES`: becomes the list of old names `THEME_RENAMES` maps.
- `bundled_copies.py`: needs no change. New framework files are added to projects; the removed Gotham files are
  removed where unchanged. Check that a project that edited a Gotham file ends up "kept" without breaking.
- AI guides (`ai/guides.py`) and the assistant's knowledge of framework names: grep for theme names.

### 6. Project compatibility

One `compat.Change` per breaking step, with `detect` and an idempotent `migrate`, as `compat.py` requires. Every
step announces itself as BREAKING in CHANGELOG.md.

- **Step 1** (`slidemage-names-and-setup-layer`, BREAKS):
  - files: rename the project's `Slidemaster_preamble_<key>.tex` → `SlideMage_template_<key>.tex`,
    `Slidemaster_project_macros.tex` → `SlideMage_project_macros.tex`, `Slidemaster.bib` → `SlideMage.bib`
    (section 0). The migration returns new bytes per file, so check whether `compat.run_update` can rename files;
    if it can't, extend it (back up the old file, write the new one, remove the old one, all or nothing).
  - decks: remove `\usetheme{gotham}`; `\input{Slidemaster_preamble_<key>}` → `\input{SlideMage_template_<key>}`;
    a `\SMUseBibliography[Slidemaster.bib]` or `\addbibresource{Slidemaster.bib}` follows the file rename
  - templates: `\input{Slidemaster_preamble_base}` → `\input{SlideMage_base}`,
    `\input{Slidemaster_project_macros}` → `\input{SlideMage_project_macros}`; insert `\input{SlideMage_setup}`
    before their colors (or after a leading `\SMLayoutProfile` or `\SMDarkMode` line);
    `\newlength{\SMLogoHeight}`+`\setlength` → `\setlength`; `\newcommand{\SMInstituteLogoPath}` and the color
    macros → `\renewcommand`
  - project settings that store a template key keep working (keys are unchanged); anything that stores a file
    name (`.slidemage/` JSON, `.latexmkrc`) is checked and migrated
  - a template with anything the migration doesn't recognise is reported, not rewritten
- **Step 2** (`own-theme-and-content-names`, BREAKS): rename the theme identifiers *and* the lowercase content
  names (section 3) in slides, snippets, decks, templates and project macros with `THEME_RENAMES`. Use
  `sm_rename`'s identifier machinery, which also handles `\csname`, tikz style names and Lua strings. Frozen slide
  versions (`*-v1-0-0.tex`) are migrated too, or they stop compiling. Check with the user whether that is
  acceptable for "never touched again" snapshots (it is the same rule the 2026-10-01 gotham→SM rename followed;
  check what it did).

Both have to work on the real project `D:\uniCLOUD\Slidemaster`, which finds the framework through
`../SlideMage/latex`. **Every framework change on the develop branch reaches that project at its next compile.**
So:

- do the work on a feature branch
- before merging each breaking step, run its migration on a *copy* of that project, compile all its decks in all
  versions and compare the renders against the baseline
- tell the user what the migration will change in their real project before merging

### 7. Bibliography (small, independent)

Keep the design (the template owns the citation format) and remove the copying:

- the house format moves to `latex/SlideMage_bibliography_default.tex`, and a template that wants it says
  `\input{SlideMage_bibliography_default}` after base
- `bibliography_house.BLOCK` becomes that one line (keep the full text for detection)
- `compat_bibliography`:
  - its "template defines the house format" check accepts the line or the full copy
  - `migrate` inserts the line
  - an optional detector offers to shorten project templates that carry the full copy
- `test_bibliography_template.py` follows

Base keeps stock defaults.

### 8. Theme packages for the catalogue

Decided by the user on 2026-10-27: themes are offered through the same catalogue as plugins
(`https://slidemage.org/plugins/index.json`, a top-level `"themes"` list beside `"plugins"`, `[[theme]]` entries in
the website's registry), with the same release, approval, pinning and SHA-256 rules, and the app installs them
through the plugin installer. The catalogue cannot list themes until this redesign defines what a theme package
is. Context: `docs/Handover_2026-10-26-Website-Session.md` (section 2) and `docs/Handover_2026-10-27-Website-To-App.md`
(section 5), both on develop's working tree; the plugin package is in `docs/PLUGINS_PLAN.md` section 2.1.

- **Word clash:** a catalogue "theme" is what this plan calls a *template* (the institution layer:
  `SlideMage_template_<key>.tex` plus its scheme folder), not a beamer theme. `beamerthemeSlideMage.sty` is
  framework and never ships separately. Say so in the definition and on the website.
- **Constraint on steps 4-7:** a template must stay self-contained so it can be packaged: one template file, its
  `schemes/scheme_<key>/` folder, and at most its own layout profile file. Nothing of it may assume it sits in the
  project root, and nothing in `latex/` may name a particular institution.
- **Proposal, to settle by step 16 at the latest** (user decision):
  - Files: `theme.toml` (id = template key, name, version, `requires_slidemage`, summary, author, homepage,
    license, layout profile used), `SlideMage_template_<key>.tex`, `schemes/scheme_<key>/`, optional
    `SlideMage_layout_<name>.tex`, `preview.png` for the catalogue, LICENSE, README.md, CHANGELOG.md.
  - Release asset: a zip `<key>-<version>.smtheme` on the theme repository's GitHub release; the manifest
    differs from `plugin.toml` (no `api_version`, `needs` or `network`, since a theme runs no Python).
  - Installed unpacked in `config_dir()/themes/<key>/`. SlideMage puts that folder on `TEXINPUTS` for every
    compile and preview, so it is offered like a bundled template and a project uses it by choosing its key, as
    today. A project copy of the same key wins (as project templates do now), which also lets a user freeze it.
- **Then report the definition to the website side**, which adds `"themes"` to the schema, the builder and the
  pages. The institution templates leaving the repository in step 16 are packaged first (step 17), but they are
  private and never listed (below).
- **What the website side settled on 2026-10-27** (`docs/Handover_2026-10-27-Website-To-App.md`), which a theme
  package inherits:
  - Catalogue URL `https://slidemage.org/plugins/index.json` (final; hard-code it), test catalogue
    `https://slidemage.org/plugins/index-test.json`, pages under `https://slidemage.org/plugins/`. Never the old
    `stpalan.github.io` address.
  - `"themes"` is an optional top-level field, so `schema` stays 1. The catalogue client ignores unknown top-level
    fields, so an app released before themes keeps working once they appear. Schema: copy
    `schema/plugins-index.schema.json` from `stpalan/slidemage-website` (its `$id` is
    `https://slidemage.org/schema/plugins-index-1.json`), not from a handover.
  - A release must carry `README.md` and `CHANGELOG.md` at its tag, or the builder refuses it. An optional
    `.sha256` asset uses the `sha256sum` format (`<64 hex>  <file name>`). Compiled files (`.pyc .pyo .so .pyd .dll
    .dylib .exe`) in the asset refuse the release; a theme has none. Icon: `website/icon.svg` (no scripts, event
    handlers, `javascript:` or `foreignObject`) or `website/icon.png`, square, at least 128 px; for a theme,
    `preview.png` is the natural source.
  - The app installs what the catalogue pins (version, URL, SHA-256), **never a repository's "latest release"**:
    GitHub can mark a broken or withdrawn release "Latest".
  - Registry key `hidden: true` puts an entry only into `index-test.json`, with no page. The id `submit` is
    reserved.
  - The plugin rule "package folder = id with hyphens as underscores" exists because a plugin is a Python
    package. A theme is not imported, so its id stays the template key, hyphens and all (`uni-graz`).
  - A theme template repository, like `stpalan/slidemage-plugin-template` for plugins, is worth offering once the
    package is defined; tell the website side if one is made.
- **Private themes stay out of the catalogue.** A theme carrying a university's logo and corporate design is not
  ours to publish. Its repository is private, so the catalogue builder could not download its asset, and
  `hidden: true` would still publish its URL in the test catalogue. SlideMage installs such a theme **directly
  from its private GitHub repository, with the user's own token, and offers its updates** (user decision
  2026-10-27):
  - **Token:** the GitHub token SlideMage already keeps for its own updates (`updater.py`: Settings → General,
    stored as `github_token` in `config_dir()`, never in a project; `$SLIDEMAGE_GITHUB_TOKEN` wins). It needs
    read access to the theme repository's releases: for a fine-grained token, Repository permissions → Contents:
    Read-only, with the theme repository among its selected repositories. One token covers SlideMage and all of a
    user's theme repositories; no second token setting.
  - **Catch, to check against GitHub's documentation at step 17:** as far as known, a fine-grained token can only
    reach repositories owned by one user or organization that the token's owner selects, and not a personal
    repository of someone else where they are only a collaborator. If that holds, Jürgen could not read
    `stpalan/slidemage-theme-uni-graz` with a fine-grained token; only a classic token with the broad `repo` scope
    would work, which grants write access to all of his repositories. The clean way: keep the private theme
    repositories in a GitHub organization, e.g. `slidemage-themes`, and give Jürgen read access to the Graz
    repository there. He then makes a fine-grained token with that organization as its resource owner. The
    organization may have to allow or approve fine-grained tokens. Settle this before creating the repository.
  - **Adding a theme:** Settings → Themes → "Add theme from GitHub…" takes `owner/name`. SlideMage lists the
    repository's releases through the API (`/repos/{owner}/{name}/releases`, never `/releases/latest`, for the
    same reason as the catalogue rule above) and installs the newest **eligible** one. Eligible means: published,
    not a draft or pre-release, carrying `<key>-<version>.smtheme` and its `.sha256`, the download matching that
    hash, its `theme.toml` version equal to the tag, and `requires_slidemage` satisfied. A release the owner
    withdraws (deleted, or turned into a pre-release) is no longer eligible. The SHA-256 here only guards against a
    damaged download; trust comes from the user choosing the repository.
  - **Where it comes from:** the install records its source next to the theme
    (`config_dir()/themes/<key>/source.json`: repository, version, release id, installed at). A theme installed from
    the catalogue records the catalogue instead, and one installed from a file records nothing and is never updated.
  - **Updates:** at start, at the app updater's cadence and under its update setting (no network when updates
    are off), SlideMage checks each GitHub-sourced theme for a newer eligible release. It offers it with the
    release's notes: Install now / Not now / Skip this version. It never installs one silently. A higher major
    version (a theme's breaking change) says so. Installing re-renders previews only of decks that use the key.
  - **Failures stay quiet and harmless:** no token, an expired token, lost access or no network leave the installed
    version working. Settings → Themes shows why the check failed, worded like the updater's messages (404 = no
    access or no release; 401/403 = token refused, with the permission it needs).
  - **"Install from file…"** (`docs/PLUGINS_PLAN.md`, Phase 1) also accepts a `.smtheme`, for offline use or a
    theme mailed around. It runs the same package checks (valid `theme.toml`, no files outside the package, a key
    that does not shadow a bundled template) and is never updated.
  - **A project's own copy of the template still wins** (section 8 above), so a project can freeze a version.

## Steps

Each step is one commit, or a few, with:

- the `VERSION_NUMBER` bump and a CHANGELOG entry: format `vX.Y.Z (date, reason): ...`, no parentheses inside
  the reason; check it with `packaging/release_notes.py`
- tests: `C:/Users/ms/SlideMage/venv/Scripts/python.exe -m pytest tests -n auto`, with `PYTHONPATH` set to the
  worktree's `src` in a worktree
- the regression check from step 0, which must be pixel-identical unless the step says otherwise
- `tools/check_layout.py` clean on the manual

Before starting, make sure the working tree is clean. On 2026-10-23 it had uncommitted work in ~35 files; don't
mix it in.

0. **Regression harness and baselines.**
   - See whether `tools/preview_benchmark/compare.py` can do this; otherwise add `tools/framework_regression.py`.
   - It compiles a list of decks in all three versions, renders every page with PyMuPDF at a fixed resolution,
     and stores per-page hashes plus the PDF font list. A later run diffs against them and writes diff images.
   - Decks:
     - the manual and the example decks, under the slidemage and uni-graz templates
     - a copy of the real project's decks under mci, uni-ibk and uni-graz, kept outside the repository (the
       content is private)
   - Record the baseline from the current develop branch.
1. **SlideMage names, setup layer and hook catalog, Gotham still underneath.**
   - Rename the framework files (section 0) and everything that names them: `slide_snapshot.py` (prefix, regex,
     `framework_dirs`, `$SLIDEMAGE_LATEX`), `project.py` (`$SLIDEMAGE_PROJECT`), `.latexmkrc` files,
     `packaging/slidemage.spec` if it names files, REUSE.toml, the bibliography and compat modules, tests, tools,
     current docs and comments.
   - Add `SlideMage_setup.tex`, which loads Gotham itself (`\usetheme{gotham}`) and the font setup that is
     there today, then the catalog.
   - The catalog starts with today's template names plus the theme lengths templates use, under their new `SM`
     names as `\let` aliases of the Gotham registers. Base no longer defines or sets any name the catalog
     owns.
   - Restructure the shipped templates. Decks lose `\usetheme`, and so do the app's generated preambles, the
     preview-equivalence rule and the tests.
   - Compat change `slidemage-names-and-setup-layer`. Pixel-identical.
2. **Own theme, pruned and renamed; content names renamed.**
   - Add `beamerthemeSlideMage.sty` with only the live code, the `SM` names, the LPPL header and the change
     list. Setup loads it instead of Gotham.
   - Rename the lowercase content names (section 3) in the framework, the example project, the app code and the
     tests. The Lua global becomes `slidemage_measure`.
   - Fonts still load where they do today, now in the new theme, until step 4.
   - Remove the Gotham files; update LICENSE, REUSE.toml, the third-party notices, `sm_rename` and
     `appendix_toc`.
   - Slide 1gr, the snippets and every example slide use the new names. Compat change
     `own-theme-and-content-names`. Pixel-identical, with the same fonts in the PDF. Afterwards a grep for
     `gotham` finds only history, LICENSE/attribution text and the compat mapping.
   - **Done 2026-10-26 (v10.1.0), notes for the later steps:**
     - `latex/beamerthemeSlideMage.sty` is one file (2214 lines against 5626). Its kept features are switched by
       `\SMMiniFramesPosition`, `\SMProgressBarPosition`, `\SMDividerFrames`/`\SMDividerLook` and
       `\SMWatermarkDefault` (and siblings), documented at the end of `SlideMage_setup.tex`; the patches mini frames
       apply to beamer's navigation are installed only when they are used. Round logo and circle bar were dropped
       with the rest.
     - Colour roles are `\SMColorA`..`E`, `\SMColorDark`, `\SMColorFG` ...; base calls `\SMApplyColorRoles` where it
       called `\gothamset{background=light}`.
     - Gotham's title/section patches of beamer's commands went with the format switches. Their one visible trace was
       `\gotham@subsectiontitleformat` in `.aux` files (`\SMAgendaSubsection`); base keeps that name as a no-op.
     - Gotham's footline called `\usebeamerfont{pagenumberinhead/foot}` (spaces lost under expl3 syntax), a font that
       does not exist; the call is gone, nothing changed.
     - `sm_rename.THEME_RENAMES` holds the surviving theme names, `THEME_REMOVED` the rest (reported by the compat
       change, `\gothamset` included). `bundled_copies` reports a dropped Gotham file the project changed as kept.
     - The manual still says "Gotham theme" on slide 1ym and in `media/alt-text.json`: step 15 (was 9), since changing it
       changes the render.
3. **Consolidation.**
   - Base's replacements of theme parts move into the theme as their only definition.
   - Base loads its packages explicitly.
   - Load-time computations that depend on hooks move to base or to the point of use.
   - Pixel-identical. Not breaking.
   - **Done 2026-10-27 (v10.2.0), notes for the later steps:**
     - Moved into `beamerthemeSlideMage.sty` (base 6998 → 5712 lines, theme 2213 → 3467): the colours of footnote,
       footline text, buttons, canvas, frame title text and blocks (block, alerted, example, reference, info; the
       theme's own native-block colours and `alertedBlock`/`example text` are gone); the text margins; `\SMBulletDot`
       as the `itemize item/subitem/subsubitem/subsubsubitem` template (no longer set at the start of every
       `standardframe`; a bare `\begin{frame}` now gets SlideMage's bullet too, approved by the user on 2026-10-27 with before/after images); `\SMInstituteLogo`, `\SMInstituteLogoGraphic`,
       `\SMFrametitleHookCode`, `\chapterlogo` with `\SMChapterLogoPath`, `\SMFrametitleFullHeightYellow`,
       `\SMFrametitleLogoFixed`, `\SMFooterBoxColor`, the `SMNoInlineLogo` template and `\SMLogoWidth` (the length);
       `\SMFooterBoxHeight` and the footer box; the footnote template `SMFootnote`, the symbols, `\sidefootnotes` and the
       side-footnote lengths and strip; the six block templates with `\SMBlockSideMargin`, `\SMBlockTitleMarkerWidth`,
       `\SMBlockTitleWithMarker`, `\SMSetBlockBullets`, `\SMBulletDotBlack`, `\SMAlertMarker`; `SMPlainEnumerate`.
     - The theme is expl3 syntax, so the moved code sits between `\ExplSyntaxOff` and `\ExplSyntaxOn` and is the base's
       text unchanged (its `\makeatletter` pairs dropped, `@` is a letter in a package).
     - `beamer` colours are read when used, so `\setbeamercolor{footline}{fg=\SMFooterTextColor}` and the like are plain
       theme-load code. Only the `\colorlet`s are eager: `\SMApplyColorRoles` (public, called by the base after the
       template) sets `SMColorDark` from `c_primary_dark`, `SMColorA` from `\SMTitleBoxColor` and the canvas default, then
       runs the roles; the theme runs the internal `\__SM_apply_color_roles:` alone at load.
     - The patches on the `frametitle` and `footline` templates (logo hook, footer box, side-footnote strip) are applied by
       `\SM@patchTemplates`, at the end of the theme and again at the end of `\__SM_nav_apply:`. Folding them into the template
       would have put them after the mini frames and the progress bar. Checked with a deck that switches mini frames,
       progress bar, divider frames and the watermark on (head/foot/frametitle positions): identical to the old tree.
     - Stays in base: the `frame footer` template, its font and `\ifSMHideFooterText` (the footer carries the deck
       version, and the theme must hold no view-dependent rule: `test_the_pins_are_the_frameworks_files...`), the
       standout patch `\global\SMHideFooterTexttrue`, `\SMLogoWidth`'s `\settowidth` (reads the catalog), the environments
       `referenceblock`, `infoblock`, `definitionblock`, `\source`, the list environments and `\SMBulletWidth`.
     - Base loads `iftex`, `fontspec`, `xcolor`, `etoolbox`, `tikz`; it uses neither `calc` syntax nor `xfp` (the theme does
       and keeps loading both).
     - The theme has no other load-time computation that reads a catalog name. `\SMFootlineHRightOffset` takes `\spaceskip`
       (always 0pt) and is not a hook.
4. **Layout profiles.**
   - Fonts move from the theme into `SlideMage_layout_fira.tex`.
   - `\SMLayoutProfile` takes effect.
   - The ascender and Top Margin go from TeX to Lua; the ascender is derived where luaotfload allows it.
   - `latex_export` finds the profile.
   - Pixel-identical.
   - **Done 2026-10-27 (v10.3.0), notes for the later steps:**
     - `latex/SlideMage_layout_fira.tex` holds, in the old order: the fontspec load with `no-math`, the availability
       check and warnings (moved out of the theme with their `\msg_new` texts), the Fira Sans weight mapping, Fira Mono,
       the tabular figures, then `\SMFontAscender`, `\SMLinespread` and `\SMParskip`, `\SMCodeFont`,
       `\SMInlineCodeFont`, `\SMCardHeadingFont`, and the `onlymath` serif font theme with the `\text` wrapper (all from
       the base). The theme sets sizes only.
     - Load order: setup inputs the profile (`\providecommand{\SMLayoutProfile}{fira}`, `\IfFileExists`, a
       `\PackageError` when missing) right before `\usetheme`. The theme still applies `\parskip` and `\linespread` at its
       old place, now from `\SMParskip` (`0.5em`) and `\SMLinespread` (`1.15`), so the em is evaluated in the same font
       as before. The `\usefonttheme[onlymath]{serif}` and `\text` code ran after the template before and now runs
       before it; the render did not change, but a template that loads a package redefining `\text` is the case to watch.
     - **Ascender.** luaotfload keeps it on the font table: `font.getfont(id).parameters.ascender / size` (the font's
       `metadata.ascender` / `units`, 935 / 1000), which gives 0.935 for FiraSans-Light. The base calls
       `slidemage_measure.derive_ascender()` right after loading the Lua file, inside a group with `\normalfont`
       selected; it rounds to four digits (so the value equals the old literal exactly) and sets `\SMFontAscender`
       globally, so `\SMLineTop` (`\rule{0pt}{\SMFontAscender em}`) follows. The profile's 0.935 is only the fallback
       for a font without that value (a test with a different fallback still gave 0.935).
     - **Top Margin.** New catalog hook `\SMTopMargin`, a macro holding a dimension: `41.58bp` (bp, because Lua measures
       in PDF units). It is not a length on purpose: a `\setlength` would round to scaled points first and shift the
       measured corrections by up to 1e-5 bp; Lua reads a value written as `<number>bp` exactly and sends any other
       unit through `tex.sp`. The base calls `slidemage_measure.configure{top_margin=..., ascender=...}` through
       `\SMLuaOnce` (so a precompiled format replays it) right after loading the Lua file, since the Lua is not loaded
       before that; the Lua constants are gone and a missing `configure` is an error.
     - **For step 5.** `\SMContentTopAlign` is still `41.58pt` while the Top Margin is `41.58bp` (0.17pt apart): they
       are two numbers, not one, so decide whether `\SMContentTopAlign` derives from `\SMTopMargin`. The font-calibrated
       lengths of the inventory were not touched. The theme still requires `ifxetex` and `ifluatex`, which nothing uses.
     - Consumers: `latex_export.PROFILE_RE` reads `\newcommand`/`\renewcommand`/`\def` of `\SMLayoutProfile` in any scanned
       text, falls back to `fira` (a test ties that to setup's `\providecommand`), reports a profile that exists nowhere.
       `deck_snapshot` copies the framework whole and records a project profile as an input (test added); `bundled_copies`
       and `packaging/slidemage.spec` take the new file without a change; `REUSE.toml` covers it by its SPDX header.
       `preview_equivalence` pins `SlideMage_layout_fira.tex`; a project profile of another name is only reachable through
       a template, and a template with an unaudited digest is rendered on its own; a project file named like a pinned
       profile is a shadow. The audit found no view-dependent rule in the profile (the test that guards the theme now
       checks the profile too).
5. **Classify every remaining value.**
   - Go through the inventory (section 2's table; the full list is in the 2026-10-23 inventory, which this
     step redoes against the code as it stands then) and decide each length.
   - Calibrations: try them as 0 under the automatic Top Margin and delete them when the render stays
     identical. Otherwise write them as metric expressions, and only failing that as profile values.
   - Design values become catalog hooks.
   - Pixel-identical. Any intended difference needs the user's approval with before/after images.
   - **Inventory 2026-10-27** (redone against v10.3.0; `b:` = `SlideMage_base.tex`, `t:` = `beamerthemeSlideMage.sty`,
     `s:` = `SlideMage_setup.tex`, `p:` = `SlideMage_layout_fira.tex`, `m:` = `SlideMage_measure.lua`). Classes: **H**
     design hook (catalog, a template may change it), **M** font metric (layout profile, a template cannot change it),
     **D** derived (base, an expression of its inputs), **I** internal (stays where it is), **O** obsolete (try as 0, delete
     if the render stays identical). "Q" marks a value whose class was unclear; it keeps the conservative class and sits
     in the questions for the user. Where a trial decides between two classes the row says so; the result is in the
     "Done" notes below. Two rules shape the table: a value that a slide reads by name (the real project reads
     `\SMContentTopAlign` 319×, `\SMFooterBoxHeight` 89×, `\SMTitleBarBottomAlign` 77×, `\SMMinipageTopCorrection`
     122×, `\SMFlatItemizeTopCorrection` 123×, ...) stays defined under that name whatever its class; and a hook is a
     value, never a piece of code (colours, logo and fonts of the profile are not repeated here).

     | Name | Where | Value | Class | Reason |
     |---|---|---|---|---|
     | `\SMTopMargin` | s:152 | 41.58bp | H | already a hook (step 4) |
     | `\SMLogoHeight`, `\SMInstituteLogoPath`, colour roles | s:118-142 | 3ex, file, names | H | already hooks |
     | `\SMFrametitleTopPadding`, `...BottomPadding`, `...LeftPadding` | t:1128-1135 | 2.2ex each | H | space around the title; plan table. Definition moves from the theme to the catalog |
     | `\SMFrametitleRightPadding` | t:1131, s:160 | 2.2ex, set to 0.28cm in setup | H | same; the theme's 2.2ex default is dead (setup always overrides it), so the catalog holds 0.28cm |
     | `\SMFrameSubtitleStrutEnd`, `\SMFrameSubtitleSep` | t:1147-1151 | 0pt, ` ---~` | H | space/text between title and subtitle; already mentioned in the catalog |
     | `\SMFootlineVOffset` | t:1571, b:2026-2039 | -0.5ex, then +/-1.3, 1.4, 0.4, 0.4, 0.87pt = net -0.77pt | H (Q) | the gap between footnotes and the footer box; the five `\addtolength` lines collapse to one value `-0.5ex-0.77pt` (same sp). Hand-measured against an underlined link at Fira, so it could also be M: kept as a hook, which changes nothing unless a template sets it |
     | `\SMFootlineHeight`, `\SMFootlineDepth` | t:1572-1573 | 1.5ex, 0.1ex | H | footline box |
     | `\SMRightFooterPadding` | t:1575 | 3.5ex | H | gap before the frame number |
     | footline `leftskip`/`rightskip` | t:1583-1584 | 3ex | H | new `\SMFootlineSidePadding` (the footer's inner side padding) |
     | `\SMFootlineHRightOffset` | t:1574 | `\spaceskip` = 0pt | I | always 0pt, not a hook (step 3 said so); dropped from the catalog's list of theme names |
     | `\SMFooterBoxHeight` | t:1629 | 7.26pt | H | plan table; read by slides |
     | `\SMFooterTextDrop` | b:2056 | -0.49pt | M | centres the footer text in the box, measured at Fira (0.14pt above vs 1.12pt below) |
     | `\SMFooterRightShift` | b:2047 | 4.6pt | M (D?) | aligns the frame number with the logo's right edge: font part (3ex, 3.5ex paddings) plus `\SMFrametitleRightPadding`. Trial: express as `RightPadding - c` with c in the profile |
     | footer text size `\fontsize{5}{3}` | b:1984 | 5/3 | H | new `\SMFooterTextSize` (plan table: text size of the footer) |
     | slide-id size `\fontsize{4}{4}` | b:2273 | 4/4 | H | new `\SMFooterIDSize` (plan table: slide id) |
     | footer pieces `\hspace*{2em}`, `-4em`, `\vspace*{0.4ex}` | b:2275-2278 | em/ex | I (Q) | positions of the id and number inside the footer, tuned by eye at Fira; moving them to the profile or the catalog changes no pixel, but it is unclear which they are |
     | footnote size `\fontsize{3.2}{1.9}` (five places) | t:1764, 1773-1776 | 3.2/1.9 | H | new `\SMFootnoteSize` |
     | `\footnotesep` | t:1680 | 3pt | H | new `\SMFootnoteSep` |
     | footnote `\lineskip` | t:1893, 1926 | 0.6pt | I | mechanics of the footnote strut, tied to `\SMFootnoteSize` |
     | `\SMFootnoteRightShift` | t:1797 | 4.8pt | M (D?) | the footnote's right edge against the logo's: same case as `\SMFooterRightShift` |
     | `\SMSideFootnoteHsize` | t:1841 | 207pt | H | plan table: side-footnote width |
     | `\SMSideFootnoteTitleBlockSep`, `\SMSideFootnoteRightInset` (default), `\SMSideFootnoteMarkerShift` | t:1847, 1851, 1865 | 3pt, 2pt, 1.3pt | H | the strip's gap to the title bar / the page edge / the marker |
     | side-footnote offsets `+2.1pt`, `+3.1pt`, `-2.31pt` | b:4742, 5009, 5010 | pt | I (Q) | gap between a side image and its footnote strip; calibrated at Fira, unclear whether design or font |
     | `\SMBlockSideMargin`, `\SMBlockTitleMarkerWidth` | t:2115, 2188 | 4.20pt, 16pt | H | plan table |
     | block box mechanics `colsep*=.75ex`, `\vskip-0.5pt`, `-.25ex`, `-.75ex` (six templates) | t:2262-2475 | | I | the pairs that make a block's title and body meet; part of the template code, not a choice |
     | bullet radius, `\SMBulletDotBlack` 1.7pt, `!` marker 7/7, `\textcircled{\scriptsize i}` | t:2129, 2425, 2311 | | I | glyph geometry |
     | `\SMImageBorderWidth` | b:339 | 2.5pt | H | plan table |
     | `\SMWarningSignPadding`, `...BorderWidth` | b:625-627 | 6pt, 4.5pt | H | look of `\SMWarningSign` |
     | `\SMTallItemBaseRatio` | b:699 | 0.3 | H | list spacing ratio (plan table) |
     | `\SMTightDisplaySkip` | b:766 | 3pt | H | display spacing in a list |
     | `\SMItemizeLevelDropSpaceRatioI-IV` | b:3564-3598 | 0.5, 0.3, 0.2, 0.5 | H | plan table |
     | `\SMItemsepRatioI-IV` | b:3705-3708 | 0.4, 0.24, 0.15, 0.09 | H | plan table |
     | `\SMItemizeLevelOpenSpaceRatioI-III` | b:3770-3772 | 0.02, 0.15, 0.02 | H | plan table |
     | `\SMBesideFigureTopGap` | b:4258 | 0.2em | H | already a macro, documented as a default |
     | `\SMItemStep`, `\SMBulletWidth`, `\leftmargini`-`iv` | b:3207-3215 | measured | D | from the bullet and `\labelsep` |
     | label-item list `\labelsep`, `\labelwidth` (four environments) | b:3095-3096, 3152-3153, 3169-3170, 3186-3187 | 4.75pt, 9.1pt | M | width of "a)" at the small itemize size; four copies become two profile lengths `\SMLabelItemSep`, `\SMLabelItemWidth` |
     | label-item list `\itemsep` (four environments) | b:3126, 3157, 3174, 3191 | 2.5pt | H | `\SMLabelItemItemsep`; a choice (tuned so a boundary reads more open than a wrapped line) |
     | `\SMEnumerateLabelWidth` box, nested enumerate `\labelwidth`/`\labelsep`/`\leftmargin`, `7.85pt` | b:3381, 3485-3493 | 20.33pt, 5.25pt, 13.1pt, 7.85pt | M | numeral widths at Fira; calibrated by measuring; four profile lengths `\SMEnumerateLabelBox`, `...NestedLabelSep`, `...NestedLeftMargin`, `...NestedMinNumber` |
     | `\SMEnumerateTextExtra` | b:3449 | 6.3pt | M | the numeral column of the outer enumerate at Fira |
     | `\SMTocLabelExtraGap` | b:3917 | `\wd` of "0" | D | measured |
     | `\SMContentTopAlign` | b:2489 | 41.58pt | H (Q) | the Top Margin as a coordinate for overlays (corner figures, floating blocks, `\SMFit`); it is 41.58pt while `\SMTopMargin` is 41.58bp, 0.156pt apart, so the two cannot become one without a visible 0.156pt move of every overlay: both stay. Question for the user |
     | `\SMTitleBarBottomAlign` | b:2538 | 25.32pt | H (Q; trial: not derivable exactly) | the bottom edge of the title bar = paddings + title strut + logo; trial: as an expression of the hooks. If it cannot be exact it stays a hook with a note that the paddings are tied to it |
     | `\SMContentBottomAlign` | b:4121 | footer + top align - bar bottom | D | already derived |
     | `\SMContentTopShift` | b:2578 | 11.5964pt | M (trial: not obsolete) | pull-up of every top-aligned frame; the automatic Top Margin measures and corrects it. Still live for frames the measurement does not manage: `sectionframe` (calibrated against it), `\SMManualTopMargin`, `\SMAutoTopMarginfalse`. Trial: 0 with `\SMSectionframeContentDrop` rewritten for the shift |
     | `\SMColumnsTopCorrection`, `\SMColumnsTTopCompensation` | b:2592, 2636 | 10.17pt, 13.76pt | M (trial: live) | only active where the measurement is not (the `[c]` frame, `sectionframe`, manual); trial 0, else profile |
     | `\SMMinipageTopCorrection`, `\SMMinipageWithCornerImageExtraCorrection` | b:2721, 2753 | 9.38pt, 10.35pt | O (M) | read by slides as `\SMReduceContentTopShift{...}`, whose effect the measurement removes. The names stay defined; trial 0, else profile |
     | `\SMSideImageFrameMinipageCorrection` | b:2784, 2803 | 8.2pt, then 6.26pt | O (M) | set twice (the first line is dead); same trial |
     | `\SMFlatItemizeTopCorrection` | b:2840, 2855 | 1.834pt, then 0.01pt | O | set twice (the first is dead); effectively 0 already |
     | `\SMContentTopShiftReduction` and the three `\SM...ContentTopShift` commands | b:2812-2864 | 0pt | I | the plumbing the corrections feed |
     | `\SMFloatingInfoblockRightAlign` | b:4103 | `RightPadding - 3.165pt` | I (Q) | the infoblock's visible edge against the logo; the 3.165pt is a hand-measured constant at Fira with the block margins (4.20pt) in it; unclear whether it derives from `\SMBlockSideMargin` |
     | `\SMFloatingInfoblockTopAlign` | b:4112 | 6.02pt | I (Q) | same case |
     | `\SMTitleframeBoxHeight`, `...TextSep`, `...BandGap`, `...BottomPad` | b:4420, 4427, 4429, 4445 | 187.147pt, 2.5ex, 0.8ex, 41pt | H | plan table. The comment calls the 41pt "empirical", calibrated to 1.5 subtitle lines at Fira, so it could be M; kept as a hook (Q) |
     | `\SMTitleframeBoxWidth`, `\SMSectionframeTitleWidth` | b:4422, 4921 | page - logo - paddings | D | already derived |
     | `\SMSectionframeBoxHeight` | b:4826 | 85.04pt | H | plan table |
     | `\SMSectionframeTrueBoxBottom` | b:4887 | 85.04pt | D | the same number as the box height; becomes `\SMSectionframeBoxHeight` |
     | `\SMSectionframeContentDrop` | b:4824 | 11.5pt | H (O) | text drop under the bar; written against `\SMContentTopShift` (see that row) |
     | `\SMSectionframeRefDepth`, `...BottomGap`, `...BottomPadCorrection`, `...HeightCorrection` | b:4897, 4908, 4910, 4919 | 4.42pt, 14.32pt, 5.58pt, 16.03pt | M | corrections of the section title measurement at Fira (`\strut`, descender) |
     | `\SMSectionframeBarBottom` | b:4951 | 85.14bp | I (Q) | "constant since v5.28.0" for the side figure; 0.42pt below the box height plus ref depth, unclear whether derived |
     | `\SMQuoteBoxHeight`, `\SMQuoteAttributionGap` | b:5055, 5057 | 0.8`\paperheight`, 1.8ex | H | plan table |
     | `\SMProgressStripRoom` | b:5285 | 11.08pt | H | plan table. The strip's node (`text height=6.2pt`, `text depth=2pt`, `inner ysep=1.5pt`, `minimum height=11.19pt`, font 6.3/7.5, `\vspace{-3pt}`, b:5310-5320) stays inside the command (I): it is the strip's font fit |
     | `\SMCodeSize` | b:5336 | 6.6/8.2 | H | plan table: code text size; moves to the catalog |
     | code panel `\fboxsep`, `breakindent` | b:5368, 5379 | 3pt, 1.5em | I | listing mechanics |
     | `\SMChapterAgendaMaxHeight` and `14pt` | b:5460, 5603 | 0pt (auto), 14pt | I | a slide-level knob and the clearance of the auto fit |
     | text margins | t:1124 | .45cm | H | new `\SMTextMarginLeft`, `\SMTextMarginRight`; applied by a theme command that the base calls after the template |
     | `\parskip`, `\linespread` | p:106-107 | 0.5em, 1.15 | M | profile values `\SMParskip`, `\SMLinespread` (user decision 2026-10-27); section 2's table row is corrected |
     | `\SMFontAscender` | p:103 | 0.935 | M | derived from the font; the number is the fallback |
     | optional features: `\SMProgressSectionHeight`, `\SMSectionHOffset`, `\SMProgressHeadFootLineheight`, mini-frame and bar numbers | t:437-3150 | 3pt, 0pt, 1.2ex, ... | I | off by default; the switches and the three lengths the catalog names are the interface, the rest is feature code |
     | `\SMHrefUnderline` thickness 0.2pt, drop `-0.35ex` | b:216-228 | | I | scaled from footnote to body size; mechanics |
     | `\SMTikzmark` `yshift=2pt`, `\SMArrow` tip 2mm, `\SMUnderbrace` amplitude 4pt/raise 1pt/below 6pt, mugshot arc 0.25cm | b:360, 368, 581, 1598-1600 | | I | drawing styles slides use; a template may redefine the tikz style |
     | key defaults of `SMFloatingBlock` (2mm, 1.2mm), `\SMCorner` (`gap=12pt`), `\SMFit` (`gap=6pt`) | b:4011, 4178, 4301 | | I | defaults of command keys, documented at the command |
     | presenter note page (0.3em, 4pt, 3pt, 7pt, 9pt, 0.95, 17.4pt, 30.8pt) | b:2169-2185 | | I | layout of the presenter's note page, not of a slide |
     | zero-size boxes, `inner sep=0pt`, `\tabcolsep` 0pt, `\parindent` 0pt, `\vbox to 0pt` | b, ~140 places | 0pt | I | structure, not values |
     | Lua: `SMALL_PICTURE` 6pt, `MIN_ROOM_PT` 1, `MIN_SIZE` 0.5pt, ratio 0.85, convergence 0.01pt / 0.0005, `MARKER_ID` | m:249-263, 393, 675-679 | | I | thresholds of the measurement algorithm |
     | Lua: top margin and ascender | m | | | gone in step 4 (parameters of `configure`) |
     | Python: `check_layout.py` `TOP_MARGIN = 41.58`, `LEFT_MARGIN = 12.55` | tools | | D | read from the PDF in step 6 |

     Counts (74 rows; a row can hold several names; the class before a bracket): H 34, M 9, D 7, I 19, O 5 (the O rows may
     end as M, see the trials).
   - **Done 2026-10-27 (v10.4.0), notes for the later steps:**
     - **Hooks.** Defined in `SlideMage_setup.tex` after `\usetheme` (the theme and the base no longer define them): text margins `\SMTextMarginLeft/Right`; `\SMFrametitle{Top,Bottom,Left,Right}Padding`, `\SMFrameSubtitleSep`, `\SMFrameSubtitleStrutEnd`; `\SMFooterBoxHeight`, `\SMFooterTextSize`, `\SMFooterIDSize`, `\SMFootlineHeight/Depth/SidePadding`, `\SMRightFooterPadding`, `\SMFootlineVOffset` (default `-0.5ex-0.77pt`: the base's five `\addtolength` lines summed in sp); `\SMFootnoteSize`, `\SMFootnoteSep`, the four `\SMSideFootnote...` lengths; `\SMBlockSideMargin`, `\SMBlockTitleMarkerWidth`; `\SMTitleframe{BoxHeight,TextSep,BandGap,BottomPad}`, `\SMSectionframe{BoxHeight,ContentDrop}`, `\SMQuote{BoxHeight,AttributionGap}`, `\SMProgressStripRoom`; the list ratio macros, `\SMTallItemBaseRatio`, `\SMLabelItemItemsep`, `\SMTightDisplaySkip`, `\SMBesideFigureTopGap`; `\SMImageBorderWidth`, `\SMWarningSign{Padding,BorderWidth}`, `\SMCodeSize`; `\SMContentTopAlign`, `\SMTitleBarBottomAlign`. Block, frametitle, caption and bibliography sizes are beamer fonts: a template uses `\setbeamerfont` after setup (documented in the catalog). The one new name that is not a rename is `\SMFootlineSidePadding`.
     - **Evaluation point.** Hooks in ex/em stay in the preamble's normal font, as before, except `\SMFootlineSidePadding`: the footline template had a literal `3ex` evaluated inside the footline's `\scriptsize`, so it is a macro (`3ex`), not a length. The first compare after the move differed on every page in exactly that (4.6pt on the footer); a numeric dump of every `\SM...` length before and after (in sp) is the fast check for this kind of slip.
     - **`\SMApplyLayoutHooks`.** A template changes hooks after the theme has loaded, so what must reach registers that are not SlideMage's own (`\beamer@leftmargin`, `\footnotesep`, the `footnote` beamer font) is applied by this theme macro, which the base calls right after `\SMApplyColorRoles`. Add anything of that kind there.
     - **Profile.** `SlideMage_layout_fira.tex` gained a 'Calibrations' section: `\SMFooterTextDrop`, `\SMFooterRightShift`, `\SMFootnoteRightShift`, `\SMEnumerateLabelBox/NestedLabelSep/NestedLeftMargin/NestedMinNumber/TextExtra`, `\SMLabelItemWidth/Sep`, `\SMSectionframe{RefDepth,BottomGap,BottomPadCorrection,HeightCorrection}`, `\SMContentTopShift`, `\SMColumnsTopCorrection`, `\SMColumnsTTopCompensation`. A profile for another font (step 7) must define all of them; the catalog header's list of what a profile defines should be extended then.
     - **Calibration trials** (in-repo compare = manual and its copy, two templates, three versions, 72 dpi pixel hashes). (1) `\SMContentTopShift` at 0 with the section divider's drop rewritten: not identical, 11 of 92 pages differ in 3-6 pixels by up to 17 levels. The automatic Top Margin records its correction to 0.001pt, so a different pull-up lands a thousandth elsewhere. Kept (profile). (2) The two column corrections at 0: not identical, a `columns` below a paragraph moves about 10pt down (manual page 3); they are live in frames the measurement does not manage. Kept (profile). (3) `\SMMinipageTopCorrection`, `...WithCornerImageExtraCorrection`, `...SideImageFrameMinipageCorrection`, `\SMFlatItemizeTopCorrection` at 0: no slide of the manual reads them, so the in-repo compare says nothing; the copy of the real project (122 slides read the first, 123 the last, 5274 pages, 48 renders) is identical. Deleted as values, the names stay defined as 0pt for the slides that read them (the base comment says so). (4) `\SMTitleBarBottomAlign` as `TopPadding + totalheight(X) - 0.5 fontcharht(E) + 0.5 LogoHeight` in the frame title font (= 25.3233pt, the measured 25.32pt is 0.0033pt off): not identical, 14-16 pixels at the logo's trim patch on every page and 594 on the appendix thumbnails. Kept as a hook with the number. (5) `\SMFootnoteRightShift` (4.8pt) and `\SMFooterRightShift` (4.6pt) are close to `text margin right - right padding` = 4.837pt (the footer's by a glyph overhang of 0.24pt): not exact, not tried, both stay profile numbers. (6) `\SMSectionframeTrueBoxBottom` is now `\SMSectionframeBoxHeight` (the same 85.04pt).
     - **Not a hook, left in place** (inventory class I, Q): the footer's `2em`/`-4em`/`0.4ex` pieces, the side-footnote offsets `+2.1pt`, `+3.1pt`, `-2.31pt`, `\SMFloatingInfoblockRightAlign` (`RightPadding - 3.165pt`) and `TopAlign` (6.02pt), `\SMSectionframeBarBottom` (85.14bp) and the progress strip's node geometry. They are font-or-design mixtures; see the questions below.
     - **Open for the user.** (a) `\SMContentTopAlign` 41.58pt against `\SMTopMargin` 41.58bp: equal in intent, 0.156pt apart in fact; deriving one from the other moves every overlay figure, floating block and `\SMFit` by 0.156pt (0.05mm, not seen by eye, but not pixel-identical), and would let a template change the Top Margin without re-measuring. Needs a yes, with before/after images if wanted. (b) `\SMTitleBarBottomAlign`: same kind of question, deriving it removes the second hand-kept number but changes 14-16 pixels per page at the logo. (c) Should the footer and footnote right shifts follow `\SMFrametitleRightPadding` (a 0.04pt / 0.24pt visible move on the default look)? (d) Is `\SMFootlineVOffset`'s -0.77pt a design choice (kept as hook) or a font calibration? (e) Is the 41pt `\SMTitleframeBottomPad` a hook (kept) or a Fira calibration?
     - **Consumers.** `appendix_toc.py` reads `\SMTextMarginLeft` where it had `.45cm` (and `\SMFrametitleRightPadding`, as before); `check_layout.py` keeps its constants (step 6 replaces them) with a comment naming the hooks; `ai/guides.py` names none of the moved values. Pins renewed (setup, profile, base, theme); no view-dependent rule entered them.
6. **Effective margins for the tools.** Base writes the PDF info keys; `check_layout.py` reads them.
   - **Done 2026-10-27 (v10.5.0), notes for the later steps:** the keys are `SMTopMargin` (`\SMTopMargin`) and
     `SMLeftMargin` (`\SMFrametitleLeftPadding`: the old constant 12.55 was exactly this length, 12.552bp, the
     strut has no width), in bp rather than the pt section 5 named, because the tool measures in PDF units. Written
     by the base right after `\SMApplyLayoutHooks`; `check_layout.pdf_margins()` reads them and falls back to
     41.58/12.55 for older PDFs. The Right Margin stays measured on the logo. Step 7's stress-test template is the
     first deck whose margins differ; check there that `check_layout.py` is clean against them.
7. **Proof and calibration.**
   - Add the `lmsans` profile.
   - Add a minimal test project, `tests/fixtures/template_stress/` (a `slide_ids.csv`, one deck, a few slides),
     with a test-only template `SlideMage_template_stress-test.tex`. It lives there, not in `example/` or
     `latex/`, so the app never offers it to users. It uses `lmsans` and overrides every catalog hook with
     clearly different values.
   - Add a calibration deck to it that exercises every frame type and list depth.
   - Pass: it compiles, `check_layout.py` is clean against the template's own margins, and a human looks at the
     renders.
   - Add `tools/calibrate_font_profile.py`.
   - Add a test that every catalog hook is used somewhere in base or the theme, and that the shipped templates
     use catalog names only.
   - **Done 2026-10-27 (v10.6.0), notes for the later steps:**
     - **Profile.** `latex/SlideMage_layout_lmsans.tex` ships to users (decision 2026-10-27): Latin Modern Sans (`lmsans10-*.otf`) with its regular and bold, Latin Modern Mono (`lmmono10-regular`, `lmmonolt10-bold`), the same math handling as Fira. It defines every name the Fira profile defines (a test compares the two lists). Its ascender is read from the font: luaotfload gives 0.806 for Latin Modern Sans (the profile's number is the fallback and says so). A template picks it with `\newcommand{\SMLayoutProfile}{lmsans}` before the setup layer. The catalog header lists what a profile defines (fonts, metrics, the 17 calibrations) and the recipe; README has both.
     - **Calibration tool.** `tools/calibrate_font_profile.py --profile <name>` compiles the calibration deck with the profile under the SlideMage template (the catalog's defaults, so the numbers are the profile's), measures the PDF and prints current value, suggestion and the reading for 11 calibrations; run on `fira` it reproduces the Fira values (`ok` everywhere, within 0.3pt, after taking out two offsets that are Fira's own: 0.22pt of glyph overhang at the footer's and footnote's right edge, and 2.36pt for `columns[T]` in a manual-top frame). Measured: footer text drop (ink of the frame number between the box's edges, from pixels), the two right shifts (against the logo's visible edge), `\SMContentTopShift`, `\SMColumnsTopCorrection`, `\SMColumnsTTopCompensation` (three manual-top frames, `\SMManualTopMargin`), the section frame's height correction, the two label-item lengths (widest label and a C, at the 10pt `\small`), the nested numeral slot and left margin (widest numeral plus the 0.43pt that Fira's slot has). Not measured, kept as Fira's: `\SMEnumerateLabelBox`, `\SMEnumerateTextExtra` (a design value), the nested label gap, and the section frame's `RefDepth`, `BottomGap` and `BottomPadCorrection`. lmsans values: footer drop -0.37pt, footer right shift -0.33pt (Fira 4.6: the footer's paddings are in ex, which is smaller in this font), footnote right shift 4.8pt, content top shift 11.17pt, columns 10.17pt and 13.55pt, section height correction 15.95pt, label width 9.16pt and sep 5.20pt, nested numeral slot 8.18pt and left margin 13.43pt.
     - **check_layout.py** was Fira- and template-bound beyond the margins: it assumed the Fira ascender (0.935), a title bar ending at 20-30bp, "Fira" in a font name for body text, and a last footnote line at 242.64. It now reads the ascender and the title bar's bottom edge from the PDF (the base writes `SMFontAscender` and `SMTitleBarBottom`, from `\SMTitleBarBottomAlign`, next to the two margins), tests body text as "not a maths font", and takes the usual last-footnote position from the deck (the highest last line plus 1.5pt, which is what a `\source` line without a raised marker needs). On the manual the findings are unchanged.
     - **Stress project.** `tests/fixtures/template_stress/`: `SlideMage_template_stress-test.tex` sets every hook of the catalog (a test checks that, and that every hook is read by the base or the theme), `decks/calibration.tex` (23 pages in all three versions: every frame type, every list depth and kind, columns, blocks, footnotes, three manual-top frames, a nested-numeral slide), `decks/stress.tex` (title, two dividers, a list and reveal steps with mini frames in the head, a progress bar in the foot, divider frames and the watermark on: all compile). `check_layout.py` is clean on the calibration deck against its own margins (top margin 50bp, left 15.5bp, ascender 0.806, title bar 30.4bp), with 12 exempted findings, each justified in a slide comment (side figures flush with the page edge, the chart's own axis label, and the manual-top frames below). The same deck under the SlideMage template with fira is clean with 7.
     - **What the stress test shows does not follow the template's hooks.** (1) The pull-up of a frame the automatic Top Margin does not manage (`\SMContentTopShift`, the two column corrections) is fitted to the default title bar: with Top Margin 50bp and another title bar the first line of a manual-top frame lands 2.9pt above the margin ([T] columns: 5.2pt), so those three slides skip `top`. (2) The footer number's and the footnotes' right edges miss the logo's edge by about 2.1pt and 2.3pt when the template changes the right padding or the text margin: `\SMFooterRightShift` and `\SMFootnoteRightShift` are profile numbers that contain the catalog's default paddings (open question (c) of step 5). (3) `\SMTitleframeBottomPad` is not "the space under the last line": at 30pt the second subtitle line stood on the box's edge, the stress template needs 55pt (question (e)). (4) A profile other than fira needs the template to set `\SMTitleBarBottomAlign` (22.17pt for lmsans against 25.32pt), `\SMTopMargin` and `\SMContentTopAlign`; the tool prints them. Also seen in the Fira reference, not caused by this step: a `\footnote` inside a `\pause`d item shows its text from the first step, and a `columns[T]` straight after a `columns[t]` starts about 3pt under the list above it, so the list's last line almost touches a table's top rule.
     - **App.** `preview_equivalence` pins `SlideMage_layout_lmsans.tex` (re-audited: no view-dependent rule; the profile test covers every profile the framework ships) and renews the setup, fira and base pins; the contract document names both profiles. `latex_export` needed no change (the profile name is read from the template; a test covers lmsans). `bundled_copies` takes the file without a change (a test). No new UI: the app lists no profile names anywhere. `REUSE.toml` covers the fixture's copied media.
     - **Regression.** Identical to the step 6 baselines: in-repo 12 entries, 1084 pages, and the private copy 57 entries, 7160 pages, 0 differences (the harness compares the PDF font lists too). Tests: 3383 passed, 2 GUI/process tests failed under load and passed alone; the opt-in compile tests (`SLIDEMAGE_TEX_TESTS=1`) of the tool and the stress deck pass. Renders of the calibration deck (stress template, three versions; SlideMage template with fira and with lmsans) and the stress deck are in `C:/Users/ms/SlideMage/regression/step7-renders/`.
   - **Next (approved by the user 2026-10-28):** `docs/plans/layout-from-metrics.md` makes
     the layout follow the font and the template (the stress test's findings above, and the user's step 5 answers).
     It is steps 8-13 (v10.7.0-v10.13.0, with a step 11b); the steps below moved to 14-17 (renumbered 2026-10-28).
8.-13. **Layout from metrics**: see `docs/plans/layout-from-metrics.md`.
14. **Bibliography file** (section 7). Can go any time after step 1.
   - **Done 2026-10-30 (v10.14.0):** the house format moved out of `latex/SlideMage_template_slidemage.tex`
     into the new, pinned `latex/SlideMage_bibliography_default.tex` (the content unchanged, SPDX
     `LPPL-1.3c+` like the base and the layout profiles); the template now says
     `\input{SlideMage_bibliography_default}` after its `\input{SlideMage_base}`, instead of carrying the
     ~165 lines itself. `bibliography_house.BLOCK` is that one line now; the full historical text moved to
     `bibliography_house.FULL_TEXT`, which `compat_bibliography.py` still needs to recognize a deck's or a
     template's pre-v10.14.0 literal copy. The "bibliography-in-template" change's `_template_state` accepts
     either form as "ready", and its `migrate` writes the one line (not the full copy) into a project
     template that is gaining the format for the first time. A new, separate compat change,
     "bibliography-default-file" (optional, LAYOUT, its own dialog entry), finds a project's own institution
     template still carrying the full copy and offers to replace it with the one line; nothing forces this,
     and `example/SlideMage_template_uni-graz.tex` is deliberately left on the full copy, as a live example
     of exactly the kind of template this new change is for. `bundled_copies.framework_files()` picks up the
     new file by its glob, no code change (a test). `preview_equivalence` renews the template's pin and adds
     one for the new file (re-audited: still only renewcommands, no view-dependent rule, like the layout
     profiles); the contract document names it next to the generic template. Base keeps its stock
     `\SMBiblatexOptions`/`\SMBibliographyStyle` defaults, unchanged. Not breaking: a deck or a template with
     its own copy keeps compiling exactly as before. Verified: full suite 3813 passed, 69 skipped, 0 failed;
     in-repo regression 12 entries / 1126 pages and private regression (ms, 57 entries / 7160 pages) both 0
     differences against `repo-v1013`/`private-v1013` -- expected, since this step only moves where the
     format's text lives, nothing any deck renders.
15. **Documentation.**
   - README's directory layout and institution-layer sections, PROJECT_OVERVIEW.md ("Gotham theme")
   - the manual's slides 1ym (framework box: "the Gotham theme"), 1pf (one look, several institutions: a
     template is now colors, logo, fonts and layout) and 1gr (layout grid)
   - the quick-reference slides, and a new manual slide "Making a template" that points at the catalog
   - a new manual slide "What a compile reads, in order" (user request, 2026-10-27), in the section
     "Appendix: Reference", because it is technical. A diagram of the final load order: the deck, its template,
     the setup layer with the catalog defaults, the theme, the layout profile, the base, the project macros and
     the slides, plus the Lua files. Each file says in a few words what it owns (look, fonts and metrics, layout
     rules, the template's own choices), and the slide shows where a template or a project's own file overrides
     a default. Make it after steps 4-7, so it shows the order as it ends up; next to "Making a template".
   - German translations where they exist (hd5)
   - Regenerate the manual's screenshots or crops only if something visible changed.
   - **Done 2026-10-31 (v10.15.0):**
     - **Load order, verified against the `\input`s** (not the order this step's list gave): deck ->
       `SlideMage_template_<key>` -> `SlideMage_setup` -> `SlideMage_layout_<profile>` (setup:164) ->
       `\usetheme{SlideMage}` (setup:172) -> the catalog (rest of setup) -> the template's settings ->
       `SlideMage_base` (which `dofile`s `SlideMage_alt.lua` and `SlideMage_measure.lua`) -> after the base, the
       template's additions: `SlideMage_project_macros` where a project's template inputs it, then
       `SlideMage_bibliography_default` (the shipped SlideMage template has only the latter; the
       "bibliography-in-template" migration inserts the format after the last of base/project macros, so this is the
       order in a project) -> back in the deck its settings, `\SMUseBibliography`, `\begin{document}`, the slides.
     - **Manual:** new slides `1im-EN-What-a-Compile-Reads` (a TikZ diagram of the twelve steps, framework files
       gray and project files white, "override 6" on the template's settings, "a project file wins" under it; alt
       text in `media/alt-text.json`) and `1vw-EN-Making-a-Template` (a minimal template as a code panel,
       `snippets/1vw-1.tex`; the rules; profile and `tools/calibrate_font_profile.py`; the four optional theme
       features with their switches), after 1uw in "Appendix: Reference" of both manual decks, in `slide_ids.csv`.
       Changed: 1ym (framework box and its alt text), 1pf and hd5 (what a template is, link to 1vw), 1gr and 1d7
       (`\SMAutoTopMarginfalse` places frames like `\SMManualTopMargin`; a link to 1vw did not fit on 1gr), 1uw (link to 1vw),
       1dt (the divider's sentence), the 1y5 snippet (a deck says `\SMUseBibliography`, it no longer loads biblatex
       itself), comments of 1xf and 2v9. Edited slides carry `+` on their version line; no frozen file was touched or
       added. No screenshot shows anything that changed (1pf/hd5's crops are step 16's business).
     - **Docs:** README (repository table, a load-order and making-a-template paragraph at the top of "Directory
       layout", the base and Uni Graz entries, a bibliography-file entry, the `Slidemaster.bib` rename typo),
       `docs/PROJECT_OVERVIEW.md`. `docs/SlideMageCommands.md` lists no template settings, so it is unchanged; plans
       and CHANGELOG history stay as they are. `latex/` is unchanged.
     - **Checks:** `check_layout.py` on both manual decks: no new findings (manual 0, copy the 1 `coltop` on dkf that
       the v10.14.0 baseline has too; the same with uni-graz). `check_layout.py` did not see a fourth bullet on 1gr
       that a first draft pushed under the footer box (the footer covers it, so its text is not "below the
       footer"); the renders did. Worth a check in the tool some day.
     - **Regression** (in-repo, against `repo-v1014`, pages aligned by slide id): 12 entries, 1150 pages; the
       differing pages are exactly the changed slides (1ym, 1pf, hd5 in the copy, 1y5, 1gr, 1dt, 1d7, 1uw), the two
       new ones, and after them 1r8, 2rg, 2v9 (the frame number, +2) and tks (a divider whose live chapter agenda
       lists the two new slides). No private regression: `latex/` is unchanged. Tests: 3831 passed, 69 skipped, 2
       GUI tests failed under load and passed alone.
     - **Open:** `example/SlideMage_template_uni-graz.tex` renews `\SMCardHeadingFont` (a profile name) after the
       base for its dark mode; the new slides say a template never sets a profile value. Harmless today; step 16
       moves the template out anyway.
16. **No institution templates in the repository** (needed before the repository goes public).
   - Move `example/SlideMage_template_uni-graz.tex` and `example/schemes/scheme_uni_graz/` to the real project
     (`D:\uniCLOUD\Slidemaster`), next to its mci and uni-ibk templates. SlideMage's own template is the only
     one the repository ships.
   - Remove `example/media/screenshot-slide-template-uni-graz.png`, `-uni-ibk.png` and `-mci.png`. Slides 1pf
     and hd5 show the slidemage template and the stress-test template of step 7 instead, with no institution
     logos.
   - Tests, REUSE.toml, the alt-text files, README and docs that name uni-graz follow. The key `uni-graz` stays
     a valid user setting (cached previews, "Default template"); only the repository stops using it.
   - The uni-graz regression baselines move to the set kept outside the repository.
   - The theme package (section 8) is defined by now, and the moved templates are its first candidates. Report
     the definition to the website side.
   - Afterwards a grep for `uni-graz`, `uni_graz`, `uni-ibk`, `innsbruck` and `mci` finds only CHANGELOG
     history and the course-system code (`online.uni-graz.at`).
   - **Done 2026-10-31 (v10.16.0):**
     - Removed from the repository: the Graz template, `schemes/scheme_uni_graz/` and the three institution
       screenshots. Copies of the template and scheme are in `C:\Users\ms\SlideMage\regression\uni-graz-template\`
       (outside the repository); the real project has its own. Slides 1pf/hd5 (and 1pf's frozen v1.0.0/v1.1.0, which
       the student views compile) show the SlideMage and the stress-test template. Tests use
       `tests/fixtures/template_acme/` or neutral keys.
     - Theme package defined in `docs/THEME_PACKAGE.md` (the section 8 proposal as decided by the user on
       2026-10-31); `themes.py`, Settings → Plugins → Themes and Install from file… for `.smtheme`,
       `tools/make_theme_package.py`, fixture `tests/fixtures/theme_package/sample-theme/`. Installed themes go on
       `TEXINPUTS` in `compiler.build_env`; snapshots and Export LaTeX copy their files. Report the definition to the
       website side (still to do: an outward action).
     - Remaining grep hits: CHANGELOG history, plans/handovers, `online.uni-graz.at` in a CampusOnline test, a binary
       font false positive, and a comment in `example/.latexmkrc` naming `\input{SlideMage_template_uni-graz}`: that
       file's digest is pinned (`AUDITED_LATEXMKRC`) and every project carries a copy, so changing a comment would
       cost existing projects their preview sharing. Change it together with the next real `.latexmkrc` change.
     - The in-repo regression lost its uni-graz entries; they are the private
       `C:\Users\ms\SlideMage\regression\private-uni-graz-base.json` (project `uni-graz-project\`). The harness cannot
       add the stress template to a run (a `template` entry only swaps the `\input` key); an `extra_dirs` option
       would allow it.
     - `AUDITED_PROJECT_TEMPLATES` keeps the Graz digests: they are hashes, and a project copy that matches one
       keeps sharing previews between views.
17. **Private institution themes** (user request 2026-10-27; after step 16, and after the plugins plan's Phase 1 has
    an installer). Includes the private-repository install and update of section 8 ("Private themes stay out of
    the catalogue"): "Add theme from GitHub…", `source.json`, the update check and offer, and the error messages.
    Tests use a fake GitHub API, as the updater's tests do.
   - **Uni Graz: a private repository shared with Jürgen Fleiß only.** Proposed name `slidemage-themes/uni-graz` in a
     GitHub organization, or `stpalan/slidemage-theme-uni-graz` if fine-grained tokens can reach a collaborator's
     repository after all (see the catch in section 8). Private, Jürgen with read access (write only if he maintains
     it too). It holds one theme
     package as section 8 defines it: `theme.toml`, `SlideMage_template_uni-graz.tex`, `schemes/scheme_uni_graz/`,
     its layout profile file if it gets one, `preview.png`, `LICENSE`, `README.md`, `CHANGELOG.md`. Each version is a
     tagged GitHub release with the `uni-graz-<version>.smtheme` asset and a `.sha256` file, following the website's
     release rules, so the theme could move into the catalogue unchanged if the university ever allows it. Creating
     the repository, pushing to it and inviting Jürgen are outward actions: ask the user before each.
   - **Licence of a private theme:** the TeX file can stay LPPL-1.3c+ like the framework, but the logo and the
     university's corporate design are not ours to license. `LICENSE` and `README.md` say so: the logo files are the
     university's, used with its permission for its members' teaching, and must not be passed on.
   - **Uni Innsbruck and MCI stay local for now** (user decision 2026-10-27): project templates in the real project
     (`D:\uniCLOUD\Slidemaster`), with no repository and no package. They then exist only in that project and its
     backups. If they are ever shared, they become private theme repositories like Graz's, one per institution,
     because GitHub grants access per repository.
   - **The real project** keeps working throughout: its own `SlideMage_template_<key>.tex` copies win over an
     installed theme of the same key (section 8). Once the Graz theme is installed from its repository, the project's
     Graz copy can go. Then the project uses the released versions, and a Graz template change happens in the theme
     repository instead of the project. Ask the user before removing it. The Innsbruck and MCI copies stay.
   - **Tests and regressions:** the uni-graz, uni-ibk and mci regression entries already live outside the repository
     (`C:\Users\ms\SlideMage\regression\`). They keep running against the installed themes. A test fixture theme for the
     installer (a tiny `.smtheme` with no institution content) goes into `tests/fixtures/`.
   - **Website side:** nothing to list, since private themes are never in the catalogue. Tell them that the theme
     package's first real users install from a private repository, so a theme repository should follow the same
     release rules whether or not it is listed.
18. **Version re-designation and the public repository** (user plan 2026-10-29; once the redesign is done and a
    version is stable). Every version so far gets a leading 0 (e.g. v10.1.12 becomes v0.10.1.12, v8.69.0 becomes
    v0.8.69.0); the public repository starts with a fresh initial commit (no history), and versions go on from
    v1.0.0. **Do not start any of this without the user's explicit authorization** (user, 2026-10-29); not even
    preparatory code changes. To plan in detail at that time; what the code needs:
   - **CHANGELOG parsing:** `version._HISTORY_ENTRY_RE` accepts exactly three parts (`v\d+\.\d+\.\d+`); it must
     accept the four-part history entries. `updater.parse_version` already takes any number of parts, and
     `(0, 10, 1, 12) < (1, 0, 0)` compares correctly. Check `packaging/release_notes.py` and its tests the same way.
   - **Projects remember versions:** `.slidemage/project.json` holds `last_app_version`, `highest_app_version` and
     `compat.checked_version` (e.g. "v10.9.0"). Opened by v1.0.0, such a project looks "used by a newer SlideMage"
     and no compat change would ever be pending (`checked_version` above the app). Needed: read an old-scheme
     version (major 2 or higher before the switch) as `0.<old>`, or migrate the file once.
   - **Compat registry:** `Change.since` values ("v10.0.0", ...) become `v0.9.0.0` ... with `REGISTRY_FROM` and the
     test that pairs BREAKING releases with entries.
   - **Update check:** an installed v8.x/v10.x build only offers a higher version, so it never offers v1.0.0. Installs
     before the switch (the user's and Jürgen's) are updated by hand once; say so in the release notes.
   - **Release tags and builds:** `release.yml` builds on `v*` tags and requires tag = `VERSION_NUMBER`; the fresh
     repository starts its tags at v1.0.0. Decide what happens to `SlideMage/SlideMage` (the current, private
     repository with history) and where the public one lives; the update check and website point to the public one.
     **Decided by the user on 2026-10-29:** the public repository is `SlideMage/SlideMage`, cut fresh (initial
     commit, no history); the full history is kept in a private repository that only the user and Jürgen Fleiß can
     access, named `SlideMage_pre_v1` (user, 2026-10-29); how the current repository becomes it is still to
     settle. The update check and the
     website keep pointing to `SlideMage/SlideMage`.
   - **Fresh initial commit:** the public repository holds the tree as it is then, minus the institution templates
     (step 16) and anything private; the CHANGELOG keeps the history as text (under the 0.x numbers).
   - Open with the user then: whether the history CHANGELOG ships in full or is cut; the order of moving
     the current repository to `SlideMage_pre_v1` and cutting the public one.
19. **Clean up everything no longer needed** (user request 2026-10-29; the very last step, after everything else is
    merged and verified). List what will go and get the user's OK before deleting anything that cannot be
    recreated:
   - **Worktrees and branches:** every step, baseline and check worktree under `.claude/worktrees/` (`fw-step*`,
     `fw-baseline*`, `fw-check-*`, finally `fw-redesign` itself once the branch is merged where it belongs) and their
     merged `claude/fw-*` branches; the branch `fw-redesign-conflict-copy-28170940`; the stash
     `fw-redesign-sync-leftover-v941-theme-header`; any leftover `(conflicted copy ...)` files under `.git`.
   - **Regression data:** `D:\uniCLOUD\SlideMage\.regression\` (baselines, compare outputs, diff images, logs; about
     1 GB+, private renders) and the per-machine folders `C:\Users\palans\SlideMage\regression\` and
     `C:\Users\ms\SlideMage\regression\` (project copies, configs, baselines), unless the user wants a current
     baseline kept for future framework work; then keep only that one and its config.
   - **Temporary files:** build output of the stress/calibration decks, `.top`/`.ovl`/aux files left outside build
     folders, sessions' scratch and Temp compile folders, old test builds and dists in `C:\Users\<user>\SlideMage`,
     `docs/plans/step*-status.md` files, and `.git/info/exclude` entries that no longer apply.
   - **Documents:** the handover documents in the main checkout's `docs/` that are finished (this one included,
     after its content is in the plan or no longer needed), and plan notes that only served the work in progress.
   - Check afterwards: `git worktree list`, `git branch`, `git stash list`, `git fsck --connectivity-only`, and that
     the main checkout and the user's real project still compile.

## Open decisions (ask the user at the step named)

- **Before step 2: the content-name mapping in section 3** (`SMTable`, `SMFloatingInfoBlock`, `SMArrow`, ...),
  and whether frozen slide versions are migrated.
- **Before step 5: may a template override a layout-profile value directly**, or only pick a profile? Proposed:
  only pick one, or ship its own profile file. That keeps the rule "a profile's numbers belong together".
  **Decided by the user on 2026-10-27: a template only picks a profile or ships its own profile file; it never
  overrides a single profile value.** So profile values are not catalog hooks.
- **Step 7: whether `lmsans` ships to users** as a selectable fallback, or stays test-only.
- **Step 16 at the latest: the theme package** (section 8): files, release asset and manifest, install location
  and how a project uses it. Then tell the website side.
- **Step 17: Uni Innsbruck and MCI.** **Decided by the user on 2026-10-27: they stay local**, as project templates
  in the real project. Private theme repositories install and update from GitHub with the user's token (section 8,
  also decided on 2026-10-27).
- **Step 17, still open:** the Graz repository's home (a GitHub organization or `stpalan/...`, depending on the
  fine-grained-token catch in section 8) and Jürgen's access level (read or write).

## Risks

- **Pixel identity across steps 1-5** is the whole safety net. Don't skip the harness, and compare the PDF's
  font list as well as the images. A step that is not identical stops and reports.
- **ex/em values change meaning** if they are evaluated in another font or at another time. Keep every hook's
  evaluation where today's `\setlength` happens: in the preamble, in the normal font, after the profile has
  loaded.
- **The real project compiles against the develop checkout** (section 6). Use a feature branch, test the
  migrations on a copy, and get the user's go-ahead before merging a breaking step.
- **Preview equivalence**: changing framework files without re-auditing makes previews fall back to isolated
  renders. That is slow but correct. A wrong audit is the dangerous case, so follow the contract document.
- **LPPL**: confirm the obligations from the license text before step 2 is committed.
