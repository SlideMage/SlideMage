# Busy and progress indicators: findings and plan

Status: plan only (no code). Base: develop @ 20d1375 (v0.14.0).

Goal from the owner: an operation that makes SlideMage look frozen gets at least a busy animation, and a
determinate progress bar where the number of steps is known. The trigger case is **Settings → Background previews →
Clear background previews**, which takes several seconds on the GUI thread with a large store.

The rule this plan applies everywhere: work that can take more than about **0.5 s** runs on a worker thread, and
the GUI shows that it is working. Work that is quicker stays where it is; an indicator that flashes for 100 ms is
noise.

---

## 1. Findings

### 1.1 The trigger case: clearing the background previews

`GeneralTab._clear_background` (`ui/dialogs/settings.py:248`) asks for confirmation, then calls
`controller.store.clear()` on the GUI thread. `RenderStore.clear()` (`render_store.py:294`) does
`shutil.rmtree(objects/)` and `shutil.rmtree(tmp/)` **while holding the store's lock**, then deletes the index rows.

* A store holds one folder per render with `slide.pdf`, one `pNNN.png` per reveal step, `thumb.png` and
  `meta.json`: five or more files per object. The code's own note on `rescan()` speaks of 6000 folders, so a full
  store is 30 000+ files; on Windows (Defender scans every delete) `rmtree` takes several seconds to tens of seconds.
* Because the lock is held for the whole `rmtree`, the background renderer's threads, the Preview's and slide list's
  store lookups, and `_background_size()` (which calls `count()` and `total_bytes()`, both under the lock) all wait
  too. So simply moving `clear()` to a worker is **not enough**: the Settings caption refresh right after it would
  block on the lock again.

The fix is two-part: make `clear()` itself quick under the lock (rename `objects/` and `tmp/` to a `trash-<uuid>/`
folder beside them, which is one rename each, delete the rows, commit), then delete the trash folder on a worker
with no lock held. A trash folder left behind by a crash is removed by the next `rescan()` (which already clears
`tmp/` at its start). Then the GUI is blocked for milliseconds, not seconds, and the busy indicator covers only the
background delete (so that the "MB stored" caption and a second click make sense while it runs).

`RenderStore.drop_deck()` (`render_store.py:274`), called on the GUI thread when a deck is archived
(`deck_actions.do_archive_deck` → `background.deck_archived` → `renderer.deck_archived`), has the same shape: an
`rmtree` per render only that deck used, all under the lock. Same fix (rename into trash under the lock, delete
later).

### 1.2 Survey: operations on the GUI thread that can block

Times are estimates from the code (file counts, network, LaTeX), on a project of the size of the owner's (hundreds
of slides, a synced folder, Windows). Step 0 of every row is to confirm them with `timing.event` (section 3, step 9).

"Busy" means an indeterminate indicator (the number of steps is not known, or there is only one step);
"Progress" means a determinate bar with "n of m".

