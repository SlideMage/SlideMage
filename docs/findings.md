# Preview rendering: code review findings and plans

21 October 2026, `develop` @ 707b350 (v8.40.1). Review of the single-slide preview path (Preview pane, render
service, verified cache, latexmk build, raster) and the background/deck refresh paths, with measurements.
Earlier work this builds on: `docs/PREVIEW_RENDER_OPTIMIZATION_PLAN.md` (view sharing, done),
`docs/plans/preview-passes-and-direct-lualatex.md` (third pass fixed in v8.37.0; option 2b planned),
`docs/plans/parallel-previews-handoff.md` (parallel renders, done).

## How this was measured

- Machine: Linux, TeX Live 2024, NVMe SSD, warm page cache, nothing else running. **Windows/MiKTeX numbers will
  differ** (slower file reads with virus scanning, slower process start); see step 0 of the plans.
- Harness: a script that drives `preview_requests.RenderService.request()` exactly like the Preview pane, on a
  scratch copy of `example/` (deck `slidemage-manual-copy`, slide `1b2-EN-Managing-a-Slide`, Instructor), with call
  counters and timers wrapped around the suspected functions. Four renders: cold (forced), unchanged (cache hit),
  edit, edit again. The script is in the session scratchpad; plan 0 turns it into `tools/preview_bench.py`.
- TeX phases were timed with `os.gettimeofday()`/`os.clock()` marks inside LuaLaTeX, using an instrumented copy of
  the precompiled format.

### Baseline (one slide, Linux)

| render | total | latexmk (rules inside) | SlideMage around it |
|---|---|---|---|
| cold, forced | 6.3 s | 3.55 s (lualatex 1.4, biber 0.5, lualatex 1.4) + format build 2.3 s (once per preamble) | 0.45 s |
| unchanged | 0.05 s | – | 0.05 s (validation only) |
| **edit** | **2.44 s** | 2.10 s (**biber 0.53**, lualatex 1.42) | 0.34 s |

Per edit render, SlideMage's own share was: `PreviewCache.store` 133 ms (most of it hashing), raster of the
display images 98 ms, format freshness check 36 ms, `begin()` evidence ×3 35 ms, `publish_preview` 26 ms, reveal
sequence raster 22 ms, thumbnail 18 ms; 1152 file reads+SHA-256 (≈ 3 × the 384 inputs), `configuration_state` ×4,
`search_state` ×4.

### Where one LuaLaTeX pass goes (precompiled preamble, edit render)

| point in the run | CPU s |
|---|---|
| format loaded, LuaLaTeX/luaotfload start-up, kernel `\everyjob` | 0.83 |
| `\SMLuaOnce` replay | +0.00 |
| OpenType font replay (`CAPTURE_LUA`) | +0.16 |
| `\begin{document}` (aux/nav/toc/bbl reads, hooks) | +0.10 |
| **the slide itself** | **≈ 0.13** |

An empty document with the format takes 1.25 s wall; the slide adds 0.13 s. Plain `lualatex` on a one-line article
takes 0.43 s. **Each LuaLaTeX pass costs ~1.1 s before any slide content**, so the number of passes and processes
is what matters, not the slide.

## Findings

Severity: **High** = measurable on every interactive render or grows without bound; **Medium** = clear waste, smaller
or path-specific; **Low** = tidy-up.

