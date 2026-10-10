# SlideMage UI redesign (Prototype v3)

Status: in progress on branch `ui-redesign`. Steps 1–9 and 10a–10d done; next is the whole-code review, then step 11 (see
"Progress and handover").
Date: 2026-10-09 (decisions settled the same day).
Source: Claude Design project "SlideMage", file `SlideMage Prototype v3.dc.html`
(plus `sm-images.js`, `support.js`, `latex/slidemage-logo.svg`).

## Objective

Replace SlideMage's PySide6 window with the prototype's single-deck workspace.
Today the window has one tab per deck table, deck editor, slide source and
Images page. The prototype has one workspace for each open deck:

```
┌ logo · deck ▾ · View as [Instructor|During|After] [EN|DE] · saved · [Preview|Split|Source|Details] · [Compile PDF ▾] · Images · ⋮ ┐
├──────────────┬──────────────────────────────────────┬───────────────────────────────┤
│ Find slide…  │  slide preview / source / split /    │ side panel ▾ (8 panels)       │
│ § Section    │  details for the focused slide       │ ───────────────────────────── │
│   1y8 Title ●│  chips: pinned · course · lang · …   │ AI chat (this slide | deck)   │
│   …          │                                      │ local ⇄ cloud toggle          │
└──────────────┴──────────────────────────────────────┴───────────────────────────────┘
  overlays: ⌘K palette · compile job + log · toasts · dialogs · Images page
```

## Decisions (2026-10-09)

1. **Switch over; no parallel UI.** The new workspace replaces the old one.
   The codebase is restructured as needed to stay well structured and lean.
   Each old widget is deleted in the step that replaces it, not kept behind a
   setting.
2. **Local and cloud AI.** Every AI feature can use a local Ollama model or a
   cloud model (Claude). The plan for this is in step 2.
3. **Bundle fonts and icons.** Roboto, Roboto Mono and Material Icons ship
   with the app.
4. **Current source editor.** The Source view uses the existing
   `LatexPlainTextEdit`. `EMBEDDED_EDITOR_PLAN.md` stays a separate, later
   project; the editor sits behind a small interface so it can be swapped.
5. **No reveal-steps feature** (2026-10-09). Ignore and do not implement
   the prototype's "Reveal steps" panel (step cards, per-step show/hide,
   step badges on the preview) or painting slide parts onto steps (step
   12). Existing `\slidestep` support stays as it is: the call variant in
   the slide list, the Visibility matrix and "One reveal step" in Add
   slide.

## Progress and handover

Last updated 2026-10-10. Suite after 10d-2: 1285 passed, 6 skipped (26 s);
ruff clean. Suite time varies with machine load (9–18 s for the same
commit; compare against HEAD in a `git worktree` before blaming a step).

### Resume here (next session)
1. Read this section, then `git log --oneline -15` on `ui-redesign`
   (latest step commit: 10d-2, see the log). Working tree should be clean
   apart from untracked `uv.lock` and `.claude/` (both left untracked on
   purpose; don't commit them). Run the suite once (expect 1285 passed,
   6 skipped). If a test fails with a git-checkout symptom
   (`test_bundled_copies`), look for a stray empty `/tmp/.git` left by
   an earlier agent run and remove it.
2. Re-fetch the prototype into the new session's scratchpad only if a
   step needs it (neither the review nor 11 does; see "How the work is run").
3. Next: a whole-code review before step 11 (12 Haiku reviewers, see
   below; ~150–200k), then **step 11** (finish the switch-over: leftover
   `qt_*` modules incl. `qt_ai_models.py`, `qt_citation_dialog.py`,
   `qt_gui.py`; PyInstaller bundle check with `anthropic`, `ptyprocess`
   and QtWebEngine (see 10c leftovers); docs, manual, screenshots tool,
   6.0 version bump). Optional kit restyle before or within step 11.
   Size each before starting and split if over ~350k tokens.
