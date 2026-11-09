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
* The four real templates: SlideMage (the catalog defaults), Greyscale (the one that "differs in nearly everything a
  template can choose"), `uni-ibk` and `mci` (institution layers in the real project).
* What a theme **cannot** set, by design: 22 **derived** names (guarded: setting one is an error), and the layout
  profile's own numbers (ascender, line spread, parskip).

What the four real templates actually change (the evidence for the order below):

| Setting group | SlideMage | Greyscale | uni-ibk | mci |
|---|---|---|---|---|
| 21 palette colours | defaults | all | all | all |
| Logo file | default | default | own | own |
| Colour roles (of 9) | defaults | 9 | 5 | 5 |
| Code panel colours | 3 | 1 | 3 | 3 |
| Layout profile (font) | fira | lmroman | fira | fira |
| Body size, text margins, Top Margin | – | all three | – | – |
| Title bar paddings, logo height and padding | – | all | right padding | right padding |
| Footer box and text sizes | – | all | – | – |
| Bullet symbol, footnote marker | – | both | – | – |
| Project macros, citation format | project macros | – | project macros | project macros |

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
   underline on the canvas >= 3:1). `theme_colors.py` (v0.14.60) already reads these lines.
3. **Logo**: `\SMInstituteLogoPath` (file picker; the file is copied to `schemes/scheme_<key_>/` and must be a vector
   PDF cropped to its ink), `\SMLogoHeight`, `\SMFrametitleRightPadding` (the white space either side of the logo; the
   frame number and footnotes end at its inner edge).
4. **Colour roles, 9** (`\renewcommand{\SM...Color}{<palette name>}`): title bar box and text, footer box and text,
   bullets, highlightframe title text, standout text, `\alert` text, progress bar. Each is a drop-down of palette
   names, so a theme cannot name a colour that does not exist. Open task `theme-color-roles` adds more (block title
   text colour among them); the form should read its list of roles from the catalog, not hard-code it.
5. **Code panel colours, 4 optional** (`\colorlet`/`\definecolor` of `SMCodeKeywordColor`, `-Comment-`, `-Background-`,
   `-Text-`): 3 of the 4 real templates change them; the checker is again contrast (commands and comments on the panel).

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
    **footnote marker** (symbols, numbers `\number#1`, boxed, dice).
11. **Bullets and lists**: bullet symbol (filled circle, en dash, custom glyph; the indent follows by itself), item
    spacing ratios of the four levels.
12. **Citation format**: `\SMCitationFormat` (default or an installed `.smcite` key; the same list as Settings),
    `\SMBiblatexOptions`, `\SMBibliographyStyle`.

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
    (`\SMCardHeadingStyle`, a font switch such as a medium weight).
17. **Optional features** (off by default, a command each): mini frames (position, spreading, sections, compress,
    marks), **progress bar** (position, style, direction), **divider frames** (levels, look, page options, offset),
    **watermark** (default on or off, template).
18. **Dark mode palette**: a second set (canvas, card, body text, inline code, code panel) used when the deck says
    `\SMDarkMode`. Not a catalog setting today: the real dark templates write beamer colour lines after the base. A
    form needs a proper design (a "dark" column beside the palette, written inside `\ifdefined\SMDarkMode`), which is why
    it is last in this tier although users ask for it.

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

* **Block title text colour** (fixed `c_primary_dark` today; the Innsbruck "white block titles" request).
* **Link colours** (text `c_custom_gray`, underline `c_secondary_blue`: fixed in the base).
* **Per-frame-type colours** (title/section/quote frame boxes follow the title bar role; no role of their own).
* **Frame title weight, case and alignment** (beamer fonts, not in the catalog).
* **Logo placement** (always the title bar's right end) and a second logo for dark backgrounds.
* **Canvas colour as a role** (it is "optional colour" `SMCanvasColor`, undocumented as a role).

## 3. The editor: what it edits and how

### 3.1 The file stays the truth

A theme is a hand-written, heavily commented `.tex` (uni-ibk's header explains where each colour came from). A form that
regenerates the file would destroy that. So:

* **Recognise, edit in place.** The form reads the file the way `deck_settings.py` reads a deck (live, uncommented
  lines; the same `_live` and `is_commented` helpers): each setting is a regex over one line. Changing a value rewrites
  that line's value and keeps its trailing comment; a setting the file does not mention is **appended** inside a
  marked block (`% --- SlideMage theme editor: begin/end ---`) immediately before `\input{SlideMage_base}`, in the
  catalog's own order. Lines the form does not recognise are never touched.
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

## 4. Staging and what each stage needs

| Stage | Contents | Depends on |
|---|---|---|
| C1 | Identity, palette with contrast badges, logo, 9 colour roles, code colours; "New theme…" from the shipped one; live sample render | the field metadata and catalog test; `theme-color-roles` for the full role list |
| C2 | Layout profile, sizes, margins, title bar, footer and footnotes, bullets, citation format | C1's editing core |
| C3 | "Advanced": tier 3 fields, optional features, dark-mode palette | a design for the dark column; the framework gaps above |
| C4 | `.smtheme` export | C1 |

Where it lives: a tab beside the source tab for a theme file, "Design…" on a personal theme's row, and "New theme…" next
to "Add from file…" in Settings → Themes.

## 5. Questions for the user

1. Is the tier order right, in particular **dark mode** (tier 3 here, though you may want it earlier) and **footnote
   marker / bullet symbol** (tier 2)?
2. Form **beside** the source tab (split, both live) or a **separate designer tab** that hides the source?
3. Should the form be allowed to write the marked block when a theme was hand-written with its own ordering (my default),
   or only edit lines that already exist and refuse the rest?
4. The sample deck for the live render: the stress-test deck as it is, or a purpose-written "theme sample" deck (title,
   section, blocks of each kind, list, footnote, quote, code)? The second costs one new deck and is nicer.
5. Which **framework hooks** to add first from "beyond the catalog" (block title text, link colours are the two the
   Innsbruck work already needs)? They belong to `theme-color-roles`.
