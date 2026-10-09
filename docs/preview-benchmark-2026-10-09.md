# Manual preview benchmark — 9 October 2026

Measured sequentially on an AMD Ryzen 7 PRO 6850U, with LuaHBTeX 1.22.0 (TeX Live 2025/Debian), latexmk 4.87, and Python 3.14.5. The existing TeX font cache was warm in every configuration.

The corpus contains 77 active slide calls (including repeated slidestep variants) from `example/decks/slidemage-manual.tex`. Baseline was collected before modifying the preview implementation. Every duration includes the preview API call, including PNG capture when that API generates a canonical snapshot; opening a PDF viewer is excluded.

| Configuration | Successful calls | Pages | Total seconds | Mean seconds | Median seconds | Speedup |
|---|---:|---:|---:|---:|---:|---:|
| Baseline (fresh job) | 77/77 | 89 | 576.33 | 7.485 | 7.360 | 1.00× |
| 1: reusable build state (fmt fallback) | 77/77 | 89 | 191.85 | 2.492 | 2.351 | 3.00× |
| 3: complete source region | 77/77 | 89 | 570.28 | 7.406 | 7.319 | 1.01× |
| 4: overlay 1 | 77/77 | 77 | 569.05 | 7.390 | 7.302 | 1.01× |
| 1 + 3 | 77/77 | 89 | 187.89 | 2.440 | 2.314 | 3.07× |
| 1 + 4 | 77/77 | 77 | 186.66 | 2.424 | 2.306 | 3.09× |
| 3 + 4 | 77/77 | 77 | 570.52 | 7.409 | 7.328 | 1.01× |
| 1 + 3 + 4 | 77/77 | 77 | 186.56 | 2.423 | 2.305 | 3.09× |

Fastest measured complete-slide configuration: **1+3**, **187.89 s** total. Fastest selected-overlay configuration: **1+3+4**, **186.56 s** total.

The default editor path combines reusable builds with in-memory source rendering and retains all overlays. Selecting a region and a specific overlay uses 1 + 3 + 4. Its roughly 0.1-second total advantage over 1 + 4 in this run is too small to establish a repeatable difference. First builds are not three times faster; the main gain is on subsequent rebuilds.

## Cold builds and unchanged requests

| Cached configuration | Initial builds, total s | Initial median s | Unchanged median s |
|---|---:|---:|---:|
| 1: reusable build state (fmt fallback) | 567.64 | 7.271 | 0.171 |
| 1 + 3 | 565.98 | 7.249 | 0.116 |
| 1 + 4 | 564.75 | 7.247 | 0.116 |
| 1 + 3 + 4 | 561.61 | 7.226 | 0.116 |

## Interpretation and limits

- **Result 1 is a fallback, not working `.fmt` caching.** Both the full manual preamble and a Beamer-class-only `mylatexformat` dump failed in `lua-uni-stage-tables.lua:141` (`attempt to perform arithmetic on a string value`). The implementation instead retains latexmk auxiliary state and dependencies. Manual PDF graphics already reuse pre-rendered assets; dynamic theme TikZ remains compiled normally.
- Cached rows measure an actual source change after a separately measured initial build. A harmless macro changes between runs to force compilation without changing the expected pixels. These are changed-input measurements, not actual word-edit measurements. Unchanged cache-hit timings are shown separately and are not used for speedup.
- The spacing-reference slide already reaches latexmk’s rerun limit in the baseline. Its cached configuration deliberately clears unconverged auxiliary state before subsequent requests, preserving the baseline output at the cost of a fresh build for this one case.
- Result 3 renders the complete source of each manual call as a region. The previous app already supported whole-buffer preview; explicit selection is the added feature. Region previews do not update the canonical full-slide PNG.
- Result 4 intentionally shows only overlay 1, so its output is smaller than a full preview. A requested overlay overrides a call’s existing slidestep filter. It remains opt-in rather than discarding overlays from the ordinary preview.
- Result 2 uses `preview.sty` for selected elements. Whole Beamer frames are rejected in element mode: it is not a drop-in full-slide renderer. Combining this mode with the mutually exclusive region mode or a frame-overlay selection has no defined meaning.
- PDF verification rasterizes every page at 72 dpi and compares pixels and page dimensions against the original standalone-preview path. For overlay 1, the corresponding first baseline page is used. The call restricted to overlay 3 has no overlay-1 reference and is marked not comparable. This does not establish equivalence to a full-deck build, whose navigation and cross-frame state can differ from standalone previews.
- The footer-annotation slide measures a timestamp even when it is hidden. Comparison runs freeze the timestamp to the baseline PDF’s minute and retain the normal timestamp-file loading behavior so its annotation positions remain comparable.
- A separate actual title edit changed “Lists and formulas” to “Lists and equations”: the initial preview took 7.345 s and the edited preview 4.492 s. A deliberately undefined command was rejected, and the repaired preview succeeded. Extra LaTeX passes make this real edit slower than the minimal-rebuild workload in the main table.
- Overlapping samples from an interrupted process were discarded and rerun sequentially. One pass per configuration is reported; differences of a few percent can be measurement noise.

## Rendering checks

| Configuration | Pixel matches | Not comparable | Mismatches |
|---|---:|---:|---:|
| 1: reusable build state (fmt fallback) | 77 | 0 | 0 |
| 3: complete source region | 77 | 0 | 0 |
| 4: overlay 1 | 76 | 1 | 0 |
| 1 + 3 | 77 | 0 | 0 |
| 1 + 4 | 76 | 1 | 0 |
| 3 + 4 | 76 | 1 | 0 |
| 1 + 3 + 4 | 76 | 1 | 0 |

## Element previews (result 2)

These four self-contained selections come from the manual: its Sharpe-ratio formula, nested list, correlation-matrix figure and Gotham table. They are not complete slides, so their timings are not part of the 77-call speedup ranking.

| Selection | 2: fresh element, s | 1 + 2: warm element, s |
|---|---:|---:|
| formula | 7.058 | 2.175 |
| list | 7.081 | 2.241 |
| figure | 7.854 | 2.475 |
| table | 7.004 | 2.234 |

## Validation

- Final diagnostic test run: **560 passed, 2 skipped**, exit status 0. An earlier run reported the same passing assertions but exited with status 139 during shutdown; the diagnostic rerun did not reproduce it. Its cause was not established.
- Ruff passed for all changed Python files and benchmark tools.
- Offscreen UI check verified all three preview scopes and disabled the overlay control for elements.
- Live TeX checks verified a real title edit, rejection of a broken edit, recovery after repair, visible timestamp refresh, and explicit rejection of overlay selection on auto-breaking frames.
- All four final element PDFs match between fresh and cached builds at 144 dpi. Formula, list, figure and table crops were visually reviewed; element padding preserves hanging list bullets.
