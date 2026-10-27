# Plugins: the SlideMage side

Status: plan, 2026-10-27. Nothing implemented. Needs the user's go per step; pause after each committed step.

Sources. Stefan's original plan (`docs/PLUGINS_PLAN.md`, 2026-10-26) is not in any repository we can reach, so
this plan is rebuilt from what came out of it, and keeps its phase numbers, API names and route ids wherever
they show:

- the four handovers of 2026-10-26: website, CampusOnline, Claude, Ollama (the Ollama one not seen yet);
- the website's answer of 2026-10-27, "Website → app: what the plugins plan needs back" ("the website answer");
- the code on `feature/ai-tools-fixes` (v8.65.0).

Where this plan adds something the handovers don't say, it is marked *(added)*. When Stefan's plan turns up,
diff the two and keep his where they disagree, unless the code says otherwise.

Three features built in today become plugins; SlideMage ships none and offers them on first start:

| Plugin | Repository | Maintainer | Released with |
|---|---|---|---|
| `campusonline` | `JuergenFleiss/slidemage-plugin-campusonline` | Jürgen | the first SlideMage without built-in CampusOnline |
| `ollama` | `stpalan/slidemage-plugin-ollama` | Stefan | the AI-free core (v10.0), together with `claude` |
| `claude` | `JuergenFleiss/slidemage-plugin-claude` | Jürgen | the AI-free core (v10.0), together with `ollama` |

## 1. Fixed by the website side (all live)

| Item | Value |
|---|---|
| Catalogue URL to hard-code | `https://slidemage.org/plugins/index.json` (final; no plugins in it yet) |
| Test catalogue | `https://slidemage.org/plugins/index-test.json`: the listed plugins plus the hidden ones; today only `hello` 0.1.0 |
| Plugin pages | `https://slidemage.org/plugins/` and `…/plugins/<id>/`. Hidden plugins have no page (`/plugins/hello/` is a 404) |
| Schema | copy `schema/plugins-index.schema.json` from `stpalan/slidemage-website` (not from the handover); `$id` `https://slidemage.org/schema/plugins-index-1.json`, served there byte for byte |
| `hello` for tests | `hello-0.1.0.smplugin`, SHA-256 `a72af2022f7b2a5b161964d6e55376815e76be50c8645e2d02ee2dc7358c00f9`, 12357 bytes. GitHub also has 0.2.0 (replaced asset, yanked), 0.3.0 (pre-release) and 0.4.0 (wrong asset name, marked "Latest"). None of these is in the catalogue, and none may ever be offered: **the app reads the catalogue, never "latest release"** |
| Package folder | the id with `-` as `_` (`my-plugin` → `my_plugin/`), with `activate(host)` in its `__init__.py`. The loader uses the same rule |
| Refused by the builder | `.pyc .pyo .so .pyd .dll .dylib .exe` in the asset; a release without `README.md` and `CHANGELOG.md` at its tag |
| `.sha256` asset | `sha256sum` format; the first word is the hash |
| Themes | Later, in the same catalogue: a top-level `"themes"` list, installed through the plugin installer, still `schema: 1`. Not before the framework redesign defines the theme package (`docs/plans/template-owned-layout-and-own-theme.md` on `dev-framework-redesign`). **The client ignores unknown top-level fields now.** |
| Template | `stpalan/slidemage-plugin-template`; its `build.py --check` lints the imports. Once `plugin_api` has a real shape, its `example/__init__.py` and README must show it: tell the website side |

## 2. Design

### 2.1 Rules for every plugin (handovers)

- Import only `slidemage.plugin_api`, the standard library, PySide6 and its own package. Everything else in
  `slidemage` is private and may change in any release.
- Pure Python: the PyInstaller build cannot load compiled modules from a plugin.
- No network I/O or slow work in `activate()`. Finding `claude` on `PATH` is fine; asking `/v1/models` is not.
- Without the plugin, nothing in SlideMage names its service. Its data stays where it is: a deck's
  `%% SlideMage course URL:` comment, and the AI settings in `ai_settings.json`.

### 2.2 What stays in core, what moves

