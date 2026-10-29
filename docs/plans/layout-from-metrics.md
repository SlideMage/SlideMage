# Plan: layout that follows the font and the template (steps 8-13 of the framework redesign)

Written 2026-10-28, after step 7 (v10.6.0). Status: **approved by the user on 2026-10-28, with the proposed
answers to the five decisions at the end.** It extends `docs/plans/template-owned-layout-and-own-theme.md` (the "main plan"); read its section 2
(the hook catalog), section 4 (layout profiles) and the "Done" notes under steps 5-7 first.

## Why

Step 7's stress test (`tests/fixtures/template_stress/`: Latin Modern Sans, every catalog hook changed) showed that
the layout still only works for Fira Sans and the SlideMage template's default values:

1. **Fixed pull-ups.** Frames the automatic Top Margin does not manage (`sectionframe`, a `\progressstrip` frame,
   `[c]` frames, `\SMManualTopMargin`, `\SMAutoTopMarginfalse`) move their body up by `\SMContentTopShift`
   (11.5964pt), and a `columns` that comes first by `\SMColumnsTopCorrection` / `\SMColumnsTTopCompensation`. All
   three were measured on Fira under the default title bar. With Top Margin 50bp the first line lands 2.9pt high,
   5.2pt in `columns[T]`; the stress deck skips `top` on three slides to get around it.
2. **Values that contain another hook's default.** `\SMFooterRightShift` (4.6pt) and `\SMFootnoteRightShift`
   (4.8pt) are `text margin - logo padding` plus a glyph overhang, frozen at the defaults: when a template changes
   the margin or the padding, page number and footnotes miss the logo's edge by about 2pt.
3. **A hook that does not mean what its name says.** `\SMTitleframeBottomPad` (41pt) is "space under the last
   line" plus beamer's own offset at the top of a frame body, so a template cannot set it by intent (the stress
   template needs 55pt to get about 30pt).
4. **A profile needs the template's help.** Another profile only works if the template also sets
   `\SMTitleBarBottomAlign`, `\SMTopMargin` and `\SMContentTopAlign` to numbers the calibration tool prints.
5. **Numbers measured once instead of derived.** 17 "calibrations" in each profile; several of lmsans's are Fira's
   unmeasured; the calibration tool needs two Fira-specific offsets (0.22pt overhang, 2.36pt for `[T]`) to read back
   Fira's own values.
6. **Two Fira bugs found on the way.** A `\footnote` inside a `\pause`d item shows its text from the first step; a
   `columns[T]` right after a `columns[t]` starts about 3pt under the list above, almost touching a table's rule.

## Starting point: the user's step 5 answers (v10.4.1)

On 2026-10-27 the user answered step 5's questions (a)-(e) (implemented as v10.4.1 on branch
`fw-redesign-conflict-copy-28170940`, never merged because of the sync incident; see the handover). They are
requirements of this plan, and step 8 re-implements them on top of v10.6.0 instead of merging that branch:

- `\SMContentTopAlign` derives from `\SMTopMargin` (moves overlays by 0.156pt; approved).
- `\SMTitleBarBottomAlign` derives from the title padding, the frame title font's cap height and the logo height
  (14-16 pixels at the logo per page, 594 on appendix thumbnails; approved).
- The footer and footnote right shifts follow the text margin and the logo's right padding (0.04pt / 0.24pt on the
  default look; approved).
- `\SMFootlineVOffset` is a profile value; `\SMTitleframeBottomPad` stays a design hook.
- A template that sets a derived name gets an error.

## Principles

1. **Three sources, nothing else.** Every length is (a) a catalog hook the template may set, (b) a property of the
   loaded font, read from the font at compile time (TeX's `\fontcharht`/`\fontchardp`/`\settowidth`, or the glyph
   data luaotfload keeps: ascender, cap height, glyph bounding boxes), or (c) derived from (a) and (b) in base. A
   value measured once on one font and stored is the exception, and each one left at the end is listed with the
   reason it could not be derived.
2. **A hook means its name.** "Bottom pad" is the space under the last line; "right shift" disappears as a concept
   because edges are placed against the logo directly. A test checks the geometry each hook names (below).
3. **No derived value contains another hook's default.** Where a formula used a default, it uses the hook.
4. **Placement that depends on what comes first is measured, not guessed.** The automatic Top Margin already
   measures each frame's first visible line at shipout (`SlideMage_measure.lua`) and corrects it on the rerun
   (`\jobname.top`). The frames it leaves out get the same mechanism in a form that respects their purpose.
5. **The profile is fonts only.** After this plan a profile holds the font files and weight mapping, the code
   fonts, the math handling, `\SMLinespread`, `\SMParskip` (typographic choices of that font, decided 2026-10-27),
   the ascender as a fallback, and nothing measured on a slide.

## The changes

### A. Geometry from hooks (the user's v10.4.1 answers, re-done on v10.6.0)

- `\SMContentTopAlign := \SMTopMargin`; `\SMTitleBarBottomAlign :=` title top padding + frame title strut − half
  the frame title font's cap height + half the logo height, computed after the template (as v10.4.1 did).
