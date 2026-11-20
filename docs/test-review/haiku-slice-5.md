# Test review, slice 5 (40 files under tests/)

Read-only review: no edits to tests/ or src/, no commits. Every test body in the 40 files was read in full.
Flags only where a concrete breakage can pass the test, or a concrete overlap exists. Parametrized cases count once.
Columns: file | test | line (def line) | drop/merge/rewrite | reason | covering test

| file | test | line | drop/merge/rewrite | reason | covering test |
|---|---|---|---|---|---|
| test_image_source_gui.py | test_a_citation_changed_by_an_agent_shows_to_review_in_both_views | 115 | merge | Same chain as test_a_citation_saved_in_the_panel_shows_on_the_page_and_back (lines 85-88): the store is flagged SOURCE_TO_REVIEW, the page chip and the panel chip read "To review". Only the writer differs (direct save_source call instead of the panel save). Could be a second writer case of the panel test. | test_a_citation_saved_in_the_panel_shows_on_the_page_and_back (same file, line 81) |
| test_settings_ai_gui.py | test_the_old_tabs_open_the_ai_tab_at_their_section | 103 | rewrite | The only parametrized case is (PROMPTS, "prompts"), so `or section == "prompts"` on line 110 is always true: the scrollbar assertion cannot fail. Make it a real check or delete it. The sheet.scrolled_to check on line 105 is the real assertion. | same test, line 105 |
| test_code_file.py | test_inline_code_keeps_its_backslash_in_the_transcript | 42 | merge | The SMCmd-to-backtick-with-backslash path is already asserted by the parametrized case \SMCmd{input} in test_transcript_conversion.py. Only the \SMCode{c\_secondary\_blue} and \texttt{\textbackslash pause} parts are unique here; fold them into the parametrization of the other test. | test_transcript_conversion.py::test_inline_code_is_verbatim |
| test_template_catalog.py | test_the_stress_template_picks_lmsans_and_stays_out_of_the_apps_reach | 143 | rewrite | The name says it checks that the stress template picks lmsans, but the body only checks that three files exist and that the app folders have no copy. A template that does not pick lmsans still passes. The pick is asserted in test_the_stress_template_sets_every_hook_of_the_catalog (line 140), so rename this test to what it checks or drop the lmsans claim. | test_the_stress_template_sets_every_hook_of_the_catalog (line 140) |
| test_render_key.py | test_two_producers_replace_one_object_of_a_key | 195 | merge | Both tests assert that repeated puts for one unit leave store.count() == 1 and one object directory holding only the key. The only extra here is the origin check (record["origin"] == origin). Fold that into the other test. | test_repeated_puts_of_an_unswept_label_leave_one_object (line 212) |
| test_images_page_gui.py | test_switching_slides_during_a_translation_asks_first | 675 | merge | Its "No" branch (stays on the slide, list row back to 0) repeats what test_declining_switch_anyway_after_a_click_keeps_the_list_on_the_slide_on_show checks through a real mouse click, including the list selection. Keep the "Yes" branch by moving it into that test. | test_declining_switch_anyway_after_a_click_keeps_the_list_on_the_slide_on_show (line 899) |
| test_images_page_gui.py | test_another_order_keeps_the_slide_on_show_and_its_translation | 945 | rewrite | Line 955 stubs QMessageBox.question with pytest.fail, and that stub runs inside a Qt signal (changed.emit). PySide6 reports an exception raised in a slot and does not re-raise it into the test, and no pytest-qt is installed (tests/conftest.py has only the qapp fixture). So if the page did ask, the test would not fail. Record the questions in a list and assert it is empty. | test_a_show_filter_that_drops_the_slide_asks_during_a_translation_and_no_restores_it (line 921) already records its answers this way |
| test_images_page_gui.py | test_a_show_filter_that_keeps_the_slide_does_not_ask_and_keeps_the_translation | 963 | merge | Same shape as test_another_order_keeps_the_slide_on_show_and_its_translation (line 945): no question asked, same current slide and form, same list row. Only the control differs (Show filter instead of sort order). Make both one test parametrized over the control. | test_another_order_keeps_the_slide_on_show_and_its_translation (line 945) |
| test_images_page_gui.py | test_a_show_filter_that_keeps_the_slide_does_not_ask_and_keeps_the_translation | 963 | rewrite | Line 968 has the same pytest.fail-inside-a-Qt-slot stub as line 955: an unexpected question would be swallowed, so the test can pass while the guard is broken. Use a recorded list asserted empty. | test_a_show_filter_that_drops_the_slide_asks_during_a_translation_and_no_restores_it (line 921) |
| test_plugin_host.py | test_cancel_token_stops_host_tools | 669 | rewrite | The name says the token stops the host's tools, but the body only checks request_stop()/is_set() on the token and that ai_tools() returns something other than None. A host that ignores the token passes. Assert that a tool call made after request_stop() is refused or returns the stopped result. | tests/test_agent_tools.py line 616 (cancel.request_stop() on a toolbox) |

