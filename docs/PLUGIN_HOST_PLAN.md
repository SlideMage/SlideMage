# Plugin host: implementation plan

Status: plan, 2026-10-28. Branch `feature/plugin-host` from `develop`, one pull request. Implements phases 0
(plugin host) and 1 (installing) of `docs/PLUGINS_PLAN.md` (draft 3, on `feature/anthropic-stdlib`; its sections
2.1, 2.5, 2.6, 2.7, 2.8, 2.9 and 6 are the spec). No feature leaves core in this pull request: CampusOnline and
the AI stay built in (phase 2 and later remove them).

## Scope

In:

- `slidemage.plugin_api` (`API_VERSION = 1`) and the host behind it: everything the CampusOnline plugin's drafted
  `Host` Protocol uses (`campusonline/host.py` in `~/github/slidemage-plugin-campusonline`, mirrored in
  PLUGINS_PLAN §6.4), plus `add_settings_tab`, `settings(plugin_id)`, `log`, `show_message`.
- Manifest, loader, enable / disable, `SLIDEMAGE_PLUGIN_PATH`, the core boundary test.
- Installer (catalogue and file), catalogue client, Settings → Plugins tab, Help → Plugins…, the first-start sheet,
  plugin updates, the frozen build's stdlib and its self-test.

Out (later phases): `add_ai_route`, `add_settings_section(page="ai")`, `terminal()`, `ai_tools()`, `credentials`,
CLI entry points (phases 3 and 6); `size="large"` boxes and the dock switcher (registered, refused with a clear
error until a plugin needs them); the upgrade preselection and project hints (they matter only in the release that
removes a feature; the detection is written here, the sheet's preselection stays off until then).

## Decisions taken for this pull request

- The package is imported under its own top-level name (`<id with - as _>`, as the template and the website
  fix it), from its folder with `importlib`, not through `sys.path`. A name that is already importable (stdlib,
  SlideMage, a dependency, another plugin) refuses that plugin.
- Contributions are registered only inside `activate()`; afterwards `add_*` raises `RuntimeError`.
- A plugin that fails (manifest, import, `activate`) is disabled for the session and shown with its traceback in
  the Plugins tab; the app starts anyway. Enable / disable / install / remove take effect at the next start.
- Commands of a plugin are namespaced (`<id>.<name>`) and enter the existing `CommandRegistry`; menu entries are
  merged into `MENU_BAR` as a section of their own at the end of the named menu.
- No version bump per step: the branch starts from `develop` while other branches take the next version numbers,
  so the final step sets the version and the changelog entry once, when the number is known.

## Steps

Each step: one commit, its tests, `ruff`. Agents work in `.worktrees/plugin-host` and run Python as
`PYTHONPATH=src QT_QPA_PLATFORM=offscreen /home/juergen/github/SlideMage/.venv/bin/python` (the shared venv's
editable install points at the main checkout). Agents don't commit; the orchestrator reviews and commits.

| # | Step | Agent | Depends on |
|---|---|---|---|
| 1 | Manifest, loader, registry, `plugin_api` types, boundary test | Sonnet | – |
| 2 | Host services: deck edits, cache dirs, settings store, background work, render priority | Sonnet | 1 |
| 3 | Installer: staging, SHA-256, zip guards, swap, state | Sonnet | 1 |
| 4 | Catalogue client | Haiku | 1 |
| 5 | Frozen build: stdlib and PySide6 set, `--self-test --plugins` | Haiku | 1 |
| 6 | UI hooks: commands and menus, Deck settings tab, Settings tab, side-panel box, loading at start | Sonnet | 2 |
| 7 | Settings → Plugins tab, Help → Plugins…, Install from file… | Sonnet | 3, 4, 6 |
| 8 | First-start sheet, plugin updates | Sonnet | 7 |
| 9 | End-to-end: the CampusOnline plugin loaded from its checkout; version and changelog | orchestrator | 8 |

Steps 2–5 run in parallel (separate files).

### 1. Manifest, loader, registry

- `src/slidemage/plugins/manifest.py`: read and check `plugin.toml` with `tomllib` (rules: website handover §3:
  id pattern, name length, semantic version, `api_version` int ≥ 1, `requires_slidemage` comma list of
  `>= <= == < >` comparisons, summary ≤ 120, `needs`/`network` lists of short lines). `matches(range, version)`
  for `requires_slidemage` (used by the catalogue too). `package_name(id)`.
- `src/slidemage/plugins/loader.py`: discover plugins in `config_dir()/plugins/<id>/` and in the folders of
  `SLIDEMAGE_PLUGIN_PATH` (`os.pathsep`-separated; each folder holds a `plugin.toml`); skip disabled ones
  (`config_dir()/plugins/state.json`); refuse a wrong `api_version` or `requires_slidemage` with a reason; import
  the package (Decisions); call `activate(host)`; record per plugin: manifest, source folder, state
  (loaded / disabled / failed / incompatible), error text.
- `src/slidemage/plugin_api.py`: `API_VERSION`, the public types (`Deck` protocol, `InsertPosition`,
  `FooterAction`, `StaleFileError`, `COURSE_GROUP`, `Host` as the documented interface), matching
  `campusonline/host.py`. The concrete host lives in `plugins/`.
- `src/slidemage/plugins/registry.py`: what plugins registered (commands, menu entries, tabs, boxes, render
  priorities, settings tabs), with the registration lock.
- Tests with fixture plugins under `tests/fixtures/plugins/` (a `hello` like the website's, a bad manifest, a
  raising `activate`, a wrong `api_version`, a name clash with the stdlib, a relative-import package), and the
  boundary test: no module under `src/slidemage` imports a plugin package.

### 2. Host services

`src/slidemage/plugins/host.py`: the concrete `Host` for the calls without UI hooks: `cache_dir()` (per plugin,
under `project.cache_dir()`), `legacy_cache_dir()` (`project.cache_dir()`), `settings(plugin_id)` (JSON in
`config_dir()/plugins/settings/<id>.json`), `run_in_background(work, done)` (QThread, `done` on the UI thread),
`insert_positions`, `insert_slides` (slide files with SlideMage's header and version, ids minted through
`slide_ids`, all-or-nothing), `edit_deck_text` (`deck_editor.apply`), `deck_language`, `open_url`, `log`,
`show_message`, `add_render_priority` wired into `BackgroundRenders` (core's own rule OR any plugin's;
exceptions count as False). Deck snapshots from `deck_scan.Deck`.

### 3. Installer

`src/slidemage/plugins/installer.py`, no Qt: `install(archive, expected_sha256=None)` → staging in
`plugins/.staging/`, hash check, unzip guards (no absolute paths, no `..`, no symlinks, size cap, refuse
`.pyc .pyo .so .pyd .dll .dylib .exe`), manifest check, the package folder present, then replace
`plugins/<id>/` (the old copy moves to `plugins/.old/` and is removed at the next start); `remove(id)`;
`set_enabled(id, flag)`; `pending_changes()` for "takes effect after a restart". Tests: zip-slip, symlink,
compiled file, wrong hash, wrong `api_version`, reinstall, remove, cleanup.

### 4. Catalogue client

`src/slidemage/plugins/catalogue.py`, no Qt: `CATALOGUE_URL = "https://slidemage.org/plugins/index.json"`,
`SLIDEMAGE_PLUGIN_CATALOGUE` overrides it; fetch with a timeout, cache the last good copy in
`plugins/catalogue.json`; parse into dataclasses, checking the fields the app uses (schema 1, website §5);
unknown top-level and plugin fields ignored; `schema` ≠ 1 → `CatalogueTooNew`; `best_release(plugin,
app_version, api_versions)`. Tests on a copy of `index-test.json` and of the website's schema (fixture validated
with `jsonschema` only if installed).

