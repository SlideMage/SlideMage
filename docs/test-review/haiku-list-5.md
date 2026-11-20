# Test review, list 5 (index 5: all 39 files, 459 test functions read)

Totals: 14 flagged rows (drop 1, merge 7, rewrite 6). Every test body in the 39 files was read in full.

Columns: file | test | line | drop/merge/rewrite | reason | covering test

| file | test | line | drop/merge/rewrite | reason | covering test |
|---|---|---|---|---|---|
| test_chat_gui.py | test_refreshing_previews_says_when_the_window_is_busy_or_the_run_failed | 710 | rewrite | `monkeypatch.undo()` reverts every patch made through the shared `monkeypatch` fixture, including the env fixture's setup patches (make_project, build_window, provider stubs), not only the `running` property; scope the busy patch to its own block | n/a |
| test_chat_gui.py | test_the_chats_stop_ends_a_compile_without_asking | 656 | merge | same shape as the preview-refresh stop test: patch a stop_now recorder, start the call on a thread, request stop, assert no question was asked; differs only in the workspace method called | test_the_chats_stop_ends_a_preview_refresh_without_asking |
| test_chat_gui.py | test_the_chats_stop_ends_a_preview_refresh_without_asking | 723 | merge | as above, for refresh_deck_previews; one parametrized stop test over the two calls would cover both | test_the_chats_stop_ends_a_compile_without_asking |
| test_preview_queue.py | test_new_revision_detaches_obsolete_pane_without_cancelling_other_consumers | 355 | rewrite | `assert view._page.pixmap is not None and view._page.pixmap is not None` repeats one clause; nothing checks that the shown page is the new one (from new_pdf) rather than the old one | n/a |
| test_preview_queue.py | test_actual_parent_destruction_closes_lifetime_and_discards_worker_result | 495-496 | rewrite | `pytest.fail` lambdas for prepare_preview_images and open_pdf run on the worker thread (preview_view.Thread); a Failed raised there goes to the thread excepthook and does not fail the test, so a bug that rasterises after destruction would pass unless the assertions catch it. Record the call in a list and assert on it in the main thread | n/a |
| test_presentation_core.py | test_next_large_clock_has_the_next_slide_large_the_notes_above_a_big_clock_and_the_strip | 212 | rewrite | the line `profile_named("Mirror and clock") is profile` repeats line 469 of test_the_builtins_names_and_the_old_clock_name_still_resolves; the rest of the test is unique, so only the duplicate assertion should go | test_the_builtins_names_and_the_old_clock_name_still_resolves |
| test_plugin_catalogue.py | test_broken_plugin_entry_is_skipped | 143 | merge | same check as the parametrized test_entry_failing_one_check_is_skipped (copy one entry, break it, expect it dropped); its sha256 case is the only one missing from the parametrized list, so add it there and drop this test | test_entry_failing_one_check_is_skipped |
| test_plugin_catalogue.py | test_http_error_raises_and_writes_no_cache | 242 | merge | identical shape to test_bad_json_raises_and_writes_no_cache (line 252): fetch fails, assert no cache file; one parametrized test over the status/body pair covers both | test_bad_json_raises_and_writes_no_cache |
| test_plugin_catalogue.py | test_bad_json_raises_and_writes_no_cache | 252 | merge | see test_http_error_raises_and_writes_no_cache | test_http_error_raises_and_writes_no_cache |
| test_plugin_catalogue.py | test_too_new_propagates_and_is_not_cached | 261 | merge | same fetch-too-new flow as test_too_new_keeps_older_cache; differs only in whether an older cache exists beforehand; one test parametrized over that precondition covers both | test_too_new_keeps_older_cache |
| test_plugin_catalogue.py | test_too_new_keeps_older_cache | 272 | merge | see test_too_new_propagates_and_is_not_cached | test_too_new_propagates_and_is_not_cached |
| test_ai_fix_gui.py | test_a_frozen_version_cannot_be_fixed_and_a_bib_has_no_check | 280 | rewrite | the name promises a bib check, but the body only covers the frozen version; the bib case is in test_a_bib_is_not_checked, so the name is wrong and the body should match it | test_a_bib_is_not_checked |
| test_framework_regression.py | test_font_names_lose_their_subset_tag | 63 | rewrite | the first assertion (line 66) uses a base-14 helv font, which never carries a subset "+" tag, so it passes even if font_list stopped stripping tags; only line 67 (SUBSET_TAG_RE) checks the behaviour; embed a real subset font or drop line 66 | n/a |
| test_ai_routes_ui_gui.py | test_route_owned_surface_is_shown_and_new_conversation_resets_it | 111 | drop | its send and new-conversation reset asserts (lines 121-125) repeat test_route_owned_surface_keeps_its_conversation_and_confirms_ending_it; the only unique line is the route switch showing the surface (118-120), which can move into that test | test_route_owned_surface_keeps_its_conversation_and_confirms_ending_it (test_chat_gui.py) |