## Per-file counts

Test functions read in full, and how many are flagged. Parametrized functions count once.

read 47 test functions, 3 flagged (4 rows) -- test_images_page_gui.py
read 39 test functions, 1 flagged -- test_plugin_host.py
read 33 test functions, 0 flagged -- test_plugin_settings_tab.py
read 30 test functions, 0 flagged -- test_plugin_ui.py
read 22 test functions, 1 flagged -- test_render_key.py
read 21 test functions, 0 flagged -- test_image_review.py
read 20 test functions, 0 flagged -- test_diagnostics.py
read 18 test functions, 0 flagged -- test_make_readable_gui.py
read 16 test functions, 0 flagged -- test_plugin_upgrade.py
read 15 test functions, 1 flagged -- test_template_catalog.py
read 15 test functions, 0 flagged -- test_ai_profile.py
read 14 test functions, 0 flagged -- test_image_source.py
read 13 test functions, 0 flagged -- test_restore_version.py
read 13 test functions, 0 flagged -- test_check_layout_margins.py
read 12 test functions, 1 flagged -- test_settings_ai_gui.py
read 11 test functions, 0 flagged -- test_slide_versions_gui.py
read 11 test functions, 0 flagged -- test_partial_compile.py
read 10 test functions, 0 flagged -- test_transcript_conversion.py
read 9 test functions, 0 flagged -- test_preview_raster.py
read 8 test functions, 0 flagged -- test_view_themes.py
read 8 test functions, 0 flagged -- test_readability_tool.py
read 8 test functions, 0 flagged -- test_manual_group.py
read 7 test functions, 0 flagged -- test_sm_rename.py
read 7 test functions, 0 flagged -- test_language_line.py (9 parametrized cases)
read 6 test functions, 0 flagged -- test_slide_branch.py
read 6 test functions, 1 flagged -- test_image_source_gui.py
read 6 test functions, 0 flagged -- test_color_modes_app.py
read 5 test functions, 0 flagged -- test_slide_preview_cleanup.py
read 5 test functions, 0 flagged -- test_latex_export_gui.py
read 4 test functions, 0 flagged -- test_theme_tokens.py (6 parametrized cases)
read 4 test functions, 0 flagged -- test_preview_pages.py
read 4 test functions, 1 flagged -- test_code_file.py
read 3 test functions, 0 flagged -- test_project_watch.py (4 cases)
read 3 test functions, 0 flagged -- test_appendix_toc.py (9 cases)
read 2 test functions, 0 flagged -- test_smoke.py (test_module_imports from the earlier inventory is already gone at HEAD)
read 2 test functions, 0 flagged -- test_render_lookup.py
read 2 test functions, 0 flagged -- test_duplicate_deck_gui.py
read 1 test function, 0 flagged -- test_tool_guidance.py
read 1 test function, 0 flagged -- test_presenter_imports.py (its PRESENTER_MODULES list is reused by test_presenter_paths.py; not a duplicate)
read 1 test function, 0 flagged -- test_cli_self_test.py

Totals: 40 files, 462 test functions read, 9 functions flagged (10 table rows). Files not finished: none.