### 5. Frozen build

`packaging/slidemage.spec`: collect the whole stdlib minus `tkinter`, `test`, `idlelib`, `ensurepip`, `lib2to3`,
and the PySide6 set `QtCore`, `QtGui`, `QtWidgets`, `QtNetwork`, `QtSvg`. `--self-test --plugins` in `cli.py`:
imports every bundled stdlib module, then loads the `hello` fixture plugin through the loader. The release
workflow runs it on every platform.

### 6. UI hooks

`add_command` / `add_menu_entry` merged into the registry and `MENU_BAR` (run with a deck snapshot of the open
deck, `enabled(None)` without one); `add_deck_settings_tab` in `DeckSettingsSheet` with its `FooterAction`;
`open_deck_settings(deck, tab)`; `add_settings_tab` in `SettingsSheet`; `add_sidebar_box(size="compact")` as
picker entries after a "Plugins" separator in `SidePanels`, with `when`; widgets `Page`, `Field`, `caption` from
`ui/kit/widgets.py`. Plugins load in `ui/app.main` before the window is built.

### 7. Plugins tab

Settings → Plugins (and Help → Plugins… opening it): installed plugins with version, state, needs, network,
enable switch, Remove, Update; a failed one with its error; "Install from file…" (warning: not from the
SlideMage plugin list, its network lines); "Available" from the catalogue with Install; "Restart now".

### 8. First-start sheet and updates

Once per machine (flag in `config_dir()`): Recommended first, marked, not preselected; summary, needs,
network, More…; footer link to `plugins_page`; Install selected / Not now; offline text with Install from file….
Plugin updates checked with the app's update check and its mode (off / ask / auto), at most once a day; a
withdrawn installed version is shown. The upgrade detection (`plugins/upgrade.py`) is written and tested but not
yet used.

### 9. End-to-end and release notes (orchestrator)

Load `~/github/slidemage-plugin-campusonline` through `SLIDEMAGE_PLUGIN_PATH` in an offscreen window: it
activates against the real host, its command, menu entries, Course tab and box appear. Version and changelog.