| Operation | Where it runs now | Can take | Needs | Notes |
|---|---|---|---|---|
| **Clear background previews** | GUI thread, store lock held (`settings.py:248` → `render_store.clear`) | seconds to tens of seconds | Busy (after the rename, the delete is one step) | the trigger case, 1.1 |
| Archive a deck: drop its renders | GUI thread, store lock held (`renderer.deck_archived` → `store.drop_deck`) | up to seconds for a large deck | none after the fix (delete moves to a worker) | same fix as 1.1 |
| Project compatibility **Update project** | GUI thread (`maintenance.compat_update` → `compat.run_update`) | seconds: every migration reads and rewrites the files it touches, and backs each up first | Progress (files of the plan) | the project must not be edited meanwhile: a modal busy sheet, not just an inline one |
| `compat.evaluate` before the sheet (`on_project_compat`, the start-up check) | GUI thread | 0.2-1 s: regex detectors over every slide and deck | Busy, if measured > 0.5 s | measure first |
| Framework / manual copies: **plan** (`check_bundled_copies`, 2.5 s after start) | GUI thread, from a timer | 0.5-2 s: hashes every framework and manual file of the app and the project | none: move to a worker, no indicator (nobody is waiting) | a start-up hitch, not a frozen action |
| Framework / manual copies: **Update / Add the manual** (`apply_bundled_parts` → `bundled_copies.apply_update`) | GUI thread | seconds: copies the manual's slides and images (hundreds of files) into a synced folder, with backups | Progress (files) | modal busy sheet: decks are reloaded afterwards |
| Housekeeping: **Remove temp files** (`maintenance.remove_temp_files` → `housekeeping.remove_temp_files`) | GUI thread | seconds: `.build/` holds the preview build caches, thousands of files | Progress (items found) | the found list is known before deleting |
| Housekeeping: **Empty pdf/** (`empty_pdf_folder` → `housekeeping.delete_files`) | GUI thread | usually < 0.5 s; seconds with many large PDFs in a synced folder | Progress (files) | cheap to include with the one above |
| Housekeeping: **Sync translation links** (`on_sync_translation_links` → `slide_rename.regenerate_translation_links`) | GUI thread ("pure text scanning … runs synchronously") | 0.5-2 s: reads and may rewrite every slide | Busy (or Progress per slide, if the function gets a callback) | |
| Housekeeping sheet opening: the scan for unused media and slides (`HousekeepingSheet.refresh` → `unused_content.find_unused_*`) | GUI thread, before the sheet shows | 0.5-2 s: reads every deck and slide | Busy inside the sheet (rows show "Counting…") | the sheet should open at once |
| Housekeeping: **Archive unused content** | worker (`_ArchiveWorker`, a QThread) | seconds | Progress (files, known) | already off the GUI thread; only the bar is missing |
| **Import PPTX/ODP** (`ImportPresentationSheet._on_import` → `slide_import.import_presentation`) | GUI thread | seconds: unzips, extracts media, writes one slide file per source slide | Progress (slides, known after extraction) | |
| **Export LaTeX** (`compile_actions.export_latex` → `latex_export.export_deck`) | GUI thread ("copying files is quick") | quick for a small deck; seconds for a deck with many media in a synced folder | Progress (files) | low priority |
| Theme / citation format **install** from an offer (`maintenance.offer_theme_update`, `offer_citation_update`, `PluginsTab._install_fetched`) and from a file (`install_theme_file`, `install_file`) | GUI thread (the download itself is already on a `Job`) | < 0.5 s to 1 s: unpack and check a package | Busy | the plugin page already says "Reading the releases…" for the fetch |
| Plugin install / update from the catalogue | worker (`settings_plugins.Job`) | seconds (download) | Busy | done: caption + disabled buttons; switch to the shared component (step 2) |
| **Check for updates** (menu) (`maintenance.on_check_for_updates`) | GUI thread with a wait cursor | up to the network timeout | Busy | the only `setOverrideCursor` user: the window is frozen meanwhile |
| **Download and install an update** (`download_and_install_update`) | GUI thread, `QProgressDialog` kept alive with `processEvents()` | tens of seconds | Progress (bytes) | works, but `processEvents()` re-enters the event loop: a click on the window can start anything while the download runs |
| Open project / **reload decks** (`WorkspaceWindow.reload_decks` → `scan_decks`) | GUI thread; at start the splash covers it | 0.2-1 s per reload | measure first | every save of deck settings, an archive, a duplicate reloads |
| Update previews: the scan before the run (`compile_actions` → `update_all_previews.needed_slides_by_template`) | GUI thread, before the compile run starts | 0.2-1 s | measure first | the run itself has the compile progress card |
| Images page **Rescan** (`ImagesPage._on_rescan` → `reload`) | GUI thread | 0.5-2 s: reads every slide's images and descriptions | Busy, if measured > 0.5 s | measure first |

### 1.3 Already fine (no change)

| Operation | How it gives feedback |
|---|---|
| Deck compiles, snapshots, Update previews, PPTX export, multi-deck runs | `compile_controller` worker + the task card and job panel (`job_panel.py`, `compile_progress.py`) |
| The render store's **rescan** at start | runs on the renderer's thread (`background_renders.py:461`); Settings says "Counting…" while `renderer.rescanning` |
| Start-up checks: app, plugin, theme and citation updates; the plugin offer | `threading.Thread` + result on the GUI thread; nobody waits for them |
| Old render sweep | daemon thread (`maintenance.sweep_old_renders`) |
| AI jobs (chat, AI fix, translation in Add slide, image drafts, readability) | their own QThreads with a `QProgressBar` or the assistant's status |
| Ollama model update / delete (plugin) | `host.run_in_background_with_progress` + a `QProgressBar` (section 2.1) |

## 2. The shared pattern

### 2.1 What exists

* **`ui/background.py`**: `start_detached(thread, on_done)` keeps a QThread alive until it has ended (a sheet that
  closes does not destroy a running thread; the app waits for it at quit), `stop_worker` asks one to stop.
* **`plugins/host.py:338` `run_in_background_with_progress(work, progress, done)`**, added for the Ollama plugin's
  model updates (slidemage-plugin-ollama 1.0.2, "a progress bar and step text while a model updates or is
  deleted"): `work(report)` runs on a QThread; `report(value)` is worker-safe and queues `progress(value)` on the
  GUI thread through a signal; `done(result, error)` runs on the GUI thread afterwards, even if the widget that
  asked is gone. `run_in_background(work, done)` is the same without progress. Both live inside the plugin host,
  so the core cannot use them.
* **The Ollama plugin's UI** (`ollama/settings.py`): a `Progress(text, fraction | None)` value; `_show_progress`
  sets a caption and a `QProgressBar` (range 0-0 when `fraction` is None, i.e. indeterminate; 0-100 otherwise),
  hidden when idle. Several models: "(model 2 of 3)" in the text.
* **Core copies of the same idea**: `settings_plugins.Job` (a QThread with `done(result, error)`), the `_Worker`
  classes in `compile_controller`, `readability_panel`, `compare_rendered`, `ai_fix`, `_ArchiveWorker` in
  Housekeeping, `_SearchWorker` in the palette. Each re-declares the same few lines.
* **Kit**: `Toast` (transient message with actions), `ModalSheet` (title, tabs, button row), `caption()`, and the
  kit's `QProgressBar` style (`kit_qss.py:475`, plus the job panel's `JOB_BAR`). There is no spinner or busy widget
  in the kit.
* **`busy.py`**: `working(reason)` tells the idle gate and the reveal slider that the machine is busy (so background
  rendering pauses). Not a UI indicator, but a long operation should hold it.

### 2.2 What to add

**`slidemage/progress.py`** (free of Qt): `Progress(text: str, fraction: float | None = None)`, with a helper
`Progress.step(n, total, text)` that makes "text (n of total)" and the fraction. The same shape as the Ollama
plugin's own `Progress`, so the plugin can switch to it later without changing what it shows.

**`ui/background.py`** gains the two runners, moved from the plugin host:

```python
def run(work, done, *, busy_reason: str | None = None) -> None
def run_with_progress(work, progress, done, *, busy_reason: str | None = None) -> None
```

Same contract as the host's (worker must not touch widgets; `report` is worker-safe; `progress` and `done` on the
GUI thread; callbacks may outlive the widget). `busy_reason` holds `busy.working(reason)` for the work's duration.
`PluginHost.run_in_background*` become one-line calls of these (the plugin API does not change).
`settings_plugins.Job` and `_ArchiveWorker` go; the other workers can follow when their files are touched anyway.

**Kit `BusyIndicator`** (`ui/kit/widgets.py`): a small inline widget, a thin kit-styled bar plus a caption, made to
sit under the button that started the work.

* `start(text)`: indeterminate. `show_progress(Progress)`: determinate when it has a fraction. `finish()`: hides it.
* It appears only after **400 ms** (a `QTimer`), so quick runs never flash; once shown it stays at least 300 ms.
* Announces the text for screen readers (`announce()`).
* Shown in the kit gallery (`ui/kit/gallery.py`).

**Kit `BusySheet`** (a `ModalSheet` subclass): for work during which the project must not change (Update project,
Add the manual, Import). Title, one `BusyIndicator`, optional Cancel (only when the work can stop between steps; a
`threading.Event` passed to the work). Window-modal, no close button while running; it closes itself in `done` and
the result is told in a toast or the existing message box. It replaces the updater's `QProgressDialog` and its
`processEvents()` loop.

**Rules for a caller** (written into the `ui/background.py` docstring):

1. Disable the control that started the work while it runs (one run at a time); never `processEvents()`.
2. Inline `BusyIndicator` when the user can carry on elsewhere; `BusySheet` when files the editor or the decks hold
   are being rewritten.
3. Determinate when the steps are counted before the work starts (files found, slides extracted, bytes); the
   back-end function gets an `on_progress: Callable[[Progress], None] | None = None` argument (Qt-free, CLI-safe).
4. Hold `busy_reason` for work that competes with background rendering for the disk (deletes, copies, imports).
5. The end is told as before (log line, toast or message box); errors arrive in `done(None, error)`.

## 3. Steps

Each step is its own PR, with a patch version bump and CHANGELOG entry (app code), and tests (pytest-qt for the
widgets; plain tests for the back-end `on_progress` callbacks and for `RenderStore.clear()`).

1. **Clear background previews without freezing** (the trigger case). `RenderStore.clear()`: rename `objects/` and
   `tmp/` to `trash-<uuid>/` under the lock, delete the rows, return the trash folders; `RenderStore.purge_trash()`
   deletes them with no lock held, and `rescan()` calls it for leftovers. Add `progress.py`,
   `background.run(...)` / `run_with_progress(...)` and the kit `BusyIndicator` (the minimum of section 2.2 this
   step needs). Settings: the button is disabled, the indicator says "Clearing background previews…" under it, the
   caption shows the emptied store at once, and the purge runs with `busy_reason="clearing previews"`. Same change
   for `drop_deck()` (archive a deck). Tests: `clear()` returns quickly with a store of many objects and leaves
   `count() == 0`; a store with a leftover trash folder is cleaned by `rescan()`; a `put()` during the purge
   survives.
2. **Plugin host on the shared runners.** `PluginHost.run_in_background*` call `background.run*`;
   `settings_plugins.Job` goes, the Extensions page shows a `BusyIndicator` for its jobs, and theme / citation
   installs (from GitHub and from a file) run their unpack on the worker too. No change to the plugin API.
3. **Update project with progress.** `compat.run_update(..., on_progress=None)` reports one step per file it backs
   up and writes; `maintenance.compat_update` runs it in a `BusySheet` (introduced here). The evaluation after it
   runs in the same worker.
4. **Framework and manual copies.** `check_bundled_copies` computes `plan_updates` on a worker (no indicator);
   `apply_update(..., on_progress=None)` reports files copied; `apply_bundled_parts` runs in a `BusySheet`.
5. **Housekeeping.** The sheet opens at once and scans on a worker ("Counting…" in the rows); Remove temp files,
   Empty pdf/ and Sync translation links run on workers with a `BusyIndicator` (determinate for the first two);
   `unused_content.archive_files(..., on_progress=None)` gives the archive its bar, and `_ArchiveWorker` goes.
6. **Import PPTX/ODP.** `slide_import.import_presentation(..., on_progress=None)`: busy while extracting, then
   "slide n of m"; the sheet becomes a `BusySheet` while it runs. The deck edit (`after_deck_edit`) stays on the GUI
   thread in `done`.
7. **Updates of SlideMage itself.** "Check for updates" fetches on a worker with a `BusyIndicator` in a small sheet
   (no wait cursor); the download runs in a `BusySheet` with a determinate bar and Cancel, without
   `processEvents()`. The install step after the download stays as it is.
8. **Export LaTeX** on a worker with a determinate `BusyIndicator` in the toast area (`latex_export.export_deck`
   gets `on_progress`). Lowest priority; can be dropped if step 9 measures it under 0.5 s on a large deck.
9. **Measure the rest, fix what is slow.** Add `timing.event` calls (`SLIDEMAGE_TIMING=1`) around `scan_decks`,
   `compat.evaluate`, `needed_slides_by_template` and the Images page reload; run them on the owner's project; any
   that is over 0.5 s moves to a worker with a `BusyIndicator`, in a follow-up PR per operation. The rest are noted
   here as measured and left alone.

Out of scope: the compile progress card, the AI status displays, and the plugin's own `Progress` (the Ollama plugin
can switch to `slidemage.progress.Progress` in a later release of its own; nothing forces it).
