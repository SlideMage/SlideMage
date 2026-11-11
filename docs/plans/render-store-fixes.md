# Plan: render store fixes, a simpler store, and fewer re-renders

Status: **steps 1 to 6 implemented, awaiting the owner's test** (written 2026-11-11 on `develop` at 8c90fa7a,
v0.16.5). Decisions D1 to D9 in section 2 carry a recommendation; the steps implement the recommendation unless the
owner changes it. Step 7 is split into 7a and 7b (2026-11-11); each needs its own go.

Steps 1 to 6 are one PR, one commit per step, v0.16.6 to v0.16.11 in step order; the full suite passes on step 6.
The Claude plugin's follow-up to step 5 (send WebP as `image/webp`) is `slidemage-plugin-claude` v1.0.2. Step 7 is
issue #170.

This follows [one-render-store.md](one-render-store.md) (implemented, v0.15.0) and
[render-store-cleanup.md](render-store-cleanup.md). It changes no design decision of those plans except where section
2 says so.

## 1. What was found

Reviewed on 2026-11-11: `render_store.py`, `render_key.py`, `render_lookup.py`, `render_evidence.py`, `dep_hash.py`,
`render_scheduler.py`, `background_renders.py`, `preview_requests.py`, `batch_render.py`, `preview_thumbnails.py`.
Measured on the owner's project (`~/Nextcloud/SlideMage`, 9 decks, 2,229 units, store
`~/.cache/slidemage/render-store/a34ec3c1f804f28c`, 1,873 renders, 769 MB).

### 1.1 Problems

| # | Problem | Evidence |
|---|---|---|
| P1 | The sweep's `work/` folder is outside the disk limit, the "Stored previews" figure and "Clear" | 2.5 GB beside 769 MB of renders: 1,656 build caches (2.0 GB, kept 14 days, `preview_build.UNUSED_DAYS`) and 44 precompiled formats (479 MB) |
| P2 | Stores of project folders that no longer exist are never removed | 22 store folders, 11 GB in all |
| P3 | `RenderStore.enforce_limit` deletes every render unused for 30 days outside the protected decks, even far under the limit. The planner's lookup never updates `last_used`, so an unopened deck is deleted and rendered again every 30 days | Reproduced with a fake clock: one render, 31 days, limit 10 GB, deleted |
| P4 | The planner scan costs about 6 s per pass, every 120 s (`REPLAN_SECONDS`) and on every `replan()` | Read-only pass timed 5.9 s. `slide_templates.framework_dirs()` is called 27,800 times per pass from `Resolver._resolve` (once per manifest entry, twice per unit), 8.1 of 13.2 s under the profiler |
| P5 | `texsets` and `failures` only grow | `texsets`: 388 rows, 47 referenced, 16 MB of a 29 MB index. `failures`: rows of keys no deck uses stay, every failed draft render adds one, and `store_failures_count` loads all rows on every `put` |
| P6 | Every read commits: `touch` runs UPDATE and commit in `page`, `pages`, `pdf_copy`, `thumbnail_path` | 200 `thumbnail_path` calls 0.54 s on an SSD, 200 `find` calls 0.017 s |
| P7 | `ingest_compile` skips a unit when `found.final`, which includes FAILED: a slide that failed in the sweep but compiled in its deck stays failed | Read in `background_renders.py:780`, not run |
| P8 | An index that was lost cannot be rebuilt: `put` keeps `tex_files` only in SQLite (`texsets`), so an adopted object fails `Resolver.tex_current` | Reproduced: fresh, then `renders` and `texsets` emptied, `rescan` adopts 1, lookup says stale |
| P9 | `HashCache.audit` has no caller, though the docstring of `dep_hash.py` relies on it | `grep "\.audit("` finds only a test |
| P10 | Nobody can tell why a sweep runs: no log line says how many units went stale or which check failed | The history of sweeps could not be reconstructed |
| P11 | The renders themselves are larger than they need to be | Section 1.4 |

