# Streamlining baseline (step 0)

Frozen at `378f50b` (SlideMage v8.3.0, `origin/develop` v5.36.0 merged). Step 0 changes no application code. Later steps measure against the figures here; "GAP" means no existing test covers the check (found by reading `tests/` names and bodies, not guessed).

## 1. Counts and test result

| Measure | At `378f50b` |
| --- | ---: |
| `tools/count_lines.py .` | files=190, physical=47,258, code=33,056 |
| Test suite (`pytest -q`, offscreen Qt) | 1,853 passed, 8 skipped, 148 s |
| `ruff check src tests` | clean |

## 2. Feature-preservation checklist

Test files are in `tests/`. Names are abbreviated to the distinctive part of `test_<name>`.

### Native AI chat/agent

| Check | Existing coverage |
| --- | --- |
| Conversation and streaming | `test_agent.py` (a_plain_answer_streams_and_ends, stop_in_the_middle_of_a_streamed_answer, done_is_the_last_event...); `test_chat_gui.py` (the_answer_streams_into_the_list_with_the_provider_label, new_chat_forgets_the_conversation) |
| Tool execution | `test_agent.py` (tool_rounds_run_in_order..., a_failing_tool_is_a_result...); `test_agent_tools.py` (all tools: read/find/search/list_slides/lint/render_preview/add_slide/add_bib_entry/compile_deck/read_guide/context); `test_chat_gui.py` (tool_calls_become_cards...) |
| Scope | `test_agent.py` (the_scope_changes_the_context); `test_agent_tools.py` (context_of_a_slide.../the_whole_deck...); `test_chat_gui.py` (while_a_run_is_going_the_model_and_the_scope_stay_as_they_are) |
| Edit approval (ask mode, apply) | `test_agent_tools.py` (ask_mode_waits_for_the_user...); `test_chat_gui.py` (ask_mode_apply_edits_the_open_buffer_unsaved_and_undoably) |
| Edit rejection | `test_agent_tools.py` (...reports_a_rejection); `test_chat_gui.py` (reject_leaves_the_buffer_and_tells_the_model, stop_rejects_an_edit_that_waits_for_an_answer) |
| Auto mode / permission change | `test_chat_gui.py` (auto_mode_applies_at_once..., changing_the_permission_mid_run..., the_permission_is_remembered); `test_agent.py` (the_mode_can_be_changed_while_the_run_is_under_way) |
| Undo | `test_agent_tools.py` (undo_puts_the_old_text_back_unless_the_file_moved_on); `test_chat_gui.py` (auto_mode_..._undo_takes_the_edit_back_from_the_buffer, undo_refuses_when_the_text_changed_since, a_closed_file_is_edited_on_disk_and_undone_there, a_new_file_has_no_undo) |
| Edit conflicts (buffer typed in, disk changed, read-only, frozen, protected) | `test_agent_tools.py` (a_buffer_that_changed_while_the_edit_waited..., a_read_only_buffer_refuses, a_file_changed_on_disk_after_reading..., old_text_must_occur_exactly_once, protected_parts..., frozen_versions...; write_file_does_not_overwrite...) |
| Edit to open buffer vs disk, backup, CRLF | `test_agent_tools.py` (edit_on_disk_saves_with_backup_keeps_crlf_and_reports, edit_in_an_open_buffer_leaves_the_disk_alone) |
| Stop, turn limit, errors | `test_agent.py` (stop_*, the_turn_limit..., provider_errors..., a_cut_off_or_declined_answer...); `test_chat_gui.py` (a_failed_request_ends_in_a_notice, closing_the_window_mid_run_does_not_hang..., switching_the_deck_stops_the_run) |
| Compile from the agent, show slide | `test_agent_tools.py` (compile_deck_reports_per_pdf...); `test_chat_gui.py` (a_compile_runs_through_the_windows_flow..., the_chats_stop_ends_a_compile_without_asking, a_deck_the_agent_changed_goes_through_the_headers...) |
| Headless `Workspace` (confirm_edit false, apply_to_buffer refuses) | `tests/agent_fakes.py` fakes; GAP: no test of the base `ai/workspace.py` defaults themselves |

### Embedded Claude Code

