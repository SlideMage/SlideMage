# BIG CHANGE 2 preview benchmark — 11 October 2026

Frozen corpus: **81 active manual calls**. Each includes a cold build, two actual visible text/graphic edits, and an unchanged request. The GUI image preparation is included; opening an external viewer and Qt painting are excluded.

| Configuration | Calls | Cold median, s | Edit mean, s | Edit median, s | Edit p95, s | Edit total, s | Unchanged median, s | Failures | PDF mismatches |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| before: saved | 81 | 7.747 | 4.907 | 4.866 | 5.461 | 795.00 | 0.234 | 0 | 0 |
| after: saved | 81 | 7.854 | 5.255 | 4.887 | 7.488 | 851.30 | 0.138 | 0 | 0 |
| after: buffer | 81 | 7.783 | 5.257 | 4.889 | 7.489 | 851.68 | 0.137 | 0 | 0 |
| after: overlay | 81 | 7.797 | 5.234 | 4.869 | 7.521 | 847.94 | 0.136 | 0 | 0 |
| after: buffer-overlay | 81 | 7.777 | 5.243 | 4.866 | 7.584 | 849.38 | 0.137 | 0 | 0 |

| Configuration | Cold mean, s | Cold p95, s | Cold total, s | Unchanged mean, s | Unchanged p95, s | Unchanged total, s | Comparable PDFs | Not comparable |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| before: saved | 7.906 | 8.617 | 640.43 | 0.398 | 0.395 | 32.25 | 0 | 0 |
| after: saved | 8.536 | 12.159 | 691.40 | 0.293 | 0.217 | 23.72 | 324 | 0 |
| after: buffer | 8.499 | 11.994 | 688.44 | 0.301 | 0.217 | 24.34 | 324 | 0 |
| after: overlay | 8.477 | 11.893 | 686.67 | 0.297 | 0.215 | 24.09 | 320 | 4 |
| after: buffer-overlay | 8.476 | 12.128 | 686.52 | 0.297 | 0.217 | 24.05 | 320 | 4 |

Edit totals cover both edits per call. Cold means a new slide build cache, with the existing TeX font cache warm. p95 uses the nearest-rank definition. Configurations alternate order by call; two different edits are repeated workloads, not identical-edit repetitions. The manual has changed since the 77-call benchmark on 9 October; these totals cannot be compared directly to that older corpus.

Selected-overlay comparisons use the corresponding first baseline page. A call restricted to overlay 3 has no overlay-1 reference and is marked not comparable. Full-slide PDF identity is to the standalone-preview baseline, not a whole-deck build.

Raw timings, per-rule traces, corpus hashes, comparison results, failures and follow-up controls are in the companion JSON.

The before-change baseline already reuses latexmk state; it includes canonical snapshots plus a second GUI raster. After-change scopes are saved files (1), complete buffers (1+3), saved-file overlay 1 (1+4), and buffer overlay 1 (1+3+4), all using deferred image preparation/publication. The older fresh-job benchmark is in the 9 October report and uses a different corpus.

## Results and choice

The lowest measured real-edit mean for complete slides is **saved** (5.255 s). For a selected overlay it is **overlay** (5.234 s). These scopes must be compared separately. Saved-file previews continue compiling the saved file; editor previews use build reuse plus the complete buffer (1+3), adding the explicit overlay selector when requested (1+3+4). Small differences between saved and buffer paths do not justify changing what a render means. For like-for-like comparisons, the buffer matrix carries the owning call’s SMSlideSteps restriction; an explicit overlay overrides it. The GUI can still render the whole buffer with all steps.

| After configuration | Cold mean reduction vs before | Edit mean reduction vs before | Unchanged median reduction vs before |
| --- | ---: | ---: | ---: |
| saved | -8.0% | -7.1% | 41.1% |
| buffer | -7.5% | -7.1% | 41.4% |
| overlay | -7.2% | -6.7% | 41.7% |
| buffer-overlay | -7.2% | -6.8% | 41.5% |

The queue improvement is separate from these single-request timings: one active GUI compile and one latest pending request prevent intermediate requests from compiling and obsolete results from publishing. No overlapping TeX jobs were used in the matrix. The footer clock is frozen at 2026-10-11 12:00, including its hidden layout annotation; a live timestamp changing minute is a changed input and can require another TeX build. The accepted GUI publication path is tested, but the benchmark uses backend image preparation and canonical snapshot publication without Qt paint timing.

## Timing variation and follow-up controls

The full matrix has **higher edit means after the change**; the table and totals above retain every slow successful request. Around calls 50–62, observed TeX passes took roughly 3.3 s rather than 2.1–2.2 s, with the same pass counts. Later calls returned to the shorter intervals. PNG and dependency-export times also rose during this interval.

To check whether this was a repeatable implementation regression, rerun four early/affected/late calls with before and after adjacent, alternating their order. Use a fresh project copy and fresh per-call caches, the same visible edits and identical-output checks. These are follow-up diagnostics; they do not replace the 81-call matrix.

| Call | Before edit mean, s | After edit mean, s |
| --- | ---: | ---: |
| 10: 1nk-EN-Installing-SlideMage | 4.695 | 4.716 |
| 55: 1w4-EN-Numbered-and-Lettered-Lists | 4.839 | 4.764 |
| 57: 1wa-EN-Columns-and-Tables | 5.004 | 4.911 |
| 70: 1mu-EN-Slidestep-Demo | 4.892 | 4.880 |
| Mean of 8 edits per implementation | 4.857 | 4.818 |

