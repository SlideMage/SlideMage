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
| 11b | Two hooks renamed (`\SMProgressStripRoom`, `\SMSideFootnoteTitleBlockSep`), three inert ones removed (`\SMFootlineHeight`, `\SMFootlineDepth`, `\SMRightFooterPadding`) | v10.11.0 | identical |
| 12 | E: footnotes in revealed items, `columns[T]` below content | v10.12.0 | yes: bug fixes, affected slides listed |
| 13 | F: calibration tool as a check, stress/calibration decks clean with both profiles, profile-content test | v10.13.0 | yes: slide 1ub's image-source line was below the page |

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
- **The bottom pad.** `\SMTitleframeBottomPad` is the space from the bottom of the last subtitle line's box to the title box's bottom edge. **Convention, and why it is not the glyph descender the plan named:** a first version measured from the descenders (the depth of "gjpqy" in `\Large`); the private harness then showed 30 of 48 entries differing on the title slide by 1.5 and 2.8bp, because the real decks' last subtitle line has no descender glyphs or is set smaller, and TeX's own line box (the deeper of the strut and the deepest glyph) is what the old placement measured from. A hook that is content-independent and a render identical to v10.9.0 exclude each other for these decks; the line box keeps the render identical (user decision 4's goal) and is what the old comment said ("the space under the last line"). Open question for the user: descender-based, with the 1.5-2.8bp shift on the real title slides. The title frame's text box is no longer put through the frame's flow after a `\vspace*`; it is a tikz node, anchored `south west` at the page's corner shifted right by `\SMTextMarginLeft` (where the flow put it) and down by `\SMTitleframeBoxHeight`, as the colored box is, and the vbox ends `\SMTitleframeBottomPad` under its last line. The old value contained beamer's offset at the top of the frame body: 41pt = 8.505pt + 32.495pt. The new default 8.505pt reproduces the SlideMage template's title slide to 0.001bp (baselines 95.242 / 154.411 / 175.034 against 95.243 / 154.411 / 175.034; x 39.571 unchanged). The stress template sets 30pt (it needed 55pt for about 30pt) and gets 30pt: the deepest ink of a "gjpqy" last line stands 29.9bp = 30pt above the box's edge.
- **Info keys.** The base writes the geometric hooks into the PDF info dictionary, one key per hook name in bp (`SMLogoHeight`, `SMTextMarginLeft/Right`, `SMFrametitle{Top,Bottom,Right}Padding`, `SMFrameSubtitleStrutEnd`, `SMFootnoteSep`, the four `SMSideFootnote` lengths, `SMBlockSideMargin`, `SMBlockTitleMarkerWidth`, `SMTitleframeBoxHeight/BottomPad`, `SMSectionframeBoxHeight`, `SMQuoteBoxHeight`, `SMQuoteAttributionGap`, `SMProgressStripHeight`) plus `SMFrametitleXHeight` (the X height the top padding is measured against) and `SMFootlineSidePadding` (a macro in ex, read in the footline font). `check_layout.py` reads them with `pdf_hooks()`.
- **check_layout.py.** Two new checks. `edge`: the frame number (its advance box) and the footnote lines end on the logo's padding edge, the page's width less `SMFrametitleRightPadding`, within the tolerance; a PDF without the key is compared with the logo's visible edge plus a point, and only on frames with the ordinary title bar (without that restriction the manual's slide 1xf, a frame without the logo patch, was flagged). `titlepad`: on a title frame (a colored box at the corner as high as `SMTitleframeBoxHeight`, narrower than the page, not a quote box) the deepest ink of the last line stands the pad above the box's edge; a last line without descender glyphs is not checked (its line box is the strut's, which the PDF does not record). Both are exact on the calibration deck under the stress template and under fira and lmsans (0 findings, exempted findings 10 / 6 / 6, as before step 11; the new slides are in a deck of their own so that the count stays). Unit tests with synthetic pages in `tests/test_check_layout_margins.py`.
- **Geometry tests.** `tests/test_hook_geometry.py` (compiles the calibration deck under the stress template and under SlideMage/fira, and the new `decks/geometry.tex` with slides ZG1 text margins plus subtitle and ZG2 side footnotes in a standard frame; opt-in `SLIDEMAGE_TEX_TESTS=1`; about a minute). A table says for every length of the catalog which test reads it back or why it cannot be; a test keeps the table complete. Read back from the PDF, value against drawn geometry: the text margins (a rule `\linewidth` wide spans margin to margin, lines begin at the left one), the title text's left edge, its baseline (top padding + X height), the title box's bottom (baseline + bottom padding, + the subtitle strut end with a subtitle), the logo's height (the logo file's artwork scaled by `\SMLogoHeight`) and its right padding, the footer box height, the footer text and id sizes, the footline's left padding, the footnote size, the footnote gap above the footer, two footnotes one `\SMFootnoteSep` + descender apart, the side-footnote strip (right inset, top sep from the foot of the title block, longest line <= Hsize and >= 0.9 Hsize), a block's text one `\SMBlockSideMargin` right of the column, the section and quote boxes' heights, the quote attribution's gap (0.5bp: TeX's box of the tallest character, not its ink), the title frame's text (the deepest ink of a "gjpqy" line against the box's edge, 0.12bp), and the default title slide against v10.9.0's positions.
- **Hook audit** (catalog `SlideMage_setup.tex`; every other geometric hook reads back where its name says). Fixed: `\SMTitleframeBottomPad`. Documented in the catalog, no look changed, and asked about in the report: (1) `\SMFrametitleBottomPadding` is the title box's bottom padding (baseline to the box's bottom, exact in the PDF), but the logo's white patch trims the visible bar to the logo's bottom edge (`\SMTitleBarBottomAlign`, from the top padding, the title font and the logo height), so the bar's bottom edge is not set by it unless it makes the box shorter than the logo's bottom; it fixes where the body begins. (2) `\SMSideFootnoteTopSep` hangs the strip from the foot of the title block (the box's bottom + beamer's 3pt gap), which lies 3-10pt under the visible bar, so the gap seen from the bar is larger than the hook. (3) `\SMFootlineHeight`, `\SMFootlineDepth` and `\SMRightFooterPadding` move nothing on the page (the stress deck with 5ex / 1ex / 9ex is identical on 23 pages): the derived `\SMFootlineVOffset` and `\SMFooterRightShift` cancel them. (4) `\SMFootlineSidePadding` moves the footer text's left end only (9ex instead of 4ex moves it 17.7bp; the right end stays on the logo's edge). (5) `\SMProgressStripHeight` is the room the content below a `\progressstrip` is moved down by, not the strip's drawn height (11.2pt, set by the node's own text height, depth and padding). Not read back, with reasons in the test table: `\SMBlockTitleMarkerWidth` (visible only when a block title wraps), the title/subtitle spacing (`\SMTitleframeTextSep`, `\SMTitleframeBandGap`), `\SMSectionframeContentDrop` (step 10), `\SMSideFootnoteMarkerShift`, and the list and drawing lengths.
- **Compat.** Entry `titleframe-bottom-pad` (v10.10.0, APPEARANCE, detects project templates and project macros that set the hook; a test). The CHANGELOG entry has `BREAKING:` for the same case; no shipped template and none of the real project's templates sets the hook (checked in the regression copy, 2026-10-29).
- **Theme.** Unchanged in this step, so no new LPPL change item.
- **User answers to step 11's questions (2026-10-29):** (1) the bottom pad stays measured from the last line's box
  (identical render), not from the glyph descender; (3) BREAKING paragraphs on minor bumps (v10.1.0, v10.7.0-v10.10.0)
  are fine; (4) no theme LPPL item for step 11 is right. (2) The user asked whether the three hooks whose visible
  result does not follow the name could be renamed instead of reworked. Proposal, waiting for the user's yes:
  `\SMProgressStripHeight` -> `\SMProgressStripRoom` (the room below, not the drawn height);
  `\SMSideFootnoteTopSep` -> `\SMSideFootnoteTitleBlockSep` (the gap below the title block);
  `\SMFrametitleBottomPadding` keeps its name (accurate for the title box; the logo patch trims the visible bar,
  documented); `\SMFootlineHeight`, `\SMFootlineDepth`, `\SMRightFooterPadding` are removed (they move
  nothing). With a compat entry that renames or reports them in project templates (none of the real project's
  templates sets any). Proposed place: a small step before step 12, or inside step 13.