- Footer number and footnotes: their right edge is placed at `\paperwidth − \SMFrametitleRightPadding` (the logo's
  edge) minus the last glyph's right side bearing, read from the font (Lua: the glyph's bounding box) instead of
  `\SMFooterNumberOverhang` (0.23691pt on Fira). `\SMFooterRightShift` and `\SMFootnoteRightShift` stop being
  values; the names stay readable for slides, derived.
- The stress template loses its `\SMContentTopAlign` and `\SMTitleBarBottomAlign` lines; lmsans then needs no help
  from the template.
- Visible: v10.4.1's approved shifts; the overhang from the font instead of 0.23691pt must reproduce Fira's number
  within 0.005pt or the difference is shown.

### B. Font measurements instead of stored numbers

Each becomes an expression evaluated in the font where it is used:

| Today (profile number, Fira) | Becomes |
|---|---|
| `\SMLabelItemWidth` 9.1pt, `\SMLabelItemSep` 4.75pt | width of the widest label ("a)" ... at the list's size) via `\settowidth`; the gap rule the calibration tool uses (2pt + half a "C") becomes a catalog hook `\SMLabelItemGap` in design units |
| `\SMEnumerateNestedMinNumber` 7.85pt, `\SMEnumerateNestedLeftMargin` 13.1pt, `\SMEnumerateNestedLabelSep` 5.25pt, `\SMEnumerateLabelBox` 20.33pt | widest numeral of the list's own font via `\settowidth` (digits are tabular in both profiles); the label gap and the slot's extra width become hooks |
| `\SMEnumerateTextExtra` 6.3pt | already called a design value: a hook |
| `\SMFooterTextDrop` −0.49pt (ink of the frame number centred in the box) | from the digits' ink (Lua bounding boxes) and the footer box height |
| `\SMFootlineVOffset` −0.5ex − 0.77pt | the footnote-to-footer gap measured from the footnote font's descender; the gap itself a hook (v10.4.1 made it a profile value; this plan proposes to go one further, see decision 3) |
| `\SMSectionframeRefDepth` / `BottomGap` / `BottomPadCorrection` / `HeightCorrection` | the section title is already set in a box: place it by that box's measured height and depth against the bar (section C) |

Proof per row: the Fira value reproduced exactly (pixel-identical) or within the named tolerance with before/after
images; lmsans then gets real values instead of Fira's.

### C. Top placement without fixed pull-ups

- **The body origin is measured, for every frame.** The automatic Top Margin's start marker records where the
  frame body begins. For frames it manages nothing changes. For the frames it leaves out, the rerun correction is
  computed for the body origin instead of the first content: the origin is moved to where a plain first paragraph's
  line box would touch `\SMTopMargin` (origin + `\topskip` − ascender × size). That is exactly what
  `\SMContentTopShift` approximates today, so on Fira it should reproduce the hand-placed positions, and with any
  other title bar or font it follows. `\SMManualTopMargin` keeps its meaning (no content-dependent correction), and
  `[c]` frames keep theirs (no pull-up at all).
- **Columns as first content** in such frames get the same treatment one level down: the column head records its
  origin, and the correction for `[t]`/`[T]` is the measured difference to a plain line, not 10.17pt / 13.76pt. Where
  only a constant can do it, it is expressed in `ex`/`\baselineskip` of the current font and justified.
- **`sectionframe`** places its title box from the box's measured size against the bar (B), and its body by the
  origin rule above.
- `\SMContentTopShift`, `\SMColumnsTopCorrection`, `\SMColumnsTTopCompensation` leave the profile. Slides that read
  the names keep them (derived, read-only; in the real project they are read only by the layout-grid and
  quick-reference slides 1gr and 1uw).
- Cost: frames that today converge in one compile may need the one rerun the automatic Top Margin already needs;
  no deck gets more reruns than today.

### D. Hooks that mean their names

- `\SMTitleframeBottomPad` becomes the space from the subtitle's last baseline's descender to the box's bottom edge:
  the text box is placed against the box's bottom (like the box itself, from the page corner), not through the
  frame's flow, so beamer's top-of-body offset drops out. The default is recomputed so the SlideMage template looks
  the same (decision 4).
- Audit of every hook in the catalog against what it does, with a test per geometric hook: the stress template's
  value appears in the PDF where the name says (e.g. title bar bottom, footer box height, text margins, the
  title-frame bottom pad, side-footnote width). `check_layout.py` gets the extra checks this needs (right edges of
  footer number and footnotes against the logo, title-frame bottom pad).

### E. The two Fira bugs

- `\footnote` inside an item revealed with `\pause` or `<n->`: the footnote text takes the overlay of its item
  (beamer's `\footnote<...>`), so it appears with the item. Every slide that has this changes on the steps before
  the item appears (a fix; the list of affected slides in the real project comes with the before/after images).
- `columns[T]` after other content: beamer's `[T]` pulls each column head up by 1ex; the compensation is applied only
  at the top of a frame. Below other content the head keeps the normal gap. Affected slides listed with images.

### F. Proof and tools

- `tools/calibrate_font_profile.py` becomes a check: it compiles the calibration deck with a profile and reports
  measured against expected geometry; it no longer prints numbers to copy, and its Fira-specific offsets go.
- Acceptance: the calibration and stress decks pass `check_layout.py` with `fira` and with `lmsans`, under the
  stress template and under the SlideMage template, with no layout exemptions (exemptions only for content that is
  meant to break a margin, such as a figure flush with the page edge, each commented as today).
- `test_template_catalog.py` gains: the profiles define only the allowed font names (a list in the test), no
  template sets a derived name, every geometric hook has a geometry check.
- Existing decks (in-repo and the private copy) render identically except the changes each step names and the user
  approves with before/after images.

## Steps

Each step is one branch from `dev-framework-redesign`, the usual rules (handover): versions, CHANGELOG, pins,
tests, both regression sets, pause for the user. Before step 8: merge develop (v8.67.1, the move to
`SlideMage/SlideMage`) and record fresh baselines at the merge from a clean detached worktree.

| Step | Content | Version | Visible on existing decks |
|---|---|---|---|
| 8 | A: geometry from hooks (v10.4.1 re-done), overhang from the font, stress template drops its overrides | v10.7.0 | v10.4.1's approved sub-point shifts |
| 9 | B: font measurements instead of stored numbers; new hooks `\SMLabelItemGap` etc. | v10.8.0 | sub-point, per row, with images |
| 10 | C: body-origin measurement for unmanaged frames, columns, section frame; pull-up numbers leave the profile | v10.9.0 | goal identical on Fira; any difference with images |
| 11 | D: `\SMTitleframeBottomPad` placement, hook audit and geometry tests | v10.10.0 | identical by construction (default recomputed) |
| 12 | E: footnotes in revealed items, `columns[T]` below content | v10.11.0 | yes: bug fixes, affected slides listed |
| 13 | F: calibration tool as a check, stress/calibration decks clean with both profiles, profile-content test | v10.12.0 | none |

The main plan's later steps move up: bibliography file 8 → 14, documentation 9 → 15, institution templates out of
the repository 10 → 16, private institution themes 11 → 17.

- **Who does what:** steps 8, 9, 11 and 13 are well specified (Sonnet sessions, as before). Step 10 changes the
  measurement mechanism and step 12 touches beamer's overlay machinery: design work, done in the orchestrating
  session or an Opus session.
- **Breaking:** step 8 makes `\SMContentTopAlign`, `\SMTitleBarBottomAlign`, `\SMFooterRightShift` and
  `\SMFootnoteRightShift` read-only; a template that sets them gets an error. Neither shipped template nor the real
  project's three templates set them (checked 2026-10-28), so no compat migration is needed; the CHANGELOG gets a
  `BREAKING:` paragraph for other projects' templates. Steps 9 and 10 do the same for the profile numbers they
  remove (templates never set those; a project's own profile would, which the paragraph says).

## What it means for documentation (step 15, was 9)

- "Making a template" gets simpler: a template sets hooks and picks a profile; it never sets a measured number.
  The recipe for a new profile becomes: copy a profile, change the fonts, run the check; no numbers to copy.
- "What a compile reads, in order" shows the measurement passes (`\jobname.top`) next to the files, since
  placement now depends on them for every frame.
- The layout-grid slide 1gr and the quick reference 1uw describe the pull-up and the manual Top Margin; they change
  with step 10.

## Decisions for the user

**Decided 2026-10-28 (the user approved the plan with the proposed answers):** (1) approved, with the renumbering;
(2) sub-point shifts from deriving a value are accepted once shown with before/after images; (3)
`\SMFootlineVOffset` is derived from the font, the gap itself becomes a hook; (4) `\SMTitleframeBottomPad` changes
its meaning to "space under the last line" with a recomputed default, so existing decks look the same; (5) step 12's
bug fixes are made now, with the affected slides listed and shown before/after.

1. Approve this plan (and the renumbering of the later steps).
2. Visible-change rule for steps 8-10: as with v10.4.1, sub-point shifts that come from deriving a value instead of
   storing it are acceptable once shown with before/after images; or should those steps keep pixel identity where
   possible by keeping a stored number?
3. `\SMFootlineVOffset`: profile value (v10.4.1, the user's answer) or derived from the font with the gap as a hook
   (this plan's proposal in B)?
4. `\SMTitleframeBottomPad`: change its meaning to "space under the last line" with a recomputed default (no visible
   change on existing decks; a project template that sets it would see its title-slide text move), or keep the name
   with its old meaning and add a new, correctly named hook?
5. Step 12's bug fixes change existing slides of the real project: fix them now, or record them and leave them for
   later?

## Done 2026-10-28 (v10.7.0), notes for the later steps

Step 8 (section A). `\SMContentTopAlign`, `\SMTitleBarBottomAlign`, `\SMFootnoteRightShift` and `\SMFooterRightShift` are
derived by `SlideMage_base.tex`; the first two leave the catalog, the last two both profiles.

- **Where.** `\SMContentTopAlign = \SMTopMargin`, `\SMTitleBarBottomAlign` = title top padding + height of an X in the
  frame title font - half its E + half the logo height, `\SMFootnoteRightShift = \SMTextMarginRight -
  \SMFrametitleRightPadding`: all right after `\SMApplyLayoutHooks` (before the PDF info keys, which read the title
  bar's bottom), through `\SM@derivedlength{<Name>}`. `\SMFooterRightShift` is set inside the frame footer template.
- **The error.** The setup layer defines each of the four names, before the profile loads, as a macro that raises a
  `PackageError` naming it (`\SM@derivedname`) and keeps a copy `\SM@guard@<Name>`. A template or profile that does
  `\setlength` on one triggers the macro; one that `\renewcommand`s it is caught by the base, which compares the name with
  the copy before replacing it with the length. These four are `DERIVED` in `tests/test_template_catalog.py` (not hooks:
  not in the stress template, not in the unused-hook test); the test file has "no template or profile sets a derived
  name", "the base derives each and the setup guards it", and with `SLIDEMAGE_TEX_TESTS=1` a compile that checks the
  message for `\setlength` and for `\renewcommand`.
- **The overhang finding (the plan's premise did not hold).** The right side bearing of the last glyph is readable:
  `font.getfont(font.current()).descriptions[<unicode>].boundingbox` (luaotfload, keyed by codepoint, not by glyph index;
  RSB = `width - boundingbox[3]` in units of 1/1000 em). For Fira Sans Light's digits that is 35-121 units, 0.175pt-0.605pt
  at the footer's 5pt: 0 0.33, 1 0.605, 2 0.265, 3 0.315, 4 0.175, 5 0.255, 6 0.255, 7 0.18, 8 0.265, 9 0.305. None is
  0.23691pt, and the number differs per page, so reading it would move the frame number by 0.0-0.4pt from page to page.
  The 0.23691pt of v10.4.1 was not a glyph property: it was `TextMarginRight - FrametitleRightPadding` (4.837pt) minus
  the old 4.6pt. The footer line ends at its box's `\hsize - \rightskip - \SMRightFooterPadding - \SMFootlineHRightOffset
  + 4em + shift`, with `\rightskip` = 3ex *of the footline font at 8pt* (12.552pt for Fira, 10.656pt
  for lmsans), `\SMRightFooterPadding` = 3.5ex of the body font (20.044pt, 17.016pt) and the footer's 4em (20pt): for Fira
  these sum to 4.632pt, 0.205pt short of the text margin, and v10.4.1's constant absorbed that and 0.032pt more. For lmsans
  the sum is different by 5pt, which was the -0.33pt. So the shift is computed from those terms where the footer is
  typeset (`\hspace*{-4em}` and the shift sit in one template), and the frame number's advance box ends where the
  footnotes' lines end, the logo's padding edge. No overhang number is kept anywhere. Consequence: the number moves
  0.032pt right (Fira), 0.036pt (lmsans), the footnotes 0.037pt right, and both fonts end 0.19pt inside the logo's visible
  edge (the logo's drawn edge is not its padding edge), which the calibration tool now reports. The user looked at the
  options as renders (`step8-images/6-footer-number-edge-options.png`: before, advance box on the edge, ink on the edge)
  and decided 2026-10-28 to keep the advance box on the edge. Ink alignment would be a few lines of Lua at the place the
  footer sets the number, and would move the number by up to 0.5pt between pages.
- **Things the next steps can use.** (1) `\SMFooterRightShift`'s expression is where the footer's 4em/2em/0.4ex pieces and
  its two paddings meet: step 11's hook audit can turn them into hooks without moving the number. (2) lmsans under the
  SlideMage template now ends its title bar at 22.09bp (v10.6.0 kept Fira's 25.23bp there): the calibration decks of step 13
  need no template help for it. (3) The calibration tool reports the derived edges instead of suggesting numbers.
- **check_layout.py.** Clean on the calibration deck under the stress template (13 exempted findings, as in v10.6.0) and under
  the SlideMage template with fira (7) and with lmsans (7).
- **Visible changes.** In-repo compare: 12 entries, 1084 pages (0 failed compiles): 1054 pages differ in the right edge of the footer or
  footnotes (0.026-0.039bp), 220 in the title bar's bottom edge (0.003bp, the logo's trim patch, the thumbnails and
  side-image frames), 24 in overlays (slides 1rb and 1c9: 0.156pt down), 12 on the layout grid slide 1gr (its Top Margin line
  and labels); no word, drawing or image was added, lost or moved otherwise (a comparison of every word, path and image
  rectangle of the baseline and the new PDFs). Fonts identical. Private copy (16 decks, 48 entries, 5274 pages, 0 failed compiles, font lists identical): 5086 pages differ in the right
  edges (the footnote lines of a justified paragraph also stretch by up to 0.037pt), 501 in the title bar's bottom edge, 482 in
  overlays (0.156pt), 3 on the layout grid; 66 pages on 12 slides (f4y, d76, jae, vpk, ice, zwk, e84, cy9, xv8, jun, nmw, yke:
  corner figures, side-image frames and floating blocks that the slides size or place from `\SMContentTopAlign`,
  `\SMContentBottomAlign` or `\SMTitleBarBottomAlign`) move by 0.15-0.45pt, twice 0.156pt where top and bottom both move, and
  a figure sized between the two coordinates gets 0.31pt shorter and 0.26pt narrower (`step8-images/7-...-f4y.png`): the
  approved shifts at second order. 16 pages (the GrundlagenFinanzwissen and IA2 decks) lost a trailing glyph in the
  text extraction only: a line of text that already ran 1.4-2.7pt past the page's right edge now ends 0.0-0.5pt on the other
  side of it; nothing visible. No word, drawing or image was added or lost, no text reflowed. Before/after images are in
  `C:/Users/palans/SlideMage/regression/step8-images/`.

## Done 2026-10-28 (v10.8.0), notes for the later steps

Step 9 (section B). Both profiles hold fonts, metrics and the three pull-ups (`SMContentTopShift`, `SMColumnsTopCorrection`, `SMColumnsTTopCompensation`, for step 10) and nothing else. Twelve names are derived and guarded by the setup layer like step 8's (`SM@guardname`); the design parts are hooks. Per row, Fira / lmsans, old -> new:

| Row | Fira | lmsans | Derivation |
|---|---|---|---|
| `SMFooterTextDrop` | -0.49pt -> -0.451pt (+0.039pt, the centring the calibration measured: ink 1.94 above / 1.86 below) | -0.37pt -> -0.384pt | The number's baseline lies `SMFootlineDepth` + the id strut's depth + 0.4ex + drop above the page bottom (the drop is a `\vadjust`); the digits' ink is luaotfload's glyph box, i.e. the `\ht`/`\dp` of `0123456789`, so no Lua was needed. |
| `SMLabelItemWidth` | 9.1pt -> 9.08pt | 9.16pt -> 9.16pt | widest of a)-c), 1)-9) with `)` or `.` in the list's font, + 0.1pt. Measured where the list begins, so it follows the size: the manual's list is at 10.95pt and gets 9.98pt. |
| `SMLabelItemSep` | 4.75pt -> 4.75pt (at 10pt) | 5.20pt -> 4.75pt | hook `SMLabelItemGap` = 0.475em (the C rule is 2pt + half a C = 0.475em for Fira only). |
| `SMEnumerateNestedMinNumber` | 7.85pt -> 7.85pt | 8.18pt -> 8.18pt | widest numeral 1.-9. (7.45pt Fira, 7.78pt lmsans) + hook `SMEnumerateNestedSlotExtra` 0.04em. |
| `SMEnumerateNestedLabelSep` / `LeftMargin` | 5.25 / 13.1pt -> same | 5.25 / 13.43pt -> same | hook `SMEnumerateNestedLabelGap` 0.525em; left margin is slot + gap. At depth 3 (9pt) the column is 1.3pt narrower, a consequence of following the font. |
| `SMEnumerateLabelBox` | 20.33pt -> 19.4pt | 20.33pt -> 20.4pt | width of a three-digit numeral; invisible (the numeral is right-aligned in a box that is wider than it). |
| `SMEnumerateTextExtra` | 6.3pt -> hook | same | catalog length. |
| `SMFootlineVOffset` | -3.6335pt -> -3.6335pt | -3.2009pt -> -2.2463pt (0.95pt higher footnotes) | beamer sets the last footnote baseline at footline height + depth + offset + 4pt (`\beamer@calculateheadfoot`); the offset puts the descenders (depth of gjpqy) `SMFootnoteFooterGap` = 1.6136pt above the footer box. |
| `SMSectionframe{RefDepth,BottomGap,BottomPadCorrection,HeightCorrection}` | bar 85.02bp -> 85.02bp, title unchanged for 1-3 line titles with and without descenders | bar -0.024pt | the bar's content is typeset once in a box by the frame title's own beamercolorbox with top padding = bar height; padding = 2 x bar height - box. Last baseline = strut depth + hook `SMSectionframeTitleGap` 0.5436em above the bottom. `SMSectionframeBoxHeight` default 85.34pt (the bar as drawn); `SMSectionframeBarBottom` = that + 0.12bp. |

- **New hooks:** `SMLabelItemGap`, `SMEnumerateNestedSlotExtra`, `SMEnumerateNestedLabelGap`, `SMEnumerateTextExtra`, `SMFootnoteFooterGap`, `SMSectionframeTitleGap`. The stress template sets all of them (and no longer `SMFootlineVOffset`).
- **Things the next steps can use.** `\SM@sectionbarmetrics` (typeset the bar's material in a box, solve the padding from its height) is the pattern step 10's body-origin measurement can follow; the base writes `SMFootnoteFooterGap`, `SMFootnoteDescender` and `SMFooterBoxHeight` into the PDF info dictionary, which `tools/calibrate_font_profile.py` now checks (it suggests only the three pull-ups). The compat registry gets `font-measurements-derived`.
- **Check.** `check_layout.py` is clean under the stress template (13 exempted findings) and the SlideMage template with fira (7) and lmsans (7), as in v10.7.0.
- **Regression.** In-repo: 12 entries, 1084 pages, 0 failed compiles, fonts identical; 1054 pages differ by 0.04pt (footer number), 12 pages (slide 1w4) by the list text 0.55-1.28pt to the right. Private copy: 48 entries, 5274 pages, 0 failures, fonts identical; 5102 pages differ, almost all by the 0.04pt; 98 pages on 18 slides (1w4, bdh, bzd, cmv, ctu, gfx, ix7, jt8, kfh, kmf, nt4, p5r, raf, rre, seg, u5j, vjy, y3a) by list text shifts of -1.4 to +2.6pt (lists not at 10pt, third-level enumerate at 9pt). No word, drawing or image added, lost or reflowed. Images: `C:/Users/palans/SlideMage/regression/step9-images/`.
- **Open for the user.** The v10.7.0 and v10.8.0 CHANGELOG entries carry BREAKING with the same major version (release_notes warns); the compat project migration for gothamFootlineVOffset (v10.1.0) now yields a template that sets a derived name.

## Done 2026-10-29 (v10.9.0), notes for the later steps

Step 10 (section C). The profiles hold fonts and font metrics only; `\SMContentTopShift`, `\SMColumnsTopCorrection` and `\SMColumnsTTopCompensation` are guarded by the setup layer (`SM@guardname`) and derived by the base (`SM@derivedlength`), readable by slides. Compat entry `top-pullups-measured`.

- **One deviation from the plan's formula, to keep Fira identical.** The plan's rule ("a plain first paragraph's line box touches `\SMTopMargin`") would move every manual-top and section frame 2.996pt down on Fira: in such a frame a plain paragraph sits that much above a list, and 11.5964pt was fitted to a list (slide 8s8). The reference line is therefore **the first line of a top-level itemize**, typeset in a box at the body origin (`\SM@toprefprobe`: the frame's own `\prevdepth`, font and list settings, measured by `slidemage_measure.box_content_top` like any first content; never on the page). The probe text is "Xh", because a `[T]` column aligns by the line's height. The probe sets beamer's default overlay specification back to `<*>` (an `\item<+->` default would count a step; an empty one breaks `\beamer@parseitem`).
- **Where the value comes from.** Every top-aligned frame writes a second marker (`ORIGIN_ID`) after its start marker, with the probe's offset. At shipout the origin without pull-up is recorded; at the end the pull-up that puts each frame's reference line on its target (Top Margin, plus the strip of a `\progressstrip` frame) is computed, and the value most frames share (to 0.0001pt; untitled frames and section frames do not vote) is written as `\SMSetContentTopShift{...}` to `\jobname.top`. A value one of the frames still has stays (a page compile of a few slides keeps the deck's). Fira/SlideMage 11.6007pt (was 11.5964pt), lmsans/SlideMage 11.1701pt (was 11.17pt), lmsans/stress 8.2736pt. The corrections of the measured frames stay relative to it.
- **No extra runs: the first run.** Without `\jobname.top` the value of the first titled frame (set at its shipout as `\SM@topshiftrun`, read by the next `\SM@topprepare`) is used for every frame after it, so the first run lays the deck out as the next one will. A first try started the first run at 0pt: 12 private entries then needed one or two runs more (SE-COF 3 -> 5), a frame with nothing measurable (only an overlay picture, slide xcb) kept 0pt (11.55bp too low), and full frames whose room rule depends on the path (ZZM, vcv, v9f) landed 1-4bp elsewhere. Now a frame that started its run from another value (only the first counted frame of a first run) is corrected from its default position, every other frame exactly as before (room rule relative to where it is), and a frame with nothing measurable keeps its correction.
- **Decisions.** `\SMManualTopMargin` keeps "no content-dependent correction": the frame gets `\SMContentTopShift` (less a `\SMReduceContentTopShift`), nothing per frame. `[c]` keeps "no pull-up"; the columns correction **stays in `[c]`** (as before), measured: it removes the columns environment's own head space, so a centred columns block is centred like a list. `\SMAutoTopMarginfalse` now means "every frame as with `\SMManualTopMargin`": the measurement still runs (it gives `\SMContentTopShift`), no frame gets a content-dependent correction. `sectionframe` gets `\SMContentTopShift` and then its hook `\SMSectionframeContentDrop`, as before but measured: its body sits where a standard frame's would relative to its own title box (it does not vote; its bar is taller). A `\progressstrip` frame was measured already (v5.30.5); its strip offset now also applies with `\SMManualTopMargin`.
- **Columns.** `\BeforeBeginEnvironment{columns}`, when the columns come first in a frame that is not corrected by its content (or at the top of a minipage there, as `\SMChapterAgenda`'s), typesets three reference lists (itemize; the same in a `columns[t]` column; in a `columns[T]` column) and sets `\SMColumnsTopCorrection` = t - list and `\SMColumnsTTopCompensation` = t - T (global, the last values measured; `\SM@columnsprobe`). Fira at normal size: 10.17pt reproduced; `[T]` now lands 0.11bp under the Top Margin, where 13.76pt left it 2.35bp above (the 13.76pt was measured before v5.14.1 set `\@minipagetrue` at a `[T]` column head). No constant is left: `[T]` stays content-dependent by beamer's design (it aligns by the first line's height), so text taller or shorter than "Xh" lands a few tenths off.
- **Things the next steps can use.** `\SM@toprefprobe{<material>}` says where any material's first line would start at the current point; step 12's `columns[T]` below content can use it (`\SM@columnsprobe` is the pattern). The slides 1gr and 1uw still say "`\SMAutoTopMarginfalse` switches it off" (step 15).
- **check_layout.py** on the calibration deck: clean under the stress template (10 exempted findings, was 13: the three manual-top exemptions are gone) and under the SlideMage template with fira (6, was 7) and lmsans (6, was 7). `tools/calibrate_font_profile.py` suggests nothing any more: it checks that the three manual-top frames start on the Top Margin (fira 0.00 / 0.00 / 0.11pt, lmsans 0.00 / 0.00 / 0.00pt).
- **Compile counts.** Calibration deck 3 LuaLaTeX runs before and after (fira, lmsans, stress, and with `\SMAutoTopMarginfalse`). In-repo 12 entries: 5 -> 5 each. Private copy 57 entries: identical to the baseline for every entry (6 at 3, 12 at 4, 39 at 5).
- **Regression** (baselines `.regression/repo-v98`, `private-v98` at `3088c4b9`; PDFs compared word by word, path by path and image by image). In-repo: 12 entries, 1084 pages, 0 failed compiles, fonts identical; 1026 pages differ, 876 by at most 0.01bp (the measured `\SMContentTopShift` and the corrections now landing exactly), 150 by 0.2-0.34bp: the 13 chapter dividers, whose `\SMChapterAgenda` moves up 0.337bp (0.203bp on 1qn), its columns correction measured at the agenda's size instead of 10.17pt. Private copy: 57 entries, 7160 pages, 0 failed compiles, fonts identical; 6170 pages differ, 6086 by at most 0.01bp, 81 by 0.2-0.34bp (the same agenda on the manual's dividers and on bij), 3 flagged over 0.5bp by the path match only (IA2 hck: its drawings move by 0.01bp). No word, drawing or image added, lost or reflowed; no page count changed. On Fira a `columns[T]` first in a manual-top, section or `[c]` frame moves 2.46bp down (calibration slide ZCK; no slide of either regression set has it; it now sits on the Top Margin, the old constant put it 2.4pt high; **approved by the user on 2026-10-29**, merged as `7c97584e`). Images: `D:/uniCLOUD/SlideMage/.regression/step10-images/`.

## Done 2026-10-29 (v10.10.0), notes for the later steps

Step 11 (section D), in two commits. Versions: the redesign's releases v9.0.0-v9.9.0 are v10.0.0-v10.9.0 (user instruction 2026-10-29), so this is v10.10.0; v9.4.1, which never landed on this branch, is v10.4.1 in the plan texts.

- **Renumbering.** 219 version strings in 31 files: the CHANGELOG headers and cross-references, `VERSION_NUMBER`, the `latex/` comments and the theme's `\ProvidesExplPackage` version (10.7.0), the compat entries' `since` values and texts and their tests, the plans, README, tools and tests. develop's 8.x entries are untouched. Preview pins renewed for the six changed TeX/Lua files (the diff of `latex/` is comments only apart from the package version). `release_notes.py --previous v8.61.0 v10.9.0` prints no warning any more: with 8 -> 10 every BREAKING paragraph is on a major bump, but the later 10.x entries (v10.1.0, v10.7.0, v10.8.0, v10.9.0, v10.10.0) still carry BREAKING on a minor bump, which the tool only warns about when a tag keeps its predecessor's major (the user has not ruled on it). The updater test's `v9.0.0` fixture tag and the 8.x-era `v9-0-0` frozen-slide names are unrelated and stay.
- **The bottom pad.** `\SMTitleframeBottomPad` is the space from the descenders of the subtitle's last line to the title box's bottom edge (the convention of `\SMFootnoteFooterGap` and `\SMSectionframeTitleGap`: the depth of "gjpqy" in the subtitle's font, `\Large` of the normal text font; not the baseline and not the strut's depth). The title frame's text box is no longer put through the frame's flow after a `\vspace*`; it is a tikz node, anchored `south west` at the page's corner shifted right by `\SMTextMarginLeft` (where the flow put it) and down by `\SMTitleframeBoxHeight`, as the colored box is. The vbox ends `descender + pad - \prevdepth` under the last line, so its bottom is the pad under the descender line. The old value contained beamer's offset at the top of the frame body: 41pt = 8.505pt + 32.495pt. The new default 8.505pt reproduces the SlideMage template's title slide to 0.001bp (baselines 95.242 / 154.411 / 175.034 against 95.243 / 154.411 / 175.034; x 39.571 unchanged). The stress template sets 30pt (it needed 55pt for about 30pt) and gets 30pt: box bottom - last baseline - descender = 29.888bp = 30pt.
- **Info keys.** The base writes the geometric hooks into the PDF info dictionary, one key per hook name in bp (`SMLogoHeight`, `SMTextMarginLeft/Right`, `SMFrametitle{Top,Bottom,Right}Padding`, `SMFrameSubtitleStrutEnd`, `SMFootnoteSep`, the four `SMSideFootnote` lengths, `SMBlockSideMargin`, `SMBlockTitleMarkerWidth`, `SMTitleframeBoxHeight/BottomPad`, `SMSectionframeBoxHeight`, `SMQuoteBoxHeight`, `SMQuoteAttributionGap`, `SMProgressStripHeight`) plus `SMTitleframeDescender`, `SMFrametitleXHeight` (the X height the top padding is measured against) and `SMFootlineSidePadding` (a macro in ex, read in the footline font). `check_layout.py` reads them with `pdf_hooks()`.
- **check_layout.py.** Two new checks. `edge`: the frame number (its advance box) and the footnote lines end on the logo's padding edge, the page's width less `SMFrametitleRightPadding`, within the tolerance; a PDF without the key is compared with the logo's visible edge plus a point, and only on frames with the ordinary title bar (without that restriction the manual's slide 1xf, a frame without the logo patch, was flagged). `titlepad`: on a title frame (a colored box at the corner as high as `SMTitleframeBoxHeight`, narrower than the page, not a quote box) the last text line's baseline + descender + pad = the box's bottom edge. Both are exact on the calibration deck under the stress template and under fira and lmsans (0 findings, exempted findings 10 / 6 / 6, as before step 11; the new slides are in a deck of their own so that the count stays). Unit tests with synthetic pages in `tests/test_check_layout_margins.py`.
- **Geometry tests.** `tests/test_hook_geometry.py` (compiles the calibration deck under the stress template and under SlideMage/fira, and the new `decks/geometry.tex` with slides ZG1 text margins plus subtitle and ZG2 side footnotes in a standard frame; opt-in `SLIDEMAGE_TEX_TESTS=1`; about a minute). A table says for every length of the catalog which test reads it back or why it cannot be; a test keeps the table complete. Read back from the PDF, value against drawn geometry: the text margins (a rule `\linewidth` wide spans margin to margin, lines begin at the left one), the title text's left edge, its baseline (top padding + X height), the title box's bottom (baseline + bottom padding, + the subtitle strut end with a subtitle), the logo's height (the logo file's artwork scaled by `\SMLogoHeight`) and its right padding, the footer box height, the footer text and id sizes, the footline's left padding, the footnote size, the footnote gap above the footer, two footnotes one `\SMFootnoteSep` + descender apart, the side-footnote strip (right inset, top sep from the foot of the title block, longest line <= Hsize and >= 0.9 Hsize), a block's text one `\SMBlockSideMargin` right of the column, the section and quote boxes' heights, the quote attribution's gap (0.5bp: TeX's box of the tallest character, not its ink), the title frame's text (by the descender key, and by the deepest ink of a "gjpqy" line, 0.12bp), and the default title slide against v10.9.0's positions.
- **Hook audit** (catalog `SlideMage_setup.tex`; every other geometric hook reads back where its name says). Fixed: `\SMTitleframeBottomPad`. Documented in the catalog, no look changed, and asked about in the report: (1) `\SMFrametitleBottomPadding` is the title box's bottom padding (baseline to the box's bottom, exact in the PDF), but the logo's white patch trims the visible bar to the logo's bottom edge (`\SMTitleBarBottomAlign`, from the top padding, the title font and the logo height), so the bar's bottom edge is not set by it unless it makes the box shorter than the logo's bottom; it fixes where the body begins. (2) `\SMSideFootnoteTopSep` hangs the strip from the foot of the title block (the box's bottom + beamer's 3pt gap), which lies 3-10pt under the visible bar, so the gap seen from the bar is larger than the hook. (3) `\SMFootlineHeight`, `\SMFootlineDepth` and `\SMRightFooterPadding` move nothing on the page (the stress deck with 5ex / 1ex / 9ex is identical on 23 pages): the derived `\SMFootlineVOffset` and `\SMFooterRightShift` cancel them. (4) `\SMFootlineSidePadding` moves the footer text's left end only (9ex instead of 4ex moves it 17.7bp; the right end stays on the logo's edge). (5) `\SMProgressStripHeight` is the room the content below a `\progressstrip` is moved down by, not the strip's drawn height (11.2pt, set by the node's own text height, depth and padding). Not read back, with reasons in the test table: `\SMBlockTitleMarkerWidth` (visible only when a block title wraps), the title/subtitle spacing (`\SMTitleframeTextSep`, `\SMTitleframeBandGap`), `\SMSectionframeContentDrop` (step 10), `\SMSideFootnoteMarkerShift`, and the list and drawing lengths.
- **Compat.** Entry `titleframe-bottom-pad` (v10.10.0, APPEARANCE, detects project templates and project macros that set the hook; a test). The CHANGELOG entry has `BREAKING:` for the same case; no shipped template and none of the real project's templates sets the hook (checked in the regression copy, 2026-10-29).
- **Theme.** Unchanged in this step, so no new LPPL change item.
