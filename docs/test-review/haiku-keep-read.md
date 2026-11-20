# Haiku keep-read: tests proposed for removal or rewrite

Scope and honesty note: the full keep-read pass (every `keep` test, file by file) was NOT completed. I read the `keep` bodies only for the
no-direct-assert and installer/theme groups listed below, plus the helpers they depend on. The rest of the 2683 `keep` rows were not opened.
Nothing was edited.

| file | test | verdict | reason | covering test |
|---|---|---|---|---|
| test_themes.py | `test_the_fixture_theme_passes_every_check` (L96) | drop | asserts only `themes.check_folder(theme_folder).id` on the fixture; `install_file` runs the same `check_folder` (src/slidemage/themes.py:202 partial of packages.check_folder) and the install tests assert id and version | test_themes.py::test_install_unpacks_into_the_themes_folder |
| test_plugin_installer.py | `test_zip_slip` (L77), `test_absolute_path` (L81) | merge | both are `fails(make_zip(...extra=[name]), "unsafe")` with the same helper (which also asserts no staging and no install); merge into one parametrised test over the member names | each other (test_plugin_installer.py) |
| test_plugin_installer.py | `test_bad_manifest` (L123), `test_wrong_api_version` (L131), `test_requires_newer_slidemage` (L135) | merge | all three are `fails(...)` with a message regex on a bad manifest; one parametrised test (name, toml change, message). No assertion is lost | each other |
| test_presentation_launch.py | `test_the_command_is_in_the_palette_with_f5_and_needs_a_deck` / `..._shift_f5_...` | merge (candidate, body not read by me) | mechanical duplicate body (same AST after normalising names/literals); merge into one parametrised test over the key | each other |
| test_steps_edit.py | `test_a_conditionalslide_missing_a_version_is_refused_because_frame_numbers_would_change` / `test_a_version_the_call_does_not_serve_is_refused` | merge (candidate, body not read by me) | mechanical duplicate body; check the two messages are the only difference | each other |
| test_ui_kit_gui.py | `test_an_item_of_the_flyout_is_triggered_on_the_menu_and_closes_both` / `test_clicking_another_row_of_the_menu_while_the_flyout_is_open_works` | keep (not merged) | mechanical duplicate body but different behaviour in the test names; read both before any change | - |

## Checked and NOT proposed for removal (so the next reader does not redo it)
- test_themes.py::test_a_key_of_a_bundled_template_is_refused (check_folder path) and test_a_bundled_key_or_a_too_new_requirement_installs_nothing (install_file path) both assert the bundled-key refusal, but through different entry points; keep both.
- test_plugin_installer.py::test_symlink and test_drive_letter_and_backslash: different checks (symbolic link, drive letter); keep.
- test_settings_gui.py open_sheet tests and test_settings_ai_gui.py test_the_ai_tab_has_the_policy...: different assertions; keep.
- test_accessibility_gui.py::test_the_link_of_the_policy_popover_is_reachable_from_the_keyboard vs test_ai_switch_gui.py::test_the_policy_popover_links_to_ai_setup: keyboard vs mouse path; keep.

## Per-file
- test_plugin_installer.py: read 14 tests (plus the `fails` helper), M flagged 3 groups (merge), 0 drops.
- test_themes.py: read 1 keep test body (test_the_fixture_theme_passes_every_check) and the install tests it relies on; M flagged 1 drop.
- test_splash.py: read 2 tests; flagged in haiku-overlap.md (rewrite).
- test_steps_edit.py, test_settings_ai_gui.py: flagged in haiku-overlap.md (rewrite).
- All other files: not read in the keep pass; 0 proposals (not 0 problems).

## Second pass (keep tests, all 247 files at HEAD)

Method: (a) AST scan of all 2614 keep bodies for no assert / weak-only asserts / `or` asserts (script output reviewed); (b) full read of the flagged bodies and of some whole files. The scan is mechanical: it finds candidates, the reads decide. Files NOT read in body are listed at the end.

