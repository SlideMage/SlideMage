# Handoff: parallel preview renders (after v8.34.0)

Written 2026-10-19 before a context compaction. Read this first, then start with step 1 below.

## The owner's prompts (verbatim, in order)

1. "I continued the work on another PC. Now I have a new request - can the preview updating be parallelized? These
   are many small, independent tasks, are they not?"
2. "Go ahead and implement it. Go with the "fast" option as a default, but implement a rule to start new threads only
   when the CPU use is below 70%, our usual threshold."
3. (mid-work) "When the user clicks the preview update status, can the popup window list the individual threads?
   This would be really cool."
4. "Hmm, I was watching task manager and the CPU never seemed to rise beyond 12%. How does that square with 70%
   being the limiting factor?"
5. "Do we need to run them in batches at all? Can they not run independently, with one starting whenever another one
   is done? Explain, don't implement. Furthermore, what would option 2 entail? Again, explain."
6. **"Do option 1, then check 2a through c, finally do option 3. But first, write the necessary stuff to disk, then
   I'll tell you to compact, read the file you wrote and then you start."**
7. "Wait, one more thing - my PC runs at 12% CPU even if no render is running. Does that change your calculations?"
   (Answer: it strengthens the plan; renders themselves use only ~0.1-0.2 core each on average, they mostly wait.)

## Where things stand

- Repo `D:\uniCLOUD\SlideMage`, branch **`feat/parallel-previews`** (from `develop` at 016b078 = v8.33.0, which the
  owner pushed from another PC). Commits: `4fa7c7a` (v8.34.0, the parallel work), `af85227` (test fixes), and this
  file. **Nothing pushed, not merged into develop. Pushing/merging/tagging only on the owner's go.**
- Full suite on af85227: 2883 passed, 1 failed (the known intermittent `test_chat_gui.py::
  test_create_slide_shows_its_returned_preview_in_the_real_window`, Windows file lock, also on older develop).
- The owner's app: `dist\SlideMage-folder` replaced with the v8.34.0 folder build (smoke-tested); the v8.33.0 folder
  is kept as `dist\SlideMage-folder.v8.33.0.bak`. Since v8.33.0 the release makes a single file AND a folder build;
  `dist` now only has the folder. **Open question to the owner (unanswered):** the Start-menu shortcut
  `%APPDATA%\Microsoft\Windows\Start Menu\Programs\SlideMage.lnk` still points to the removed `dist\SlideMage.exe`
  (broken) — repoint it to `dist\SlideMage-folder\SlideMage.exe`? Do not change it without a yes.
- `LICENSE` showed as modified (CRLF only, from the other PC); restored with `git checkout -- LICENSE` at the owner's
  request. Working tree was clean afterwards.

### What v8.34.0 did (commit 4fa7c7a)
- **Root cause found**: on Windows every preview compile held the project's preview maintenance lock "shared", but
  `filelock.build_lock` used `msvcrt.locking` (exclusive only), so all preview compiles of a project ran one after
  another. Now `LockFileEx` (shared + exclusive) in `src/slidemage/filelock.py` (`_windows_lock`/`_windows_unlock`).
  Measured: 8 slides from scratch: 96 s one at a time -> 17 s eight at once.
- `background_renders.PROFILES` scale with cores: gentle 1, normal cores//4, fast min(16, cores//2); default "fast".
  `RenderScheduler` (`render_scheduler.py`): cap `workers` running jobs; a job beside running ones (not P_FOREGROUND)
  starts only if `may_add()` -> CPU below `idle_gate.CPU_LIMIT` (0.7). `power_status.shared_cpu_meter()` (one
  CpuMeter, min_interval 1 s) answers all CPU questions. `progress.working` follows all running jobs (`_set_working`).
