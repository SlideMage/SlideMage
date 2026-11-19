# UI stalls during editing (issue #252): plan

Status: steps 1–5 done 2026-11-19 (v0.17.32–v0.17.35), on feature/ui-stalls-pr, rebased onto develop @ 3d0983f0 (v0.17.31); tested by the owner. Step 5 follow-ups (section 3.1) are not started.

The issue names three sources of main-thread stalls in a 17-hour session (about 900 slide files): the slide language
index rebuilt on the GUI thread several times per refresh, the Linux input watcher walking every widget four times a
second, and background threads holding the GIL. This plan fixes the first two and measures the third before
changing anything there.

One branch per step, from `develop`, one patch version each (v0.17.32 onwards), a CHANGELOG entry with a `NEW:` bullet
where the user notices something. Run the tests as in the "Running tests in worktrees" note (one capped pytest run at a time).

---

## 1. Findings from the code

### 1.1 The language index (`slide_language.py`)

`links_for(ctx)` builds a new `TranslationLinks` each time. Its constructor calls `_listing`, which runs `os.scandir`
plus a `stat` on every `*-current.tex` (about 900 here). The file texts (`_texts`) and the groups (`_groups_cache`) are
already cached by `(mtime, size)`, so the listing is the fixed cost of every call. Two more costs make it worse while
someone is editing:

* **Unsettled groups.** `group()` reuses the cached groups only when *no* file in the folder changed in the last 2 s
  (`_RACY_NS`). While Claude or the user is editing, some file almost always changed in the last 2 s. So every call
  runs a full `_scan()`, which runs both link regexes over the cached text of every current file (about 2.3 MB).
  The issue puts the 60–90 ms on the scandir, but the stall stacks cannot tell the listing from the regex pass, and
  the perf event logs no separate listing time. Step 1 measures this.
* **Many entry points, no sharing.** About 20 call sites call `links_for` themselves. On the GUI thread the issue
  names `resolve_outline` (slide list rebuild), `deck_bubbles` (assistant header offers) and `deck_language.slots`
  reached through `resolve_slots` without `links=`. The GUI callers that pass no `links=` are
  `preview_target.for_call` (both `resolve_call` and the presenter-frame `resolve_slots` when no matching `outline` is
  passed), `panels/used.py:47`, `presentation/launch.py:48`, `task_bubbles.deck_slots` (via `deck_language.deck_slots`)
  and `task_bubbles.py:749` / `:1213`. One edit triggers several of these in separate handlers, so each one scans
  again.

Caching the listing by the folder's mtime, as `render_evidence.search_inventory` does, is **not safe here**. Editing
a file in place leaves the folder's mtime unchanged, so the old stamps would come back with the old cached text, and
the translation links would be stale with no way to notice. The listing has to be redone, or shared only within a
bounded scope.

### 1.2 The input watcher (`ui/workspace/background_previews.py:291`)