| Check | Existing coverage |
| --- | --- |
| Terminal interaction, PTY lifecycle | `test_pty_process.py` (all 6); `test_claude_code_gui.py` (typing_resize_theme_exit_restart_and_shutdown, copy_and_paste..., a_process_that_cannot_start...) |
| Install hint without Claude | `test_claude_code_gui.py` (without_claude_the_view_says_how_to_install_it...) |
| WebEngine integration | `test_claude_code_gui.py` (copy_and_paste...); `test_terminal_theme.py`. No test of the web terminal page itself |
| Focus/deck context | `test_claude_scope.py` (all); `test_claude_code_gui.py` (the_scope_switch_and_the_focus_reach_the_hooks) |
| MCP server | `test_mcp_server.py` (all 13); `test_claude_code_gui.py` (claude_code_reads_the_unsaved_buffer_and_the_focus_through_mcp) |
| Hooks (edit guard) | `test_claude_hook.py` (all 12); `test_claude_launch.py` (the_command_line_carries_the_mcp_server_the_hook...) |
| Launch command, token by environment, own login | `test_claude_launch.py` |
| Switch to deck mode / show slide | `test_claude_code_gui.py` (switch_to_deck_mode_sets_the_scope_switch, show_slide_brings_a_deck_slide_into_focus) |
| Buffer/disk sync with Claude's file edits | `test_claude_code_gui.py` (a_clean_buffer_is_reloaded..., a_dirty_buffer_is_not_overwritten..., keep_my_edits..., other_files_refresh..., decks_and_new_or_removed_slides...) |

### Focused AI tasks and providers

| Check | Existing coverage |
| --- | --- |
| Task buttons (bubbles) follow focus/lint | `test_claude_tasks_gui.py` (the_bubbles_follow_the_focus_and_the_lint, bubbles_that_do_not_fit_go_under_more, without_claude_there_are_no_bubbles, two_clicks_start_one_task) |
| Fix / proofread / shorten / title / note apply into the buffer, undo | `test_claude_tasks_gui.py` (a_fix_goes_into_the_open_buffer_and_ctrl_z..., proofreading_applies_its_edits_into_the_buffer, a_shortened_slide_is_applied..., a_better_title..., a_speaker_note_goes_before...) |
| Task result checks (edits, protected, lint, structure) | `test_claude_tasks.py` (edits_*, protected_parts_must_not_change, an_edit_may_not_add_a_lint_error, a_shortened_text_keeps_..., a_translation_may_not_cite...) |
| Translation: create partner, link, add to deck; failure creates nothing; source changed | `test_claude_tasks_gui.py` (a_translation_creates_the_partner_after_the_source_and_links_both, a_failed_translation_creates_nothing, a_source_that_changed_meanwhile_gets_no_partner, a_partner_made_meanwhile_is_not_made_again, a_slide_that_is_not_in_the_deck_still_gets_its_translation) |
| Update of a translation (open / closed / changed meanwhile) | `test_claude_tasks_gui.py` (an_update_goes_into_the_open_translation..., an_update_of_a_closed_translation_is_saved_to_its_file, a_translation_that_changed_meanwhile_is_not_overwritten, ..._on_disk_meanwhile_...) |
| Conflicts: typing during a task | `test_claude_tasks_gui.py` (typing_during_a_fix_is_a_conflict..., typing_during_a_title_task_is_a_conflict, a_focus_change_during_a_task_does_not_change_its_target, a_slide_edited_during_its_run_is_a_conflict_for_that_slide_only) |
| Cancellation | `test_claude_tasks_gui.py` (stop_cancels_and_the_late_result_is_dropped); `test_claude_runner.py` (stop_cancels_and_a_late_result_is_dropped, the_deadline_ends_the_process) |
| CLI runner (isolation, repair once, login, process death, rate/usage limits) | `test_claude_runner.py` (all 15), `test_claude_images.py`; `fake_claude.py` |
| Batch (images, deck summary, rate-limit backoff, parallel workers) | `test_claude_tasks_gui.py` (describing_images_stores_drafts..., two_processes_run_at_once..., a_rate_limit_drops_to_one_worker..., a_usage_limit_stops_the_bat..., the_deck_bubbles_follow_the_scope...) |
| Task-specific model/effort remembered | `test_claude_tasks_gui.py` (the_picked_model_and_effort_reach_claude_and_are_remembered); `test_ai_models_gui.py` (the_provider_of_a_task_without_a_picker_follows_the_settings) |
| Direct Anthropic API | `test_ai_providers.py` (anthropic_* 5 tests, api_key_source_precedence, set_api_key_*); `test_agent_claude.py` (7) |
| Ollama provider | `test_ai_providers.py` (ollama_* 4 tests, abort_*); `test_agent_ollama.py` (10) |
| Task-specific tasks (syntax check, image description, translation) via provider | `test_ai_tasks.py` (7); `test_ai_fix_gui.py` (14) |
| Credentials | `test_ai_providers.py` (keychain/settings-file tests); `test_settings_gui.py` |
| Local-only policy | `test_ai_providers.py` (local_only_blocks_cloud_globally_and_per_project, project_override_lives_in_project_json..., cloud_models_on_offer_need_a_key_and_no_local_only); `test_agent.py` (local_only_stops_a_cloud_provider); `test_chat_gui.py` (local_ai_only_disables_the_cloud_model_with_a_hint); `test_settings_gui.py` (local_only_hides_the_cloud_models_at_once) |
| Cloud consent once per project | `test_ai_models_gui.py` (first_cloud_request_asks_once_per_project); `test_agent.py` (the_first_cloud_request_needs_consent_once); `test_chat_gui.py` (the_cloud_consent_is_the_windows_question) |
| Live provider calls | `test_ai_live.py` (skipped without credentials) |

