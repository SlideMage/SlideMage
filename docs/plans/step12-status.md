# Step 12 (plan section E): status, stopped for a decision

Branch `claude/fw-step12-bugs-8bdcad`, from `dev-framework-redesign` at `fcd2b65b` (v10.11.0). Work in progress: the version
is still v10.11.0, no CHANGELOG entry, no plan "Done" notes. The step stopped because the `columns[T]` fix makes full slides
of the manual overflow (the stop rule: lost content goes to the user).

## 1. Footnotes in revealed content: done, no open question

- **Mechanism** (`latex/beamerthemeSlideMage.sty`, after `\setbeamertemplate{footnote}[SMFootnote]`; LPPL change item 10,
  package version 10.12.0). Beamer builds a footnote's text where `\footnote` is called, into the frame's footnote box, and
  covers it only by the footnote's own specification (`\uncover#2` in `\beamer@framefootnotetext` and `\@mpfootnotetext`); the
  box is set at the frame's bottom, outside the content's covering. The theme redefines both macros with `\SM@FootnoteCover{#2}`
  in place of `\uncover#2`: with a specification of its own, the footnote is `\uncover`ed by it as before; without one, it is
  covered when beamer's covering depth (`\beamer@coveringdepth`, raised by `\uncover`, `\onslide`, `\pause`, `\item<...>` on
  the steps that hide their content) or `\SM@InvisibleDepth` (counted in `\beamer@begininvisible`/`\beamer@endinvisible`, for
  `\visible`, `\onslide+`) is above zero, the way beamer covers a hidden `\footnote<...>` (`\beamer@reallymakeinvisible`; under
  a colour-mixing `\setbeamercovered{transparent}` the footnote's colour is set inside the box, where the mix is still in
  force). Otherwise `\uncover{...}` exactly as before, so footnotes outside revealed content are unchanged. A covered footnote
  keeps its space: nothing moves between steps. The side-footnote strip covers its copy again (`\SM@SideFootnoteCover`), which
  also ends the old quirk that a `\footnote<2->` in side mode showed on every step.
- **Fixtures:** calibration slide ZCM (six steps: `\pause`, `\item<3->`, `\onslide<4->{}`, `\uncover<5->{}`, `\visible<6->{}`,
  plus one footnote outside revealed content and one `\footnote<2->`); geometry slide ZG3 (side strip); ZCH (existing: its
  footnote now appears with the third item).
- **Tests:** `tests/test_revealed_footnotes.py` (source checks; the two macros equal beamer's own apart from the cover, read
  from the installed `beamerbaseframecomponents.sty`; with `SLIDEMAGE_TEX_TESTS=1` the step-by-step visibility under the stress
  template and SlideMage/fira, the side strip, ZCH).
- **check_layout.py:** the deck's "usual" last footnote line is taken from each slide's last step only (on an earlier step a
  hidden footnote leaves the visible lines higher than the block ends); unit test in `tests/test_check_layout_margins.py`.
- **In-repo set:** no slide has a footnote in revealed content (1uw and 2v9 have reveals and footnotes, but the footnotes
  are outside the revealed parts); no page changed for this reason. Private set: see section 4.

## 2. columns[T] below content: implemented, makes full slides overflow

- **Mechanism** (`latex/SlideMage_base.tex`, the `T` key of `beamer@col`). When the `T` key runs at the columns level (vertical
  mode, or the outer paragraph a table leaves open -- the key ends it; the per-column keys run in the columns' own box, internal
  mode, and do nothing) and the frame's vertical list already holds a visible box (`slidemage_list_has_no_visible_box`, the
  columns hook's test), it typesets a top-level itemize and the same itemize in a `[T]` column in boxes at that point
  (`\SM@toprefprobe`, step 10's probe, with the list's `\prevdepth`) and puts the difference in front of the columns as a plain
  `\vspace` (which keeps `\prevdepth`): the columns' first reference line starts where the list's would without the columns.
  That is step 10's rule for the top (`[T]`'s compensation puts its first line where a plain list starts), applied below
  content. A first version matched a `[t]` column instead; that put the columns a whole line lower still (a `[t]` column's
  `\leavevmode` head leaves an empty line above a list) and was dropped.
- **Fixtures:** ZCN (`columns[T]` below a list and below a table) and its twin ZCO (plain lists in the columns' place); ZC6
  (existing) changes. Before: below the table the `[T]` row was drawn over the table's bottom rule (8.3bp into it under the
  stress template); after: both rows keep a list's gap, to 0.13bp. Test in `tests/test_revealed_footnotes.py`.
