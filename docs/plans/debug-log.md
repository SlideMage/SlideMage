# Plan: an on-demand debug log for SlideMage

Status: decisions made 2026-10-31 (section 7). Steps 1 and 2 done (v0.12.3, v0.12.4); step 3 next, after the go.

## 1. Review: what SlideMage writes today

### 1.1 Debug traces that write all the time (leftovers)

| What | Where it is written | Since | When it is written |
|---|---|---|---|
| `status_trace.StatusTrace`: every change of the progress card | `<config>/status-progression.log`, or the file named by `SLIDEMAGE_STATUS_LOG` | v8.32.0, 2026-10-19 | **On every compile run**, overwritten each time (`ui/workspace/compile_controller.py:90`) |
| `background_renders.Trace`: what background rendering decided (focus, input, start/stop, chip) | `<cache>/background-trace.log` (+ `.1`), capped at 512 KB | v8.52.4, 2026-10-21 | **Always** while background previews run (`ui/workspace/background_previews.py:362`); off only under `SLIDEMAGE_NO_BACKGROUND_PREVIEWS` |

Both were added to chase one bug each and never switched off. They cost little,
but they write files on every user's machine that no one reads, and each has its
own format and location.

### 1.2 Debug tools that are already opt-in

| What | Switch | Output |
|---|---|---|
| `timing.py`: prompt-to-preview events from the app, the AI tools, the plugin hooks | `SLIDEMAGE_TIMING=1` | `<project>/.slidemage/timing.jsonl`, read by `tools/timing_summary.py` |
| `preview_metrics.PreviewMetrics`: stage/rule timings of one preview | always collected, in memory only | `request.metrics`; printed by `preview_cli.py` and the benchmarks |

These are fine as they are. `timing` is a second debug channel next to whatever we build, so it should be folded in.

### 1.3 Python `logging`: used, but goes nowhere

About 45 `log.exception` / `log.error` / `log.warning` / `log.info` calls in 14 modules
(the plugin host, installer, updates, upgrade, themes, theme sources, settings dialogs,
plugin UI, plugin boxes, `ui/app.py`). **No handler is configured anywhere**: no
`basicConfig`, no `FileHandler`. That means:

* The windowed build (`console=False` in `packaging/slidemage.spec`) has no stderr, so
  every one of these, tracebacks included, is lost in the installed app.