### 1.2 What forces re-renders

All 1,873 renders in the store were made on 2026-11-11 between 10:12 and 12:02: one full rebuild takes about 1 h 50.

Every deck goes stale when:

| # | Trigger | Notes |
|---|---|---|
| R1 | A framework file's content changes. Seven framework files are in every manifest | Real: the output may change. `latex/SlideMage_base.tex` changed in 15 commits on 7 days since 2026-11-01 |
| R2 | The project's template changes (in 1,657 of 1,873 manifests) | Real |
| R3 | A file is added, removed or renamed anywhere in the project outside `slides/`, `media/`, `snippets/`, `pdf/`, `.temp/`, `snapshots/` (`render_evidence.search_inventory`, the "conservative" part) | Tested, fresh becomes stale: `sources/paper.pdf` (a chat attachment), `decks/NewDeck.tex`, `decks/archive/Old.tex`, `.migration-backups/b.zip`, `notes.txt`. **Broader than needed**, see below |
| R4 | A file is added or removed in the framework folder or an installed theme or citation folder | Kept as it is |
| R5 | `.latexmkrc`, `/etc/LatexMk`, or the binary of one of six tools changes (`configuration_state`); the six include `pdflatex`, `xelatex`, `bibtex`, which previews do not run | The unused three can go |
| R6 | The 30-day rule (P3) | |

Why R3 is broader than needed: the project's `.latexmkrc` puts the project root and the framework on `TEXINPUTS`
without subfolders (`.latexmkrc:90`), and TeX runs in `decks/`. TeX finds a file by name only at the top level of the
root, of `decks/` and of the framework and theme folders. A file deeper in the project is read only when a slide,
deck or template names its path, and then it is a recorded input, covered by the same-stem rule that
`slides/`, `media/` and `snippets/` use already.

One whole deck goes stale when:

| # | Trigger | Notes |
|---|---|---|
| R7 | Its preamble changes (`preview_target.preamble_sha`; only `\deckoutputfolder`, `\decktags` and the open-PDF comment are ignored) | Kept |
| R8 | A slide is inserted, removed or moved: every later slide is re-rendered in every view for its footer page number (`scan()`, the `numbering` list). 183 slides: up to about 549 renders for one slide inserted at the front | D3 |
| R9 | `background_renders.deck_units` numbers a unit by its call position, the slide list by `deck_outline.resolve_slots(...).frame_number`. After a repeated `\slidestep` call or a hidden call they differ (36 units of `slidemage-manual`), so the Preview and the sweep replace each other's render | Bug |

### 1.3 Redundant and unused code

- `BackgroundRenderer._drop_stale` deletes a subset of what `RenderStore.put` already deletes (the same label's other
  keys, except `current_keys`). With it: the `label` parameter of `RenderStore.drop_stale`, `_CurrentKeys.labels`.
- `origin`: the `renders.origin` column, the meta field, `ORIGIN_BACKGROUND`, `ORIGIN_REVEAL`, `ORIGIN_COMPILE`, the
  parameter of `put` and `_store_render`. Nothing reads it.
- `renders.name` and `renders.fast_key` are equal in all 1,873 rows; a record carries both `name` and `key`.
  `RenderStore.root` equals `local_dir`; `lock` equals `_lock`.
- "Remove the folder and delete the row" is written five times (`delete`, `drop_deck`, `drop_stale`, `enforce_limit`,
  `rescan`).
- `last_tries` is a table of its own for one fact about a failure.
- Unused in `src`: `BackgroundRenderer._outstanding`; `RenderScheduler.user_active`, `grace`, `queued_keys`,
  `running_keys`; `PRIORITY_NAMES`; `P_NEIGHBOURS`; a second `ALL_PAGES` (`background_renders.py`, `batch_render.py`).
- In `scan()`: `own = found.usable and found.record is not None and found.record.get("key") == found.key` equals
  `found.usable`.
