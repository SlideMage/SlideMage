# Idle-time background preview rendering: findings and plan

Status: plan only (no code). Base: develop @ b3acd47 (v8.23.1). Branch: `claude/plan-idle-rendering-6d79cf`.

Companion plans (other branches, same base): `docs/plans/reveal-step-slider.md` and `docs/plans/deck-context-preview.md` (branch `claude/plan-reveal-slider-aa950d`), and the presentation-mode session. Where this plan touches them it says so (section 5.3).

**Owner decisions (2026-10-18), applied below:** idle means 30 s without input; the feature is on by default; background renders may keep wrappers and build caches outside the project; the footer timestamp is deprecated and removed (the version stays); a page number that is briefly off after inserting a slide is acceptable; scope is all decks in order of recency, all versions, and a deck whose inputs did not change is never touched again; pause on battery.

Goal from the owner: whenever SlideMage is idle it brings previews up to date, so that opening a deck rarely finds slides not yet rendered, **with all reveal steps**. Most recently used decks first; within a deck the instructor version first, then the other versions.

---

## 0. Summary

**Staleness verdict.** SlideMage has no system that tells it exactly what is stale for a single-slide render. It has four partial mechanisms, each right for its own purpose and none usable as the base for "is this background render still valid":

| Mechanism | Strength | What it cannot say |
|---|---|---|
| `PreviewTarget.key` + `RenderService` key | structural identity of a request (in-flight sharing) | nothing about content: the slide text enters only through `st_mtime_ns` and the buffer text; no media, no `latex/`, no engine |
| `preview_build.configuration_key` + latexmk state | latexmk checks every input it recorded (md5/mtime) when asked | it caches *build state*, not results: every request still launches latexmk; no query "is the result current" without a run |
| `slide_snapshot.is_fresh` | cheap | pure mtime comparison "PNG at least as new as the slide file"; ignores everything but the slide file; and wrong under sync (4.2) |
| `compile_records` (v5.34.0) | true content hashing (SHA-256 of every input from `.fls`, `.bib` from `.blg`, wrapper, engine line, PDF) | exists only for **whole-deck** compiles; rehashes every input on every check (no mtime shortcut); machine-specific absolute paths |

