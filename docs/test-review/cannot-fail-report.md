# Tests that cannot fail: decisions

Source: the `rewrite` rows of haiku-overlap.md, haiku-keep-read.md, haiku-slice-0..5.md, haiku-list-3.md and haiku-list-5.md, each checked against the test at HEAD. Rule: delete a test that cannot fail whatever the code does; delete a single vacuous assertion when the rest of the test is real; keep tests that could only be stronger, are misnamed, or can fail by raising.

Counts: deleted whole 0, line removed 4, kept 49 (one more row named a test no longer at HEAD).

file | test | decision
--- | --- | ---
test_settings_ai_gui.py | test_the_old_tabs_open_the_ai_tab_at_their_section | line removed: the scrollbar assert `... > 0 or section == "prompts"` is always true (only case is "prompts"); removed it and its resize/show/processEvents setup; the scrolled_to assert stays
test_steps_edit.py | test_a_comment_between_alternatives_keeps_them_one_place_other_text_does_not | line removed: the `... or True` assert and its `split` setup; the `apart` case stays
test_compat.py | test_not_now_changes_nothing_so_it_comes_back | line removed: `json.loads(before)[...] == "v5.28.1"` checks the test's own make_project fixture read before any action; removed it and `before`; the checked_version assert stays
test_reveal_flag.py | test_taking_the_flag_out_does_not_make_the_slide_look_changed_but_putting_it_in_does | line removed: `assert hashlib.sha256(...).hexdigest()` is a non-empty string, always true; removed it and the hashlib import
test_ai_routes.py | test_fake_route_can_script_provider_runner_and_surface | not at HEAD (dropped in 3c6f3579); nothing to do
test_splash.py | test_releasing_the_splash_never_touches_windows_off_windows | kept: no assert, but fails if the call raises
test_steps_edit.py | test_an_open_ended_spec_stays_open_ended | kept: the `== X or is None` assert fails on any other result
test_presentation_gui.py | test_the_audience_window_shows_nothing_but_the_slide | kept: could be stronger (non-recursive findChildren), assertions can fail
test_preview_queue.py | test_refresh_tool_publishes_saved_artifact_through_gui_workspace | kept: `pixmap is None or == old_image` fails when a different image is shown
test_background_previews_gui.py | test_the_status_window_lists_every_deck_with_its_versions_and_state | kept: the disjunction fails when the dialog is shown and failures hidden
test_background_renders.py | test_the_planner_hands_over_consecutive_units_of_one_deck_view_and_language_up_to_the_batch_size | kept: `or not r._plan` only excuses an empty plan; other asserts real
test_deck_context.py | test_without_a_usable_compile_there_is_no_deck_render | kept: weak but can fail
test_accessibility_gui.py | test_the_real_announce_runs_on_this_qt | kept: no assert, fails if announce raises
test_centre_gui.py | test_the_preview_never_renders_the_buffer_of_another_slide | kept: uses an undefined slide id, but the asserts can fail
test_centre_gui.py | test_keys_in_the_source_view_do_not_leak_into_other_views | kept: name over-promises; dirty assert can fail
test_languages.py | test_a_project_without_the_key_has_english_and_german_if_it_uses_german_and_nothing_is_written | kept: name only
test_presentation_resume.py | test_remember_saves_after_a_rest_and_never_raises | kept: the timer/slide asserts are real; the never-raises part is a no-assert call
test_reveal_steps.py | test_all_steps_selects_every_overlay_and_refuses_nothing_else | kept: name only
test_insert_popovers_gui.py | test_nothing_is_inserted_into_a_frozen_version | kept: could be stronger, assert can fail
test_wizard_portal.py | test_transparent_artwork_and_all_animation_phases_render | kept: could be stronger, assert can fail
test_plugin_boundary.py | test_core_does_not_import_plugin_packages | kept: could be stronger, can fail on a top-level plugin import
test_deck_language.py | test_links_with_wrong_language_or_self_reference_are_not_used | kept: could be stronger
test_deck_language.py | test_slidestep_slide_counts_as_used | kept: `not in unused` fails when the slide is reported unused
test_side_panels_gui.py | test_redraft_stops_when_there_is_no_model_or_it_fails | kept: last call has no assert but can raise; other asserts real
test_side_panels_gui.py | test_images_show_state_and_save_drafts_and_reviews_through_the_store | kept: overlap with a sibling, not vacuous
test_readability.py | test_the_thresholds_are_one_frozen_set_and_a_check_can_use_another | kept: pytest.raises(Exception) is broad but fails without an exception
test_calibrate_font_profile.py | test_new_needs_all_four_faces | kept: pytest.raises(SystemExit) is broad but can fail
test_themes_gui.py | test_no_theme_says_how_to_get_one | kept: name over-promises; assert can fail
test_compare_rendered_gui.py | test_the_dialog_in_both_themes | kept: could be stronger
test_agent_tools.py | test_fields_and_qr_height_are_checked_by_schema | kept: could be stronger
test_deck_snapshot.py | test_project_scans_never_look_inside_snapshots | kept: fails if sm_rename.PROJECT_GLOBS (src) gains a pattern that reaches snapshots/
test_slide_add.py | test_extract_odp_skips_starview_metafile_masquerading_as_png | kept: all() fails if a slide keeps the image (vacuous only when no slides)
test_language_tex.py | test_a_language_without_patterns_hyphenates_as_english_with_a_warning | kept: guarded branch runs when the fallback happens; the ja asserts are unconditional
test_idle_gate.py | test_render_now_skips_the_idle_rules_but_not_busy_or_the_switch | kept: accepts two reasons but can fail
test_step_renders.py | test_dropping_the_background_forgets_queued_jobs_but_not_foreground_ones | kept: name over-promises
test_diagnostics.py | test_the_cli_takes_the_debug_flag | kept: name over-promises
test_plugin_host.py | test_cancel_token_stops_host_tools | kept: name over-promises; asserts can fail
test_images_page_gui.py | test_draft_all_confirms_then_runs_the_queue_and_reports_errors | kept: name over-promises
test_template_catalog.py | test_the_stress_template_picks_lmsans_and_stays_out_of_the_apps_reach | kept: name over-promises
test_images_page_gui.py | test_another_order_keeps_the_slide_on_show_and_its_translation | kept: the pytest.fail stub inside a Qt slot is swallowed, but it also keeps a modal dialog away and other asserts are real
test_images_page_gui.py | test_a_show_filter_that_keeps_the_slide_does_not_ask_and_keeps_the_translation | kept: same as above
test_source_view_gui.py | test_other_files_save_plainly_and_a_file_that_changed_on_disk_gets_the_conflict_bar | kept: same swallowed-stub issue; other asserts real
test_add_slide_gui.py | test_a_project_language_can_be_machine_translated_but_mult_cannot | kept: same swallowed-stub issue; other asserts real
test_plugin_loader.py | test_reserved_manifest_id_is_refused[installed] | kept: refused earlier by folder name, but the assert can fail
test_plugin_loader.py | test_unloaded_name_may_load_twice | kept: name only
test_open_project_gui.py | test_importing_the_app_selects_no_project | kept: fails if any import raises, or if project gains a global `use`/`transitional_context`
test_color_modes.py | test_the_colorblind_preset_changes_the_alert_block | kept: could be stronger
test_stray_windows_gui.py | test_clicking_slides_opens_no_window_of_its_own | kept: could be stronger
test_chat_gui.py | test_refreshing_previews_says_when_the_window_is_busy_or_the_run_failed | kept: monkeypatch scope issue, not vacuous
test_preview_queue.py | test_new_revision_detaches_obsolete_pane_without_cancelling_other_consumers | kept: repeated clause still fails on a None pixmap
test_preview_queue.py | test_actual_parent_destruction_closes_lifetime_and_discards_worker_result | kept: worker-thread pytest.fail stubs are swallowed, but the main-thread asserts are real
test_presentation_core.py | test_next_large_clock_has_the_next_slide_large_the_notes_above_a_big_clock_and_the_strip | kept: duplicate assert, not vacuous
test_ai_fix_gui.py | test_a_frozen_version_cannot_be_fixed_and_a_bib_has_no_check | kept: name only
test_framework_regression.py | test_font_names_lose_their_subset_tag | kept: the helv assert is weak but fails if font_list breaks
