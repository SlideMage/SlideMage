# Preview rendering optimization validation — 18 October 2026

The six implementation steps are complete. Rendering now groups equivalent
course views before compilation, shares matching in-flight work, preserves
per-view PDF provenance, and uses one whole-slide image-selection policy for
thumbnails and the pane. Saved and identical buffer requests execute the same
captured-text wrapper and share their request identity. Presenter, region,
element, overlay and transcript behavior remain distinct.

Deck refresh resolves actual occurrences, pinned versions, translations, reveal
selection and deck settings. It supports selected/all-view scope, reports partial
failures, and refreshes the exact cache used by both surfaces. The batched version
notification refreshes rows once and obeys the existing live-render setting.
Audited pinned calls can retain their result after unrelated new frozen siblings;
configuration, dependency content, search shadows and classifier-contract changes
still invalidate it. Unknown TeX retains conservative invalidation.

Compare Rendered uses validated 144 dpi reveal images where its 130 dpi minimum
is met. Additional resolutions and page ranges use `preview_pages`, shared with
PDF inspection tools. Its cache keys include PDF content and renderer version;
corruption and PDF mutation are checked, and storage is bounded independently
of the render cache.

## Automated checks

- Integrated preview/build/cache/dependency/grouping/request/selection/raster,
  deck refresh, MCP/tool, comparison, pane/list/version GUI, controller and module
  import checks: **693 passed** (63.70 s).
- After binding pinned-resolution evidence to the classifier contract revision:
  **54 focused cache/group/thumbnail/deck checks passed** (1.54 s).
- Focused Ruff checks and changed-file whitespace checks passed.

The existing chat composer's 640-pixel layout timeout is outside this plan and
was observed separately in the preceding Step 5 run. This is a focused integration
result, not a claim that the entire repository suite passes.

## Real LuaLaTeX checks

The final opt-in LuaLaTeX gate passed (**1 passed in 146.49 s**). An initial
probe used a new font-cache directory; the final gate used the now-warm font
cache, with no other tests, builds or compilers running concurrently. It covers full
ordered reveal sequences and dimensions, footers, default differing labels,
included view rules, macro overrides, numbering, hidden calls, source/image/
framework edits, pinned files, translation, restart reuse, and independent saved-
file versus captured-text reference renders. One/two/three groups are checked
against independently forced exact-view references; matching buffer requests
then perform zero compilation and raster work.

| Phase | Seconds | Compile jobs | LuaLaTeX passes | Display raster batches | Sequence raster batches | Cache hits |
|---|---:|---:|---:|---:|---:|---:|
| Cold independent exact-view references, including font initialization | 38.236 | 3 | 6 | 3 | 3 | 0 |
| Equivalent group, cold preview cache / warm fonts | 6.215 | 1 | 3 | 1 | 1 | 2 |
| Two groups, cold preview cache / warm fonts | 5.932 | 2 | 4 | 2 | 2 | 1 |
| Three groups, cold preview cache / warm fonts | 7.467 | 3 | 5 | 3 | 3 | 0 |
| Warm exact-view requests, initial recorder dependencies | 2.678 | 0 | 0 | 0 | 0 | 3 |
| Final warm exact-view requests | 0.222 | 0 | 0 | 0 | 0 | 3 |
| Final service restart | 0.228 | 0 | 0 | 0 | 0 | 3 |
| Warm after source/framework edits | 0.221 | 0 | 0 | 0 | 0 | 3 |

These are descriptive sequential runs. The group/reference jobs differ in font
and reusable-build state, so the times do not establish a controlled speedup
ratio. Compile avoidance is established by actual job counts. A job may require
multiple LuaLaTeX passes. Reference raster checks outside timed requests are not
included in production raster counts. Group rows report actual production jobs, observed LuaLaTeX passes and raster
batches from the final gate.

The initial recorder retained **3,814 dependencies, about 1.01 GB**, dominated by
font discovery. The largest were Noto CJK font collections (19–27 MB each), emoji
fonts, the distribution's LuaLaTeX format and its font map. These legitimate
inputs were retained. Three initial warm requests read about 3.02 GB of recorder
dependencies and spent 2.599 s validating caches. Later warm requests validated
about 94 MB in 0.149 s. This is why cache validation runs off-thread and retains
previous pixels while checking. Dependency-read counters and cache-validation
time are reported separately from compilation and rasterization.

The separate real deck probe produced nine occurrence/view results for two
current calls plus a pinned call. Cold refresh used nine jobs (26.405 s) in an
intentionally unclassified framework context; the repeated refresh had **nine
cache hits, zero jobs and zero raster batches** (0.476 s). Thumbnail and pane
artifact identities matched for every occurrence in all three views.

The final real pinned-version probe used the audited framework: one initial
render, then **zero jobs and zero raster batches** after a batch added a frozen
sibling and changed the current source. The current and pinned revisions retained
distinct identities. Unit checks additionally cover unknown TeX and new shadows.

## Qt display probe

A separate offscreen Qt run used 200 populated synthetic rows and one shared
32 MiB dependency. This measures cache validation and display responsiveness;
it is not a LaTeX correctness fixture or a production-deck latency guarantee.
No tests, builds or compilers ran concurrently with the timed probes.

| Measurement | Three validation passes |
|---|---:|
| End-to-end refresh | 440–444 ms |
| Background validation | 426–431 ms |
| GUI callback delay | 6.24–6.44 ms |
| Largest 10 ms timer gap | 10.7–18.0 ms |
| Row publication | 2.96–3.56 ms |
| Last viewport paint after dispatch | 438–442 ms |

Selection, scroll position and existing tree-item identities were preserved.
Each pass hashed the shared dependency once, with a separate stability reread;
there was no compilation, rasterization or full-size image decode for thumbnails.
These display measurements are separate from the compile-avoidance results.

## Packaged smoke

The final one-file Linux executable built successfully with PyInstaller 6.22.3.
Its `--help` entry point and two requests through its persistent `--preview-raster`
child passed. Packaged page PNGs and the complete reveal-sequence signature
matched the source renderer. The archive inventory includes `preview_pages`,
`preview_equivalence` and `deck_preview_refresh`.

Executable SHA-256:
`1aa24dc575d64669e10f46c01a7c1226b1078a0a364783dc150fd23f106bbbb2`.

Raw evidence is retained in
[preview-render-optimization-benchmark.json](preview-render-optimization-benchmark.json).

## Reproduction and scope

The commands are in [the benchmark README](../tools/preview_benchmark/README.md).
Run `views.py`, `deck.py`, `pins.py`, `display.py` and the packaged smoke sequentially.
The local evidence directory is `/tmp/slidemage-plan-validation/`; the executable
is built into its `package/dist/` subdirectory.

The selected-slides context-menu command, importing previews from a full-deck PDF,
and retaining a view across a changed source revision using newly proven semantic
equivalence remain the plan's deferred extensions. Previous pixel equality never
promotes an old source revision into a current render result.
