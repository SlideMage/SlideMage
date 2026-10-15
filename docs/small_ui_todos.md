# Small UI todos

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
