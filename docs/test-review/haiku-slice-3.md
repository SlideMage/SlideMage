# Test review, slice 3 (haiku)

Read-only review of the 39 test files in slice 3 (tests/). Every test body was read in full. Flags only where a concrete argument exists. "read N tests" counts `def test_` functions (parametrized cases count as one).

| file | test | line | drop/merge/rewrite | reason | covering test |
|---|---|---|---|---|---|
| test_agent_tools.py | test_fields_and_qr_height_are_checked_by_schema | 859 | rewrite | Asserts only that the error does not contain "fields.year". Any unrelated error (unknown kind, another missing field) passes. Assert the exact missing-field message. | test_add_bib_entry_validates (521) |
| test_agent_tools.py | test_add_bib_entry_writes_a_sorted_entry_with_a_suggested_key | 507-508 | drop (these 2 lines) | Re-asserts the taken-key refusal (kind=book, key=old2000, "already exists") that the next test checks identically. | test_add_bib_entry_refuses_a_taken_key_before_asking_and_a_buffer_that_got_edits_while_asking (513) |
| test_agent_tools.py | test_hidden_folders_do_not_exist_for_the_model | 139 | drop (this line) | Same search "sk-secret" -> "Nothing found" as line 154. | test_find_and_search_skip_dot_files_and_links_into_hidden_folders (154) |
| test_deck_snapshot.py | test_real_snapshot_of_manual | 632-643 | merge | Same deck, same copytree, same create_snapshot and result.ok assert as test_real_snapshot_with_the_framework_on_another_drive. The other test adds only SLIDEMAGE_LATEX on another drive. Merge into one opt-in test parametrized over framework location (same drive / other drive). | test_real_snapshot_with_the_framework_on_another_drive (181) |
| test_deck_snapshot.py | test_project_scans_never_look_inside_snapshots | 541-550 | rewrite | Globs sm_rename.PROJECT_GLOBS against tmp_path. Patterns are anchored at the root, so snapshot files under tmp_path/snapshots/ cannot match anyway. No call into sm_rename or deck_scan, no positive control, so it passes whatever the code does. The docstring promises deck_scan coverage that is not there. Rewrite to run sm_rename's walk and deck_scan.scan_dir on a project containing a snapshot, with a positive control. | none in slice |
| test_slide_add.py | test_extract_odp_skips_starview_metafile_masquerading_as_png | 357-358 | rewrite | `all(not slide.images for slide in slides)` is vacuously true if extract_odp returns no slides, so the test passes when the page disappears. Assert len(slides) == 1 before checking images. | test_extract_matches_across_pptx_and_odp (449) covers extraction only in part |
| test_latex_edit.py | test_every_insert_entry_has_an_edit_except_those_that_ask_first | 127-128 | drop (these 2 lines) | Literal Insert("\\tallitem", "literal") -> Edit(text, len(text)) is also asserted for the same kind by test_insert_menu_offers_final_state_for_students (latex_edit.py:251 is a literal entry). | test_insert_menu_offers_final_state_for_students (219-220) |
| test_language_tex.py | test_a_language_without_patterns_hyphenates_as_english_with_a_warning | 250-251 | rewrite | The first assertion sits under `if "Language: [0]" in text:`. When that string is absent the test asserts nothing about Romanian, so a broken language switch passes. Assert the outcome unconditionally, or pin the TeX setup the test expects. | none in slice |
| test_slide_notes.py | test_add_note_goes_before_the_frames_end_one_indent_deeper | 46-47 | drop (these 2 lines) | Re-checks the add_note result that lines 41-42 already fix by full string equality. | same test, lines 41-42 |
| test_translation_languages.py | test_the_prompt_for_german_to_french_names_both_languages_and_the_address | 29-32 | drop (whole test) | Same DE->FR informal request format and the same assertion as the other test; only the input text differs. | test_tasks.py::test_a_translation_into_any_language_says_how_to_address_the_audience (43-46) |
| test_translation_languages.py | test_the_prompt_for_french_to_english_still_carries_the_address | 35-38 | drop (whole test) | The FR->EN "formal" startswith assertion is identical to test_tasks.py lines 47-48; "French slide" in proofread_request is test_tasks.py line 163. | test_tasks.py::test_a_translation_into_any_language_says_how_to_address_the_audience (47-48) and test_a_proofread_request_names_the_language_and_keeps_the_german_address (163) |
| test_idle_gate.py | test_render_now_skips_the_idle_rules_but_not_busy_or_the_switch | 70 | rewrite | `reason() in ("you are working", "on battery")` accepts either value. With force ignored, the reason is "on battery" and the test passes. Pin the expected reason and check the forced render is still allowed at that time. | none in slice |
| test_step_renders.py | test_dropping_the_background_forgets_queued_jobs_but_not_foreground_ones | 126-136 | rewrite | The name promises that foreground jobs survive drop_background; the body never submits or checks a foreground job. A drop_background that also drops foreground jobs passes. Add a foreground submit and assert it is still pending or runs. | none in slice (test_foreground_jobs_go_before_waiting_background_ones_and_in_order, 78, covers ordering only) |
| test_step_renders.py | test_a_closed_queue_takes_nothing | 143 | drop (this line) | `assert step_renders.POLL_SECONDS > 0` is unrelated to closing the queue. | n/a |