All 16 after-change control PDFs matched their corresponding references. The large slowdowns did not recur. Temporary environment variation is the most likely explanation, but CPU contention or frequency was not measured. **Real-edit speed remains essentially unchanged in these controls.** The reliable gain in the main run is the unchanged-preview path; the GUI queue and stale-result protection address responsiveness and correctness.

The measured full-slide leader is 1 (saved/cache) and the selected-overlay leader is 1+4. Their leads over buffer modes are only 2 ms and 9 ms per edit respectively, so they do not establish a repeatable advantage. Choose the fastest compatible path: 1 for saved files, 1+3 for current buffers, add 4 for an explicitly selected overlay, and use 1+2 for isolated elements. These are the production defaults for each input/scope.

## Where the time goes

Median observed stages for saved-file previews. Stages overlap; do not sum them. TeX rule counts and all individual intervals are in the JSON.

| Stage | Initial build, s | Real edit, s | Unchanged, s |
| --- | ---: | ---: | ---: |
| prepare | 0.0000 | 0.0000 | 0.0000 |
| cache_configuration | 0.0006 | 0.0006 | 0.0006 |
| lock_wait | 0.0000 | 0.0000 | 0.0000 |
| prune | 0.0007 | 0.0008 | 0.0007 |
| wrapper_write | 0.0000 | 0.0000 | 0.0000 |
| latexmk | 7.7535 | 4.7893 | 0.1189 |
| pdf_copy | 0.0002 | 0.0002 | 0.0002 |
| dependencies | 0.0151 | 0.0151 | 0.0149 |
| png | 0.0634 | 0.0635 | 0.0001 |
| snapshot_write | 0.0008 | 0.0007 | 0.0004 |

Real edits remain dominated by TeX passes. PNG caching helps most on unchanged requests. The spacing-reference slide retains a fresh-state fallback because its auxiliary layout state can oscillate; it is included in every total.

| Slowest saved-file edit call in the full run | Mean of its two edits, s |
| --- | ---: |
| 80: 2v9-EN-Itemize-Spacing-Reference | 11.995 |
| 57: 1wa-EN-Columns-and-Tables | 7.671 |
| 60: 1u5-EN-Color-and-Emphasis | 7.616 |
| 59: 1nz-EN-Footnotes-Sources-Citations | 7.596 |
| 58: 1c9-EN-Placing-Figures | 7.495 |

## Element previews: results 2 and 1+2

Separate manual selections: a formula, nested list, figure and table. These rows measure PDF generation only. The warm sample changes an unused macro to force a rebuild while preserving pixels; it is not a real word edit. Each selection has one fresh and one reused-build sample, so there is no p95 claim for this small set.

| Manual selection | Fresh (2), s | Reused state (1+2), s | Pixels at 144 dpi |
| --- | ---: | ---: | --- |
| formula | 7.493 | 2.322 | Match |
| list | 7.642 | 2.415 | Match |
| figure | 8.222 | 2.643 | Match |
| table | 7.542 | 2.398 | Match |
| Mean | 7.725 | 2.445 | 4/4 match |

Use 1+2 for isolated elements. Frame-region and element scopes are mutually exclusive; overlay filtering has no meaning for these isolated fragments.

## Preamble-format gate

Both format-dump probes failed before restore could run. The full manual took 1.901 s to fail; the Beamer-class-only probe took 0.799 s. Both reported `lua-uni-stage-tables.lua:141: attempt to perform arithmetic on a string value (local 'key')`. No `.fmt` cache is enabled. Result 1 uses latexmk state reuse; there is no experimental component renderer or blanket TikZ externalization.

## Correctness and reproducibility

- 405 configuration/call records and 1620 preview requests; no failures.
- 1288 comparable after-change PDFs matched dimensions and raster pixels; 8 overlay requests lack a matching baseline overlay page.
- The frozen full-slide corpus has 93 pages across 81 calls and 78 distinct slide/version identities. Each configuration includes 156 title edits, two quote edits, two body edits and two graphic-annotation edits. The four original hidden-footer cases were remeasured with visible changes and their old samples excluded.
- 1,461 automated tests passed, 6 skipped. Live TeX checks passed for a word edit, failure and recovery, two timestamps, two included-file states, two bibliography states, and rejection of overlay selection on an auto-breaking frame. Cached preview builds generated no SyncTeX files.
- GUI tests cover first/latest requests, debounce, event-loop responsiveness, obsolete errors and results, buffer/source/context invalidation, bounded pixmaps, and image-process restart. Native Windows frozen binaries were not built on this Linux host; frozen dispatch and missing-standard-stream handling have automated coverage.
- Python 3.14.5, PyMuPDF 1.28.2, PySide6 6.12.0, LuaHBTeX 1.22.0 (TeX Live 2025/Debian), latexmk 4.87 and Biber 2.21. Before and after used matching Python/PDF-library versions and the same warm TeX font cache.
- Corpus revision `1b3a2aa793863d7bef9de8615efd74541a1c7bed` plus the already edited working manual, frozen before implementation. Project and backend source hashes are recorded in the JSON. Later GUI status/LRU changes and Windows pipe restoration do not alter the timed Linux backend path.
- Source files were restored and verified against their initial hashes. The active example project was not used for timed edits. Raw PDFs, full logs, both source snapshots and probe diagnostics remain under `/tmp/slidemage-big-change-2`.
- One initial build, two different edit workloads and one unchanged request were measured per call/configuration. This establishes observed latency for this corpus, not a universal speedup or identical-edit repeatability.

See [the raw data](preview-benchmark-2026-10-11.json), [implementation details](BIG_CHANGE_2_IMPLEMENTATION.md) and [benchmark commands](../tools/preview_benchmark/README.md).