read 47 tests, 3 flagged (test_chat_gui.py; 1 rewrite, 2 merge)
read 38 tests, 2 flagged (test_preview_queue.py; 2 rewrite)
read 34 tests, 1 flagged (test_presentation_core.py; 1 rewrite)
read 25 tests, 5 flagged (test_plugin_catalogue.py; 5 merge)
read 23 tests, 0 flagged (test_presenter_update.py)
read 21 tests, 0 flagged (test_selection_tasks_gui.py)
read 20 tests, 0 flagged (test_section_editor.py)
read 18 tests, 0 flagged (test_settings_deck_groups_gui.py)
read 17 tests, 0 flagged (test_hook_geometry.py; the tex-compiling tests skip without SLIDEMAGE_TEX_TESTS=1 and latexmk)
read 15 tests, 0 flagged (test_readability_gui.py)
read 15 tests, 1 flagged (test_ai_fix_gui.py; 1 rewrite)
read 14 tests, 0 flagged (test_image_languages.py)
read 13 tests, 0 flagged (test_presenter_app.py)
read 13 tests, 0 flagged (test_bundled_copies.py)
read 12 tests, 0 flagged (test_plugin_manifest.py)
read 11 tests, 0 flagged (test_review_transcript_import.py)
read 11 tests, 1 flagged (test_framework_regression.py; 1 rewrite)
read 10 tests, 0 flagged (test_templates.py)
read 9 tests, 0 flagged (test_preview_dependencies.py)
read 8 tests, 0 flagged (test_updater_folder.py)
read 8 tests, 0 flagged (test_protected_regions.py)
read 8 tests, 0 flagged (test_compile_records.py)
read 7 tests, 0 flagged (test_slide_usage.py)
read 7 tests, 0 flagged (test_compat_gui.py)
read 6 tests, 0 flagged (test_previews_cache.py)
read 6 tests, 0 flagged (test_deck_versions.py)
read 6 tests, 1 flagged (test_ai_routes_ui_gui.py; 1 drop)
read 5 tests, 0 flagged (test_review_persistence.py)
read 5 tests, 0 flagged (test_find_replace_gui.py)
read 4 tests, 0 flagged (test_shared_widgets_gui.py)
read 4 tests, 0 flagged (test_plugin_campusonline_e2e.py; skipped unless SLIDEMAGE_E2E_CAMPUSONLINE names a checkout)
read 4 tests, 0 flagged (test_bibliography_template.py)
read 3 tests, 0 flagged (test_small_helpers.py)
read 3 tests, 0 flagged (test_project_context.py)
read 3 tests, 0 flagged (test_ai_free_editor_gui.py)
read 2 tests, 0 flagged (test_render_evidence.py)
read 2 tests, 0 flagged (test_design_handbook.py)
read 1 test, 0 flagged (test_terminal_theme.py; parametrized over light and dark)
read 1 test, 0 flagged (test_packaging.py)