### Step 11b: two hooks renamed, three inert ones removed

**Done (v10.11.0).** The user approved the proposal above on 2026-10-29.
- **Renames**, everywhere (catalog, base, theme, stress template, tests, README, plans): `\SMProgressStripHeight` -> `\SMProgressStripRoom` (the room below the strip) and `\SMSideFootnoteTopSep` -> `\SMSideFootnoteTitleBlockSep` (the distance the strip hangs below the foot of the title block); the catalog comments say so. `\SMFrametitleBottomPadding` keeps its name. The PDF info keys follow the names. `tools/check_layout.py` and `tools/calibrate_font_profile.py` name neither hook.
- **Removed**, with what replaced each: `\SMRightFooterPadding` is gone from the footline (an `\hspace` before the frame number) and from the term that `\SMFooterRightShift` added back, so nothing is left to cancel. `\SMFootlineHeight` and `\SMFootlineDepth` turned out not to be inert in one place: the footline box's height and depth enter the mini navigation's length (`\SM@temp@PaperheightFrametitle` in the two `mini nav progress` templates) as well as the derived `\SMFootlineVOffset` and `\SMFooterTextDrop` that cancel them. They are kept as the theme's own lengths `\SM@footlineheight` (1.5ex) and `\SM@footlinedepth` (0.1ex), with the catalog's values, so every position stays; they are no hooks any more, so a template that sets 2ex no longer changes the mini navigation (the stress template's 23 pages show nothing else).
- **Guard.** Like step 8's, in `SlideMage_setup.tex`: `\newcommand` under each of the five old names stops the compile with a package error ("... was renamed ..." or "... is no longer a hook"), checked by compiling the stress template with two old names (both errors reported). `tests/test_template_catalog.py` keeps the catalog, the stress template (sets every hook) and the guards in line.
- **Compat.** Entry `hook-renames-and-removals` (v10.11.0, BREAKS) in `src/slidemage/compat_hooks.py`: `migrate` renames the two in project templates, layout profiles and the macros file (CRLF kept, idempotent), `detect` lists the renamed ones still there and every use of the removed ones. `sm_rename`'s old `gotham...` mapping for the three removed names stays (it leads to the new error that says they are gone).
- **Pins** of the setup layer, the base and the theme renewed (`preview_equivalence`, no view-dependent rule entered).
- **Verification.** Full suite: only the load-flaky GUI tests fail in the parallel run and pass alone; with `SLIDEMAGE_TEX_TESTS=1` also the known `test_deck_snapshot` (3) and `test_a_real_beamer_deck_is_read_slide_by_slide`, plus `test_the_stress_template_deck_is_clean_against_its_own_margins` and a workspace-window test that passed alone. `check_layout.py` on the calibration deck: 0 findings, exempted 10 (stress) / 6 (fira) / 6 (lmsans). Regression: in-repo 12 entries, 1084 pages, all identical (a first run showed 12 entries differing: a stray `\makeatother` in the theme, fixed before this); private: 57 entries, 7160 pages, 0 differences.
- **Theme.** The theme's behaviour is unchanged (two lengths now internal), so no new LPPL item.

## Done 2026-10-30 (v10.12.0), notes for the later steps

Step 12 (section E). User decisions (2026-10-29/30): `columns[T]` below content keeps a list's gap (option a, the general rule) and the manual's slides are fitted to it; a `\source{}` written after a `\pause` appears with the last step (beamer's rule: it belongs to what it follows, and the student versions show the final step); the automatic "Image source(s)" line is shown on every step.

- **Footnotes in revealed content** (`latex/beamerthemeSlideMage.sty`, after `\setbeamertemplate{footnote}[SMFootnote]`; LPPL change item 10, package version 10.12.0). Beamer builds a footnote's text where `\footnote` is called, into the frame's footnote box, and covers it only by `\uncover#2` with the footnote's own specification; the box is set at the frame's bottom, outside the content's covering. The theme redefines `\beamer@framefootnotetext` and `\@mpfootnotetext` (copies of beamer's, a test compares them with the installed beamer) with `\SM@FootnoteCover{#2}` in place of `\uncover#2`. With a specification of its own the footnote is uncovered by it as before; without one it is covered when `\beamer@coveringdepth` (raised by `\uncover`, `\onslide`, `\pause`, `\item<...>` on the steps that hide their content) or `\SM@InvisibleDepth` (counted in `\beamer@begininvisible`/`\beamer@endinvisible`: `\visible`, `\onslide+`) is above zero: `\beamer@reallymakeinvisible`, as beamer covers a hidden `\footnote<...>`, or, under a colour-mixing `\setbeamercovered`, the footnote colour set inside the box where the mix is in force. Otherwise `\uncover{...}` exactly as before. The footnote keeps its space; nothing moves between steps. The side strip covers its copy again (`\SM@SideFootnoteCover`), which ends the old quirk of a `\footnote<2->` there showing on every step. `\ifSM@FootnoteShown` exempts a footnote of the whole frame: the base sets it around the "Image source(s)" `\source` (`\SMEmitImageSourceFootnote`, emitted at the frame's end, where a `\pause` still covers).
- **`columns[T]` below content** (`latex/SlideMage_base.tex`, the `T` key of `beamer@col`). At the columns level (vertical mode, or the outer paragraph a table leaves open, which the key ends; the per-column keys run in internal mode and do nothing) and when the frame's list already holds a visible box (`slidemage_list_has_no_visible_box`), the key typesets a top-level itemize and the same in a `[T]` column at that point (`\SM@toprefprobe`, with the list's `\prevdepth`) and puts the difference in front of the columns as a `\vspace` (which keeps `\prevdepth`): their first reference line starts where the list's would. Step 10's rule at the top, applied below content; no constant. A first version matched a `[t]` column and was dropped: a `[t]` column's `\leavevmode` head leaves an empty line above a list, a line lower than the list itself.
- **The manual.** Its slides had hand-made space before such columns (`\smallskip`, `\medskip`, `\bigskip`, `\vspace{6pt}`) to make up for the tight head; it is removed on the 38 slides that had it (1w4's `\vspace{-2pt}`, a tightening, stays and is now -3.5pt). Eleven full slides got a shorter line, a smaller picture or less space so that they still fit: 1an 1b6 1be 1fg 1pf hd5 1rv 1us 1vd 1w4 1wk (no slide version change, as for earlier layout fixes). check_layout.py then shows no new finding in any of the 12 in-repo entries, and four old ones are gone in each (1an, 1fg and 1wk fit now; 1an's source line was below the page). The real project's copy of the manual has its own slides; it gets these edits with the manual, not with the framework.
- **check_layout.py.** The deck's usual last footnote line is taken from each slide's last step only (on an earlier step hidden footnotes leave the visible ones higher). **Gap found, for step 13:** the `bottom` check does not see text inside or below the footer box; 1fg's source line went below the page edge unnoticed (the regression classifier found it), and 1ub's "Image source(s)" line is below the page in the baseline already (not touched by this step).
- **Fixtures and tests.** Calibration deck: ZCM (footnotes after `\pause`, in `\item<3->`, `\onslide<4->{}`, `\uncover<5->{}`, `\visible<6->{}`, one outside, one with `<2->`), ZCN (`columns[T]` below a list and a table) and ZCO (the same with plain lists); ZCH's footnote now appears with its item, ZC6's `[T]` row no longer touches the table. Geometry deck: ZG3 (side strip), ZG4 (image source with a reveal; the fixture got `media/alt-text.csv` with one image). `tests/test_revealed_footnotes.py`; unit test for the footnote line in `tests/test_check_layout_margins.py`.
- **check_layout.py on the calibration deck:** 0 findings, exempted 10 / 6 / 6 (stress / fira / lmsans), as before.
- **Parallel compiles.** `tools/calibrate_font_profile.py` writes its deck wrapper under a name of its own per call (the job name stays): with `pytest -n 8` two tests compiling the same deck used to share it (PermissionError, compiles cut short), which the larger decks of this step made frequent.
- **Compat.** No entry: nothing a project carries must be acted on (no `\footnote<...>` in the real project; a hand-made space before a `columns[T]` only makes a gap larger), and the plan names no APPEARANCE entry for this step.
- **Regression** (baselines `.regression/repo-v1011`, `private-v1011` at `fcd2b65b`; every differing page classified by a script: all text of the page kept, and either footnote-size lines hidden or everything below a `columns[T]` moved by one shift). In-repo: 12 entries, 1126 pages, 0 failed compiles, no page count or font list changed; 532 pages on 39 slides differ, all of them slides with a `columns[T]` below content: on 30 (1az 1b2 1cb 1cx 1d8 1dk 1gu 1hi 1je 1jv 1kg 1mu 1n6 1nk 1nt 1pn 1r8 1sv 1t2 1th 1ti 1u4 1un 1us 1w4 1wa 1y8 des dkf neg) everything from the columns down moves by one shift (net of the removed space, mostly +3.3bp, 0.1-6.2bp, 1kg +10.7bp: below a table, where the head was drawn into the rule), on 9 (1an 1b6 1be 1fg 1pf 1rv 1vd 1wk hd5) the same plus the fit edits above. No slide of the manual has a footnote in revealed content (1uw and 2v9 have reveals and footnotes, but the footnotes are outside the revealed parts). Private copy (the real project): 57 entries, 7160 pages, 0 failed compiles, no page count or font list changed; 368 pages on 14 entries differ. (1) 34 course slides hide footnote lines on the steps before their content -- footnotes in revealed content, the intended fix: a7b am5 azy ccz cqh d56 ds4 dsk gv2 hnr jww k5w m9i pvm qvm ren sas uuh vj7 wcb yhe yvt; a `\source{}` after a `\pause`, now with the last step: crc d5j ez4 gym knt raf sn8; both: bzy m36 qk2 tuw y5z. No "Image source(s)" line is hidden any more (a first run hid it on 17 slides, which led to `\ifSM@FootnoteShown`). (2) The project's own copy of the manual (35 slides, 1an ... 1y8 as in-repo): the `columns[T]` shift on its unedited slides, so there its full slides overflow as the in-repo ones did before the fit edits (on 1be a footnote line goes below the page) until the project gets the edited manual slides. Nothing else differs (pages the script left unclassified are hidden footnotes whose `\href` underline is a drawing that moves with them, or one drawing moved by 0.01bp). Images (baseline | current | difference): `D:/uniCLOUD/SlideMage/.regression/step12-images/`.

## Done 2026-10-30 (v10.13.0), notes for the later steps

Step 13 (section F). The acceptance bar is the 2x2 matrix read literally: the calibration deck and the stress
deck (`decks/calibration.tex`, `decks/stress.tex` of `tests/fixtures/template_stress/`) pass `check_layout.py`
cleanly under fira and under lmsans, under the SlideMage template and under the stress-test template.

- **`tools/calibrate_font_profile.py` is a check, and checks what actually compiled.** It already reported
  pass/fail per metric (step 9/10 had already removed the Fira-specific offsets and the "numbers to copy"
  framing); what step 13 found and fixed: (1) the section bar height, a list's label gap and a nested
  enumerate's slot and gap were checked against the catalog's own default (`SlideMage_setup.tex`), not against
  what the compiled template actually set -- invisible as long as nothing was ever checked under a template
  that overrides them, which the stress-test template does for all three. The section bar height now reads the
  base's own PDF key (`SMSectionframeBoxHeight`, as `check_layout.py` already does for its own checks); the
  label gap and the nested enumerate's two em hooks read the template's own text first (`\renewcommand`), the
  catalog's `\newcommand` only as the fallback for an older PDF or an unmodified hook. (2) The label-gap check
  itself mismatched a frame's own title text as a list label when its running text happened to split into a
  span that reads like one (the calibration deck's own title, "Lists with a), 1), 1. and a. labels" -- "1."
  followed by "and"), in the title's own font and size; picked as the "worst" label this skewed the check
  against a value with nothing to do with `\SMLabelItemGap`. `label_gap()` now excludes anything above the
  title bar's bottom edge. Found and fixed from a peer session's review of this step, which ran the full 2x2
  matrix and caught the stress-test template combinations nobody had run calibrate_font_profile.py against
  before.
- **`tools/check_layout.py` sees text in and below the footer box** (the gap step 12 found). The `bottom`
  check's `low` detection only ever saw body content inside `area` (the page above the footer box); a small,
  left-aligned line that is not a footnote's own continuation (not right-aligned, no existing footnote block to
  join) was kept only when it still fell inside that area -- dropped silently otherwise, including when an
  overfull frame pushed it into or under the footer box itself. It is now kept as an item regardless of where
  it landed, the same as a real footnote continuation already was. New unit test
  `test_bottom_sees_a_small_line_an_overfull_frame_pushed_into_or_under_the_footer_box`.