- `RenderService` and `BackgroundRenderer` construct each other, and `RenderService.request` uses nine private
  members of the renderer: `_store_render`, `_rasterise`, `_render_in_deck`, `_render`, `_current`, `_failure_keys`,
  `_failure_slides`, `_last_try`, `_working_lock`.

### 1.4 What the store's bytes are

Of 775 MB: page images (PNG, 1920 px wide) 444 MB, 57 %, 232 KB each; `slide.pdf` 308 MB, 40 %, 165 KB each;
thumbnails 17 MB; `meta.json` 6 MB. The project has 1.02 pages per render.

Tried on 80 stored renders (Pillow, one 1920 x 1080 page each):

| Encoding | Page size | Encode | Decode |
|---|---|---|---|
| PNG as stored | 241 KB | | 19 ms |
| WebP, quality 90 | 93 KB | 134 ms | 20 ms |
| WebP lossless | 124 KB | 330 ms | 22 ms |
| PNG at maximum compression | 233 KB | 295 ms | |
| Thumbnail: PNG as stored, WebP quality 85 | 9.4 KB, 2.4 KB | 2 ms | |

What does not help: identical pages across views (2.2 % of the page bytes); recompressing the PDFs (2 %: 86 % of a
PDF is the slide's own pictures, and none repeats across slides); 1280 px pages (22 %, at the cost of a blurrier
Preview). The PDF stays: Open PDF, the readability check and the rendered comparison take it from a store hit and
would otherwise render the slide again.

## 2. Decisions

| # | Question | Recommendation (what the steps implement) |
|---|---|---|
| D1 | Narrow R3 to what TeX can see? | Yes. Only the top level of the project root and of `decks/` stays conservative; deeper project folders follow the same-stem rule. Other search roots are unchanged |
| D2 | Go further at those two top levels, so a new deck re-renders nothing? | Yes. There, only watched names stay conservative: `SlideMage_*`, `*.bib`, `.latexmkrc`, `latexmkrc`. These cover the framework's four project probes (`SlideMage_layout_*.tex`, `SlideMage_citation_*.tex`, `SlideMage_project_macros.tex`, the `.bib` fallback). Every other name follows the same-stem rule. `tests/test_framework_probes.py` guards the list |
| D3 | Re-render for a page number alone (R8)? | No. A render that differs only in its footer number counts as finished for the sweep. A deck compile, an edit or a forced render stores the right number. This extends render-store-cleanup.md D3 from slides called twice to all slides |
| D4 | After R1 or R2, sweep only the open and recent decks? | **Not planned.** It breaks "every deck is prepared". Decide after step 1's log shows how often R1 and R2 occur for a normal user |
| D5 | The 30-day rule (P3)? | Remove it, with the `bg_previews_keep_days` setting. Stale renders are removed by `put` and `drop_stale` since v0.14.2; orphans and the disk limit stay |
| D6 | The work folder (P1)? | Keep sweep build caches 2 days instead of 14, and let "Clear" remove them. The size shown stays the renders' |
| D7 | A lost index (P8)? | Do not adopt. `rescan` deletes object folders the index does not know. This shortens `rescan` and removes a path that never gave a current render |
| D9 | Smaller page images (P11)? | **Decided 2026-11-11: lossless WebP** for pages and thumbnails. About 216 MB less on the owner's project (28 %), with the rasteriser's exact pixels. The alternative was WebP at quality 90 (about 37 %, not exact) |
| D8 | `HashCache.audit` (P9)? | Delete it and correct the docstring: the strict read for the selected slide (`verify=True`) is the check that exists |

## 3. Rules for every step

1. One branch per step from the current `develop`, one PR per step, with its own `VERSION_NUMBER` bump and CHANGELOG
   entry (`src/slidemage/version.py`, `src/slidemage/CHANGELOG.md`; read `VERSION_NUMBER` on `develop` first). Push to
   the owner's fork, never to `origin`; open the PR only after the owner tested the step.