- `parallel_runs.py` (new): `run_all(tasks, workers, may_add, cancel)` worker pool (first always starts, extra only
  with CPU room); `default_workers()` = max(2, min(16, cores//2)); `cpu_has_room()`.
- `preview_batch.render_batch`: units run through `parallel_runs.run_all`; views with the same `image_group` are one
  unit (in order); results keep order; `BatchProgress.done` / `DeckProgress.done` count finished ones (compile panel
  `compile_controller._preview_progress` and the Preview's "Rendering all views · n/N done" use it).
- `preview_raster_client.RasterPool` (up to `POOL_SIZE` = min(4, cores//6) children; `_shared` is the first).
- Status window (`ui/workspace/background_previews.py` `StatusDialog`): "Running now: n of up to N · processor x%
  busy (more start below 70%)" + a list (deck, slide, version, language, background/reveal steps, running time) from
  `BackgroundRenderer.running()` / `capacity()` / `RenderScheduler.running_jobs()`.
- Settings labels show the counts ("Fast (up to 12 at once)").

### Measurements (24 logical cores, 47 GB RAM; owner's machine idles at ~12% CPU: AdobeCollabSync ~0.8 core,
Outlook, Nextcloud, Syncovery)
- Deck refresh (`update_all_previews.rerender_deck`), 17 slides, Instructor, cold cache: 226 s one at a time,
  48 s parallel (4.7x). (Clear `project.preview_cache_dir(root)` between runs, or the second run is all cache hits.)
- 8 renders at once (`C:\smrc\where_time.py`): no lock waits (<1 s total); all 8 latexmk runs truly concurrent
  (~17 s each vs 12 s alone); one outlier render took **96 s** in one run (option 3).
- CPU sampling (`C:\smrc\cpu_top.ps1`): two short bursts per render (pass 1, pass 2) where all LuaLaTeX processes
  compute (~37% total, ~7 cores); between them 7-15% total: perl/latexmk ~1 core, process starts, MiKTeX, file I/O.
  Net render share ~0.1-0.2 core per render on average: **renders mostly wait**, so the cap (not the 70% rule) limits.
  Note: MiKTeX's engine processes are named `lualatex`/`miktex-*`; German Windows localises perf-counter names
  (use Get-Process TotalProcessorTime deltas, as cpu_top.ps1 does).

## The plan to carry out now (owner's order: 1, then 2a-c, then 3)

### Step 1 — option 1: more renders at once, one shared pool
- Raise the caps to the full logical core count (24 here): `parallel_runs.default_workers()` and
  `background_renders.PROFILES["fast"]` (keep a hard ceiling, e.g. 32, ~300 MB per LaTeX run; normal stays a
  quarter, gentle 1). Keep the 70% rule (CPU counts the whole machine, incl. the owner's ~12% idle load — intended).
- **One shared pool/budget for all three sources** (background scheduler, reveal-step counting, user batches): today
  each has its own cap. Introduce a process-wide render budget (e.g. a counting semaphore/token holder in
  `parallel_runs`, used by `RenderScheduler._next` and `parallel_runs.run_all`), so the total never exceeds the cap
  and the CPU rule applies to the total. The user's own single render (P_FOREGROUND) must never wait for the budget.
- Update Settings labels/tooltips, CHANGELOG/version (next: v8.35.0), tests (`tests/test_parallel_runs.py`,
  `tests/test_render_scheduler.py`, `tests/test_background_previews_gui.py`).
- Re-measure with `C:\smrc\bench_deck.py` (17 slides) and `C:\smrc\bench_parallel.py`, and CPU with cpu_top.ps1.

### Step 2 — check options 2a-c (measure first, then decide/implement what pays off)
First measure how one render's ~12-17 s split: perl/latexmk start+bookkeeping, MiKTeX/LuaLaTeX start-up, pass 1,
pass 2, raster (instrument `preview_build._compile_cached` / `compiler.run_latexmk`, latexmk `-time`, the log).
- **2a** Skip the second pass when it changes nothing: keep the slide's helper files (`.aux .toc .nav .ovl .top`)
  from its previous render (the reusable build dir partly does already; note benchmarks used `force_build=True`), run
  pass 2 only on "Rerun" in the log or changed helper files. Watch SlideMage's two-pass mechanisms:
  `\SMFinalStateForStudents` `.ovl`, Top Margin `.top`, deck context (sections/agenda), citations.
- **2b** Call LuaLaTeX directly for previews instead of latexmk (no biber/index for single-slide previews; fixed pass
  logic) — saves Perl/latexmk overhead. Full deck compiles keep latexmk.
- **2c** Load more into the precompiled preamble (`preview_format.py`, `preamble.fmt`): fonts/packages loaded on
  every run, to shorten start-up.
- (2d, several slides per LaTeX run, is NOT in scope.)
- Also look at file-access waiting: Windows Defender (`MsMpEng`) scanning TeX/MiKTeX files, MiKTeX file-name database.
- The build code (`preview_build`, `preview_format`) is Jürgen's: keep changes contained and documented.

### Step 3 — option 3: the outlier
One of 8 parallel renders took 96 s instead of ~17 s (`where_time.py`, render 4; latexmk run 0.3..96.4 s). Reproduce
(run where_time.py several times), find the stall (latexmk log, MiKTeX log
`%LOCALAPPDATA%\MiKTeX\miktex\log`, package install prompts/locks, luaotfload cache rebuild, file locks), fix or
guard (e.g. a timeout/kill-and-retry).

## Progress after the compaction (2026-10-19, same day)

All three steps done on `feat/parallel-previews` (nothing pushed or merged):
- **Step 1 = v8.35.0 (c02bb24):** `parallel_runs.default_workers()` = one per logical core (CEILING 32); one process-wide
  `RenderBudget` (`parallel_runs.BUDGET`) used by `run_all` and `RenderScheduler(budget=...)`; the user's own render and
  a batch's first never wait; idle renders stand back while a batch wants places. 17 slides: 48 s -> 30 s. Suite green
  (2888 passed).
- **Step 2/3 = v8.36.0 (1e0b2c8):** measured one render: cold 12.5 s = 3 LuaLaTeX passes of ~2.7 s + biber 1.5 s +
  latexmk ~0.5 s per step. Found the precompiled preamble had never worked on Windows (backslash path in the `-ini`
  command; MiKTeX ignores TEXFORMATS; fontspec's Lua module missing after the format). Fixed (`fmt_option`, forward
  slashes, `require("fontspec")` in PRELUDE_TAIL, SCHEMA 4): pass 2.9 s -> 1.6 s, identical pixels; cold render 7.5 s.
  The freshness check of the format now runs under a shared lock (was exclusive: renders started 0.35 s apart).
  The 96 s outlier = luaotfload's cache-writability test (fixed file name `m_t_x_t_e_s_t.tmp`) racing between LuaLaTeX
  runs that start together -> luaotfload quits -> fonts missing, MiKTeX maketfm ~1 s per font; reproducible at 24 at
  once (about 1 in 100 runs). Guard: `preview_build.font_cache_race` -> latexmk again with -g (up to 3 times),
  `FontCacheBusy` never disables the format; the format build does not mark it bad either. 17 slides: 20-24 s.
- **Checked, not done (owner may decide):** 2a skip biber (1.4 s, but citations are only known after pass 1; json
  image sources cite through Lua, so citing slides would get slower); latexmk's 3rd pass (pixel-identical, comes from
  latexmk treating newly-read helper files as changed); 2b LuaLaTeX directly (saves ~2.5-3 s per cold render, but
  replaces the latexmk dependency records the reusable builds use -- plan with Jürgen).
- Side findings: example slide `neg-EN-Installing-LaTeX-Linux` fails to render (`\faLinux` undefined; also on old
  code). Raster pool (4 children) is not a bottleneck (3.4 s summed for 17 slides).

## State when the owner said "stop here and write a handoff" (2026-10-20, ~00:15)

Owner's prompt, verbatim: **"Actually, stop here and write a handoff."**

- Branch `feat/parallel-previews`, HEAD **9e4eab0** (v8.36.0 plus a fix found by the full suite), then this file.
  Nothing pushed, merged or tagged. Working tree clean after this commit.
- The full suite on 1e0b2c8 had **2 failures**, both fixed in 9e4eab0:
  1. `test_release_notes.py::test_current_release_has_a_new_paragraph`: the CHANGELOG paragraph started "FIXED:"; only
     "NEW:" is parsed (`version.NEW_PREFIX`). Changed to "NEW:".
  2. `test_background_renders.py::test_a_real_background_render_...matches_the_foreground_render` (fails only when the
     whole file runs; new in v8.36.0): with the format, a citation-free slide can finish without biber; latexmk then
     records the bibliography as a missing source (`"Slidemaster.bib" 0 -1 0 ""` in .fdb_latexmk); `recorded_inputs`
     made it `decks/Slidemaster.bib` (nonexistent) -> manifest unstable -> render never FRESH. Fix: database entries
     with size -1 are skipped (`preview_build.recorded_inputs`); test case added in `tests/test_preview_dependencies.py`.
     The affected files pass (55 tests: preview_dependencies, background_renders, preview_build, release_notes).
- **Open, interrupted:** the full suite on 9e4eab0 and the exe build of 9e4eab0 were started and then **stopped** at
  the owner's request. Next session: run the full suite on 9e4eab0 (expect green apart from the known intermittent
  `test_chat_gui.py::test_create_slide_shows_its_returned_preview_in_the_real_window`), then build 9e4eab0, smoke-test,
  replace `dist\SlideMage-folder` while no SlideMage runs.
- **The owner's app right now:** `dist\SlideMage-folder` = the v8.36.0 build of **1e0b2c8** (smoke-tested: window
  "SlideMage — v8.36.0"; it LACKS the 9e4eab0 fix, so background previews of citation-free slides may stay "outdated"
  in the store). Backups: `dist\SlideMage-folder.v8.34.0.bak`, `dist\SlideMage-folder.v8.33.0.bak`.
  `C:\smrc\src` is checked out at 9e4eab0; `C:\smrc\dist836` holds the 1e0b2c8 build.
- Still unanswered from before: repoint the Start-menu shortcut to `dist\SlideMage-folder\SlideMage.exe`? (only on yes)
- Decisions for the owner: 2b (LuaLaTeX directly, with Jürgen) and 2a (skip biber), see above; merging the branch
  into develop; telling Jürgen that the precompiled preamble now works on Windows (his module `preview_format`
  changed: `fmt_option`, forward slashes, fontspec reload, SCHEMA 4, shared-lock freshness check, race guard).
- Scratch tools in `C:\smrc`: `bench_deck_par.py` (WARM_FORMAT=1 prebuilds the format), `batch_trace.py` (timeline,
  lock waits, stack samples), `split_time.py` / `pass_replay.py` (one render's passes), `fmt_pixels.py` (format vs
  full preamble, pixel compare), `tex_scale.py` (N bare LuaLaTeX at once; reproduces the font-cache race at 24),
  `bib_compare.py` (-bibtex- experiment), `cpu_top2.ps1` (CPU sampling with an extra argument).

## Working rules (from memory and this session)
- Tests: `PYTHONPATH=src QT_QPA_PLATFORM=offscreen C:/smrc/v/Scripts/python.exe -m pytest -q -p no:cacheprovider`
  from `D:\uniCLOUD\SlideMage` (full suite ~18 min; run in background; `-o faulthandler_timeout=180` to catch hangs).
  Ruff: `C:/smrc/v/Scripts/python.exe -m ruff check src tests`.
- Builds: `C:\smrc\src` worktree (`git -C C:/smrc/src checkout -q -f --detach <commit>`), then
  `C:/smrc/v/Scripts/python.exe -m PyInstaller packaging/slidemage.spec --noconfirm --distpath C:/smrc/distXXX
  --workpath C:/smrc/workXXX`; it makes `SlideMage.exe` and `SlideMage-folder/`. Smoke-test with
  `--project D:\uniCLOUD\SlideMage\example`, stop only processes I started, replace `dist\SlideMage-folder` (keep a
  backup) only while no SlideMage runs. Commit while the build runs.
- Never compile the owner's Slidemaster decks; never touch `D:\uniCLOUD\Slidemaster\decks\#workdeck.tex`; benchmark
  on scratch copies (`C:\smrc\...`). Never kill SlideMage instances I did not start. No push/merge/tag without a go.
- Heredocs mangle backslashes in Python/TeX: write scripts with the Write tool, edit with Edit.
- CHANGELOG entry header must not contain parentheses inside its "(...)" part (the version parser).
