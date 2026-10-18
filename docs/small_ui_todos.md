# Small UI todos

- [ ] **Reverse image search through Claude Code.** Add a workflow for finding an image's
  original source and recording the source link. Reference:
  [Turn Claude AI into an image detective](https://copyseeker.net/de/blog/turn-claude-ai-into-an-image-detective-the-ultimate-reverse-search).

- [x] **Investigate differences between left-panel slide thumbnails and the main Preview (v8.21.1).**
  Thumbnails now use the matching verified final slide image for the selected view, language,
  deck context, pinned version and source revision. Shared Instructor snapshots are labelled
  as reference images; previous renders of the correct view are marked old. Region, element
  and individual-step previews can intentionally differ from the whole-slide thumbnail.
  Findings: [Thumbnail and Preview consistency](PREVIEW_THUMBNAILS.md).

- [x] **Optimize preview rendering across Instructor / During course / After course views (v8.21.0).**
  Detect views that produce the same slide output and reuse the rendered preview between them.
  Added **Render all views**, explicit/all-view tool requests and dependency-validated reuse.
  Successful matching tool renders reach the Preview; hidden and superseded results are reported.
  Implementation plan: [Preview views: separate steps](PREVIEW_VIEWS_IMPLEMENTATION_PLAN.md).

- [x] **Further optimize rendering and preview consistency.** Render once for views
  with equivalent supported rules and deck context, align thumbnail/main-pane
  fallback selection, and reduce cache-validation work on the UI thread. Include
  autosave request coalescing, content-based freshness after external Claude Code
  edits, and a batched rendering integration for selected-slide version updates.
  Completed 18 October 2026; [plan](PREVIEW_RENDER_OPTIMIZATION_PLAN.md) and
  [validation evidence](PREVIEW_RENDER_OPTIMIZATION_VALIDATION.md).

- [ ] **Set the default Claude Code chat model.** Add an option to the Claude switch
  dropdown to choose and save the default model used by Claude Code chat.

- [ ] **Update versions of selected slides.** When multiple slides are selected, add
  **Update Versions…** to the right-click context menu. Apply the version update to
  the selected slides, with a shared Patch / Minor / Major choice.

- [ ] **Use the slide/deck language for image descriptions.** If the slide or deck is German,
  Claude should write both short and long image descriptions (alt text) in German in
  `media/alt-text.json`. Currently it writes English descriptions even for German decks.

- [x] **Continuous saving (done: v8.18.0, v8.19.0, v8.19.1), like Overleaf.** Edits in the source editor are saved automatically as
  you type (debounced), so there is no unsaved state to lose. Replace the "Save" button with
  **"Update Version"**: it no longer writes the file but records the current state as a new
  version (the existing version / snapshot step), so the button means "make this a version",
  not "keep my work".

## Follow-ups to continuous saving

- [x] Claude Code's edits in the terminal bypass `save_slide`, so they get no "+" until the next in-app
  write (Update Version still sees them by comparing with the frozen version).
- [x] An autosave does not start a render (Ctrl+S / Ctrl+R do). Live re-render on autosave could be an option.
- [x] Snapshot and export could warn about slides with "+".
- [x] Assistant header: " · unsaved" flickers briefly while typing; show it only for edits that could not be saved.
- [ ] Two failing tests, unrelated to saving: `test_ai_switch_gui.py::test_ai_setup_closes_on_escape_and_on_a_click_outside_but_not_on_its_anchor`
  and `test_chat_gui.py::test_a_six_line_input_and_send_row_fit_at_640px`.
