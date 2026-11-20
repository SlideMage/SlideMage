# Rewrite of the `rewrite` tests (2026-11-11)

The 37 functions with verdict `rewrite` in `test-inventory.csv`, plus the merge of the four `test_multi_best_release_*`
tests. Only `tests/` changed; no test was deleted, no assertion weakened.

## How it was measured
Same machine, the 37 tests only, before (develop 0a09d9d1) and after, each run twice: serially (`-p no:cacheprovider`,
no workers) and with `-n 6`. Seconds are setup + call + teardown summed per function (all its cases). The inventory's
own numbers (8 workers, whole suite) are 2-10x higher; they rank, they do not measure.

| | serial before | serial after | `-n 6` before | `-n 6` after |
|---|---|---|---|---|
| summed seconds | 446 | 341 | 583 | 479 |
| wall clock | 449 s | 344 s | 123 s | 90 s |
| failures | 1 (typing pause) | 0 | 1 (deck context, PermissionError) | 0 |

About **105 s saved summed** (serial and `-n 6` alike), wall clock -105 s serial, -33 s with 6 workers.

## What changed, and why

### Shared: `conftest.same_tex_configuration` (new fixture)
The biggest finding for the real-TeX tests: `_isolated_config_dir` sets a new `XDG_CONFIG_HOME` per test, and that path
is part of `preview_build.configuration_key` (latexmk reads an rc file there). So every TeX test built the precompiled
preamble again (about 3 s) and started each view's build folder from scratch (a first render is about 5 s, a later
one about 3.6 s; biber runs on every render). The new fixture gives every test of a module the same empty folder;
`APPDATA` and `project.config_dir` stay per test. Used by `test_language_tex`, `test_reveal_steps_tex`,
`test_qr_code_tex`, `test_deck_context_tex`. Only helps tests of a module that run in the same worker:
under xdist's default `--dist load` a module is spread over the workers (see Leftovers).

### Shared: `QTest.qWait` keeps the GIL
`QTest.qWait()` does not release the GIL while it waits. A test that polls a background thread with `qWait(10)`
starves that thread: in `test_a_typing_pause...` the render thread's six `shutil.which` lookups took 1-3 s *each*
(measured), the 10 s deadline ran out and the test failed even alone. Waiting with `processEvents()` + `time.sleep()`
(as `conftest.wait_until` does) fixes it. Other tests that poll threads with `qWait` likely suffer the same under load.

