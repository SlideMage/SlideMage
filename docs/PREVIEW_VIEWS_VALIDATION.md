# Preview views validation — 15 October 2026

The opt-in real LuaLaTeX test passed (`1 passed in 78.15s`). It creates a
temporary project and a separate external framework copy, using the production
request, batch, dependency validation and raster paths. The fixture checks
complete reveal sequences, separate PDFs for equal views, the final display PNG,
default deck labels, deck-only content, conditional pauses, hidden views, frame
number resolution, pinned files and a linked German translation.

| Phase | Seconds | Compile jobs | LuaLaTeX passes | Display raster batches | Sequence raster batches | Cache hits |
|---|---:|---:|---:|---:|---:|---:|
| cold-identical-all | 10.907 | 3 | 6 | 3 | 3 | 0 |
| warm-all | 0.167 | 0 | 0 | 0 | 0 | 3 |
| restart-all | 0.169 | 0 | 0 | 0 | 0 | 3 |
| view-switch-cache-lookup | 0.167 | 0 | 0 | 0 | 0 | 3 |
| default-labels-all | 10.958 | 3 | 6 | 3 | 3 | 0 |
| conditional-reveals-all | 9.354 | 3 | 6 | 3 | 3 | 0 |
| image-edit-all | 8.192 | 3 | 5 | 3 | 3 | 0 |
| external-framework-edit-all | 12.146 | 3 | 6 | 3 | 3 | 0 |
| same-plus-source-edit-all | 8.568 | 3 | 5 | 3 | 3 | 0 |
| warm-after-edits-all | 0.186 | 0 | 0 | 0 | 0 | 3 |

Counts come from each production request's metrics. Compile jobs are view builds;
LuaLaTeX passes are observed latexmk rules, excluding optional format probes.
Independent correctness re-rasterizations outside the timed requests are not
counted. A compile job can require several LuaLaTeX passes. Each display raster batch
produces multiple requested sizes; sequence batches inspect every page at 144 dpi.
The cold identical batch shared eight image artifacts after rendering; PDFs
remained per-view. Warm requests and a fresh service avoided every LaTeX pass
and raster batch. Each tested image/framework/source edit caused three misses.
The source edit retained the same `1.0.0+` marker.

These are descriptive single-run backend timings with warm TeX font caches.
The full test suite and packaging overlapped parts of the run, so this is a
correctness/compile-avoidance gate, not a controlled speed comparison. View
switching measures validated cache lookup, excluding Qt event/paint latency.
Raw per-request metrics are in [preview-views-benchmark.json](preview-views-benchmark.json).

Reproduce with:

```sh
SLIDEMAGE_REAL_LATEX=1 TEXMFVAR=/tmp/slidemage-tex-cache \
  TEXMFCACHE=/tmp/slidemage-tex-cache \
  .venv/bin/pytest -q tests/test_preview_views_latex.py
```

The full integration run completed without the former mixed Qt/HTTP segfault:
**2637 passed, 10 skipped, 8 failed** in 332.81 seconds. Four failures were test
assumptions corrected during review: the new publication guard checks the buffer
again (the test now counts actual reloads), render output describes captured
source, comparison shortcuts need an active offscreen window, and task cleanup
must not close an already deleted context menu. The eight MCP revision cases
passed with valid PNG fixtures; the comparison and context-menu tests passed.

A six-case isolated rerun then had **2 passed, 4 failed**. Remaining failures are:

- `test_ai_switch_gui.py::test_ai_setup_closes_on_escape_and_on_a_click_outside_but_not_on_its_anchor`
- `test_chat_gui.py::test_a_six_line_input_and_send_row_fit_at_640px`
- `test_more_menu_gui.py::test_two_columns_with_their_sections_and_a_footer_in_order`
- `test_palette_gui.py::test_it_opens_on_every_visible_command_grouped_and_closes_on_escape`

The first two were recorded before this preview work. The latter two expect menu
contents/group order from before the existing uncommitted wizard command; its
registration and menu insertion explain the differences. That separate work was
preserved. The complete suite was not rerun after these test-only corrections;
targeted integrated preview checks cover the final implementation.

The Linux PyInstaller executable was built from this workspace with
`.venv/bin/python -m PyInstaller --noconfirm packaging/slidemage.spec`.
Smoke checks exercise its native `--help` and `--preview-raster` routes, including
three real view renders through the production MCP HTTP server and tool handler
using the packaged raster helper, in another disposable project with an external
framework copy. This checks MCP serialization with the packaged helper; it does
not run a Claude model/login or drive the packaged GUI's embedded terminal.
The executable remains in `dist/SlideMage`; no installed application was replaced.

Local evidence archive: `.previews/benchmarks/preview-views-2026-10-15.tar.gz`

SHA-256: `9e54de5aaa2e37876fdaf7a1720f2eb7997cfcb052cd4a68c59dbf2e025e61fb`.

Final focused validation: **224 integrated preview tests passed** in 46.02 seconds
(targets, requests, dependencies, completed cache, raster signatures, batches, pane
queue, chat tools and MCP). After the last palette-context fix, **64 queue/command
tests passed** in 11.09 seconds, including Source/Details actions resolving the
currently focused slide. The MCP revision tests passed **8/8** with actual PNG
fixtures. Ruff passed for all `src`, `tests` and `tools` files.

Final package rebuild after all review fixes completed in 123.14 seconds; its
`--help` check and three-image MCP/raster smoke both exited successfully.
Executable SHA-256: `7117ecd974566ea5f1cbe6a3bde0c1cc12b1940d10f0ef28c217b3deb1bce58b`.
