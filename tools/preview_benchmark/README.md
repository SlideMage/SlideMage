# Preview benchmark

## Short BIG CHANGE 2 verification

Use the fixed four-call subset for new changes. It covers lists/formulas (54),
a figure (58), steps 1,2 (70) and the known spacing/fresh-fallback case (80).
It measures 20 records / 80 requests, with a default ten-minute wall budget.
Do not run other compilers or tests during timing.

Run from the repository root with the app dependencies and LuaLaTeX installed.
`--before-source` is a preserved `src/` tree from before BIG CHANGE 2, already
using cached latexmk builds; it is not the fresh-build Oct 9 baseline.

```sh
.venv/bin/python tools/preview_benchmark/run_subset.py \
  --before-source /tmp/frozen-before-src --after-source src \
  --project example --framework latex --output /tmp/bc2-subset \
  --report docs/preview-benchmark-subset.md \
  --archive .previews/benchmarks/bc2-subset.tar.gz --time-budget 600
```

The orchestrator freezes source trees, project, framework and benchmark tools.
It alternates before/after order by call and candidate order within the call.
The saved-file baseline includes canonical PNG capture and GUI rasterization;
the candidate prepares images with its persistent raster helper and publishes
accepted canonical snapshots. The scopes are saved (1), buffer (1+3), overlay
(1+4) and buffer-overlay (1+3+4). Overlays are a different requested output and
cannot replace full-slide defaults.

Each record starts with an empty slide build cache, makes one title edit, then
one body/formula/graphic edit retaining that title, and requests the last input
unchanged. Each edit must change pixels relative to its preceding phase. These
are different edit transitions, not repetitions of one timing experiment.
The TeX font cache remains warm; each child starts a raster helper on its first
image request. Timestamp text and its hidden layout annotation are fixed at
2026-10-11 12:00. Buffer wrappers preserve the call's step selection; explicit
overlay selection overrides it.

Every PDF is compared at 72 dpi to its matching saved baseline, or the matching
baseline page for an overlay. This proves standalone-preview equality for the
selected cases, not full-deck equivalence. Reports include per-case timings,
cold/edit/unchanged aggregates, observed latexmk rule intervals, ordering,
load/frequency observations, source/tool/dependency hashes and tool versions.
Small-sample maxima and descriptive aggregates do not establish repeatability.
GUI debounce, event delivery and paint latency are covered by separate tests,
not these backend timings.

Create `/tmp/bc2-subset/results/STOP` to stop between requests; the active TeX
process finishes cleanly. Budget expiry also stops at that boundary. An
incomplete run is reported as incomplete and exits unsuccessfully. Remove STOP
and rerun the same command to resume completed records. Changed sources,
project inputs, tools or options reject a resume; unfinished records restart
with a new empty cache. Use a new output directory for a changed experiment.

The checked-in orchestrator generates the final Markdown/JSON report and a
checksummed local archive containing PDFs, logs, records, frozen implementations,
benchmark tools and project/framework TeX/media inputs. Project settings are
omitted. `.previews/benchmarks/` is ignored by Git; preserve the archive with
release artifacts rather than relying on `/tmp`.

Rebuild the timing summary from an extracted archive without running TeX:

```sh
mkdir -p /tmp/bc2-evidence
tar -xzf .previews/benchmarks/bc2-subset.tar.gz -C /tmp/bc2-evidence
.venv/bin/python /tmp/bc2-evidence/tools/summarize.py \
  /tmp/bc2-evidence/results /tmp/bc2-evidence/recreated-report.md
```

The orchestrator adds the outer archive checksum and overall wall duration to
the report; the inner summary contains the timing evidence without that outer
checksum. Low-level `compare.py` supports `--subset-indices` for the immutable
selection and `--indices` for the calls executed by an individual invocation.
`summarize.py` requires exactly the declared records/phases and zero failed,
invisible or mismatching results for a passing report. `--allow-incomplete`
produces a progress report, never a passing gate.

## Historical all-corpus research tools

