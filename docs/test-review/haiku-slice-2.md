# Test review, slice 2 (haiku)

Read-only review. Each test body was read in full. Flags only where a concrete break would pass the test, or a concrete duplicate exists.

| file | test | line | drop/merge/rewrite | reason | covering test |
|---|---|---|---|---|---|
| test_side_panels_gui.py | test_redraft_stops_when_there_is_no_model_or_it_fails | 698 | rewrite | The last call `_on_drafted("cit", "media/gone.png", ...)` has no assertion. A regression that writes the draft into the wrong slot or the wrong form still passes. | none (add an assertion that the form values and the store are unchanged) |
| test_side_panels_gui.py | test_images_show_state_and_save_drafts_and_reviews_through_the_store | 562 | rewrite | Lines 562-564 repeat the refusal of review without a long description that is asserted in full by the next test. | test_the_images_panel_refuses_review_without_a_long_description |
| test_readability.py | test_the_thresholds_are_one_frozen_set_and_a_check_can_use_another | 425 | rewrite | `pytest.raises(Exception)` also passes when `readability.DEFAULTS` is removed (AttributeError), so the freeze is not what is tested. `Thresholds` is a frozen dataclass, so narrow it to `dataclasses.FrozenInstanceError`. | none |
| test_calibrate_font_profile.py | test_new_needs_all_four_faces | 135 | rewrite | `pytest.raises(SystemExit)` also passes when `--new` is unknown to the parser (argparse also exits with SystemExit), so the test does not show that the four-face rule holds. Assert on the message or on the exit code plus the missing-face text. | none |
| test_themes_gui.py | test_no_theme_says_how_to_get_one | 65 | rewrite | The name promises the empty-state caption ("No themes are installed. A theme is a slide template ...", settings_plugins.py line 731), but the body asserts only `theme_rows == {}`. Removing or breaking the caption passes. | none (assert the caption text on the tab) |
| test_compare_rendered_gui.py | test_the_dialog_in_both_themes | 231 | rewrite | Asserts only that a PNG over 1000 bytes is saved. Nothing checks that the light or dark theme reached the dialog, so a dialog painted in the wrong theme passes. | none (assert the background color of the grabbed image, or the palette, per theme) |

test_side_panels_gui.py: read 69 tests, 2 flagged
test_settings_gui.py: read 34 tests, 0 flagged
test_readability.py: read 31 tests, 1 flagged
test_deck_settings.py: read 25 tests, 0 flagged
test_image_batches_gui.py: read 22 tests, 0 flagged
test_selection.py: read 20 tests, 0 flagged
test_menu_bar_gui.py: read 19 tests, 0 flagged
test_plugin_updates.py: read 17 tests, 0 flagged
test_latex_export.py: read 16 tests, 0 flagged
test_compare_rendered_gui.py: read 15 tests, 1 flagged
test_preview_target.py: read 14 tests, 0 flagged
test_calibrate_font_profile.py: read 14 tests, 1 flagged
test_personal_themes.py: read 13 tests, 0 flagged
test_workspace_state.py: read 12 tests, 0 flagged
test_fileio.py: read 12 tests, 0 flagged
test_plugin_terminal.py: read 11 tests, 0 flagged (the whole file is skipped on win32, so it does not run in this review's environment)
test_accessibility_cards_gui.py: read 11 tests, 0 flagged
test_ai_review_gui.py: read 10 tests, 0 flagged
test_housekeeping_gui.py: read 9 tests, 0 flagged
test_release_notes.py: read 8 tests, 0 flagged
test_open_pdf.py: read 8 tests, 0 flagged
test_transcript_options.py: read 7 tests, 0 flagged
test_provider_tasks.py: read 7 tests, 0 flagged
test_themes_gui.py: read 6 tests, 1 flagged
test_compile_controller.py: read 6 tests, 0 flagged
test_plugin_api_contract.py: read 6 tests, 0 flagged
test_tex_source.py: read 5 tests, 0 flagged
test_reveal_steps_tex.py: read 5 tests, 0 flagged (TeX-gated; skipped without latexmk and lualatex)
test_deck_context_tex.py: read 5 tests, 0 flagged (TeX-gated)
test_review_gui.py: read 4 tests, 0 flagged
test_framework_fallback.py: read 4 tests, 0 flagged
test_alt_store_version.py: read 4 tests, 0 flagged
test_qr_code_tex.py: read 3 tests, 0 flagged (TeX-gated)
test_import_presentation_gui.py: read 3 tests, 0 flagged
test_transcript_preview_gui.py: read 2 tests, 0 flagged
test_manual_fits_templates.py: read 2 tests, 0 flagged (compiles the manual; opt-in via SLIDEMAGE_TEX_TESTS=1)
test_deck_editor_insert.py: read 2 tests, 0 flagged
test_preview_views_latex.py: read 1 test (parametrized to 2 cases), 0 flagged (opt-in via SLIDEMAGE_REAL_LATEX=1)
test_job_panel_gui.py: read 1 test, 0 flagged

Totals: 39 files read, 463 test functions read (parametrized tests counted once), 6 flagged (5 files).