4. User-side checks still open (need the user's quota or key): try a local
   tool-capable model in the Chat once on a real slide edit (the live test only
   reads); try the
   Claude Code tab once (focused slide visible via MCP; an edit of a
   slide header must be blocked by the hook); the chat against real
   Claude needs an API key (`ANTHROPIC_API_KEY`; the user has a Pro
   subscription only, so the Claude Code tab is their main route).

### Remaining work and size (estimate 2026-10-10)
About 5% of the user's 5-hour window per ~100k agent tokens.

| Work | Content | Agent tokens | ≈ window |
|---|---|---|---|
| ~~9d-2 Images page~~ | done (~500k actual) | | |
| ~~10a Agent backend~~ | done (~370k actual) | | |
| ~~10b Chat UI~~ | done (~340k actual) | | |
| ~~10c Claude Code terminal~~ | done (~380k actual) | | |
| ~~10d-1 Cleanup~~ | done (~90k actual) | | |
| ~~10d-2 Ollama tool calling~~ | done (~190k actual) | | |
| Review before 11 | 12 Haiku reviewers + one Sonnet fix agent | 150–200k | 8–10% |
| 11 Finish switch-over | delete leftover `qt_*` (`qt_ai_models`, `qt_citation_dialog`, `qt_gui`), fix screenshots tool, README/manual/`docs/SlideMage.md`/screenshots, 6.0 bump | 200–300k | 10–15% |
| Kit restyle (optional, recommended) | inputs/combos/checkboxes/scrollbars in kit style, view chips, QSS colour tokens, review leftovers (panel helpers, click-frame base) | 150–250k | 8–12% |

Remaining after 10d-2 ≈ 350–600k agent tokens (≈ 18–30% of one
window; recent steps landed at the top of their estimates). Pause after
each committed step.

A cheap whole-code review that worked: 12 parallel read-only Haiku
reviewers (Explore, `model: haiku`), each on a ~1–1.5k-line slice, max
12 findings tagged bug/simplify/layering with file:line; the
orchestrator spot-checks bug claims (one of ~120 was false) and hands
the confirmed list to one Sonnet agent (review fixes: ~160k tokens).
Worth repeating before step 11.

| Step | Commit | State |
|---|---|---|
| 1. Visual foundations | `2ead8ca` | done |
| 2. AI provider layer | `49c1fa4` | done |
| 3. Workspace shell | `ef3a5a6` | done |
| 4. Slide list | `61e348f` | done |
| (user's preview work) | `776267e` | committed before step 5 |
| 5a. Centre views | `d543147` | done |
| 5b. Lint, AI fix, Insert/Cite | `15a30ed` | done |
| 6a. Panel host, Used in decks, Slide versions, Visibility | (see git log) | done |
| 6b. Citations, Language, Images, Transcript, Notes panels | (see git log) | done |
| 7. Compile flow | (see git log) | done |
| 8. Command palette | (see git log) | done |
| 9a. Add slide sheet | (see git log) | done |
| 9b. Project picker, compat, No decks/First run, Housekeeping, Snapshots, deck group dialog, About | (see git log) | done |
| 9c. Settings + Deck settings sheets | (see git log) | done |
| 9d-1. Images page logic → `image_review.py` (backend only) | (see git log) | done |
| Review fixes (12 Haiku reviewers, Sonnet fixes) | (see git log) | done |
| 9d-2. Kit Images page under `ui/pages/`, transcript preview sheet; deleted `qt_transcript_tab.py` / `qt_transcript_preview_tab.py` | (see git log) | done |
| 10a. Agent backend (`ai/agent.py`, `ai/tools/`, `anthropic` SDK) | (see git log) | done |
| 10b. Chat UI + Chat \| Claude Code switch (`ui/workspace/chat/`) | (see git log) | done |
| 10c. Claude Code terminal (`ui/workspace/terminal/`, MCP server, hook) | (see git log) | done |
| 10d-1. Remove `qt_ai_draft_dialog.py` (Tools ▾ "Ask the chat…"), chat takes the Ollama slot | (see git log) | done |
| 10d-2. Ollama tool calling in the chat (`OllamaProvider.stream_turn`), tool-capable model pickers, dead AI-drafting settings removed | (see git log) | done |
| 11 | | not started |

### What exists now
- `ui/kit/`: `tokens.py` (light/dark tokens), `kit_qss.py`, `theme.py`
  (moved from `qt_theme.py`), `fonts.py` (`load_fonts()`), `widgets.py`
  (SegmentedControl, Chip, SplitButton, IconButton, IconLabel, Button,
  PopoverMenu, Toast, Card, ModalSheet, `apply_shadow`), `gallery.py`
  (`python -m slidemage.ui.kit.gallery`). Fonts in `assets/fonts/` (Roboto
  and Roboto Mono SIL OFL 1.1, Material Icons Apache 2.0).
- Step 10d-2: `OllamaProvider.stream_turn()` (stdlib `/api/chat` NDJSON,
  tools as functions, results as `role: "tool"` messages with
  `tool_name`, `render_preview` images as a following user message for
  vision models, else a text note; `_HttpProvider._request` is the
  streaming plumbing, Stop shuts the socket down). `installed(detailed=)`
  / `capabilities()` (`/api/show`) / `InstalledModel.supports_tools` (name
  list fallback for Ollama < 0.6.4) / `tool_models()`; Settings → AI
  models lists only tool-capable local models for "Chat assistant"
  (`SettingsSheet.tool_models`), the chat's model menu (`LocalModels`
  thread in `chat/session.py`) the same; a send that cannot start keeps
  its text in the message box. Removed: Settings "AI drafting"
  (`ai_draft` task) and the "Slide rewrite" prompt page
  (`KIND_SLIDE_REWRITE`, `ai_draft.SYSTEM_PROMPT`, `unmask`);
  `ai_draft.py` is now only `mask_protected_regions`. Tests:
  `test_agent_ollama.py` (fake NDJSON server, `fake_http.ollama_ndjson`,
  `Server.script` / `routes`); live: `test_ai_live.py` (ran green on
  `maternion/ling-3.0-tiny:8b-Q4_K_M-8k`).
- `ai/`: `providers.py` (`ChatProvider`, `OllamaProvider`,
  `AnthropicProvider`, `ProviderError`, `Cancelled`), `resolver.py`
  (`provider_for_task`, local-only global/per project, consent),
  `credentials.py` (API key: env → keyring → settings file),
  `ollama_admin.py`. Task logic stays in `ai_draft` (protected regions only),
  `syntax_check` (`SyntaxChecker`), `alt_draft` (`ModelBackend`,
  `ModelTranslationBackend`); Qt pickers share `qt_ai_models.py`
  (`provider_from_combo` asks for consent). Settings values are
  `ollama:<model>` / `anthropic:<model>`; optional extra `keyring`.
- `ui/workspace/`: `state.py` (`WorkspaceState`), `window.py`
  (`WorkspaceWindow`), `topbar.py`, `menus.py` (deck switcher, Compile
  caret, ⋮ menu), mixins `compile_jobs.py`, `deck_actions.py`,
  `maintenance.py`, `multi_compile.py` ("Several decks…"),
  `slide_list.py` + `slide_tree.py`; backend `deck_outline.py` (row
  statuses). `qt_gui.py` is only `main()`.
- Removed: `qt_deck_table.py`, `qt_closable_tab_bar.py`,
  `qt_deck_editor_tab.py`, the menu bar.

- Step 5: `ui/workspace/centre.py` (`CentreColumn`), `source_editor.py`
  (`SourceEditor` protocol, `LatexPlainTextEdit`, find bar),
  `source_file.py`, `source_view.py`, `preview_view.py`,
  `details_view.py`, `ai_fix.py` (inline "Ask AI to fix"),
  `insert_popovers.py` (hyperlink, code file, Cite ▾); backend
  `latex_edit.py`, `preview_target.py`, `snippets.py`,
  `bibliography.search`. Kit: `Popover`, `Surface`,
  `SegmentedControl.set_badge`. `WorkspaceState` has `mode`, `dirty`,
  `lint_errors`, `footer_timestamp`.
- Removed in step 5: `qt_slide_source_tab.py`, `qt_slide_preview_popup.py`,
  `qt_syntax_check_dialog.py`, `qt_insert_citation_dialog.py`.
- Step 7: `compile_jobs.py` holds `CompileSignals` and all compile
  orchestration (`_init_compile`); `job_panel.py` (floating run card),
  `log_drawer.py` (Ctrl+L, ⋮ Log), `render_check.py` (pre-check sheet,
  `confirm_render`, `open_issue_in_editor`); backend `compile_status.py`
  (`RunStatus`, `LatexError`). `try_start_ollama_task`/`end_ollama_task`
  take the provider (cloud tasks skip the slot). Removed:
  `qt_render_check.py`, the log panel.
- Step 8: `ui/commands.py` (`Command`, `CommandRegistry`,
  `bind_shortcuts`), `ui/workspace/actions.py` (`build_registry()`, ~95
  commands; ids such as `slide:*`, `section:*`, `compile:*`),
  `palette.py` (Ctrl+K / Ctrl+Shift+F). Menus in `menus.py` are lists of
  command ids (`add_commands`). New dialogs and pages in step 9 should
  register commands there. Removed: `qt_slide_search_dialog.py`.
- Step 9a: `ui/dialogs/add_slide.py` (`AddSlideSheet`, opened by
  `window.open_add_slide_dialog(deck, insert_at, indent, **start)`),
  `ui/dialogs/import_presentation.py`; backend `slide_add.py`,
  `slide_ids.slide_body`/`read_template`; kit `Field`, `ThumbnailGrid`,
  `ModalSheet.add_footer_note`; `assets/frames/*.png`. Removed:
  `qt_add_slide_dialog.py`, `qt_duplicate_slide_dialog.py`,
  `qt_import_dialog.py` (it was PPTX/ODP import, kept as its own sheet).
- Step 9b: `ui/dialogs/open_project.py` (`OpenProjectSheet` = start
  screen + `open_project` command, `NewerProjectSheet`),
  `project_compat.py`, `housekeeping.py` (+ `housekeeping` command),
  `snapshot.py`, `deck_group.py`, `about.py` (`version_history`
  command); `ui/pages/no_decks.py`; backend `housekeeping.py`,
  `app_info.py`, `project.recent_projects`/`project_status` (recent list
  in `config_dir()/recent_projects.json`). Removed: `qt_compat_dialog`,
  `qt_archive_unused_dialog`, `qt_snapshot_dialog`, `qt_deck_group_dialog`,
  `qt_version_history_dialog`.
- Step 9c: `ui/dialogs/settings.py` (+ `settings_ollama.py`,
  `settings_prompts.py`; tabs General, AI models, Cloud, Ollama,
  Prompts), `deck_settings.py` (General, PDF output, Admin slides tab
  from `admin_slides.py`); backend `admin_slides.py`,
  `deck_settings.from_form`; `ui/background.py` (`start_detached`); kit
  `Page`, `caption()`, `row()`, `columns()`. Tests: autouse fixture in
  `conftest.py` redirects prompt stores and `resolver.PROJECT_ROOT`.
  Removed: `qt_settings_dialog`, `qt_deck_settings_dialog`,
  `qt_admin_slides_dialog`, `qt_translation_prompts_panel`.
  `qt_ai_models.py` remains (move under `ui/` in step 11).
- Step 9d-1: `image_review.py` (`FILTERS`, `scan_views`, `visible_views`,
  `sort_order`, `slide_state`/`image_state`, `state_counts`,
  `summary_text`, `find_slide`, `form_baseline`, `FormEdit`,
  `save_slide_forms`, `needs_long_description`, `copy_into_media`,
  `repoint_slides`, `is_unused_after`, `has_text`);
  `alt_images.stamp_review`, `set_takeaway_default`. For 9d-2: the old
  page is slide-centric with filters Needs attention, All slides with
  images, No description, Draft unreviewed, Needs re-check, Reviewed;
  it has no deck/all scope, free-text search, "Picture changed" or
  "No German" filter (the plan's list came from the prototype; "No
  German" needs a small predicate over `alt_images.translation_state`).
  Drafting/translation batches are in `alt_draft`; image preview uses
  `alt_blocks.resolve_image`/`media_render`.
- Step 9d-2: `ui/pages/images.py` (`ImagesPage`: sibling in the centre
  stack; hides slide list and side panels while shown; `dirty`/`flush()`
  joins the close prompt), `image_nav.py` (filters, order, find, model
  pickers, Draft all / Translate all), `image_form.py`, `image_runs.py`
  (`ImageRunsMixin`; one job at a time, `stop_worker`, Ollama slot),
  `image_jobs.py` (`Job`, `JobCard`), `image_dialogs.py`
  (`ReplaceImageSheet`, `PromptTuningSheet`), `image_preview.py`;
  `ui/dialogs/transcript_preview.py` (`show_transcript_preview()`, from
  Render ▾ and the Images page header). Backend: `image_review.lacks_german`
  ("No German" filter), `apply_translation`, `preview_for`,
  `repoint_slides(unsaved=…)` refuses slides with unsaved Source edits;
  `alt_draft.slide_jobs`; `CentreColumn.sync_source`, `TopBar.mode_clicked`.
  Removed: `qt_transcript_tab`, `qt_transcript_preview_tab`.
- Step 10a (agent backend, no Qt): `ai/agent_types.py` (events
  `TextDelta`, `ToolStarted`/`ToolFinished`, `EditProposed`/`EditApplied`/
  `EditRejected`, `Done(reason)` always last; `EDIT_ASK`/`EDIT_AUTO`),
  `ai/agent.py` (`Agent(provider, workspace, on_event, mode, max_turns)`,
  `run(history, request, scope)` blocking on a worker thread, never
  raises; `stop()` from any thread; one `Agent` per request),
  `ai/workspace.py` (`Workspace` base for 10b to subclass:
  `context()`, `is_open`/`is_dirty`/`buffer_text`, `apply_to_buffer(path,
  expected, new)`, `confirm_edit`, `confirm_cloud`, `file_changed`,
  `compile_deck`; all called on the agent thread, GUI work must be
  marshalled), `ai/agent_context.py` (fixed, cached system prompt +
  per-request context; scope slide/deck), `ai/guides.py`, `ai/tools/`
  (read_file, find_files, search, edit_file, write_file, list_slides,
  lint, render_preview, add_slide, add_bib_entry, compile_deck,
  read_guide; dot-folders and `pdf/` invisible; protected-region and
  frozen-version refusal; `undo_edit`). `AnthropicProvider` now runs on
  the `anthropic` SDK (lazy import, `stream_turn()`); Ollama
  got its own in 10d-2. Settings → AI models has "Chat assistant"
  (`chat_model`). Live test: `SLIDEMAGE_LIVE_AI=1` + `ANTHROPIC_API_KEY`
  (not yet run). Open: server-side refusal `fallbacks` (beta) not used.
- Step 10b: `ui/workspace/chat/` — `assistant.py` (`AssistantArea`,
  Chat | Claude Code switch remembered as `assistant_view`; holds
  `claude_code = ClaudeCodeView` since 10c), `view.py`, `cards.py` (text, tool,
  diff cards with Apply/Reject/Undo), `session.py` (`ChatSession`: history,
  agent `QThread`, `stop_worker`), `gui_workspace.py` (`GuiWorkspace`:
  `on_gui(fn, default)` queues onto the GUI thread and waits on an
  Event; Stop/close reject pending asks; compile via `_compile_jobs` +
  `CompileSignals.run_settled`, `stop_compilation_now()`), `format.py`.
  Settings: `chat_edit_mode`. `centre.path`, `centre.file_written(path)`;
  palette "Ask the chat" live (`window.ask_chat`). The assistant sits
  under the side panels (splitter 300/500, not remembered).
- Step 10c: `pty_process.py` (`PtyProcess`: ptyprocess / pywinpty,
  reader thread, fd soft limit lowered to 4096 around spawn),
  `ai/mcp_server.py` (hand-written MCP over `http.server`, 127.0.0.1,
  bearer token from env, tools `get_focus`, `read_buffer`, `list_slides`,
  `lint`, `render_preview`, `read_guide`, `add_slide` (asks)),
  `ai/claude_launch.py` (`find_claude`, flags `--mcp-config`,
  `--settings` (PreToolUse hook + allow rules), `--append-system-prompt`;
  child env drops `ANTHROPIC_API_KEY`/`ANTHROPIC_AUTH_TOKEN`/session
  markers so the Pro login is used), `ai/claude_hook.py` (exit 2 blocks
  protected-region / frozen-version edits; `python -m
  slidemage.ai.claude_hook` or frozen `<exe> --claude-hook`),
  `ai/project_watch.py` (1 s poll), `ui/workspace/terminal/` (`view.py`,
  `web.py` xterm.js in QWebEngineView via QWebChannel, `session.py`,
  `sync.py`, `theme.py`), vendored xterm 6.0.0 + addon-fit 0.11.0 in
  `assets/terminal/`. Source buffers get a conflict bar ("Reload from
  disk" / "Keep my edits"). Right column is a draggable splitter
  (340–900 px, `right_column_width`). Test fixture
  `_restore_app_stylesheet` keeps the suite fast.
- Right column: `side_panels.py` (vertical `QSplitter`, chat goes below
  in step 10) and `panels/` (`base.py`, `used.py`, `versions.py`,
  `visibility.py`, `citations.py`, `language.py`, `images.py`,
  `transcript_entry.py`, `notes.py`; registry `PANELS` in
  `panels/__init__.py`). Panels have `dirty`/`flush()`; the close prompt
  counts them; Notes edits go into the Source buffer (versioned save).

### Temporary hosts still in place
- Details view: slug, frame, language fact, Duplicate / Rename / Delete.
- Citations "Add to .bib…" and Cite ▾ footer open `qt_citation_dialog`
  (the add-entry form, kept; step 10 chat may take over).

### Carried over to later steps
- Preview chip "course note" has no slide-level backend data (not
  built); "outdated translation" is wired (`translation_link`: original
  saved via SlideMage after the translation was written, not a content
  check). The slide list's lint dot follows the saved file.
- Review leftovers: use `ui/background.stop_worker` for every new
  worker thread (9d-2, 10); `image_review.repoint_slides` writes slides
  directly, bypassing open Source buffers (fix in 9d-2); backend still
  builds `-current.tex` names by hand in several modules
  (`slide_language.current_name` exists); slide list shows pinned
  versions as `v1-0-0` (could use `version_label`); larger refactors
  not done: panel boilerplate helpers in `panels/base.py`, one click-frame
  base for kit widgets, QSS colours via tokens (`#ffffff` ×6).
- 10d-2 leftovers: no reduced tool list for small local models (the
  chat sends all 12 tools and the same system prompt; `Agent(tools=...)`
  allows it, but nothing says yet which models need it); the agent asks
  Ollama for a 16384-token window (`providers.AGENT_NUM_CTX`) and does
  not warn when a long conversation outgrows it (Ollama then drops the
  oldest text silently; `usage["input"]` is the prompt size); thinking
  output of local models is dropped, not shown; the local model list
  of the chat is loaded when the chat is built and whenever the model
  menu opens (so a model pulled meanwhile shows at the next opening);
  the Claude cloud list is still the static one. `docs/SlideMage.md`
  still names "AI drafting" and "Slide rewrite" (step 11).
- 10c leftovers: the hook has not fired in a real session yet (needs a
  model edit; user can try: ask Claude Code to change a slide header);
  real `tools/call` from Claude Code untested; Windows (pywinpty,
  `claude.cmd`, frozen-hook stdin) untested; QtWebEngine runs with
  `--disable-gpu`; step 11 must check PyInstaller with QtWebEngine
  (~+220 MB, helper process, sandbox flags) and `anthropic`; plain URLs
  in the terminal are not clickable.
- 10b leftovers: cloud model picker lists `ANTHROPIC_FALLBACK_MODELS`,
  not the live list; no chat history persistence/search.
- 10a leftovers: check the PyInstaller bundle with `anthropic`
  (httpx/pydantic) in step 11; run the live agent test once with a key;
  `add_slide` header regeneration relies on the GUI's `file_changed`.
- 9d-2 leftovers: the Images page uses legacy-themed combos, checkboxes
  and some scrollbars; first paint of a slide's forms can be squeezed for
  one event-loop turn; Draft all / Translate all show no counts;
  `docs/SlideMage.md` and `make_screenshots.py` (`window.transcript_tab`)
  still name the old tab (step 11).
- Kit restyle pass still open: line edits, combos, checkboxes and
  scrollbars in the new sheets use the legacy app theme; "Appears in"
  uses plain checkboxes, not the prototype's view chips; Existing list
  has no thumbnails.
- 9b leftovers: No decks has no "New deck" (no backend to create a deck
  from a name + template); the newer-project guard can prompt twice
  (picker chip, then cli guard after relaunch; hypothetical while
  `PROJECT_FORMAT` is 1); a few confirms are still `QMessageBox`
  (Empty pdf, Remove temp, Update previews, Update project results,
  newer framework/manual offer).
- Citations panel doesn't refresh after a hand edit of Slidemaster.bib;
  no "update translation" action yet (only Open); Image descriptions
  panel path label wraps awkwardly; some unused imports in `ui/`
  (`window.py` `bare_id`, `gallery.py`, `theme.py`, `ai_fix.py`).
- Build options is still a dialog (a toggle row in `PopoverMenu` would
  let it become a menu). "Retry failed" re-runs the pre-check and the
  "Nothing changed" question.
- "Move to section" menu can be long (13 entries on the manual).
- Step 11: `tools/manual/make_screenshots.py` still uses the old window
  API and imports removed dialogs (broken); `docs/SlideMage.md`, the
  README and `version.py` release-note text mention removed modules;
  stale comment mentions in `slide_preview.py`; `example/.slidemage/
  project.json` (gitignored) was reset to `{}` by a 9c screenshot run
  (harmless; rewritten on open).

### Behaviour changes made so far (user may reverse)
- Single click selects a slide; double-click/Enter opens its source.
- Section menu "Add slide here" adds at the end of the section (old: top).
- Grid view and the hover preview tooltip of the deck editor are dropped.
- Deck group collapse state and the deck table's "?" help are dropped.
- Step 5: no Close / Close-and-save (no tabs); language is set by an
  explicit Details action (no pending-language offer on save); top-bar
  EN/DE always applies to the preview; Tools ▾ "Check syntax" became
  "Ask AI to fix" on the lint line; Cite ▾ inserts `\fullcite` (default),
  `\textcite`, `\parencite` or the key; a pending transcript summary is
  auto-saved on slide/deck switch and is in the close prompt.
- Step 6: "Freeze as vX.Y.Z" in Slide versions; pin selector for the
  open deck only; Set language lives in the Language panel; a pending
  Image-descriptions edit is saved as a draft (un-reviewing it) on
  leaving the slide/deck/panel; pending Notes edits move into the
  Source buffer unsaved; Transcript entry has no per-step text.
- Step 7: runs show in a floating card (bottom centre); the Log is a
  drawer, closed by default, auto-opens on failure; Stop asks first;
  a row's × skips or kills one job; ad-hoc renders (previews) show no
  progress bar; closing mid-compile asks "Stop it and quit?";
  "Selected pages…" is "Pages by number…"; new "Pages of the selected
  slides" and "All decks except archive"; Snapshots, Update previews and
  Export PPTX also show in the job panel (Export PPTX honours Stop).
- Step 8: ⋮ "Go to slide…"/"Search slide text…" became "Find
  anything… Ctrl+K"; Go to slide focuses a slide in the deck (reveals
  it: clears the Find filter, opens its section) and opens other decks'
  slides in Source; full-text search covers slides, deck .tex files and
  Slidemaster.bib from 3 characters; the empty palette lists all
  commands (prototype caps at 9); "Ask the chat" is a disabled row until
  step 10; some labels changed ("Pages of the selected slides").
- Step 9a: Duplicate/Translate add the copy to the open deck right after
  the original (before: a loose slide); a failed machine translation
  creates nothing (error in the sheet); translation runs on a thread
  with Cancel; inline validation instead of message boxes; copying a
  slide with unsaved edits is refused inline; `\slidefinal`,
  `\omitslide`, `\omitslideversion` are only in the row's "Call as"
  menu; new slides start from a frame skeleton (standard frame = the
  project's `slide-template.tex`).
- Step 9b: no "Switch to X?" confirm (picker footer says it restarts);
  a non-project folder from "Open folder…" opens the New project form;
  Archive unused lets you untick files and runs on a thread; no "Run all"
  in Housekeeping; snapshot questions/summary are sheets; recent
  projects are remembered per machine; the first-run picker is dark by
  default (app_settings can't load before a project exists).
- Review fixes: per-deck view/language/mode memory is keyed by deck
  path (old name-keyed entries are ignored once); "Open pdf" labels
  include the file name.
- Step 9c: command `preferences`/"Preferences…" is `settings`/
  "Settings…"; per-project "Local AI only" lives in Settings → Cloud
  ("This project"), since it is per project, not per deck; prompts stay
  in Settings (stored per project); AI settings span AI models / Cloud /
  Ollama tabs; model lists load on a thread; Deck settings uses Save /
  Cancel with inline errors, and Admin slides' "Insert slides" is
  disabled while the form has unsaved changes; Build options stays a
  dialog (two options are per launch).

- Step 9d-2: leaving a slide/filter/order/deck/the page saves a pending
  image edit as a draft (old: asked to discard); one draft/translate job
  at a time; Stop on a single-image run aborts at once; Replace image is
  one sheet and refuses slides with unsaved Source edits; page-level
  EN/DE switch instead of stacked EN and DE blocks; model pickers in the
  left column's footer; "Tune prompt…" per image; deck order follows the
  open deck (no "any deck" combo); the transcript preview is a sheet,
  not a tab; new filter "No German".

- Step 10b: "Ask the chat" works; window close / deck switch stop a
  running chat request; chat edits go into the Source buffer when the
  slide is open there, else to disk with a backup (Preview re-renders);
  a chat compile can show the usual "nothing changed"/lint prompts.

- Step 10c: the Claude Code tab runs the installed `claude` (Pro login)
  in the project folder; a file with unsaved edits that changes on disk
  shows a conflict bar instead of reloading; "Keep my edits" makes the
  next save overwrite disk (backup kept); the right column is
  resizable.

### How the work is run (to resume)
- The user wants a pause after each committed step (sub-steps such as
  6a/6b count): commit, update this section, then wait for "continue".
- Orchestrator: the main session briefs one agent per step, reviews the
  result (diff, tests, screenshots in the scratchpad), sends corrections,
  then commits on `ui-redesign` with only that step's files. The user asked
  for no extra whole-branch review at the end.
- Agents: Sonnet at high effort, via `.claude/agents/ui-step-implementer.md`
  (`subagent_type: ui-step-implementer`; earlier steps ran at medium).
  Background agents; corrections go to the same agent with SendMessage
  (it keeps its context), a new step usually gets a fresh agent. Haiku
  (Explore) is fine for read-only inventories.
- Usage: about 5% of the user's 5-hour window per ~100k agent tokens
  (9d-1: ~96k ≈ 5%). Typical steps were 270–725k agent tokens. If the
  limit hits mid-step, the tree stays consistent: check `git status`,
  run the suite, and resume the agent with what is left.
- Commit hygiene: `git add -A src tests` (plus docs touched by the step),
  never `uv.lock` / `.claude/`; agents sometimes `git rm --cached`
  deleted files, which is fine. CRLF warnings on commit are normal here.
- Each brief contains: read the plan (Decisions, Approach, the step),
  the relevant modules and tests, the prototype; the step's tasks; tests
  `uv run --extra dev python -m pytest -q` and `uv run --extra dev ruff
  check src tests`; offscreen screenshots (`QT_QPA_PLATFORM=offscreen`,
  `SLIDEMASTER_PROJECT=example`) looked at by the agent; never touch the
  user's in-progress files, never git stash/checkout/reset/restore, never
  commit; a report listing files and line counts, old feature → new
  location, test results, open points.
- Review checklist that caught real problems so far: test suite time
  (step 1), workflows lost with removed widgets (step 3: multi-deck
  compile), guessed data instead of backend truth (step 4: frame numbers),
  flaky exit crashes (step 4), lost unsaved edits on close (5a summary),
  widgets reaching into widgets (5a footer timestamp), worker threads
  outliving the window (5b, 7), dark-mode contrast and white
  placeholders (7), hidden rows after "go to" (8), agents writing into
  the example project from screenshot scripts (9c), plan text based on
  the prototype instead of the real code (6a, 9d-1).
- Prototype: re-fetch with the DesignSync tool (project
  `3e2dd21f-cbd5-4329-a0d7-d3e1779450aa`, `get_file` on
  `SlideMage Prototype v3.dc.html`; needs `/design-login`). Reads are
  capped at 256 KiB, so the last ~5 KB of script are missing. Save it to
  the session scratchpad and point agents at that path. If the tool asks
  for login, the user runs `/design-login`. Save with: parse the
  persisted tool result JSON and write its `content` field to
  `<scratchpad>/prototype-v3.html`.

## Approach

- Work on a long-lived branch `ui-redesign`, merged into `develop` in steps
  that each leave the app runnable. While the branch is open, `main` only
  gets bug fixes.
- **Package layout.** All Qt code moves into a `slidemage/ui/` package. The
  backend modules (deck_editor, compiler, slide_versioning, …) stay where
  they are, so their imports and tests don't churn:

  ```
  src/slidemage/
    ai/            providers + task functions        (step 2)
    ui/
      kit/         tokens, fonts, reusable widgets   (step 1)
      workspace/   window, top bar, slide list, centre, panels, chat
      dialogs/     add slide, project picker, settings, housekeeping, …
      pages/       image descriptions
      commands.py  action registry (step 8)
    <backend modules unchanged>
  ```

- **Lean rules.** No widget holds file-format logic: anything a widget needs
  from a .tex/.bib file goes through a backend module, and new parsing goes
  into a backend module with unit tests. Widgets talk to one
  `WorkspaceState` object (focused slide, view, language, selection) with Qt
  signals instead of reaching into each other. `qt_gui.py` (2,582 lines)
  shrinks to the application, window and project bootstrap.
- **Tests.** Every step ports or replaces the `tests/test_*_gui.py` tests for
  the widgets it removes, so GUI coverage never drops.

## Steps

### 1. Visual foundations and package skeleton
- Create `ui/` and `ui/kit/`. Move `qt_theme.py` to `ui/kit/theme.py` and add
  the prototype's tokens: neutral greys (#f3f4f6 background, #1d1d1d text),
  view colors (Instructor/During/After), step colors (`STEPC`), status colors
  (error #b91c1c, warning amber, ok green), corner radii and shadows. The
  existing dark-mode palette stays.
- Bundle the fonts under `assets/fonts/` (Roboto and Roboto Mono under
  SIL OFL 1.1, Material Icons under Apache 2.0) with license files. Load them
  through `QFontDatabase` at startup, and add them to the PyInstaller spec in
  `packaging/`.
- Widgets in `ui/kit/`: segmented control, chip, split button, icon button
  (Material icon by name), popover menu with metadata column, toast with
  actions, card frame, and a modal sheet with tabs.
- Done when: a kit gallery (debug-only entry) renders every widget in light
  and dark mode, with a screenshot test.

### 2. AI provider layer (local + cloud)
Today, four modules each make their own Ollama HTTP calls: `ai_draft`,
`alt_draft` (image descriptions and translation), `syntax_check`, and the
Settings dialog's model listing. This step pulls those calls into one layer,
before any chat UI exists.

- **`ai/providers.py`**: a `ChatProvider` protocol with
  `chat(messages, *, images=None, json=False, timeout) -> str` and
  `list_models()`. Two implementations, both stdlib-only (`urllib`, as the
  project already does, with no new dependency):
  - `OllamaProvider`: the existing `/api/chat` code, moved here.
  - `AnthropicProvider`: the Messages API (`POST /v1/messages`), including
    image blocks for alt text, with the `x-api-key` and `anthropic-version`
    headers. Default model `claude-sonnet-5-5`, changeable in Settings.
- **`ai/tasks.py`**: the task functions the UI calls (rewrite slide, fix
  syntax, describe image, translate, find citation, chat). Each task keeps
  its current prompt and checks (the protected-placeholder check, verified
  syntax fixes, alt text drafts staying unreviewed), so cloud output passes
  the same checks as local output.
- **Choosing a provider.** `app_settings` gets a provider and a model per
  task (an extension of the existing per-task model keys; old keys migrate
  to `ollama:<model>`), plus a "Local AI only" switch. The switch is global
  in Settings and can be overridden per project in Deck/Project settings.
  When it is on, cloud providers are never called.
- **API key**: read from `ANTHROPIC_API_KEY` if set, otherwise from the
  system keychain through the optional `keyring` package. Without
  `keyring`, the key is stored in the settings file, and the dialog says so.
- **Privacy**: the first cloud request in a project shows what will be sent
  (slide text, images) and asks once per project. The chat label always
  shows which provider answers ("qwen3 · local" / "claude · cloud").
- Remove the per-module HTTP code from `ai_draft`, `alt_draft` and
  `syntax_check`; those modules keep only their prompt and check logic, or
  are folded into `ai/tasks.py` where nothing else is left.
- Done when: the existing AI tests (`test_review_ai_backend.py`,
  `test_model_preferences_gui.py`) pass against the new layer, each task has
  a fake-provider unit test, and an opt-in live test runs against Ollama and
  the Claude API.

### 3. Workspace shell
- `ui/workspace/window.py`: the main window with the top bar and a
  three-column `QSplitter`. `WorkspaceState` holds the focused slide, view,
  language and selection.
- Top bar: deck switcher (decks grouped as in today's deck table, which it
  replaces), View as I/D/A, EN/DE, save status, the
  Preview/Split/Source/Details switch, Compile split button, Images button,
  and the ⋮ menu.
- The start screen when no deck is open is the project picker and No decks
  states from step 9. Archived decks move into the deck switcher's footer.
- Remove `qt_deck_table.py`, `qt_closable_tab_bar.py` and the tab and menu
  bar code in `qt_gui.py`. Menu actions go into the ⋮ menu for now and into
  the registry in step 8.

### 4. Slide list (left column)
- Data from `deck_editor`/`deck_scan`. Sections can collapse and be renamed
  inline; locked sections (admin slides) show a lock. Each row shows id,
  title and status dots: lint error, stale preview, hidden in the current
  view, missing translation.
- The "Find slide by id or title" box filters the list. Drag and drop moves
  slides within and between sections. Shift- or Ctrl-click selects several
  slides and shows a bulk bar (show/hide in a view, remove, compile pages).
  Arrow keys move the focus.
- Remove `qt_deck_editor_tab.py` once its tests are ported. (done: the list
  is `ui/workspace/slide_list.py`, `slide_tree.py` and the backend
  `deck_outline.py`.) `qt_deck_group_dialog.py` stays until step 9: the ⋮
  menu's "Tags…" and "Duplicate deck…" use it.

### 5. Centre: Preview, Source, Split, Details
- **Preview**: the rendered page in the current view and language from
  `preview_build`/`slide_preview` (this includes the uncommitted preview
  benchmark work). Shows rendering, stale and missing states with "Render
  now"; chips for pinned version, course note, language, outdated
  translation and "hidden in this view". Replaces
  `qt_slide_preview_popup.py`.
- **Source**: `LatexPlainTextEdit` with highlighting, line numbers and
  find/replace, extracted from `qt_slide_source_tab.py` into
  `ui/workspace/source_editor.py` behind a `SourceEditor` interface. Adds a
  lint status line and a red badge on the tab, "Ask AI to fix", Insert ▾
  (hyperlink, code file, itemize, definition block, both languages) and
  Insert citation ▾.
- **Split**: Source and Preview side by side; saving re-renders.
- **Details**: slug, frame type, versions and the visibility matrix.
- Remove `qt_slide_source_tab.py`, `qt_syntax_check_dialog.py` (now inline)
  and `qt_insert_citation_dialog.py` (now a popover).

### 6. Side panels (right column, upper part)
Panel picker (▾). Order follows how much backend work each panel needs:
1. **Used in decks**: `slide_usage`. Replaces `qt_slide_usage_dialog.py`.
2. **Slide versions**: `slide_versioning`, "Make this the current version",
   pin options, version bumps. (Done in 6a; `qt_version_history_dialog.py`
   turned out to be the app Info dialog and stays.)
3. **Visibility**: the I/D/A × slide/step matrix writing
   `\conditionalslide`/`\slidestep` through `deck_editor`.
4. **Citations**: `bibliography`; marks missing keys; "Add to .bib with
   chat". Replaces `qt_citation_dialog.py`.
5. **Language**: EN/DE status, outdated marker, Translate (the step 2
   translation task).
6. **Image descriptions**: images on this slide, role, short/long text from
   `alt_blocks`, "Redraft with chat".
7. **Transcript entry**: instructor or student text, summary, per-step text
   from `transcript`.
8. **Speaker notes**: read/edit `\note` content. New parsing goes into
   `slide_source` with tests.
9. ~~**Reveal steps**~~: not implemented (decision 5).

### 7. Compile flow
- Compile split button: the current view; the caret menu offers all views,
  transcripts (Markdown + HTML), selected pages (`partial_compile`) and "Run
  all except archive".
- Pre-check with `latex_lint`; on errors, a dialog with "Build anyway" /
  "Cancel".
- Job panel with per-job progress (`compile_progress`), a Log drawer, Stop,
  and "Retry failed". On failure, a toast "Compile failed in <id>" with "Open
  in Source", which jumps to the line.
- Move `CompileSignals` and the compile orchestration out of `qt_gui.py`
  into `ui/workspace/compile_jobs.py`.

### 8. Command palette (⌘K / Ctrl+K)
- `ui/commands.py`: one action registry used by the top bar, the ⋮ menu,
  context menus and the palette.
- Groups: View & build, Slide <id>, Deck, Project, Go to slide; for longer
  queries, also text in project files (`slide_search`) and "Ask the chat".
  Keys: ↑↓ move, ↵ run, Esc close. Replaces `qt_slide_search_dialog.py`.
- Done when: every action from the former menu bar is in the registry.

### 9. Dialogs and full-screen pages
Rebuilt with the kit under `ui/dialogs/` and `ui/pages/`. Each replaces the
old module named in brackets:
- **Add slide** [`qt_add_slide_dialog`, `qt_duplicate_slide_dialog`,
  `qt_import_dialog`]: source New / Existing / Duplicate / Translate; load
  as Live / Frozen / One reveal step; frame gallery; languages; visibility.
- **Open a project**: recent projects with compatibility chips, "Open
  folder…", "New project…" (name + template).
- **Project compatibility** and **Made with a newer SlideMage**
  [`qt_compat_dialog`].
- **No decks** / **First run** states.
- **Housekeeping** [`qt_archive_unused_dialog`, the housekeeping menu]:
  empty pdf/ and .build/, remove temp files, archive unused, update previews,
  reestablish translation links.
- **Settings** and **Deck settings** as tabbed sheets [`qt_settings_dialog`,
  `qt_deck_settings_dialog`, `qt_admin_slides_dialog`,
  `qt_translation_prompts_panel`]. The AI models tab adds the step 2
  provider, model, key and "Local AI only" settings.
- **Snapshots** [`qt_snapshot_dialog`] as a dialog from the Deck commands.
- **Image descriptions page** [`qt_transcript_tab`, `qt_transcript_preview_tab`]:
  scope (this deck / all), filters (All, No description, Draft, Picture
  changed, No German, Reviewed), search, per-image review.

### 10. AI chat (right column, lower part)
Redesigned 2026-10-10 (user decision): the chat is an **agent**, like
Claude Code, not a suggestion box. The model gets the focused slide as
context and SlideMage tools, and makes the change itself.

- **Context per request**: project, open deck, focused slide (id, path,
  current buffer incl. unsaved edits), View as, language, lint errors.
  A system prompt explains SlideMage's slide conventions (frames,
  `\slidestep`, protected parts, project macros); longer guides can be
  loaded on demand with a `read_guide` tool.
- **Tools** (no shell, nothing outside the project folder):
  - generic: `read_file`, `find_files`, `search`, `edit_file(path,
    old_text, new_text)` (exact, unique replacement, like Claude Code's
    Edit), `write_file` for new text files;
  - SlideMage actions: `list_slides`, `lint`, `render_preview`
    (returns the rendered image), `add_slide`, `add_bib_entry`,
    `compile_deck`.
  - Edit rules: a file open in an editor buffer is edited in the buffer
    (undo, unsaved until saved); other files are saved through the
    normal backend path (slides via `slide_versioning`); edits that
    touch protected parts of a slide (header comment,
    `\setSlideVersion`, `\vbox to 0pt` blocks) are refused; text files
    only; `.build/`, `pdf/`, `.slidemage/` read-only or hidden.
- **Permissions**: "Ask before edits" (default: each edit shows a diff
  and waits for Apply / Reject; a reject is reported to the model) or
  "Edit automatically" (applied at once, diff card with Undo).
- **Providers**: one provider-neutral agent loop. Claude through the
  official `anthropic` SDK (streaming + tool use, prompt caching;
  becomes a dependency; `AnthropicProvider` moves onto it). Ollama
  tool calling through the existing stdlib code comes in 10c. Not the
  Claude Agent SDK (needs the Claude Code CLI, writes to disk directly,
  hard to bundle).
- **UI**: This slide / Whole deck scope, streamed messages, tool and diff
  cards, Stop, permission switch, provider label with local/cloud
  switch (disabled when "Local AI only" is on); palette "Ask the chat".
- **Claude Code terminal** (user decision 2026-10-10, replaces an
  Agent SDK route): the right column's lower part switches between
  **Chat** (the in-app agent above; API key, later Ollama) and **Claude
  Code**, a real terminal (xterm.js in a Qt web view on a pty:
  `ptyprocess` / `pywinpty`) running the user's installed, logged-in
  `claude` in the project folder (Pro login, full Claude Code).
  SlideMage runs a local MCP server the embedded Claude Code connects
  to (focused slide, its unsaved buffer, `render_preview`, `lint`,
  `list_slides`, guides; reusing `ai/tools`), and a PreToolUse hook
  that runs the protected-region check. Claude Code edits files on
  disk; SlideMage watches and reloads them, and warns/blocks when a
  file with unsaved buffer edits is changed underneath. Only available
  when `claude` is installed.
- Split: **10a** agent backend (`ai/agent.py` loop, `ai/tools/`,
  SDK switch, system prompt; tests with a fake provider, opt-in live
  test); **10b** chat UI in the right column, with the Chat | Claude Code
  switch; **10c** Claude Code terminal; **10d** Ollama tools, palette row, remove
  `qt_ai_draft_dialog.py`.

### 11. Finish the switch-over
- Delete any `qt_*` module left over (`qt_render_check.py` becomes a test
  helper or goes), and check that nothing imports the old names.
- Update the README, `SlidemasterManual.md` and the manual slides, the
  screenshots in `example/media/`, and `PYSIDE6_MIGRATION.md` (mark as
  historical). Major version bump (SlideMage 6.0).

### 12. ~~Paint reveal steps on the preview~~
Not implemented (decision 5).

## Notes on the source

- The design tool caps reads at 256 KiB, so the prototype's last ~5 KB of
  script (the end of the chat input's local/cloud toggle) and part of
  `sm-images.js` (embedded screenshots) were not read. The layout markup was
  read in full.
- The prototype's data (decks, slides, bib entries, models) is mock data. The
  real data comes from the backend modules named above.
