# Test review, slice 0 (haiku)

Read-only review. Flags only where a concrete reason is given. Counts: N = test functions in the file (a parametrized test counts once).

| file | test | line | drop/merge/rewrite | reason | covering test |
|---|---|---|---|---|---|
| test_centre_gui.py | test_the_preview_never_renders_the_buffer_of_another_slide | 466 | rewrite | Focuses slide id `ddd`, which the fixture never defines (fixture slides are aaa, bbb, ccc; `link_german` is not called). The assertions only check that preview mode returns no buffer, so the "another slide" case is not exercised. Use an existing second slide such as `ccc`. | test_centre_gui.py::test_rendering_the_buffer_uses_the_unsaved_text_the_scope_and_the_reveal_step (402) covers the positive path |
| test_centre_gui.py | test_keys_in_the_source_view_do_not_leak_into_other_views | 586 | rewrite | The name promises that keys do not leak into other views, but the only assertion is that the source editor became dirty. Nothing checks another view. | none |
| test_languages.py | test_a_project_without_the_key_has_english_and_german_if_it_uses_german_and_nothing_is_written | 47 | rewrite | Name says the project has English and German, but the body creates only an English slide and asserts English alone. The German case is untested under this name. Rename to match the body. | test_german_anywhere_in_a_project_without_the_key_makes_german_a_secondary_language (54) covers the German case |
| test_languages.py | test_a_project_can_have_one_language | 185 | merge | Same operation as test_writing_keeps_the_other_keys_and_is_read_back (secondary is empty here, non-empty there). Could be one test parametrized over the secondary list. | test_languages.py::test_writing_keeps_the_other_keys_and_is_read_back (191) |
| test_compat.py | test_version_order_across_the_renumbering | 196 | merge | Its ordering cases repeat test_updater.py::test_version_comparison (v0.11.0 vs v10.19.0, v1.0.0 vs v0.12.0, v0.12.0 vs v0.11.1). The only unique parts are the four-part `v0.10.19.0` and `v0.9.4.0 > v8.69.0` cases; move those into test_version_comparison and delete this test. | tests/test_updater.py::test_version_comparison (line 14) |
| test_compat.py | test_not_now_changes_nothing_so_it_comes_back | 80 | rewrite | Line 87 asserts the pre-open file content written by make_project, which is fixture data, not behaviour. The behavioural check is line 88 (`checked_version`). Remove line 87 and the `before` read at line 82. | itself (line 88 keeps the real check) |
| test_presentation_resume.py | test_remember_saves_after_a_rest_and_never_raises | 157 | rewrite | No assertion that the broken save was survived. `resume_ui.save` swallows OSError itself, and a Qt slot's exception is printed rather than raised (no pytest-qt in the repo), so the test passes whether or not the guard works. Assert on the outcome, e.g. capture `sys.excepthook` or check the saved file is unchanged and no exception is recorded. | none |
| test_ai_routes.py | test_fake_route_can_script_provider_runner_and_surface | 165 | drop | Lines 174-175 assert the test double's own scripted returns (`fake.task_runner(...)() == "task result"`, `fake.chat_surface() == "surface"`), and line 172 only checks the fake's reply. Nothing in src is exercised beyond what test_route_choices_and_provider_backends already covers. | test_ai_routes.py::test_route_choices_and_provider_backends (41) |
| test_plugin_credentials.py | test_the_file_is_owner_only | 56 | merge | Checks the final mode 0600 and that no *.tmp is left. The mode check is repeated by the last line of test_the_secret_is_owner_only_before_replacement (82); fold the tmp-file check into that test. Both are skipped on Windows, so neither runs on this platform. | test_plugin_credentials.py::test_the_secret_is_owner_only_before_replacement (66) |
| test_reveal_steps.py | test_all_steps_selects_every_overlay_and_refuses_nothing_else | 122 | rewrite | The name promises a refusal check, but nothing asserts a refusal. The last assertion is a substring check (`"{2}" in ...`). Rename to what it checks, or add the refusal case the name names. | none |
| test_insert_popovers_gui.py | test_nothing_is_inserted_into_a_frozen_version | 167 | rewrite | Asserts only that no CitationPopover is visible after the hyperlink insert. It never checks the text: the frozen buffer ("old") and frozen_file on disk are not asserted unchanged, so an insert into the read-only frozen version would pass. Add `pane.current.editor.text() == "old"` and `frozen.read_text() == "old"`. | none |
| test_wizard_portal.py | test_transparent_artwork_and_all_animation_phases_render | 82 | rewrite | Each frame is checked only at pixel (0, 0) for alpha 0. A paint_scene that draws nothing, or draws only outside that corner, passes. Assert that some pixel of the artwork is opaque in at least one phase. | none |
| test_plugin_boundary.py | test_core_does_not_import_plugin_packages | 23 | rewrite | The check reads only the first dotted segment and skips relative imports (`if level == 0`). `from slidemage.plugins.hello import x` or `from .hello import x` in core passes. Compare the full dotted name and resolve relative imports. | test_plugin_boundary.py::test_plugin_api_imports_nothing_from_slidemage_or_qt (32) covers only plugin_api |

