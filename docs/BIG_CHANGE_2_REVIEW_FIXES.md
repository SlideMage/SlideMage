# BIG CHANGE 2 review fixes

Implemented 2026-10-11 in SlideMage 6.1.1. This resolves the required findings in
[the independent Astra review](BIG_CHANGE_2_ASTRA_REVIEW.md); the optional TeX
rerun/agenda optimization remains deferred. Existing LuaLaTeX convergence,
fresh-state fallback and preview scopes are retained.

## Changes

| Finding | Implementation | Regression coverage |
| --- | --- | --- |
| F1: actual Qt destruction | A plain Python lifetime token receives `destroyed`, clears pending work and discards temporary results. Workers and queued completions check the token. Raster failures discard new PDFs while retaining the last successful page. | Real parent `DeferredDelete` during a blocked worker, queued completion before destruction, no second job/raster/publication, temporary-PDF cleanup |
| F2: accepted-image freshness | Timestamp setting is part of saved and buffer image identity. Previous images remain visible with a stale notice; switching back can reuse a matching accepted image. Disk thumbnails are unverified until rendered. | Saved/buffer toggle and switch-back; disk snapshot status; centre-panel integration |
| F3: cleanup races | Register reservations before cache/wrapper mutation. Check and delete under the common activity lock. A persistent project maintenance lock protects active previews in other processes, outside removable build entries. Housekeeping and pruning skip protected work. | Both race orderings with barriers; reservation before first mkdir; active child process protects cleanup and pruning |
| F4: benchmark evidence | Immutable source/tool/options/dependency identities; atomic records; new cold cache for interrupted attempts; declared-subset completeness; alternating before/after orchestration; final report from checked-in scripts; checksummed durable archive including frozen tools | Changed resume rejected; interrupted cold restarts; duplicate/missing/failed/invisible/mismatching records rejected; after-first comparison reconciliation; archive checksums |
| Raster helper deadline | A 15-second deadline kills and reaps an unresponsive child, including a blocked write. Validate response shape, count, base64 and PNG signature; restart on the next request. | Child never responds; child never reads a full pipe; restart succeeds; malformed responses fail |

The second benchmark edit must change pixels relative to edit 1, even though it
retains edit 1's title change. A regression test specifically covers an ineffective
second edit that differs from cold only because of the first title change.

## Verification

- Final pre-commit suite: **1,491 passed, 6 skipped in 35.38 seconds**, including
  all **14 benchmark tests** and the new successive-edit visibility checks.
- Focused Qt lifecycle, cleanup, timestamp and raster tests passed; Ruff fatal
  error checks and whitespace checks passed.
- Independent `gpt-6-astra` re-review: F1–F3 and raster containment resolved;
  F4 was accepted after the second-edit correction. **26 focused tests** and
  **3 final spot-check tests** passed. The reviewer made no changes and ran no TeX.
- Native Windows packaging remains a separate binary-release check; Linux tests
  exercise the frozen-process protocol and missing-standard-stream handling.

## Bounded timing gate

The new run uses only immutable calls **54, 58, 70 and 80** from the current
81-call manual: lists/formulas, graphic placement, steps 1,2 and the known spacing
fallback. It runs **20 records / 80 requests**: saved baseline plus saved,
buffer, overlay and buffer-overlay candidates, each with cold/title edit/body
or graphic edit/unchanged phases. The global budget is 600 seconds, checked
between requests while the active TeX process finishes cleanly.

The gate **passed in 473.6 seconds (7 minutes 54 seconds)**: all 80 requests
succeeded, all 40 edits changed pixels relative to their preceding phase, and
all 64 candidate PDFs matched their standalone saved baseline. There are no
excluded overlay references in this subset. No cold or individual edit
transition exceeded both 5% and 100 ms of slowdown against its saved baseline.

[The subset report](preview-benchmark-review-fixes-2026-10-11.md) and
[raw JSON](preview-benchmark-review-fixes-2026-10-11.json) retain every request,
per-case results, rule traces, ordering and machine observations.

| Combination | Cold median, s | Edit mean, s | Unchanged median, s |
| --- | ---: | ---: | ---: |
| Baseline: cached saved | 7.781 | 5.766 | 0.235 |
| 1: saved | 7.880 | 5.729 | 0.138 |
| 1+3: buffer | 7.675 | 5.748 | 0.132 |
| 1+4: saved overlay | 7.635 | 5.767 | 0.134 |
| 1+3+4: buffer overlay | 7.720 | 5.647 | 0.134 |

