# Plan: a theme editor (Part C of the handover task `personal-themes-extensions`)

Status: **draft for the user's review, nothing of Part C built.** Parts A and B (list personal themes in Settings →
Extensions; edit a theme's `.tex` in a centre tab; copy an installed theme into the project) are in v0.14.62
(PR SlideMage/SlideMage#145, merged). All nine design questions answered 2026-11-10 (section 0); stage C0 built (v0.15.3).

## 0. Where this stands (read this first; written 2026-11-09 evening for the next session)

**What the discussion produced, in order** (each step is a section below; the user steered every turn):

1. The full inventory of what a theme can set, ranked (section 2), from the hook catalog and five real templates.
2. **Uni Graz as the reference theme** (section 1a): the most used, the only one with a dark mode, an *installed* package
   (`D:\Dropbox\repos\slidemage-theme-uni-graz`, 1.1.1; the installed copy under `%APPDATA%\SlideMage\themes\uni-graz` is
   identical). First acceptance test of the editor: a byte-identical round trip of the Graz file.
3. **Themes per view** (3.7, stage C0): instructor / during-course / after-course each map to `theme[:mode]`, so one deck is
   dark for projection and light for print. The user asked for it to be in the plan.
4. **Colours** (3.8, stage CR): a physical palette, about 35 roles, role names slides can use, and **modes as a list a theme
   declares** (colour schemes only; `dark` and `grey` as derivation presets), reached through one BREAKING release with the
   `compat.py` migration and no legacy aliases. The user's decisions in the discussion: no compatibility leftovers; dark must not
   be hard-coded; Greyscale-like variants are modes of a theme (the user's idea; my boundary: a mode is colours only).

**Decided by the user so far:** per-view themes go in the plan; the roles strategy "in principle"; clean transition over
aliases; modes not hard-coded. **Nothing else is decided, and nothing may be built before their OK on a stage.**

**All nine questions answered by the user on 2026-11-10** (1 to 5 as recommended: tier order as written, Graz route A plus B with the round-trip test, form beside the source tab, the form may add a marked block, a purpose-written theme sample deck, block-title text and link colours as the first roles; 6 to 9 as noted in the table). **Stage C0 approved and built** (section 3.7, v0.15.3, branch `feat/theme-per-view`); CR is next, not yet approved.

**Open questions, with my recommendation (kept for the record)** (all in section 5; the user had not answered them when this was written):

| # | Question | My recommendation |
|---|---|---|
| 1, 1a | Tier order; which route for editing Graz | tier order as written; route A as built plus B (the theme's source folder) for the author, C (edit the installed copy) not offered; Graz round trip as the first test |
| 2 | Form beside the source tab, or a designer tab that hides it | beside it, both live on one buffer |
| 3 | May the form add a marked block to a hand-written theme | yes |
| 4 | Sample deck for the live render | a purpose-written theme sample deck |
| 5 | Which framework hooks first | block title text and link colours, as the first roles of CR |
| 6 | A mode is colours only; Greyscale as shipped stays a theme | **ANSWERED 2026-11-10: a mode may change colours AND the logo** (not fonts, margins, bullets); Greyscale stays a theme. See 3.8 |
| 7 | Derived modes live in TeX with explicit lines winning, or only explicit values written by the editor | **ANSWERED: live defaults in TeX, explicit lines win; add a `colorblind` derivation preset** (also offered by the form's "Add mode") |
| 8 | One BREAKING release with migration and regression proof; old installed themes refused until updated | **ANSWERED: yes, agreed** |
| 9 | Role names for slides | **ANSWERED 2026-11-10 (final): `c_text`, `c_canvas`, `c_card`, `c_line`, `c_text_muted`, `c_text_on_accent`, `c_link`** |

**Suggested way on, when the user has answered:** (1) settle 6 to 9 and fold the answers into 3.8; (2) C0 as its own task
and PR (small, framework-free, fourteen call sites); (3) CR as its own task (this is also the plan for handover task
`theme-color-roles`, whose step 1, white block-title text, is the first role); (4) the form (C1 onwards). C0 and CR do not
depend on the form; CR depends on C0 only for the `theme:mode` value.

**Facts a new session needs, so it does not rediscover them:**

* Worktree `D:\Dropbox\repos\SlideMage\.claude\worktrees\personal-themes` on branch `feat/personal-themes-extensions`; PR #145 holds
  A, B and this file (docs-only commits after the code commit). Develop was v0.14.61 when it started.
* The hook catalog is `latex/SlideMage_setup.tex` (21 palette colours, 8 optional colours, 9 colour roles, 33 lengths, 42
  macros, 22 guarded derived names); `\SMApplyColorRoles` in `latex/beamerthemeSlideMage.sty` is the single place that
  resolves colour roles after the template.
* The real project is `D:\uniCLOUD\Slidemaster` (templates `mci` and `uni-ibk` in the project folder, Graz is installed; 1,416
  slides; the usage counts in 3.8 come from there). Existing migration precedent: `src/slidemage/compat.py` and
  `compat_names.py` / `compat_own_theme.py`. The regression tool for "identical PDFs before and after" is
  `tools/framework_regression.py`.
* Template consumers to touch for per-view themes: fourteen `detect_template(...)` calls in ten files (listed in 3.7).
* A theme package holds exactly one template file (`themes.check_names`), which is why Graz Dark as a package of its own
  would be a second package.
* Not checked: the Presenter app against per-view themes; whether `compat.py`'s detector can classify the ambiguous colour
  uses well enough (the plan assumes a rule table plus a report of what it cannot classify, proven by the base-mode PDF
  regression); the exact TeX for `derive=grey` (xcolor can convert to gray, not tried).

Request (2026-11-09): "a UI for theme settings or for defining a new theme (font, colours, margins)". The user
asked to discuss what really goes into a theme and its editor, and for a full inventory of everything a theme could
set, from what makes most sense to include to what makes least.

## 1. Where the inventory comes from

* `latex/SlideMage_setup.tex`, the **hook catalog**: 21 palette colours, 8 optional colours, 9 colour roles, 33 lengths and
  42 macros (font switches, size settings, ratios, switches), and the optional features. Rule 2 of that file: between
  `\input{SlideMage_setup}` and `\input{SlideMage_base}` a template may only `\setlength`, `\renewcommand`,
  `\definecolor` and `\colorlet` names that exist; a misspelt one is an error.
* Rule 1: before the setup file only `\SMLayoutProfile` and `\SMDarkMode`. Rule 3: after the base, additions only.
* The five real templates: **Uni Graz** (the theme package `uni-graz` 1.1.1, repository `slidemage-theme-uni-graz`;
  the most used and most tested, and the reference for this plan: section 1a), SlideMage (the catalog defaults),
  Greyscale (the one that "differs in nearly everything a template can choose"), `uni-ibk` and `mci` (institution
  layers in the real project). Graz is an *installed* theme, not a file in the project folder, so Part A lists it with
  the installed themes, not as personal.
* What a theme **cannot** set, by design: 22 **derived** names (guarded: setting one is an error), and the layout
  profile's own numbers (ascender, line spread, parskip).

What the five real templates actually change (the evidence for the order below):

| Setting group | **Uni Graz** | SlideMage | Greyscale | uni-ibk | mci |
|---|---|---|---|---|---|
| 21 palette colours | all (17 set, plus the theme's own `c_true_black`) | defaults | all | all | all |
| Logo file | own | default | default | own | own |
| Colour roles (of 9) | 6 (+ 3 overridden in dark mode) | defaults | 9 | 5 | 5 |
| Code panel colours | 3 (+ 4 in dark mode) | 3 | 1 | 3 | 3 |
| **Dark mode** (`\ifdefined\SMDarkMode`) | **yes, 50 lines in two blocks** | – | – | – | – |
| Layout profile (font) | fira (default) | fira | lmroman | fira | fira |
| Body size, text margins, Top Margin | – | – | all three | – | – |
| Title bar paddings, logo height and padding | right padding | – | all | right padding | right padding |
| Footer box and text sizes | – | – | all | – | – |
| Bullet symbol / footnote marker | – / **boxed** (`\SMSetFootnoteMarkers`) | – | both | – | – |
| Card heading font (`\SMCardHeadingStyle`) | Fira Sans Medium (dark mode) | – | – | – | – |
| Citation format | `\input{SlideMage_bibliography_default}` (the older form) | `\SMCitationFormat` default | same | – | – |
| Project macros after the base | – | – | – | yes | yes |

## 1a. Uni Graz, the reference theme

`SlideMage_template_uni-graz.tex` is 161 lines. Its parts, in file order, with where each lands in the inventory below:

| Lines | What it holds | Inventory item |
|---|---|---|
| header | `% SlideMage template name: University of Graz`, `% SlideMage dark mode: true`, a prose paragraph | 1 Identity |
| before the palette | `\SMSetFootnoteMarkers{boxed}` (a command, not a hook; before the palette) | 10 Footnote marker |
| palette | 17 `\definecolor{c_...}{HTML}{...}` lines, official Graz colours, with prose comments saying why `c_custom_gray` exists | 2 Palette |
| logo | `\SMInstituteLogoPath` (vector PDF, cropped to its ink), `\SMLogoHeight` 3ex, `\SMFrametitleRightPadding` 0.28cm ("re-measured against the compiled PDF for this logo") | 3 Logo |
| roles | `\SMBulletColor`, `\SMTitleBoxColor`, `\SMTitleTextColor`, `\SMFooterBoxColorDefault`, `\SMFooterTextColor` (yellow boxes, black text), `\SMStandoutTextColor` = `c_true_black` | 4 Colour roles |
| code | `SMCodeKeywordColor` (a darkened blue, `definecolor`), `SMCodeCommentColor`, `SMCodeBackgroundColor` (`colorlet`), each with its contrast ratio in the comment | 5 Code colours |
| `c_true_black` | an extra colour of the theme's own, because dark mode turns `c_primary_dark` white | new: theme-defined colours |
| `\ifdefined\SMDarkMode` block 1 (before the base, 27 lines) | canvas, card fill, card border, process border; `c_primary_dark` becomes white; seven tertiary colours become the card fill; `c_custom_gray` lightens; title and footer text turn black; code panel colours; **card heading font** `\newfontfamily\SMCardMediumFont{FiraSans-Medium.otf}` + `\SMCardHeadingStyle` | **Dark mode** (5a), 14a, 16 |
| `\input{SlideMage_base}` | | |
| `\ifdefined\SMDarkMode` block 2 (after the base, 23 lines) | an `\SMInlineCodeStyle` that colours inline code yellow **only in the body colour** (a TeX trick with `\current@color`), `\tikzset{SMProcess...}`, `\setbeamercolor{normal text}`, `\hypersetup{citecolor}`, `button`, **five `block title` colours**, `standout` (dark canvas, yellow text) | Dark mode; beyond the catalog; raw TeX |
| last line | `\input{SlideMage_bibliography_default}` | 12 Citation |

What Graz does **not** set: a layout profile, body size, margins, Top Margin, title bar paddings (except the right one),
footer sizes, bullet symbol. They all keep the catalog defaults. That matches the usage table: tier 1 is what an
institution theme is made of; tier 2 is what a differently designed theme (Greyscale) adds.

What Graz teaches the editor (each point changed the plan below):

1. **Dark mode is not an extra, it is a third of the file** (50 of 161 lines, 41 of them live code) in the theme you use
   most. It moves from tier 3 to tier 1 (item 5a), and the editor's first test is Graz.
2. **Settings live in scopes.** The same name (`c_primary_dark`, `\SMTitleTextColor`, `SMCodeKeywordColor`) is set
   twice: once at top level (light) and once inside `\ifdefined\SMDarkMode ... \fi` (dark). A line-by-line reader that
   ignores `\if` would show the dark value as *the* value or find two. The reader must track the scope (section 3.1).
3. **A theme defines colours of its own** (`c_true_black`, `SMCardMediumFont`'s font) that the roles then use. The
   palette-name drop-downs must include them, and the form needs a small "theme's own colours" list.
4. **Part of the file is arbitrary TeX the form cannot model** (the inline-code style, the `tikzset`, the `\setbeamercolor`
   lines). The form must keep it, show "N lines are beyond the form: open them in the source tab", and never reflow it.
5. **Five `\setbeamercolor{block title...}{fg=c_true_black}` lines in dark mode** are the block-title text colour that is
   a gap in the catalog (see "beyond the catalog"): the evidence that the hook belongs in the framework, so the dark
   block could shrink from five lines to one role.
6. **The comments carry knowledge** ("re-measured against the compiled PDF", contrast ratios, why a colour exists). The
   editor may never rewrite or drop them. Where the form changes a value that has a stated contrast ratio in its
   comment, it shows the new ratio next to the old one and leaves the comment for the user to fix.
7. **Graz is an installed package with its own repository, version and release flow** (`theme.toml`, CHANGELOG, a GitHub
   release with a `.smtheme`), so editing it is not "edit a personal file". Section 3.6.

## 2. The inventory, most sensible first

"Sensible" = changed by most themes, one value each, safe (cannot break the layout), and something a form beats raw
TeX at (a picture, a check, a picker). Each entry names the TeX it writes. The tier is where I would draw the line
between "first release of the form", "second" and "behind an Advanced section or only in the source tab".

### Tier 1: every theme sets these (form, first release)

1. **Identity**: name (`% SlideMage template name:` header line, 1-40 chars), key (the file name,
   `SlideMage_template_<key>.tex`, 2-32 chars, not a shipped key), "supports dark mode" (`% SlideMage dark mode: true`),
   author and licence (only needed for packaging as a `.smtheme`, `theme.toml`).
2. **Palette, 21 colours** (`\definecolor{c_...}{HTML}{...}`): `c_primary_dark` (body text, dark boxes),
   `c_primary_highlight` (accent: bullets, highlights), `c_primary_gray` (highlightframe), `c_primary_white`; six
   secondary colours (violet, blue, green, red, orange, yellow: the block titles, link underline, infoblock) with a
   tertiary partner each (block bodies, the 50 % white blend), `c_tertiary_gray`; four supporting colours
   (`c_custom_gray` hyperlinks, `_red`, `_green`, `_brown`). A form can do what raw TeX cannot: colour picker,
   "derive the tertiary as a white blend" button, and the **contrast checks the catalog states** (body text on every
   secondary block title >= 4.5:1, title/footer text on its box >= 4.5:1, white on `c_primary_gray` >= 4.5:1, link
   underline on the canvas >= 3:1). `theme_colors.py` (v0.14.60) already reads these lines. Beside the 21: the
   **theme's own colours** (Graz's `c_true_black`), a free list of name plus value that the role drop-downs then offer.
3. **Logo**: `\SMInstituteLogoPath` (file picker; the file is copied to `schemes/scheme_<key_>/` and must be a vector
   PDF cropped to its ink), `\SMLogoHeight`, `\SMFrametitleRightPadding` (the white space either side of the logo; the
   frame number and footnotes end at its inner edge).
4. **Colour roles, 9** (`\renewcommand{\SM...Color}{<palette name>}`): title bar box and text, footer box and text,
   bullets, highlightframe title text, standout text, `\alert` text, progress bar. Each is a drop-down of palette
   names, so a theme cannot name a colour that does not exist. Open task `theme-color-roles` adds more (block title
   text colour among them); the form should read its list of roles from the catalog, not hard-code it.
5. **Code panel colours, 4 optional** (`\colorlet`/`\definecolor` of `SMCodeKeywordColor`, `-Comment-`, `-Background-`,
   `-Text-`): all 5 real templates change them; the checker is again contrast (commands and comments on the panel).
   Graz writes the keyword colour with `\definecolor` and the background with `\colorlet`: the form reads both forms
   and writes back the form that was there.
5a. **Dark mode** (moved up from tier 3 after reading Graz; it is the most used theme; **superseded by section 3.8**: dark is one mode among the modes a theme declares, not a special case): the deck says `\SMDarkMode`
   before the template (deck settings write it; the template opts in with `% SlideMage dark mode: true`), and the
   template then overrides settings **inside `\ifdefined\SMDarkMode ... \fi`**. What Graz overrides, and so what the
   form shows as a "Dark" column beside "Light": the slide canvas (`SMCanvasColor`), card fill and border
   (`SMCardBackgroundColor`, `SMCardBorderColor`), process border (`SMProcessBorderColor`), body text (`c_primary_dark`
   becomes white), the tertiary block-body colours (become the card fill), hyperlink grey, title and footer text, code
   panel colours, standout frame colours, the card heading font, plus block title text, button, citation colour and
   the inline-code style after the base (raw TeX). The first release round-trips all of it unchanged and edits the
   colours; a "make this colour the same in dark" shortcut and a "derive a dark mode from the light palette" helper
   come after.

### Tier 2: common, one value each (form, second release)

6. **Font**: the **layout profile** (`\newcommand{\SMLayoutProfile}{...}` before the setup file): fira, lmsans, lmroman,
   or a profile of the project's own (`SlideMage_layout_<name>.tex` found next to the templates). The form picks one;
   it **never** edits a profile's numbers. Making a *new* profile from font files is a separate tool
   (`tools/calibrate_font_profile.py --new`, then a calibration run to read the ascender); the form can offer to run it
   later, it is not a field.
7. **Sizes**: body text `\SMBodyFontSize` (the others follow: small, footnotesize, ...), footer text and id
   (`\SMFooterTextSize`, `\SMFooterIDSize`: `\fontsize{a}{b}\selectfont`), footnote text (`\SMFootnoteSize`), code
   (`\SMCodeSize`), and the beamer font sizes of frame title, block titles, caption, bibliography entries
   (`\setbeamerfont`, written after the setup file; see "beyond the catalog" below).
8. **Margins**: text margin left and right (`\SMTextMarginLeft/Right`), the **Top Margin** (`\SMTopMargin`, in bp, where the
   first line of a frame starts), the block side margin (`\SMBlockSideMargin`).
9. **Title bar**: top, bottom, left, right padding (`\SMFrametitle...Padding`), subtitle separator and strut. The bar's
   bottom edge is derived (from the top padding, the title font and the logo height), so the form must say "the bar ends
   at the logo's lower edge" rather than offer a height.
10. **Footer and footnotes**: footer box height, footer side padding, footnote-to-footer gap, space between footnotes,
    **footnote marker** (symbols, numbers `\number#1`, boxed, dice). Graz uses the command
    `\SMSetFootnoteMarkers{boxed}` (before the palette); Greyscale uses `\renewcommand{\SMFootnoteMark}`: both forms
    read, the one that was there is written back.
11. **Bullets and lists**: bullet symbol (filled circle, en dash, custom glyph; the indent follows by itself), item
    spacing ratios of the four levels.
12. **Citation format**: `\SMCitationFormat` (default or an installed `.smcite` key; the same list as Settings),
    `\SMBiblatexOptions`, `\SMBibliographyStyle`. Graz still ends with `\input{SlideMage_bibliography_default}`, the
    form older than `\SMCitationFormat`: shown as "house format", kept as it is unless the user picks another.

### Tier 3: rarely changed, expert (only under "Advanced", or only in the source tab)

13. **Block shape**: title marker width, block title and body sizes (beamer fonts).
14. **Frame types**: `\titleframe` (box height, text separation, band gap, bottom pad), `\sectionframe` (bar height, title gap,
    content drop), `\quoteframe` (box height, attribution gap), `\progressstrip` room. Each is a measured number of the
    shipped design; a form can show them but a wrong value looks bad without any error.
14a. **Cards and processes** (diagram building blocks): `SMCardBackgroundColor`, `SMCardBorderColor`,
    `SMProcessBorderColor`, `SMCanvasColor` (the slide background; with dark mode this is the main colour).
15. **Fine spacing**: level-by-level list ratios (drop, open space), tall item, label item width and gap, nested
    enumerate slot and gap, tight display skip, `\SMBesideFigureTopGap`, side footnote strip geometry (width, inset,
    marker shift).
16. **Drawing helpers**: image border width, warning sign padding and border, card heading style
    (`\SMCardHeadingStyle`, a font switch such as a medium weight). Graz does this in dark mode with
    `\newfontfamily\SMCardMediumFont{FiraSans-Medium.otf}`: a font file by name, so the field is a font-file name plus a
    check that the font exists, not a free font switch.
17. **Optional features** (off by default, a command each): mini frames (position, spreading, sections, compress,
    marks), **progress bar** (position, style, direction), **divider frames** (levels, look, page options, offset),
    **watermark** (default on or off, template).
18. *(Dark mode moved to item 5a, after reading Uni Graz.)*

### Tier 4: things a theme editor should not offer

* The 22 **derived** lengths (`\SMContentTopAlign`, `\SMFooterRightShift`, `\SMLabelItemWidth`, the section frame's four
  corrections, ...): the catalog guards them with an error. To move what they place, change the hook they follow.
* The **removed** names (`\SMFootlineHeight`, `\SMFootlineDepth`, `\SMRightFooterPadding`) and the renamed ones.
* A layout profile's numbers (`\SMFontAscender`, `\SMLinespread`, `\SMParskip`).
* Anything in `SlideMage_base.tex` or `beamerthemeSlideMage.sty` (the framework; "A template does not patch the theme or
  the base").
* **Deck-level** settings the deck settings dialog already owns: template choice, dark on/off, language, footer text and
  hidden elements, output folders, aspect ratio and paper size (the deck's `\documentclass`), PDF to open.
* **Project macros** (`\input{SlideMage_project_macros}` after the base: course diagrams): the project's, not the theme's;
  keep the line, do not edit it.
* Extra packages, hyphenation, hyperref options: no catalog name; source tab only.

### Beyond the catalog: what a theme would sensibly set but cannot yet

These are the gaps a form would immediately expose. Each needs a framework hook before the form can offer it (the
smallest hook, as for `theme-color-roles`):

* **Block title text colour** (fixed `c_primary_dark` today; the Innsbruck "white block titles" request; Graz's dark
  mode patches it with five `\setbeamercolor{block title...}` lines after the base).
* **Inline code colour** (Graz's dark mode redefines `\SMInlineCodeStyle` with a `\current@color` comparison to colour
  inline code only in body text: a role such as `\SMInlineCodeColor` would replace that TeX).
* **Standout and canvas for dark mode as roles** (Graz sets `\setbeamercolor{standout}` and `normal text` by hand).
* **Link colours** (text `c_custom_gray`, underline `c_secondary_blue`: fixed in the base).
* **Per-frame-type colours** (title/section/quote frame boxes follow the title bar role; no role of their own).
* **Frame title weight, case and alignment** (beamer fonts, not in the catalog).
* **Logo placement** (always the title bar's right end) and a second logo for dark backgrounds.
* **Canvas colour as a role** (it is "optional colour" `SMCanvasColor`, undocumented as a role).

## 3. The editor: what it edits and how

### 3.1 The file stays the truth

A theme is a hand-written, heavily commented `.tex` (Graz's and uni-ibk's headers explain where each colour came from
and what contrast it has). A form that regenerates the file would destroy that. So:

* **Recognise, edit in place.** The form reads the file the way `deck_settings.py` reads a deck (live, uncommented
  lines; the same `_live` and `is_commented` helpers): each setting is a regex over one line. Changing a value rewrites
  that line's value and keeps its trailing comment; a setting the file does not mention is **appended** inside a
  marked block (`% --- SlideMage theme editor: begin/end ---`) immediately before `\input{SlideMage_base}`, in the
  catalog's own order. Lines the form does not recognise are never touched.
* **Scope-aware (only until section 3.8 is in).** After the colour cut of 3.8 a mode's values are plain data lines
  with the mode as an argument, and no scope is needed; the reader below is for the files written before it. The reader tracks `\ifdefined\SMDarkMode ... \else ... \fi` (and the position against
  `\input{SlideMage_base}`), so each recognised line belongs to one scope: *light* (top level), *dark* (inside the
  conditional) or *after the base*. The form shows Light and Dark values separately. A new dark value is appended
  **inside the existing dark block, before its `\fi`**, or a new block is made when the theme has none (then the
  header gets `% SlideMage dark mode: true`). Nested or unusual conditionals (anything but a plain
  `\ifdefined\SMDarkMode`) make the reader say "this part is beyond the form" instead of guessing.
* **Beyond the form is kept and counted.** Lines the form cannot model (Graz's inline-code style, `\tikzset`,
  `\setbeamercolor` lines) stay byte for byte; the form says how many there are and opens the source tab on them.
* **Acceptance test, Graz.** The Graz file is the golden fixture (copied into `tests/fixtures/`, the TeX file only: it
  is LPPL, the logo is not). (1) Read it and write it back with nothing changed: **byte-identical**. (2) Change
  `c_primary_highlight`: **exactly one line differs**. (3) Change the dark canvas: one line differs, inside the dark
  block. (4) Add a setting Graz does not have (the body size): it lands in the marked block, nothing else moves. (5) The
  Graz field values equal what `theme_colors.py` reads for the same file. The same four checks run on Greyscale and
  uni-ibk, which have other shapes (roles, no dark mode, `colorlet` against `definecolor`).
* **Source tab and form are two views of one buffer.** The form writes through the same `SourceFile` the tab shows
  (undo history, autosave, conflict bar all work), and a hand edit in the tab shows in the form at once. Part B's
  recompile-on-write then re-renders the decks that use the theme: no extra machinery.
* **The form's field list comes from the catalog**, not from a hand-written table: a build step (a test) parses
  `SlideMage_setup.tex` and fails when a catalog name has no entry in the form's metadata (group, kind, label, tier,
  default, help) or an entry names something the catalog no longer has. That keeps form and framework from drifting
  (the framework changes: v10.x added hooks in nearly every release).

### 3.2 Kinds of field

colour (picker plus hex, contrast badge), palette-name (drop-down of the 21 + named colours, for roles), length (number
plus unit: pt, bp, cm, mm, ex, em, with the warning that ex/em are read in the layout profile's font), font size pair,
choice (profile, bullet, footnote marker), text (name), file (logo), switch (feature on/off) and group-of-options
(progress bar and the other optional features).

### 3.3 Live feedback

* **A fixed sample deck** (the calibration or stress deck the tests use, `tests/fixtures/template_stress/`, shipped as
  an example) rendered with the theme being edited, shown beside the form, re-rendered on every change after a
  pause. This is what makes the form worth more than the source tab: you see the title bar, a block of each kind, a
  list, a footnote, the footer.
* **Checks as badges**: contrast pairs (section 2, item 2), "the logo is a vector PDF", "the key is free", "this
  length would put the Top Margin above the title bar" (Top Margin >= the bar's derived bottom edge; the
  `tools/check_layout.py` rules that read margins from the PDF).

### 3.4 New theme from the shipped one

`New theme…` asks for key and name (key rules from `themes.py`, not a shipped key, not a file that exists), then copies
the **shipped** `SlideMage_template_slidemage.tex` (or Greyscale as a second starting point: it shows more settings) to
the project folder under the new key with the name line changed, and opens the form on it. `Copy to my project and edit`
(already built for installed themes) is the same machinery with another source. Logos go to
`schemes/scheme_<key_>/`.

### 3.5 Packaging (later, separate)

Export a personal theme as a `.smtheme` (`tools/make_theme_package.py` already packs a folder): needs `theme.toml`,
README, CHANGELOG, LICENCE from the identity fields. Not part of the first release of the form.

### 3.6 Editing a theme that is an installed package (the Graz case)

Graz is not a file in your project: it is `~/AppData/Roaming/SlideMage/themes/uni-graz/` (identical to the
`slidemage-theme-uni-graz` repository's `SlideMage_template_uni-graz.tex` today), installed from GitHub, updated from
there, with a `theme.toml`, CHANGELOG and releases. An edit has three possible destinations, and they differ in what
happens next:

| Route | What it does | Good for | Cost |
|---|---|---|---|
| **A. Copy to my project** (built in v0.14.62) | The files go into the project folder; the copy wins over the installed theme | A change that belongs to this project (a personal variant) | A copy that no longer follows the package's updates; it shadows the installed theme under the same key |
| **B. Edit the package's own repository** | The editor opens the theme source in its repository folder (`slidemage-theme-uni-graz`), and the release flow follows: version in `theme.toml`, CHANGELOG line, `make_theme_package.py`, GitHub release, then "Check for update" installs it | You, maintaining Graz | The editor must know where the repository is (a setting per theme key, "development folder", like the plugin dev path) |
| **C. Edit the installed copy in place** | Changes `themes/uni-graz/` directly | A quick try | The next update overwrites it; `theme.toml` and the package checks are not re-run |

Recommendation: A stays as built (it is the safe default and the one other users need), B is added for the author, with a
"Theme source folder" per key; C is not offered. Opening a Graz tab for editing then shows, at the top, where it will be
written ("uni-graz 1.1.1, your project's copy" or "from the repository D:\...\slidemage-theme-uni-graz"), so nobody edits
the wrong one.

### 3.7 Themes per view (instructor, during-course, after-course)

Request (2026-11-09 discussion): let the deck's views use different themes, so the same deck is dark for projection
(instructor view) and light for print (student views). It also gives Greyscale for printed handouts, and it decides the
question "dark as a mode or as a theme of its own" without forcing either: the mapping works for both.

How views work today (checked in the code): a deck that supports versions has three views (`deck_editor.VIEWS`); every
compile is a job for one view (`compiler.py`), with a generated wrapper file that defines `\deckversionoverride` and, in
several branches, already inlines a rewritten copy of the deck's preamble (it adds the language lines). The render key
already carries the template per render unit (`unit.template`). In the deck the template is `\input` *before*
`\deckversion[...]` runs, so TeX cannot choose the theme from the view; the app has to, when it builds the wrapper.

* **Where it is stored:** in the deck, as one comment-style settings line, for example
  `% SlideMage view themes: instructor=uni-graz:dark, during-course=uni-graz, after-course=uni-graz:grey`. The deck's own
  `\input{SlideMage_template_...}` line stays the default. A view without an entry, and a compile outside the app,
  use that default; the deck stays valid TeX.
* **A value is a template key, optionally `:<mode>`** (`uni-graz:dark`, `uni-graz:grey`): a mode of that theme
  (section 3.8). The wrapper defines `\SMModeOverride{<mode>}` for that view. Dark and grey are modes of the theme, not
  themes of their own, and the print/projection case works without a second package; a brand that wants a different dark
  design maps the view to a theme of its own instead. (An earlier draft wrote `+dark`; modes replace it.)
* **At compile time:** `wrapper_text` replaces the template key in the inlined preamble for a mapped view, and takes
  the inline-preamble branch for it (not plain `\input{deck}`).
* **One function for the template of a deck and view:** `slide_templates.template_for(preamble, view)`. Fourteen calls in ten files
  now call `detect_template(deck.preamble_text)` (compiler twice, deck_outline twice, preview_target,
  preview_thumbnails, slide_preview twice, add_slide, deck_actions, maintenance, source_view, update_all_previews
  twice); each takes the view and uses the new function. The colour menu of the toolbar (`theme_colors`) follows the
  view shown.
* **Render sharing:** `preview_equivalence` already isolates a template with another digest from the others. It must
  compare the effective template per view, so views with different themes are never shared; this costs more stored
  renders for such a deck.
* **Deck settings:** the template picker and the Dark slides checkbox become a table "Theme per view" (default, then one
  row per view). Decks without version support have no views and keep the single picker.
* **Limit:** a view is a content axis, print versus projection a medium axis. The same view in both media (instructor
  view as a dark projection and as a light handout) needs a one-off "theme for this build" in the Compile menu, which
  the mapping would then supply as the default. Not part of the first step.
* **Package rule:** a theme package holds exactly one template file (`themes.check_names`). A standalone "Graz dark" is
  therefore a second package with the palette duplicated, unless the package rules are relaxed (a second template and a
  shared include). Dark as `+dark` needs none of that.
* **Not checked yet:** the Presenter app (it presents the instructor view, so it should follow that entry).

Order: this is its own step, before the form: a small framework-free app change with focused tests (the twelve call
sites, the wrapper, equivalence, deck settings). The editor's per-view table then edits the same settings line.

**Built (v0.15.3, stage C0, 2026-11-10); what differs from the text above.** Develop had fewer `detect_template` calls than counted (five outside `slide_templates`). Instead of a view-aware function at each call site, `view_themes.preamble_for_view(preamble, view)` returns the preamble as a view sees it and is applied where a view meets a deck: `compiler.wrapper_text` (inline branch for a mapped view), `render_key.unit_for` (so the unit's preamble, template and key follow and `preview_equivalence` needs no change), `preview_target.render` / `render_text`, `batch_render`. `view_themes.template_for` / `templates_used` serve the toolbar colours and `maintenance.on_theme_installed`. The only mode is `dark` (the existing `\SMDarkMode` switch); an entry fully describes its view (an entry without `:dark` turns a dark deck default off). Deck settings, General, has the "Theme per view" table (decks without views skip it). Not done: the Compile-menu one-off; the Presenter app (not checked).

### 3.8 Colours: palette, roles, modes, and a clean transition

Decided in discussion (2026-11-09): no legacy aliases and no leftovers; dark is not hard-coded; Greyscale-like colour
variants are modes too.

**Why not rename `c_primary_dark`.** The real project's 1,416 slides use the colour names thousands of times
(`c_custom_red` 648, `c_primary_highlight` 624, `c_primary_dark` 494, `c_secondary_blue` 316, ...), and `c_primary_dark` has
two meanings in them: the ink of lines, rules and text on the canvas, and dark text on a coloured fill. In dark mode
the first must turn light and the second stay dark; Graz had to invent `c_true_black` to get both. Renaming one name
cannot fix that; separating the meanings does.

**Three layers.**

* **A. Palette: physical colours that never change with the mode.** The 21 slots, the theme's own colours, and
  `c_true_black` / `c_true_white` defined by the framework (no theme invents them). The slot names are slots, not
  descriptions (Greyscale makes `c_secondary_blue` grey, which is how a diagram in the `c_secondary_*` colours turns grey
  by itself). A tertiary colour defaults to its secondary mixed 50 % with white when the theme omits it.
* **B. Roles: what a colour is for.** About 35, in groups: surfaces (background, surface, surface line, process line),
  text (text, muted text, on-accent text, link, link underline, citation), chrome (title fill and text, footer,
  highlightframe, standout, bullet, alert, progress bar), the five block kinds (title fill, title text, body fill, body
  text), code (keyword, comment, panel, text, inline code) and the quote box. Nine exist as internal roles today
  (`\SMTitleBoxColor` and the others, plus the `SMColor...` names `\SMApplyColorRoles` resolves after the template).
* **C. Role names a slide can use** as real colour names: `c_text`, `c_canvas`, `c_card`, `c_line`, `c_text_muted`,
  `c_text_on_accent`, `c_link` (final names to be decided). `\SMApplyColorRoles`, the one place that already runs after the
  template, resolves them for the active mode with `\colorlet`. A slide author uses a role for "follow the theme and the
  mode" and a slot for "this exact colour".

**Modes: a list a theme declares, not light and dark.**

* A theme lists its modes in its header (`% SlideMage modes: light, dark, grey`, ids with labels). The framework knows no
  mode name. The first is the **base mode** (conventionally `light`); the others inherit everything they do not set.
* **Answer of 2026-11-10 (Q6): a mode is a colour scheme plus the logo**: palette overrides, role assignments, and which logo file the theme shows (a dark mode typically needs the white logo; a `\SMSetLogo{mode}{file}` data line, falling back to the base mode's logo). Fonts, margins, bullets and footnote markers still belong to the theme. **Q7:** a third derivation preset joins `dark` and `grey`: `colorblind` (palette remapped to a colour-vision-safe set with roles following; the exact set is chosen when CR is built and shown on the sample deck). The bullet as first written: a mode is a **colour scheme only**: palette overrides and role assignments. Fonts, margins, bullets and footnote
  markers are the theme's design, so a mode never changes them; that is the line between a mode and a theme. Greyscale as
  it ships (Latin Modern Roman, en dashes, numbered footnotes, taller title bar, wider margins, grey palette) stays a
  **theme**; a `grey` mode gives any theme a grey version of its own colours.
* **Data lines, no scopes:** `\SMSetRole{text}{dark}{c_true_white}` and `\SMSetColor{c_secondary_blue}{grey}{HTML}{8f8f8f}`;
  the mode id is an argument. Lines without a mode set the base mode. A reader needs no `\if` tracking, the form can
  add and remove a column by adding and removing lines, and Graz's 50 dark lines become about a dozen role lines.
* **Derivation presets as defaults, not as special cases:** the framework derives a mode's missing values when the
  mode says `derive=dark` (canvas the base's dark colour mixed about 17 % with white, text white, block title text black,
  surfaces from the canvas; Graz's `#2B2B2B` is that mixture of black) or `derive=grey` (every palette colour converted to
  its grey, roles follow). Any explicit line wins. A light-only theme gets a working dark mode by declaring
  `dark` with `derive=dark` and nothing else. The form shows derived cells in italics with a "set explicitly" action.
* **Choosing a mode:** the deck settings "Dark slides" checkbox becomes a drop-down of the theme's modes; a view's entry
  is `theme:mode` (3.7); a one-off Compile-menu choice can follow. The wrapper writes `\SMModeOverride{<mode>}`.
  The mode is part of the effective template of a render (render key, `preview_equivalence`): different modes are never
  shared.
* **The editor's table has one column per declared mode**, plus "Add mode" (from preset dark, grey, or a copy of the base)
  and "Remove mode". Contrast checks run for every column. Keep the number small (the presets give two).

**Clean transition (the project's own precedent).** `compat.py` already exists for exactly this: a BREAKING release with
a `Change` whose `migrate` rewrites the project atomically after a backup (`.slidemage/backups/<time>/compat/`),
idempotent, with a report; v10.0.0 renamed every framework file and v10.1.0 every Gotham name, frozen slide versions
included. This is the third such change.

* **Removed in the cut:** `\SMDarkMode`, the `% SlideMage dark mode: true` header flag and the deck's dark line, the
  flip of `c_primary_dark` in dark mode, the template-side `\ifdefined\SMDarkMode` pattern, the old `SMColor...`
  internals. Nothing is kept as an alias. A palette name keeps one meaning (a physical colour).
* **Migration of slides:** each use of the role-like names (`c_primary_dark`, `c_primary_white`, `c_custom_gray`, and the
  accents when used as text or lines) is rewritten by context to a role: lines, rules and text on the canvas to `c_text`;
  dark text on a coloured fill to `c_text_on_accent`; an ink-filled box with white text to `c_text` on `c_canvas`.
  What the rules cannot classify is left as it is **and listed in the compat report** with file and line.
* **Proof:** in the base mode the roles resolve to the same colours as before, so `tools/framework_regression.py` must
  show identical PDFs before and after for the decks of the real project. Dark and grey need a look: the report lists how
  many migrated uses appear in each mode, and a sample deck rendered in each mode is the review page.
* **Themes:** installed packages cannot be rewritten by the app; each releases a version for the new framework (Graz
  1.2.0, Innsbruck, MCI, Greyscale, the shipped templates) and the app refuses an older one with a message that offers
  the update (the theme update flow exists). Project templates with a hand-written dark block cannot be converted
  mechanically: they are reported, and Graz's pattern is converted by hand and released.
* **Cost, honestly:** one coordinated release (framework, app, four or five themes, the real project's slides) and a
  second-number version bump with a BREAKING paragraph, against the staged route with aliases that would have cost
  nothing at the start and something forever. The regression proof makes the base-mode part checkable.

**Built: CR slice F1, the framework side (v0.15.9, branch `feat/color-roles-framework`).** Additive: nothing is removed, so
this is not the BREAKING release yet; every old name and flag still works, and in the base mode the PDFs are identical
(tools/framework_regression.py, 873 pages). It lives in `SlideMage_setup.tex` (section "Colour modes and role colours"), is
resolved by `\SMApplyColorRoles` (which calls `\SM@applymode`) and is read by the theme and the base.

* **Data lines, as in the plan:** `\SMDeclareMode{id}{derive}` (the first declared is the base mode), `\SMSetRole{role}{mode}{colour}`,
  `\SMSetColor{name}{mode}{model}{spec}`. A line of a mode that is not the active one does nothing.
* **How a deck chooses the mode (changed from the text above):** the wrapper defines the macro `\SMModeOverride` before the
  template (`\newcommand{\SMModeOverride}{dark}`), like `\SMDarkMode`, not a call. Order: `\SMModeOverride`, else `dark` when
  `\SMDarkMode` is defined, else the base mode. `view_themes` does not write it yet (its non-dark modes still have no effect).
* **Presets** (`derive`): `dark` (canvas and card from `c_primary_dark` mixed 17 % and 23 % with white; text, line and link white;
  text on an accent black), `grey` (every palette colour to its grey), `colorblind` (Okabe-Ito accents). Order: preset, palette
  lines, role lines, so an explicit line wins.
* **Roles with colour names:** `c_text`, `c_canvas`, `c_card`, `c_line`, `c_text_muted`, `c_text_on_accent`, `c_link`. The
  framework reads them for body text, footnotes, links, buttons, the canvas and `SMCard`. **Roles that set a catalog hook:**
  `title_fill`, `title_text`, `footer_fill`, `footer_text`, `bullet`, `alert`, `progress`, `block_title_text`.
  `c_true_black` and `c_true_white` are framework colours.
* **Not done (the next slices):** the other ~20 roles (block fills and bodies, code, quote box, link underline, standout...);
  moving the framework's remaining `c_primary_dark` uses (table rules, block-body text, bullets in blocks) to roles; the
  app side (the wrapper writing `\SMModeOverride`, a mode drop-down, the header `% SlideMage modes:` line); the slide migration
  with `compat.py`; removing `\SMDarkMode` and the flip of `c_primary_dark`; the themes' releases. In a non-base mode a slide that
  uses `c_primary_dark` as ink does not turn light until it is migrated to `c_text`.

**Built: CR slice F2 (v0.15.10, branch `feat/color-roles-framework-2`, on top of F1).** More roles, same rules (additive, base
mode identical: 873 pages of the manual set, 292 of the manual under Uni Graz, light and with `\SMDarkMode`): the five block title
fills (`block_title_fill`, `alerted_`, `example_`, `reference_`, `info_block_title_fill`), `block_body_fill` (also SMProcess),
`block_body_text` (text and bullets in a block, SMProcess text), `link_underline`, `code_keyword`, `code_comment`, `code_panel`,
`code_text`, and the per-kind title text hooks. The framework's frame-start ink is `c_text`. Left for F3: highlightframe and
standout fills, the quote box, table rules and the other `c_primary_dark` uses inside the framework (they are unmapped
hard-coded names; each is a decision about which role it is).

**Built: CR slice F3 (v0.15.12, branch `feat/color-roles-framework-3`).** The framework's remaining hard-coded colours are roles: `highlight_fill`, `standout_fill`, `standout_text`, `quote_attribution`, `table_rule` (inside a block: `block_body_text`), `image_border`, `marker` (SMHighlight, SMDottedHighlight, warning sign), `citation`, `strip_fill` (its text is `c_text_on_accent`). What is left in the framework's code is the white text of a button and the red of the DRAFT watermark. Base mode identical: 873 pages of the manual set, 292 of the manual under Uni Graz, light and with \SMDarkMode. This ends the framework-only slices of CR; what follows needs the app: the wrapper writing \SMModeOverride and the mode drop-down, the `% SlideMage modes:` header, then the slide migration and the BREAKING cut.

## 4. Staging and what each stage needs

| Stage | Contents | Depends on |
|---|---|---|
| C0 | **Themes per view** (section 3.7): the settings line, `template_for(preamble, view)` at the fourteen call sites, the wrapper, equivalence, the deck settings table; optional `+dark` | nothing; independent of the form |
| CR | **Colours cut** (section 3.8): palette, roles, modes; the BREAKING release with the compat migration of slides and project templates; Graz 1.2.0 and the other themes; toolbar and `theme_colors` read roles | C0 (the per-view mode value); the framework regression proof |
| C1 | The reader and in-place writer (data lines after CR; the scope-aware reader only for older files) with the **Graz round-trip tests** first; then identity, palette (with the theme's own colours) and contrast badges, logo, 9 colour roles, code colours, **Light / Dark columns** for the colours Graz overrides, footnote marker; "New theme…" from the shipped one; live sample render in light and dark | the field metadata and catalog test; `theme-color-roles` for the full role list |
| C2 | Layout profile, sizes, margins, title bar, footer, bullets, citation format; route B (theme source folder) for installed themes | C1's editing core |
| C3 | "Advanced": tier 3 fields, optional features; a "derive dark mode from the light palette" helper; the framework hooks that remove Graz's raw dark-mode TeX (block title text, inline code, standout) | the framework gaps above |
| C4 | `.smtheme` export | C1 |

Where it lives: a tab beside the source tab for a theme file, "Design…" on a personal theme's row, and "New theme…" next
to "Add from file…" in Settings → Themes.

## 5. Questions for the user

1. Is the tier order right now that dark mode is in tier 1 (because of Graz), and **footnote marker / bullet symbol**
   in tier 2?
1a. **Graz**: which route (3.6)? A as built, plus B for you as the author (my recommendation), or something else?
    And is "the form must round-trip Graz byte for byte" the right first acceptance test?
2. Form **beside** the source tab (split, both live) or a **separate designer tab** that hides the source?
3. Should the form be allowed to write the marked block when a theme was hand-written with its own ordering (my default),
   or only edit lines that already exist and refuse the rest?
4. The sample deck for the live render: the stress-test deck as it is, or a purpose-written "theme sample" deck (title,
   section, blocks of each kind, list, footnote, quote, code)? The second costs one new deck and is nicer.
5. Which **framework hooks** to add first from "beyond the catalog" (block title text, link colours are the two the
   Innsbruck work already needs)? They belong to `theme-color-roles`.
6. **Modes (3.8):** is "a mode is colours only; fonts, margins and bullets are the theme" the right line, so Greyscale as shipped stays a theme and a `grey` mode is separate?
7. **Derived modes:** live defaults in TeX (a theme that declares `dark` with `derive=dark` works at once) with explicit lines overriding, or only explicit values written by the editor?
8. **Clean cut:** one BREAKING release with the compat migration of slides and the regression proof, and the themes released with it. Agreed, including that old installed themes are refused until updated?
9. **Role names for slides:** `c_text`, `c_canvas`, `c_card`, `c_line`, `c_text_muted`, `c_text_on_accent`, `c_link`; changes?
