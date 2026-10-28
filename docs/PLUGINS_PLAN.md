# Plugins plan

Status: draft 3, 2026-10-28. Draft 2 (Stefan, 2026-10-26) is sections 1–5 unchanged; section 6 is what changed
since then: the website's answers, decisions, and the work done. Each phase needs the user's go before it
starts; pause after each committed phase. The website side is in
`docs/Handover_2026-10-26-Plugins-For-Website.md`.

Goal: three features that ship in SlideMage today become plugins. SlideMage ships no plugin; on first start it
offers to download some. A plugin lives in its own GitHub repository, and the SlideMage website lists them.

- **Claude**: Claude Code (the terminal in the assistant, one-shot `claude -p` tasks, the MCP server) and the
  Anthropic API.
- **Ollama**: the local models and their admin (host, pull, remove).
- **CampusOnline**: a deck's course link, the admin slides (title slide, course-sessions table) and "a session
  is soon" for background renders.

An installed plugin can show a box in the right column, add menu entries, add a tab or section to the Settings
window, and add a tab to the Deck settings sheet.

## 1. What exists today

### CampusOnline: small and already separate

| Piece | Where | Moves to the plugin |
|---|---|---|
| REST client, parsing, LaTeX rendering | `course_schedule.py` (454 lines, stdlib only) | yes |
| Admin slides logic | `admin_slides.py` | yes |
| Admin slides tab of the Deck settings sheet | `ui/dialogs/admin_slides.py`, `ui/dialogs/deck_settings.py:65` | yes |
| "Admin slides…" command, Deck menu | `ui/workspace/actions.py:77,302`, `deck_actions.py:32,194`, `menus.py:150` | yes |
| The course link of a deck: the preamble comment `%% SlideMage course URL: …` | `deck_scan.py:55,249` (`Deck.course_url`), `deck_settings.py` (field and its write), `deck_editor.py:382-423` (normalise, write), the "Course page" field and Open button of Deck settings (`ui/dialogs/deck_settings.py:151,276`) | yes, see below |
| Render priority before a session | `background_renders.py:212` (`session_soon`) | yes, through a hook |

The course link goes with the plugin. Nothing outside the CampusOnline code reads it: not the LaTeX framework,
not the QR codes, not the compiler. It is a comment in the preamble, so a deck keeps it as plain text while the
plugin is absent and compiles the same. The deck group "Course deck" (`deck_groups.TAG_COURSE`) is a core
concept and stays; the plugin only uses it to decide when Admin slides is offered.

### AI: large and woven through the core

About 12,000 lines across `ai/`, `ui/workspace/{ai_*,assistant*,chat/,terminal/}`, `ui/ai_models.py` and the
Settings tabs AI, Cloud, Ollama and Prompts. Core features call AI: image descriptions (`alt_draft.py`), slide
translation (`slide_add.py`), the syntax check, the AI review, rename and outline, the image pages, the task
cards. All of them ask `ai_profile.resolve()` and run on what `ai/resolver.py` returns.

The seam already exists (`providers.ChatProvider`, the neutral `agent_types.py`, the provider-neutral
`agent.py`, the single resolver), but the three routes are hard-coded: `LOCAL`, `CLAUDE_CODE`, `API` in
`ai_profile.py`, `Route.name`, `SERVICES`, `resolver.provider_for()`, and 26 non-AI files that name Ollama.

## 2. Decisions

### 2.1 What a plugin is

A Python package loaded in-process, with a manifest, that registers contributions with the host through one
stable facade, `slidemage.plugin_api`. In-process because every plugin here contributes Qt widgets.

```
slidemage-plugin-campusonline/            its own GitHub repository
  plugin.toml                             id, name, version, api_version, requires_slidemage, summary,
                                          author, homepage, license, needs, network (fields and rules: the
                                          website handover, section 3)
  campusonline/__init__.py                def activate(host: PluginHost) -> None
  campusonline/...                        the plugin's modules, assets
  tests/                                  run against SlideMage's plugin_api in CI
  CHANGELOG.md, LICENSE, README.md
```

A release is a zip, `campusonline-1.2.0.smplugin`, attached to the repository's GitHub release.