### Reproducible deck snapshots

| Check | Existing coverage |
| --- | --- |
| Capture: used files, dependencies, LaTeX package files on request, fonts, environment | `test_deck_snapshot.py` (snapshot_copies_what_the_deck_uses..., latex_package_files_are_copied_on_request, file_outside_project_is_a_warning, parse_fls...). Font and application capture options: GAP (no test names fonts/application capture) |
| Manifest, determinism (zip) | `test_deck_snapshot.py` (zip_snapshot_has_the_folder_tree_and_is_deterministic, old_snapshots_found_by_manifest...) |
| Render script / verify | `test_deck_snapshot.py` (verify_renders_from_the_snapshot_and_passes, verify_fails_when_..., verify_detects_changed_files) |
| Versions, reuse unchanged | `test_deck_snapshot.py` (snapshot_of_versioned_deck_compiles_every_version, unchanged_version_is_reused_changed_one_compiled) |
| Several decks, cancel, failure | `test_deck_snapshot.py` (decks_one_by_one_a_failure_does_not_stop_the_rest, cancel_skips_the_remaining_decks, failed_compile_leaves_nothing_behind) |
| Reading existing snapshots | `test_deck_snapshot.py` (snapshot_project_is_recognized_and_uses_its_own_framework_and_dates, snapshot_is_never_migrated_or_updated, project_scans_never_look_inside_snapshots) |
| GUI (sheet, banner, questions, summary) | `test_deck_snapshot_gui.py` (11) |
| Real snapshot of the manual | `test_deck_snapshot.py` (real_snapshot_of_manual, real_omitslide_is_instructor_only) |

### Presentation conversion

| Check | Existing coverage |
| --- | --- |
| PPTX import | `test_slide_add.py` (parametrised pptx/odp fixture, from line 303); `test_import_presentation_gui.py` (3) |
| ODP import | same parametrisation in `test_slide_add.py` |
| PPTX export | GAP: only `test_commands.py` checks the "Export PPTX..." menu entry maps to `export_pptx`; nothing runs `pptx_export.py` |
| Overlay behaviour on import | thin: `test_slide_add.py` (test_item_text_starting_with_overlay_bracket_is_protected); GAP for PPTX/ODP overlay conversion proper |

### Partial compilation

| Check | Existing coverage |
| --- | --- |
| Selected-page recompilation, numbering | `test_partial_compile.py` (page_compile_maps_slides_and_preserves_numbers, page_spec, frames_for_slides_finds_a_fragment_translation, deck_changes_after_the_asked_for_slides_are_fine, plan_*) |
| PDF patching and link retargeting | `test_partial_compile.py` (patch_swaps_the_pages_in_and_keeps_the_rest checks LINK_URI and LINK_GOTO page; slide_with_a_new_page_count_is_not_swapped) |
| Overlay grouping | thin: reveal pages counted within `test_partial_compile.py`; GAP for an explicit overlay-group test |
| Whole-deck fallback | `test_partial_compile.py` (plan_refuses_when_the_whole_deck_is_needed, no_deck_copy_on_record_means_any_change_counts) |
| Caret / selected pages from the window | `test_compile_flow_gui.py` (the_caret_compiles_the_selected_slides_and_every_active_deck); `test_workspace_window.py` (selected_pages_compile_the_current_view) |
| Progress | `test_partial_compile.py` (progress_bar_stops_after_a_page_compile) |