The Oct 9 fresh-build/macro-invalidation experiment used `run.py`, `matrix.py`,
`elements.py`, `probe_format.py` and `report.py`. Its 77-call report remains in
`docs/preview-benchmark-2026-10-09.md`. An unused macro forced recompilation;
that warm time is not a visible-edit measurement. The format dump probes failed
on the tested LuaLaTeX/fontspec setup, so no `.fmt` optimization is enabled.
Element mode (`preview.sty`, 2 or 1+2) measures cropped objects separately.

The Oct 11 all-corpus comparison used 81 calls and two visible edits. Its
original report and raw JSON remain historical evidence, including interleaved
follow-up controls and run-to-run TeX variation. Do not rerun either full matrix
as the gate for review fixes; use the four-call orchestrator above.

## One real bullet-edit comparison

`bullet_edit.py` compares the original fresh-job behavior with the current cached
saved-file path on only call 54. The title stays unchanged; the first bullet is
edited twice. Each implementation measures initial build, both visible edits and
one unchanged request. The original renderer uses the project's normal `.build`
directory to match its fixed latexmk auxiliary directory; every request creates a
fresh job. The candidate has its own retained cache. Both paths include their
corresponding GUI image/snapshot work and use the same frozen inputs and clock.

```sh
.venv/bin/python tools/preview_benchmark/bullet_edit.py \
  --before-source /tmp/frozen-before-src --after-source src \
  --project example --framework latex --output /tmp/bc2-bullet-edit \
  --report docs/preview-bullet-edit.md \
  --archive .previews/benchmarks/bc2-bullet-edit.tar.gz --time-budget 90
```

Use a new scratch directory for each experiment; this short probe does not resume.
The successful 11 October run took 44.3 seconds. Its two bullet edits averaged
7.645 s with original fresh jobs and 2.387 s with retained builds (3.20×, 68.8%
less time). All four phase comparisons matched at 72 dpi and 1920-pixel display
width. This is a one-slide proof for two text-only edits, separate from the full
macro-invalidation table and the comparison against an already cached baseline.

## Typical user-edit examples

`user_edits.py` adds title, formula and figure-height edits to the retained bullet
probe. Each case uses the same saved-file input for original fresh jobs and the
optimized full-slide preview, with two successive real edits. The two text/formula
cases use call 54, and the figure uses call 58. Original/optimized ordering alternates
by case. The shared default budget is three minutes; no full corpus is rerun.

```sh
.venv/bin/python tools/preview_benchmark/user_edits.py \
  --before-source /tmp/frozen-before-src --after-source src \
  --project example --framework latex --output /tmp/bc2-user-edits \
  --bullet-report docs/preview-bullet-edit-2026-10-11.json \
  --report docs/preview-user-edits.md \
  --archive-dir .previews/benchmarks/bc2-user-edits --time-budget 180
```

Each case retains its own frozen inputs, sources, logs, PDFs and checksum archive.
The aggregate JSON embeds all four case records. Regenerate the summary without TeX:

```sh
.venv/bin/python tools/preview_benchmark/user_edits.py --summarize-only \
  --output /tmp/bc2-user-edits --bullet-report docs/preview-bullet-edit-2026-10-11.json \
  --report /tmp/bc2-user-edits/recreated.md
```

The successful run added 24 requests in 139.3 seconds. These are typical saved-file
preview-generation examples, not measurements of keyboard-to-screen latency;
lint, automatic-save debounce and Qt painting remain outside the timings.

For the delivered 11 October comparison, the combined local archive also contains
all four case archives, aggregation inputs and the final summarizer. Its SHA-256
is recorded as `summary_artifact` in the report JSON. Recreate the published table
without TeX or the original `/tmp` directories:

```sh
mkdir -p /tmp/bc2-user-evidence
tar -xzf .previews/benchmarks/preview-user-edits-2026-10-11.tar.gz \
  -C /tmp/bc2-user-evidence
.venv/bin/python /tmp/bc2-user-evidence/tools/user_edits.py --summarize-only \
  --output /tmp/bc2-user-evidence/results \
  --bullet-report /tmp/bc2-user-evidence/results/bullet.json \
  --report /tmp/bc2-user-evidence/recreated.md
```

