# Test review, slice 4 (read-only review)

Slice 4 = element index 4 of slices.json (0-based; the fifth list, starting at test_images_page_gui.py).
Columns: file | test | line | drop/merge/rewrite | reason | covering test

| file | test | line | drop/merge/rewrite | reason | covering test |
|---|---|---|---|---|---|
| test_slide_branch.py | test_other_decks_can_switch_too | 65 | merge | Same fixture and call as test_only_the_decks_asked_for_load_the_new_slide_and_pinned_calls_stay; only the deck list differs. One test parametrized over the deck list (["talk"] vs ["talk", "course"]) would cover both, with the course-line assertion as the expected value. | test_only_the_decks_asked_for_load_the_new_slide_and_pinned_calls_stay (line 54) |
| test_settings_ai_gui.py | test_the_old_tabs_open_the_ai_tab_at_their_section | 102 | rewrite | Line 110 is `assert ... > 0 or section == "prompts"`. The only parametrized case has section "prompts", so the disjunction is always true and the scroll check can never fail. Assert the scroll position itself (or drop the `or`) and keep the parametrization meaningful. | test_the_ai_tab_has_the_policy_the_models_the_prompts_and_a_section_per_service (line 33) only covers the tab, not the scroll |
| test_diagnostics.py | test_the_cli_takes_the_debug_flag | 212 | rewrite | Name and assertion disagree: the test only checks `cli._role` ("--claude-hook" -> "hook"). The --debug wiring it is named for (cli.py line 93, `diagnostics.setup(..., debug=True if DEBUG_FLAG in given ...)`) is never run, so it would still pass if --debug were dropped from the CLI. Either drive `cli.main` with --debug and check the debug log or rename it to test only the role. | test_debug_flag_is_passed_on_until_it_is_turned_off (line 187) covers setup(debug=True) directly, not the CLI path |
| test_plugin_host.py | test_cancel_token_stops_host_tools | 669 | rewrite | The only assertion is `box is not None`. The name says a cancelled token stops the host's tools, but nothing checks that the token is wired into the returned toolbox or that a tool sees it set. It would pass if `ai_tools` ignored `cancel` entirely. | none for the wiring; test_chat_context_builds_fresh_tools_on_gui_and_exposes_full_focus (line 722) only checks that the token is passed to ai_tools |
| test_images_page_gui.py | test_the_order_follows_the_open_deck | 181 | merge | Its deck-order check (sort_order -> two, one) is the same setup and assertion as the second half of test_another_order_keeps_the_slide_on_show_and_its_translation, which also drives the deck order (via the signal). Keep the files-order assertion here, or fold both into one test. | test_another_order_keeps_the_slide_on_show_and_its_translation (line 945) |
| test_images_page_gui.py | test_draft_all_confirms_then_runs_the_queue_and_reports_errors | 466 | rewrite | The name promises that errors are reported, but the test only covers a declined run and a successful one (FakeBackend never returns an error). A broken error report would pass. Add a backend that returns an error and assert the report, or drop "reports_errors" from the name. | test_stop_ends_a_batch_after_the_current_image_and_takes_the_click_back (line 511) uses an error result but does not assert the report; test_a_failed_translation_says_so_and_frees_the_form (line 655) covers translation errors only |
| test_color_modes_app.py | test_a_view_can_have_any_mode_of_its_theme | 72 | merge | Lines 80-84 (an entry without a mode turns the deck default off) repeat test_an_entry_without_mode_turns_a_dark_default_off, which checks the same rule with the dark switch instead of the grey override. The mode-override part (lines 73-78) is the only unique content. | test_an_entry_without_mode_turns_a_dark_default_off in test_view_themes.py (line 44) |

Per-file summary:
- test_smoke.py: read 2 tests, 0 flagged
- test_cli_self_test.py: read 1 test, 0 flagged
- test_tool_guidance.py: read 1 test, 0 flagged
- test_presenter_imports.py: read 1 test, 0 flagged
- test_duplicate_deck_gui.py: read 2 tests, 0 flagged
- test_code_file.py: read 4 tests, 0 flagged
- test_theme_tokens.py: read 4 tests, 0 flagged
- test_project_watch.py: read 4 tests, 0 flagged
- test_latex_export_gui.py: read 5 tests, 0 flagged
- test_color_modes_app.py: read 6 tests, 1 flagged
- test_slide_branch.py: read 6 tests, 1 flagged
- test_render_lookup.py: read 2 tests, 0 flagged
- test_preview_pages.py: read 4 tests, 0 flagged
- test_manual_group.py: read 8 tests, 0 flagged
- test_sm_rename.py: read 7 tests, 0 flagged
- test_view_themes.py: read 8 tests, 0 flagged
- test_partial_compile.py: read 11 tests, 0 flagged
- test_transcript_conversion.py: read 10 tests, 0 flagged
- test_readability_tool.py: read 8 tests, 0 flagged
- test_language_line.py: read 7 tests, 0 flagged
- test_preview_raster.py: read 9 tests, 0 flagged
- test_image_source_gui.py: read 6 tests, 0 flagged
- test_slide_preview_cleanup.py: read 5 tests, 0 flagged
- test_appendix_toc.py: read 3 tests (1 parametrized into 7 cases), 0 flagged
- test_settings_ai_gui.py: read 12 tests, 1 flagged
- test_restore_version.py: read 13 tests, 0 flagged
- test_ai_profile.py: read 15 tests, 0 flagged
- test_plugin_upgrade.py: read 16 tests, 0 flagged
- test_diagnostics.py: read 20 tests, 1 flagged
- test_template_catalog.py: read 15 tests, 0 flagged
- test_image_source.py: read 14 tests, 0 flagged
- test_check_layout_margins.py: read 13 tests, 0 flagged
- test_slide_versions_gui.py: read 11 tests (1 parametrized into 4 cases), 0 flagged
- test_plugin_ui.py: read 30 tests (2 parametrized), 0 flagged
- test_render_key.py: read 22 tests, 0 flagged
- test_image_review.py: read 21 tests, 0 flagged
- test_make_readable_gui.py: read 18 tests (2 parametrized into 2 cases), 0 flagged
- test_plugin_settings_tab.py: read 33 tests, 0 flagged
- test_plugin_host.py: read 39 tests, 1 flagged
- test_images_page_gui.py: read 47 tests (5 of them parametrized), 2 flagged

Totals: 41 files, 463 test functions read (parametrized cases not counted separately), 7 flagged: 3 merge (test_slide_branch, test_color_modes_app, test_images_page_gui) and 4 rewrite (test_settings_ai_gui, test_diagnostics, test_plugin_host, test_images_page_gui). Every file in the slice was read in full.