### Administration

| Check | Existing coverage |
| --- | --- |
| Ollama management (list, delete, update/pull, relink derived model, busy slot, host) | `test_review_ai_backend.py` (relink_derived_model_*, update pulls); `test_settings_gui.py` (the_installed_models_are_listed..., model_changes_run_on_a_thread..., a_busy_ollama_slot_stops_a_delete_and_an_update, a_changed_host_is_saved...). No test of ollama_admin pull-progress parsing beyond the fakes |
| Manual update check, automatic choices | `test_update_check_gui.py` (startup_update_choices, errors_and_up_to_date_only_log, no_startup_check_for_a_source_checkout); `test_updater.py` |
| Breaking-release handling | `test_update_check_gui.py` (breaking_update_is_always_asked, staying_on_the_major_version_installs_the_safe_release); `test_updater.py` (breaking_notes_and_markers, plan_update_counts_every_release_in_between) |
| Install (binary replace, platform asset) | `test_updater.py` (install_replaces_binary_and_extra_files, install_refuses_zip_without_binary, fetch_picks_platform_asset...) |
| Token for private repo | `test_updater.py` (token_saved_privately..., refused_token_names_the_missing_permission) |
| Bundled-copy updates (manual, framework) | `test_bundled_copies.py` (11) |
| Project compatibility migrations | `test_compat.py` (11), `test_compat_gui.py`, `test_compat_bibliography.py`, `test_project_format.py` |
| Course/schedule helpers | `test_course_schedule.py` (19), `test_course_url.py`, `test_admin_slides.py`, `test_admin_slides_gui.py` |

### Compile progress

| Check | Existing coverage |
| --- | --- |
| Percentage estimates, historical pass counts | `test_compile_passes.py` (5); `test_compile_status.py` (a_skipped_job_counts_as_done_work_for_the_progress_bar); `test_partial_compile.py` (progress_bar...); `test_deck_snapshot.py` (progress_follows_snapshot_compiles) |
| Current stage, job status from log | `test_compile_status.py` (10); `test_compile_log.py` |
| Logs (drawer, all writers) | `test_compile_flow_gui.py` (the_log_drawer_is_closed_until_asked_and_takes_every_writer) |
| Stop (one job, whole run), skip | `test_compile_status.py` (stopping_the_current_job_kills_its_process...); `test_compile_flow_gui.py` (stopping_a_job_skips_a_queued_one..., stop_all_asks_and_stops_the_whole_run, closing_the_window_mid_compile_stops_the_run...) |
| Retry failed | `test_compile_flow_gui.py` (retry_failed_runs_only_the_failed_jobs_again) |
| Summary card, auto-open | `test_compile_flow_gui.py` (a_run_shows_its_jobs_and_ends_with_a_summary_card, auto_open_opens_each_pdf..., single_job_toast...) |
| Job order, unchanged jobs | `test_job_order.py`; `test_compile_records.py` (8) |
| Compile output itself (PDF pages/text) | tests mostly fake the TeX engine; real output is covered only by the new fixtures (section 4) and `real_snapshot_of_manual` |

### Editor and image UI

