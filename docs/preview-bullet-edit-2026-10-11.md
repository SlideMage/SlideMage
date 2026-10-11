# One-bullet text edit — 11 October 2026

One frozen manual call (54, Lists and Formulas). Only the first bullet text changes; the title is unchanged. Original fresh jobs use the preserved pre-BIG-CHANGE-2 code with build reuse disabled and its original snapshot/GUI PNG path. The current path retains latexmk state and shares prepared images. Both use the same project, framework, fixed footer annotation, warm TeX font cache and interpreter. Original runs first, then optimized; the optimized image helper stays alive between requests.

| Request | Original fresh job, s | Optimized, s | Speedup | Time saved |
| --- | ---: | ---: | ---: | ---: |
| cold | 7.496 | 7.602 | 0.99× | -1.4% |
| edit-1 | 7.483 | 2.362 | 3.17× | 68.4% |
| edit-2 | 7.807 | 2.412 | 3.24× | 69.1% |
| unchanged | 7.505 | 0.131 | 57.43× | 98.3% |

Mean of the two real bullet edits: **7.645 s → 2.387 s**, **3.20×** or **68.8% less time**.

All four matching PDFs pass at 72 dpi and 1920-pixel display width; all four edited PDFs visibly differ from their preceding phase. Timings include GUI image preparation and allowed snapshot writes, exclude lint/debounce/Qt paint, and represent one slide and two different edits. They do not establish a universal editing speedup. Initial builds and difficult slides with fresh fallback remain slower.