`_InputWatcher` is the Linux-only path (`USE_WIDGET_INPUT_WATCHER`). An application-wide event filter crashes in
Shiboken there (WebEngine's private focus objects), so idea 2 of the issue (install the filter on the application)
is ruled out on Linux. Every 250 ms it reads the cursor (cheap) and walks `QApplication.allWidgets()` against a
`WeakSet` (expensive, and growing over a session). The terminal view already installs filters on children from
`ChildAdded` (`terminal/web.py:181`), which shows that the pattern works next to WebEngine.

### 1.3 Background threads

Most stall samples (1402) show the GUI thread idle in the event loop while workers run. `stall_monitor` already
records every thread's innermost frames per stall, so the log can rank which worker was busy. The candidates are
the planner's `scan()` (`background_renders.py:427`), header sync (`deck_headers.py:116`) and thumbnail validation.

---

## 2. Steps

### Step 1: measure the index (v0.17.32)

* Extend the `slide_language.scan` perf event: `listing_s` (time in `_listing`), `settled` (whether the cached
  groups could be used), and `caller`, the first frame outside `slide_language` / `deck_language` / `deck_outline`
  (only when `timing.enabled()`).
* Log a `slide_language.listing` event for every `TranslationLinks` built on the GUI thread, not only when groups
  are rebuilt. Today a call that reuses the cached groups logs nothing, so the count of 256 GUI scans undercounts.
* Owner test: with `SLIDEMAGE_DEBUG=1`, edit a few slides by hand and through the terminal. The log should show
  listings per edit, the listing time compared with the regex time, and which callers are involved. Steps 2 and 3
  are sized from these numbers. If the listing turns out cheap, step 3 comes first.

### Step 2: one listing per GUI refresh (v0.17.33)

* `slide_language.shared_links(ctx)`: a context manager. Inside it, `links_for(ctx)` on the same thread returns one
  instance (a thread-local keyed by `slides_dir` and the language codes). Outside it, nothing changes. Nesting reuses
  the outer instance.
* Wrap the GUI refresh entry points that run on every edit or version update: `slide_list.rebuild`, the assistant
  header's offer refresh (`assistant_header.py:249`), the Preview's target update, and the `centre.py:1565` path.
  The list is final once step 1 names the callers.
* Inside a scope, nothing may write a slide file. These entry points only read. Add a test that writes a link
  header inside a scope and shows that the next scope sees it.
* Where the `Outline` is at hand, also pass `outline=` / `links=` at the remaining GUI call sites (`used.py:47`,
  `launch.py:48`, `task_bubbles.py:749/:1213`) instead of scanning again.
* Leave background threads (`batch_render`, the planner, header sync) as they are. They already share one
  `links` per pass.

### Step 3: re-read only the files that changed (v0.17.34)

* Cache each file's parsed links (`Translation of:` targets, `<LANG> translation:` pairs) by `(path, stamp)` next to
  `_texts`, and build `parents` in `_scan()` from those. The regexes then run only on files that are new, changed, or
  changed within the last 2 s. The graph pass over about 900 ids stays (milliseconds).
* Keep the all-settled `_groups_cache` shortcut as it is. Step 3 makes the unsettled path cheap; it does not change
  when the shortcut applies.
* Tests: a link added or removed in one file changes the groups straight away, including within 2 s of a previous
  write. A file deleted between two scans drops out of its group.

### Step 4: input watcher without the widget walk (v0.17.35)

* Install the filter on each top-level widget, and from there on every child already present
  (`findChildren(QWidget)`) and every child added later (`QEvent.ChildAdded` with `isinstance(child, QWidget)`, as in
  `terminal/web.py`). Keep the `WeakSet` so that no widget gets a second filter.
* The 250 ms timer stays for the cursor poll, which is still needed for unpressed moves on widgets without mouse
  tracking. Instead of `allWidgets()` it checks `QApplication.topLevelWidgets()` for new windows: menus, popups and
  dialogs have no parent to send `ChildAdded`. That is a handful of widgets, not thousands.
* `stop()` removes the filters from the widgets in the `WeakSet`, with no `allWidgets()` walk.
* Tests in `test_background_previews_gui.py`: a widget added after start, a nested child, a new top-level dialog and
  a popup menu each report input. Owner check on Linux: the terminal and Preview (WebEngine) still work, and there
  is no Shiboken crash over a long session.

### Step 5: rank the GIL holders (findings only, no fix)

* Tool: `python tools/debug_log.py --stalls [files]` (an option of the existing `tools/debug_log.py`) reads the
  `stall late=…` reports and counts, per stall, the GUI frame and the busy worker frames, grouped by function. Run it
  on the owner's 17-hour log, then again after steps 2–4.
* Write the ranking into this file (section 3). Then decide per hotspot, with the owner: yield (`time.sleep(0)`
  every N items in long pure-Python loops), reuse a cache (the planner may be rebuilding outlines that steps 2–3
  now make cheap), or move the work into the render processes. Each fix chosen becomes its own step.

---

## 3. Results

### 3.1 Step 5 ranking, before the fixes (2026-11-19)

Taken with `python tools/debug_log.py --stalls` over the local Linux log of v0.17.23 (17 h, started 2026-11-18 17:07): 2950
stalls, 866 s late in total. In 1142 of them the GUI was idle (a worker held the GIL), and in 837 the watchdog took no
sample. Threads parked in a blocking call (`selectors.py select`, `ptyprocess.py read`) are left out of the worker
table: they release the GIL.

GUI thread (count, seconds late):
- `background_previews.py _watch_widgets` 273 / 63 s, plus `_weakrefset.py` `_remove` / `__contains__` 136 / 32 s
  (the watcher's WeakSet). Step 4.
- `slide_language.py _listing` 160 / 147 s. Steps 1–3.
- `window.py open_settings` 180 / 46 s: opening Settings. A one-off, not part of #252.
- `app_settings.py _read` 51, `<frozen posixpath> _joinrealpath` 74: not traced yet.

Busy workers during stalls (count, seconds late):
- `preview-display` `render_evidence.search_inventory` 413 / 158 s, plus `pathlib stat` 408 / 183 s.
- `edit-watch-scan` `project_watch.scan` 357 / 128 s: the once-a-second poll of the project's text files. Since v0.16.50
  it runs off the GUI thread (older logs show it on the GUI thread), but it walks and stats the whole project every
  second, in Python.
- Other `stat` calls: `render-scheduler` 313, `Thread- (_run)` 382 (compile jobs).
- `dep_hash.hash`: `background-planner` 158, `preview-display` 150, `list-thumbnails` 115.
- `pty-reader` `service.py _emit` 220 / 110 s: terminal output.

Candidates for follow-up steps, decided after steps 1–4 have been measured:
- (a) `project_watch.scan` every second: skip unchanged folders by their mtime, or poll less often while no agent runs.
- (b) `search_inventory` / `dep_hash` in the preview-display thread: check whether the same key is computed several
  times per refresh.
- (c) Why the watchdog takes no sample in 837 stalls.