2. **Never bump `RENDER_SCHEMA` or `STORE_FORMAT`.** Either one re-renders everything. Step 6 is the only step that
   may make stored renders stale, once.
3. Simplicity: delete first, one way per job, no new setting, layer, option or test-only hook beyond what the step
   names, no compatibility code except the one-time index migration of step 2. Check each diff for leftovers and end
   each step with a simplify pass. Report what was deleted and the diff stat.
4. Tests: one test per rule the step exists for, through the public function; at most the number the step names.
   Delete tests of removed code in the same step.
5. Run tests one suite at a time, capped:
   `systemd-run --user --scope -p MemoryMax=10G -p MemorySwapMax=0 env PYTHONPATH=src QT_QPA_PLATFORM=offscreen
   .venv/bin/python -m pytest -n 12 -q -p no:cacheprovider --rootdir=. tests`. Check `pgrep -af pytest` before a rerun.
   Known unrelated failures: the zip-fixture tests in `test_citations.py` and `test_theme_sources.py`.
6. Before removing or renaming a name, grep the plugin repositories (`~/github/slidemage-plugin-*`) and `tools/` for
   it. A name a plugin uses is kept or the plugin is changed in the same step.
7. Do not open the owner's real store or project for writing in a test or a measurement.

## 4. Steps

### Step 1: say why, and a cheaper scan (P4, P10)

No change to what is rendered.

- `render_evidence.ValidationPass`: add `framework_dirs(root)`, a memo of `slide_templates.framework_dirs(root)` for
  the pass, like `inventory` and `configuration`.
- `render_key.Resolver`: `_resolve(kind, rel, frameworks=None)` uses the given list. `lookup` takes the list once from
  its `validation` and passes it to its own `_resolve` calls and to `manifest_current`. Other callers stay as they are.
- `Resolver.lookup` says which check failed: `Lookup` gets a field `why: str = ""`, set for STALE and MISSING to
  `"inventory"`, `"file <rel>"` (the first manifest entry that changed), `"tex files"` or `"no render"`. For that,
  `manifest_current` returns the first changed `rel` or `None` in place of a bool; adjust its three callers.
- `BackgroundRenderer.scan()`: count `why` over the units that are not fresh, and log one INFO line on
  `slidemage.background` when the counts differ from the previous scan's: seconds the scan took, units, fresh,
  failed, and the five most frequent reasons with their counts.
- `BackgroundRenderer._work`: one `ValidationPass` for the job's lookups, not one per unit.

Tests (2): a stale lookup names the changed file; a scan after a file change logs the reason with its count.

Check: time `scan()` on a copy of a real project before and after (the log line carries the seconds). Expected:
about 6 s to about 2.5 s for 2,229 units.

### Step 2: a smaller store, same behaviour (1.3)

- Remove `BackgroundRenderer._drop_stale`, its call in `_store_render`, the `label` parameter of
  `RenderStore.drop_stale`, and `_CurrentKeys.labels`.
- Remove `origin`: `put(key, pdf, pages, meta, *, decks=())`, `_store_render(unit, pdf, pages, manifest, evidence)`,
  the three constants and their imports.