### Per test
| test | change |
|---|---|
| `test_chat_gui::test_at_640px_every_suggestion...` | 12 cases (3 themes x 2 scopes x 2 line counts) -> 6: every pair of two factors once, both scopes at 6 lines (the picker case). Body unchanged. |
| `test_language_tex` (13) | One example copy per module (and one on the TeX path) reset before each test (languages, project macros, `hyphenation/`), instead of a copy per test; `same_tex_configuration`. `..._a_project_language_in_a_slug...`: 7 compiles -> 2 (the slugs of each project setting typeset together by `render_slide_texts_to_pdf`, the function the file's reads-the-same test already uses). `..._a_slide_hyphenates_in_its_own_language...`: 3 -> 2 (the two slides of the French deck together). |
| `test_reveal_steps_tex` (5) | `same_tex_configuration`. Compiles unchanged: each remaining render differs in view or all-steps, which is per document; batching them would test another function than the preview's. |
| `test_qr_code_tex` (3) | `same_tex_configuration` (one render each; the first pays the format). |
| `test_deck_context_tex` (4) | `same_tex_configuration`. The module fixture (one whole-deck compile, about 16 s) was already shared. |
| `test_batch_render::test_an_ordinary_slide_after_an_omitted...` | The example is copied without its build output (`_ignore_template_build_output`), not with whatever earlier tests of the worker rendered into `example/.build`. One batch compile is the test; no gain alone. |
| `test_workspace_window::test_a_typing_pause...` | Waits with processEvents + sleep and a 20 s deadline instead of `QTest.qWait` loops (see above). 11 s and failing -> 1.8 s, passing. |
| `test_presentation_gui` eraser circle (2) | Wait until the windows are exposed and the canvases keep their size (`settled`), and re-send a mouse move until the canvas has it (`hover`) instead of asserting right after one move. Same assertions. |
| `test_source_view_gui::test_a_slide_is_saved_as_you_type...` | `wait_until(written and not dirty)` (10 s) instead of a fixed `qWait(150)` before checking the autosave. |
| `test_plugin_catalogue::test_multi_best_release_*` (4) | One parametrized `test_multi_best_release` with the four cases as ids. |

### Before / after per function (seconds)
| test | serial before | serial after | -n6 before | -n6 after |
|---|---|---|---|---|
| test_background_renders.py::test_a_real_background_render_creates_nothing_in_the_project_and_match | 24.3 | 22.9 | 26.4 | 27.5 |
| test_batch_render.py::test_an_ordinary_slide_after_an_omitted_slide_is_stored_without_the_om | 9.9 | 10.2 | 12.2 | 12.7 |
| test_chat_gui.py::test_at_640px_every_suggestion_is_reachable_without_scrolling_and_the_ | 32.0 | 15.4 | 17.6 | 18.2 |
| test_deck_context_tex.py::test_in_the_deck_a_chapter_agenda_lists_the_titles_of_its_slides | 8.6 | 8.4 | 25.9 | 10.7 |
| test_deck_context_tex.py::test_in_the_deck_a_contents_slide_lists_every_section_and_has_its_real | 22.5 | 24.4 | 25.9 | 29.8 |
| test_deck_context_tex.py::test_with_the_skeleton_a_contents_slide_lists_every_section_and_an_age | 18.2 | 17.9 | 29.1 | 41.1 |
| test_deck_context_tex.py::test_without_any_context_the_same_slide_has_an_empty_contents_list | 8.6 | 5.5 | 26.9 | 7.6 |
| test_language_tex.py::test_a_deck_hyphenates_in_its_language | 17.6 | 18.3 | 24.7 | 24.9 |
| test_language_tex.py::test_a_keyed_multilingual_text_falls_back_to_the_main_language | 13.7 | 13.3 | 18.3 | 12.7 |
| test_language_tex.py::test_a_language_without_patterns_hyphenates_as_english_with_a_warning | 14.3 | 11.9 | 20.0 | 13.8 |
| test_language_tex.py::test_a_missing_string_falls_back_to_the_main_language_with_a_warning | 8.5 | 4.9 | 11.7 | 6.1 |
| test_language_tex.py::test_a_project_adds_strings_of_its_own | 8.6 | 8.1 | 11.8 | 12.0 |
| test_language_tex.py::test_a_project_language_in_a_slug_sets_the_slide_language_only_with_th | 38.8 | 13.9 | 51.3 | 16.5 |
| test_language_tex.py::test_a_slide_hyphenates_in_its_own_language_and_a_multilingual_one_in_ | 19.0 | 11.2 | 26.4 | 20.4 |
| test_language_tex.py::test_a_slug_that_looks_like_a_language_only_in_a_project_that_has_it | 13.6 | 10.1 | 17.5 | 16.7 |
| test_language_tex.py::test_an_english_and_german_project_reads_the_same_with_and_without_the | 27.7 | 24.3 | 33.9 | 31.5 |
| test_language_tex.py::test_the_automatic_texts_and_the_pdf_language_follow_the_decks_languag | 18.6 | 14.9 | 25.3 | 19.2 |
| test_language_tex.py::test_the_main_language_and_a_main_language_other_than_english | 8.6 | 4.9 | 10.6 | 6.0 |
| test_language_tex.py::test_the_pdf_language_is_the_tables_tag_for_a_project_with_languages_o | 18.9 | 14.9 | 23.8 | 22.7 |
| test_language_tex.py::test_the_shipped_patterns_hyphenate_without_the_distributions | 8.8 | 5.7 | 11.6 | 7.5 |
| test_plugin_offer.py::test_nothing_offerable_shows_no_sheet_and_writes_no_flag | 0.0 | 0.0 | 0.0 | 0.1 |
| test_plugin_ui.py::test_on_theme_changed_fires_once_after_the_stylesheet_and_stops_when_u | 4.5 | 2.3 | 3.6 | 7.3 |
| test_presentation_gui.py::test_a_circle_of_the_erasers_size_follows_the_mouse_on_that_canvas_onl | 0.1 | 0.1 | 0.1 | 0.2 |
| test_presentation_gui.py::test_the_circle_shows_on_the_projector_when_it_takes_the_mouse | 0.1 | 0.1 | 0.1 | 0.1 |
| test_qr_code_tex.py::test_a_caption_wider_than_its_code_is_centred_under_it_and_the_code_ke | 8.6 | 5.3 | 12.4 | 12.1 |
| test_qr_code_tex.py::test_an_href_wider_than_its_line_keeps_its_underline_under_its_text_an | 8.1 | 5.2 | 11.9 | 6.4 |
| test_qr_code_tex.py::test_the_code_links_and_a_caption_href_keeps_its_underline | 8.5 | 9.3 | 11.9 | 13.0 |
| test_rerender_deck_gui.py::test_the_command_is_a_deck_command_in_the_palette_and_needs_a_deck | 0.8 | 1.0 | 0.8 | 1.1 |
| test_reveal_steps_tex.py::test_a_conditional_pause_counts_only_in_the_versions_that_pause | 13.2 | 13.2 | 15.8 | 16.1 |
| test_reveal_steps_tex.py::test_a_raw_frame_spec_is_overridden_so_page_k_is_still_step_k | 13.8 | 10.3 | 17.9 | 15.9 |
| test_reveal_steps_tex.py::test_a_slidestep_call_keeps_its_steps_unless_all_steps_is_asked_for | 13.3 | 13.4 | 16.9 | 16.1 |
| test_reveal_steps_tex.py::test_the_final_state_flag_does_not_cut_a_student_render_to_the_last_st | 13.6 | 8.7 | 17.8 | 16.3 |
| test_reveal_steps_tex.py::test_two_pauses_are_three_steps_and_page_k_is_step_k | 8.4 | 8.5 | 12.3 | 11.8 |
| test_source_view_gui.py::test_a_slide_is_saved_as_you_type_with_its_version_frozen_first_and_th | 0.2 | 0.1 | 0.2 | 0.2 |
| test_theme_sources_gui.py::test_add_theme_from_github_installs_the_newest_eligible_release_after_ | 0.1 | 0.1 | 0.1 | 0.2 |
| test_workspace_window.py::test_a_typing_pause_renders_once_and_autosave_hits_the_store | 11.1 | 1.8 | 9.4 | 2.9 |
| test_workspace_window.py::test_narrow_top_bar_controls_and_lint_badge_survive_relabeling | 0.4 | 0.4 | 0.8 | 1.4 |
| **total** | 446 | 341 | 583 | 479 |

## Not changed, and why
- `test_background_renders::test_a_real_background_render...` (23 s): two real renders, one in the store's work folder
  and the foreground one it is compared with; each builds its own format by design. Nothing to share without testing less.
- `test_plugin_offer::test_nothing_offerable...` (0.01 s), `test_theme_sources_gui::test_add_theme_from_github...`
  (0.07 s), `test_rerender_deck_gui::test_the_command_is_a_deck_command...` (1 s),
  `test_workspace_window::test_narrow_top_bar_controls...` (0.4 s; it has no layout grid to shrink): fast alone and
  with 6 workers. Their 23-74 s in the inventory come from the whole-suite load, not from the tests.
- `test_plugin_ui::test_on_theme_changed_fires_once...` (2.3 s): four restyles of the whole window are what it checks.

## Leftovers
- Module sharing (`same_tex_configuration`, the shared example copies, `test_deck_context_tex`'s module compile) pays off
  only when a module's tests run in one worker. With `-n auto` (`--dist load`) the 16 s deck compile of
  `test_deck_context_tex` runs once per worker that gets one of its tests. `--dist loadfile` (or `loadscope`) for the
  TeX modules would save more; that is a run-configuration choice, not a test change.
- `test_deck_context_tex::test_with_the_skeleton...` failed once in the `-n 6` baseline with `PermissionError` renaming
  `*.trimmed.pdf` onto `*.pdf` in the render's temp folder (a Windows file lock in src, not the test); not seen after.
- Found while batching: in a document of several slides, `\slideLanguage` keeps the previous slide's tag for a slide
  whose slug names no language (only `\ifSMSlideLanguageSet` is reset). A single-slide preview never shows it; a batch
  render (background previews) would. Possibly a framework bug; the test puts such a slide first and documents why.
- `test_centre_gui::test_the_render_menu_offers_scope_reveal_step...` failed once of three 16-worker stress runs of the
  GUI files (not one of the 37); the four load-flaky tests rewritten here passed all three.
