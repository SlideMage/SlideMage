# SlideMage UI redesign (Prototype v3)

Status: in progress on branch `ui-redesign`. Steps 1–6 done (see
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

Last updated 2026-10-09. Suite after step 6: 865 passed, 4 skipped, about
7 s; ruff clean.

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
| 7–11 | | not started |

### What exists now
- `ui/kit/`: `tokens.py` (light/dark tokens), `kit_qss.py`, `theme.py`
  (moved from `qt_theme.py`), `fonts.py` (`load_fonts()`), `widgets.py`
  (SegmentedControl, Chip, SplitButton, IconButton, IconLabel, Button,
  PopoverMenu, Toast, Card, ModalSheet, `apply_shadow`), `gallery.py`
  (`python -m slidemage.ui.kit.gallery`). Fonts in `assets/fonts/` (Roboto
  and Roboto Mono SIL OFL 1.1, Material Icons Apache 2.0).
- `ai/`: `providers.py` (`ChatProvider`, `OllamaProvider`,
  `AnthropicProvider`, `ProviderError`, `Cancelled`), `resolver.py`
  (`provider_for_task`, local-only global/per project, consent),
  `credentials.py` (API key: env → keyring → settings file),
  `ollama_admin.py`. Task logic stays in `ai_draft` (`SlideDrafter`),
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

### Temporary hosts still in place
- Centre stack in `window.py`: `TranscriptPreviewTab` / `TranscriptTab`
  for Images (until step 9).
- Log panel under the columns (until step 7's Log drawer).
- Right column: `side_panels.py` (vertical `QSplitter`, chat goes below
  in step 10) and `panels/` (`base.py`, `used.py`, `versions.py`,
  `visibility.py`, `citations.py`, `language.py`, `images.py`,
  `transcript_entry.py`, `notes.py`; registry `PANELS` in
  `panels/__init__.py`). Panels have `dirty`/`flush()`; the close prompt
  counts them; Notes edits go into the Source buffer (versioned save).
- Details view: slug, frame, language fact, Duplicate / Rename / Delete.
- Citations "Add to .bib…" and Cite ▾ footer open `qt_citation_dialog`
  (the add-entry form, kept; step 10 chat may take over).
- Image descriptions panel and the Images page both edit
  `media/alt-text.json`; the review stamp is duplicated in
  `qt_transcript_tab._save` (fold into `alt_images.save_slide_image` in
  step 9).
- `qt_version_history_dialog.py` is the app's Info dialog (release
  history, license), not a slide-version viewer; step 6 left it. Decide
  its home in step 9.
- "Add reference to .bib…" (Cite ▾ footer) still opens
  `qt_citation_dialog` (until step 6 Citations).
- `qt_deck_group_dialog.py` kept for ⋮ "Tags…" and "Duplicate deck…"
  (until step 9).

### Carried over to later steps
- Preview chip "course note" has no slide-level backend data (not
  built); "outdated translation" is wired (`translation_link`: original
  saved via SlideMage after the translation was written, not a content
  check). The slide list's lint dot follows the saved file.
- Citations panel doesn't refresh after a hand edit of Slidemaster.bib;
  no "update translation" action yet (only Open); Image descriptions
  panel path label wraps awkwardly; some unused imports in `ui/`
  (`window.py` `bare_id`, `gallery.py`, `theme.py`, `ai_fix.py`).
- Step 7: `try_start_ollama_task`/`end_ollama_task` also serialise cloud
  tasks (too strict); `deck_outline.forget_lint()` is not wired to "Refresh
  decks"; deck switch rebuilds the list twice (harmless, ~75 ms).
- Step 9: "Move to section" menu can be long (13 entries on the manual).
- Step 11: `tools/manual/make_screenshots.py` still uses the old window API
  (broken); `docs/SlideMage.md` still describes `qt_deck_table.py`;
  stale comment mentions of removed modules in `slide_preview.py`.

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

### How the work is run (to resume)
- Orchestrator: the main session briefs one agent per step, reviews the
  result (diff, tests, screenshots in the scratchpad), sends corrections,
  then commits on `ui-redesign` with only that step's files. The user asked
  for no extra whole-branch review at the end.
- Agents: Sonnet at high effort, via `.claude/agents/ui-step-implementer.md`
  (earlier steps ran at medium). Step 5 was split into 5a and 5b,
  run by one agent resumed with SendMessage.
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
  flaky exit crashes (step 4).
- Prototype: re-fetch with the DesignSync tool (project
  `3e2dd21f-cbd5-4329-a0d7-d3e1779450aa`, `get_file` on
  `SlideMage Prototype v3.dc.html`; needs `/design-login`). Reads are
  capped at 256 KiB, so the last ~5 KB of script are missing. Save it to
  the session scratchpad and point agents at that path. Prototype path in
  the 2026-10-09 evening session:
  `/tmp/claude-1000/-home-juergen-github-SlideMage/846a66b3-5695-49c8-8ed3-dad860494bc8/scratchpad/prototype-v3.html`.

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
- Scope (This slide / Whole deck), suggestion chips, messages with quoted
  context and inline diffs, Apply / Discard, thinking indicator, waiting
  note, and the provider label with a local/cloud switch (disabled when
  "Local AI only" is on).
- Requests go only through `ai/tasks.py`. Applied changes save through
  `slide_versioning`, as manual edits do.
- Replaces `qt_ai_draft_dialog.py`.

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
