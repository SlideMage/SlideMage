# Plugins: handover to Stefan, 2026-10-28

From Jürgen's side of the plugins work. It says what has been built since your handovers of 2026-10-26, the pull
requests we will open (with their drafts), and every change or addition to your plan and handovers. Status:
PRs 2 and 3 are open as drafts (#20, #21); PR 1 was merged as #19 on 2026-10-27.

Your documents this refers to: `docs/PLUGINS_PLAN.md` (your draft 2, now draft 3 with a section 6),
`Handover_2026-10-26-Plugins-For-Website.md`, `-CampusOnline-Plugin.md`, `-Claude-Plugin.md`,
`-Ollama-Plugin.md` (the last one we haven't seen).

## 0. Update, end of 2026-10-28: the whole plan is built

Everything in the plan is now implemented and in pull requests on `SlideMage/SlideMage` (the repository moved to
the organisation during the day; the old `stpalan/SlideMage` URLs redirect). Sections 1–8 below are the state of
the morning; where they differ, this section wins.

| PR | What | Base | State |
|---|---|---|---|
| #20 | Phase 4: Anthropic API without the SDK; HTTPS proxy support (`HTTPS_PROXY`/`NO_PROXY`, CONNECT, proxy auth) and Stop ending a stuck connect/TLS handshake (review findings 6, 7) | `develop` | draft |
| #21 | Phases 0–1: plugin host; all review findings on it fixed (1–5, 8, 11, and the release points: separate migration offers, self-test of the PySide6 set); `plugin_api` contract test; manual chapter and README | `develop` | draft |
| #22 | `develop`'s 8 failing GUI tests | `develop` | merged |
| #23 | Phase 2: CampusOnline out of core (v9.0.0, `Migration('campusonline', 'v9.0.0')`) | #21 | draft |
| #24 | Phases 3 and 6 (core): AI routes in a registry, the AI UI and one AI tab over them, the host for AI plugins (`add_ai_route`, `add_settings_section`, entry points, terminal service, credentials, `ai_tools`, `RouteContext`, route task leases, chat surface context, …) | #21 (+#20 merged in) | draft |
| #26 | Phase 7: the AI-free core (v10.0.0, migrations for Claude and Ollama, `--claude-hook` dispatches to the plugin); tests on shared fake routes; full suite clean apart from the font test #22 fixes | #24 | draft |

Merge order: #22 (merged), #20, #21, then #23 and #24 (both on #21), then #26. Version numbers get renumbered at merge (and
see section 6 on renumbering for publication).

**Plugins** (all on the real `plugin_api`, packaged code importing nothing else from SlideMage; `build.py --check`
passes; review findings 8–10 fixed in CampusOnline; #20's proxy and abort fixes ported into both AI plugins):

| Plugin | Where now | Next |
|---|---|---|
| CampusOnline | `JuergenFleiss/SlideMageS`, branch `plugin-campusonline` | public repository, 1.0.0 with SlideMage 9.0, registry entry |
| Claude | local repository `slidemage-plugin-claude` (history filtered) | public repository, 1.0.0 with SlideMage 10.0, registry entry |
| Ollama | local repository `slidemage-plugin-ollama` (history filtered; yours to maintain) | same |
| Template | local branch `plugin-api-1` of your template: the real API in the example, frozen-app import contract, relative-import check, a changelog checker (`release_notes.py`) | pull request to you, if you want it |

**Needed from you now:**
1. **Organisation access.** Jürgen is not a member of the `SlideMage` organisation (only a collaborator with write
   access on `SlideMage/SlideMage`), so he cannot create the plugin repositories there. Following the organisation
   proposal (5.7): please create `slidemage-plugin-campusonline`, `slidemage-plugin-claude` and
   `slidemage-plugin-ollama` in the organisation with Jürgen as admin (Ollama: you), or invite him as a member with
   repository creation allowed.
2. Review #21 and #24 as the owner of the API; the decisions taken along the way are below.
3. The version question (section 6) before #23 and #26 are released.

**Decisions taken on the way** (Jürgen said to go ahead with the recommended option):
- `edit_deck_text` instead of `add_deck_marker`; the extra host calls of 5.2; `add_*` only inside `activate()`;
  render priority on a worker thread.
- Plugin updates and removals are staged and applied at the next start; reserved plugin ids for the host's own
  folders.
- First-start onboarding and migration offers are separate (`upgrade.MIGRATIONS`); the CampusOnline project hint
  doesn't nag on the same start as its migration sheet.
- Routes: only the first local route is used (a chooser needs a design); a chat surface has no "session is live"
  property, so the switch asks before leaving any surface; route methods get a typed `RouteContext`.
- The plugin API grew by additions only (`API_VERSION` stays 1), guarded by the contract test's snapshot.

## 1. In short

- **Phase 4** (stdlib Anthropic client) is done, ahead of the order, because nothing depends on it.
- **Phases 0 and 1** (plugin host and installing) are built by us, as their own pull request from `develop`.
  Nothing built in moves out yet.
- **CampusOnline plugin**: steps 0–4 of its own plan done. It runs against the real host in an end-to-end test.
- **Where we went another way than your plan, or added to it**: section 5. Most important: `plugin_api` follows
  the CampusOnline plugin's drafted host (`edit_deck_text` instead of `add_deck_marker`, and more), and the host
  is **v8.68.0, not v9.0** (section 6).
- **What we need from you**: section 7.

## 2. Branches and repositories

| Where | Branch | Base | Commits | Version | Pushed |
|---|---|---|---|---|---|
| `stpalan/SlideMage` | `feature/ai-tools-fixes` | `develop` | 14 | v8.64.1 – v8.65.0 | merged as #19 (2026-10-27) |
| `stpalan/SlideMage` | `feature/anthropic-stdlib` | `develop` | +6 | v8.67.1 – v8.67.2 | yes, draft PR #20 |
| `stpalan/SlideMage` | `feature/plugin-host` | `develop` | 12 | v8.68.0 | yes, draft PR #21 |
| `JuergenFleiss/SlideMageS` (private fork) | `plugin-campusonline` (history of its own) | – | 6 ahead of the fork | plugin 1.0.0 (undated) | partly: up to `21665d5` |

`feature/plugin-host` is independent of the other two; the merge conflicts this causes are listed in 3.3.

## 3. Pull request drafts

### 3.1 PR 1: AI tools fixes (`feature/ai-tools-fixes` → `develop`)

Already merged as #19 (2026-10-27). Not part of the plugins work; PR 2 was stacked on it.

> **Title:** AI tools: fixes from the 2026-10-27 review (v8.64.1 – v8.65.0)
>
> Implements `docs/AI_TOOLS_FIX_PLAN.md`:
> - the Slide scope enforced in the agent tools, not only in the Claude Code hook (v8.64.1);
> - `modify_slide` edits the file it was given, and only a bare id follows the EN/DE switch (v8.64.2);
> - one source of tool guidance: the prompts keep the workflow, the tool descriptions the details (v8.64.3);
> - tool arguments checked recursively against their schema (v8.64.4);
> - one preview path through `preview_batch_output`, `insert_slide` as its own tool, the `create_slide` deck default,
>   cleanups (v8.65.0);
> - `docs/` overview of the AI tools.
>
> **Tests.** The AI tool, MCP, hook and chat tests pass. 8 GUI tests fail, the same 8 that fail on `develop`
> itself (section 8), so none of them comes from this branch.

### 3.2 PR 2 (#20, draft): Anthropic API without the SDK (`feature/anthropic-stdlib` → `develop`)

> **Title:** Plugins plan phase 4: the Anthropic API without the anthropic SDK (v8.67.1 – v8.67.2)
>
> Phase 4 of `docs/PLUGINS_PLAN.md`, brought forward because nothing depends on it. The Claude plugin must be pure
> Python, and the SDK needs the compiled `pydantic_core`.
>
> - `ai/anthropic_provider.py` (new, the path the Claude handover asks for, so its history extracts cleanly):
>   `AnthropicProvider` on `http.client` with server-sent events, a subclass of the Ollama provider's
>   `_HttpProvider`. It covers plan §2.3's table: streaming for `chat()` too; tool input from `input_json_delta`
>   pieces; thinking, redacted-thinking and unknown blocks kept as wire dicts and replayed unchanged
>   (`AssistantMessage.raw` is now a list of plain dicts); `cache_control`, `output_config.effort`, images, usage
>   with cache tokens; two retries on 408/409/429/5xx and dropped connections, only before any answer arrived,
>   honouring `retry-after` (capped at 60 s); the same error messages; `/v1/models` with pagination; `abort()`
>   during connect, backoff or a blocked read; unknown events and deltas ignored; TLS with the stdlib's default
>   context, as the updater uses.
> - `anthropic` and what came only with it (`pydantic`, `pydantic_core`, `httpx2`, `httpcore2`, `anyio`, `jiter`,
>   `sniffio`, `idna`, `h11`, `annotated-types`, `typing-inspection`, `docstring_parser`) leave `pyproject.toml`,
>   the spec and `THIRD_PARTY_NOTICES.md`; `tools/third_party_notices.py` no longer lists it.
> - `docs/PLUGINS_PLAN.md`: your draft 2 restored unchanged as sections 1–5, and draft 3's section 6 (what
>   changed since), plus this handover.
> - Claude Code is untouched: it never used the SDK.
>
> **Tests.** New in `test_agent_claude.py` and `test_ai_providers.py`: retry on 529, `retry-after`, no retry after
> streaming started, a mid-stream error event, unknown events, tool input in pieces, replayed thinking blocks,
> pagination, abort during backoff. The full suite: 3553 passed, 14 skipped, 8 failed, all 8 being `develop`'s
> own (section 8).
>
> **Before merging:** `uv.lock` is regenerated (the SDK and its dependencies are out). Check one real
> API call from a Windows release build (certificates come from the system store now, not from `certifi`).

### 3.3 PR 3 (#21, draft): the plugin host (`feature/plugin-host` → `develop`)

> **Title:** Plugins plan phases 0 and 1: the plugin host (v8.68.0)
>
> Implements `docs/PLUGIN_HOST_PLAN.md` (the step plan for phases 0 and 1 of `docs/PLUGINS_PLAN.md`). Nothing
> built in moves out: CampusOnline and the AI stay in core until phase 2 and later.
>
> - **Loading** (`plugins/manifest.py`, `loader.py`, `registry.py`):
>   - a plugin is a package with a `plugin.toml` (the website handover's rules);
>   - it is installed unpacked in `config_dir()/plugins/<id>/`, or is a checkout named by `SLIDEMAGE_PLUGIN_PATH`
>     (a checkout replaces an installed copy of the same id);
>   - it is imported under its own name (the id with `-` as `_`) from its folder, and refused when the name is
>     already importable;
>   - a failing, disabled or incompatible plugin is recorded with its reason and never stops the start.
> - **`slidemage.plugin_api`** (API 1, stdlib only): the types and the `Host` Protocol. They follow the CampusOnline
>   plugin's drafted host (section 5.2), plus `settings()`, `add_settings_tab`, `log`, `show_message`. `add_*` works
>   only inside `activate()`.
> - **Host** (`plugins/host.py`, `ui/plugin_ui.py`):
>   - services: cache folders (with `legacy_cache_dir()`), per-plugin settings, background work, deck edits with
>     the stale-file check, slide insertion (ids minted, all or nothing), deck language, `open_url` (http/https only);
>   - UI hooks: commands into the registry and palette, Deck menu sections named after the plugin, Deck settings
>     tabs with a footer action that replaces Save on that tab, Settings tabs, compact side-panel boxes after a
>     "Plugins" separator (`when` decides; `large` refused until the dock is built), render priority ORed with
>     core's rule.
> - **Installing**:
>   - `plugins/installer.py` checks the SHA-256 and refuses absolute paths, `..`, symlinks, backslashes, compiled
>     files and oversized archives, then swaps the folder atomically. Plugin downloads are http/https only, with
>     the size checked;
>   - `plugins/catalogue.py` reads `https://slidemage.org/plugins/index.json` (override
>     `SLIDEMAGE_PLUGIN_CATALOGUE`), caches it, ignores unknown fields, skips broken entries, and picks the newest
>     release that fits. It never reads GitHub's "latest release".
> - **UI**:
>   - Settings → Plugins: installed plugins with state, details, needs, network, enable, remove and update;
>     available plugins with install; Install from file… with a warning and an optional `.sha256`; "Restart now";
>   - Help → Plugins…;
>   - a first-start sheet, shown only when the list has something to offer;
>   - plugin updates following the app's update mode (off, ask, auto), at most once a day;
>   - withdrawn versions are flagged;
>   - the upgrade detection (which built-in features a user used) is written and tested, but switched off
>     (`PRESELECT_ON_UPGRADE = False`).
> - **Frozen build**: the spec bundles the stdlib (minus `tkinter`, `turtle*`, `idlelib`, `test`, `ensurepip`,
>   `lib2to3`, `pydoc_data`, `this`, `antigravity` and private modules) and `QtCore`, `QtGui`, `QtWidgets`,
>   `QtNetwork`, `QtSvg`; `--self-test --plugins` imports them and loads a plugin, in the release workflow on Linux
>   and Windows.
>
> **Tests.** About 255 in `tests/test_plugin_*.py`, with fixture plugins (good, bad manifest, raising, future API,
> needs newer, name clash, relative imports, late `add_*`, a UI plugin). `test_plugin_campusonline_e2e.py` loads
> the real CampusOnline plugin when `SLIDEMAGE_E2E_CAMPUSONLINE` names its checkout: it activates, and its commands,
> Course tab and box work. The full suite fails on the same 8 tests as `develop` and no others (section 8).
>
> **Not verified here:** a PyInstaller build (the self-test in the release workflow is the check), and how much the
> stdlib adds to the download.
>
> **Merge conflicts with PRs 1–2**, all mechanical:
> - `version.py` and `CHANGELOG.md`: renumber at merge;
> - `packaging/slidemage.spec`: PR 2 sets `HIDDEN_IMPORTS = []`, PR 3 builds the stdlib list with
>   `collect_submodules("anthropic")` in it; keep PR 3's list without the anthropic line;
> - `tests/test_settings_gui.py` and `tests/test_menu_bar_gui.py`: both add expectations.

### 3.4 PR 4: CampusOnline plugin, public repository (after PR 3 is merged)

Not a pull request into SlideMage. Its plan's steps 5 and 6:

1. Step 5: replace `campusonline/host.py`'s Protocol by imports from `slidemage.plugin_api`, delete `bridge/`, and
   test against the oldest and newest SlideMage allowed.
2. Create `JuergenFleiss/slidemage-plugin-campusonline` (public, issues open), push the branch as `main`, replace
   the template's icon, add screenshots, date 1.0.0, and tag `v1.0.0`.
3. A pull request to `stpalan/slidemage-website` `registry/plugins.toml` (`releases = "all"`, first-party).

### 3.5 PR 5: phase 2 in core, CampusOnline out (after 1.0.0 is listed)

Remove `course_schedule.py`, `admin_slides.py`, `ui/dialogs/admin_slides.py`, the course-link code of `deck_scan`,
`deck_settings` and `deck_editor`, the Deck settings field, the command and its menu entry, and the core
"session soon" rule, with their tests. Switch on the upgrade preselection for CampusOnline. Add the project hint
for decks with a course link. With a `BREAKING:` paragraph and a `compat.py` entry, this would be **v9.0.0**
(section 6).

### 3.6 PR 6 (#22, merged): the 8 GUI tests failing on `develop` (`fix/develop-gui-tests` → `develop`)

All 8 were tests that had fallen behind the app; no app code changes:
- the AI switch moved out of the top bar, and Claude Code got session ids (both v8.61.0);
- a tuple index typo;
- Qt listing a font family under two foundries.

One trade-off for you to look at: the SemiBold font check now runs only off Linux, because Qt on Linux doesn't list
a variable font's named instances. CI runs on Linux, so it no longer runs in CI.

### 3.7 Later

Phase 3 (the AI route registry, yours), the Ollama plugin (yours), phase 6 (the Claude plugin, ours), phase 7
(AI-free core), phase 8 (manual).

Small pull requests to your repositories we can open if you like:
- `slidemage-plugin-template`: refuse relative imports that leave the package; name the bundled stdlib and
  PySide6 set; show the real `plugin_api` calls in `example/__init__.py`.
- `slidemage-plugin-hello`: a release with a lower `requires_slidemage` (section 6).

## 4. Work done

### 4.1 Phase 4 in SlideMage (PR 2)

As in 3.2. On the way:
- **A suspected hang wasn't one.** A full-suite run without `pytest-xdist` (not in the venv, so `-n auto` fails)
  is serial and takes about 35 minutes. No test hangs; the slowest file takes 73 s.

### 4.2 Phases 0 and 1 in SlideMage (PR 3)

As in 3.3. Built as nine steps (`docs/PLUGIN_HOST_PLAN.md`), each reviewed and committed on its own.

### 4.3 CampusOnline plugin (its repository, `docs/PLAN.md` there)

| Step | What | Commit |
|---|---|---|
| 0–1 | history filtered from `stpalan/SlideMage` `develop`; template adopted; the package stdlib-only, SlideMage internals in `bridge/` | up to `b7c891e` |
| 2 | the host drafted as a `typing.Protocol` (`campusonline/host.py`), a `FakeHost`, `activate()` registering everything | `9d5a6b9` |
| 3 | "Course" Deck settings tab (link with Save link and Open, admin slides, Insert slides as the footer action) and the compact box (title, next session with date, time and room, Open course page, Admin slides…) | `df91066` |
| 4 | SlideMage's old `course-schedules.json` adopted once at activation | `3d22a40` |
| – | the cache keeps the course title and full sessions, read through a public `cached_entry()` | `6922913` |
| – | box sizes `compact` / `large` as in your plan | `d18b8a0` |

120 tests; `build.py --check` passes.

## 5. Changes and additions to your plan and handovers

### 5.1 `docs/PLUGINS_PLAN.md`

| Your draft 2 | Now | Why |
|---|---|---|
| Order 0 → 1 → 2 → 3 → 4 → … | 4 done first; 0 and 1 done; 2 next | 4 depends on nothing; 0 and 1 were the bottleneck for the plugin |
| Phases 0–1 implied yours | built by us (PR 3) | to keep CampusOnline moving; review it as if it were yours |
| §2.1 "own vendored pure-Python code" | the package imported under its own name from its folder; a name already importable (stdlib, SlideMage, a dependency, another plugin) refuses that plugin | no `sys.path` entries, and no plugin can shadow a module |
| §2.2 | the build bundles the whole stdlib and five PySide6 modules for plugins, checked by `--self-test --plugins` | a plugin using e.g. `csv` would otherwise fail only in the installed app |
| §2.5 `factory(WindowApi)`, `when(DeckApi)` | `build(deck)` and `when(deck)` with a deck snapshot; only `compact` | what CampusOnline needs; `large` and the dock wait for a plugin that uses them |
| §2.7 extension points | see 5.2 | |
| §2.8 first-start sheet | shown only when the catalogue lists something offerable; offline, an empty list or a too-new catalogue leave it for a later start without setting the flag | the public catalogue is empty now: otherwise everyone would see an empty sheet once, and never the real one |
| §2.8 upgrade preselection | written and tested, `PRESELECT_ON_UPGRADE = False` until the release that removes a feature | nothing is removed yet |
| §2.8 updates "in the same pass as its own" | their own check, following the same mode, at most once a day, also in source checkouts | the app's own check is skipped in a source checkout; plugins can still update there |
| §2.6 Plugins tab | as specified, plus Details… for a load error, "Withdrawn from the plugin list", and a real restart through the existing relaunch | |
| §3 version numbers (implicit in the handovers: host ≥9.0) | host v8.68.0; v9.0 for the release that removes CampusOnline | section 6 |

Section 6 of `PLUGINS_PLAN.md` (draft 3) records the website's answers and the first half of this; this handover
supersedes it where they differ.

### 5.2 `plugin_api` against your §2.7

| Your §2.7 | `plugin_api` (API 1) | Why |
|---|---|---|
| `add_command(id, title, scope, run, enabled, shortcut=None)` | `add_command(id, title, run, enabled)`; `id` must start with `<plugin id>.`; `enabled(None)` without an open deck | `scope` and `shortcut` are easy to add when a plugin needs them |
| `add_menu_entry(menu, command_id, section=None)` | `add_menu_entry("deck", command_id)`, one section per plugin at the end of the Deck menu, headed with its name | the only menu a plugin uses so far |
| `add_menu(title, sections)` | not built | no user |
| `add_settings_section(page="ai", …)` | not built | phase 3 |
| `add_deck_settings_tab(title, factory)` with footer action and dirty state | `add_deck_settings_tab(title, build, footer_action=FooterAction(label, run, enabled))`; the action's button replaces Save on that tab | the same, made concrete |
| `add_deck_marker(name)` | **`edit_deck_text(deck, change)`**; the plugin parses its own comment | smaller, more general; keeps the stale-file check |
| – | `open_deck_settings(deck, tab)` | "Admin slides…" opens the sheet on the Course tab |
| – | `cache_dir()`, `legacy_cache_dir()` | the plugin's cache, and where core kept a file before the plugin |
| – | `insert_positions(deck)`, `insert_slides(deck, position, [(suffix, frame)], language)`, `deck_language(deck)`, `open_url(url)` | the admin slides' deck edits |
| – | `Page()`, `Field(label, widget)`, `caption(text, tone)` as host methods | the tab and box look like SlideMage's |
| `settings(plugin_id)` | `settings()` (the host is per plugin) | |
| `add_render_priority(fn)` | the same; called on a worker thread; an exception counts as False | `BackgroundRenders` asks there |
| `add_ai_route`, `terminal()`, `ai_tools()`, `credentials` | not built | phases 3 and 6 |

### 5.3 Website handover

- The client follows your answer of 2026-10-27: the fixed URL, `index-test.json` for tests, unknown fields
  ignored, the package-folder rule, the catalogue as the only source.
- **Download URLs:** the client accepts any `https` download URL. The schema's
  `github.com/…/releases/download/` pattern isn't enforced, since the catalogue is trusted either way. Say if you
  want it enforced.
- **Test overrides:** `SLIDEMAGE_PLUGIN_CATALOGUE` points the app at another catalogue, and
  `SLIDEMAGE_PLUGIN_PATH` at plugin checkouts.
- **Copies in our tests:** the schema and `index-test.json` are copied into `tests/fixtures/catalogue/`. Update
  them when the schema changes.

### 5.4 CampusOnline handover

- **Repository:** on Jürgen's private fork `JuergenFleiss/SlideMageS` (branch `plugin-campusonline`) until 1.0.0,
  then `JuergenFleiss/slidemage-plugin-campusonline`. The handover's clone URL `JuergenFleiss/slidemage.git`
  doesn't exist; the history was filtered from `stpalan/SlideMage`.
- **Host:** `add_deck_marker` is replaced by `edit_deck_text` (5.2). The calls of its §2 table all exist, with the
  additions in 5.2.
- **Course tab:** the link has its own Save link button (Return saves too). After saving or inserting, the tab asks
  to reopen Deck settings, because the deck it holds is a snapshot.
- **Box:** shows cached data only and never fetches: title, next session (date, time, room), Open course page,
  Admin slides…. The cache now keeps the title and sessions. The weekday names are English for now.
- **Old cache:** `course-schedules.json` is adopted from `legacy_cache_dir()` once, never overwritten, and only
  when it is valid JSON.
- **§7 questions, Jürgen's answers:**
  - **Owner:** `JuergenFleiss/slidemage-plugin-campusonline` for now, with a counterproposal for later: a SlideMage
    organisation (section 5.7).
  - **Settings tab:** none for 1.0.
  - **Box:** as built. The weekday follows the deck's language (Mo/Di… for a German deck). There's no "group of
    the next session", because a course's groups usually have decks of their own.

### 5.5 Claude handover

- **§4 (the stdlib client):** done by us, in `ai/anthropic_provider.py`, as asked.
- **`raw`:** now holds plain wire dicts, which matters for the plugin's tests.
- **§8 (feedback on the `AiRoute` shape for Claude Code):** still to come from us before phase 3. What we know
  it needs:
  - the `chat_surface` lifecycle: `stop()` and `restart(model, continue_conversation)`;
  - effort as part of the model choice;
  - a `problem()` that can say "not installed".

### 5.6 Ollama handover

Not seen on our side; nothing changed.

### 5.7 Counterproposal: a SlideMage organisation on GitHub

Your plan (§2.9) puts each plugin on its maintainer's personal account. That works for now, and CampusOnline
starts on Jürgen's account. For the longer run we propose **a GitHub organisation for SlideMage**, as aTrain has
for its transcription app, or as Flathub does for its apps:

- **Each plugin gets a repository in the organisation**, first-party and third-party alike.
- **The plugin's developer owns their repository** (admin rights on it).
- **One organisation member has access to every plugin repository**, for review, security fixes, and taking over
  a plugin whose developer has gone.
- SlideMage itself, the website and the template can live there too, or stay where they are: your call.

Please look at how Flathub is organised; it is the closest model we know:
- every app is a repository `github.com/flathub/<app-id>`;
- a new app comes in as a reviewed pull request to the submission repository;
- once it is approved, the organisation creates the app's repository and gives its maintainers write access to
  that repository only;
- builds and publishing run centrally.

In our terms, the submission pull request is the website registry's approval pull request (handover §4), and the
build bot is the catalogue builder.

What it gains:
- **A neutral home** that outlives any one person's account.
- **Stable repository URLs** for the registry and for each plugin's `homepage`.
- **One place to look** for "every approved plugin".
- **A simpler review.** The registry could require plugin repositories to be in the organisation, which makes the
  review checklist's "maintainer reachable" and "repository follows the conventions" easier to keep true.

Moving the repositories later is cheap, since GitHub redirects the old URLs, but the registry entries and the
`homepage` fields would change. So deciding before the first real plugin is listed is best.

## 6. Version numbers: a decision for you

The release tooling (`packaging/release_notes.py`) refuses a major version without a `BREAKING:` paragraph, and
a `BREAKING:` paragraph needs a `compat.py` entry. The plugin host breaks nothing, so it is **v8.68.0**. The handovers assumed 9.0:

- `hello` 0.1.0 and CampusOnline ask for `requires_slidemage = ">=9.0"`, so neither installs on the 8.x host. The
  end-to-end test loads CampusOnline as if the app were v9.0.0.
- **Proposal:**
  - **v9.0.0** is the release that removes CampusOnline (PR 5), a real `BREAKING:` change, and CampusOnline 1.0.0
    keeps `">=9.0"`;
  - `hello` gets a release with `">=8.66"`, so the installer can be tested against `index-test.json` on the host
    release;
  - **v10.0** stays the AI-free core, as the Claude handover says.
- The alternative: ship the host as v9.0.0 with a `BREAKING:` paragraph and a `compat.py` entry anyway.

**Jürgen's proposal on top: renumber SlideMage for publication**, to something like **0.4**. A public first
release numbered 8 or 9 suggests a maturity and history the public hasn't seen. The plugins'
`requires_slidemage` values would then follow the new numbers: the host's release, then the release that removes
CampusOnline, then the AI-free core.

What a renumbering has to solve: the updater (`updater.py`) installs a release only when its version is higher,
so installs on 8.x would never take a 0.4. Options:
- a last 8.x release whose updater knows the new scheme;
- the public numbering starting in a new repository or release channel;
- installs of the current testers moved by hand.

Your call, since it's your release process.

## 7. What we need from you

1. Review PR 3 as the owner of phases 0–1, and confirm or change 5.2's API, before the CampusOnline plugin moves
   onto it (step 5). The calls that matter most: `edit_deck_text` vs `add_deck_marker`, and the extra calls.
2. Version numbers (section 6), and a `hello` release with a lower `requires_slidemage`, if you agree.
3. `add_render_priority` on a worker thread, `enabled(None)`, and `add_*` only inside `activate()`: OK?
4. The template: the relative-import check, the stdlib/PySide6 set in its README, and the real `plugin_api` in
   `example/__init__.py`. Shall we send the pull request?
5. The Ollama handover.
6. The 8 GUI tests that fail on `develop` itself (section 8): fixed in #22 (3.6), merged.
7. **Install from file…:** as built, any `.smplugin` that passes the checks installs after a warning ("not from the
   SlideMage plugin list", plus its network lines). Should it be limited to plugins listed in the catalogue? Your
   call.
8. The organisation (5.7) and the renumbering (section 6): what you think.

## 8. Full test suite, `feature/plugin-host` against `develop`

Both run in full on 2026-10-28, serially (`pytest-xdist` is not in the venv), side by side on one machine:

| | Passed | Skipped | Failed | Time |
|---|---|---|---|---|
| `develop` (clean copy) | 3510 | 14 | 8 | 36 min |
| `feature/plugin-host` | 3765 | 18 | 11 | 39 min |

- **The 8 failures of `develop`:** `test_workspace_window.py::test_top_bar_densities_*` (3),
  `test_accessibility_cards_gui.py::test_the_headers_icons_have_names`, `test_claude_code_gui.py` (2),
  `test_compare_rendered_gui.py::test_the_task_card_compares_in_review_and_done`,
  `test_ui_kit_gui.py::test_font_files_are_bundled_and_registered`. The plugin host's run fails on these 8 too.
- **Its 3 extra failures:**
  - `test_claude_tasks_gui.py::test_a_translation_creates_the_partner_after_the_source_and_links_both`
  - `test_workspace_window.py::test_column_toggles_…[shortcut-left…]`
  - `test_workspace_window.py::test_column_toggles_…[shortcut-right…]`

  All three pass alone, and their two files pass in full (apart from the 3 top-bar tests). They are timing
  failures under the load of two suites running at once, not failures of the branch.
- **Result:** the plugin host adds no failure. The 8 are `develop`'s own.
