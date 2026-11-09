# Plan: a theme editor (Part C of the handover task `personal-themes-extensions`)

Status: **draft for the user's review, nothing built.** Parts A and B (list personal themes in Settings → Extensions;
edit a theme's `.tex` in a centre tab; copy an installed theme into the project) are in v0.14.62.

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
5a. **Dark mode** (moved up from tier 3 after reading Graz; it is the most used theme): the deck says `\SMDarkMode`
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
* **Scope-aware.** The reader tracks `\ifdefined\SMDarkMode ... \else ... \fi` (and the position against
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

## 4. Staging and what each stage needs

| Stage | Contents | Depends on |
|---|---|---|
| C1 | The scope-aware reader and in-place writer with the **Graz round-trip tests** first; then identity, palette (with the theme's own colours) and contrast badges, logo, 9 colour roles, code colours, **Light / Dark columns** for the colours Graz overrides, footnote marker; "New theme…" from the shipped one; live sample render in light and dark | the field metadata and catalog test; `theme-color-roles` for the full role list |
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
