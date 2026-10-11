# Typical preview editing gains — 11 October 2026

Comparison against the original fresh-job behavior, before build reuse. Each row averages two actual successive edits after an initial preview, using the same input in both saved-file paths. The bullet measurement is the earlier 44.3-second probe; the three added examples are measured sequentially in this run, alternating original/optimized order by case.

| Typical action | Original fresh job, s | Optimized preview, s | Seconds saved | Speedup | Less time |
| --- | ---: | ---: | ---: | ---: | ---: |
| Edit one bullet | 7.645 | 2.387 | 5.258 | 3.20× | 68.8% |
| Change the slide title | 7.352 | 4.624 | 2.728 | 1.59× | 37.1% |
| Edit a formula | 7.433 | 2.376 | 5.056 | 3.13× | 68.0% |
| Resize a figure | 7.352 | 2.429 | 4.923 | 3.03× | 67.0% |

The title test leaves body content unchanged. The formula test changes only the denominator; the figure test changes only image height; their titles remain unchanged. The main saving comes from retaining latexmk auxiliary state and resolved bibliography data. Required passes are still chosen by latexmk; no pass cap or draft output is used.

These timings include backend compilation, GUI image preparation and permitted snapshot writes, with the TeX font cache warm. Lint, the automatic-save debounce and Qt painting are excluded. Original and optimized output matched for every phase at 72 dpi and 1920-pixel display width. These are representative examples from two slides, not a corpus-wide average or a universal speed guarantee. Initial previews still take about 7–8 seconds; the known spacing fallback case remains slower.

This baseline is the original fresh-build behavior. The separate BIG CHANGE 2 comparison starts from an already cached implementation and measures its additional effect.
