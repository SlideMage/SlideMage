# Tools for the SlideMage manual

The manual is `example/decks/slidemage-manual.tex` (slides `example/slides/1*`,
code panels `example/snippets/`). Its generated images live in `example/media/`
and are rebuilt with the scripts here, from the repository root, with the
SlideMage venv's Python. Rerun the step whose input changed.

| Images | Made by | Rerun when |
|---|---|---|
| `illustration-*.pdf`, `chapter-logo-building-blocks.pdf` | `python tools/manual/make_illustrations.py` (vector, from `illustrations.tex`) | the illustrations change |
| `screenshot-slidemage-*.png` | `python tools/manual/make_screenshots.py OUT_DIR` (the real widgets of the workspace window, drawn off screen: on Windows by the native platform with the window never shown, since the offscreen platform there draws some labels in the icon font; elsewhere offscreen Qt; light theme, on a throwaway copy of `example/`; `--list` names the shots, `--only NAME…` makes some). It writes every shot to `OUT_DIR` and, cut from them (`MANUAL_IMAGES` in the script: which shot, which crop), the manual's images to `OUT_DIR/manual/` under the names the slides use; copy those into `example/media/`. | SlideMage's UI changes; then check the callouts of slides `1ub` and `1ti`, whose positions are fractions of the picture |
| `screenshot-slide-gallery-*.png` | `python tools/manual/make_crops.py gallery example/decks/slidemage-manual.pdf` | a frame-type demo slide changes |
| `screenshot-slide-version-*.png` | `python tools/manual/make_crops.py versions <instructor.pdf> <during-course.pdf> <after-course.pdf>` -- the manual compiled as each version (a wrapper deck with `\def\deckversionoverride{during-course}` before `\input{slidemage-manual.tex}`) | slide `1th` changes |
| `screenshot-slide-presenter.png` | `make_crops.py one <presenter.pdf> 1y3 presenter` -- the manual compiled with `\def\SMPresenterModeOverride{1}` | slide `1y3` or the presenter layout changes |
| `screenshot-slide-appendix-grid.png` | `make_crops.py titled <appendix.pdf> "Frame types" appendix-grid` -- a compile with the generated appendix (`compiler.wrapper_text` of a job with `appendix_toc=True`) | the appendix layout changes |
| `screenshot-slide-template-*.png` | `make_crops.py one <deck.pdf> 1wa template-<name>` -- one-slide decks with `\slide{1wa-EN-Columns-and-Tables}` under each template; MCI and Innsbruck need a project that has those templates (`\input@path` pointing there) | slide `1wa` or a template changes |

Crops are PNG at 288 dpi, not PDF pages: an embedded PDF page carries its
text, so the slide showing it would contain the cropped slide's footer, and
SlideMage's preview capture (which reads the first "slide id" on a page) and
screen readers would pick that up.

Compile the manual twice after its slides change (`latexmk` does): the chapter
agendas and the footer navigation are built from the previous pass's `.aux`.

`make_screenshots.py` works on a copy of `example/` and `latex/` in a temporary folder (with three placeholder decks, one per deck group, so the deck menu shows the grouping; the stored previews of `example/.build/preview-cache` come along), uses a fixed list of Ollama models and no network, and leaves the repository alone. The AI is a plugin since v9.1.0: `--plugins DIR…` names checkouts of `slidemage-plugin-claude` and `slidemage-plugin-ollama` (default: `SLIDEMAGE_PLUGIN_PATH`, else the folders next to this repository), loaded as dev plugins instead of the ones installed on the computer; without them the shots show no AI and the chat shot is left out. The focused slide is rendered for real when no stored preview of it exists (the first time takes a minute or two); the slide list's thumbnails stay empty boxes unless the stored previews cover those slides. Most footer numbers in the crops
are page numbers of the manual: when slides are added or removed earlier in
the deck, rerun the crops too.

## Edits made in a project's copy of the manual

Projects get a copy of the manual (`bundled_copies.py`), and a user may edit
slides there. `python tools/manual/adopt_user_edits.py --project <project>`
lists the changes that exist only in the project's copy (compared with the
baseline in its `.slidemage/bundled_copies.json`) and, with `--apply`, copies
them -- and the project's frozen versions of those slides -- into `example/`,
so the next SlideMage version carries them. Slides changed on both sides are
listed as conflicts and merged by hand. Run it before every release.
