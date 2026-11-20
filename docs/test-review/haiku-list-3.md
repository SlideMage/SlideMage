# Test review, list 3 (slices.json index 3)

Read-only review. Every test body in each file was read in full. Flags only where a concrete argument exists.

| file | test | line | drop/merge/rewrite | reason | covering test |
|---|---|---|---|---|---|
| tests/test_source_view_gui.py | test_the_toolbar_has_no_revert_button | 398 | drop | Asserts that the attribute `_revert_button` does not exist. No such name exists in src/slidemage/ui/workspace/source_view.py (grep: only `_revert_label`, `_set_revert_menu`), so it passes whatever the revert behaviour is. Tests no behaviour. | test_revert_puts_the_last_version_back_as_one_undoable_edit (line 534) |
| tests/test_source_view_gui.py | test_other_files_save_plainly_and_a_file_that_changed_on_disk_gets_the_conflict_bar | 349 | rewrite | `monkeypatch.setattr(QMessageBox, "critical", lambda *_a: pytest.fail(...))` is the "autosave asks nothing" guard. It runs inside the autosave Qt slot, so the pytest.fail is swallowed and cannot fail the test. Record the calls in a list and assert it is empty. | itself |
| tests/test_add_slide_gui.py | test_a_project_language_can_be_machine_translated_but_mult_cannot | 341 | rewrite | `use_provider(monkeypatch, pytest.fail)` uses the pytest.fail function as the translator "must not be used" sentinel. It has no `is_local`/`chat` attributes, so any use raises AttributeError inside Qt code, which is swallowed, and the test does not fail. Use a translator that records calls and assert no call was made. | itself |
| tests/test_plugin_loader.py | test_reserved_manifest_id_is_refused[installed] | 193 | rewrite | The installed case uses the folder name `settings`. src/slidemage/plugins/loader.py:94 refuses reserved folder names before the manifest is read, so this case passes even if the manifest-id check (src/slidemage/plugins/manifest.py:128) were removed. Only the dev case (folder `checkout`) isolates the manifest check. Use a non-reserved folder name for the installed case. | test_reserved_installed_folder_is_refused_even_with_another_manifest_id (line 185) covers the folder path |
| tests/test_plugin_loader.py | test_unloaded_name_may_load_twice | 139 | rewrite | The name says a name may load twice; the body asserts the second load fails (`state == "failed"`). Rename to describe the refusal, e.g. test_a_name_already_in_sys_modules_is_refused_on_reload. | itself |
| tests/test_palette_gui.py | test_a_slide_outside_the_deck_opens_in_the_source_view | 168 | drop | Runs the same palette action (outside-the-deck slide) as test_a_slide_from_outside_the_deck_opens_a_tab_and_keeps_the_focus_when_it_is_saved, but with open_slide_editor monkeypatched, so it checks only the path and ignores the `tab=True` kwarg that palette.py:115 passes. The covering test drives the real window and checks the path and the tab. Fold the `"not in this deck"` meta assertion into the covering test, then drop. | test_a_slide_from_outside_the_deck_opens_a_tab_and_keeps_the_focus_when_it_is_saved (line 182) |
| tests/test_reveal_flag.py | test_taking_the_flag_out_does_not_make_the_slide_look_changed_but_putting_it_in_does | 147 | rewrite | `assert hashlib.sha256(current.read_bytes()).hexdigest()` asserts that a non-empty hex string is truthy, so it can never fail. Delete the line and the now unused hashlib import. | itself |
| tests/test_open_project_gui.py | test_importing_the_app_selects_no_project | 163 | rewrite | The subprocess exits with `int(hasattr(project, 'transitional_context') or hasattr(project, 'use'))`. Neither name exists in src/slidemage (grep), so the exit code is 0 whatever the import does, and project selection is never checked. Assert the real selection state after import, or drop the probe. | itself |
| tests/test_color_modes.py | test_the_colorblind_preset_changes_the_alert_block | 97 | rewrite | `base.samples != cb.samples` passes on any pixel difference anywhere on the page (footer, logo, anything), so it does not check the alert block its name claims. Compare the pixels inside the alert block region. | itself |
| tests/test_navigation.py | test_single_slide_transcript_drops_the_agenda_placeholder | 51 | merge | Same shape as test_single_slide_transcript_drops_the_subsection_agenda_placeholder (line 98): only the macro name and one extra assertion differ. Merge both into one test parametrized over (macro, agenda text). | test_single_slide_transcript_drops_the_subsection_agenda_placeholder (line 98) |

| tests/test_stray_windows_gui.py | test_clicking_slides_opens_no_window_of_its_own | 58 | rewrite | `_TopLevelShows(window, *QApplication.topLevelWidgets())` exempts every top-level widget that exists at setup, hidden or not, so a pre-existing hidden top-level that a click shows is never reported. Exempt only the widgets visible at setup (`isVisible()`), so the spy catches a hidden window that gets shown. | itself |

test_slide_list_gui.py: read 54 tests, 0 flagged
test_citations.py: read 38 tests, 0 flagged
test_source_view_gui.py: read 32 tests, 2 flagged
test_translation_groups.py: read 25 tests, 0 flagged
test_create_slide.py: read 23 tests, 0 flagged
test_add_slide_gui.py: read 21 tests, 1 flagged
test_plugin_loader.py: read 19 tests, 2 flagged
test_qr_code.py: read 18 tests, 0 flagged
test_agent.py: read 17 tests, 0 flagged
test_palette_gui.py: read 15 tests, 1 flagged
test_theme_sources.py: read 14 tests, 0 flagged
test_open_project_gui.py: read 14 tests, 1 flagged
test_reveal_flag.py: read 13 tests, 1 flagged
test_deck_settings_gui.py: read 13 tests, 0 flagged
test_slide_ids.py: read 12 tests, 0 flagged
test_theme_sources_gui.py: read 11 tests, 0 flagged
test_plugin_selftest.py: read 11 tests, 0 flagged
test_updater.py: read 10 tests, 0 flagged
test_tls_trust.py: read 9 tests, 0 flagged
test_deck_groups.py: read 9 tests, 0 flagged
test_plugin_deck_edits.py: read 8 tests, 0 flagged
test_color_modes.py: read 8 tests, 1 flagged
test_revealed_footnotes.py: read 7 tests, 0 flagged
test_ai_tasks.py: read 7 tests, 0 flagged
test_plugin_box_refresh.py: read 6 tests, 0 flagged
test_compile_passes.py: read 6 tests, 0 flagged
test_update_check_gui.py: read 5 tests, 0 flagged
test_snippets.py: read 5 tests, 0 flagged
test_navigation.py: read 5 tests, 1 flagged
test_transcript_languages.py: read 4 tests, 0 flagged
test_project_access.py: read 4 tests, 0 flagged
test_debug_log_tool.py: read 4 tests, 0 flagged
test_stray_windows_gui.py: read 3 tests, 1 flagged
test_prompt_stores.py: read 3 tests, 0 flagged
test_attachments.py: read 3 tests, 0 flagged
test_review_ai_backend.py: read 2 tests, 0 flagged
test_figure_helpers.py: read 2 tests, 0 flagged
test_version.py: read 1 test, 0 flagged
test_preview_thumbnails.py: read 1 test, 0 flagged
test_framework_probes.py: read 1 test, 0 flagged