- `api_version` is an integer SlideMage bumps on a breaking change of `plugin_api`; a plugin naming another one
  is listed as "needs SlideMage x.y" and not loaded. `requires_slidemage` is a version range.
- Plugins import only `slidemage.plugin_api`, the stdlib, PySide6 and their own vendored pure-Python code. Core
  never imports a plugin. A test in core checks the second; the plugin template's lint checks the first.
- A plugin that raises in `activate()` is disabled for the session and named in the Plugins tab, never a crash
  at start.
- Installed plugins live in `config_dir()/plugins/<id>/`, unpacked. Enabled / disabled is per machine.

### 2.2 The frozen-build constraint

SlideMage ships as a PyInstaller build with no pip inside. A downloaded plugin can only use what the build
contains plus pure-Python code it carries. A compiled module in a plugin would have to match the build's Python
version and platform exactly.

- Ollama, CampusOnline: stdlib already. No issue.
- Claude Code terminal: needs QtWebEngine and a pty (pywinpty / ptyprocess). Both are native, so they stay in
  core as a generic embedded terminal service (run a command in a pty, show it). The Claude plugin decides what
  runs there. A SlideMage without the Claude plugin still carries QtWebEngine; dropping it would need a second
  build flavour, not worth it now.
- Anthropic API: uses the anthropic SDK, which needs the compiled `pydantic_core`. See 2.3.

### 2.3 Replacing the Anthropic SDK: does it cost functionality?

No user-visible functionality is lost, if the replacement covers what `AnthropicProvider` uses today
(`ai/providers.py:475-635`). The SDK is used as a transport only; prompts, tools and messages are already plain
dicts. What a stdlib client (`http.client` + server-sent events, like the Ollama provider) has to reproduce:

| SDK feature used today | Replacement |
|---|---|
| `messages.stream`: text deltas, the final message | parse the SSE events (`message_start`, `content_block_start/delta/stop`, `message_delta`, `message_stop`) |
| tool use: the streamed `input_json_delta` pieces assembled into the tool input | concatenate per block, `json.loads` at `content_block_stop` |
| `raw=message.content` handed back in the next turn (thinking blocks with signatures, tool_use blocks) | keep the blocks as the dicts they came in as; send them back unchanged |
| prompt caching, `output_config.effort`, images, usage incl. cache tokens | plain request fields and response fields; no change |
| `max_retries=2` with backoff on 429, 5xx, 529 and dropped connections | a small retry loop that honours `retry-after` |
| typed errors mapped to messages (`_translate`) | map on the HTTP status and the error body instead |
| `models.list` with pagination | follow `has_more` / `last_id` |
| `abort()` from another thread by closing the socket | the same `_shutdown_socket` the Ollama provider uses |
| TLS with the SDK's bundled certificates | stdlib `ssl.create_default_context()`; the updater and CampusOnline already reach HTTPS this way in the frozen builds |

What does change:

- **Maintenance.** The SDK follows new API features by itself. With our own client, a new API feature we want
  (a new block type, a new beta header) is written by hand. The client touches only what SlideMage uses, so
  this is small, but it is ongoing.
- **Edge cases** the SDK handles silently (an event type the client does not know, a stream cut mid-block) need
  tests. Unknown event types must be ignored, not fatal.
- **Benefits:** the plugin is pure Python and installable into any build; the app loses `anthropic`, `pydantic`,
  `pydantic_core`, `httpx` and friends (smaller download, faster first AI request, no `collect_submodules` hack).

Recommendation: do it, in core first behind the existing `AnthropicProvider` interface, with recorded SSE
streams as test fixtures, before moving it into the plugin.

### 2.4 AI routes in a registry; the AI features stay in core

The AI features (chat, image descriptions, translation, fixes / notes / transcripts, task cards, agent tools,
prompts) are SlideMage features, not Claude's or Ollama's. They stay in core as the AI layer. Plugins contribute
routes:

```python
class AiRoute(Protocol):
    id: str                       # "ollama", "claude_code", "anthropic_api"
    service: str                  # "Ollama", "Claude Code", "Anthropic API"
    is_local: bool                # nothing leaves the machine: it belongs to Local, otherwise to Cloud
    tasks: frozenset[str]         # which of ai_profile.TASKS it can answer
    def problem(self, ctx) -> str: ...                       # "" or why it cannot run now
    def models(self, ctx, task) -> list[str]: ...
    def provider(self, ctx, route) -> ChatProvider | None    # None: no chat provider (Claude Code)
    def draft_backend(self, ctx, route) -> ...               # image pipeline
    def translation_backend(self, ctx, route) -> ...
    def chat_surface(self, ...) -> QWidget | None            # None: the core chat view; Claude Code: its terminal
```

The Claude plugin registers two routes, the Ollama plugin one. `ai_profile` keeps mode, policy, per-task models
and `resolve()`, over registry ids instead of three constants.

The wording stays "Local | Cloud". Underneath, Local is "the routes with `is_local`" and Cloud the others;
`cloud_conn` becomes "which cloud route". With only Local or only Cloud routes installed, the other side of the
switch is shown disabled with "Install a plugin…". With no AI route, the assistant, the AI menu and every AI
command hide, and SlideMage is a complete editor without AI.

Settings keys stay where they are (`ai_settings.json`; `ai_models` keyed by route id, `local` read as `ollama`
and `api` as `anthropic_api` until the first write), so nobody loses their models or key.

### 2.5 The right column

Today the column is the panels card (top: a picker ▾ and the chosen per-slide panel such as Notes, Images,
Versions) and the assistant card (bottom), in a splitter (`side_panels.py`).

A plugin box goes to one of two places, decided by the size the plugin declares, never by the plugin naming a
place:

```python
host.add_sidebar_box(id, title, factory: Callable[[WindowApi], QWidget], *,
                     size: Literal["compact", "large"], when: Callable[[DeckApi], bool] = always)
```

| | `size="compact"`: in the panel picker | `size="large"`: in the dock |
|---|---|---|
| For | a few facts and buttons about the deck or slide, glanced at now and then | a working surface used for minutes at a time, next to the slide panels |
| Where | an entry of the top card's ▾ picker, below the slide panels after a separator headed "Plugins" | a box in the bottom card, which today holds only the assistant |
| Height | the top card's: 38 % of the column by default, at least 128 px; the content must fit one 64 px row and scroll beyond | the bottom card's: at least 380 px |
| Shown with | replaces the slide panel while chosen | the slide panel above stays visible |
| Example | CampusOnline: the deck's course, next session (date, time, room), Open course page, Admin slides… | the assistant (core); a future plugin with a large surface |

Rules of the dock:

- The assistant is the dock's first box, present while an AI route is installed.
- One box in the dock: no switcher, the column looks exactly as today. Two or more: the bottom card's header gets
  a segmented switcher (assistant first, then plugins in install order); the choice is remembered in
  `layout_settings` like the panel picker's.
- No box in the dock (no AI plugin, no large plugin box): the bottom card is hidden and the top card takes the
  column. "Focus assistant" becomes "Focus" and applies to whichever dock box is shown.
- A running assistant (a streaming answer, a Claude Code terminal) keeps running while another dock box is shown;
  the switcher marks it with the same busy dot the assistant header uses.

Rules of the picker:

- Plugin entries keep their own remembered choice like the panels do; the picker's summary line ("a few facts
  about the slide") comes from an optional `summary(deck, slide) -> str` of the box.
- `when` hides an entry, for CampusOnline a deck without a course link. If the shown entry is hidden, the picker
  goes back to the slide panel shown before it, and returns to the plugin box when it is offered again.

Both places give a box the same narrow window facade (focused deck and slide, their change signals, run a
command, show a message), never `WorkspaceWindow`, so a box can be moved between them by changing its size in a
plugin release. User-driven moving ("Move to dock") is not in v1.

The two AI plugins add no box; they feed the one assistant: its model chip, its Local | Cloud switch and, for
Claude Code, its terminal.

### 2.6 Settings: a shared page for the two AI plugins

Yes, but core owns the page. A page two plugins co-own has no owner: it exists only while one of them is
installed, its layout depends on install order, and a version mismatch between them breaks it. Instead:

- **AI tab** (core, shown when any AI route is installed): Local | Cloud policy of the project, which cloud route,
  the model per task (from every installed route), and the prompts (today's Prompts tab is provider-neutral).
- Each AI plugin adds a section to it: Ollama (host, installed models, pull and remove; today's Ollama tab),
  Claude (API key, today's Cloud tab; Claude Code found or not).

That turns today's AI, Cloud, Ollama and Prompts tabs into one or two.

A new core **Plugins tab**: installed plugins with version, enabled switch (takes effect after a restart in v1),
update, remove, "Install from file…", "Browse plugins…" and what each plugin contacts on the network.

CampusOnline gets a Settings tab only if it has settings; its per-deck UI is a Deck settings tab (2.7).

### 2.7 Extension points

| Extension point | Used by |
|---|---|
| `add_command(id, title, scope, run, enabled, shortcut=None)`: palette, shortcuts | all |
| `add_menu_entry(menu, command_id, section=None)`: into an existing top-level menu (File, Edit, Deck, Slide, View, Build, AI, Housekeeping, Help), in a section of its own named after the plugin unless `section` names one; Submenu supported | CampusOnline (Deck → Admin slides…, Open course page) |
| `add_menu(title, sections)`: a new top-level menu, placed before Help | any plugin with many commands |
| `add_settings_tab(title, factory)` / `add_settings_section(page="ai", title, factory)` | CampusOnline (if needed), Ollama, Claude |
| `add_deck_settings_tab(title, factory)`, including a footer action ("Insert slides") and the dirty state | CampusOnline: one tab "Course" with the course link, Open, and the admin slides |
| `add_deck_marker(name)`: read and write a `%% SlideMage <name>: …` preamble comment through the host's deck editing (undo, expected-text checks) | CampusOnline course link |
| `add_render_priority(fn: deck -> bool)` | CampusOnline `session_soon` |
| `add_sidebar_box(...)` (2.5) | CampusOnline |
| `add_ai_route(route)` (2.4) | Ollama, Claude |
| `settings(plugin_id)`: namespaced per-machine storage; `credentials`: keyring or file (from `ai/credentials.py`) | all |
| `terminal()`: the embedded terminal service | Claude Code |
| `ai_tools()`: the agent's ToolBox, for the MCP server | Claude Code |
| `run_in_background`, `log`, `show_message` | all |

Menu entries follow the declarative `MENU_BAR` of `menus.py`: plugin entries are merged into it at start, so the
palette, the shortcuts list and the menu bar stay consistent. The AI menu itself is core; it is shown while an AI
route is installed.

Keep the API this small in v1; add points when a plugin needs them.

### 2.8 Nothing bundled: first start and upgrades

- **First start** (no `plugins/` folder and no "plugin offer seen" flag): a sheet lists the catalogue's plugins
  with a one-line summary, what each needs (Ollama installed, Claude Code or an API key, a CAMPUSonline course)
  and what it contacts on the network. The plugins the catalogue marks `recommended` (Claude and Ollama) come
  first under "Recommended", with a line on what they add ("AI help with image descriptions, translation, fixes
  and a chat about your slides"), the rest under "More plugins". Recommended means listed first and marked, not
  preselected: Ollama does nothing without Ollama installed and Claude sends slides to the cloud, so the user
  ticks them. The sheet's footer links to the website's plugin page ("See all plugins and what they do"), and
  each plugin's "More…" to its own page. Buttons: "Install selected", "Not now". The Plugins tab and Help →
  Plugins… offer the same list later.
- **Offline**: the sheet says the list could not be loaded and offers "Install from file…".
- **Upgrade** from a SlideMage that still had the features built in (this matters most): the first start of the
  release that removed a feature checks whether it was in use and preselects its plugin, with the reason: an API
  key or a Claude Code route in `ai_settings.json` → Claude; Ollama models chosen → Ollama; any deck with a
  course link → CampusOnline. Without this, an update would silently remove features people use.
- **Project hints**: opening a project whose decks carry a course link, or whose `project.json` sets an AI
  policy, while the matching plugin is missing shows one dismissible line: "This project uses CampusOnline course
  links. Install the plugin…".
- **Updates**: the updater checks plugin updates in the same pass as its own, from the catalogue. A SlideMage
  update that bumps `api_version` lists which installed plugins have a compatible release and holds the update
  back (in "ask" mode) if one does not yet.

### 2.9 Repositories and releases

- One repository per plugin, each on its owner's account: `slidemage-plugin-claude` and
  `slidemage-plugin-campusonline` (Jürgen Fleiß), `slidemage-plugin-ollama` (Stefan Palan), plus
  `slidemage-plugin-template` with the manifest, the CI workflow and the lint rule.
- Code moves with `git filter-repo` so each plugin keeps the history of its files.
- Plugin CI: tests against the oldest and the newest SlideMage its `requires_slidemage` allows (SlideMage checked
  out at those tags), builds the `.smplugin` and attaches it with its SHA-256 to a GitHub release.
- Core keeps contract tests with a fake plugin in `tests/`, and a test that the plugin API's public names do not
  change without an `api_version` bump.
- The catalogue (`index.json`) is built by a scheduled job in the website repository (Stefan's account, GitHub
  Pages) from the releases of the approved plugins: approval is a reviewed pull request adding the plugin to the
  website's registry. The builder pins each release's SHA-256 when it first sees it. The app hard-codes only the
  catalogue URL, `https://<domain>/plugins/index.json`; the custom domain must be chosen before phase 1 ships.
  Details in the website handover.
- For development, `SLIDEMAGE_PLUGIN_PATH` points SlideMage at plugin checkouts; they load like installed ones.
- A plugin runs with the user's rights. The app installs from the catalogue only files whose SHA-256 matches and
  warns on "Install from file…". Signatures come later.

## 3. Phases

Rough cost uses the usual calibration (~5 % of a 5-hour window per ~100k agent tokens). Nothing is released
without its plugin: a feature leaves core only in the release whose first start can install it again.

**Phase 0: plugin host** (~200k tokens). `slidemage/plugins/` (loader, manifest, registry, enable / disable),
`slidemage/plugin_api.py` (versioned facade), menu and command merging, Settings and Deck settings tab hooks, the
Plugins tab, `SLIDEMAGE_PLUGIN_PATH`, the core boundary test, a fake plugin in `tests/` (load, failing activate,
wrong `api_version`).

**Phase 1: installing** (~150k tokens). Catalogue client, download with SHA-256 check, unpack, "Install from
file…", the first-start sheet, the upgrade preselection, plugin updates in the updater. Needs the catalogue URL
and format agreed with the website (the handover). The website side publishes a hidden test catalogue,
`plugins/index-test.json`, with the sample plugin `hello`, which the installer's tests use.

**Phase 2: CampusOnline plugin, first release without a built-in feature** (~200–300k tokens). Jürgen's
repository (`docs/Handover_2026-10-26-CampusOnline-Plugin.md`); he can create it and extract the code before
phase 0 is done, and wire it to `plugin_api` once it exists. The core side of this phase removes the code from
SlideMage. Moves `course_schedule.py`, `admin_slides.py`, `ui/dialogs/admin_slides.py`, the course-link code of
`deck_scan` / `deck_settings` / `deck_editor` and the Deck settings field, and their tests. The plugin adds the
"Course" Deck settings tab, the Deck menu entries, the sidebar box and the render priority. Done when: without
the plugin, no trace of it in the UI and decks with a course link compile and save unchanged; with it,
everything works as today; an upgraded install that had course links is offered the plugin.

**Phase 3: AI route registry, inside core** (~400–600k tokens, the big one). No plugin yet. 3a resolver and
profile on `AiRoute`, today's three routes registered from core; 3b UI (assistant, chat view, image pages, task
cards, the 26 Ollama-naming files); 3c the AI tab with sections. Done when no core module outside the three
route implementations names Ollama, Claude Code or the API.

**Phase 4: stdlib Anthropic client, inside core** (~100–150k tokens). 2.3, with recorded streams as fixtures;
drop `anthropic` from `pyproject.toml` and the spec.

**Phase 5: Ollama plugin** (~100k tokens). New repository; move `OllamaProvider`, `ollama_admin.py`,
`settings_ollama.py`, the route.

**Phase 6: Claude plugin** (~250–350k tokens). Split the embedded terminal service (core) from the Claude Code
session (plugin); new repository; move `claude_*.py`, `mcp_server.py`, the terminal session, the API route and
the Claude settings section.

**Phase 7: AI-free SlideMage** (~100k tokens). No AI plugin: the assistant, the AI menu, every AI command and AI
hints in dialogs disappear; image descriptions and translation keep their manual paths. GUI tests run with no
plugin. Phases 5–7 release together, so no release has the AI half removed.

**Phase 8: manual and changelogs.** A "Plugins" chapter in the manual; each plugin carries its own CHANGELOG in
the app's format, checked by a copy of `release_notes.py` in the template.

Order: 0 → 1 → 2 (release) → 3 → 4 → 5 → 6 → 7 (release) → 8. Phase 3a can start in parallel with phase 2
(different files).

## 4. Risks

- Plugin API churn across four repositories: keep the facade narrow, `api_version` honest, and the template's CI
  testing against two SlideMage versions.
- Losing features on update: the upgrade preselection (2.8) and the rule that no release removes a feature its
  first start cannot reinstall.
- First start needs the network for anything beyond plain editing; offline users get "Install from file…".
- Arbitrary code: catalogue with hashes now, signatures later.
- Python version of the build: pure-Python plugins survive it; a plugin that ever needs a compiled module needs
  per-platform builds and a `python_abi` field.

## 5. Decided

- One Claude plugin with two routes, Claude Code and the Anthropic API, and one Claude section in the AI tab.
- The first-start sheet recommends the AI plugins and links to the website (2.8).
- Box placement by declared size: compact in the panel picker, large in the dock (2.5).
- Owners, each with a handover:
  - CampusOnline: Jürgen Fleiß, `docs/Handover_2026-10-26-CampusOnline-Plugin.md`;
  - Claude: Jürgen Fleiß, `docs/Handover_2026-10-26-Claude-Plugin.md`;
  - Ollama: Stefan Palan, `docs/Handover_2026-10-26-Ollama-Plugin.md`;
  - the website side: `docs/Handover_2026-10-26-Plugins-For-Website.md`.
- So that the plugins' history extracts cleanly, phase 3 puts the Ollama route and provider in
  `ai/ollama_route.py` and phase 4 the new Anthropic client in `ai/anthropic_provider.py`.

## 6. Since draft 2 (2026-10-27/28)

### 6.1 The website side is live (its answer of 2026-10-27)

| Item | Value |
|---|---|
| Catalogue URL to hard-code | `https://slidemage.org/plugins/index.json` (final; no plugins listed yet) |
| Test catalogue | `https://slidemage.org/plugins/index-test.json`: `hello` 0.1.0 only, SHA-256 `a72af2022f7b2a5b161964d6e55376815e76be50c8645e2d02ee2dc7358c00f9`, 12357 bytes. GitHub also has `hello` 0.2.0 (replaced asset, yanked), 0.3.0 (pre-release) and 0.4.0 (wrong asset name, marked "Latest"): none may ever be offered, so **the app reads the catalogue, never "latest release"**. Hidden plugins have no page (`/plugins/hello/` is a 404) |
| Schema | copy `schema/plugins-index.schema.json` from `stpalan/slidemage-website`, not from the handover; served at its `$id` `https://slidemage.org/schema/plugins-index-1.json` |
| Pages the app opens | `https://slidemage.org/plugins/`, `…/plugins/<id>/` (stable). The old `stpalan.github.io/slidemage-website/…` answers 301; don't hard-code it |
| Package folder | the id with `-` as `_`; `activate(host)` in its `__init__.py`. The loader uses the same rule |
| Refused by the builder | `.pyc .pyo .so .pyd .dll .dylib .exe` in the asset; a release without `README.md` and `CHANGELOG.md` at its tag. `.sha256` asset: `sha256sum` format |
| Themes | later, in the same catalogue (a top-level `"themes"` list, installed through the plugin installer, still `schema: 1`), once the framework redesign defines the theme package. **The catalogue client ignores unknown top-level fields from its first release** |
| Template | `stpalan/slidemage-plugin-template`; once `plugin_api` has its first real shape, the template's `example/__init__.py` and README must show it: tell the website side |

### 6.2 Phase 4 decided and started ahead of the order

Decided 2026-10-27 (Jürgen): replace the SDK, as 2.3 recommends. The alternatives weighed were keeping the SDK
bundled in core for the plugin to import (an exception to the import rule, and the plugin tied to the SDK
version core ships) and dropping the API route (Claude Code never used the SDK). Jürgen does it now, ahead of
phases 0–3: nothing depends on it. Fallback if it proves much harder: drop the API route, not bundle the SDK.

Done on branch `feature/anthropic-stdlib` (from `feature/ai-tools-fixes`): the client in
`ai/anthropic_provider.py` (2.3's table as the checklist; v8.69.1, `cc150b8`), then `anthropic` and what came only
with it dropped from `pyproject.toml`, the spec and the third-party notices (v8.70.0, `69bf491`). `uv.lock` is
regenerated when the branch is merged (CI installs with pip).

### 6.3 The CampusOnline plugin is ahead of phase 0

Its own plan: `docs/PLAN.md` in `~/github/slidemage-plugin-campusonline`, branch `plugin-campusonline` on
Jürgen's private fork `JuergenFleiss/SlideMageS` until the public repository (its step 6). Done:

- the history filtered from `stpalan/SlideMage` `develop` (the handover's clone URL
  `JuergenFleiss/slidemage.git` doesn't exist);
- the template adopted; the package standard-library only;
- **the host interface drafted** as a `typing.Protocol` in `campusonline/host.py`, with a `FakeHost` in its
  tests: phase 0 should build `plugin_api`'s CampusOnline part to it, or say where it differs;
- the "Course" Deck settings tab (course link with Save and Open, admin slides, Insert slides as footer action),
  the compact box (title, next session with time and room, Open course page, Admin slides…), the cache keeping
  title and sessions, and the old `course-schedules.json` adopted once.

Waits for phase 0: the real `plugin_api`, then the public repository and 1.0.0.

### 6.4 Where the CampusOnline draft differs from 2.7 (for Stefan)

| 2.7 | CampusOnline's `host.py` | Why |
|---|---|---|
| `add_deck_marker(name)` | `edit_deck_text(deck, change)` plus the plugin's own `course_link.py` | a general text edit is smaller than a marker API and covers this case; it keeps undo and the expected-text check |
| `add_command(id, title, scope, run, enabled, shortcut=None)` | `add_command(id, title, run, enabled)`, `enabled(None)` when no deck is open | `scope` and `shortcut` not needed by CampusOnline; fine to add |
| `add_menu_entry(menu, command_id, section=None)` | `add_menu_entry("deck", command_id)` | the same, without `section` |
| `add_sidebar_box(id, title, factory(WindowApi), size, when(DeckApi))` | `build(deck)`, `when(deck)`, size `"compact"`/`"full"` | rename `"full"` → `"large"`; `build` taking `WindowApi` instead of a deck is fine if the facade gives the focused deck |
| `add_deck_settings_tab(title, factory)` with footer action and dirty state | `add_deck_settings_tab(title, build, footer_action=FooterAction(label, run, enabled))` | the same, made concrete |
| — | `open_deck_settings(deck, tab)` | "Admin slides…" opens the sheet on the Course tab, as today |
| — | `cache_dir()`, `legacy_cache_dir()` | the plugin's own cache, and where core kept `course-schedules.json` |
| — | `insert_positions`, `insert_slides`, `deck_language`, `open_url` | the admin slides' deck edits and the course page |
| — | widgets `Page`, `Field`, `caption` as host methods | the tab and box look like SlideMage's |

Also from the CampusOnline work:

- `add_render_priority`'s callback runs on a worker thread (`BackgroundRenders` asks there).
- The template's `build.py --check` misses relative imports that leave the package (`from ..x import`).
- The frozen build contains only the stdlib modules SlideMage itself imports: either bundle a stated set
  (all of the stdlib minus `tkinter`, `test`, `idlelib`, `ensurepip`, checked by a self-test), or offer what
  plugins need through `plugin_api` (for example an HTTP GET helper that also handles proxies and certificates).

### 6.5 Open

- Version numbers: the handovers imply v9.0 for the plugin host (`hello` and CampusOnline say
  `requires_slidemage = ">=9.0"`) and v10.0 for the AI-free core (Claude says `">=10.0"`).
- The Ollama handover: not seen on this side.
- CampusOnline handover §7: repository owner, a Settings tab (proposed: none for 1.0), what else the box shows.
- "Install from file…": anything that passes the checks with a warning (2.9), or only catalogue ids?