### Proposals (rewrite or remove), keep verdicts
| file | test | verdict | reason | covering test |
|---|---|---|---|---|
| test_steps_edit.py | `test_a_comment_between_alternatives_keeps_them_one_place_other_text_does_not` (L133) | rewrite | first assert ends `... or True`: a tautology, can never fail. Assert the real result of `edit()` for the comment case (take the expected text from the src behaviour) | none |
| test_presentation_gui.py | `test_the_audience_window_shows_nothing_but_the_slide` (L96) | rewrite | the `all(...)` branch uses non-recursive `findChildren(QLabel)` while the first clause is recursive, so nested labels are never checked | none |
| test_preview_queue.py | `test_refresh_tool_publishes_saved_artifact_through_gui_workspace` (L701, assert L774) | rewrite | `pixmap is None or pixmap.toImage() == old_image` passes when nothing was rendered; assert the new image | none |
| test_background_previews_gui.py | `test_the_status_window_lists_every_deck_with_its_versions_and_state` (L388, assert L405) | rewrite | `not failures.isHidden() or dialog.isHidden()` passes whenever the dialog is hidden | none |
| test_background_renders.py | `test_the_planner_hands_over_consecutive_units_...` (L615, assert L635) | rewrite | `== min(...) or not r._plan` is vacuous whenever the plan is empty | none |
| test_background_renders.py | `test_editing_the_slide_or_what_it_reads_makes_it_outstanding_again` (L179, assert L190) | rewrite (check src first) | `MISSING or STALE` accepts two states; pin the one the edit produces | none |
| test_deck_context.py | `test_without_a_usable_compile_there_is_no_deck_render` (L206, assert L216) | rewrite | `failure != "refused" or any("old" in line ...)` is weak; the second clause alone decides | none |
| test_accessibility_gui.py | `test_the_real_announce_runs_on_this_qt` (L220) | rewrite | body is one call, no assertion; can only fail by raising. Assert the text reaches the accessible announcement | none (test_accessibility_cards_gui tests announce only through a monkeypatched image_results.announce) |
| test_plugin_installer.py | `test_zip_slip` + `test_absolute_path` (L77, L81) | merge | same `fails(..., "unsafe")` check, one parametrised test | each other |
| test_plugin_installer.py | `test_bad_manifest`, `test_wrong_api_version`, `test_requires_newer_slidemage` (L123, L131, L135) | merge | all `fails(...)` with a message on a bad manifest; one parametrised test, no assertion lost | each other |
| test_themes.py | `test_the_fixture_theme_passes_every_check` (L96) | drop | only `check_folder(...).id`; install path runs the same check and asserts id/version | test_themes.py::test_install_unpacks_into_the_themes_folder |
| test_splash.py | `test_releasing_the_splash_never_touches_windows_off_windows` | rewrite | no assertion (see first report) | test_splash.py::test_releasing_the_splash_is_a_no_op_without_a_splash (other branch only) |

Not proposed (checked): test_presentation_launch.py::test_only_one_presentation_runs_at_a_time (no assert, but the monkeypatched pytest.fail fails the test if a PDF is searched: acceptable); test_pty_process.py (two tests; loops and a final raise, real checks); test_stall_monitor.py (`late=0.4 or late=0.5` is timing tolerance, not a tautology); test_workspace_window.py::test_top_bar_densities (conditional by design); test_assistant_gui.py::test_only_the_tasks_the_route_can_run (wait_until asserts the timeout); test_tasks_gui.py::test_the_text_bubbles... (wait_until asserts the timeout); test_preview_build.py::test_the_framework_names_a_missing_ovl... (greps the framework .tex for a fixed string: brittle, but it guards real behaviour; not removed).

### Per-file (bodies I actually read)
- test_preview_build.py: read 27 of 30 keep tests, M flagged 0 for removal (1 brittle source-grep noted).
- test_preview_queue.py: read 1 of 38, M flagged 1 (L701 rewrite).
- test_bundled_copies.py: read 0 of 9 (body not reached).
- test_plugin_installer.py: read 13 of 13 keep tests, M flagged 2 merge groups (3 tests in groups above, 4 tests in the 2nd group).
- test_splash.py: read 2 of 2, M flagged 1.
- test_presentation_gui.py: read 3 of 3 flagged, M flagged 1 (L96).
- test_steps_edit.py: read 1 of 1 flagged keep test, M flagged 1 (L133).
- test_reveal_bar_gui.py: read 1 flagged keep test, M flagged 0.
- test_background_renders.py: read 2 flagged keep tests, M flagged 2.
- test_background_previews_gui.py: read 1, M flagged 1.
- test_deck_context.py: read 1, M flagged 1.
- test_preview_queue.py / test_accessibility_gui.py / test_assistant_gui.py / test_tasks_gui.py / test_plugin_offer.py / test_workspace_window.py / test_topbar_tab_order_gui.py / test_ui_kit_gui.py / test_stall_monitor.py / test_pty_process.py / test_presentation_launch.py / test_themes.py: read the flagged keep tests only (1-2 each), see "Not proposed" and proposals above.

### Files NOT covered in body (keep pass incomplete)
All other keep tests: the 2614-test scan covered every keep test mechanically; their bodies were not read except the flagged ones above. Remaining unread bodies include essentially all of tests/test_*.py except the files named above (in particular test_bundled_copies, test_qr_code, test_qr_dialog_gui, test_latex_export, test_deck_snapshot, test_plugin_settings_tab, test_slide_list_gui, test_agent_tools, test_centre_gui, test_compat, test_languages, test_render_key, test_updater, test_plugin_host and the rest). The 15 overlap files read only 16 lines per test were not re-read.
