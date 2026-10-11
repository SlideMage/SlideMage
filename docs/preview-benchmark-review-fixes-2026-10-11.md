# BIG CHANGE 2 preview benchmark — 11 October 2026

Frozen subset: **4 of 81 active manual calls**. Each includes a cold build, two actual visible text/graphic edits, and an unchanged request. The GUI image preparation is included; opening an external viewer and Qt painting are excluded.

| Configuration | Calls | Cold median, s | Edit mean, s | Edit median, s | Edit maximum, s | Edit total, s | Unchanged median, s | Failures | PDF mismatches |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| before: saved | 4 | 7.781 | 5.766 | 4.835 | 11.951 | 46.13 | 0.235 | 0 | 0 |
| after: saved | 4 | 7.880 | 5.729 | 4.787 | 11.959 | 45.83 | 0.138 | 0 | 0 |
| after: buffer | 4 | 7.675 | 5.748 | 4.790 | 12.240 | 45.98 | 0.132 | 0 | 0 |
| after: overlay | 4 | 7.635 | 5.767 | 4.733 | 12.276 | 46.14 | 0.134 | 0 | 0 |
| after: buffer-overlay | 4 | 7.720 | 5.647 | 4.702 | 11.780 | 45.17 | 0.134 | 0 | 0 |

| Configuration | Cold mean, s | Cold p95, s | Cold total, s | Unchanged mean, s | Unchanged p95, s | Unchanged total, s | Comparable PDFs | Not comparable |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| before: saved | 8.757 | 11.865 | 35.03 | 3.100 | 11.703 | 12.40 | 0 | 0 |
| after: saved | 8.797 | 11.758 | 35.19 | 3.026 | 11.697 | 12.11 | 16 | 0 |
| after: buffer | 8.751 | 12.063 | 35.00 | 3.098 | 11.998 | 12.39 | 16 | 0 |
| after: overlay | 8.706 | 11.971 | 34.83 | 3.090 | 11.959 | 12.36 | 16 | 0 |
| after: buffer-overlay | 8.737 | 11.940 | 34.95 | 3.083 | 11.936 | 12.33 | 16 | 0 |

Edit totals cover both edits per call. Cold means a new slide build cache, with the existing TeX font cache warm. Raw p95 is descriptive only; this subset is too small to establish a stable tail estimate. Configurations alternate order by call; two different edits are repeated workloads, not identical-edit repetitions. The manual has changed since the 77-call benchmark on 9 October; these totals cannot be compared directly to that older corpus.

Selected-overlay comparisons use the corresponding first baseline page. A call restricted to overlay 3 has no overlay-1 reference and is marked not comparable. Full-slide PDF identity is to the standalone-preview baseline, not a whole-deck build.

Raw timings, per-rule traces, corpus hashes, comparison results and failures are in the companion JSON.

Declared call indices: [54, 58, 70, 80]. Passing completeness gate: **True**.

Implementation, tools, dependencies, options and edit recipes are bound to immutable identities. Resumes reject changes; unfinished records restart with a new empty cache. The checked-in subset orchestrator alternates before/after order by call.

| Call | Before saved edit mean, s | After saved edit mean, s | Difference |
| --- | ---: | ---: | ---: |
| 54: 1sv-EN-Lists-and-Formulas | 3.654 | 3.599 | -1.5% |
| 58: 1c9-EN-Placing-Figures | 3.743 | 3.682 | -1.6% |
| 70: 1mu-EN-Slidestep-Demo | 3.728 | 3.696 | -0.9% |
| 80: 2v9-EN-Itemize-Spacing-Reference | 11.939 | 11.938 | -0.0% |

Evidence archive: `/home/juergen/github/SlideMage/.previews/benchmarks/preview-review-fixes-2026-10-11.tar.gz`; SHA-256 `13639c8c47f41f5f6c4cf7cc5e4eaa154e2ff91a1138662f40d9e7da35406632`. Completed 20 records in 473.6 s.