The aggregate report was recreated byte-for-byte from those archived tools and
inputs. Each nested measurement archive's checksum and every contained file
checksum were verified.

## View cache acceptance probe

`views.py --output /tmp/new-preview-views` creates a small project and a separate
external framework copy, then uses the production RenderService and batch API.
The output folder must be new. LuaLaTeX, latexmk and the project dependencies are
required. In restricted environments set `TEXMFVAR` and `TEXMFCACHE` to a writable
TeX cache directory. No model provider or Claude login is needed.

The probe asserts identical full reveal sequences with the deck label hidden,
differing default labels, deck-only content and conditional pauses, hidden views,
per-view numbering, pinned input and a linked translation. It compares final
pane-sized PNGs against the last PDF page. It records cold/warm/restarted all-view
batches, direct view cache lookups, image edits, external framework edits and
source edits retaining the same `+` version marker in `results.json`.

`compile_count` counts non-cached view jobs, `latex_passes` counts actual latexmk
LuaLaTeX rule passes (not optional format probes), `raster_count` counts display-image preparation batches and
`sequence_raster_count` counts full-sequence verification batches. Multiple image
sizes/pages can be produced by a raster batch. `cache_hits` and
`deduplicated_images` distinguish compile avoidance from image storage sharing.
Counts are from production request metrics; independent correctness raster checks
outside the timed requests are excluded. View-switch timings measure validated
backend lookups, excluding Qt painting.
Timings are descriptive single runs and vary with font caches and machine load.

The opt-in pytest gate is:

```sh
SLIDEMAGE_REAL_LATEX=1 .venv/bin/pytest -q tests/test_preview_views_latex.py
```

## Optimization completion probes

The real-engine probe additionally checks one/two/three pre-render groups against
independent per-view references, saved-file versus captured-text equality, and
zero-compile/zero-raster identical-buffer reuse. Per-request metrics include
`cache_validation` seconds, `dependency_bytes_read` and total `content_bytes_read`.
Start with a new `TEXMFVAR`/`TEXMFCACHE` directory to distinguish initial font
discovery from later warm requests; keep scanned font dependencies in the evidence.

Run these sequentially, without concurrent tests, compilers or builds:

```sh
TEXMFVAR=/tmp/preview-fonts TEXMFCACHE=/tmp/preview-fonts \
  .venv/bin/python tools/preview_benchmark/views.py --output /tmp/preview-latex
TEXMFVAR=/tmp/preview-fonts TEXMFCACHE=/tmp/preview-fonts \
  .venv/bin/python tools/preview_benchmark/deck.py \
  --project /tmp/preview-latex/project --framework /tmp/preview-latex/external-framework \
  --output /tmp/preview-deck
TEXMFVAR=/tmp/preview-fonts TEXMFCACHE=/tmp/preview-fonts \
  .venv/bin/python tools/preview_benchmark/pins.py \
  --project /tmp/preview-latex/grouped/project \
  --framework /tmp/preview-latex/grouped/external-framework --output /tmp/preview-pins
QT_QPA_PLATFORM=offscreen .venv/bin/python tools/preview_benchmark/display.py \
  --output /tmp/preview-display --rows 200
PYINSTALLER_CONFIG_DIR=/tmp/preview-package-config .venv/bin/pyinstaller \
  --noconfirm --distpath /tmp/preview-package/dist --workpath /tmp/preview-package/build \
  packaging/slidemage.spec
.venv/bin/python tools/preview_benchmark/package_smoke.py \
  --binary /tmp/preview-package/dist/SlideMage --output /tmp/preview-package-smoke
```

The display probe seeds synthetic cache artifacts and a shared 32 MiB dependency.
It measures background validation, Qt timer/event delay and viewport paints,
checks item/selection/scroll preservation, and performs no TeX or raster work.
It is a display workload, not a correctness reference or a desktop performance
claim. The packaged smoke checks the real one-file entry point and two requests
to its persistent raster child, comparing PNGs and the full reveal signature.
The delivery results are in `docs/PREVIEW_RENDER_OPTIMIZATION_VALIDATION.md`.