- **check_layout.py** on the calibration deck: 0 findings, 10 / 6 / 6 exempted (stress / fira / lmsans), as before.
- **In-repo regression** (baseline `repo-v1011`, 12 entries, 1126 pages; log `.regression/step12-repo-compare.log`): 0 failed
  compiles, no page count or font list changed; 532 pages differ, all on 39 slides with a `columns[T]` below content (1an 1az
  1b2 1b6 1be 1cb 1cx 1d8 1dk 1fg 1gu 1hi 1je 1jv 1kg 1mu 1n6 1nk 1nt 1pf 1pn 1r8 1rv 1sv 1t2 1th 1ti 1u4 1un 1us 1vd 1w4 1wa
  1wk 1y8 des dkf hd5 neg). The columns and everything below them move down 4.7-16.3bp (mostly 6.0, 7.2, 8.2, 9.2bp). **The
  manual's slides are full**, laid out against the old tight `[T]` head, so check_layout finds new problems on 17-19 of them
  per deck: text into the footer clearance or below it (1be, 1pf, 1fg, 1cx, 1us, 1hi, 1wk; hd5, neg in the copy deck),
  footnotes pushed down (1b2, 1b6, 1d8, 1kg, 1rv, 1vd), the automatic Top Margin's room rule pulling the top up (1hi -2.4pt,
  1un -2.2pt, 1us -7.1pt, 1w4 -1.3pt), and 1th's step 4 overfull, so TeX shrinks its `\medskip` and the list jumps 2pt between
  steps. On 1be and 1an the last list line runs below the page and on 1an, 1fg, 1wk footnotes are pushed off the page (lost
  content). Images (baseline | current | difference): `D:/uniCLOUD/SlideMage/.regression/step12-images/repo/`.

## 3. The decision for the user

Options for `columns[T]` below content:

- **(a) As implemented** (a list's gap, measured). Correct by the plan's wording and consistent with the top rule; every
  `columns[T]` below content moves down by 5-16bp, and the ~19 overflowing manual slides (and those of the real project) need
  shortening or a local correction.
- **(b) Only remove the collision**: move the columns down only as far as needed for the head to keep a minimum gap below the
  content (for example the interline `\lineskip`, or the gap a plain line of text would keep), measured the same way. Slides
  where the `[T]` head already stands clear of the content (below a paragraph, like 1jv) stay as they are; the ones below a
  table or a rule (ZC6, ZCN) are fixed. Far fewer slides move, by less.
- **(c) Leave `columns[T]` as it is** and fix only the footnotes in this step.

## 4. Private set (the real project's copy)

Compare against `private-v1011` (57 entries, 7160 pages; log `.regression/step12-private-compare.log`): 0 failed compiles,
no page count or font list changed; 16 entries, 403 pages differ.

- **`columns[T]` below content:** 35 slides, all of them the manual's (1an 1az 1b2 1b6 1be 1cb 1cx 1d8 1dk 1fg 1gu 1hi 1je
  1jv 1kg 1mu 1n6 1nk 1nt 1pf 1pn 1r8 1rv 1sv 1t2 1th 1ti 1u4 1un 1us 1vd 1w4 1wa 1wk 1y8), the same moves as in-repo. None of
  the course decks has a `columns[T]` below content that moved.
- **Footnotes hidden on the steps before their content:** 45 course slides, by what the hidden line is:
  - a footnote (often a `ullcite`) in revealed content, the intended fix: a7b am5 azy ccz cqh d56 ds4 dsk gv2 hnr jww k5w m9i
    pvm qvm ren sas uuh vj7 wcb yhe yvt;
  - a `\source{}` line after a `\pause` (it now appears with the last step): crc d5j gym knt raf sn8;
  - **the automatic "Image source(s):" line** (`\SMEmitImageSourceFootnote`, emitted at the frame's end, so it inherits the
    covering of the frame's last `\pause`): f7p igr k3i me3 pe7 rjr; mixed with the two kinds above: bzy dxg ez4 fni fuv g96
    m36 qk2 tuw waj y5z. **This one is most likely wrong**: the line lists every image of the frame, including those shown on
    step 1. Proposed: emit it outside the covering (always shown), a two-line change in the base.
- Nothing else: every differing page is one of the two kinds (the pages the classifier first flagged are hidden footnotes
  whose `\href` underline is a drawing that moves with them, and 1be's overflow).
- Images (baseline | current | difference, one slide's pages per file name):
  `D:/uniCLOUD/SlideMage/.regression/step12-images/private/`.

Decisions this adds for the user: (d) should a `\source{}` written after a `\pause` appear with the last step (beamer's
rule, as implemented) or always; (e) the "Image source(s)" line always shown (proposed).

## 5. Compat

No compat entry, for either fix: nothing a project carries now behaves in a way it must act on. No real-project slide uses
`\footnote<...>`; two manual slides (1kg `\vspace{6pt}`, 1w4 `\vspace{-2pt}`) have a `\vspace` right before a `columns[T]`,
which would only make a gap larger, and the plan names no APPEARANCE entry for step 12.

## 6. Other changes made

`src/slidemage/preview_equivalence.py`: pins of the base and the theme renewed, with an audit note (no view-dependent rule:
the covering follows beamer's steps, which a handout collapses for content and footnotes alike). Version still v10.11.0.