Unchanged saved requests improve by about **41%**. The saved real-edit mean
improves by only **0.6%**, which does not establish a repeatable editing gain.
The first three cases average about 3.6–3.7 seconds per edit; the spacing case
averages about 12 seconds and remains in the totals. Its unchanged request also
uses fresh fallback, so the median is not a promise for every slide. Title edits
normally run two TeX passes; the formula/body/graphic edits normally run one.
These transitions differ from the two title edits in the historical full run.

The fastest observed full-slide combination is **1 (saved)**; the fastest
selected-overlay combination is **1+3+4 (buffer overlay)**. The leaders vary
with this small workload and do not prove stable rankings. Preserve requested
semantics: saved source uses 1, editor buffer uses 1+3, and an explicitly
selected overlay uses 1+4 or 1+3+4 for its respective source. No overlay becomes
the ordinary full-slide default.

Additional display-resolution checks compared edit 2 of calls **58, 70 and 80**
in all four candidate scopes with the corresponding baseline page(s), at a
1920-pixel width: **12 PDFs / 14 pages matched exactly**. The evidence archive's
outer checksum and all **1,993 file checksums** were verified. Running the
archived summarizer reproduced every timing, identity, ordering and output-check
field in the delivered JSON; only the outer archive checksum and orchestration
wall duration are added by the orchestrator.

An initial sandbox attempt failed because LuaLaTeX reported no writable font
cache. It was stopped cleanly and retained in the separate local archive
`.previews/benchmarks/preview-review-fixes-2026-10-11-sandbox-failed.tar.gz`.
Those failures are excluded from the successful run above, which used the
existing warm font cache. The successful archive is
`.previews/benchmarks/preview-review-fixes-2026-10-11.tar.gz`.

All ten protected, pre-existing user files retained their original SHA-256
hashes. No example source was edited by the benchmark outside its scratch copy.

Reproduction and archive commands are documented in
[the benchmark README](../tools/preview_benchmark/README.md). The Oct 9 and earlier
Oct 11 full reports remain historical evidence. The earlier 3× macro-invalidation
speedup is not a measured visible-edit improvement.

## Follow-up: does an actual bullet edit benefit?

A separate one-slide probe compares the original fresh-job mode with the current
cached path, rather than the already cached baseline used above. Only the first
bullet of call 54 changes: `First level` → `Edited level` → `Final level`; the
frame title and other content stay fixed. Both paths include GUI image work.

The two real edits averaged **7.645 s fresh → 2.387 s cached**, **3.20×** or
**68.8% less time** (about 5.26 s saved per edit). Fresh jobs ran three LuaLaTeX
passes per edit; retained builds ran one. Initial builds were 7.496 s and 7.602 s.
All four phase PDFs matched at 72 dpi and 1920-pixel display width, and both edits
changed pixels in both paths. The run completed eight requests in 44.3 seconds.

[Report](preview-bullet-edit-2026-10-11.md), [raw data](preview-bullet-edit-2026-10-11.json)
and the checksummed local archive
`.previews/benchmarks/preview-bullet-edit-2026-10-11.tar.gz` retain the evidence.
This establishes a real text-edit benefit for this normal slide from build reuse
(result 1). It does not establish a further large editing gain from BIG CHANGE 2
beyond that existing reuse, nor a universal speedup for difficult fallback slides.

## Additional typical editing examples

The [user-edit comparison](preview-user-edits-2026-10-11.md) adds three measured
workflows to the original bullet example:

| Typical action | Original fresh job, s | Optimized preview, s | Seconds saved | Speedup | Less time |
| --- | ---: | ---: | ---: | ---: | ---: |
| Edit one bullet | 7.645 | 2.387 | 5.258 | 3.20× | 68.8% |
| Change the slide title | 7.352 | 4.624 | 2.728 | 1.59× | 37.1% |
| Edit a formula | 7.433 | 2.376 | 5.056 | 3.13× | 68.0% |
| Resize a figure | 7.352 | 2.429 | 4.923 | 3.03× | 67.0% |

All are complete saved-file previews after an initial build; every row compares
the exact same edit against original fresh jobs. The new run finished 24 requests
in **139.3 s**. All 12 new candidate PDFs matched at 72 dpi and display resolution;
all 12 new edits were visible. Title edits ran two LaTeX passes; formula and figure
edits ran one, versus three LaTeX passes plus Biber for original fresh jobs.
The updated benchmark report gates passed **14 focused tests**, including rejection
of invisible second edits, mismatched output and missing phases. No app code was
changed for these additional measurements.
