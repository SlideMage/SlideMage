# Plan: a theme editor (Part C of the handover task `personal-themes-extensions`)

Status: **C0, CR, the form stage C1, C2a and the form's look merged; C2b (margin marks) built, C2c next.** Parts A and B
(list personal themes in Settings → Extensions; edit a theme's `.tex` in a centre tab; copy an installed theme into the
project) are in v0.14.62 (PR SlideMage/SlideMage#145, merged). All nine design questions answered 2026-11-10 (section 0);
stage C0 built (v0.15.3), stage CR v0.15.9 to v0.16.5, C1a v0.16.6 (section 4). Section 0 below is the state of
2026-11-09/10 and is kept for the record.

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
* **Acceptance test, Graz.** The Graz file is the golden fixture. *(Changed when built, C1a: the file is NOT copied into
  `tests/fixtures/`. Its TeX is LPPL, but the theme's LICENSE says the University's corporate design it reproduces, its
  palette among it, is not covered and the theme must not be published; this repository is public. The tests run on a
  test theme of the same shape with made-up colours, `tests/fixtures/theme_files/`, and on the real Graz, uni-ibk and
  MCI files when `SLIDEMAGE_REAL_THEMES` names them.)* (1) Read it and write it back with nothing changed: **byte-identical**. (2) Change
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

* **Slide pictures that show what a field changes (user's requirement, 2026-11-10).** Next to every group of fields the
  form shows a picture of a slide, so nobody has to guess what a setting is: while a field has the focus, or the
  mouse is over it, the picture marks the element or the margin it changes (the title bar, the Top Margin, the text
  margins, the footer box, a block title, the bullet, the footnote area, the logo) and the picture is the real
  render of the sample deck with the theme as edited, so the change shows as it is made. Design notes:
  one render per page of the sample deck (title bar and footer; a block of each kind; list and footnote; a code
  panel; a quote frame; a table) so each field group points at the page that shows its element; the marks are
  overlays drawn over the rendered page from geometry (the hooks' values for margins and paddings, which
  `tests/test_hook_geometry.py` already measures against the PDF; boxes of the other elements read from the PDF's
  drawing operations or from a pass of the sample deck that writes the boxes of its elements to a file), never
  baked into the render, so they follow the values as they change and need no second compile; a margin field shows
  its measure as a dimension line with the value; for a colour field the picture dims everything but the
  elements that use the role (the role table of section 3.8 says which); in a mode column the page is rendered in
  that mode. A static, annotated picture per field is the fallback where a live mark is not possible. Stage: the
  picture of the colour roles belongs to C1, the margins and layout fields to C2; the overlay mechanism is built in C1.

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

**Built: CR app side, step 1 (v0.15.13, branch `feat/color-modes-app`).** `deck_settings.template_modes` reads `% SlideMage modes: light, dark, grey=Greyscale` from a template's header (first = base mode; the older `dark mode: true` = light and dark); `DeckSettings.mode` and `set_mode` write \SMModeOverride before the template (`dark` keeps \SMDarkMode); `view_themes.preamble_for_view` gives a view any mode; Deck settings has a Colours drop-down in place of the Dark slides check box and a mode drop-down per view. Not done: the shipped templates declare no modes (they must not before slides are migrated to roles, or a dark deck shows invisible ink); the Compile-menu one-off mode; the toolbar colour list and `theme_colors` reading roles; the Presenter app.

**Built: CR migration of slides (v0.15.14, branch `feat/color-roles-migration`).** `compat_color_roles.py`, registered in `compat.CHANGES` as `colour-roles-in-slides` (APPEARANCE: listed in Info -> Project compatibility, Update project runs it; not loud, because nothing looks different in the base mode). It reads each live use of `c_primary_dark` by its bracket context (a TikZ option list `[...]` or `key={...}`, a colour command's argument, a `\foreach` list) and rewrites it: ink of lines, arrows, shapes, axis plots and text on the canvas -> `c_text`; `text=` or a bare colour on a node whose `fill=` is a palette colour (not ink, not white) -> `c_text_on_accent`; `fill=c_primary_dark(!N)` -> `c_text(!N)` with that list's `text=white|c_primary_white` -> `c_canvas`; `fill=white|c_primary_white` of a shape drawn in ink -> `c_canvas`; `\color`, `\textcolor`, `\arrayrulecolor`, `\pagecolor`, `fg=` -> `c_text` (`c_text_on_accent` inside a node with a coloured fill). Left alone: comments, colour lists, `c_primary_white` elsewhere (white does not flip), templates (themes keep a physical palette; their dark blocks are the cut's job). Reported with file and line, unchanged: `c_custom_gray` outside a list (link or muted text: a person decides), `\colorbox`, `\fcolorbox`, cell and row colours, `\colorlet`, `\definecolor`, `bg=`, unknown TikZ keys. Scope as `compat_own_theme` (slides with frozen versions, snippets, decks, decks/archive, root .tex except templates); idempotent. On the real project: 34 files, 151 uses (114 `c_text`, 34 `c_canvas`, 3 `c_text_on_accent`), nothing left unclassified apart from the palette slide's list. **Proof:** six real decks (Masterdeck-Publishing, Ibk-AWP, FM2, IA2, Grundlagen, manual; instructor version) compiled from a copy of the project before and after the migration with `tools/framework_regression.py`: 2186 pages, all identical (2026-11-11). Not done: running it on `D:\uniCLOUD\Slidemaster` itself (the user's Update project click), the dark-mode review page, the BREAKING cut.

**Built: the CR cut (v0.16.0, BREAKING, branch `feat/color-roles-cut`).** Framework: `\SM@activemode` reads only `\SMModeOverride`; a deck that still defines `\SMDarkMode` stops with a `\PackageError` naming the replacement. Four more roles, each off or equal to today in the base mode: `process_line` (a border around SMProcess, `none` unless set), `inline_code` (colours `\SMCode`/`\SMCmd` only in body text, so a title bar, block title or `\textcolor` keeps its colour), `button_text` (white) and `strip_text` (`c_text_on_accent`). App: `DeckSettings` has one `mode` (no `dark_mode`); `set_mode` writes `\SMModeOverride` for dark too; `set_dark_mode`, `DARK_MODE_RE` and the `% SlideMage dark mode: true` header are gone; `view_themes` writes only the mode line. Compat: `compat_color_cut.py`, change `dark-switch-removed` (BREAKS): decks' switch to `\newcommand{\SMModeOverride}{dark}` (dropped next to an existing mode line), every other live `\SMDarkMode` or dark header in templates, project macros, slides and snippets reported by line. Themes: `packages.PackageKind.check_contents` (new) with `themes.check_contents`: a theme whose template uses `\SMDarkMode` in live code is not installed, not on TeX's path, and listed as "not usable" with `needs_update` (Settings keeps Check for update). The example project's three slides were migrated (colour-roles-in-slides). **Proof:** the manual set (manual, copy, Greyscale, Uni Graz 1.1.1; instructor and after-course) with develop's framework against this one: 786 pages identical. **Uni Graz 1.2.0** (theme repo, branch `release/1.2.0`): the two `\ifdefined\SMDarkMode` blocks became `\SMDeclareMode` / `\SMSetRole` / `\SMSetColor` lines, requires SlideMage >= 0.16.0. The manual in Graz dark, 1.1.1 on develop against 1.2.0 on this branch: 4 of 95 pages differ, all intended: card headings keep the light font (a mode changes colours only), migrated slides' arrows turn white, the quick-reference slide names the new line, resampling noise on one screenshot (the step strip's text was black on the dark strip until `strip_text` existed). Not converted: Graz's `normal text` background for SlideMage's built-in title page. **Release order:** Graz 1.2.0 must be published together with v0.16.0, or decks using Uni Graz stop compiling (1.1.1 is refused).

**Built: CR, the shipped templates' modes (v0.16.2, branch `feat/shipped-modes`).** `SlideMage_template_slidemage.tex` and `SlideMage_template_greyscale.tex` declare `light` (base) and `dark` (the dark preset), in the header and with \SMDeclareMode, and add dark-only role lines where the preset left an accent too dark on the canvas (#444444 and #484848; the highlight blue was 1.7:1, Greyscale's greys 1.2:1): SlideMage bullets, table rules and image borders `c_secondary_blue!60!white` (4.9:1), alert `c_secondary_orange`, marker `c_secondary_red!60!white`; Greyscale a dark title bar with white title and standout text, bullets, alert, rules and borders `c_secondary_violet` (4.9:1), marker `c_tertiary_violet`. The palette is not changed per mode (the slides' callout circles put white text on `c_primary_highlight`), so slide text in a palette colour stays that colour; in the manual that is the `c_primary_highlight` text of a few slides and the named-colour demo, dim in dark. Proof: light identical, 873 pages of the manual set; dark manual under each template reviewed page by page. Left in CR: toolbar and `theme_colors` reading roles, the Compile-menu one-off mode, accents as text in slides (a migration rule or a role such as `c_accent_text`, the user's call).

**Built: CR, the Color menu reads roles (v0.16.3, branch `feat/toolbar-roles`, on top of #165).** `theme_colors` reads \SMDeclareMode, \SMSetColor and \SMSetRole besides \definecolor and \colorlet (now with xcolor mixes, `a!p!b`, and any colour name, so Graz's `c_graz_dark_canvas` resolves) and resolves a mode as \SM@applymode does: preset (dark's derived roles, grey's conversion 0.3/0.59/0.11, colorblind's accents), the mode's palette lines, then each role from its line, else the derived value, else the base source; an undeclared mode gets no preset and only its own lines, as in TeX. `theme_colors(template, root, mode)` and `swatches(..., mode)`; `view_themes.mode_for(preamble, view)`. The source view's Color menu leads with the seven role colours under "Follows the colour mode" (each with what it is for), then "Palette", in the mode of the deck and the view shown. Proof: `tests/test_theme_colors_tex.py` prints every role and ten palette colours from LuaLaTeX and compares (+-1 per channel) for a test template in six modes plus an undeclared one and for both shipped templates light and dark; Uni Graz 1.2.0 agrees as well (light and dark, checked once by hand). Left in CR: the Compile-menu one-off mode; accents as text in slides.

**Built: CR, the one-off mode in the Compile menu (v0.16.4, branch `feat/compile-mode`).** `CompileJob.mode`: a mode id of the view's template; `compiler.wrapper_text` applies it after the view's theme (`with_mode`: \SMModeOverride written, removed for the base mode), so the wrapper inlines the preamble and the deck is not touched. The jobname gets `-<mode>` (a literal `\deckoutputfolder` file name `-<mode>` on its stem), so the view's usual PDF and its page compiles stay apart; `job_label` adds " · <mode> colours" and `deck_pdfs` looks for each view's other modes. `compiler.other_modes(ctx, deck, view)` lists the template's modes without the one the view compiles in. Command `compile:mode` in the Compile caret menu and Build -> PDF, after "All views": "Current view in Dark slides" when there is one other mode (compiles at once), "Current view in another colour mode…" with a choice when there are several, disabled when the template declares none. Not offered for chapters, presenter, page compiles or several decks (a whole-view build of the current deck). Left in CR: accents as text in slides.

**Built: CR, accents as text in dark mode (v0.16.5, branch `feat/dark-accents`; Uni Graz 1.2.1).** Decided by the counts, not by a migration: the example's live slides write palette accents as text 25 times (17 of them `c_primary_highlight`), the real project's 1022 about 260 times over nine colours (`c_custom_red` 90, `c_secondary_blue` 52, `c_secondary_red` 32, `c_primary_highlight` 21, ...). Under Graz dark only `c_custom_red` (2.2:1) and `c_custom_brown` (2.4:1) are too dark; no slide of either project fills with them, and the only white-on-accent fill is the example's two callout nodes on `c_primary_highlight`. So each theme gives those colours a dark-mode value with \SMSetColor (the plan's rule that a palette name is one colour gives way to the existing per-mode palette lines Graz already used for its tertiaries), with no compat rule and no new role: SlideMage highlight 8BBCEC, custom red FF9090, green 7FD07F, brown E0B060 (its bullet, rule, border and marker lines removed: those roles are made of these colours); Greyscale highlight C7C7C7 and custom greys DEDEDE, D0D0D0, C4C4C4, BABABA (its five accent role lines removed); Graz 1.2.1 custom red FF6B6B, brown D19A5C. The callouts write `text=c_canvas` (white in light). The dark preset also derives `button_text` black (a button is filled with the link colour, white in dark: the shipped templates' buttons were white on white) and `quote_attribution` muted. Code keywords keep the dark blue (\colorlet copies it before the mode applies; the code panel stays light). Proof: light identical (manual set, and the manual under Graz 1.2.0 vs 1.2.1); dark manuals reviewed. Left: a theme's own accents that slides fill behind white text would need a role; none seen yet.

## 4. Staging and what each stage needs

| Stage | Contents | Depends on |
|---|---|---|
| C0 | **Themes per view** (section 3.7): the settings line, `template_for(preamble, view)` at the fourteen call sites, the wrapper, equivalence, the deck settings table; optional `+dark` | nothing; independent of the form |
| CR | **Colours cut** (section 3.8): palette, roles, modes; the BREAKING release with the compat migration of slides and project templates; Graz 1.2.0 and the other themes; toolbar and `theme_colors` read roles | C0 (the per-view mode value); the framework regression proof |
| C1 | The reader and in-place writer (data lines after CR; the scope-aware reader only for older files) with the **Graz round-trip tests** first; then identity, palette (with the theme's own colours) and contrast badges, logo, 9 colour roles, code colours, **Light / Dark columns** for the colours Graz overrides, footnote marker; "New theme…" from the shipped one; live sample render in light and dark | the field metadata and catalog test; `theme-color-roles` for the full role list |
| C2 | Layout profile, sizes, margins, title bar, footer, bullets, citation format; route B (theme source folder) for installed themes | C1's editing core |
| C3 | "Advanced": tier 3 fields, optional features; a "derive dark mode from the light palette" helper; the framework hooks that remove Graz's raw dark-mode TeX (block title text, inline code, standout) | the framework gaps above |
| C4 | `.smtheme` export | C1 |

The user split C1 (2026-11-11): **C1a** the reader and writer with the field list and the round-trip tests, no window;
**C1b** the form tab beside the source tab (identity, palette with own colours and contrast badges, roles per mode, code
colours, logo, footnote marker); **C1c** "New theme…", the theme sample deck, the live render and the slide pictures of
section 3.3.

**Built: C1a (v0.16.6, branch `feat/theme-form-core`).** `src/slidemage/theme_file.py`: `ThemeFile(text)` reads every
setting at the top level (not inside another command's argument) with its kind, mode, value span, line, place (before
the setup file, the settings, after the base) and whether it sits in a conditional; `editable` = in the settings part
and outside `\if ... \fi` (the layout profile: before the setup file; the two header lines always). `find`/`value`
(a HTML colour as "#rrggbb"), `modes()`, `own_colours()`, `beyond()` (0-based lines of live code the form does not edit),
`set(key, value, mode)` and `remove(key, mode)`. Keys: a hook's name, a colour's name, `role:<id>` and `mode:<id>`,
`header:name`, `header:modes`; a `\SMSetColor` line is its colour's name with the mode. In place means only the value:
`{HTML}{..}` of a colour (upper-case hex stays upper case), the braced argument otherwise; `#rrggbb` on a `\colorlet` or
an expression on a `\definecolor` rewrites that command and keeps the comment. New lines: the header after SPDX and
header lines; the layout profile right before `\input{SlideMage_setup}`; a mode line after the theme's last mode line
(a declaration after its last declaration); everything else in the marked block before `\input{SlideMage_base}`, sorted
by the catalog's order with declarations and then mode lines last. Removing the block's last line removes the block. The
file's line ends stay ("\r\n" or "\n"). `src/slidemage/theme_fields.py`: `FIELDS`, one `Field(name, group, kind,
label, tier, hook, args, choices)` per catalog setting (151 fields for the 162 catalog names, 43 of them roles: the 13
hook macros that are a role's base value are covered by that role's field, which names the macro in `hook`; plus the
two header lines); `catalog(setup_text)` reads defaults, help texts and the roles' base sources from the setup file;
`order()`. Tests: `tests/test_theme_fields.py` (the field list against the catalog and against
`test_template_catalog.py`'s own reading), `tests/test_theme_file.py` (the five acceptance checks above on the shipped
templates, the stress template and the two shape fixtures; line ends; a TeX compile of an edited template with
`SLIDEMAGE_TEX_TESTS=1`). Run with `SLIDEMAGE_REAL_THEMES` on Graz 1.2.1, uni-ibk and MCI: all pass. Not done: the
old scope-aware reader for `\ifdefined\SMDarkMode` files (v0.16.0 refuses them, so the form never sees one); the
footnote marker's two forms (`\SMSetFootnoteMarkers`, `\SMFootnoteMark`) are two fields, merged into one in the form.

**Built: C1b (v0.16.7, branch `feat/theme-form-tab`).** `src/slidemage/theme_form_model.py`: `ThemeModel(text, root,
key, setup_text)`, no Qt. Columns are the declared modes (one "Colours" column for a theme without modes). Each cell
has what the theme writes (`palette_written`, `role_written`; None = it follows) and what it comes to (`palette_hex`,
`resolve("role:<id>", mode)`), resolved like `\SM@applymode`: a mode's line, else its preset (the dark preset's roles
are read from the setup file's `\SM@derived@...` lines), else the base; a hook role's base value is its macro, followed
through (`\SMTitleBoxColor`, `\SMBlockTitleTextColor`); a theme's own `\colorlet` of an optional colour (code keyword)
keeps the base palette's colour in every mode, the framework's default is made after the mode's palette lines. Edits:
`set_palette`, `set_role` (base + hook: the macro; a mode: `\SMSetRole`; a role without a hook has no base value in a
theme without modes), `add_mode` (a theme without modes gets `light` first; header and `\SMDeclareMode`),
`remove_mode` (every line of it), `add_own_colour`, `set_name`, `set_value`, `import_logo` (into
`schemes/scheme_<key_>/`), `set_footnote_style` (symbols, boxed, dice via `\SMSetFootnoteMarkers`; numbers via
`\SMFootnoteMark`; a theme's own mark shows as "custom"). `checks(mode)`: 16 WCAG pairs (`CHECKS`), text 4.5:1, the
link underline 3:1. `theme_colors.theme_colors_for_text` reads an unsaved buffer. `src/slidemage/ui/workspace/theme_form.py`:
`ThemeForm(editor, path, root, setup_path)`, a scrolling column of cards (intro with the count of lines beyond the
form and "Show them in the source", name and modes, contrast badges, palette, the four role groups of
`ROLE_SECTIONS`, code panels, logo, footnote markers); a cell is a swatch (colour picker) plus a field (a drop-down of
the colour names for roles), an empty field follows and its grey text says what it takes. Every edit runs through
`apply()`: model edit, then `editor.patch_text` (one undo step, autosave and the conflict bar as for typing); typing
in the source refreshes the form after 400 ms; the cards are rebuilt only when the modes, own colours, lines beyond
the form or the footnote style change. `SourceFile` puts it in a splitter beside the editor for any
`SlideMage_template_<key>.tex` that is not a slide; "Hide form" / "Show form" on its status line, remembered
(`theme_form_shown`). Tests: `tests/test_theme_form_model.py`, `tests/test_theme_form_gui.py`. **Finding:** the
check shows Greyscale's dark mode with code commands at 1.4:1 (C7C7C7 on EBEBEB): it sets no `SMCodeKeywordColor`,
so the framework makes it from `c_primary_highlight` after the dark palette line; the SlideMage template avoids this
with a `\colorlet` before its modes. Not fixed here (a `latex/` change). Not done (C1c): "New theme…", the sample
deck and the live render with the slide pictures of 3.3.

**Built: C1c, first part (v0.16.9, branch `feat/theme-form-render`).** C1c is done in two parts: (1) "New theme…", the
sample deck and its live render; (2) the marks on the sample slides for the field in focus (overlays from geometry,
role dimming) — not built yet. Part 1: `src/slidemage/assets/theme_sample/theme-sample.tex` (+ `snippet.tex`), seven
pages (`theme_sample.PAGES`: title frame; title bar, lists, link, `\alert`, inline code, footnote, source; the five
block kinds; code panel; highlight, standout and quote frames); SlideMage fills its `%MODE%` and `%THEME%` lines (the
`\SMModeOverride` line, `\graphicspath` of the project root, `\input` of the theme). `src/slidemage/theme_sample.py`:
`render(ctx, text, key, mode, cancel=)` writes the buffer as `SlideMage_template_<key>.tex`, the deck and the snippet
into `.build/theme-sample/<key>/<mode>/`, puts that folder first on TEXINPUTS (then the project root, the framework,
what `compiler.build_env` set) and runs latexmk with lualatex (about 8 s from cold); `SampleResult(pdf, log, mode)`.
`src/slidemage/ui/workspace/theme_sample_view.py`: `ThemeSampleView` above the form in a vertical splitter on the
right of the source tab (`SourceFile.theme_side`; "Hide form" hides both): mode picker (labels from the header line),
page arrows, the page scaled to the panel (PyMuPDF at 110 dpi), status line (the TeX error's first line, the rest in
the tooltip). Renders 1.2 s after a buffer change, in a thread; a change during a render stops it (CancelToken) and
renders again after; nothing while hidden, catches up on show. "New theme…" (section 3.4): `themes.SHIPPED_STARTS`,
`themes.check_new_key` (key rules, not shipped, not in the project, not installed), `themes.new_theme(key, name, root,
start)` (the shipped template through `ThemeFile`, name line set or added); Settings → Extensions → Themes →
"New theme…" asks name, key (filled from the name until edited, checked as typed) and start, closes the sheet, then
`WorkspaceWindow.new_theme` makes it, opens it with the form and reloads the decks. Tests: `tests/test_theme_sample.py`
(the deck render in light and dark with `SLIDEMAGE_TEX_TESTS=1`, the panel with a fake render, New theme).

**Built: C1c, second part (v0.16.16, branch `feat/theme-form-marks`).** The colour part of the slide pictures of 3.3,
done without geometry: `src/slidemage/theme_probe.py` renders the sample deck once more with every colour role (kind
"role": the 43 roles and the hook `\SMHighlightTitleTextColor`) or every palette colour (kind "palette": the 21 and the
theme's own) set to a colour of its own (`PROBES`: 60 colours on a 0x10/0x50/0x90/0xD0 grid, no greys), as
`\SMSetRole` / `\SMSetColor` lines of the mode right before `\input{SlideMage_base}` of a copy of the buffer (a theme
without modes gets `\SMDeclareMode{probe}{}` first), and `usage_map` reads every pixel within 10 per channel of a probe
colour (at twice the panel's 110 dpi, folded down, so text strokes count) into a `UsageMap` (one byte per pixel and
page). `ThemeSampleView.show_usage(kind, name, mode)` switches to the field's mode, makes the map of that kind and mode
once per text (a thread, about 9 s plus 1 s reading), turns to the first page using the colour, and draws the page
dimmed (black at 65 %) with the colour's pixels on top, one pixel wider; the line under it says on which pages it is
used, or that the sample does not use it. The form's palette, role and code cells report focus and hover
(`ThemeForm.on_usage`, `on_usage_cleared`; the mouse over a cell wins while it is there). Seen: Block title fill lights
only the block's violet bar on page 3; Body text in dark only the white body text. Tests: `tests/test_theme_probe.py`
(the real probe with `SLIDEMAGE_TEX_TESTS=1`: block title fill on page 3 only, code panel on page 4 only). Not done
(C2, as the plan stages it): the dimension lines and marks of margins and paddings, which need the hooks' geometry.
Limits: a colour a slide writes by palette name directly (`\textcolor{c_primary_highlight}`) shows under the palette
kind, not the role kind; an image whose pixels happen to have a probe colour would light up too.

C2 is done in three parts: **C2a** the layout fields (tier 2 of section 2), **C2b** the marks of margins and paddings on
the sample slides (dimension lines from the hooks' geometry), **C2c** route B (a theme's source folder for installed
themes, section 3.6).

**Built: C2a (v0.16.17, branch `feat/theme-form-layout`).** `theme_form_model.LAYOUT_SECTIONS`: six cards with every
tier-2 field (a test checks none is missing): Font and text sizes (`SMLayoutProfile`, `SMBodyFontSize`, `SMCodeSize`),
Margins (`SMTopMargin`, `SMTextMarginLeft/Right`, `SMBlockSideMargin`), Title bar (the three paddings,
`SMFrameSubtitleSep`, `SMFrameSubtitleStrutEnd`), Footer and footnotes (`SMFooterBoxHeight`, the three size pairs,
`SMFootlineSidePadding`, `SMFootnoteFooterGap`, `SMFootnoteSep`), Lists (`SMBulletSymbol`), Citations
(`SMCitationFormat`). Widgets: profile and citation format as editable drop-downs (`layout_profiles(root)`: bundled,
then the project's and the framework's `SlideMage_layout_*.tex`; `citation_formats()`: bundled and installed), lengths
as fields checked when left (`check_length`: number plus unit, or a multiple of `\paperheight`, `\linewidth` and the
like; a bad value is not written and the field says why), size pairs as two numbers in pt (`parse_size_pair`,
`format_size_pair`; another form shows as raw TeX), the bullet as a choice (`BULLETS`, or "the theme's own"),
`SMFrameSubtitleSep` as raw TeX. Grey text shows the framework's value. `ThemeForm.layout_fields` keeps the widgets
by key. Tests: `tests/test_theme_form_layout.py`. Not done: a check that the Top Margin lies below the title bar
(needs the derived geometry: C2b).

**The form's look (v0.16.18, branch `feat/theme-form-look`).** The look was no stage of the plan; the user asked for
a mockup (2026-11-12, a Design canvas: https://claude.ai/artifact/6e2dFeq4NqZ6VYfdFSFfmT) and, after asking how an
open list of modes fits ("Proposed: any number of modes"), chose it. Built: `src/slidemage/ui/workspace/theme_workspace.py`,
`ThemeWorkspace` (the theme part of `SourceFile`, `SourceFile.theme_side`): `ModeBar` (one button per declared mode
with "base" or "<preset> preset · n set", "+ Add mode…"), a Form / Split / Source `SegmentedControl` (remembered as
`theme_view`), one splitter with the editor, the sample slides and the form, shown per view. `ThemeForm` is a `QWidget`
with a `QTabBar` and five scrolling pages (Identity, Colours, Layout, Logo & notes, Advanced; Advanced says C3 is to
come), shows `form.mode` only (`set_mode`; `on_structure` tells the workspace), and on Colours: the mode's heading, a
contrast `Chip` for that mode (details on "Show all 16"; "Other modes: n below" picks the first such mode), the palette
filtered by `ThemeModel.palette_matters` ("Show all 21"), folding groups for the four role sections and the code panels
(a count of what is set; "Title bar and footer" open at first). `_Cell` gained the provenance tag
(`ThemeModel.provenance`: set here / set in the theme / dark, grey or colour-blind preset / from <base> / framework
default), Reset, and the per-mode strip (`ThemeModel.strip`, the picked mode ringed). Lengths are a number and a unit
(`split_length`, `UNITS`; another form stays raw TeX). `ThemeSampleView` follows the mode bar (`follow_mode_bar`,
`set_mode`) and has a page-thumbnail strip with a dot under the pages using the focused colour. The Top Margin's
dimension line and the "below the title bar" check of the mockup's Layout screen are C2b.

**Built: C2b (v0.16.19, branch `feat/theme-form-measures`).** No new TeX: SlideMage_base already writes the
geometric hooks into the PDF's info dictionary in bp (for check_layout and test_hook_geometry), so
`theme_sample.read_geometry(pdf)` gives every hook as rendered (ex and em worked out in their fonts, the derived
`SMTitleBarBottom`, `SMLeftMargin` = the title's left padding) plus the page size; `SampleResult.geometry`,
`ThemeSampleView.geometry` and `geometry_changed`. `src/slidemage/theme_measures.py`: `to_bp(value, key, geometry,
rendered_value)` (absolute units exactly; ex/em scaled from the rendered value in the same unit, else None),
`marks(key, value_bp, geometry)` -> `Mark`s for `MEASURED` (Top Margin: line + arrow + the title bar's bottom;
text margins: both lines; footer box: a frame; title bar paddings, logo height and padding: the bar's bottom edge,
the title's left edge, the logo padding, with "after the next render" where the edge is derived), and
`title_bar_check(top_bp, geometry)`. `ThemeSampleView.show_measure(key, value_bp)` / `clear_measure()` paints the
marks over the page (`_paint_marks`, after the colour dimming) and turns from the title, standout and quote frames
to page 2. The form's length fields report focus and every keystroke (`ThemeForm.on_measure`,
`on_measure_cleared`, `geometry`), wired in `ThemeWorkspace`; the Top Margin field shows the check under it.
Tests: `tests/test_theme_measures.py` (with `SLIDEMAGE_TEX_TESTS=1` a real render's geometry). Not done: marks for
the block side margin and the footnote spacing (the geometry has them, but no element of the sample deck is placed
by them alone); size pairs (font sizes) get no mark.


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