**Decision: extend, not replace.** Add a content-addressed *render key* in two parts (a cheap "fast key" computed without rendering, plus a dependency manifest recorded from the last render, as in Make/ninja depfiles), a per-machine persistent store with a SQLite index outside the synced project folder, and a single priority scheduler (shared with the reveal-slider's neighbour queue) fed by an idle producer. Existing keys keep their jobs (in-flight dedupe, latexmk state, whole-deck records, canonical snapshots).

**Key design decisions** (details in sections 3-8):

1. Render unit = (slide call as the deck typesets it, deck version, language, deck preamble). One **unrestricted** latexmk run yields every reveal step as one PDF page each; no per-step compiles.
2. Key = `fast_key` (slide content hash, call, view, language, preamble hash, template, engine fingerprint, wrapper schema) **and** a manifest of every file the last render read, each with a content hash. A render is valid iff both match. Hashes are cached by (path, size, mtime_ns) so checking is `stat`-only; mtime is a *shortcut*, never the verdict.
3. The frame number is **not** in the content key; it is a "decoration" recorded with the render. A render whose only difference is the page number is shown as *fresh, numbering differs* and refreshed at low priority. This stops one inserted slide from invalidating the rest of a deck and lets a slide shared by several decks share one render.
4. Renders live **inside the project folder** (`.previews/render-store/`, gitignored, synced with the project; owner decision) as immutable, content-addressed objects (PDF + pre-rasterised page PNGs + a self-describing `meta.json`). Only the **index is per machine** (local SQLite outside the project), because SQLite files and WAL do not survive a sync client. A second machine adopts the other's objects by key (portable engine fingerprint) instead of re-rendering. Not touched by `render_cleanup_hours`/`sweep_renders` (those only match `slidemage_preview_*` in the OS temp folder).
5. One worker, one LaTeX process by default, below-normal OS priority, preempted at once by a foreground render or deck compile, paused on user input, paused on battery by default, duty-cycled for heat.
6. **One run per slide-version**, isolated, identical to a foreground render. Multi-slide batching is evaluated (section 5.5) but deferred behind a benchmark gate, because it leaks TeX state between slides and loses per-slide dependency attribution.
7. Background renders **never** write canonical snapshots (MVP). Failures are remembered by key and retried only when an input changes or after backoff.

---

## 1. Investigation: staleness tracking today

### 1.1 What keys what (code facts)

**`preview_target.PreviewTarget.key`** (`preview_target.py:59-64`): tuple `(macro, id_slug, version, conditions, steps, frame_number, template, sha256(preamble_text))`. Excludes the view, the language and the slide's content. It is used inside the `RenderService.request` key (`preview_requests.py:100-102`) together with `source_path.resolve()`, the editor `text`, **`source_path.stat().st_mtime_ns`**, view, language, timestamp setting, presenter, mode, overlay. Purpose: share an in-flight request. Nothing is persisted; once the request finishes it is deleted from `_requests` (`finished()`). So it is not a cache at all.

**Preview build cache** (`preview_build.py`): `configuration_key` (`:119-146`) = SHA-256[:24] of {schema, project root, slide id-slug, wrapper **preamble** text (before `\begin{document}`), env vars (TEX*, LUA*, BIB*, FONTCONFIG*, LATEXMK*, MIKTEX*, PATH, ...), executable path+size+mtime of latexmk/lualatex/pdflatex/xelatex/biber/bibtex, contents of every `.latexmkrc` candidate}. It names a directory `.build/preview-cache/<key>/` and a wrapper `decks/_slidemage_preview-<key>.tex`. Per slide **and** preamble, **not** per view/language (those lines are after `\begin{document}`, so latexmk's own dependency check handles a change by re-running). With a precompiled format (`preview_format.ensure`) the key also takes the format's `st_mtime_ns`. Slide body, media and `latex/` files are tracked only by latexmk (`.fdb_latexmk`: mtime+md5), i.e. by *running* latexmk. The result is a "temporary PDF" copied to `slidemage_preview_*` in the OS temp dir (`publish_preview`, `:278-290`), plus `<pdf>.inputs.json` listing the recorded inputs (`recorded_inputs`, `:67-90`; used by the external-viewer watch) - note this dependency list **already exists** for every render and is the natural source for section 3.2.

**Footer timestamp.** The wrapper embeds the current minute literally (`_preview_timestamp_line`, `slide_preview.py:690-707`) when "Include footer timestamp" is on. So the wrapper text, and therefore the PDF bytes, change every minute. Any content key must exclude it; the owner has decided to remove the timestamp altogether (3.5).

**`slide_snapshot`** (`slide_snapshot.py`): PNGs in `.previews/slide_previews/<bare id>[-<Lang>]-<Template>-<w>-<h>.png` (full 1920x1080 and thumb 304x171), instructor view, last page only. Key = (bare id, language segment of the id-slug, template, size). `is_fresh` (`:395-407`) = `png.stat().st_mtime >= slide_path.stat().st_mtime` - the docstring says plainly it is a best-effort signal, "not a hash". `publish_preview` (`:229-240`) `touch()`es an identical PNG to "refresh freshness". An in-memory `_PNG_CACHE` keyed by (PDF SHA-256, size) is the only content-addressed piece: 16 entries / 32 MB, never persisted. The 665-snapshot legacy cache (module docstring) has no LRU on disk; `update_all_previews` prunes by "no deck needs it".

**`compile_records`**: `.build/compile-records/<jobname>.json` + `<jobname>/` (aux copies, `deck.tex`). Written after every successful whole-deck compile; holds SHA-256 of every `.fls` input and `.bib` source (`write_record`, `:230-330`), the wrapper hash without the run line, `engine_version()` (`lualatex --version` line, cached per process), the PDF path and SHA-256, TeX package version lines. `fresh_output` / `check_record` re-hash **all** inputs every time (`sha256()` reads whole files, 1 MiB chunks) - no mtime shortcut. Deliberate limitations (module docstring): luatex caches skipped; a file looked for but absent is not in the `.fls`; no record if an input changed during the compile (`path.stat().st_mtime > started`); absolute, machine-specific paths. `partial_compile` and `deck_snapshot` consume them. This is the best staleness test in the code base and the design below imitates it per slide.

**Slide versioning** (`slide_versioning.py`): the "+" marker flags "changed since last version" (`changed_slides`); frozen `-vX-Y-Z` files are immutable by convention. The "+" is a flag in the file text, not a hash; but it does mean a call with `version` set (frozen) points at a file that never legitimately changes - its content hash is a stable identity and such renders almost never go stale (only through preamble/media/engine). A current-version render is keyed by the file's content hash, so "+" changes (which rewrite the header line) are also content changes and correctly re-render.

**Render cleanup** (`slide_preview.py:48-95`): `sweep_renders` -> `sweep_old_renders(hours*3600)` deletes folders matching `slidemage_preview_*` in the OS temp dir that are older than `render_cleanup_hours` (1/24/72/168/720/Never, default 24). Runs 'shortly after start' (`maintenance.py:176-185`, daemon thread) and after renders (`preview_view.py:564`). It only governs user-facing temp PDFs. `_sweep_stale_previews` deletes `.build/preview-*.*` older than 1 h (fresh-build path only). `preview_build.prune_unused` deletes wrappers/caches idle for `UNUSED_DAYS = 14`. "Remove temp files" (`housekeeping.py`) deletes `.build` entries (not `compile-records`), `decks/_slidemage_*.tex`, `.temp/`.

### 1.2 mtime versus content hash

| Thing | Keyed by | Notes |
|---|---|---|
| `RenderService` request | source `st_mtime_ns` + text | mtime only to separate revisions; fine inside one session |
| Snapshot freshness | mtime compare | content-blind, dependency-blind |
| latexmk build state | its own md5+mtime of recorded inputs | exact, but only when latexmk runs |
| `preview_format` freshness | `_stamp` (mtime-based) of inputs | `preview_format.py:102-130` |
| prune/cleanup | mtime ages | fine, age-based by design |
| `compile_records` | SHA-256 | exact, whole-deck only, no stat shortcut |
| `_PNG_CACHE` | SHA-256 of PDF | exact, volatile |

### 1.3 Gaps (what changes a render but is not tracked per slide)

- **Dependencies of the render.** `is_fresh` sees only the slide file. Not seen: `Slidemaster_preamble_base.tex`, the institution layer `Slidemaster_preamble_*.tex` (project root or `latex/`), other `latex/` and theme files, snippets `\input` by the slide, media (`\includegraphics`), image description files, `.bib` (`Slidemaster.bib`, cited slides), fonts. The deck's own preamble *is* hashed in `PreviewTarget.key`, but the files that preamble `\input`s are not.
- **Deck-level settings.** Version/language are lines after `\begin{document}` (hashed nowhere persistent). A deck's course settings, footer text, `\decktags` etc. live in its preamble (covered by the preamble hash) or in the generated wrapper of full compiles (not used here).
- **Deck context.** `frame_number` is in `PreviewTarget.key`; section/agenda/contents/citation numbering needs the deck-context plan (aux files of a whole-deck compile): not tracked anywhere for single-slide renders.
- **Engine and TeX distribution.** `configuration_key` stat()s executables but a MiKTeX package update changes neither the executable nor the key; `compile_records` records the engine line and package version lines but a per-slide render has none of that persisted.
- **Wrapper/template logic.** A change to `slide_preview` (new `\deckversion` handling, overlay patch) changes the output of every render with no key change.
- **Footer timestamp** changes the wrapper every minute (see 1.1); to be removed (3.5).
- **Negative dependencies.** A file that did not exist when the slide was rendered and appears later (a project-level `Slidemaster_preamble_uni-graz.tex` now shadowing the framework copy found via `TEXINPUTS`) is invisible to `.fls`. `compile_records` documents the same limit.
- **Frozen vs current.** Snapshots are not kept for a frozen version shown alone (`is_frozen_alone`), so those always re-render.
- **Reveal steps.** Snapshots keep the last page only; the pages for earlier steps are never persisted anywhere.

### 1.4 Cloud sync and cross-machine (the project lives in `D:\uniCLOUD`)

- `.build/`, `.previews/` and `decks/_slidemage_preview-*.tex` wrappers are **inside the synced project folder** (`project.py:466-473`, `ctx.build_dir = root/.build`). Build caches contain absolute machine paths and are useless on a second machine; they still get uploaded (the format `.fmt`, latexmk state, 2 wrappers per slide/preamble). Background rendering of hundreds of slides multiplies that churn unless the new store sits elsewhere (5.2) and the wrapper-in-`decks/` problem is solved (owner approved moving them out).
- `is_fresh` can say **fresh when it is stale**: a sync client that restores the *remote* modification time can leave a source file with an older mtime than a local snapshot even though its content changed on the other machine. `RenderService` keys on mtime only within a session, so it is unaffected. This is the one real correctness bug class found; content hashing removes it.
- Cloud placeholders ("files on demand") make `stat` free but reading a file hydrates (downloads) it; sync may also write a file in several steps. The design therefore hashes only when `(size, mtime_ns)` changed, never hashes files modified in the last seconds, and re-checks size/mtime after hashing (git's "racy" rule).
- Snapshots in `.previews/slide_previews` *are* shared between machines through sync - that is a feature (a fresh machine sees thumbnails) and a risk (a snapshot made by machine A with a different TeX/fonts replaced by B). It stays that way; the background store is deliberately per-machine.
- Two machines running SlideMage concurrently would each render their own store independently; no coordination is needed because nothing shared is written (except foreground snapshots as today).

---

## 2. Investigation: existing background and idle work

- **Idle timers:** none. `QTimer.singleShot` only for start-up delays in `ui/workspace/maintenance.py` (compat check, bundled copies check, render sweep on a daemon thread, update check) and the 300 ms preview debounce (`preview_view.py:253`). No input-idle detection, no power/CPU awareness (grep: no `battery`/`GetSystemPowerStatus`).
- **`RenderService`** (`preview_requests.py`): a dict of in-flight `RenderRequest`s deduplicated by key. A request starts a **new daemon thread when someone calls `wait()`** (`:48-56`); there is **no queue, no priority, no concurrency cap**. Cancellation is cooperative through `compiler.CancelToken` (`request_stop`, kills the live `Popen`); `wait()` times out after 300 s. The pane creates one `RenderService()` (`preview_view.py:250`) and runs work in `Thread(target=self._run)` (`:543`).
- **LaTeX process count:** per-slide preview builds take a per-cache file lock (`build_lock(cache/'build.lock')`) so one slide/preamble builds at a time, but different slides can build in parallel if the user triggers them. Whole-deck jobs run serially in `run_jobs` (jobs loop, `compiler.py:1004+`). Before building, a precompiled format is created once per preamble under a lock (`preview_format.ensure`). A "maintenance" shared lock (`preview-maintenance.lock`) lets cleanup wait for or skip live builds (`cleanup_guard`).
- **Rasteriser:** a single long-lived child process (`preview_raster_client`), requests serialised by a global RLock; request timeout 15 s. Anything in the background that rasterises many pages holds that lock - chunk it (section 5.7).
- **`update_all_previews`:** user-triggered "Update previews" compile of throwaway megadecks for every template, instructor view, last page only; `deck_snapshot` compiles all versions for snapshots with `compile_records` reuse. These are the existing *bulk* preview producers; this plan does not touch them.
- **Recency data:** only `LAST_DECK_KEY = "last_deck"` (a single deck name) in `.slidemage/app_settings.json` (`window.py:74,333-346`), which is inside the synced project. No list of recent decks, no timestamps, no last slide position. `project.recent_projects()` exists for projects, not decks.
- **Compile status:** `compile_status.py` / `compile_actions` know when a deck compile runs (used by the reveal plan as a precondition); Claude Code tasks and AI jobs run elsewhere (`ui/workspace/terminal`, `ai/`). The scheduler needs a single "busy" predicate over these (6.2).

---

## 3. Design: the content-addressed render key

### 3.1 Replaces or extends? **Extends.**

- `PreviewTarget.key` and the `RenderService` key stay (in-flight sharing, buffer renders, overlay renders). The reveal plan already wants a steps-free variant of it; that is a prefix of the new fast key.
- latexmk build state and `preview_format` stay as the *how fast* layer under every render.
- `compile_records` stay for whole-deck compiles. The new hash utility (3.3) could later also serve them (it removes their "rehash everything" cost) - out of scope here.
- `slide_snapshot.is_fresh` gains a key-based path (sidecar from the store), keeps mtime as fallback for legacy snapshots (phase 3).

### 3.2 The key: fast key + dependency manifest

A *unit* = what the Preview would render for one deck slide call in one view/language. `fast_key` is computed from the saved state of the project **without running TeX**:

```
fast_key = SHA-256 of canonical JSON {
  schema:         RENDER_SCHEMA                 # int, bumped when wrapper logic or this key changes
  slide_sha:      sha256(slide source, EOL-normalised)   # the file the call loads (current or frozen)
  call:           macro, id_slug, version, conditions    # steps: NOT included (unrestricted render)
  view:           instructor | during-course | after-course
  language:       en | de
  presenter:      false                          # presenter renders are not background-prepared
  preamble_sha:   sha256(deck.preamble_text)     # as today; or default preamble + template for slides with no deck
  template:       slide_snapshot.detect_template(...)
  engine_fp:      lualatex --version line + latexmk/biber version lines + OS font-cache-independent TeX fingerprint (3.4)
  config_sha:     the part of preview_build.configuration_key that is not path-specific (rc files, TEX* env)
}
```

Deliberately **not** in the key (recorded with the render instead, "decoration"): `frame_number` and the render time (the footer timestamp is being removed, 3.5). See 3.5.

`manifest` = every file the render read, from the `.fls`/`.fdb_latexmk` of the render (the same data `recorded_inputs` writes to `<pdf>.inputs.json`) plus the `.bib` files biber read (`.blg`, `compile_records.parse_blg_sources`). Partitioned into:

- **project files** (under the project root or the framework `latex/` dir): stored as root-relative POSIX path + SHA-256. These are the real invalidators: preamble layers, `latex/`, snippets, media, image descriptions, `.bib`.
- **TeX distribution files** (under the TeX root: packages, fonts, formats): thousands per render, never content-hashed; covered by `engine_fp` and a *distribution stamp* = hash of the sorted `(path, size, mtime_ns)` of those inputs (stat only, ~hundreds of `stat` calls). A MiKTeX/TeX Live package update changes a stamp and invalidates only renders that read that package.
- **derived/volatile** (excluded, as in `compile_records`): `luatex-cache`, the build/cache dir, wrappers, `.previews` (a generated appendix's thumbnails).

A stored render is **valid** iff `fast_key` equals and every manifest entry's current hash equals. Because manifests are per render, a change to `Slidemaster_preamble_base.tex` invalidates every render that read it, and a change to one image invalidates only the slides that show it, with no separate dependency parser. Slides that were never rendered have no manifest: they are simply *missing*.

### 3.3 Cheap computation

- **File hash cache** (`dep_hash.py`, SQLite table `filehash(path, size, mtime_ns, sha256, checked_at)`): `current_hash(path)` = `stat`; if `(size, mtime_ns)` equal the row, return the stored hash, else hash the file and update. Cost per check: one `stat` per dependency. A deck with 80 slides x ~15 project deps (~100 distinct files, most shared) costs about a hundred `stat`s, i.e. well under 10 ms warm.
- **Racy files:** if `mtime_ns` is within `RACY_SECONDS` (3 s) of now, do not trust the shortcut and do not store the hash; defer the unit (sync may still be writing). After hashing, `stat` again; if it moved, retry later.
- **Slide hash** is the same cache applied to the slide file; EOL-normalisation is applied *after* hashing raw bytes only for the key (hash the raw bytes in the cache, key on `sha(normalise(text))` computed when the raw hash changed). Simpler: key on the raw bytes hash; a CRLF/LF flip from sync just causes one extra render. (open question below)
- **Change detection without scanning everything on every tick:** keep an inverted index `dep path -> render ids`. Triggers: (a) deck open / app start: stat-sweep the union of manifest paths of the all decks' renders (a few thousand `stat`s, tens of ms); (b) `QFileSystemWatcher` on the project's `slides/`, `snippets/`, `media/`, `latex/` and the preamble layers is an *optimisation* (low-latency dirty marking) but the stat-sweep stays the authority, because watchers miss events on synced folders and network drives; (c) an idle "audit" tick that re-verifies a rolling slice of the manifests, including a full content re-hash (ignoring the stat shortcut) of a few files per tick, to catch same-size-same-mtime edits that only a sync client can produce.
- **Dependency list for the *next* check** comes from the render that was just made; no TeX parsing in Python. If a render's inputs changed *during* it (any manifest file's mtime > render start, as `compile_records` does) the render is shown but stored as *unstable*: not trusted as fresh, re-rendered next idle slot.

### 3.4 `engine_fp`

`compile_records.engine_version()` (already memoised per process) plus: the `LaTeX2e <...>` and top-level package version lines of the first render's log (`compile_records.version_lines`), stored once per TeX installation in the store (`meta`), plus the distribution stamp above. `RENDER_SCHEMA` guards SlideMage's own wrapper logic: a test hashes the source text of `slide_preview`'s wrapper-building helpers (`_footer_timestamp_line`, `_deck_version_line`, `_overlay_line`, `GENERIC_PREAMBLE`, ...) and fails when it changes without a `RENDER_SCHEMA` bump. This avoids tying the key to the app version (which would re-render everything on every release).

### 3.5 Frame number, timestamp, deck context

- **Frame number** (page number in the footer; set by `\setcounter{framenumber}`): excluded from `fast_key`, stored on the render. Lookup returns `FRESH` when it matches, `FRESH_NUMBERING_DIFFERS` when only this differs (the image is correct apart from the footer number; UI shows it without an "outdated" badge but with a quiet marker, and the scheduler re-renders it at the lowest priority). Rationale: inserting one slide at the front would otherwise stale every later slide in every version of the deck, and a slide used in several decks (identical preamble) would be rendered once per position. The owner accepted this (page number may be briefly off). Strictness would be a one-line change if ever wanted.
- **Footer timestamp: deprecated (owner decision).** The footer keeps the version and drops the date/time. Consequence for this plan: no timestamp in the wrapper (`_preview_timestamp_line`, `_footer_timestamp_line`, the `footer_timestamp` argument and the toolbar's "Include footer timestamp" checkbox go away in a separate prerequisite change, also in `compiler.wrapper_text` and the `SMFooterTimestampOverride` / `.timestamp` mechanism of the template), so the wrapper text is stable per (slide, preamble), PDF bytes are reproducible, latexmk's no-rewrite rule works, and nothing time-dependent is in the key. Until that change lands, the key ignores the timestamp and a background render simply shows its render time.
- **Deck context** (deck-context plan: contents/agenda/section slides, real citation labels): such units get a `context_sha` in the key = id of the whole-deck compile record they used (or the "skeleton B" input hash). Until that plan lands, units the scan flags as context-dependent are rendered like today (standalone) and carry `context: none`; when the deck-context plan lands the flagged units re-key and re-render once. Units flagged as needing a context that does not exist yet are **not** background-rendered (a wrong image would be worse than none).

### 3.6 Invalidation, precisely

| Change | What goes stale |
|---|---|
| Slide file edited / synced from another machine | that slide's renders (all views/languages), by `slide_sha` |
| `Slidemaster_preamble_base.tex`, a `latex/` file, an institution layer | every render whose manifest lists it (usually all decks of that template) |
| Snippet / image / `.bib` edited | only renders that read it |
| Deck preamble edited (template, theme, footer) | that deck's units (preamble hash); other decks' units survive |
| Deck call edited (steps, version pin, conditions) | the call part of the key; a `steps` change alone does not (unrestricted render) |
| Slide added/removed/moved in deck | nothing is invalid; `frame_number` differs -> numbering state, low priority refresh |
| Language of the deck changed | different `language` key; the other language's renders remain |
| TeX/MiKTeX update | by distribution stamp, only renders that read changed packages; engine line change = everything |
| SlideMage wrapper change | `RENDER_SCHEMA` bump = everything |
| Anything while the app was closed | detected at the next sweep: hashes are compared on open, never trusting "nothing happened" |

---

## 4. Design: storage

### 4.1 Where (revised: owner asked for the store in the project)

Is a store in the project sensible even though it is synced? Mostly yes, with two conditions. Renders are a function of project content (the key is a content hash), so a render made on machine A is valid on machine B when B has the same TeX engine/packages; sharing saves B from re-rendering the whole project after a sync. What does *not* work in a synced folder is a database file: SQLite (and its `-wal`/`-shm` files) is corrupted or conflicted by sync clients. So:

- **Shared, in the project:** `.previews/render-store/objects/<ab>/<render_key>/` holding `slide.pdf`, `p01.png ... pNN.png` (every page at `STORE_WIDTH` 1280) and `meta.json` (the full index row incl. manifest, written **last**, with sizes and SHA-256 of the other files). Objects are write-once and never modified, so sync never sees a conflict; a half-synced object (no `meta.json`, or sizes/hash mismatch) is ignored until complete. Written to a temp dir and renamed into place.
- **Per machine, outside the project:** the SQLite index (`<cache base>/render-store/<project-id>/index.sqlite`; Windows `%LOCALAPPDATA%\SlideMage\`, macOS `~/Library/Caches/SlideMage/`, Linux `$XDG_CACHE_HOME/slidemage/`; new `project.cache_dir()`), the file-hash cache, failure memory and `deck_usage`. It is a cache of the `meta.json` files: if lost, it is rebuilt by listing `objects/` (cheap: small JSON files), which is also how objects arriving from another machine get adopted.
- **Portable fingerprint:** because objects are shared, `engine_fp` must not contain machine paths or mtimes: engine version line + latexmk/biber versions + OS family (fonts and rasterisation differ across OSes) only. The stat-based "distribution stamp" of TeX package files (3.2) stays a *local* check applied to renders this machine made; an object adopted from another machine is accepted on `fast_key` + project-file manifest and is marked `foreign` (shown as fresh and trusted; no local re-verification, owner decision).
- **Cost:** the store counts against the cloud-sync quota and every machine's disk, up to the disk limit (setting). Two machines rendering the same unit at once create two objects with the same key; the second rename fails and is discarded (identical content). Eviction deletes object directories; sync propagates the deletion, which is correct (the other machine's index forgets it at its next listing).
- Wrappers and latexmk build caches (a speed layer with machine-specific absolute paths) stay out of the synced folder where Phase 0 shows it works (`ctx.build_dir` override under the local cache base); the store is the only new thing in the project.

```
<project>/.previews/render-store/objects/ab/<render_key>/
    slide.pdf   p01.png ... pNN.png   meta.json   (meta.json last)
<local cache>/render-store/<project-id>/
    index.sqlite   tmp/
```

Identical pixels are deduplicated across keys (a slide without version logic renders identically in all views) via a `blobs/<sha>.png` store referenced from `meta.json`. PDFs are kept so any other size can be rasterised later and the step count is always known.

### 4.2 Index (SQLite, stdlib, per machine)

Persistence across restarts needs a durable index and SQLite gives atomic multi-row updates, cheap LRU queries and "what is missing for deck D" queries with no JSON rewriting.

- `renders(id, fast_key, unit_id, view, language, slide_id_slug, deck_path_hint, pages, width, height, bytes, frame_number, rendered_at, last_used, duration_ms, pdf_sha, manifest_sha, state)`; `state` in `ok | unstable`.
- `manifest(render_id, relpath, kind, sha256)` (kind: project/framework/bib/tex-stamp).
- `filehash(path, size, mtime_ns, sha256)`.
- `failures(fast_key, manifest_probe_sha, attempts, last_error_tail, kind, first_at, next_try_at)` (6.4).
- `deck_usage(deck_path, last_opened, open_count, last_slide_id, last_view, last_language, pinned)` - **per machine**, replaces reliance on the synced `last_deck` (that setting stays for startup).
- `meta(schema, engine_fp, tex_root, created)`.
- Rebuild rule: if `index.sqlite` is missing/corrupt/newer-schema, delete it and rebuild from the `meta.json` files in `objects/` (the objects are the source; the index is a cache). `deck_usage` and failures are local and simply start empty.

### 4.3 Budget and eviction

- Estimate: ~100 KB/page PNG x ~4 pages x 3 views + PDFs ~ 1.5 MB per slide when every version differs, much less after dedup; 700 slides in recent decks is on the order of 0.5-1 GB. Default budget **2 GB** (setting), plus a free-disk guard: no background rendering when free space on the volume is under 5 GB.
- Eviction order when over budget (run after each render and at start): (1) superseded renders of units that have a newer one; (2) renders of slides/decks that no longer exist; (3) decks least recently opened (`last_used` oldest); (4) LRU over the rest. Renders belonging to the open deck and the most recently used decks' *current* keys are protected unless the store is 2x over budget. With all decks in scope the budget is what bounds the store: when it is reached, background rendering of the oldest decks stops rather than evicting recent ones (shown in the chip). `last_used` is updated when the Preview/slider reads a render.
- The previous valid-then-superseded render of a unit is kept until its replacement exists, so the UI can show an "outdated" image rather than nothing while re-rendering.

### 4.4 Interaction with the render cleanup setting and `sweep_renders`

- `sweep_renders` removes `slidemage_preview_*` folders in `tempfile.gettempdir()` older than `render_cleanup_hours`. The store is a different place and a different name, so **background renders are never swept by it** and never need the setting. The setting remains the lifetime of *user-facing* temp PDFs only.
- The only coupling: the render pipeline still produces its PDF in a `slidemage_preview_*` temp folder (`publish_preview`). The store step must **move the PDF into `renders/` immediately after publication** and delete that temp folder (as `preview_requests.work` does on a raster failure, `:109-110`), so nothing a background render created depends on the sweep and the 1-hour setting cannot delete a half-adopted file.
- Add the store to Housekeeping (`housekeeping.py`/dialog): show its size and offer "Clear background previews". "Remove temp files" does not delete it (it is not a temp file). `preview_build.prune_unused` and `_sweep_stale_previews` keep applying to build caches, which are only a speed layer (a pruned cache = one slower render).
- Optionally a second setting "Keep background previews: for decks used in the last [14 days]" independent of `render_cleanup_hours`, as the store's own age rule (default 30 days).

### 4.5 Snapshot rules

- **Background renders never write `.previews/slide_previews` snapshots or thumbnails** in the MVP. Canonical snapshots remain products of (a) foreground renders of the instructor view and (b) whole-deck compiles (`capture_deck`).
- Phase 3 optional "adoption": a background instructor render may refresh a snapshot only if all hold: unrestricted call (no `steps`), not a frozen-alone target, not context-flagged, the render's key is valid now, the deck's template equals the snapshot's template, and the snapshot is not newer than this render's source (compare `slide_sha` recorded in a snapshot sidecar, falling back to mtime for legacy). It writes via `publish_preview` (identical bytes -> only `touch`). This also gives snapshots a key-based freshness (3.1).
- Never overwrite with a "worse" image: a during-course/after-course render, a render with a failed bibliography (cf. `BIBER_NEEDED_RE`), an `unstable` render, or a render older than the existing snapshot's recorded source time. Overlay (`overlay=N`) and presenter renders never snapshot, as today.

---

## 5. Design: the scheduler

### 5.1 One shared scheduler, three priority classes

A single `RenderScheduler` (Qt-free core, in a new module next to `preview_requests.py`) owns the worker thread(s) and exposes:

```
submit(unit, priority_class, rank, reason, cancel_group)
cancel_group(name) ; preempt()        # foreground arrival
```

Classes (strict order): **P0 foreground** (the user asked: selected slide, edit render, deck compile busy -> pause); **P1 neighbours** (the reveal-slider plan's "selected slide + 4 neighbours, 1 process"); **P2 idle sweep** (this plan). `RenderService` keeps request dedupe and becomes the P0 entry; the reveal plan's `BackgroundRenders` is the P1 producer. All three call `store.ensure(unit)`: look up -> valid? done : render -> store. When this plan has been working, the P1 producer finds almost everything already ready and does nothing; when it hasn't, P1 behaves exactly as the reveal plan describes. **Precedence between the reveal-slider's renders and background renders (owner decision).**

1. *Scheduling (owner decision):* the reveal-slider's renders (P1) always come first and **never wait for a background job, not even one for the same key** (a background job can take minutes). On a P1 arrival the running P2 job is cancelled and re-queued (not a failure); the P1 render then runs. P1 may use a second process slot when the profile allows it.
2. *Which version is kept (owner decision):* the background version wins. Two cases: (a) a reveal render finishes for a unit and the background sweep renders that unit later: the sweep treats a reveal-made object as *provisional*, still renders it, and the new background object replaces it; (b) a reveal render is requested for a slide that has not changed and a valid background object exists: no render is made, the background object is used. The store keeps objects write-once, so both can exist for a key as `<key>` (origin reveal, provisional) and `<key>.bg` (origin background); lookup prefers `.bg`, and the provisional one is deleted once `.bg` exists. Where the two differ in something in the key (deck context, `context_sha`), they are different keys and the richer one is preferred; a poorer entry never replaces a richer one.
3. *What the reveal producer must do (the "feeding" interface):* call `scheduler.submit(unit, class=P1, rank, cancel_group='reveal')`; obtain results through the store (`ensure(unit)`); build units with `render_key.unit_for(target, view, language)` using the unrestricted/steps-free definition; write nothing of its own (no private dict, no snapshots). Its 4-neighbour/1-process limits become producer-side policy, not a separate worker.

**Coordination ask for the reveal session:** build `BackgroundRenders` as "a producer into the scheduler with priority class P1", as above.

### 5.2 Work unit and what a render produces

For a unit the worker: builds the target (`preview_target.for_call` with the deck's preamble), calls a new `slide_preview.render_slide_to_pdf(..., steps=None, capture_snapshot=False, overlay=None)` entry through `preview_build.compile_cached` (reusable build, precompiled format), then in one go: reads the `.inputs.json` for the manifest, rasterises pages in chunks (5.7), moves PDF + PNGs into the store, writes the index row (one transaction), deletes the temp folder. Cancellation = the existing `CancelToken`; a cancelled job leaves latexmk's reusable state valid and is re-queued without counting as a failure.

### 5.3 What gets rendered, in what order

Candidate generation (the producer, cheap, runs only when idle):

1. Decks: from `deck_usage`, ordered by `last_opened` desc, then (tie-breaker/secondary signal for decks never opened on this machine) newest `decks/<deck>.tex` mtime; **all non-archived decks, in order of recency** (no cap; the cost is bounded because a deck whose manifests all still validate is never touched again, and by the disk budget). A setting "Recent decks to prepare" can limit it (default: all). Recency signals, in order: (a) `last_opened` on this machine; (b) **upcoming course sessions** from a **cached** course schedule only (never a network call from the scheduler; the course UI that already fetches it, `course_schedule.fetch_schedule`, keeps the copy it got with its fetch time; no cache = no boost): a deck whose next session is within 7 days ranks as if opened today; (c) decks changed through the synced folder (another machine) are noticed by the newest mtime of the deck file and its slides, ranking after (a)/(b) for decks never opened here. Archived decks excluded. The open deck is always rank 0, even if only just opened.
2. Per deck, version-major: **instructor** for the whole deck, then **during-course**, then **after-course** (the owner's order). A version is skipped for a call whose conditions exclude it (recorded as "absent", counted done). Unflagged slides (no version logic anywhere in the slide or its recorded dependency files) are rendered once and **aliased** to the other two views through the dedup in 4.1 (saves two thirds of the compiles for most slides); a slide's first full set of three renders validates the alias heuristic once, and a mismatch (different PDFs for unflagged slides) switches that slide to per-view renders and logs a warning.
3. Within a version: slides in deck order **starting at the last-viewed slide of that deck** (`deck_usage.last_slide_id`), wrapping around; for the open deck, outward from the current selection (distance order) so the next slides the user is likely to visit come first, and the currently selected view/language first.
4. Language: the deck's own language, plus the UI's last-used language for that deck; the other language of a multilingual deck only after everything else (low priority, optional setting).
5. Re-render of `FRESH_NUMBERING_DIFFERS` units last.
6. Units whose deck recently went stale en masse (preamble layer change) are processed in the same order; the count in the indicator jumps accordingly, which is honest.

Ties across decks resolve by deck rank; there is no round-robin between decks (finish deck 1's instructor set before deck 2's). Exception: the open deck's instructor version is finished before anything else, and a deck that has ≤ 5 outstanding units is finished before moving on.

**Per-deck override and archiving (owner decision).** Each deck has a setting "Background previews: automatic / off" (stored with the project's per-deck settings, `deck_settings`/`app_settings`, in the deck's settings dialog; default automatic). Off means the producer never submits units for that deck (its already stored objects stay until evicted). **Archiving a deck** removes the objects that only that deck uses (an object also used by a non-archived deck's unit stays; tracked by `deck_path_hint` references in the index) and exempts the deck from background rendering; unarchiving puts it back under "automatic" and it re-enters the recency order. Rendering a slide for an archived deck by hand still works (foreground path, not stored by the background rules).

### 5.4 All reveal steps

The unit is the **unrestricted** render: no `steps` in the call, `overlay=None`, so latexmk emits one page per overlay step. N pages = N steps, shown by the slider; the last page equals what the snapshot shows for an unrestricted call. This costs one run per unit regardless of N. Calls with a `\slidestep` restriction still show their restricted final page in the deck, but the stored unrestricted render is the superset; the Preview picks the restricted subset via the call (consistent with the reveal plan, which also notes a plain `\slide` target needs no second compile). Slides rendered through the foreground path for a *different* purpose (buffer text, region/element, presenter, `overlay=N`) never populate the store.

### 5.5 Batching several slides per LaTeX run (evaluated)

Options: (A) one run per unit (isolated); (B) one wrapper with many `\slide{}` calls, pages mapped back through the "slide id: XXX" footer (`slide_snapshot.slide_runs` / `capture_deck` already do exactly this for deck PDFs).

| | A: one per unit | B: batch per (deck, view, language) |
|---|---|---|
| Per-run overhead | latexmk start + format load + 2-3 passes; the precompiled preamble format already removes the preamble cost, which was ~half of a run | amortised once for the batch |
| Fidelity vs foreground render | identical by construction | **not guaranteed**: global counters, `\renewcommand`s and `\def`s in slide/snippet files, `\newcounter`, TikZ names, biblatex state, `\section` state, `framenumber` and `\pause` counters leak between slides; pages differ from what a single-slide Preview shows |
| Failure | isolated; failing slide recorded alone | one bad slide aborts or poisons the rest (`-f` keeps going but attribution is murky); would need bisecting reruns |
| Dependencies | per slide `.fls`, exact invalidation | one union manifest; a change to any image invalidates the whole batch's key unless we add a TeX-side per-slide `\typeout` attribution (fragile) |
| Cancellation/preemption | easy: kill, nothing lost but one slide | a half-finished batch loses minutes |
| Page mapping | trivial | footer id plus run-length; frames hidden by `conditionalslide` produce zero pages; "mult" slides etc. |

**Decision:** MVP and phases 1-3 use A. Phase 4 benchmarks B on the example project (`tools/preview_benchmark`): adopt only if wall time per slide drops by ≥ 2.5x **and** a validation corpus shows page-for-page pixel identity with A, and then only for deck slides without context flags, in sub-batches of ≤ 8 slides with a per-slide fall-back to A on any difference or error. A cheaper alternative with the same payoff: keep one long-lived `lualatex` + format process (a "server" that loads the format once and processes slide after slide via `\input`) - not feasible with latexmk's rerun logic, so not recommended.

### 5.6 Idle detection, preemption, concurrency, throttling

**Idle detector** (`idle_monitor.py`, Qt adapter around a Qt-free predicate): the scheduler may *start* a P2 job when all hold:

- no user input in the app for `IDLE_AFTER` = **30 s** (owner decision) (an application-wide event filter on `QApplication` recording `MouseMove/Button/KeyPress/Wheel/TouchBegin`; no OS-wide hooks). While the app window is inactive/minimised, the same 30 s apply (measured from the last input);
- no P0 request queued or running, no deck compile running (`compile_status`), no AI/Claude Code job streaming into the UI, no export (pptx/pdf) or "Update previews" in progress, and no modal dialog open;
- power: not on battery (default; "also on battery above 60 %" optional), not in battery-saver mode. Windows: `GetSystemPowerStatus` via `ctypes` (no new dependency); macOS: `pmset -g batt`; Linux: `/sys/class/power_supply`;
- CPU: system busy below 70 % averaged over 5 s (Windows `GetSystemTimes`, Linux `/proc/stat`, macOS `os.getloadavg`) - protects against competing with a video call or the owner's Slidemaster compile in a terminal;
- free disk above the guard (4.3);
- the first start-up delay (`~20 s` after the window shows, like the other maintenance tasks) has elapsed.

**Preemption.** On a P0 submit or a deck-compile start: cancel the running P2/P1 job immediately (`CancelToken.request_stop()` kills the latexmk process tree), re-queue it, serve P0. On mere input (mouse move, typing in the editor): do **not** kill a job that has been running < 20 s and is likely to finish; do not start another one until the app is quiet again. A running job that outlives 20 s of input activity is cancelled (kill when the user has clearly resumed). This avoids thrash while scrolling and yet frees the machine within seconds when it matters. Quit: cancel and wait (the existing `background.py` wait-at-quit hook pattern).

**Concurrency.** Default 1 LaTeX process; setting 1-3 ("Fast" profile 2). The latexmk child runs with **below-normal priority** (Windows `BELOW_NORMAL_PRIORITY_CLASS` creationflag next to `CREATE_NO_WINDOW`, POSIX `nice 10`), which needs a priority argument on `compiler.run_streamed`. Memory: each lualatex run 300-600 MB; refuse >1 process when free RAM < 4 GB. Never more than one *format build* at a time (existing lock). Rasterisation uses the existing child (one) - 5.7.

**Throttling / thermal.** A duty cycle: after a job that took `d` seconds sleep `0.25 d` (Normal) or `0.5 d` (Gentle), max 5 s; a sustained-run governor: after 10 minutes of continuous background work, rest 1 minute. Profiles: Gentle (1 proc, 50 % duty), Normal (1 proc, 25 %), Fast (2 procs, no duty). No OS thermal API is relied on; if the machine has a high-resolution throttle signal in future it plugs into the same predicate. Stop completely when the OS reports battery-saver, when `on battery` is true (default), or after 3 consecutive timeouts (something is wrong; surface it).

### 5.7 Raster in the background

The rasteriser child is a shared single process (`preview_raster_client._ask` under a global lock). Background rasterisation sends ≤ 4 pages per request so a foreground raster waits at most one small request (target ≤ 200 ms). Decided: background work uses its **own second raster child**, so the 4-page chunking is only a courtesy. All pages are rasterised at `STORE_WIDTH` 1280 (matching the 1280 display width already requested in `RenderService.work`); the 304x171 thumb is derived for the last page only when the snapshot-adoption path is on.

### 5.8 UI: "work remaining" and states

- **Status chip** in the main window's status area (single line, hidden when nothing to do): `Preparing previews - 37 left (open deck ready)`. States: *working* (spinner), *waiting* ("paused: you're active / on battery / compile running"), *done* (shown briefly, then hidden), *attention* ("3 slides can't be rendered"). Click opens a small popover: per deck progress bars in priority order with per-version counts, [Pause/Resume], [Render now] (override idle rules for this session), [Show failed slides], [Settings].
- **Slide list rows** get a tiny state dot only when not fresh (no dot = fresh): amber *outdated*, spinner *rendering*, red *failed*, hollow *not yet rendered*.
- **Preview pane / slider:** `FRESH` and `FRESH_NUMBERING_DIFFERS` show instantly with no spinner; `STALE` shows the previous image dimmed with "outdated - updating..." and a foreground render is queued; `MISSING` triggers the normal foreground render; `FAILED` shows the saved error tail with a "Retry" button. **A stale image is never presented as fresh**: only an exact `fast_key` + manifest match returns `FRESH`.
- Settings (Settings -> General, next to the render cleanup choice in `ui/dialogs/settings.py`): *Prepare previews in the background* (on/off, default **on**, owner decision), *Decks to prepare* (default all, in order of recency; optional cap), *Versions* (default all; instructor first), *Processes* (1-3, default 1), *Profile* (Gentle/Normal/Fast), *Only when plugged in* (default on), *Disk budget* (default 2 GB), *Keep for* (default 30 days), button *Clear background previews*.

---

## 6. Correctness

### 6.1 Never show stale as fresh

The only path to `FRESH` is `store.lookup(unit)`: compute `fast_key`, find the row, validate the manifest through `dep_hash.current_hash` (stat shortcut, hash on change). Any exception, missing dependency file, racy mtime, or `unstable` flag yields `STALE`/`MISSING`, never `FRESH`. The unsaved editor buffer is not a unit: the Preview's buffer render stays foreground-only and always wins visually over the stored saved-file render.

### 6.2 "Busy" predicate

One function `app_busy()` (compile running, AI running, export, update-all-previews, modal) shared by the idle monitor and by the reveal plan's 1.5 s timer rule, so both agree. Implementation: a small registry `busy.acquire(reason)/release()` used by the existing compile/AI/export code paths (each already has a start/stop hook), rather than polling six widgets.

### 6.3 Across restarts

The SQLite index and files on disk are the state; startup does: open index, drop `tmp/`, drop rows whose files vanished, schedule a stat-sweep (3.3) for the all decks after the start delay, rebuild `deck_usage` ranks. Interrupted jobs leave only `tmp/` debris. If the TeX distribution or the OS changed, `engine_fp` changes and the sweep simply finds everything stale.

### 6.4 Failures: no retry loops

- On failure keep `failures(fast_key, manifest_probe_sha)`, where `manifest_probe_sha` is the hash of the dependency files known from the failed attempt's `.fls` (latexmk `-f` still writes it) - i.e. the exact input state that failed. The unit is retried **only when** `fast_key` or any of those file hashes changed (the user fixed it), the TeX fingerprint changed, or the user clicks Retry.
- Failure classes: *deterministic* (TeX fatal error, `Render failed for ...`): no automatic retry for that input state; shown as FAILED with the log tail. *Transient* (timeout, killed by cancel/preemption, file lock, disk full, raster child died): backoff 5 min, 30 min, 3 h, then stop until input change or app restart, max 3 per key per session. A cancelled-by-preemption job is not a failure at all.
- Per-job timeout 180 s in the background (`TIMEOUT` is 300 s for the foreground); 3 consecutive timeouts anywhere pause the scheduler and show the "attention" chip.
- Failed units count as "done" for the progress indicator but are listed separately, so the chip can reach 0 left.

### 6.5 Sync folders and two machines

Covered in 1.4/3.3: shared immutable objects in the project plus a per-machine index (4.1); hash shortcut with racy-file deferral; no writes to shared locations except `decks/_slidemage_preview-*.tex` wrappers (owner approved) and, in phase 3, snapshots. If two machines use the same project simultaneously there is no shared mutable state: objects are write-once and the index is local. Conflicted copies (`file (1).tex`, `.conflict` files) are not slides/decks and are ignored by the scanners already; they are not manifest members unless TeX read them.

---

## 7. Phases (MVP first)

**Phase 0 - measurements (no feature code; 0.5 day).** On `example/` (never the owner's Slidemaster decks): per-slide wall time with the format cache warm/cold; share of time in latexmk start vs TeX; cost of the stat-sweep and hashing for a 100-slide deck; page counts; PNG sizes at 1280; can the wrapper live outside `decks/` (owner approved) and can `ctx.build_dir` point at a local dir without building the format twice; batching feasibility numbers (5.5). Output: numbers appended to this doc; decides defaults (idle seconds, duty cycle, budget).

**Phase 1 - key, hash cache, store (no scheduler, no UI; the base).** `dep_hash.py`, `render_key.py`, `render_store.py` (SQLite), `deck_usage.py` recording deck opens. `slide_preview` store entry (render unit -> store). Pane consults the store before rendering (instant display when valid) - already a user-visible win for any slide rendered earlier, including after restart.

**Phase 2 - MVP: idle sweep of the open deck, instructor view.** `scheduler` core, `idle_monitor` (input silence + app-busy + foreground preemption, 1 process, below-normal priority), producer for the open deck only, setting on/off (default on), minimal status chip with counts, failure memory with backoff. Success criteria 1-3 and 6 of section 7 apply to the open deck, instructor view.

**Phase 3 - the owner's full order.** All decks by recency, all versions with aliasing, last-viewed ordering, the popover with per-deck progress, AC-power/battery/CPU/disk predicates, duty-cycle profiles, store budget + eviction + Housekeeping entry, `FRESH_NUMBERING_DIFFERS` handling, snapshot key sidecar and optional adoption, wiring the reveal-slider P1 producer into the shared scheduler, default on from the start (owner decision).

**Phase 4 - optimisations (each behind a benchmark).** Batching (5.5), `QFileSystemWatcher` dirty marking, cross-deck sharing statistics, deck-context units when that plan has landed, optional second language, course-schedule boost.

### Files to add

- `src/slidemage/dep_hash.py` - stat-shortcut hash cache.
- `src/slidemage/render_key.py` - `Unit`, `fast_key`, manifest build/validate, `RENDER_SCHEMA`, `Freshness` enum.
- `src/slidemage/render_store.py` - SQLite index, paths, eviction, failures, deck usage.
- `src/slidemage/render_scheduler.py` - Qt-free queue/worker/priority/backoff/duty cycle.
- `src/slidemage/idle_monitor.py` (+ `power_status.py` for platform power/CPU) - the idle/power predicates.
- `src/slidemage/ui/workspace/render_status.py` - status chip and popover.
- Tests (below).

### Files to touch

- `preview_target.py` - `unit_for(...)`, steps-free key helper (shared with the reveal plan).
- `preview_requests.py` - make `RenderService` the P0 submitter into the scheduler; store lookup in `request`.
- `slide_preview.py`, `preview_build.py` - render-to-store entry (no snapshot, no overlay), return the inputs; optional priority argument; wrapper timestamp via file (decided).
- `compiler.py` (`run_streamed`/`latexmk_command`) - low-priority creation flag.
- `slide_snapshot.py` - key sidecar, `is_fresh` fallback (phase 3).
- `housekeeping.py`, `ui/dialogs/housekeeping.py`, `ui/dialogs/settings.py`, `app_settings` keys.
- `ui/workspace/preview_view.py` - states; `slide_list.py` - row dots; `window.py` - install the monitor, record deck opens/last slide; `maintenance.py` - start-up sweep after the delay.
- `project.py` - `cache_dir()` (local index) and `ctx.render_store_dir = .previews/render-store`; `.gitignore`.
- `CHANGELOG.md`, `README.md` (Settings text, privacy: nothing leaves the machine).

### Tests (pytest, `QT_QPA_PLATFORM=offscreen`, a fake render function; no real LaTeX unless marked)

- `test_dep_hash.py`: stat shortcut avoids reading; changed size/mtime triggers rehash; racy-file deferral; hash after sync-style mtime restore with different size; same content, new mtime -> same hash.
- `test_render_key.py`: each input in the 3.6 table flips validity or not as listed (slide, preamble layer in manifest, image, `.bib`, template, view, language, steps unchanged -> same key, frame number -> numbering state only); `RENDER_SCHEMA` guard over the wrapper helper sources; unstable render not trusted; CRLF/LF.
- `test_render_store.py`: persistence across a new `Store` instance (restart), corrupt index -> empty store, eviction order and protection, dedup of identical pages, crash debris in `tmp/`.
- `test_render_scheduler.py` (fake clock, fake renderer, fake idle predicate): priority classes, version-major order, last-viewed wrap-around, recent-deck order, preemption by a P0 submit re-queues without failure, backoff schedule, deterministic failure not retried until an input changes, 3 timeouts pause, concurrency cap, duty-cycle sleeps, pause on battery/busy.
- `test_idle_monitor_gui.py`: event filter timestamps input; predicate combinations; chip text states (offscreen Qt).
- `test_preview_requests.py` / `test_preview_target.py` additions: store hit skips render; stale shows previous image flagged; background render writes no snapshot and no `slidemage_preview_*` folder remains (`test_slide_preview_cleanup.py` style).
- `test_housekeeping_gui.py` addition: store size and clear.
- Integration (marked `latex`, skipped if no TeX): render two slides of `example/` through the real pipeline, edit a snippet, assert only the dependent slide goes stale.

### Success criteria (measured on the example project and, by the owner, on real use via a debug log line, never by compiling Slidemaster decks here)

1. **Freshness on open:** after the app has been idle ≥ 5 min, ≥ 95 % of the instructor-version units of the top-3 recent decks are `FRESH`, and ≥ 90 % of all versions of the open deck; measured as `fresh/total` logged on deck open.
2. **Zero false-fresh:** in a randomised edit test (edit slide, snippet, image, preamble layer, `.bib`, template) 0 stale renders are classified `FRESH`; every dependency change is detected within one stat-sweep.
3. **Foreground latency:** time from a user action to a started foreground render unaffected: p95 added delay ≤ 150 ms with the scheduler running (preemption works); no more than one background LaTeX process by default.
4. **Cost of checking:** `lookup` of a warm 100-slide deck in ≤ 30 ms; start-up stat-sweep of 5 decks in ≤ 300 ms.
5. **Footprint:** store ≤ budget; no `slidemage_preview_*` folders left behind by background work; no files created in the synced project by background work other than build state already created today.
6. **No loops:** a deliberately broken slide is rendered at most once per input state and appears in the chip's failure list.

---

## 8. Risks and open questions

### Risks

- **Wrappers and build caches in the synced folder.** Today each (slide, preamble) pair gets `decks/_slidemage_preview-<key>.tex` plus `.build/preview-cache/<key>/`; background rendering of hundreds of slides creates hundreds of files in a sync tree and uploads them. Mitigation (owner approved moving them out): wrapper text is stable once the timestamp is gone; background builds use a local `build_dir`/wrapper location outside the project; Phase 0 spikes how, and measures, before the default-on release.
- **Format duplication.** A second `build_dir` means a second precompiled preamble format per preamble; need to share the format dir while splitting the per-slide caches.
- **Hidden TeX state differences** between a background render and the foreground render (we use the same code path, one slide per run, so this is only an issue if batching is adopted).
- **Dependency blind spots:** negative dependencies and generated files; mitigated by the idle audit and a visible "Re-render all previews of this deck" action (the existing `rerender_deck()` can call into the store to invalidate).
- **Heat/battery on laptops:** conservative defaults (AC only, 1 process, below-normal priority, duty cycle) and visible pause reasons.
- **Complexity of the shared scheduler** with the reveal-slider branch: needs an agreed interface early (5.1); risk of two queues if both land independently.
- **Disk use** of PNGs if the owner has many large decks: budget + eviction + clear button.
- **SQLite on Windows with antivirus/indexers:** WAL files in the local cache dir (not the synced tree) avoid the worst of it; retry on `database is locked`.

### Decided by the owner (2026-10-18)

1. Default: on. 2. Wrappers/build caches for background renders may live outside the project (spike in Phase 0 decides how). 3. Footer timestamp deprecated and removed, version stays (prerequisite change, see 3.5). 4. Briefly wrong page numbers after inserting a slide are acceptable. 5. All decks in order of recency, all versions; unchanged decks are not touched again. 6. Pause on battery by default. Idle = 30 s.

**Decided (owner confirmation):** the footer-timestamp functionality is removed entirely: the template's `\SMFooterTimestampOverride`, the wrapper lines (`slide_preview`, `compiler.wrapper_text`), the toolbar checkbox and the `.timestamp` mechanism. Own small PR before Phase 2.

**Decided:** background work gets its own second rasteriser child (no lock contention with the foreground one). Defaults 2 GB / 30 days are kept, and the disk limit is a user setting (Settings -> General, "Disk limit for background previews"); "Remove temp files" does not touch the store, Housekeeping has its own "Clear background previews".

**Decided (round 3):** raw bytes are hashed (a line-ending flip by sync re-renders once). Store lives in the project, with a per-machine index (4.1). Course schedule: cached copy only. Reveal-slider renders always run first and never wait for a background job (5.1); the background version is the one kept. Per-deck override and archive rule (5.3). Renders from another machine are trusted as fresh (engine version + OS family + project-file hashes match); no local re-verification. The shared store has the same disk limit/quota as before (default 2 GB, user-settable).

### Still open

None at present; remaining decisions are measurements from Phase 0.
