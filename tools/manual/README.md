# Tools for the SlideMage manual

The manual is `example/decks/slidemage-manual.tex` (slides `example/slides/1*`,
code panels `example/snippets/`). Its generated images live in `example/media/`
and are rebuilt with the scripts here, from the repository root, with the
SlideMage venv's Python. Rerun the step whose input changed.

| Images | Made by | Rerun when |
|---|---|---|
| `illustration-*.pdf`, `chapter-logo-building-blocks.pdf` | `python tools/manual/make_illustrations.py` (vector, from `illustrations.tex`) | the illustrations change |
| `screenshot-slidemage-*.png` | `python tools/manual/make_screenshots.py` (offscreen Qt, the real widgets, light theme; also refreshes the manual's slide previews from `example/decks/slidemage-manual.pdf`) | SlideMage's UI changes |
| `screenshot-slide-gallery-*.png` | `python tools/manual/make_crops.py gallery example/decks/slidemage-manual.pdf` | a frame-type demo slide changes |
| `screenshot-slide-version-*.png` | `python tools/manual/make_crops.py versions <instructor.pdf> <during-course.pdf> <after-course.pdf>` -- the manual compiled as each version (a wrapper deck with `\def\deckversionoverride{during-course}` before `\input{slidemage-manual.tex}`) | slide `1th` changes |
| `screenshot-slide-presenter.png` | `make_crops.py one <presenter.pdf> 1y3 presenter` -- the manual compiled with `\def\SMPresenterModeOverride{1}` | slide `1y3` or the presenter layout changes |
| `screenshot-slide-appendix-grid.png` | `make_crops.py titled <appendix.pdf> "Frame types" appendix-grid` -- a compile with the generated appendix (`compiler._wrapper_text` of a job with `appendix_toc=True`) | the appendix layout changes |
| `screenshot-slide-template-*.png` | `make_crops.py one <deck.pdf> 1wa template-<name>` -- one-slide decks with `\slide{1wa-EN-Columns-and-Tables}` under each template; MCI and Innsbruck need a project that has those templates (`\input@path` pointing there) | slide `1wa` or a template changes |

Crops are PNG at 288 dpi, not PDF pages: an embedded PDF page carries its
text, so the slide showing it would contain the cropped slide's footer, and
SlideMage's preview capture (which reads the first "slide id" on a page) and
screen readers would pick that up.

Compile the manual twice after its slides change (`latexmk` does): the chapter
agendas and the footer navigation are built from the previous pass's `.aux`.

`make_screenshots.py` adds three placeholder decks for its run (`#workdeck`,
`course-example-2027s`, `talk-example-seminar`, one per deck group) so the
deck table shows the grouping (slide `1d8`) and full rows (slide `1ub`), and
deletes them again; it unfolds every deck group for the run without touching
the project's settings. It also prints the centres of the elements slide
`1ub`'s numbered callouts point at, as fractions of the screenshot: after a
UI change, place each `\callout` just beside its element (never past the
picture's edge -- that widens the column). Most footer numbers in the crops
are page numbers of the manual: when slides are added or removed earlier in
the deck, rerun the crops too.