| Stays in core | Moves to a plugin |
|---|---|
| AI layer: the `ChatProvider` protocol, `ChatReply`, `ProviderError`, `Cancelled`, `parse_json_object`, `agent_types`, the agent, the tools (`ai/tools/`), `ai/workspace.py`, `ai/guides.py`, `provider_tasks.py`, the image pipeline's backend protocols (`alt_draft`), `syntax_check`, `slide_add.translate_body` | **claude**: `claude_launch`, `claude_runner`, `claude_images`, `claude_hook`, `claude_scope`, `mcp_server`, the Anthropic part of `credentials`, `AnthropicProvider` (as the new stdlib client), `terminal/session.py`, `terminal/view.py`, `terminal/draft.py`, today's Cloud tab, the Claude Code parts of `ai_profile`/`resolver`, `tools/claude_task_benchmark.py` |
| The tasks: `ai/claude_tasks.py` → `ai/tasks.py`, `terminal/tasks.py` → `ui/workspace/task_bubbles.py` (renamed in phase 3) | **ollama**: `OllamaProvider`, `ollama_admin`, `settings_ollama`, the Ollama host setting, model management |
| The terminal service: `terminal/web.py`, `theme.py`, `assets/terminal/` (xterm.js), `pty_process.py`. QtWebEngine and pywinpty/ptyprocess are compiled | **campusonline**: `course_schedule`, `admin_slides` (+ its UI), the course link (`COURSE_URL_RE`, `parse_course_url`, `Deck.course_url`, `normalize_course_url`, `course_url_text`, `set_course_url`), the Deck menu command, the "session soon" render priority |
| The external-edit watch: `ai/project_watch.py`, `terminal/sync.py` | |
| The AI switch, AI setup, the assistant UI, the project's AI policy, the deck group "Course deck", `protected_regions.py` | |

### 2.3 AI routes (`add_ai_route`)

Today `ai_profile` hard-codes `LOCAL`, `CLAUDE_CODE` and `API`, and `resolver.py` maps each to a class. In
phase 3 these become routes registered by plugins. The route ids are `ollama`, `claude_code` and
`anthropic_api`; the stored values `"local"` and `"api"` are read as `ollama` and `anthropic_api`. Sketch, to be
replaced by Stefan's §2.4 when it turns up:

```python
@dataclass(frozen=True)
class AiRoute:
    id: str                          # "ollama", "claude_code", "anthropic_api"
    name: str                        # "Ollama", "Claude Code", "Anthropic API"
    is_local: bool                   # which side of Local | Cloud
    tasks: frozenset[str]            # of ai.tasks: chat, image_description, translation, fixes_...
    model_choices: Callable[[ProjectContext], list[str]]   # pickers; never waits on the network
    problem: Callable[[ProjectContext, Route], str]        # "" or why it can't run (no key, not installed)
    provider: Callable[[ProjectContext, Route], ChatProvider] | None = None
    draft_backend: Callable | None = None                  # else alt_draft.ModelBackend(provider)
    translation_backend: Callable | None = None
    slide_translator: Callable | None = None
    chat_surface: ChatSurfaceFactory | None = None         # Claude Code: the terminal instead of the chat view
```

`ChatSurface` is the lifecycle the core switch drives: `widget()`, `stop()` and `restart(model, continue_conversation)`,
which covers today's Switch now (v8.61.0). "Cloud means" (`cloud_conn`) becomes the chosen route of the
cloud side. `resolver`'s rule stays: no silent fallback to another route. With no route on a side, that side
of the switch is disabled with "Install a plugin…".

### 2.4 `slidemage.plugin_api` (`api_version = 1`)

The union of what the three handovers ask for:

| Area | Calls | For |
|---|---|---|
| Entry | `activate(host)` | all |
| AI | `add_ai_route`, `ai_tools()` (the ToolBox for the MCP server), the neutral AI types | claude, ollama |
| Settings | `add_settings_section(page="ai", ...)`, `add_settings_tab(...)`; `settings(plugin_id)`, with a one-time read of the old keys (`cloud_conn`, `ai_models`, `ollama_host`) | claude, ollama, campusonline (optional) |
| Secrets | `credentials`: environment variable, OS keychain, file fallback, per plugin. It must find the existing `ANTHROPIC_API_KEY`, the keychain entry and the `anthropic_api_key` file | claude |
| Process | `add_entry_point(name, fn)`; `entry_point_command(name)` gives the argv (`SlideMage --plugin claude:hook` frozen, `python -m slidemage --plugin claude:hook` from source) | claude |
| Terminal | `terminal()`: a PTY in the assistant card; the plugin supplies argv and env. The external-edit watch, switched on while the terminal runs | claude |
| Focus | the current deck, slide and scope; `protected_regions` (read) | claude |
| Decks | a deck (`name`, `path`, `text`, `groups`); `edit_deck_text(deck, change)` (refuses if the file changed meanwhile, like `deck_editor.apply`); `insert_slides`, `insert_positions`, `deck_language`. The handover's `add_deck_marker` is dropped: the plugin parses its own comment (`course_link.py`) | campusonline |
| UI | `add_deck_settings_tab(..., footer_action=...)`, `add_command`, `add_menu_entry("Deck", ...)`, `add_sidebar_box(size="compact", when=...)`, the kit widgets `Page`, `Field`, `caption` | campusonline |
| Rendering | `add_render_priority(fn: Deck -> bool)` | campusonline |
| Misc | `cache_dir()`, `legacy_cache_dir()` (where core kept a file before the plugin, e.g. `course-schedules.json`), `run_in_background`, `log`, `show_message`, `open_url`, `app_version` | all |

The CampusOnline side of this table is drafted in the plugin's own repository as a `typing.Protocol`
(`campusonline/host.py`, its step 2); `plugin_api` should be built to that.

The API is versioned by `api_version`, not by SlideMage's version. An incompatible change means
`api_version = 2`, and SlideMage keeps loading `api_version = 1` plugins for at least one major version.

### 2.5 Package, install, load *(added: the handovers leave the app mechanics open)*

- **Place:** `config_dir()/plugins/<id>/`, unpacked. `plugins/state.json` holds the enabled ids, the installed
  versions and the last catalogue check. Per machine, never in the project.