- **`check_layout.py`'s logo detection also missed a tall logo.** `logo_visible_right()`'s scan window, used on
  a title or quote frame (no ordinary title bar to bound it by), was a flat 20pt guess that fits the shipped
  templates' own small logo (`\SMLogoHeight` 3ex, about 13pt) but not the stress-test template's taller
  three-square calibration logo (about 22pt), which under Fira sits a few points lower than under Latin Modern
  Sans and fell outside the window entirely -- found from the peer review's own 2x2 matrix run (fira +
  stress-test: two unexempted `right` findings on ZC1 and ZC9, the title and quote frames, each a logo mark
  the checker itself was blind to, not slide content). The window now reads `\SMLogoHeight` from the PDF (a
  hook since v10.10.0) for real headroom instead of another guessed constant. New unit test
  `test_the_logo_detection_window_covers_a_tall_logo_a_title_frame_draws_low`.
- **Slide 1ub's "Image source(s)" line below the page** (the other gap step 12 found, older than that step).
  The cause, found once `check_layout.py` could see it (above): the slide's own column split, a 12-item list at
  0.38 of the frame's width in `\scriptsize`, wrapped two items onto a second line, 9.3pt more than the frame
  had room for (`Overfull \vbox (9.29388pt too high)`), which pushed the automatic footnote below the page
  along with it. The columns are now 0.52/0.45 (a narrower image, a wider list column) instead of 0.59/0.38,
  which stops the wrap at 0 overfull boxes; no text, callout or image changed, no slide version bump (the same
  convention as step 12's eleven fit edits). Before/after images:
  `D:/uniCLOUD/SlideMage/.regression/step13-images/repo-slidemage-manual-instructor-p25-1ub/`.
- **The 2x2 matrix, with both fixes above.** Calibration deck: 0 findings under every combination, exemptions
  6 (fira+slidemage) / 6 (lmsans+slidemage) / 10 (lmsans+stress-test) / 10 (fira+stress-test), each for content
  meant to break a margin by design (the three exemption comments in `ZC2`, `ZCA`, `ZCB`, unchanged and still
  accurate). Stress deck (`decks/stress.tex`, the optional-features deck: mini frames, progress bar, divider
  frames, watermark): clean under both profiles with the SlideMage template (these features stay off there, so
  it renders as an ordinary deck); under the stress-test template, where the features are actually on,
  `check_layout.py` finds real findings on its own three slides (left/right/bottom, plus one jitter) that this
  step did **not** chase down -- the footer text sits noticeably higher than the footer box's own background in
  that configuration (diagnosis: the progress-bar-in-foot template is appended after the ordinary footline
  content, which grows the footline's own measured height and, since the footline box is anchored to the
  bottom of the page, pushes the earlier footer text up, while the footer's background box is drawn as a
  separate, independently fixed-height overlay that was never resized to match). `\SMFooterBoxHeight` is read
  by several other placements elsewhere in the base (content bottom align, side-image/section-figure height,
  the footer text's own vertical centring), so a quick fix risks moving other things; these optional features
  are off by default and not used by the real project, so the blast radius of leaving this open is zero outside
  the stress deck itself. **Open for the next step or the user:** either give the footer's background box the
  progress bar's own height when `\SMProgressBarPosition` is `foot`, or decide the stress deck's own findings
  are acceptable and add the usual `%% layout-check: skip ...` exemptions to its three slides once that
  decision is made (not added here, since the cause is a layout bug, not content meant to break a margin).
- **`tests/test_template_catalog.py`** gains three checks (`test_profiles_define_only_an_allowed_list_of_font_names`,
  `test_no_template_sets_a_name_the_profile_computes`, `test_every_geometric_hook_has_a_check_in_test_hook_geometry`):
  a profile may declare only `\SMCodeFont`/`\SMInlineCodeFont` as a font family of its own; no template sets one
  of the profile's own metrics or code fonts (`\SMCardHeadingFont` stays the one documented exception, a
  template redefining it to pick one of its own card-heading looks); every geometric hook of the catalog has an
  entry in `tests/test_hook_geometry.py`'s own table, cross-checked from this file too.
- **Verification.** Full suite: 3806 passed, 69 skipped (opt-in TeX tests), 0 failed, one parallel run, no GUI
  flakes this time. Opt-in TeX tests (`SLIDEMAGE_TEX_TESTS=1`): only the four known pre-existing failures
  (`test_deck_snapshot` x3, `test_a_real_beamer_deck_is_read_slide_by_slide`). In-repo regression: 12 entries,
  1126 pages, 0 failed compiles; 1 page differs per entry (page 25 of the plain manual decks, 31 of the
  manual-copy decks -- slide 1ub, confirmed by text), no `FLAKY` on retry. Private copy (the real project): 57
  entries, 7160 pages, 0 failed compiles, 0 differences, all identical -- expected, since the project's own
  copy of the manual's slide 1ub is a separate file this step never touched (see step 12's note on that copy).
- **Compat.** No entry: nothing a project carries must be acted on (no catalog hook renamed or removed, no
  derived name added; the tool/test changes affect only `tools/` and `tests/`, not anything a project ships).
- **No pins renewed.** No `latex/` framework file changed this step (`tools/calibrate_font_profile.py` and
  `tools/check_layout.py` are not framework files, and `example/slides/1ub-...tex` is a project slide, not
  pinned).