test_deck_language.py: read 26 tests, 0 flagged.
test_ai_switch_gui.py: read 24 tests, 0 flagged.
test_compat.py: read 13 tests, 2 flagged (merge and rewrite above).
test_languages.py: read 20 tests, 2 flagged.
test_render_scheduler.py: read 18 tests, 0 flagged.
test_centre_gui.py: read 120 tests, 2 flagged.
test_deck_in_several_groups.py: read 17 tests, 0 flagged.
test_plugin_slides.py: read 15 tests, 0 flagged.
test_ai_chat_service.py: read 15 tests, 0 flagged.
test_compile_flow_gui.py: read 14 tests, 0 flagged.
test_presentation_resume.py: read 13 tests, 1 flagged.
test_ai_routes.py: read 13 tests, 1 flagged.
test_plugin_credentials.py: read 12 tests, 1 flagged.
test_reveal_steps.py: read 11 tests, 1 flagged.
test_debug_instrumentation.py: read 11 tests, 0 flagged.
test_deck_snapshot_gui.py: read 10 tests, 0 flagged.
test_insert_popovers_gui.py: read 9 tests, 1 flagged.
test_translation_placement.py: read 8 tests, 0 flagged.
test_plugin_entry_points.py: read 8 tests, 0 flagged.
test_commands.py: read 8 tests, 0 flagged.
test_scan_cache.py: read 7 tests, 0 flagged.
test_citations_gui.py: read 7 tests, 0 flagged.
test_preview_requests.py: read 6 tests, 0 flagged.
test_deck_settings_maintenance_gui.py: read 6 tests, 0 flagged.
test_wizard_portal.py: read 5 tests, 1 flagged.
test_source_indent_gui.py: read 5 tests, 0 flagged.
test_presenter_paths.py: read 5 tests, 0 flagged.
test_batch_render.py: read 5 tests, 0 flagged.
test_plugin_ai_free_core.py: read 4 tests, 0 flagged.
test_app_settings.py: read 4 tests, 0 flagged.
test_slide_search.py: read 3 tests, 0 flagged.
test_plugin_registry.py: read 3 tests, 0 flagged.
test_about_gui.py: read 3 tests, 0 flagged.
test_plugin_boundary.py: read 2 tests, 1 flagged.
test_deck_new.py: read 2 tests, 0 flagged.
test_status_trace.py: read 1 test, 0 flagged.
test_open_path.py: read 1 test (parametrized to 3 cases), 0 flagged. The whole module is skipped on non-Linux, so on this Windows checkout none of its cases run.

Totals: 37 files, 454 test functions read in full, 13 flagged (drop 1, merge 3, rewrite 9). No files left unfinished.
