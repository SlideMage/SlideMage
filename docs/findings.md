# Preview rendering: code review findings and plans

21 October 2026, `develop` @ 707b350 (v8.40.1). Review of the single-slide preview path (Preview pane, render
service, verified cache, latexmk build, raster) and the background/deck refresh paths, with measurements.
Earlier work this builds on: view sharing (done, `docs/PREVIEW_RENDER_OPTIMIZATION_VALIDATION.md`),
`docs/plans/preview-passes-and-direct-lualatex.md` (third pass fixed in v8.37.0; option 2b planned),
parallel renders (done).

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

**Plan 5, step 1: feasibility (21 October 2026).** Scripts in the session scratchpad (`batch/`), run on a temp copy of
`example/` + `latex/`; nothing under `src/`, `latex/`, `example/`, `tests/` was touched. Deck `slidemage-manual-copy`,
Instructor, EN (65 background units). Single = `render_slide_to_pdf(..., all_steps=True, workspace=...)` exactly as
`BackgroundRenderer._render_pdf` calls it, each in its own cold build folder; batch = one wrapper (the unit's
preamble, `\deckversion`/`\decklanguage`, the all-steps `_overlay_line` **once**, then per slide
`\setcounter{framenumber}{n-1}` + the unit's call, one `\end{document}`) through `preview_build.compile_cached`
(latexmk: lualatex, biber, lualatex). Pixels: PyMuPDF at 1920 px width, exact equality of the RGB samples.

**Go for steps 2–7.** Every page of every slide tried is pixel-identical to its single render, and the page counts match.

| What was compared | Slides | Pages single = batch | Identical |
|---|---|---|---|
| batch A: 8 consecutive units (1bb … 1cx; 1cx has citations in its code) | 8 | 8 = 8 | yes |
| batch B: 1vh, 1u5 (TikZ `remember picture`), 1nz (citation, biber), 1dk, 1th, 1t2 (reveals), 1mu twice (`\slidestep`) | 8 | 20 = 20 | yes |
| the whole deck in 9 batches of 8 (units 0–64: title, text slides, TikZ, figures, tables, columns, reveals, `\slidestep`) | 65 | 80 = 80 | yes |
| one batch of 16 and one of 32 | 16 + 32 | – | yes |
| synthetic: `\slideversion`, `\slidefinal`, `\conditionalslide`, `\omitslide`, then plain `\slide` of the same ids (does a final-state flag or version leak?) | 7 | 23 = 23 | yes |
| During course and After course (reveal slides), DE (title slide, translated slides) | 8 + 8 + 8 + 8 | = | yes |

Differences found: none for deck-order slides without context. Two causes are known and avoided or removed:

1. **The navigation bar.** `\SMNavigationLinks` shows its links only when the `.aux` holds `\SMAgendaDeckTarget` (written
   by `\SMDeckAgenda`, i.e. by a contents slide) or a chapter target (written by a chapter agenda). A single render
   prints just "Navigation:". A batch that contains the contents slide gets "Contents · Chapter contents" on **all**
   its slides after pass 2 (shown: batch of 1bb, 1r2, 1us, 1y9, neg, dkf: every normal page differs). Units that need
   context (`needs_context`: contents, chapter agendas) are not background units (`deck_units` skips them), so the
   case does not occur. If they are ever batched: one wrapper line before every slide,
   `\makeatletter\global\let\SM@ag@decktarget\@undefined\makeatother` (no `\section` is written either, so chapter
   targets stay unused). **Verified:** with it, the normal pages in that batch are identical to their single renders.
   No framework change is needed.
2. **Same bare id twice in one batch** (the two `\slidestep` calls of `1mu`): pixels are identical, but a split by slide id
   cannot tell the runs apart (6 consecutive pages of `1mu`), and `\hypertarget` is defined once. Planner rule: at most
   one unit per bare id per batch (the second has the same pixels anyway: its steps are dropped).

Not causes (checked): frame numbers (explicit `\setcounter` per slide), footer text and `v1.0.0EN` version tag
(`\ifSMSlideVersionSet` is reset by every `\slide`), hyperref anchors, overlay counters (page k is overlay k, as the
single path), `\SMSlideSteps`, pgf `remember picture` marks (second pass), bibliography (biber once for the union of cites).

**Splitting pages.** `\SMSlideStart` does not exist. Two markers exist already, both worked on all 65 slides:
- the **slide id on every page**: the footer's "(slide id: X …)" or, on frames without a footer (`\titleframe`,
  `\fullbleedframe`), `\SMInvisibleSlideIDStamp`. `slide_snapshot.slide_id_of(page)` + `slide_snapshot.slide_runs(...)`
  (what `ingest_compile` uses) gave the right runs in order in every batch; no page returned `None`;
- the **named destination** `\hypertarget{<bare id>}` that `\setSlideID` writes: `doc.resolve_names()[id]["page"]` is the
  first page of the slide in every batch tried (1dk → page 3 of 4 pages, 1mu, 1i4 …). It survives a page without a stamp.