| # | Finding | Severity | Measured / estimated gain | Effort |
|---|---|---|---|---|
| F1 | Every render-service miss forces latexmk with `-g`: biber and a full pass run on every edit | **High** | edit 2.44 → 1.90 s (**−22%**), measured | S |
| F2 | `PreviewCache.prune()` runs after every render and parses every manifest in the cache | **High** | 191 ms at 167 generations (26 MB JSON); ~0.5 s near the 512 MB cap; on the critical path | S |
| F3 | Content hashes of TeX-distribution files and tool binaries, recomputed 3–7× per render and every 5 s for the shown slide | **High** (Windows), Medium (Linux) | ~33 MB hashed per validation, 98% distribution files; ~120–150 ms per edit render here, more on Windows | M |
| F4 | Bookkeeping on the critical path: the user waits for store, reveal-sequence raster, thumbnail and prune | Medium | ~0.2–0.7 s off the time to pixels | M |
| F5 | Cold renders (first render of a slide, every background render) need 2 LuaLaTeX passes + biber, ~1.1 s fixed cost each | **High** for deck refresh/background | batching N slides per run: ~10× less CPU for a deck (estimate) | L |
| F6 | All three views of a slide share one build folder; switching views makes latexmk rerun (helper files flip) | Medium | one avoided pass (~1.1–1.4 s) per view switch/edit after a switch | S |
| F7 | Manifests store the whole project inventory (73 KB) and full input list (82 KB) per generation | Medium | disk (~155 KB × generations), JSON parse in lookup/prune | M |
| F8 | `prune_unused` (wrapper/cache sweep) runs before every build, one lock per wrapper | Low | 5 ms here; grows with slides × preambles | S |
| F9 | `configuration_key` (×2) and `_is_miktex` (×1) per render: `shutil.which` ×8, rc reads | Low | ~1 ms Linux; more on Windows `PATH` | S |
| F10 | Background renders build their own precompiled format (workspace) besides the foreground one | Low | one 2.3 s format build and 14 MB per preamble | S |
| F11 | Format folders of older schemas (`preview-formats/2-*`) are never removed | Low | 14 MB each, disk only | S |
| F12 | Option 2b (direct LuaLaTeX, no latexmk) | Low here | latexmk's own time was ~0.15 s per edit on Linux (2.10 s stage vs 1.95 s rules); larger on Windows (0.56 s measured there) | L |

### F1 – `-g` on every render-service miss (High)

`preview_requests.RenderService.request.work()` always passes `force_build=True` (lines 510–517), which reaches
`preview_build._compile_reserved` as `-g`. latexmk's log shows biber and lualatex rerun with reason `go_mode` on
every edit, although the slide has no citations ("Found 0 citekeys"). Without `-g` the same edit renders run only
lualatex: **2.44 s → 1.90 s**.

Why it is there: `tests/test_preview_requests.py` (around line 221) changes a theme file and restores its mtime.
The verified cache sees the content change, but latexmk would not, because it checks a file's hash only when its time
or size changed. So `-g` covers "the cache missed but latexmk thinks the build is current". It is needed only when
the wrapper text is unchanged. When the slide text changed, latexmk reruns LuaLaTeX anyway, and that pass reads every
input again.

### F2 – `prune()` after every render (High)

`RenderService.work()` calls `cache.prune()` before it returns the result. `prune()` globs every
`*/*/manifest.json`, stats every file of every generation and the image folder, then **reads and parses every
manifest** to collect referenced blobs. It does this even when nothing is old or over the limit. On the largest
real cache on this machine (167 generations, 199 MB) that is 26 MB of JSON and 191 ms. It grows linearly up to the
512 MB cap, around 0.5 s on this machine and more on Windows. The user waits for it.

### F3 – Repeated content hashing (High on Windows)

`preview_cache.file_state()` reads and SHA-256-hashes a file by design ("never trust modification time").
Per edit render:
- `_lookup`: evidence (`configuration_state` hashes latexmk, lualatex, pdflatex, biber, bibtex binaries, ~9.5 MB
  here) + `search_state` (walk of project and framework) + all recorded inputs;
- `begin()` ×3 (stability walk + config hashes);
- `preview_format._fresh()` (search + config + all format inputs, 25.6 MB);
- `store()`: `dependency_state` + `input_state` again (the stability re-check) + `_evidence`.

The Preview pane revalidates the shown slide about every 5 s (`_validation_poll` → `_refresh` → `validate_captured`),
another ~33 MB each time while the pane is visible. Of the bytes hashed, **98% are TeX-distribution files**
(356 files, 32 MB) and 2% project/framework files (11 files, 0.66 MB).

