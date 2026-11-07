# Design handbook

An English, 15-slide SlideMage project for core contributors and plugin authors.
It uses the repository's `latex/` and generic SlideMage template; it is not bundled
into lecturer projects.

From the repository root, regenerate tables and both themes' widget images:

```sh
PYTHONPATH=src QT_QPA_PLATFORM=offscreen .venv/bin/python tools/manual/make_design_handbook.py
```

Use your checkout's Python environment if `.venv` lives elsewhere. `--text-only`
updates tables without Qt; `--output /tmp/handbook` writes to another project root.
Tables read live `tokens.py` values and `ThemeTokens` fields. Plugin columns mark
public fields; core only means the field is not exposed. Roles are short editorial
labels in the generator. Translucent swatches show the wash composited over white.
Widget PNGs reuse kit gallery arrangements, supplemented with Badge, RowButton,
Label, the mono chip and faint icon options that its main window does not show.
The D1/D10 slide explains the recorded render decisions; it does not reproduce
historical plugin screenshots or depend on another repository.

Compile from this project root (POSIX shell):

```sh
mkdir -p build
TEXINPUTS="$(pwd)/../../latex//:$(pwd)//:" lualatex -interaction=nonstopmode -halt-on-error -output-directory=build decks/design-handbook.tex
TEXINPUTS="$(pwd)/../../latex//:$(pwd)//:" lualatex -interaction=nonstopmode -halt-on-error -output-directory=build decks/design-handbook.tex
```

The PDF is `build/design-handbook.pdf` (ignored, like other compiled decks).
If LuaTeX's font cache is read-only, set `TEXMFVAR` and `TEXMFCACHE` to writable
local folders or compile outside the sandbox. The sandbox build succeeded with
`TEXMFVAR=/tmp/handbook-tex-cache TEXMFCACHE=/tmp/handbook-tex-cache`
after creating that directory. On Windows, use `;` as the TeX
search-path separator. In the SlideMage app, open this folder as the project
and select the repository's `latex/` as the framework.

Verify committed text and expected widget pictures:

```sh
PYTHONPATH=src QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_design_handbook.py -q
```

The drift test compares generated tables as text. Image tests check presence,
not pixels; regenerate and visually review both themes when widgets change.