Production: take `slide_runs` over the batch PDF, then **check** that the run ids equal the planned ids in the planned
order and that the pages add up; otherwise do not store and retry the units singly. `ingest_compile` gives the page
mapping (the loop over `slide_runs` / `runs.setdefault`) and the manifest filter `_compile_manifest`, but stores only
the **last** page as a partial record (`ORIGIN_COMPILE`, one image); a batch needs all pages of a run (`pages[a:b]`)
with a full record like `render_unit` (`store.put(key, origin, pdf_of_the_pages, pages, meta)`), so extract the unit's
page range into its own PDF (PyMuPDF `select`) or store the images without a PDF.

**Evidence per unit.** The batch's `.inputs.json` is the union (383 entries vs 366–368 for a single). Filtered with
`_compile_manifest`'s rule (drop other slides, drop media/snippets the slide's text does not name), the project-side set
equals the single's **exactly**, with two exceptions: the extras are TeX-distribution font files (`cmmi6.tfm`,
`FontAwesome5Brands-Regular-400.otf`: other slides of the batch; they go to `tex_files`, which only makes the record
stale a little more often), and the filter drops `media/alt-text.csv` that every render reads (the media rule drops it
because no slide names it). Exempt it when step 4 reuses the filter (a bug of `ingest_compile`'s records too: an edit of
`alt-text.csv` would not stale them).

**Timing** (Linux, cold build folders, format warm; child-process CPU = latexmk + lualatex + biber):

| | singles wall / CPU | batch wall / CPU | factor |
|---|---|---|---|
| 8 consecutive slides (A) | 29.5 s / 29.1 s | 4.7–5.0 s / 4.7–4.9 s | 6× |
| 8 slides, 20 pages with TikZ, citation, reveals (B) | 35.6 s / 35.2 s | 10.1 s / 10.0 s | 3.5× |
| units 4–19, k = 16 | 62.0 s / 61.4 s | 8.7 s / 8.5 s | 7× |
| units 0–31, k = 32 | 124.3 s / 123.0 s | 13.7 s / 13.6 s | 9× |
| whole deck, 65 units | 264.7 s / 262.0 s | 9 batches of 8: 64 s | 4× |

Model: ≈ 2.7 s fixed per batch (2 × 1.1 s + biber 0.5 s) + ≈ 0.35 s per slide (both passes), but heavy slides cost
more (2v9: 8.0 s single, 7.7 s as a batch of one; TikZ/tcolorbox slides ~0.5–1 s per pass). The expected "~10×" holds
only for large k; **k = 16 is a better default than 8** (7× against 4–6×), at the price of more work lost on a failure.

**Risks.** (1) One bad slide (`\undefinedmacro` → latexmk fails, the PDF is still written; a missing `\input` stops the
run) fails the whole batch: retry singly, as planned; the RuntimeError carries only the last 25 log lines, and the
offending `slides/<id>-current.tex:N:` is wrapped at 79 columns in the log, so do not parse it, retry singles. (2) A slide
that relies on global state of earlier slides is not different here (a deck compile has the same leakage and all 65
slides pass), but a slide file that `\newcommand`s/`\newcounter`s a name twice will error in a batch only if another
slide of the batch defines the same name: not seen in the manual deck, covered by the singles retry. (3) A slide
edited while the batch runs: record only units whose source hash still equals the one planned (as `ingest_compile` does).
(4) The unit list for one batch must share preamble text, view and language (the wrapper asserts it). (5) The job name
of the build folder comes from the wrapper hash; use a short id (the slide-id list in a name hit "File name too long").
(6) Same wrapper text + same id reuses the build folder: a second identical batch is a 2.2 s one-pass run, which also
makes a timing bench with an unchanged batch meaningless, use a fresh workspace. (7) Cancelling or a timeout now kills k slides.

Done in v8.50.0 (steps 1-4, 6, 7 for background renders; deck refresh, step 5, is not done): batches of up to 16 units (`bg_previews_batch_size`) in one document through `slide_preview.render_slides_to_pdf`, split by the slide id on each page, stored like single renders; failures retry singly. Linux, `tools/preview_bench.py background-batch`, slidemage-manual-copy Instructor EN, 64 units: 248.6 s wall / 239.8 s child CPU singly, 48.2 s / 41.0 s in batches of 16 (5.2x / 5.8x). `media/alt-text.*` are kept in the unit evidence (`_unit_inputs`).

Done in v8.51.0 (step 5, deck refresh): `rerender_deck` renders the requests without a verified preview up to `bg_previews_batch_size` (16) at a time in one editor-style document (`batch_render`, `slide_preview.render_slide_texts_to_pdf`), splits it by the slide id on each page (`slide_snapshot.batch_runs`) and records each slide through `RenderService.request(prebuilt=)` like a single render; a failed or unsplittable document leaves its requests to singles. Pixel gate (editor-style wrapper, instructor, during-course, after-course, 8 slides each): all pages identical, 8 singles 50.7 s wall against 8.8 s as a batch; the real-TeX test compares display pictures, page images and evidence of 3 slides (one `\slidestep`) with their single renders. Linux, 16 CPUs, `tools/preview_bench.py --scenarios deck-refresh`, slidemage-manual-copy, forced: batch size 1 219.7 s wall / 2258 s child CPU, 16: 79.5 s / 647 s (2.8x / 3.5x); the machine was not idle, the earlier single-document run was 168.9 s / 1071 s.

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