* From a terminal only WARNING and higher show up (Python's last-resort handler). So
  `Host.log()` in the plugin API (`plugins/host.py:248`, INFO) never shows up anywhere,
  even though plugin authors are told it is the way to log.
* No `sys.excepthook`, `threading.excepthook` or Qt message handler is installed, so
  uncaught exceptions in worker threads and Qt warnings are lost the same way.

### 1.4 `print` calls

* **Meant to be there (CLI output):** `cli.py`, `compat.py`, `deck_scan.py`,
  `deck_snapshot.py`, `sm_rename.py`, `preview_cli.py`, `plugins/selftest.py`,
  `plugins/entry.py:43` (a plugin entry point's error, run as a subprocess). These stay.
* **Lost in the GUI:** `project.warn_legacy_env_vars()` (`project.py:480`) prints to
  stderr, which the windowed app does not have. It should become a logged warning
  (and keep printing for the CLI).
* **Debug leftover:** `ui/kit/gallery.py:83` prints toast actions. It sits in the
  debug-only gallery, so it is harmless; it can become a `log.debug`.

### 1.5 Not debug output (no change)

The compile log (`compile_log` + `log(...)` callbacks, shown in the compile drawer),
LaTeX `.log` files, `compat-report.md/.json`, and the dev/test switches
`SLIDEMAGE_NO_BACKGROUND_PREVIEWS`, `SLIDEMAGE_PREVIEW_FORMAT=0`, `SLIDEMAGE_LATEX`.
No commented-out prints, `breakpoint()` or `pdb` were found.

## 2. Goal

One debug-log facility:

* **Off by default**, apart from a small error log that is always on.
* Turned on **from the app** (Settings), with `--debug`, or with `SLIDEMAGE_DEBUG=1`.
* **One place, one format**, with a header that says what produced it. You can zip
  it and send it in, and Claude or a person can read it without a tool.
* Built on the standard `logging` module, so the existing calls and the plugin API's
  `Host.log()` start working without being rewritten.
* Replaces the two always-on traces and the separate timing switch.

## 3. Design

### 3.1 A new module `slidemage/diagnostics.py` (no Qt)

`diagnostics.setup(debug: bool)` is called once and as early as possible in `cli.main()`
(and in the hook and `--plugin` entry paths). It attaches handlers to the `slidemage`
logger, not the root logger, so third-party libraries stay quiet unless asked.

* **Always on, the error log:** `<cache>/logs/slidemage.log` (the local cache folder, not the roaming config folder), level WARNING,
  rotating at 1 MB with 3 backups. This catches everything in 1.3 that is lost today.
* **Debug on, the session log:** `<cache>/logs/debug/YYYY-MM-DD_HHMMSS_<pid>_<role>.log`,
  level DEBUG. `role` is `app`, `hook` or `plugin-<id>`, so each subprocess gets its
  own file and no two processes share a file. Each file rotates at 10 MB. At startup,
  sessions are deleted beyond 20 files or 100 MB in total.
* **Hooks:** `sys.excepthook`, `threading.excepthook`, and `qInstallMessageHandler`
  (installed from `ui/app.py`, since diagnostics stays free of Qt) send uncaught
  exceptions and Qt warnings to the log.
* **Turning it on or off at runtime** changes the handler and the logger level. No
  restart is needed, and the setting is passed on to subprocesses through `SLIDEMAGE_DEBUG`.
* **It stays on across restarts** until turned off (D1). It is a normal persisted
  setting, read before the window exists, so startup is logged too. The status-bar
  indicator and the 20-file/100 MB cleanup limit stop it from going unnoticed or filling the disk.

### 3.2 Line format

Plain text with fixed columns, one record per line. Fields are `key=value` pairs, and
tracebacks are indented underneath:

```
2026-10-31 14:02:11.384 +12.406s DEBUG    compile            app:4312 MainThread  job started  deck=micro-01 job=micro-01-de engine=lualatex
2026-10-31 14:02:19.902 +20.924s INFO     compile            app:4312 Worker-2  job finished deck=micro-01 seconds=8.52 exit=0
2026-10-31 14:02:20.010 +21.032s DEBUG    background         app:4312 Renderer  planner: may render
```

* Elapsed time since the process started, as the existing traces have it.
* `role:pid` names the process. The error log is shared by every process, so it needs them
  (step 1); a session log has them too, so that merged files stay readable.
* The **area** is the logger name without `slidemage.`: `compile`, `preview`,
  `background`, `status`, `timing`, `ai`, `terminal`, `plugins.<id>`, `update`,
  `themes`, `project`, `ui`, `startup`.
* There is one helper, `diagnostics.event(log, "job started", deck=..., job=...)`, that
  formats the fields the same way everywhere and costs nothing when DEBUG is off.
* A small `tools/debug_log.py` filters by area, level or time, and turns the `timing`
  lines into the timeline that `timing_summary.py` prints today.

### 3.3 Header of each session log

Version, flavour, frozen/source, Python, Qt/PySide, OS, display scale, project path,
the TeX engine found and its version, loaded plugins with their versions, and every
`SLIDEMAGE_*` environment variable that is set (values redacted where they are secrets).

### 3.4 Privacy and redaction

* A filter on every handler masks API keys and tokens: the values known to
  `plugins/credentials.py`, the updater token, `ANTHROPIC_API_KEY`, and anything
  shaped like `sk-…` or `ghp_…`.
* Slide text and prompts are not logged. Paths and file names are, since they are
  needed to debug. Where content helps (a failing LaTeX line, say), it is cut to
  200 characters.
* The settings text says what the log contains and where it is stored.

### 3.5 UI

* **Settings → General:** "Detailed debug log" switch, with "Open log folder" next to it.
* While it is on, a small indicator appears in the status bar, so it is not left on
  by mistake. Clicking the indicator opens the folder.
* **Help → "Save debug report…":** a zip of the newest session logs, the error log, the
  header data, the newest compile log and `compat-report.json`, written where the user
  chooses. Nothing is sent anywhere.

### 3.6 Plugin API

`Host.log()` finally ends up in the log, under `plugins.<id>`. It becomes
`Host.log(message, level="info")`, where `level` is one of `"debug"`, `"info"`,
`"warning"` or `"error"` (D5). Existing calls keep working. This is a plugin-API
minor version: bump the API version, add a changelog entry, update the plugin-author
docs, and give the self-test fixture plugin a call with a level. The plugins can then
use it in their own releases; their minimum API version only goes up when they do.
`Host.debug_enabled()` lets a plugin skip expensive debug output when nobody is logging.

## 4. Migration of the existing traces

| Today | After |
|---|---|
| `status_trace.StatusTrace` → `status-progression.log` on every run | Keeps its change detection, but writes `log.debug` to area `status`. It is only active when debug is on. `SLIDEMAGE_STATUS_LOG` goes. |
| `background_renders.Trace` → `background-trace.log` | `self.trace()` becomes `log.debug` in area `background`; the `Trace` class and its file go. |
| `timing.event` / `SLIDEMAGE_TIMING` | `enabled()` is true when debug is on, and `SLIDEMAGE_TIMING=1` still works as an alias. Events go only to area `timing` in the debug log, and `timing.jsonl` is no longer written (D2). `tools/debug_log.py --timeline` merges the app's and the hooks' session files by timestamp and replaces `timing_summary.py`. |
| `preview_metrics` | Unchanged. When debug is on, each finished preview logs its metrics in one `preview` line. |
| `warn_legacy_env_vars` print | Logs a warning, and keeps printing when run from a console. |
| gallery `print` | `log.debug`. |
| Old files | At startup, `status-progression.log` and `background-trace.log*` are deleted once (same pattern as the other cleanups in `maintenance`). |

## 5. New instrumentation (debug level)

These are the points that would have spared us the ad-hoc traces:

* **startup:** the time of each stage (imports, fonts, theme, plugins, window shown) and
  each `maintenance` check scheduled and finished.
* **compile:** job queued, started, finished, stopped or superseded. For every TeX/latexmk
  call: the command line, cwd, exit code and seconds.
* **preview:** request, cache hit or miss, deduplication, cancel, and a metrics summary.
* **background:** everything `Trace` has today.
* **ai / terminal:** each tool call (name, seconds, error; arguments only by name), and
  Claude Code terminal start/exit/restart with its exit code.
* **plugins:** discovery, manifest problems, load time per plugin, hook calls, and
  background jobs with exceptions.
* **update / themes:** each check (URL without token, HTTP status, seconds, result).
* **project / ui:** project opened, deck opened, view and language changes, file-watcher
  events, settings changed (key, not secret values).

## 6. Steps (one PR each, stop after each)

1. **Base (done, v0.12.3):** `diagnostics.py`, the always-on error log, the excepthooks and the Qt
   message handler, called from `cli.main()` and the subprocess paths. Tests for rotation,
   cleanup, redaction and the format. This alone makes the lost exceptions from 1.3 visible.
2. **The debug switch (done, v0.12.4):** `--debug`, `SLIDEMAGE_DEBUG`, the persisted setting, the session
   file and header, switching at runtime, and passing it on to hooks and plugin
   subprocesses. It also adds `Host.log(level=…)` and `Host.debug_enabled()`. The plugin API grows
   by additions without raising `API_VERSION` (the contract test's snapshot is renewed),
   so "minor bump" means a plugin that uses them says `requires_slidemage = ">=0.12.4"`.
   Short-lived processes (hook, plugin, raster) share one file per role with a two-line
   header, so a hook does not create a session file on every run. The plugin self-test
   loads plugins with a bare `Registrar`, which has no `log`, so it doesn't call it.
3. **Fold in the old traces** (section 4), including the one-off file cleanup.
4. **UI:** the settings switch, the status-bar indicator, Help → Save debug report.
5. **Instrumentation** (section 5), area by area. Small, so it can be one PR or split
   into compile+preview and the rest.
6. **Docs:** a section in the manual, a short note for plugin authors, and
   `tools/debug_log.py` (which replaces `timing_summary.py`).

## 7. Decisions (2026-10-31)

* **D1:** Debug mode **stays on until turned off**, across restarts. The status-bar
  indicator is the reminder, and the cleanup limit caps the disk use.
* **D2:** Timing goes **into the debug log only**. `timing.jsonl` and
  `timing_summary.py` go, and `tools/debug_log.py --timeline` replaces them.
* **D3:** The **always-on error log** (warnings and errors, at most about 4 MB): yes.
* **D4:** **Plain-text lines** with `key=value` fields.
* **D5:** `Host.log(level=…)` comes **now**, in step 2, with the plugin-API minor bump.