- One key name: the table's primary key column is `key`; drop `fast_key` and its index; records carry `key` and
  `dir`, not `name`. One attribute each: `RenderStore.root` (drop `local_dir`, keep the constructor argument's name)
  and `RenderStore.lock` (drop `_lock`).
- One private `_remove(key)` (folder and row, no commit) used by `delete`, `drop_deck`, `drop_stale`, `enforce_limit`
  and `rescan`; each commits once at its end.
- `failures` gets a column `last_try REAL`; drop the `last_tries` table. `tried_last` and `note_last_try` keep their
  signatures.
- The one-time index migration, in `RenderStore.__init__` after `executescript(SCHEMA)`: when
  `PRAGMA table_info(renders)` still lists `origin`, run `DROP INDEX IF EXISTS renders_key`, `ALTER TABLE renders DROP
  COLUMN origin`, `ALTER TABLE renders DROP COLUMN fast_key`, `ALTER TABLE renders RENAME COLUMN name TO key`,
  `ALTER TABLE failures ADD COLUMN last_try REAL`, `DROP TABLE IF EXISTS last_tries`. `STORE_FORMAT` stays 2. Old
  `meta.json` files keep their `origin` entry; nothing reads it.
- Delete the unused names of 1.3 (with the tests that only test them) and simplify `own` in `scan()`. Keep one
  `ALL_PAGES`, in `batch_render.py`; `reveal_steps.py` imports it from there.

Tests (1): a store whose index has the old columns opens, and a render stored before is found by its key. Existing
tests are adjusted, not multiplied.

Check: open a copy of a v0.16.5 store folder with the new code; `count()` and one `find` agree with before.

### Step 3: upkeep that does not undo the sweep's work (P3, P5, P6, P7, P8, P9)

- D5: `enforce_limit` loses `keep_days` and rank 1. Order: orphans, then least recently used outside the protected
  decks while over the limit, the protected ones only above twice the limit. Remove `DEFAULT_KEEP_DAYS`,
  `KEEP_DAYS_KEY` and the setting's control if the Settings dialog has one.
- P6: `touch` writes at most once an hour per key: keep `{key: time}` in memory and skip the UPDATE within the hour.
- P5: `RenderStore.prune_index(keep_failures, before)` deletes failures whose key is not in `keep_failures` and whose
  `first_at` is before `before`, and `texsets` rows no render refers to
  (`digest NOT IN (SELECT json_extract(meta, '$.tex_digest') FROM renders)`). `BackgroundRenderer._clear_stale` calls
  it with `current.keys` and `current.at` when every deck was read in full (`all_clean`).
- P7: in `ingest_compile`, skip only when `found.state is Freshness.FRESH`.
- D7: `rescan` no longer adopts. It clears `tmp/`, deletes rows whose object is gone or incomplete, and deletes object
  folders without a row. Keep the per-shard locking and `should_stop`. Its return value (objects adopted) goes, with
  its use.
- D8: delete `HashCache.audit` and its test; correct the module docstring of `dep_hash.py`.

Tests (4): a render unused for 31 days in an unprotected deck under the limit stays; a compile is imported for a unit
with a stored failure and the failure is gone; a failure of a key no deck uses and an unreferenced `texsets` row are
gone after a clean scan; `rescan` deletes a folder the index does not know.

### Step 4: the work folder and forgotten stores (P1, P2)

- D6: `preview_build.prune_unused` takes the age in days; the background workspace passes 2, the project keeps
  `UNUSED_DAYS`. Find what removes `work/build/preview-formats/*` (`preview_format.py`); if nothing does, remove a
  format folder unused for the same 2 days under the same guard.
- "Clear" (`ui/dialogs/settings.py`, `_clear_background`): after `store.clear()`, prune the workspace with age 0.
  `cleanup_guard` skips builds that are running.
- P2: `RenderStore.__init__` writes the project's folder to `<store>/project.txt`. A function in `housekeeping.py`,
  run with the start-up maintenance that calls `sweep_old_renders` (`ui/workspace/maintenance.py`), deletes sibling
  stores whose `index.sqlite` is older than 30 days and whose `project.txt` is missing or names a folder that does
  not exist. Never the open project's store.

Tests (2): a workspace cache older than 2 days is pruned and a newer one stays; a store of a missing folder with an
old index is deleted while one with a recent index stays.

Check on the owner's machine after two days of use: `du -sh ~/.cache/slidemage/render-store/*/work`.

### Step 5: smaller page images (P11, D9)

No stored render goes stale: objects stored before keep their PNG files and are read as they are. There is no
conversion of existing objects; they are replaced as their slides change.

- `RenderStore.put` writes each page as `pNNN.webp` and the thumbnail as `thumb.webp`, both lossless (Pillow,
  `lossless=True`, the default method), from the PNG bytes the rasteriser gives it. Encode before taking the store lock, where
  `thumbnail_png` runs today. `render_evidence.thumbnail_png` becomes the one function that makes the thumbnail's
  bytes in the stored format.
- Readers take file names from the record, not from a pattern: `page`, `pages` and `thumbnail_path` look up the
  page and thumbnail names in `meta["files"]`, so a record lists either `.png` or `.webp` files. `THUMB_NAME` goes.
  `_checked_meta` already compares whatever `files` lists.
- Check every consumer of `store.page(`, `store.pages(` and `thumbnail_path(` for an assumption that the bytes are
  PNG: `preview_requests.py` (the cached hit), `preview_pages.py`, `appendix_toc.py`, `preview_thumbnails.py`,
  `ui/dialogs/add_slide.py`, `ui/workspace/preview_view.py`, `ai/tools/slidemage.py`. Qt and Pillow detect the format
  from the bytes. Where a media type is sent with the image (the AI tools), send the right one, taken from the
  bytes' signature; do not convert back to PNG.
- A fresh render's pane image is unchanged: the pane gets the raw pixels before `put`. After `put`, the last page
  shown comes from the store (`pages[-1]` in `RenderService.request`): return the stored bytes there, so the Preview
  shows after a render what it shows on the next hit.
- Packaging keeps Qt's `qwebp` plugin already (`packaging/slidemage_presenter.spec`, `_KEEP_IMAGEFORMATS`). Check the
  other spec files, and Pillow's WebP support in the packaged build.

Tests (2): a stored render's pages are WebP and decode to the same pixels as the PNG given to `put`; a record stored with PNG
files is still read by `page`, `pages` and `thumbnail_path`.

Check: the store's size per render before and after on a copy of a real project (expected about half the page bytes,
120 KB less per page); a packaged Windows build shows thumbnails and the Preview from the store; one test page decodes to the same pixels as its PNG.

