# Your own slides use the framework instead of per-slide layout fixes

Status 2026-11-02: batch A is done; `\SMContentHeight` is on develop. What is left, and how to run it, is in `docs/handover.md`, section 9.

User request 2026-11-01: do for the slides in `D:\uniCLOUD\Slidemaster` what step 17c part B did for the manual
(fixed sizes and positions replaced by ones derived from the available space and the catalog, see f2c37515).

## What is there

Of the 997 slides the decks use, about 154 own slides (`*-current.tex`) size or place something by hand for the Uni Graz
layout. Manual slides that live in the project (1pf, hd5, 1vh, 1w4, 2v9, ZZL, ZZO) are copies of the app's manual
and stay out; 1pf/hd5 still use `width=98pt` screenshots in the manual itself, which is a fix for the SlideMage
repository, not here.

| Group | Pattern | Framework replacement | Slides |
| --- | --- | --- | --- |
| A | image as an overlay at `(current page.south)+(0,20pt)` below the text, sized in pt | `\fitfigure` (top=here, valign/halign), which fills the room down to the Bottom Margin | about 24: a7b bwi d5j f7p fmn g96 hbt igr j6f n5f ni4 pf2 q3b qq5 sch svu t5u tcc tii trx vvk wki wmm zax |
| B | image beside the text with hand-computed heights and text widths from `\paperheight`, `\SMFooterBoxHeight` ... (`\zwkImgContentHeight`, `\dskBandHeight`, ...) | `\besidefigure[height=...]` with the height relative to the content area; text column follows | dsk ice zwk cy9 xv8 e84 qdz fh6, plus wjx v5y zax c2t fuv zkx (same idea, pt coordinates) |
| C | figure in a corner with a fixed width (`\cornerfigure{\includegraphics[width=7.8cm]...}`) next to full-width text | `\besidefigure` where text runs beside it (text column no longer overlaps under a narrower layout); small logos and icons (1.6-2.3cm, 14pt, 0.85em) stay | acw aqe bfa f6m h5z p8i za2 zn5 zsg wmu wum i7z scs y4p zjs (logos baa y5z jky jkf qbj waj tgz stay) |
| D | inline images and tables in fixed cm/pt (`width=3cm` in a 4x2 matrix, `width=6cm` in a column) | fractions of `\linewidth` or `\columnwidth`, as 1rv/1td did | shw h36 fmn q3b j6f xci eaq szi n8e fm6 bbt nin dxg n3m qnb gi7 wvf pm2 and others |
| E | overlays at absolute page coordinates (`(current page.north west)+(420pt,-74.57pt)`, dotted lines at `(343.32pt,-93.26pt)`) | anchored to what they mark: a named image node and coordinates relative to it (`($(img.south west)!.6!(img.south east)$)`), or a remember-picture mark in the text line; content top from `\SMContentTopAlign` instead of 41.58pt | ayr sas dsk zwk y89 mpn m7c wjx c4c d76 dh6 eau fiq gtt ha9 jae n2u nc8 neb nt5 p33 q3q s55 vtm w83 wbd x49 |
| F | negative `\vspace` to squeeze a slide | removed; the slide is shortened or rebalanced if it then overflows (German partner too) | cae crc djt ebq emv gk7 pgk q5x xqq y57 zve |

The exact list per batch is fixed when the batch starts (one slide can be in several groups; it is done once, in its
first group). Slides that only explain their history in long comments get the comment trimmed to what still holds.

## Rule

A slide renders as before under the Uni Graz template (small shifts allowed where a guessed number becomes the
framework's value) and has no `tools/check_layout.py` finding under Uni Graz and under the shipped greyscale template.
Where an old version is frozen (`-v1-0-0.tex` etc.), only `-current` changes; a slide whose look changes noticeably gets
its version bumped as usual.

## Possible framework addition (SlideMage repository, own version, only if you want it)

Groups B and E compute the content area's height by hand (`\paperheight-\SMFooterBoxHeight-...`) in at least 8 slides.
A length `\SMContentHeight` (Top Margin to Bottom Margin) and `\SMContentWidth` set by the base would make
`\besidefigure[height=0.8\SMContentHeight]` possible. Without it, `\fitfigure`/`\besidefigure` cover most cases.

## How

- Branch `framework-fit` in `D:\uniCLOUD\Slidemaster`; the uncommitted files there (`bundled_copies.json`,
  `project.json`, the three deleted template screenshots) are left alone.
- One batch per group, A to F, each a commit; stop after each batch for your go.
- Per batch: compile the affected decks before and after with `tools/framework_regression.py` (Uni Graz; config
  like `C:\Users\ms\SlideMage\regression\real-v0120.json`), compare page images, and run `check_layout.py` under Uni
  Graz and greyscale; report the slides that changed visibly, with before/after images.
- Edits of a batch can go to one sub-agent per 8-10 slides; the regression and the check stay here.