| Check | Existing coverage |
| --- | --- |
| Preview / Source / Split modes | `test_centre_gui.py` (the_mode_decides_which_views_are_shown, split_divider_share_is_remembered...); `test_workspace_window.py` (the_mode_switch_of_the_top_bar...) |
| Details view | `test_centre_gui.py` (details_follow_the_focused_slide, language_switch_changes_editor_preview_details...); `test_slide_versions_gui.py` (details_survive_a_slide_without_a_file...). No dedicated details view test file |
| Inspector editing (side panels) | `test_side_panels_gui.py` (notes, used, matrix, versions, citations, language, summary, images panels); `test_slide_notes.py` |
| Images page: lists, filters, find | `test_images_page_gui.py` (the_page_lists_the_slides..., the_no_german_filter..., find_slide_jumps_to_it..., the_order_follows_the_open_deck) |
| Images page: save draft | `test_images_page_gui.py` (leaving_the_slide_saves_the_edit_as_a_draft, a_rescan_and_a_deck_switch_save_a_pending_edit_too, save_merges_human_edit_with_worker_updates...) |
| Images page: mark reviewed, refused without long description, moves on | `test_images_page_gui.py` (review_is_refused_while_an_informative_image_has_no_long_description, marking_reviewed_moves_on...) |
| Images page: decorative, state chip, set default, clear draft | `test_images_page_gui.py` (decorative_images_keep_only_the_source_editable, the_state_chip_follows_the_typing..., set_as_default_needs_a_takeaway..., clear_draft_discards_unreviewed_text_only) |
| Images page: translation (German), stop, unsaved handling | `test_images_page_gui.py` (about 14 translation tests) |
| Images page: draft / draft all / tune / replace image | `test_images_page_gui.py` (draft_slide_*, draft_all_*, stop_ends_a_batch..., a_tuned_draft_can_be_accepted_with_its_hint, replace_image_*) |
| Images page minimum width | `test_images_page_gui.py` (images_page_minimum_width_fits_with_full_action_labels) |
| Inspector images panel: save draft / reviewed | `test_side_panels_gui.py` (images_show_state_and_save_drafts_and_reviews_through_the_store) |
| Inspector images panel: refuses review without long description | GAP (the Images page has the test; the panel's `_save` guard does not) |
| Inspector images panel: save preserves worker update; pending edit saved on leaving | `test_side_panels_gui.py` (image_save_preserves_a_field_updated_by_a_worker, a_pending_image_edit_is_saved_as_a_draft_when_the_slide_is_left) |
| Inspector images panel: redraft | `test_side_panels_gui.py` (redraft_fills_the_fields_from_the_model_and_stores_nothing, redraft_is_ignored_after_switching..., redraft_stops_when_there_is_no_model_or_it_fails, redraft_that_raises_still_ends...) |
| Both entry points use one store; closing asks about unsaved edits | `test_workspace_window.py` (closing_asks_about_unsaved_image_edits..., leaving_the_images_page_saves_a_pending_edit..., closing_asks_about_a_pending_side_panel_edit_too); `test_image_review.py` (21) |
| Source editor behaviour (format, comment toggle, folding, brace match, hyperlink) | `test_source_view_gui.py` (about 20 tests) |
| Shortcuts | `test_workspace_window.py` (registered_shortcuts_are_unique...); `test_commands.py`; `test_palette_gui.py` |
| Resizing and remembered layout, geometry | `test_workspace_window.py` (about 25 column/geometry tests); `test_chat_gui.py` (the_right_column_split_is_saved...); `test_side_panels_gui.py` |
| Widget kit | `test_ui_kit_gui.py`. No visual (pixel) regression test of QSS: GAP |

### Content and safety

| Check | Existing coverage |
| --- | --- |
| Accessibility / transcripts | `test_transcript_conversion.py`, `test_transcript_options.py`, `test_transcript_policy.py`, `test_transcript_preview_gui.py`, `test_review_transcript_import.py` |
| Bibliography | `test_compat_bibliography.py`, `test_bibliography_template.py`; `test_agent_tools.py` (add_bib_entry_*); `test_workspace_window.py` (the_bib_is_sorted_...); `test_side_panels_gui.py` (citations_*) |
| Language links / translation partners | `test_deck_language.py` (about 30 tests); `test_slide_add.py`; `test_side_panels_gui.py` (language_*) |
| Frozen versions | `test_restore_version.py`, `test_slide_versions_gui.py`, `test_source_view_gui.py` (a_frozen_version_is_read_only_until_unlocked...), `test_agent_tools.py` (frozen_versions_and_non_text_files_cannot_be_changed) |
| Undo and backups | `test_slide_notes.py` (a_real_save_makes_a_backup...), `test_agent_tools.py`, `test_image_review.py` (repoint_keeps_the_line_ends_and_makes_a_backup), `test_compat.py` (update_backs_up_writes_atomically...) |
| Protected regions | `test_protected_regions.py` (4); `test_claude_tasks.py`; `test_claude_hook.py`; `test_agent_tools.py` |
| Compatibility checks | `test_compat.py`, `test_project_format.py` |
| Conflict handling (stale file on save) | `test_source_view_gui.py` (other_files_save_plainly_and_a_file_that_changed_on_disk_is_refused, a_stale_slide_is_refused_before_anything_is_frozen_or_asked) |
| Rename, delete, move slide | `test_sm_rename.py`, `test_centre_gui.py` (rename_and_delete_go_through_slide_rename), `test_latex_edit.py`, `test_slide_ids.py` |
| Lint | `test_latex_lint.py`, `test_ai_fix_gui.py` |

### Preview behavior

| Check | Existing coverage |
| --- | --- |
| Saved vs unsaved rendering | `test_preview_target.py` (a_call_renders_with_..., a_buffer_renders_in_the_same_context...); `test_centre_gui.py` (rendering_the_buffer_uses_the_unsaved_text_the_scope_and_the_reveal_step, an_unsaved_draft_offers_to_render_the_buffer_not_the_saved_file) |
| Overlays / scopes | `test_preview_build.py` (regions_and_elements_keep_preamble_and_validate, overlay_does_not_change_action_defaults, element_rejects_frame_only_options); `test_claude_scope.py` |
| Build cache and dependency invalidation, locks, pruning | `test_preview_build.py` (cached_build_retains_aux_and_rejects_stale_pdf, unused_preview_wrappers_are_pruned, rerun_limit...); `test_preview_dependencies.py` (9) |
| Format-cache capability | `test_preview_build.py` (format_is_built_once_and_rebuilt_when_an_input_changes, format_noise_after_the_preamble..., slide_failing_only_with_the_format_is_rebuilt_without_it...) |
| Fresh-reference mode (`reuse_build=False`) | thin: only `test_slide_preview_cleanup.py` mentions it; the fixtures in section 4 compare cached and fresh output on real TeX |
| Stale-result rejection, one active plus latest pending | `test_preview_queue.py` (three_requests_compile_only_first_and_latest..., obsolete_results_never_replace..., old_error_is_ignored..., destroyed_pane_discards...) |
| Image cache bound | `test_preview_queue.py` (session_pixmaps_are_bounded..., prepared_images_preserve_pixels...) |
| Raster isolation | `test_preview_raster.py` (6) ; `test_preview_queue.py` (raster_failure_discards_the_new_temp_pdf...) |
| Persisted snapshot | `test_preview_build.py` (partial_previews_never_replace_full_slide_snapshot); `test_preview_queue.py` (disk_snapshot_is_best_effort...); `test_centre_gui.py` (the_cached_snapshot_is_shown...) |
| Cleanup of leftovers | `test_slide_preview_cleanup.py` (3) |
| Timestamp setting | `test_preview_queue.py` (timestamp_changes_make_accepted_images_stale...); `test_workspace_window.py` (the_build_options_footer_timestamp_is_the_states) |
| Preview benchmark harness | `test_preview_benchmark.py` |

**Totals.** 113 concrete checks (table rows) in the tables above. Explicit GAPs (no test): base `Workspace` defaults; font/application capture options of snapshots; PPTX export; PPTX/ODP overlay conversion; overlay grouping of partial compile as a named case; inspector Images panel refusing review without a long description; widget-kit appearance (QSS) regression. Thin (one incidental test): fresh-reference preview mode, web terminal page.

## 3. Code locations that steps 1-5 measure against

Current line counts at `378f50b`.

### Step 1: image form, validation, widget kit and QSS (budget 350-900)

| Location | Lines |
| --- | ---: |
| `ui/pages/image_form.py` (Images page `ImageForm(Surface)`) | 314 |
| `ui/workspace/panels/images.py` (inspector panel; `ImageForm(Row)` is lines 31-98, about 68 lines; the panel is the rest) | 215 |
| `ui/pages/images.py` (page that uses the form; `_save` at 354) | see file |
| `ui/kit/` total | 2,763 (`kit_qss.py` 1,304; `widgets.py` 853; `gallery.py` 238; `tokens.py` 150; `theme.py` 107; `palette.py` 61; `fonts.py` 45) |

What is already identical: the roles `ROLES` and chip tones `STATE_TONES` (the panel imports them from `image_form.py`); the predicate `image_review.needs_long_description(role, long)`; the store (`alt_images`, `media/alt-text.json`); the edit-versus-baseline idea (`values()` and `changed`; `baseline` in the panel, `saved_english` and `rebase` in the page form); role control (`SegmentedControl`), state `Chip`, `Button`.

What differs: the Images page form holds English and German fields (short, long, takeaway, source and `_de`), takes slide id and hash, supports replace, tune and translate buttons and signals, uses `ImagePreview`, `Field`, `Surface`; its save goes through `image_review.save_slide_forms(FormEdit...)` and shows one dialog listing all images missing a long description. The panel form is single-language (role, short, long), has a 56 px thumbnail, Redraft, "Save draft" and "Mark reviewed" buttons; saves one image through `alt_images.save_slide_image(..., baseline=...)`; its dialog names only one image; it also flushes pending edits on slide change and runs the redraft thread. So the validation rule (`needs_long_description`) is already shared; what is duplicated is the warning dialog and the dirty-and-save plumbing, and the two save entry points (`save_slide_forms` vs `save_slide_image`).

### Step 2: edit write paths (budget 200-600)

| Location | Lines (file) | What it is now |
| --- | ---: | --- |
| `ai/tools/edits.py` `write_text` (81) | 182 | The one real write: open buffer via `workspace.apply_to_buffer`, else `slide_source.save_slide_source(..., expected_text=before)` with `StaleFileError` mapped to `ToolError`, then `workspace.file_changed`. `undo_edit` reuses it |
| `ai/claude_runner.py` `apply_result` (214) | 221 | A 7-line wrapper over `write_text` returning the error string; used only by `terminal/tasks.py` (lines 548, 569) |
| `ai/claude_tasks.py` `_apply_edits` (203) | 277 | Not a write path: pure text transformation of `before/after` edit lists, with `check()` doing protected-region, structure and lint validation |
| `ai/workspace.py` `apply_to_buffer` (61) | 105 | Headless base class stub returning "it is not open for editing" |
| `ui/workspace/chat/gui_workspace.py` `apply_to_buffer` (173) | 296 | The only real buffer implementation (read-only, expected-text and `patch_text` checks on the GUI thread) |
| `ui/workspace/terminal/tasks.py` `_apply` (530) | 590 | Decides summary vs translate vs write; `_write` and `_translate` call `claude_runner.apply_result`; also creates partner slides and deck calls |
| Other users of `save_slide_source` / `patch_text` | | `ui/workspace/source_file.py` (344/353, the editor's own save), `slide_versioning.py` (175, 231), `image_review.py` (322), `ui/workspace/ai_fix.py` (327 lines, applies fixes into the editor) |

Correction to the plan's evidence: the plan lists these as "separate write paths". At this revision there is already one write primitive (`write_text`) with two call sites that wrap it (`apply_result`, `undo_edit`); `_apply_edits` is validation not writing; `ai/workspace.apply_to_buffer` is only the headless default. The genuinely separate implementations are the GUI `apply_to_buffer`, the editor's own save in `source_file.py`, and `ai_fix.py`. The step-2 budget (200-600) rests on that overlap and should be re-estimated at the start of step 2.

### Step 4: compile process startup and execution (budget 300-800)

| Site | File:line | Notes |
| --- | --- | --- |
| Common primitive | `compiler.run_streamed` (375), `Popen` at 385 | Streams output, registers the process with `CancelToken` |
| Deck/chapter jobs | `compiler.run_job` (739), `run_streamed` at 797 | latexmk with private build dir and wrapper; `build_env` (496) |
| Preview, fresh build | `slide_preview.compile_and_extract` (340), `run_streamed` at 437 | |
| Preview, cached build | `preview_build._compile_reserved` (259), `run_streamed` at 294 | Locks, dependency records, `configuration_key` |
| Page (partial) compile | `partial_compile.py` (655 lines), `run_streamed` at 456 | |
| Snapshot compile | `deck_snapshot.py` (1,438 lines), `run_streamed` at 467 | |
| Format creation | `preview_format.py` (217), `subprocess.run` at 195 | Not `run_streamed` |
| Export | `pptx_export.py` starts no process (no `subprocess` or compiler reference) | |
| Controller | `ui/workspace/compile_jobs.py` 802 lines (`CompileJobsMixin`); `job_panel.py` 220; `multi_compile.py` 72; `compile_status.py` 188; `compile_progress.py` 263 | |

So five of six latexmk launches already share `run_streamed`; the repeated code is the environment, wrapper writing, build-directory policy, log validation and publication around it. Other `subprocess` users outside compilation: `project.py` 490, `slide_rename.py` 65/470, `version.py` 85, `compile_records.py` 188, `open_path.py` 29, `archive.py` 112, `processes.py` 18, `preview_raster_client.py` 51, `ai/claude_runner.py` 130.

### Step 3 and step 5: project root, atomic writers

- `PROJECT_ROOT` is named in **44** application files (plan figure of 44 holds); `deck_scan.py` line 20 sets `PROJECT_ROOT = project.discover() or Path.cwd()` at import. `compiler.py` 48-49 derives `BUILD_DIR`, `PDF_DIR`. This is also why `tools/streamlining_fixtures.py` must set `SLIDEMASTER_PROJECT` before importing the app.
- Atomic-write helpers: the plan names two, `alt_images.atomic_write_text` (394, temp file + fsync + `os.replace`, text) and `compat._atomic_write` (236, bytes, fixed `.slidemage-tmp` name, no fsync). There are at least four more hand-rolled temp-then-`os.replace` writes: `compile_records.py` 319-321, `ai/claude_scope.py` 37-39, `deck_snapshot.py` 262-268 (replace with retry), `updater.py` 332-333. They are not identical (text vs bytes, fsync, temp name, retry), so the step-5 budget should not assume they merge freely.

Step 5 parsing locations (sizes): `tex_source.py`, `latex_lint.py`, `transcript.py`, `latex_edit.py`; see `wc -l` at the start of step 5.

## 4. Output fixtures

`tools/streamlining_fixtures.py` copies `example/` and the sibling `latex/` framework (the project expects its framework as a sibling folder) into a temp directory, then, with `SLIDEMASTER_PROJECT` set:

- compiles `slidemage-manual-copy` in the instructor view with `compiler.build_jobs` and `compiler.run_jobs` (the app's own path), footer timestamp off;
- renders four single slides (`1jh-EN-Title-Slide`, `tnb-DE-Title-Slide`, `1ym-EN-Framework-Project-App`, `1bb-EN-What-You-Need`) with `slide_preview.render_slide_to_pdf`, each twice: `reuse_build=True` (cached build) and `reuse_build=False` (fresh), `capture_snapshot=False`;
- records per PDF the page count, a SHA-256 prefix of each page's extracted text and of each page's 30 dpi grayscale pixmap, into `tests/fixtures/streamlining/manifest.json` (about 5 KB; no PDFs kept).

```
PYTHONPATH=src python tools/streamlining_fixtures.py           # write the manifest
PYTHONPATH=src python tools/streamlining_fixtures.py --check   # recompile and compare
```

`--check` exits 1 if page count or any text hash differs; an image hash difference prints `WARN` only. Runtime: about 110 s (the 92-page deck takes about 100 s; the eight single-slide renders about 10 s). `slidemage-manual-copy` (the deck with the German slides and the LaTeX install chapter) was chosen; at 100 s the full instructor view was fast enough, so no smaller view or chapter was needed. Not covered: chapter, presenter and appendix views, a large deck.

Timestamps: the footer timestamp is the only wall-clock content; it is switched off through the app's own setting (`CompileJob.footer_timestamp = False`, `footer_timestamp=False` for previews), so no `SOURCE_DATE_EPOCH` is needed. With it off, all 8 preview renders and 91 of 92 deck pages have identical text and image hashes on every run. **Deck page 17** ("Inside a slide file, and its footer", from `1nt-EN-Inside-a-Slide-File`, which draws a zero-space overlay of arrows over its own footer) has stable text but its image hash varies from run to run (it differed from the stored manifest in four of four re-runs, and not always to the same value). It is reported as a warning only. Cause not investigated (probably layout of the overlay between latexmk passes); treat an image warning on page 17 as noise and any text mismatch, page-count change, or other image warning as real.

Stability result: `--check` against the committed manifest passes on text in every run (exit 0, "OK"), with one image warning (page 17).

## 5. Stale figures in the plan

- Baseline totals: the plan's evidence quotes 47,019 physical lines (at `3925f65`); at `378f50b` it is 47,258 physical, 33,056 code, 190 files. Updated in `STREAMLINING_PLAN.md`.
- `compile_jobs.py` is 802 lines (the plan already says so); `ui/kit/` is 2,763 lines (unchanged); `image_form.py` 314 and `panels/images.py` 215 (unchanged by the merge).
- "Separate write paths" for edits: see the correction in section 3, step 2.
- "The 'informative image needs a long description' check repeated in both `_save` methods": the rule is a single function, `image_review.needs_long_description`; what repeats is the warning dialog around it.
- "The two existing atomic-write helpers": there are at least six temp-then-replace writers (section 3).
- "Repeated process startup": five of six latexmk launches go through `compiler.run_streamed`; the exception is format creation.
- Test baseline is 1,853 passed, 8 skipped (the run brief's 1,840 predates the develop merge).