# Plugins: the rest of the plan, implementation

Status: plan, 2026-10-28. Covers what remains of `docs/PLUGINS_PLAN.md` (draft 3) after phases 0, 1 (PR #21) and 4
(PR #20): phases 2, 3, 5, 6, 7 and 8. Stefan leaves the plugin API to us until it is done, so all of it is ours,
including the Ollama plugin. Steps run without pausing, as many in parallel as touch separate files; each is
reviewed and committed by the orchestrator. Creating public repositories, releases and the website registry pull
requests wait for Jürgen's go.

## Branches and repositories

| Work | Where | Base | PR |
|---|---|---|---|
| Phase 3 (AI route registry) and phase 6's core part (the host API for AI plugins, terminal service, entry points) | `feature/ai-routes`, worktree `.worktrees/ai-routes` | `feature/plugin-host` + `feature/anthropic-stdlib` (both merged in) | stacked on #20 and #21 |
| Phase 2, core part (CampusOnline out) | `feature/campusonline-out`, worktree `.worktrees/campusonline-out` | `feature/plugin-host` | stacked on #21 |
| Phase 7 (AI-free core) | `feature/ai-free-core` | `feature/ai-routes` | stacked |
| Phase 8 (manual, changelogs) | on the branches above | | |
| CampusOnline plugin, step 5 (onto `plugin_api`) | `~/github/slidemage-plugin-campusonline`, branch `plugin-campusonline` | | its repository |
| Claude plugin | `~/github/slidemage-plugin-claude`, branch `plugin-claude` (history filtered from `feature/anthropic-stdlib`) | | its repository |
| Ollama plugin | `~/github/slidemage-plugin-ollama`, branch `plugin-ollama` (history filtered) | | its repository |

Version numbers: phase 2's release removes a feature, so it is **v9.0.0** with a `BREAKING:` paragraph and a
`compat.py` entry; phase 7's is **v10.0.0**, likewise (as the handovers have it; the renumbering for publication
in the handover's section 6 is Stefan's decision and would be applied at release). Branches renumber at merge.

## Phase 3: AI routes in a registry (plan §2.4)

Goal: no core module outside the three route implementations names Ollama, Claude Code or the Anthropic API.
Today's routes keep working, registered from core. Then phase 6 moves two of them into a plugin and phase 5 the
third.

**3a. The registry (`ai/routes.py`) and the routes as modules.**

- `AiRoute` (in `plugin_api`, re-exported for core) following §2.4: `id`, `service`, `is_local`, `tasks`,
  `problem(ctx, task)`, `model_choices(ctx, task)` (fast, never the network), `default_choice(task)`,
  `choice_label(choice)`, `provider(ctx, route)` (or None), `draft_backend`, `translation_backend`,
  `slide_translator` (None → core wraps `provider`), `task_runner(ctx, route)` (None → core's
  `provider_tasks`; Claude Code runs its own `claude -p`), `chat_surface(...)` (None → the core chat view;
  Claude Code → its terminal, with `stop()` and `restart(choice, continue_conversation)` for Switch now), and
  `settings_section` (a builder for the AI tab).
- Route ids `ollama`, `claude_code`, `anthropic_api`. Stored settings read `local` as `ollama` and `api` as
  `anthropic_api` until the next write.
- `ai_profile`'s mode, policy, per-task models and `resolve()` work over registry ids. `cloud_conn` becomes "which
  cloud route".
- `resolver.py` asks the route, and keeps its rule of never falling back silently.
- The three routes become modules registered from core at start:
  - `ai/ollama_route.py`: `OllamaProvider`, the host setting, `ollama_admin` use;
  - `ai/claude_code_route.py`: `claude_launch`, `claude_runner`, `claude_images`, the terminal session as
    `chat_surface`;
  - `ai/anthropic_api_route.py`: `anthropic_provider`, `credentials`.

**3b. The UI over the registry.**
- Switch and setup: the AI switch, AI setup, the assistant header, `ai_route.py`, `ai_switch.py`.
- Pickers and tasks: `ui/ai_models.py`, the Images page pickers, `add_slide`'s translation, the task cards and
  bubbles (`terminal/tasks.py` → `ui/workspace/task_bubbles.py`, `ai/claude_tasks.py` → `ai/tasks.py`).
- Side states: one side with no route shows "Install a plugin…". With no route at all, the assistant, the AI menu,
  every AI command and the AI hints hide.

**3c. The AI tab with sections.**
- Settings' AI, Cloud, Ollama and Prompts tabs become one AI tab (policy, cloud route, models per task, prompts)
  plus one section per route that has `settings_section`: Ollama is today's Ollama tab, and Claude is today's
  Cloud tab with the Claude Code status.
- `plugin_api` gains `add_settings_section(page="ai", title, build)`.

**3d (phase 6's core part). The host API for AI plugins.**
- `add_ai_route(route)`.
- `ai_tools()`: the agent's ToolBox, for an MCP server.
- `terminal()`: the embedded terminal service, split from the Claude Code session. `pty_process.py`,
  `terminal/web.py`, `theme.py` and the xterm assets stay core.
- The external-edit watch as a host service (`project_watch`, `terminal/sync.py`).
- `credentials(plugin_id)`: environment, keychain or file, finding the old Anthropic key places.
- `add_entry_point(name, fn)` with `SlideMage --plugin <id>:<name>` in `cli.py`, and `--claude-hook` kept as an
  alias for one major version.
- The neutral AI types re-exported: `ChatProvider`, `ChatReply`, `ProviderError`, `Cancelled`, the agent types,
  the task definitions, the image backend protocols, `protected_regions` (read), and the focus (deck, slide,
  scope).
- `API_VERSION` stays 1 (only additions).

## Phase 2: CampusOnline out (plan §3, phase 2)

**2a. Core.**
- Remove `course_schedule.py`, `admin_slides.py` and `ui/dialogs/admin_slides.py`.
- Remove the course-link parts of `deck_scan`, `deck_settings` and `deck_editor`, the "Course page" field, the
  `admin_slides` command and its Deck menu entry, and the core `session_soon` rule, with their tests.
- A deck keeps its `%% SlideMage course URL:` comment untouched and compiles the same.
- Turn on the upgrade preselection for CampusOnline. Add the project hint ("This project uses CampusOnline course
  links. Install the plugin…").
- Release v9.0.0, with a `BREAKING:` paragraph and a `compat.py` entry.

**2b. The plugin onto `plugin_api`** (its plan's step 5):
- import from `slidemage.plugin_api` instead of `campusonline/host.py`'s Protocol;
- `bridge/` deleted;
- tests run against the host of `feature/plugin-host` (`PYTHONPATH` pointing at its `src`), and `FakeHost` kept
  for the unit tests;
- `requires_slidemage` set to the release of 2a.

## Phase 5: the Ollama plugin

**5a. Repository.**
- Filter `ai/ollama_admin.py`, `ui/dialogs/settings_ollama.py`, `ai/ollama_route.py` (after 3a) and their tests
  out with their history.
- Adopt `stpalan/slidemage-plugin-template`.
- Layout `ollama/{__init__,provider,admin,route,settings}.py`, with `bridge/` for what still needs SlideMage
  internals.

**5b. Onto the AI host API** (after 3d):
- `activate(host)` registers the route and the AI tab section;
- the settings move from the old keys (`ollama_host`, `ai_models.local`);
- `needs`: "Ollama installed"; `network`: "the Ollama server you set (by default on this computer)".

## Phase 6: the Claude plugin (Claude handover)

**6a. Repository** (done: history filtered from `feature/anthropic-stdlib`).
- Adopt the template, and lay out `claude/{__init__.py, api/, code/, credentials.py, settings.py}` as the
  handover's section 6 says.
- What still needs SlideMage internals goes in `bridge/`.
- Tests split into the plugin's own (run anywhere) and the bridge's.

**6b. Onto the AI host API** (after 3d):
- two `add_ai_route` calls, the AI section, `add_entry_point("hook")`;
- `claude_launch` builds the hook command from `entry_point_command`;
- the settings and the key are found in their old places.

## Phase 7: the AI-free core (after 3, 5b, 6b)

- Delete the three route modules and everything only they used from core, with their tests (they live in the
  plugins now).
- Turn on the upgrade preselection for Claude and Ollama, and the project hint for an AI policy.
- GUI tests run with no AI plugin.
- Release v10.0.0, with a `BREAKING:` paragraph and a `compat.py` entry.

## Phase 8: manual and changelogs

- A "Plugins" chapter in the manual deck: what plugins are, installing, the first-start sheet, Settings → Plugins,
  privacy, writing one (with a link to the template).
- The README's plugins section.
- Each plugin's CHANGELOG in the app's format.
- A copy of `release_notes.py` in the template (a pull request to Stefan's template, offered in the handover).

## Waves

| Wave | In parallel | Agent |
|---|---|---|
| 1 | 3a · 2a · 2b · 6a · 5a's extraction | Sonnet · Sonnet · Sonnet · Sonnet · orchestrator (filter-repo) + Haiku (layout) |
| 2 | 3b · 3c · 3d | Sonnet ×3 (3b and 3c in separate files; 3d after 3a) |
| 3 | 5b · 6b | Sonnet ×2 |
| 4 | 7 · 8 | Sonnet · Haiku |