Distribution files and tool binaries change only through package-manager updates, which change size and mtime. A
`(size, mtime_ns, ino, ctime_ns)` fingerprint memo for files **outside the project and framework roots**, with content
hashes kept for project files, keeps the "same-mtime edit" guarantee where users edit, and removes ~98% of the
reads. On Windows (Defender scans every read; the earlier plan measured ~0.45–0.5 s of SlideMage-side time per render)
this is likely the largest SlideMage-side saving. It may also account for part of the ~12% idle CPU the owner saw.

### F4 – Bookkeeping before the pixels (Medium)

`work()` returns only after `prepare_preview_images` (needed), `preview_sequence` (re-rasterizes every page at
144 dpi for equality evidence), `store()` (hashes, PNG dedupe by reading each existing blob back, thumbnail via
PIL decode/encode, manifest writes), `publish_group` and `prune()`. Only the display PNGs are needed to show the
slide. The rest can run after delivery on the same worker, as long as the cache record keeps its race guards.

### F5 – Cold renders cost two or three processes (High for deck refresh / background)

Each slide has its own build folder, so a slide's first render, and every background render (a separate workspace),
is cold: lualatex, biber, lualatex. That is ≈ 3.5 s, almost all of it the fixed ~1.1 s per pass. The project-wide
"Update previews" already compiles one throwaway deck per template (`update_all_previews._build_deck_text` +
`compiler.run_job` + `slide_snapshot.capture_deck`), and `background_renders.ingest_compile` already maps deck
compile pages to render units. A **batched background renderer** (k slides per document, pages split per slide by
the framework's slide markers) would pay the fixed cost once per batch instead of once per slide.

### F6 – One build folder for all views (Medium)

`configuration_key(key_text, id_slug, …)` hashes the preamble and the slide id, not the view (the view is set after
`\begin{document}`). Instructor writes no `.ovl`, the student views do. Switching views therefore changes helper
files, and latexmk runs an extra pass (noted in `preview-passes-and-direct-lualatex.md` §1.4). One folder per
`(slide, view)` keeps each view's state stable. The cost is up to three folders per slide (small: aux files and
one PDF).

### F7 – Manifest size (Medium)

Each generation stores `evidence` (configuration + the whole search inventory, 73 KB) and `inputs` (82 KB). Most of
the inventory is identical across all generations of a project. Storing the evidence once, content-addressed
(`evidence/<digest>.json`), with the digest in the manifest, shrinks manifests ~10×. That speeds `_lookup`, `prune`
and `equivalent_views`, all of which parse them.

### F8–F11 (Low)

- **F8:** `preview_build.prune_unused` runs in `_compile_cached` before every build. It globs `decks/_slidemage_preview-*.tex`
  and takes a non-blocking lock per wrapper. Once per session plus from the idle scheduler is enough.
- **F9:** memoise the `shutil.which`/`resolve`/`stat` of `configuration_key` and `_is_miktex` per process, keyed by
  `PATH`. The rc file contents stay read each time (cheap and correctness-relevant).