- **Install** (from the catalogue or from a file):
  1. Download to `plugins/.staging/`.
  2. Check the SHA-256 (the catalogue's, or for a file the `.sha256` beside it if present).
  3. Unzip with guards: no absolute paths, no `..`, a size cap, and a refusal of the builder's compiled
     extensions.
  4. Check `plugin.toml`, `api_version` and `requires_slidemage`.
  5. Rename into place; the old version waits in `.old/` until the next start.

  Install from file shows "Not from the SlideMage plugin list" and the plugin's `network` lines first.
- **Load:** at start, before the window. The package `<id with _>` is imported as `slidemage_plugins.<id>` with
  `importlib` (no `sys.path` entry), so plugin packages can't clash with each other or shadow the stdlib.
  A failing import or `activate` disables that plugin for the session and shows the traceback in
  Settings → Plugins; the app starts anyway.
- **Changes take effect at the next start**, with "Restart now". Modules can't be unloaded safely, and a
  route that disappears would break running requests.
- **Frozen build:** the spec collects the whole stdlib (minus `tkinter`, `test`, `idlelib`, `ensurepip`) and a
  fixed set of PySide6 modules (`QtCore`, `QtGui`, `QtWidgets`, `QtNetwork`, `QtSvg`), because PyInstaller
  bundles only what SlideMage itself imports. `--self-test --plugins` checks them, and the template documents
  exactly this set.

### 2.6 Catalogue client, first start, updates

- `plugins/catalogue.py`:
  - fetches `index.json` over HTTPS with a timeout and caches the last good copy;
  - `SLIDEMAGE_PLUGIN_CATALOGUE` points it at `index-test.json` *(added)*;
  - an unknown `schema` shows "Update SlideMage to see plugins";
  - unknown fields are ignored (themes, 1).
- **Choosing a release:** the newest one whose `api_version` is supported and whose `requires_slidemage` fits
  (a small parser for `>= <= == < >` comma lists).
- **First-start sheet** (also Settings → Plugins and Help → Plugins…):
  - "SlideMage works without plugins";
  - "Recommended" first, marked, not preselected;
  - per plugin: summary, needs, network, and "More…" (`homepage`);
  - footer: "See all plugins and what they do" (`plugins_page`).
- **Upgrade path:** preselect the plugins this person used:
  - `claude`: an API key, or a Claude Code or API route in `ai_settings.json`;
  - `ollama`: an Ollama host or local models set;
  - `campusonline`: a deck with a course link.

  A project with course links shows "This project uses CampusOnline course links. Install the plugin…" while
  the plugin is missing.
- **Updates:** with the app's update check and its mode (`updater.py`: off, ask, auto). A yanked installed
  version shows "withdrawn: update or remove".

## 3. Phases

Phase numbers as in the handovers. Each step is one commit with its tests. A user-visible change gets the
version bump and changelog line.

### Phase 0: `plugin_api` shape

**0.1** Write `plugin_api.py` as signatures and docstrings only (2.4), and review it with Jürgen against the
CampusOnline box and tab designs and Claude Code's `chat_surface` needs. Send its v1 shape to the website side
for the template.

### Phase 1: plugin host and installing plugins

**1.1 Manifest and loader.** `plugins/manifest.py` (`tomllib`, the handover's field rules, `requires_slidemage`)
and `plugins/loader.py` (2.5). Tests: a copy of `hello-0.1.0.smplugin` in `tests/fixtures/plugins/`, plus
synthetic ones: bad manifest, raising `activate`, wrong `api_version`, compiled file, zip-slip.

**1.2 Installer.** Staging, SHA-256, guards, swap, `.old`, `state.json`.

**1.3 Entry points.** `--plugin <id>:<name>` in `cli.py`: loads that one plugin, no window, calls its entry
point. Tests with a fixture plugin.

**1.4 Frozen build.** The spec's stdlib and PySide6 set; `--self-test --plugins` in the release workflow on all
three platforms.

**1.5 Settings → Plugins and Help → Plugins….** Installed (version, state, needs, network, Disable, Remove,
the error) and Install from file….

**1.6 Catalogue client.** 2.6, validated against the copied schema. Tests on a recorded `index-test.json`. A
network-marked test checks that the 0.2.0, 0.3.0 and 0.4.0 releases of `hello` are never offered and that
0.1.0 installs with the hash above.

**1.7 First-start sheet, upgrade preselection, plugin updates.**

Release **v9.0.0**: the plugin host, `api_version = 1`. `hello` installs from `index-test.json`.

### Phase 2: CampusOnline as the first plugin

The plugin side has its own plan: `docs/PLAN.md` in `~/github/slidemage-plugin-campusonline` (branch
`plugin-campusonline` on Jürgen's private fork `JuergenFleiss/SlideMageS` until it gets its public repository).
Done there: the history filtered from `stpalan/SlideMage` `develop`, the template adopted, the package
standard-library only, with what still needs SlideMage in `bridge/`. Then: the host Protocol, the Course tab and
the box, moving the old cache. Its steps 5–6 wait for this phase.

**2.1 Host calls for CampusOnline**, built to the plugin's `campusonline/host.py` Protocol. Core callers use
them first, so they are tested before anything moves.

**2.2 The plugin onto the real `plugin_api`** (plugin plan step 5): `bridge/` is deleted, and the plugin's tests
run against the oldest and newest SlideMage it allows.

**2.3 Cut from core:** the files and code of 2.2. The tests move with them (`test_course_schedule`,
`test_admin_slides*` and `test_course_url`, plus the course cases of `test_background_renders`,
`test_deck_settings*`, `test_commands`, `test_menu_bar_gui` and `test_accessibility_gui`). Without the plugin,
the deck keeps its comment and compiles the same.

Release **v9.1.0** together with `campusonline` 1.0.0 (`requires_slidemage = ">=9.1"`). It has a `BREAKING:`
paragraph, so auto-update asks first. The catalogue lists 1.0.0 before this ships.

### Phase 3: the core becomes provider-neutral (Stefan)

**3.1** The `AiRoute` registry (2.3). `ai_profile` and `resolver` ask it; Ollama, Claude Code and the API
register themselves from inside core. No visible change.

**3.2** The AI tab with sections (`add_settings_section(page="ai")`); the Cloud and Ollama tabs become sections.

**3.3** Rename the task code out of `claude_*`: `ai/tasks.py`, `ui/workspace/task_bubbles.py`, and the
`test_claude_tasks*` tests with them.

**3.4** The "no route" states: disabled sides, "Install a plugin…" on the Images page, in the chat and in the
bubbles.

### Phase 4: Anthropic without the SDK (Jürgen; done first)

Decided 2026-10-27 (Jürgen):
- Replace the SDK rather than keep it bundled in core (A) or drop the API route (D). Claude Code never used
  the SDK; only the API route does.
- Jürgen writes it, now, ahead of phases 1–3: nothing depends on it.
- If it turns out much harder than expected, fall back to dropping the API route, not to bundling the SDK.

**4.1** The stdlib client in `ai/anthropic_provider.py`, behind today's `AnthropicProvider` interface (Claude
handover §4). It must cover:
- streamed text, stop_reason, and usage with cache tokens;
- tool use, assembling the `input_json_delta` pieces;
- raw blocks handed back unchanged in the next turn (thinking blocks with signatures);
- images, `cache_control` and `output_config.effort`;
- two retries on 429/5xx/529 and dropped connections, honouring `retry-after`;
- the error messages per status;
- `/v1/models` with pagination;
- `abort()` by closing the socket;
- unknown SSE events ignored.

Recorded streams are the fixtures. Then drop `anthropic`, `pydantic`, `httpx` and the spec's
`collect_submodules("anthropic")`.

### Phase 5: Ollama plugin (Stefan; see the Ollama handover)

**5.1** `slidemage-plugin-ollama`: `OllamaProvider`, model management and the Ollama section, registered as the
`ollama` route.

### Phase 6: Claude plugin and the cut

**6.1** Split the terminal service and the external-edit watch from the Claude Code session (`host.terminal()`),
and add `add_entry_point`.

**6.2** `slidemage-plugin-claude` (Claude handover §5 and §6):
1. Run `filter-repo`.
2. Lay out the repository.
3. In `activate`: two `add_ai_route` calls, `add_settings_section(page="ai")` and
   `add_entry_point("hook")`.

`claude_launch` builds the hook command from `entry_point_command`. Core keeps `--claude-hook` as an alias
for one major version, for Claude Code sessions started by an older SlideMage.

**6.3** Cut from core everything Claude and Ollama, with their tests (Claude handover §2). The settings and the
key are found in their old places (2.4).

### Phase 7: the AI-free core

Release **v10.0.0** together with `claude` 1.0.0 and `ollama` 1.0.0 (both `requires_slidemage = ">=10.0"`),
both listed before it ships. The first start offers each person the plugins they used.

**Done when:**
- With the plugins: everything works as today. That means Claude Code's terminal, tasks, images, Switch now,
  scope and hooks; the API; Ollama and its model management; and CampusOnline. Existing users keep their key,
  connection, models and course links.
- Without them: the AI switch says "Install a plugin…", and nothing else names Claude, Ollama or CAMPUSonline.
- Each plugin's tests pass against the oldest and newest SlideMage its `requires_slidemage` allows.

## 4. Open

1. **Stefan's original plan:** diff it against this one when it turns up. In particular, compare his §2.3 (SDK
   assessment) and §2.4 (the `AiRoute` sketch) with 2.3 here.
2. **The Ollama handover:** not seen. Phase 5 is a placeholder.
3. ~~Who writes the stdlib Anthropic client~~: Jürgen, first (phase 4).
4. **CampusOnline handover §7:** Jürgen to decide the repository owner, a Settings tab, and what goes in the box.
5. **Install from file:** anything that passes the checks (planned), or only ids in the catalogue?
6. ~~Which repository the `filter-repo` commands clone~~: done from `stpalan/SlideMage` (the handover's
   `JuergenFleiss/slidemage.git` doesn't exist).
7. **From the CampusOnline plan, for Stefan:**
   - The template's `build.py --check` misses relative imports that leave the package (`from ..x import`).
   - Bundle the whole stdlib (2.5), or offer an HTTP GET helper in `plugin_api` that also handles proxies and
     certificates?
