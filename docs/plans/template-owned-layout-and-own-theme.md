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
| Design hook | setup catalog | yes | logo path and height; frametitle top/bottom/left/right padding; title, footer and bullet colors; title-frame box height, text sep, band gap, bottom pad; section-frame box height; quote box height and attribution gap; footer box height; side-footnote width; block side margin and title-marker width; progress-strip height; text margins (.45cm); list spacing ratios; image border width; Top Margin (41.58pt); text sizes of footer, slide id, footnotes, code, block titles; `\parskip`, `\linespread` (default from the profile) |
| Font metric | layout profile | no, it picks a profile | font files and weight mapping; ascender ratio (0.935); line-box top strut; code/inline-code fonts and scale; card heading font; math-font handling; each calibration that stays font-dependent after step 5 |
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
   - **Done 2026-10-26 (v9.1.0), notes for the later steps:**
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
     - The manual still says "Gotham theme" on slide 1ym and in `media/alt-text.json`: step 9, since changing it
       changes the render.
3. **Consolidation.**
   - Base's replacements of theme parts move into the theme as their only definition.
   - Base loads its packages explicitly.
   - Load-time computations that depend on hooks move to base or to the point of use.
   - Pixel-identical. Not breaking.
   - **Done 2026-10-27 (v9.2.0), notes for the later steps:**
     - Moved into `beamerthemeSlideMage.sty` (base 6998 → 5712 lines, theme 2213 → 3467): the colours of footnote,
       footline text, buttons, canvas, frame title text and blocks (block, alerted, example, reference, info; the
       theme's own native-block colours and `alertedBlock`/`example text` are gone); the text margins; `\SMBulletDot`
       as the `itemize item/subitem/subsubitem/subsubsubitem` template (no longer set at the start of every
       `standardframe`; a bare `\begin{frame}` now gets SlideMage's bullet too); `\SMInstituteLogo`, `\SMInstituteLogoGraphic`,
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
5. **Classify every remaining value.**
   - Go through the inventory (section 2's table; the full list is in the 2026-10-23 inventory, which this
     step redoes against the code as it stands then) and decide each length.
   - Calibrations: try them as 0 under the automatic Top Margin and delete them when the render stays
     identical. Otherwise write them as metric expressions, and only failing that as profile values.
   - Design values become catalog hooks.
   - Pixel-identical. Any intended difference needs the user's approval with before/after images.
6. **Effective margins for the tools.** Base writes the PDF info keys; `check_layout.py` reads them.
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
8. **Bibliography file** (section 7). Can go any time after step 1.
9. **Documentation.**
   - README's directory layout and institution-layer sections, PROJECT_OVERVIEW.md ("Gotham theme")
   - the manual's slides 1ym (framework box: "the Gotham theme"), 1pf (one look, several institutions: a
     template is now colors, logo, fonts and layout) and 1gr (layout grid)
   - the quick-reference slides, and a new manual slide "Making a template" that points at the catalog
   - German translations where they exist (hd5)
   - Regenerate the manual's screenshots or crops only if something visible changed.
10. **No institution templates in the repository** (needed before the repository goes public).
   - Move `example/SlideMage_template_uni-graz.tex` and `example/schemes/scheme_uni_graz/` to the real project
     (`D:\uniCLOUD\Slidemaster`), next to its mci and uni-ibk templates. SlideMage's own template is the only
     one the repository ships.
   - Remove `example/media/screenshot-slide-template-uni-graz.png`, `-uni-ibk.png` and `-mci.png`. Slides 1pf
     and hd5 show the slidemage template and the stress-test template of step 7 instead, with no institution
     logos.
   - Tests, REUSE.toml, the alt-text files, README and docs that name uni-graz follow. The key `uni-graz` stays
     a valid user setting (cached previews, "Default template"); only the repository stops using it.
   - The uni-graz regression baselines move to the set kept outside the repository.
   - Afterwards a grep for `uni-graz`, `uni_graz`, `uni-ibk`, `innsbruck` and `mci` finds only CHANGELOG
     history and the course-system code (`online.uni-graz.at`).

## Open decisions (ask the user at the step named)

- **Before step 2: the content-name mapping in section 3** (`SMTable`, `SMFloatingInfoBlock`, `SMArrow`, ...),
  and whether frozen slide versions are migrated.
- **Before step 5: may a template override a layout-profile value directly**, or only pick a profile? Proposed:
  only pick one, or ship its own profile file. That keeps the rule "a profile's numbers belong together".
- **Step 7: whether `lmsans` ships to users** as a selectable fallback, or stays test-only.

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
