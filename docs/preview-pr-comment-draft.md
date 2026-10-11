BIG CHANGE 2 and the independent Astra review fixes are implemented in **v6.1.1**.

Typical editing actions now have direct comparisons against the **original fresh-job
preview behavior, before build reuse**. Each row averages two real edits after an
initial preview, using identical saved-file inputs and complete-slide output in
both paths:

| Typical action | Original fresh job, s | Optimized preview, s | Seconds saved | Speedup | Less time |
| --- | ---: | ---: | ---: | ---: | ---: |
| Edit one bullet | 7.645 | 2.387 | 5.258 | 3.20× | 68.8% |
| Change the slide title | 7.352 | 4.624 | 2.728 | 1.59× | 37.1% |
| Edit a formula | 7.433 | 2.376 | 5.056 | 3.13× | 68.0% |
| Resize a figure | 7.352 | 2.429 | 4.923 | 3.03× | 67.0% |

The title test changes only the heading. The formula test changes its denominator;
the figure test changes image height; their titles stay fixed. Fresh jobs run three
LaTeX passes plus Biber; retained builds need one pass for the tested bullet,
formula and figure edits, and two for title edits. This saves roughly **2.7–5.3
seconds per edit** in these examples.

Timings include compilation, GUI image preparation and canonical snapshot work,
with a warm TeX font cache. Lint, automatic-save debounce and Qt painting are
excluded. These are examples from two manual slides, rather than a corpus-wide
editing average. Initial previews still take about 7–8 seconds; difficult
fresh-fallback slides remain slower. Every output matched at 72 dpi and
1920-pixel display width.

The original plan also compared all 77 manual calls on 9 October:

| Result / combination | Mean per call | Total, 77 calls | Speedup vs original | Less time |
| --- | ---: | ---: | ---: | ---: |
| Original: fresh job | 7.485 s | 576.33 s | 1.00× | 0.0% |
| 1: reusable latexmk build state | 2.492 s | 191.85 s | 3.00× | 66.7% |
| 3: complete source region | 7.406 s | 570.28 s | 1.01× | 1.0% |
| 4: selected overlay 1 | 7.390 s | 569.05 s | 1.01× | 1.3% |
| 1+3 | 2.440 s | 187.89 s | 3.07× | 67.4% |
| 1+4 | 2.424 s | 186.66 s | 3.09× | 67.6% |
| 3+4 | 7.409 s | 570.52 s | 1.01× | 1.0% |
| 1+3+4 | 2.423 s | 186.56 s | 3.09× | 67.6% |

Cached rows in that historical table measure a warm rebuild forced by a harmless
macro change. The real-edit examples above separately demonstrate the benefit for
visible changes. The fastest measured complete-slide combination in the original
matrix was **1+3**; its selected-overlay leader was **1+3+4**, with a lead too small
to establish a repeatable ranking. Ordinary editor previews retain all overlays;
selecting one overlay remains explicit. Result 1 uses latexmk state reuse; the
`.fmt` probes failed on the tested installation.

The further BIG CHANGE 2 work improves request coalescing, stale-result protection,
shared image preparation, dependency handling and cleanup. The review fixes also
cover actual Qt teardown, timestamp freshness, cross-process cleanup protection,
raster timeout/recovery and reproducible evidence. Against an **already cached**
baseline, the latest saved unchanged-preview median improves from **0.235 s to
0.138 s (41%)**; additional real-edit compilation speed is essentially unchanged.

Validation: **1,491 tests passed, 6 skipped** in the final full suite, including
all **14 benchmark gate tests** after adding these examples. The four-slide review gate passed
80 requests in 7m 54s with zero failures/mismatches. The three new editing examples
added 24 requests in 2m 19s. Across all four editing examples, all 16 edited PDFs
visibly changed and all 16 candidate phase PDFs matched their original references.

Reports and raw data: `docs/preview-user-edits-2026-10-11.md`,
`docs/preview-benchmark-2026-10-09.md` and
`docs/preview-benchmark-review-fixes-2026-10-11.md`.
