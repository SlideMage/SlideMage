# BIG CHANGE 2: fast preview implementation

Status: required review fixes implemented and verified, 2026-10-11 (SlideMage 6.1.1).

The [independent Astra review and commit plan](BIG_CHANGE_2_ASTRA_REVIEW.md) records the
required lifecycle, image-freshness, cleanup and benchmark-provenance fixes.
Their implementation and independent re-review are recorded in
[review fixes](BIG_CHANGE_2_REVIEW_FIXES.md). The optional TeX rerun/agenda work is deferred.
New benchmarks target about ten minutes on a fixed representative subset; the existing
81-call measurements remain historical evidence.

Implements the preview work in
[UI extensions and big fixes](UI_EXTENSIONS_AND_FIXES_PLAN.md#big-change-2-make-slide-previews-fast).
The 9 October measurements remain the historical starting point; the current manual is a different
corpus. All comparisons for this implementation use one frozen copy of it.

## Scope and decisions

Use the existing LuaLaTeX engine, fonts, theme and latexmk convergence logic. Ordinary saved-file
renders compile the saved file; buffer renders compile the requested buffer. All overlays remain
available by default, with region, element and specific-overlay rendering as explicit scopes.
Each change must preserve the corresponding standalone PDF output. The renderer retains fresh
builds as the reference path and as the fallback for unconverged auxiliary state.

The implementation addresses latency both in the backend and between a request and publication.
It keeps one active GUI job and the latest pending job, shares prepared PNGs between the display
and snapshots, and tracks the inputs that should invalidate a reusable build. The research's
component-level rendering and background/box caches are outside this implementation.

## 1. Profile the complete preview path

Files: `preview_metrics.py`, `preview_build.py`, `slide_preview.py`, `preview_cli.py`,
`ui/workspace/preview_view.py`, `tools/preview_benchmark/compare.py` and `summarize.py`.

- A context-local `PreviewMetrics` collector follows one call. It records preparation, cached-build
  configuration, wrapper writes, latexmk, PDF copying, dependency export, PNG generation and snapshot
  writes. Nested times overlap; they must not be added together as independent totals.
- Parse latexmk's own rule-start lines for LaTeX and bibliography passes. Stop a LaTeX rule at its
  log-reading line; other rules end at the next rule or process completion. These are wall-clock
  intervals observed through stdout, including logging overhead, rather than engine CPU timings.
- GUI workers record their trace and the interval from the request to completion. Publication timing
  includes Qt image loading; actual compositor/paint completion and opening a PDF viewer are excluded.
- `preview_cli --profile` prints a JSON trace. Ordinary calls work with no active collector.
- Preserve per-call PDF, full log, JSON timings, call identity and input hashes. Separate new slide
  build caches, real edits, and unchanged requests. The TeX font cache stays warm during comparison.

Validation: stage nesting and rule parsing tests; benchmark traces from live TeX; report medians,
means, nearest-rank p95, total edit duration, failures and PDF comparison counts.

## 2. Accept the latest GUI request

File: `ui/workspace/preview_view.py`; timestamp changes signal through `workspace/state.py`.

The GUI has one active job and at most one pending request. An explicit render replaces the pending
request and starts immediately if idle. An automatic render after saving uses a 300 ms single-shot
Qt timer; repeated saves restart it. A request arriving during compilation replaces the pending
request and waits for the active compiler to finish. Running TeX is allowed to finish, keeping its
auxiliary state usable. Requests for superseded intermediate buffers never compile.

Each request captures its generation, target, preamble identity, source modification time, view,
language, timestamp option, full editor buffer when applicable, and request time. The worker captures
these values before starting and never reads a changing Qt setting. On completion the GUI checks
that the generation, context, source and buffer still match. Changing slide, preamble, view,
language or timestamp invalidates pending work. A saved source change or a newer buffer also blocks
publication of an older job.

| Event | Active job | Pending request | Publication |
| --- | --- | --- | --- |
| Explicit request while idle | Start worker | Empty | Wait for matching completion |
| Automatic save while idle | Empty during debounce | Latest saved request | After debounce and completion |
| Request while worker runs | Keep running | Replace with latest request | Old generation is discarded |
| Context changes | Keep running | Clear | Old context is discarded |
| Worker finishes with latest successful result | Clear, then start pending if ready | Consume when ready | Show PDF/PNG and publish allowed snapshots |
| Worker finishes obsolete or with obsolete error | Clear, then start pending if ready | Consume when ready | Discard temporary result |
| Latest worker fails | Clear | Retain newer request if any | Keep previous page and show failure |
| Pane is destroyed | Worker can finish | Clear | Discard result; no access to deleted Qt objects |

The last successful page stays visible during a rebuild. A failed edit is labelled as failed and
cannot replace the page with a stale successful PDF. Buffer previews report when they are older
than the current buffer; a 150 ms status debounce updates that notice after typing pauses, including
edits made while the buffer is already dirty. It does not start a TeX compile. Session pixmaps retain
the twelve most recently used results so rendering a long deck cannot accumulate every full-size page.
Accepted-image keys include the timestamp option; toggling it marks the previous image stale until
a matching result is available. Disk thumbnails are explicitly unverified. An independent lifetime
token receives actual Qt destruction and prevents completion from accessing deleted widgets.
Presenter requests open the PDF without generating display PNGs.

Validation: three requests compile only first and latest; current-target waiting status; bounded session
pixmaps and dirty-buffer age updates; stale success/error; source, buffer,
preamble and all context changes; timer cancellation; presenter behavior; real-worker Qt event-loop
responsiveness. No concurrent GUI TeX jobs are introduced.

## 3. Prepare images once, publish after acceptance

Files: `slide_snapshot.py`, `preview_raster.py`, `preview_raster_client.py`, `cli.py`,
`preview_target.py`, `slide_preview.py`, `preview_view.py`.

- Add `capture_snapshot=False` to the GUI's backend calls, including in-memory rendering. The worker
  prepares images without touching canonical snapshots. The GUI publishes only accepted results.
- `prepare_preview` produces the display image and, where allowed, full-size and thumbnail PNGs.
  A 16:9 full-slide display reuses the prepared full-size snapshot; other deck aspect ratios
  get a display image at their actual aspect ratio. Cropped element and
  selected-overlay displays retain their own page aspect ratio and do not publish full-slide PNGs.
- Rasterize in a persistent child process. MuPDF objects remain there; PDF/PNG bytes cross private
  pipes. This fixes a crash reproduced while a worker rasterized and the GUI thread ran garbage
  collection. [PyMuPDF documents that it does not support Python threading](https://pymupdf.readthedocs.io/en/latest/recipes-multiprocessing.html).
  Reuse the child after the first request, close it at shutdown, and restart it after errors/exits.
  A 15-second request deadline kills and reaps a stalled child, including blocked pipe writes; malformed
  response shape/base64/PNG payloads fail the whole request. The next request starts a new child.
  The frozen app dispatches `--preview-raster` before GUI setup, reusing its executable without a
  splash or another extraction; windowed builds restore their redirected pipe handles when standard
  stream objects are unavailable ([PyInstaller documents this Windows behavior](https://pyinstaller.org/en/stable/common-issues-and-pitfalls.html#sys-stdin-sys-stdout-and-sys-stderr-in-noconsole-windowed-applications-windows-only)); this follows [PyInstaller's worker environment](https://pyinstaller.org/en/stable/advanced-topics.html#environment-variables-used-by-frozen-applications).
- Cache PNGs by SHA-256 of PDF bytes and requested dimensions, with a limit of 16 entries and 32 MiB.
  File paths and mtimes alone are insufficient because a path can receive a different PDF. A lock
  serializes access to the byte cache and image-process requests. Missing/corrupt PDFs and PDFs with no pages cannot become successes.
- Preserve the canonical raster sizes and rendering method. Identical images can keep their bytes,
  but their freshness time is refreshed after an accepted render. Existing APIs continue capturing
  snapshots for non-GUI callers unless capture is disabled explicitly.
- Include the actual deck preamble hash in `PreviewTarget.key`; changing colors or footer content
  under the same template must invalidate a previous target.

Validation: exact raster dimensions and pixels, repeated PDF content avoids rerasterization, changing
PDF content in the same path invalidates it, superseded GUI jobs never publish canonical images, 4:3 displays keep their proportions, and a
crashed image process is recovered without a GUI crash.

## 4. Reuse build state with configuration and recorded dependencies

Files: `preview_build.py`, `slide_preview.py`, `compiler.py`, `housekeeping.py`, `deck_headers.py`.

- Version the cache key schema. Include root, slide, preamble, TeX/bibliography/font search environment,
  latexmk rc contents and resolved executable identity (path, file size and modification time).
  Changing tools, project/user/system configuration or relevant environment starts new state.
- Leave an unchanged wrapper untouched so latexmk can perform its own dependency check. Keep its
  required reference and bibliography passes. Do not replace that check with a source-only PDF hit.
- Disable SyncTeX generation for cached scratch previews: only the PDF is returned, so the private
  auxiliary SyncTeX file cannot serve the external viewer. Full-deck compiles keep their configuration.
- Preserve the existing interprocess build lock and error-log checks. A failed edit must fail even
  if an old PDF exists. Retain the clean-current-PDF check and fresh-state fallback for a rerun limit.
- Reserve cache and wrapper paths before their first mutation. Cleanup checks and deletion share
  the reservation lock; a persistent project maintenance lock also protects active CLI/other-process
  previews. Housekeeping and pruning skip cleanup while another preview owns that lock. The lock
  lives outside removable `.build` entries. POSIX allows concurrent preview readers; the Windows
  byte-lock primitive serializes project preview builds. A recently created wrapper whose cache belongs to another build
  root is kept; absence of a cache under this particular root is insufficient grounds to remove it.
- Exclude generated underscore-prefixed wrappers from deck-membership header scans. This prevents
  previews from adding temporary deck names to tracked slide headers during a concurrent rescan.

Validation: reuse across body edits, rejection of stale PDFs, broken-edit recovery, configuration
and toolchain invalidation, pruning, and housekeeping that starts after a count was displayed.
Header tests use an isolated project and confirm that real deck names remain.

## 5. Watch recorded dependencies

Files: `preview_build.py`, `slide_preview.py`, `preview_cli.py`.

Export an `.inputs.json` beside each returned temporary PDF. Gather inputs from TeX's `.fls` recorder
and latexmk's database, including bibliography files. Resolve relative paths using the recorder's
working directory, keep names containing spaces, and exclude generated cache files and wrappers.
Deduplicate recorder entries and normalize paths without repeated filesystem walks; profiling
identified those walks as about 70 ms of avoidable overhead on an unchanged preview.

The CLI watches source, owning deck, project rc files and discovered inputs. A change to a graphic,
bibliography or included preamble triggers a render even when the selected source is unchanged.
Reread the owning deck preamble on each render. Keep missing/deleted recorded paths watched so
recreation triggers a retry. Compare pre-render stamps for inputs already watched: a change during
compilation must trigger the next iteration rather than be swallowed by a post-render snapshot.

Validation: dependency extraction, missing-file recreation and a watched graphic change with an
unchanged source. This uses recorded successful-build dependencies; a file never recorded by a
failed first build may still require a source edit or restarting watch to retry.

## 6. Gate precompiled preambles and further graphics caching

File: `tools/preview_benchmark/probe_format.py` and its retained diagnostic output.

Recheck the full manual and Beamer-class-only `mylatexformat` probes on the installed LuaHBTeX.
A usable format requires both dump and restore, matching fonts/theme, correctly tracked preamble
inputs, and identical PDFs across real edits. Enable it only after those checks pass. If the
installed engine continues failing in its Lua font-loading tables, keep latexmk reuse and document
the diagnostic; do not patch the TeX installation or change the engine to make a format appear usable.

Use measured profiles to decide whether independent expensive graphics need extra caching. The
manual already includes pre-rendered graphics, and theme TikZ depends on remembered page positions.
Retain ordinary compilation for those theme components unless an independent, equivalent output
can be demonstrated. No blanket externalization or additional shell-escape requirement is added.

## 7. Benchmark compatible preview combinations on a fixed subset

The completed 81-call run remains historical evidence. New review gates use only calls
54, 58, 70 and 80: 20 records / 80 requests with a ten-minute budget checked between requests.
The checked-in `run_subset.py` freezes implementations, project, framework and tools; alternates
baseline/candidate order; and generates the summary and checksummed evidence archive.
Its immutable manifest includes normalized source hashes, checkout/dirty-patch identity, options,
edit version, tool versions, dependency hashes, selected identities and ordering seed. Incompatible
resumes reject; interrupted cold attempts start with fresh unique caches. Work on a `/tmp` project copy and restore each source after measuring it. Never edit the
user's active manual slides to benchmark a change.

Before modification, measure the existing cached saved-file path including canonical snapshot
capture and its second GUI PNG generation. After modification, measure saved files, complete
buffers, saved-file overlay 1 and complete-buffer overlay 1 using deferred image publication.
These cover the compatible 1, 1+3, 1+4 and 1+3+4 scopes. The historical fresh-job and uncached
region/overlay rows remain available in the 9 October report; they must not be relabelled as timings
of the current corpus. Element mode (2 and 1+2) remains a separate output type.

For each subset call/configuration, use an isolated cache for one initial build, a visible title edit,
a second formula/body/graphic edit retaining that title, and an unchanged request. Each edit must
change pixels relative to the immediately preceding successful phase. Alternate configuration
order between calls. Compare every PDF page's dimensions and 72 dpi raster pixels with the matching
before-change PDF for that same edit. Compare the corresponding overlay page; mark absent reference
pages as not comparable. Keep full logs and failures; never drop slow successful calls from totals.

Publish the new report and raw JSON with separate cold, edit and unchanged columns, per-case
measurements, edit maxima and total edit time. The small subset cannot establish a stable p95
or repeatability. Missing, duplicate, failed, invisible or mismatching phases fail the gate. Select the fastest repeatable combination for each scope, without treating a selected
overlay or an isolated element as an equivalent complete slide. A small difference within run noise
is not evidence for changing the ordinary render's semantics.

## Completion and rollout

Run focused tests, the full app suite with the repository's dependencies, Ruff, and whitespace checks.
Run live TeX checks for a real edit, failure/recovery, timestamps, dependencies, references and the
unsupported auto-breaking-frame overlay case. Keep the ordinary full-slide and all-overlay defaults;
retain the existing fresh fallback. Record the implementation in the app's version history.

Review-fix completion requires every declared subset request to succeed, comparable PDFs to match,
stale publication to be blocked, and the GUI to remain responsive. Broad manual output evidence
comes from the existing full run; no new all-81 benchmark is required. First-build and real-edit gains must be stated separately.
Use the measurements to identify remaining slow cases and compatibility limits; no subsecond cold
compile target is assumed.

## Review-fix verification

The [review-fix record](BIG_CHANGE_2_REVIEW_FIXES.md) covers F1–F4, the raster
deadline and independent Astra re-review. Final suite: **1,491 passed, 6 skipped**.
The [new four-call subset](preview-benchmark-review-fixes-2026-10-11.md) completed
20 records / 80 requests in **473.6 seconds**, with all 40 edits visible and all
64 candidate PDFs matching. Twelve further PDFs matched at 1920-pixel display
width. No cold/edit transition exceeded the proposed 5% and 100 ms slowdown
threshold. All 1,993 archived file checksums passed, and the frozen summarizer
reproduced the report data. Saved unchanged median: **0.235 s → 0.138 s**;
saved edit mean: **5.766 s → 5.729 s**, with no substantial editing-gain claim.

## Historical full-run verification

- 1,461 automated tests passed, 6 skipped; Ruff and whitespace checks passed.
- All 81 manual calls across four combinations succeeded, with two visible edits each. All 810 edits across the baseline and four new combinations changed pixels.
- 1,288 comparable matrix PDFs matched; eight selected-overlay requests have no matching reference page.
- Eleven live TeX scenarios passed, including failed-edit recovery, timestamps, includes, bibliography updates and unsupported overlays; no cached SyncTeX artifacts were generated.
- Four real element selections matched at 144 dpi. Their reused-build mean is 2.445 s versus 7.725 s fresh; these warm samples force an unused macro change rather than an element edit.
- Both format probes failed before restore, so the existing latexmk fallback remains enabled.
- Frozen-process dispatch and missing-standard-stream recovery have automated coverage. A native Windows binary was not built on this Linux host.

The [final speed report](preview-benchmark-2026-10-11.md) and [raw data](preview-benchmark-2026-10-11.json) retain all full-run timings and the interleaved follow-up controls. Unchanged previews are faster; the controls do not establish a substantial real-edit gain. Use build reuse for each requested scope, retaining saved-file and buffer semantics.