- **F10:** background renders could load the foreground's format (read-only use under its shared lock) instead of
  building their own in `workspace/build/preview-formats`. That saves one format build per preamble. Keep the
  separation if it was deliberate for isolation (it is documented: "Background renders keep everything of theirs
  outside the project").
- **F11:** `preview_format.ensure` could remove `preview-formats/<other schema>-*` folders it is not using (under
  the same lock rules as `prune_unused`).

### Checked and fine

- Cache hit: 0.05 s; the view-sharing work (`image_group`, `classify_views`) costs 3–4 ms.
- The raster child process, the PNG LRU in `slide_snapshot._preview_pngs`, and render deduplication in
  `RenderService` (one request per key) work as intended.
- The 300 ms edit debounce in the Preview pane is reasonable.
- The v8.37.0 third-pass fix holds: a cold render here ran exactly lualatex, biber, lualatex.

## Plans

Order by value/effort: **0 → 1 → 2 → 3 → 4**, then 6, then 5 (largest, for background/deck refresh). Each plan is one
commit with its own version and changelog entry, like earlier plans. Each starts and ends with the bench from plan 0,
on Linux and on the owner's Windows machine.

### Plan 0 – A committed benchmark (prerequisite)

Done: `tools/preview_bench.py` (`--project --framework --deck --slide --view --language --repeat --in-place --keep --json --scenarios cold,unchanged,edit,view-switch,deck-refresh,fill-cache`), a temp copy of the project unless `--in-place`, a
table per scenario (medians over `--repeat`) and everything in `--json`; steps 1 and 2 below are met, step 3 (the recorded baselines) is still to do. `fill-cache` replaces the planned `--fill-cache`, `deck-refresh` the planned `--deck-refresh`.

**Linux baseline (before plan 1)**, `example/`, deck `slidemage-manual-copy`, slide `1an-EN-Slide-Versions`, Instructor,
medians of 3, Python 3.14, LuaHBTeX 1.22 (TeX Live 2025), Latexmk 4.87, 16 CPUs:

| scenario | total s | latexmk s | rules | content read |
|---|---|---|---|---|
| cold (forced) | 6.26 | 3.55 | lualatex ×2, biber | 143 MB |
| unchanged (hit) | 0.07 | – | – | 44 MB |
| edit | 2.41 | 2.07 | biber 0.52, lualatex 1.41 | 143 MB |
| view switch: during course | 3.85 | 3.51 | biber, lualatex ×2 | 143 MB |
| view switch: back to instructor | 3.90 | 3.54 | biber, lualatex ×2 | 143 MB |
| prune(), 400 generations | 0.114 | – | – | 41 MB manifests |
| deck refresh (79 renders) | 168.9 wall | – | – | child CPU 1071 s |

The Windows baseline is still to do: run the tool at this commit and at the branch tip on the owner's machine.

1. Move the harness to `tools/preview_bench.py`: arguments `--project`, `--deck`, `--slide`, `--view`,
   `--repeat N`. It copies the project to a temp folder unless `--in-place`. Scenarios: cold (forced), unchanged,
   edit ×N, view switch (Instructor → During course → Instructor), and a deck rerender
   (`update_all_previews.rerender_deck`) with `--deck-refresh`.
2. Output JSON: total, the latexmk stage, latexmk rules (from `preview_metrics`), the per-function timers (the same
   wrap list), `content_bytes_read`, `dependency_bytes_read` counters. Plus a short table on stdout.
3. Run it on Linux and on Windows (the owner's machine, MiKTeX), quiet machine, 5 repeats, and record the medians in
   `docs/findings.md` as the baseline. Go/no-go per plan below is judged against this.

### Plan 1 – `-g` only when latexmk cannot see the change (F1)

1. In `preview_build._compile_reserved`, compute `changed = not wrapper.exists() or wrapper.read_bytes() != new`
   (the existing check) and return it, or use it directly: pass `-g` only if `force and not changed`.
2. Keep `force` semantics for explicit "Rerender" (the user's force, `options.force`): there `-g` stays. In
   `RenderService.work()`, call `render_text`/`render` with `force_build=options.force or <cache missed with
   unchanged text>`. The second condition is what the theme test needs. Simplest correct rule:
   `force_build=True` from the service as now, and `_compile_reserved` drops `-g` when the wrapper text changed.
   That leaves every caller's meaning intact.
3. Biber edge case: a `.bib` edited with its mtime restored *and* the slide text changed in the same render. biber
   would not rerun. Accept it (same as latexmk's own behaviour), or add the recorded bibliography sources'
   content hashes to the wrapper's "changed" test (`recorded_inputs` already lists them from `.fdb_latexmk`).
   Recommendation: accept, document in the docstring.
4. Tests:
   - `tests/test_preview_build.py`: an edit after a cached build runs exactly `['lualatex']` (rules from the log
     lines, as the existing third-pass test does); an unchanged wrapper with `force=True` runs all rules; the
     existing theme-with-restored-mtime test in `tests/test_preview_requests.py` still renders.
   - Adjust `test_preview_requests.py:221` (`all(call['force_build'] …)`) only if the service-side rule changes.
5. Equivalence: render every example slide in all three views, edit (append a comment), render again, with and
   without the change. Compare pixels per page (the harness of the third-pass plan, §1.4). Expect identical.
6. Bench: edit render −0.5 s (Linux 2.44 → 1.90 s measured with the change applied from outside).

Done in v8.45.0: `-g` only when the wrapper text is unchanged (`_compile_reserved`). Linux, medians of 3: edit 2.41 →
1.91 s (rules `lualatex` only), view switch 3.85 → 3.35 s and 3.90 → 3.46 s; 30 of 30 display images (10 slides × 3
views) identical to the `-g` behaviour.

### Plan 2 – `prune()` off the per-render path (F2)

1. Add `PreviewCache.maybe_prune()`, which prunes at most once per N minutes per process (a module-level
   timestamp) **and** only when a cheap size estimate says it may be needed. Keep a running byte counter in
   `<root>/size.json`, updated by `store()` (plus) and `prune()` (recomputed), or use the image folder's size, which
   one `os.scandir` gives without reading manifests.
2. In `prune()`, read manifests for blob references **only if a generation was deleted** (nothing deleted → no
   blob can have become unreferenced). Use `os.scandir` for the stat pass.
3. Call `maybe_prune()` from `RenderService.work()` **after** the result is delivered (with plan 4), and from the
   idle/background scheduler. Keep `prune()` itself unchanged for tests and maintenance.
4. Tests: `prune()` with nothing to delete reads no manifest (count `read_text` calls via monkeypatch);
   `maybe_prune` rate limit; existing prune tests unchanged.
5. Bench: per-render `prune` time ~0 for the common case; measure on a cache filled to ~400 generations
   (`tools/preview_bench.py --fill-cache`).

Done in v8.46.0: `prune()` reads manifests only after a deletion, `maybe_prune()` (first call, then every 10 min or when the
in-memory size estimate passes `MAX_BYTES`) replaces it in `RenderService.work()`. Linux fill-cache (400 generations):
`prune()` 116 → 11 ms; edit render no longer prunes. `_prune_transients` measured 5.5 ms, left as is.

### Plan 3 – Fingerprint memo for system files; evidence once per render (F3, F9)

1. New `preview_cache.FileStateMemo`, process-wide, thread-safe:
   `state(path) -> [resolved, sha256] | None`. For paths **outside** the project root and the framework root
   (`search_roots`), it returns the cached hash while `(st_size, st_mtime_ns, st_ino, st_ctime_ns)` is unchanged and
   hashes only on a change. Paths **inside** those roots are always hashed (the existing guarantee for user files).
   On Windows `st_ctime_ns` is the creation time; size+mtime+ino still change on every package-manager update. Write
   that reasoning in the docstring.
2. Use the memo in `file_state` callers: `input_state`, `dependency_state`, `ValidationPass.inputs`,
   `configuration_state` (tool binaries), `preview_format._stamp`. Keep `file_state` itself for the project files.
3. Evidence per render: compute `configuration_state` once per `(project_root, env digest)` per render, passing a
   `ValidationPass` through `RenderService.work()` (`lookup`, `begin`, `store`), as list refreshes already do.
   The race guard stays: `begin()` before the build and the stability re-check after it still compare
   `search_state(stability=True)`. Only the redundant third `begin()` call inside `store()` goes, reusing the
   pass's evidence.
4. `preview_format._fresh`: same memo for the format's inputs. Plus a per-process verdict cache
   `(directory, format.json mtime) → (fresh, checked_at)` valid for a few seconds, so renders within a burst skip it.
5. F9: memoise `shutil.which` lookups in `configuration_key`, `configuration_state` and `_is_miktex` per `PATH`
   string (`functools.lru_cache` on a helper).
6. Tests:
   - the theme test with a restored mtime (project file) still misses;
   - a file outside the roots with unchanged stat is not reread (count reads through the existing
     `count('content_bytes_read', …)` counter);
   - a changed size/mtime outside the roots is rehashed;
   - `configuration_state` called twice hashes the binaries once.
7. Bench: `content_bytes_read` per edit render from ~100 MB to < 2 MB. On Windows, report the SlideMage-side time
   before and after. Also watch idle CPU with the Preview open (the 5 s revalidation).

Done in v8.47.0: `FileStates(roots)` memoises the state of files outside the roots (stat fingerprint, racy files and
misses not kept), `find_tool` memoises `shutil.which`, `work()` shares one `ValidationPass` between its two lookups,
`store()` derives its evidence from the `begin()` it compares. No verdict cache for `_fresh` (35 ms, and 2 s could
serve a format built from an edited theme). Linux, medians of 3: content read edit 143 → 2.0 MB, unchanged 44 → 1.1 MB.

### Plan 4 – Pixels first, bookkeeping after (F4)

1. Split `RenderService.work()` into **deliver** (build, `prepare_preview_images`, set the request's result so
   `wait()` returns) and **record** (reveal sequence, `store`, `publish_group`, `remember_display`,
   `maybe_prune`, temp-folder cleanup). `record` runs on the same worker thread right after deliver.
2. Contract changes:
   - The result's PDF is the temp render folder's PDF until `record` finishes. The temp folder is removed only after
     `record`, and only if nothing leased it: move the `shutil.rmtree(pdf.parent)` into `record`, and have
     `_ArtifactLease` keep the temp path alive.
   - `preview_result.status` stays `'rendered'`. The cache entry (`_cache_entry`) is attached when `record` ends.
     Consumers that need it (`equivalent_views`, the group alias) already go through the cache.
   - Cancellation: a cancel after deliver does not abort `record` (the pixels are valid). A failure in `record` is
     logged, never shown as a render failure.
3. Move the thumbnail into the raster child: `prepare_preview_images` asks for one more size (`THUMBNAIL_MAX`),
   so `store()` gets it without a PIL decode/encode. In `store()`, compare a blob by name only
   (`checksum.png` exists); the content-addressed name already is the hash, so skip `read_bytes() == data`.
4. Tests (`tests/test_preview_requests.py`):
   - `wait()` returns before `store()` runs (monkeypatch `store` to block on an event);
   - the cache entry exists after `record`;
   - a `record` failure leaves the delivered result intact;
   - the temp folder is removed after `record`.
5. Bench: time from request to `wait()` return for an edit render: expect −(store + sequence + thumbnail + prune),
   i.e. ~0.2 s on Linux and more on Windows or with a large cache.

Done in v8.48.0: `work()` is split into deliver (build, `prepare_preview_images`) and `record` (reveal sequence, `store`, `pin`,
`publish_group`, temp cleanup, `maybe_prune`); `wait(pixels_only=True)` returns at delivery, a plain `wait()` after the record
(all other consumers unchanged). The pane holds the temp PDF through its last request. Thumbnail from the raster child,
`store()` dedupes blobs by memoised state. Linux, medians of 3: time to pixels edit 1.91 → 1.78 s (store 97 ms + sequence 22 ms moved
after it), cold 6.43 → 6.23 s. Review fix: plan 3's `FileStates` resolved every path and compared `Path`s per root on each
call (22 000 `lstat`s in two renders, ~120 ms per `store()`); string prefixes and `realpath` only on a memo miss bring
`store()` to 34 ms, a cache hit to 0.03 s and an edit render to 1.84 s (pixels at 1.79 s).

### Plan 5 – Batched background and deck-refresh renders (F5)

Goal: render k slides of one deck/view/language in one LuaLaTeX document (two passes + biber for the batch), and
split the PDF into per-slide units with the same keys and evidence as single renders.

1. **Feasibility check first (one day, no product code):**
   - Build a batch wrapper for 8 slides of `slidemage-manual-copy` the way `_build_deck_text` does: the deck
     preamble, `\deckversion`/`\decklanguage`, and per slide `\setcounter{framenumber}{n}` + `\slide{id}`.
   - Compare each slide's pages, pixel by pixel, with its single render: overlays, footers, frame numbers, the
     navigation bar (it reads `.nav`, which now lists 8 slides), `\SMSlideSteps`, view rules.
   - Record which differ and why. The navigation bar is the likely difference: a single render's nav has one slide.
   - **Go only if** the differences can be removed by framework hooks (e.g. a `\SMPreviewIsolated` switch that
     resets nav entries per slide) or are absent.
2. **Page-to-slide mapping:** use the markers `ingest_compile` already relies on (`compile_records`: the slide id in
   the footer / `\SMSlideStart` records). Reuse `background_renders.ingest_compile`'s mapping code rather than a
   second parser.
3. **Batch planner** in `background_renders`: group outstanding units by `(deck, view, language, preamble)`,
   batches of k = 8 (setting), keeping the plan order within the group. One failing slide fails the batch. Retry its
   units singly (the current path), so one broken slide never blocks the rest.
4. **Evidence per unit:** each unit's manifest must list only the files that unit read. The batch's `.fls` is the
   union, which is safe: it only adds inputs, so the record may go stale more often but is never wrong. Use the union
   and note it. Optionally refine later with `\SMSlideStart`/`\SMSlideEnd` recorder marks.
5. **Deck refresh** (`update_all_previews.rerender_deck`) uses the same batch renderer for units with no foreground
   cache entry.
6. Tests:
   - batch of 3 fake slides → 3 units with the right page ranges;
   - a failing slide → singles retry;
   - unit records equal the single-render records for the same slide (real-TeX test, skipped without LaTeX).
7. Bench: 17-slide deck refresh, CPU-seconds and wall time, single vs batch. Expected order of magnitude: ~60
   CPU-s → ~10 CPU-s (2 passes × (1.1 s + 8 × 0.13 s) per batch of 8, plus biber once).

### Plan 6 – One build folder per view (F6)

1. Add the view and the language to the job identity in `preview_build._compile_cached`, as a second argument to
   `configuration_key(key_text, id_slug, …)`: `id_slug + '|' + view + '|' + language`. The wrapper body carries
   them as `\deckversion[...]`/`\decklanguage[...]`, so parse them there, or pass them down from `render_text`.
2. `prune_unused` already removes unused folders after 14 days. No change is needed.
3. Tests: Instructor → During course → Instructor on one slide runs one lualatex pass for the return to Instructor
   (no rerun from flipped helper files); folders differ per view.
4. Bench: the view-switch scenario of plan 0.

Done in v8.49.0: `preview_build.view_variant` reads the `\deckversion[...]`/`\decklanguage[...]` lines of the wrapper body (before `\setSlideID`) and `_compile_cached` adds it to the per-slide key only; the format key and `prune_unused` are unchanged. Linux, medians of 3: During course 3.39 → 1.85 s, back to Instructor 3.35 → 1.83 s (LuaLaTeX once instead of twice); an edit is 1.87 s.

### Not planned now

- **Option 2b** (direct LuaLaTeX instead of latexmk): latexmk's own share was ~0.15 s per edit on Linux. Redo its
  step 1 measurement on Windows after plans 1–3. It is worth it only if latexmk still costs ≥ 0.5 s there.
- **A persistent LuaLaTeX process** (pre-loaded format, one PDF per job): it would remove most of the 1.1 s fixed cost.
  But LuaTeX writes one PDF per run, and forking is not available on Windows, the main platform. Not feasible
  without a different engine setup.
- **The font replay** (0.16 s per pass) could be limited to fonts actually used. Small gain, risky (missing kerning
  is silent). Revisit after plan 5.