### Step 6: fewer re-renders (R3, R5, R8, R9)

This step changes the evidence stored with every render, so **every stored render goes stale once** and the store
rebuilds (about 2 hours on the owner's project). All four changes ship in one PR for that reason. Say so in the
CHANGELOG entry.

- D1 and D2, in `render_evidence.search_inventory`: for the project root, a file goes to the conservative list only
  when it is at the top level of the root or of `decks/` **and** its name is watched (`SlideMage_*`, `*.bib`,
  `.latexmkrc`, `latexmkrc`). Every other project file goes to `stems`, as files under `slides/`, `media/` and
  `snippets/` do now; `media/alt-text.csv` and `media/alt-text.json` stay conservative. Other search roots (framework,
  themes, citation formats, `TEXINPUTS`) are unchanged. The watched patterns are one constant beside
  `_SKIP_DIRS`, with a comment naming the four probes. Extend `tests/test_framework_probes.py` so that a probe for a
  project file whose name the constant does not match fails the test.
- R5: `configuration_state` lists only the tools a preview runs: `latexmk`, `lualatex`, `biber`. Check
  `preview_build` for the engine actually started before removing the others.
- R9: `background_renders.deck_units` takes each unit's `frame_number` from
  `deck_outline.resolve_slots(ctx, deck, view, language, links=links)` (the row of the same position), as
  `batch_render.plan_deck` and the slide list do, and passes it to `preview_target.for_call(..., frame_number=...)`.
- D3: in `scan()`, a unit that is usable but out of step in its number counts as fresh and is not planned. Remove the
  `numbering` list, `key_count`, and the `1000 +` rank. `ingest_compile` (step 3) and foreground renders still replace
  such a render, because only FRESH is skipped there. Update the docstrings of `scan()` and `render_key.py` that
  describe "refreshed last".

Tests (4): a new file in `sources/`, a new deck in `decks/` and a file in `decks/archive/` leave a render fresh,
while a new `SlideMage_project_macros.tex` in the root and a same-stem file make it stale (one parametrised test);
`deck_units` gives the slide list's frame numbers after a repeated `\slidestep` call; a scan after a slide is
inserted at the front of a deck plans only the new slide; the extended probe test.

Check on a copy of the real project, with step 1's log: attach a file to the chat, create a deck, insert a slide
at the front of a deck. None of the three starts a sweep of more than the new units.

### Step 7: the render service and the sweep stop reaching into each other (needs the owner's go)

Today `RenderService` and `BackgroundRenderer` construct each other. `RenderService.request` uses nine private
members of the renderer (`_store_render`, `_rasterise`, `_render_in_deck`, `_render`, `_current`, `_failure_keys`,
`_failure_slides`, `_last_try`, `_working_lock`), it decides the sweep's retry rule for failed units and it writes
the sweep's failure sets. Other code reaches the store through the private `service._renderer(ctx)`.

**When:** only after steps 1 to 6 are merged and have run on the owner's machine for a few days. Behaviour that
shows up in that test must be traced to steps 1 to 6 alone, not mixed with a refactor of the same code.

Decided 2026-11-11: two parts, each with its own go and PR. Part 7a removes the cross-module writes and the private
access at low risk. Part 7b moves code between the classes and carries most of the risk; it is done only if, after
7a, the coupling that is left still gets in the way.

#### Step 7a: public accessors and the sweep's own retry rule

Goal: no module outside `background_renders.py` uses a private member of `BackgroundRenderer`, and `request` no
longer writes the sweep's state. The render code paths stay where they are.

- `RenderService` gets `store` and `resolver` (read-only, through the renderer it already holds). Callers of
  `service._renderer(ctx).resolver` and `.store` (`batch_render.py`, `preview_view.py`, the AI tools, plugins; grep
  `~/github/slidemage-plugin-*`) use them. Plugins that use the old path are changed in the same step.
- The sweep's rule for a failed unit (`_last_try`, `tried_last`, `note_last_try`) moves out of `request` into
  `BackgroundRenderer._work`, which decides before it asks for the render.
- `request` reports a recorded failure through one callback the renderer sets (`on_failure(unit, key)`), in place of
  writing `_failure_keys` and `_failure_slides` itself.
- What `request` still calls on the renderer (`_store_render`, `_rasterise`, `_render_in_deck`, `_render`) becomes
  public under the same names without the underscore, unchanged otherwise. That marks the interface 7b would move.

No new tests; the existing preview, batch and background suites must pass unchanged in what they assert. One
Codex task.

#### Step 7b: the render service owns publication (only if still worth it after 7a)

Goal: neither class constructs the other.

- `RenderService(ctx, store)` owns the store, the `HashCache`, the `Resolver`, the raster client, and what
  `store_render`, `rasterise` and `render_in_deck` (after 7a) do today, as its own methods. A service made without a
  store opens and closes its own (today's `_owns_background`).
- `BackgroundRenderer(ctx, renders, ...)` takes the service and reads `renders.store` and `renders.resolver`. It keeps
  planning, progress and the failure sets.

No new tests; the same suites must pass unchanged in what they assert. Decide after 7a: if what is left is a handful
of public calls in one place, 7b is not needed.

## 5. Done when

- Steps 1 to 6 are merged and the owner's store shows, in step 1's log, no full sweep after a chat attachment, a new
  deck or an inserted slide.
- `render_store.py` has one name per thing (1.3) and no caller-specific rule; `work/` stays below the renders' size.
- The full suite and Ruff pass after each step; the plugin preview suites pass after steps 2, 5, 7a and 7b.
- After 7a, no module outside `background_renders.py` uses a private member of `BackgroundRenderer`.