## Per-file counts

- test_agent_tools.py: read 68 tests, 3 flagged
- test_tasks.py: read 34 tests, 0 flagged
- test_deck_snapshot.py: read 32 tests, 2 flagged
- test_slide_add.py: read 24 tests, 1 flagged
- test_latex_edit.py: read 22 tests, 1 flagged
- test_task_card_gui.py: read 20 tests, 0 flagged
- test_modify_slide.py: read 19 tests, 0 flagged
- test_deck_outline.py: read 18 tests, 0 flagged
- test_ai_providers.py: read 16 tests, 0 flagged
- test_centre_tabs.py: read 15 tests, 0 flagged
- test_presenter_open_with.py: read 14 tests, 0 flagged
- test_ai_review.py: read 14 tests, 0 flagged
- test_language_tex.py: read 13 tests, 1 flagged
- test_slide_notes.py: read 12 tests, 1 flagged
- test_translation_languages.py: read 11 tests, 2 flagged
- test_qr_dialog_gui.py: read 11 tests, 0 flagged
- test_background.py: read 11 tests, 0 flagged
- test_compile_status.py: read 10 tests, 0 flagged
- test_idle_gate.py: read 9 tests, 1 flagged
- test_step_renders.py: read 8 tests, 2 flagged
- test_parallel_runs.py: read 8 tests, 0 flagged
- test_ai_models_gui.py: read 8 tests, 0 flagged
- test_plugin_ai_tools.py: read 7 tests, 0 flagged
- test_slug_collision.py: read 6 tests, 0 flagged
- test_latex_lint.py: read 6 tests, 0 flagged
- test_compat_color_roles.py: read 6 tests, 0 flagged
- test_terminal_draft.py: read 5 tests, 0 flagged
- test_rerender_deck_gui.py: read 5 tests, 0 flagged
- test_deck_context_gui.py: read 5 tests, 0 flagged
- test_project_format.py: read 4 tests, 0 flagged
- test_deck_headers.py: read 4 tests, 0 flagged
- test_transcript_policy.py: read 3 tests, 0 flagged
- test_review_compiler.py: read 3 tests, 0 flagged
- test_packages.py: read 3 tests, 0 flagged
- test_translation_chip_gui.py: read 2 tests, 0 flagged
- test_source_freeze.py: read 2 tests, 0 flagged
- test_helper_stdin.py: read 2 tests, 0 flagged
- test_compile_log.py: read 2 tests, 0 flagged
- test_job_order.py: read 1 test, 0 flagged

Totals: 39 files read in full, 0 unfinished, 467 test functions read. Flags: 14 rows in total, of which 7 drop, 6 rewrite and 1 merge.
