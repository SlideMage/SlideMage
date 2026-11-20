# Test inventory (3377 test functions, 4628 collected cases)

Verdicts (per function): {'keep': 2683, 'review-overlap': 641, 'rewrite': 37, 'merge': 4, 'ASK-drop': 11, 'drop-candidate': 1}. Summed test time (8 workers, so inflated by load): 4155 s.

Per-test rows are in `test-inventory.csv` (filter by verdict/flags).


## Per file

| file | funcs | cases | secs | verdicts | flags |
|---|---|---|---|---|---|
| test_about_gui.py | 3 | 3 | 0.7 | {'keep': 3} | {'reads-example': 1} |
| test_accessibility_cards_gui.py | 11 | 11 | 8.3 | {'keep': 9, 'review-overlap': 2} | {'no-unique-coverage': 9, 'waits/sleeps': 1} |
| test_accessibility_gui.py | 21 | 27 | 30.8 | {'keep': 14, 'review-overlap': 7} | {'no-unique-coverage': 11, 'reads-example': 1, 'no-direct-assert': 1, 'slow': 4} |
| test_add_slide_gui.py | 21 | 23 | 8.8 | {'keep': 18, 'review-overlap': 3} | {'no-unique-coverage': 4, 'waits/sleeps': 1} |
| test_agent.py | 17 | 20 | 1.9 | {'keep': 16, 'review-overlap': 1} | {'no-unique-coverage': 6} |
| test_agent_tools.py | 68 | 79 | 10.6 | {'keep': 54, 'review-overlap': 14} | {'no-unique-coverage': 16, 'skipped-here': 2, 'legacy-compat': 5, 'reads-example': 3, 'waits/sleeps': 1} |
| test_ai_chat_service.py | 15 | 21 | 0.5 | {'keep': 14, 'review-overlap': 1} | {'no-unique-coverage': 1} |
| test_ai_fix_gui.py | 15 | 15 | 0.4 | {'keep': 11, 'review-overlap': 4} | {'no-unique-coverage': 7, 'legacy-compat': 1} |
| test_ai_free_editor_gui.py | 3 | 3 | 2.4 | {'keep': 2, 'review-overlap': 1} | {'waits/sleeps': 2, 'no-unique-coverage': 3} |
| test_ai_models_gui.py | 8 | 9 | 0.2 | {'keep': 7, 'review-overlap': 1} | {'no-unique-coverage': 2} |
| test_ai_profile.py | 15 | 27 | 0.6 | {'keep': 14, 'review-overlap': 1} | {'legacy-compat': 2, 'no-unique-coverage': 1} |
| test_ai_providers.py | 16 | 31 | 0.7 | {'keep': 15, 'review-overlap': 1} | {'no-unique-coverage': 1} |
| test_ai_review.py | 14 | 20 | 2.1 | {'keep': 10, 'review-overlap': 4} | {'no-unique-coverage': 8} |
| test_ai_review_gui.py | 10 | 22 | 14.7 | {'keep': 8, 'review-overlap': 2} | {'no-unique-coverage': 5, 'waits/sleeps': 1, 'slow': 1} |
| test_ai_routes.py | 13 | 13 | 0.4 | {'keep': 10, 'review-overlap': 3} | {'no-unique-coverage': 5, 'legacy-compat': 2} |
| test_ai_routes_ui_gui.py | 6 | 6 | 5.4 | {'keep': 5, 'review-overlap': 1} | {'waits/sleeps': 3, 'no-unique-coverage': 5} |
| test_ai_switch_gui.py | 24 | 24 | 66.1 | {'keep': 16, 'review-overlap': 8} | {'slow': 18, 'no-unique-coverage': 13, 'waits/sleeps': 3} |
| test_ai_tasks.py | 7 | 9 | 0.4 | {'keep': 6, 'review-overlap': 1} | {'no-unique-coverage': 1} |
| test_alt_store_version.py | 4 | 4 | 0.2 | {'review-overlap': 3, 'keep': 1} | {'no-unique-coverage': 3} |
| test_app_settings.py | 4 | 4 | 0.3 | {'review-overlap': 2, 'keep': 2} | {'no-unique-coverage': 2, 'legacy-compat': 2} |
| test_appendix_toc.py | 3 | 9 | 1.6 | {'keep': 3} | {'no-unique-coverage': 1} |
| test_assistant_gui.py | 15 | 15 | 42.4 | {'review-overlap': 5, 'keep': 10} | {'slow': 14, 'no-unique-coverage': 8, 'no-direct-assert': 1} |
| test_attachments.py | 3 | 3 | 0.1 | {'review-overlap': 1, 'keep': 2} | {'no-unique-coverage': 2} |
| test_background.py | 11 | 17 | 0.9 | {'keep': 11} | {'waits/sleeps': 3, 'no-unique-coverage': 7} |
| test_background_previews_gui.py | 28 | 28 | 44.9 | {'keep': 24, 'review-overlap': 4} | {'slow': 13, 'no-unique-coverage': 7, 'waits/sleeps': 5, 'long': 1} |
| test_background_renders.py | 45 | 46 | 418.5 | {'keep': 41, 'review-overlap': 3, 'rewrite': 1} | {'no-unique-coverage': 7, 'waits/sleeps': 1, 'slow': 32, 'TeX': 2, 'reads-example': 1, 'skipped-here': 2, 'legacy-compat': 3} |
| test_batch_render.py | 5 | 6 | 32.2 | {'keep': 4, 'rewrite': 1} | {'slow': 2, 'no-unique-coverage': 1} |
| test_bibliography_template.py | 4 | 4 | 0.2 | {'keep': 4} | {'reads-example': 1} |
| test_bundled_copies.py | 13 | 15 | 15.1 | {'keep': 13} | {'reads-example': 9, 'no-unique-coverage': 2, 'slow': 1, 'legacy-compat': 1} |
| test_calibrate_font_profile.py | 14 | 16 | 0.3 | {'keep': 14} | {'legacy-compat': 1, 'reads-example': 1, 'skipped-here': 3} |
| test_centre_gui.py | 120 | 127 | 54.7 | {'keep': 90, 'review-overlap': 30} | {'no-unique-coverage': 48, 'slow': 2, 'waits/sleeps': 4, 'legacy-compat': 5} |
| test_centre_tabs.py | 15 | 15 | 0.3 | {'keep': 15} | {'legacy-compat': 1} |
| test_chat_gui.py | 47 | 72 | 783.5 | {'rewrite': 1, 'keep': 39, 'review-overlap': 7} | {'slow': 7, 'no-unique-coverage': 11, 'reads-example': 2} |
| test_check_layout_margins.py | 13 | 13 | 6.7 | {'keep': 13} | {'legacy-compat': 1, 'slow': 1} |
| test_citations.py | 38 | 58 | 22.8 | {'keep': 24, 'review-overlap': 14} | {'legacy-compat': 10, 'no-unique-coverage': 15, 'slow': 4} |
| test_citations_gui.py | 7 | 7 | 1.0 | {'review-overlap': 1, 'keep': 6} | {'no-unique-coverage': 1} |
| test_cli_self_test.py | 1 | 1 | 2.1 | {'keep': 1} | {'slow': 1} |
| test_code_file.py | 4 | 4 | 0.2 | {'keep': 3, 'review-overlap': 1} | {'no-unique-coverage': 1} |
| test_color_modes.py | 8 | 8 | 0.0 | {'keep': 8} | {'skipped-here': 8} |
| test_color_modes_app.py | 6 | 6 | 0.3 | {'review-overlap': 3, 'keep': 3} | {'no-unique-coverage': 4} |
| test_commands.py | 8 | 8 | 0.3 | {'keep': 6, 'review-overlap': 2} | {'no-unique-coverage': 2} |
| test_compare_rendered_gui.py | 15 | 16 | 68.1 | {'keep': 14, 'review-overlap': 1} | {'slow': 14, 'legacy-compat': 1, 'no-unique-coverage': 4} |
| test_compat.py | 22 | 27 | 0.7 | {'keep': 20, 'review-overlap': 2} | {'legacy-compat': 4, 'no-unique-coverage': 3, 'reads-example': 1} |
| test_compat_bibliography.py | 12 | 12 | 0.4 | {'keep': 12} | {'legacy-compat': 2} |
| test_compat_color_roles.py | 6 | 34 | 0.4 | {'keep': 6} | {} |
| test_compat_gui.py | 7 | 9 | 0.4 | {'keep': 7} | {'legacy-compat': 1} |
| test_compat_names.py | 11 | 11 | 0.9 | {'keep': 11} | {'TeX': 2, 'legacy-compat': 4} |
| test_compat_own_theme.py | 10 | 10 | 0.6 | {'keep': 10} | {'legacy-compat': 3} |
| test_compat_project_macros.py | 4 | 4 | 0.0 | {'keep': 4} | {} |
| test_compat_setup.py | 4 | 4 | 0.0 | {'keep': 4} | {} |
| test_compile_controller.py | 6 | 6 | 0.1 | {'keep': 5, 'review-overlap': 1} | {'no-unique-coverage': 2, 'TeX': 1} |
| test_compile_flow_gui.py | 14 | 15 | 8.0 | {'keep': 13, 'review-overlap': 1} | {'no-unique-coverage': 3} |
| test_compile_log.py | 2 | 17 | 0.1 | {'keep': 1, 'review-overlap': 1} | {'no-unique-coverage': 1} |
| test_compile_passes.py | 6 | 6 | 0.1 | {'keep': 6} | {'TeX': 3, 'no-unique-coverage': 1} |
| test_compile_records.py | 8 | 8 | 0.8 | {'keep': 5, 'review-overlap': 3} | {'no-unique-coverage': 5, 'TeX': 1, 'legacy-compat': 1} |
| test_compile_status.py | 10 | 10 | 0.1 | {'keep': 5, 'review-overlap': 5} | {'TeX': 1, 'no-unique-coverage': 6, 'legacy-compat': 1} |
| test_create_slide.py | 23 | 51 | 14.3 | {'keep': 18, 'review-overlap': 5} | {'no-unique-coverage': 9, 'slow': 1, 'reads-example': 1} |
| test_debug_instrumentation.py | 11 | 11 | 0.2 | {'review-overlap': 7, 'keep': 4} | {'no-unique-coverage': 7, 'TeX': 1} |
| test_debug_log_tool.py | 4 | 4 | 0.1 | {'keep': 4} | {'no-unique-coverage': 1} |
| test_deck_context.py | 13 | 36 | 0.7 | {'keep': 11, 'review-overlap': 2} | {'no-unique-coverage': 3} |
| test_deck_context_gui.py | 5 | 5 | 2.9 | {'keep': 3, 'review-overlap': 2} | {'no-unique-coverage': 2, 'waits/sleeps': 2} |
| test_deck_context_tex.py | 5 | 5 | 161.8 | {'rewrite': 4, 'review-overlap': 1} | {'slow': 4, 'reads-example': 1, 'no-unique-coverage': 1} |
| test_deck_editor_insert.py | 2 | 2 | 0.1 | {'review-overlap': 2} | {'no-unique-coverage': 2} |
| test_deck_groups.py | 9 | 26 | 0.5 | {'keep': 8, 'review-overlap': 1} | {'no-unique-coverage': 3} |
| test_deck_headers.py | 4 | 9 | 0.4 | {'keep': 3, 'review-overlap': 1} | {'no-unique-coverage': 2} |
| test_deck_in_several_groups.py | 17 | 17 | 7.1 | {'review-overlap': 5, 'keep': 12} | {'no-unique-coverage': 6} |
| test_deck_language.py | 26 | 62 | 5.7 | {'keep': 18, 'review-overlap': 8} | {'no-unique-coverage': 14, 'reads-example': 1, 'legacy-compat': 1} |
| test_deck_new.py | 2 | 2 | 0.0 | {'keep': 2} | {'no-unique-coverage': 1} |
| test_deck_outline.py | 18 | 31 | 0.6 | {'keep': 13, 'review-overlap': 5} | {'legacy-compat': 1, 'no-unique-coverage': 7} |
| test_deck_settings.py | 25 | 29 | 0.3 | {'review-overlap': 6, 'keep': 19} | {'no-unique-coverage': 6, 'legacy-compat': 4, 'reads-example': 1} |
| test_deck_settings_gui.py | 13 | 21 | 0.6 | {'keep': 12, 'review-overlap': 1} | {'no-unique-coverage': 2} |
| test_deck_settings_maintenance_gui.py | 6 | 8 | 0.2 | {'keep': 6} | {} |
| test_deck_snapshot.py | 32 | 33 | 21.8 | {'review-overlap': 5, 'keep': 27} | {'no-unique-coverage': 8, 'skipped-here': 3, 'reads-example': 4, 'TeX': 2, 'legacy-compat': 3, 'slow': 2} |
| test_deck_snapshot_gui.py | 10 | 15 | 0.7 | {'keep': 10} | {'legacy-compat': 3} |
| test_deck_versions.py | 6 | 8 | 0.5 | {'keep': 4, 'review-overlap': 2} | {'no-unique-coverage': 5} |
| test_design_handbook.py | 2 | 2 | 0.2 | {'keep': 2} | {} |
| test_diagnostics.py | 20 | 20 | 1.2 | {'keep': 14, 'review-overlap': 6} | {'no-unique-coverage': 7, 'legacy-compat': 5, 'TeX': 1} |
| test_duplicate_deck_gui.py | 2 | 2 | 8.5 | {'review-overlap': 2} | {'slow': 2, 'no-unique-coverage': 2} |
| test_figure_helpers.py | 2 | 2 | 0.1 | {'review-overlap': 2} | {'no-unique-coverage': 2} |
| test_fileio.py | 12 | 14 | 0.5 | {'keep': 10, 'review-overlap': 2} | {'legacy-compat': 5, 'no-unique-coverage': 3, 'waits/sleeps': 1, 'skipped-here': 1} |
| test_find_replace_gui.py | 5 | 6 | 0.3 | {'keep': 5} | {'waits/sleeps': 1} |
| test_framework_fallback.py | 4 | 4 | 0.2 | {'review-overlap': 2, 'keep': 2} | {'no-unique-coverage': 2} |
| test_framework_probes.py | 1 | 1 | 0.1 | {'keep': 1} | {} |
| test_framework_regression.py | 11 | 11 | 1.7 | {'keep': 11} | {} |
| test_helper_stdin.py | 2 | 2 | 0.1 | {'review-overlap': 1, 'keep': 1} | {'no-unique-coverage': 1} |
| test_hook_geometry.py | 17 | 17 | 0.0 | {'keep': 17} | {'skipped-here': 15} |
| test_housekeeping_gui.py | 9 | 9 | 0.4 | {'review-overlap': 2, 'keep': 7} | {'legacy-compat': 1, 'no-unique-coverage': 2, 'waits/sleeps': 1} |
| test_idle_gate.py | 9 | 9 | 0.1 | {'keep': 8, 'review-overlap': 1} | {'no-unique-coverage': 2, 'legacy-compat': 1} |
| test_image_batches_gui.py | 22 | 23 | 7.7 | {'review-overlap': 6, 'keep': 16} | {'no-unique-coverage': 10, 'slow': 1} |
| test_image_languages.py | 14 | 14 | 0.9 | {'review-overlap': 5, 'keep': 9} | {'no-unique-coverage': 5} |
| test_image_review.py | 21 | 21 | 1.4 | {'keep': 17, 'review-overlap': 4} | {'no-unique-coverage': 6} |
| test_image_source.py | 14 | 14 | 1.6 | {'keep': 8, 'review-overlap': 6} | {'no-unique-coverage': 10, 'legacy-compat': 1} |
| test_image_source_gui.py | 6 | 6 | 10.5 | {'keep': 6} | {'slow': 1} |
| test_images_page_gui.py | 47 | 54 | 21.6 | {'keep': 42, 'review-overlap': 5} | {'slow': 2, 'waits/sleeps': 2, 'no-unique-coverage': 10} |
| test_import_presentation_gui.py | 3 | 3 | 0.1 | {'keep': 3} | {} |
| test_insert_popovers_gui.py | 9 | 9 | 1.3 | {'keep': 8, 'review-overlap': 1} | {'no-unique-coverage': 1} |
| test_job_order.py | 1 | 5 | 0.1 | {'keep': 1} | {'no-unique-coverage': 1} |
| test_job_panel_gui.py | 1 | 1 | 0.1 | {'keep': 1} | {'no-unique-coverage': 1} |
| test_language_line.py | 7 | 9 | 1.5 | {'keep': 5, 'review-overlap': 2} | {'no-unique-coverage': 4, 'legacy-compat': 1} |
| test_language_tex.py | 13 | 13 | 557.6 | {'rewrite': 13} | {'slow': 13, 'no-unique-coverage': 5} |
| test_languages.py | 20 | 32 | 7.3 | {'keep': 17, 'review-overlap': 3} | {'no-unique-coverage': 5, 'legacy-compat': 5, 'slow': 1, 'reads-example': 1} |
| test_latex_edit.py | 22 | 29 | 0.5 | {'keep': 13, 'review-overlap': 9} | {'reads-example': 1, 'no-unique-coverage': 9} |
| test_latex_export.py | 16 | 16 | 114.8 | {'keep': 14, 'review-overlap': 2} | {'slow': 10, 'legacy-compat': 6, 'TeX': 2, 'no-unique-coverage': 2} |
| test_latex_export_gui.py | 5 | 5 | 7.5 | {'keep': 4, 'review-overlap': 1} | {'slow': 2, 'legacy-compat': 2, 'no-unique-coverage': 1} |
| test_latex_lint.py | 6 | 26 | 0.7 | {'keep': 5, 'review-overlap': 1} | {'reads-example': 1, 'no-unique-coverage': 1} |
| test_make_readable_gui.py | 18 | 19 | 22.9 | {'keep': 15, 'review-overlap': 3} | {'no-unique-coverage': 6} |
| test_manual_fits_templates.py | 2 | 3 | 0.0 | {'keep': 2} | {'skipped-here': 1, 'reads-example': 1} |
| test_manual_group.py | 8 | 8 | 0.1 | {'review-overlap': 4, 'keep': 4} | {'no-unique-coverage': 4} |
| test_menu_bar_gui.py | 19 | 20 | 16.7 | {'review-overlap': 10, 'keep': 9} | {'slow': 1, 'no-unique-coverage': 11, 'waits/sleeps': 2} |
| test_modify_slide.py | 19 | 46 | 14.9 | {'keep': 14, 'review-overlap': 5} | {'no-unique-coverage': 10} |
| test_navigation.py | 5 | 5 | 1.0 | {'keep': 3, 'review-overlap': 2} | {'legacy-compat': 2, 'no-unique-coverage': 2} |
| test_open_path.py | 1 | 3 | 0.0 | {'keep': 1} | {'skipped-here': 1, 'reads-example': 1} |
| test_open_pdf.py | 8 | 13 | 0.9 | {'keep': 6, 'review-overlap': 2} | {'no-unique-coverage': 2} |
| test_open_project_gui.py | 14 | 18 | 4.1 | {'keep': 13, 'review-overlap': 1} | {'legacy-compat': 4, 'no-unique-coverage': 1, 'reads-example': 1} |
| test_packages.py | 3 | 6 | 1.6 | {'keep': 3} | {'legacy-compat': 1, 'no-unique-coverage': 1} |
| test_packaging.py | 1 | 1 | 0.0 | {'keep': 1} | {'skipped-here': 1} |
| test_palette_gui.py | 15 | 16 | 62.8 | {'review-overlap': 4, 'keep': 11} | {'no-unique-coverage': 5, 'slow': 14, 'legacy-compat': 1} |
| test_parallel_runs.py | 8 | 8 | 2.0 | {'review-overlap': 2, 'keep': 6} | {'no-unique-coverage': 4, 'waits/sleeps': 2} |
| test_partial_compile.py | 11 | 19 | 30.6 | {'keep': 10, 'review-overlap': 1} | {'slow': 1, 'TeX': 2, 'no-unique-coverage': 4} |
| test_personal_themes.py | 13 | 13 | 4.4 | {'review-overlap': 1, 'keep': 12} | {'no-unique-coverage': 1, 'slow': 1} |
| test_plugin_ai_free_core.py | 4 | 4 | 0.1 | {'keep': 4} | {'legacy-compat': 1} |
| test_plugin_ai_tools.py | 7 | 7 | 0.5 | {'review-overlap': 1, 'keep': 6} | {'no-unique-coverage': 2} |
| test_plugin_api_contract.py | 6 | 8 | 0.4 | {'keep': 6} | {'legacy-compat': 1} |
| test_plugin_boundary.py | 2 | 2 | 3.8 | {'keep': 2} | {'slow': 1} |
| test_plugin_box_refresh.py | 6 | 6 | 10.9 | {'keep': 5, 'review-overlap': 1} | {'slow': 2, 'no-unique-coverage': 1} |
| test_plugin_campusonline_e2e.py | 4 | 4 | 0.0 | {'keep': 4} | {'skipped-here': 4, 'reads-example': 1} |
| test_plugin_catalogue.py | 28 | 45 | 7.9 | {'keep': 17, 'merge': 4, 'review-overlap': 7} | {'legacy-compat': 3, 'sibling-group': 4, 'no-unique-coverage': 9, 'no-direct-assert': 1, 'slow': 1} |
| test_plugin_credentials.py | 12 | 12 | 0.8 | {'keep': 11, 'review-overlap': 1} | {'skipped-here': 2, 'legacy-compat': 4, 'no-unique-coverage': 1} |
| test_plugin_deck_edits.py | 8 | 8 | 12.4 | {'keep': 7, 'review-overlap': 1} | {'legacy-compat': 1, 'slow': 4, 'no-unique-coverage': 2} |
| test_plugin_entry_points.py | 8 | 11 | 0.8 | {'keep': 7, 'review-overlap': 1} | {'no-unique-coverage': 1} |
| test_plugin_host.py | 39 | 40 | 4.2 | {'keep': 35, 'review-overlap': 4} | {'legacy-compat': 2, 'no-unique-coverage': 6, 'reads-example': 1} |
| test_plugin_installer.py | 30 | 41 | 4.1 | {'review-overlap': 7, 'keep': 23} | {'no-unique-coverage': 10, 'no-direct-assert': 14, 'legacy-compat': 1} |
| test_plugin_loader.py | 19 | 20 | 1.3 | {'review-overlap': 9, 'keep': 10} | {'no-unique-coverage': 9, 'legacy-compat': 3} |
| test_plugin_manifest.py | 12 | 61 | 2.3 | {'keep': 10, 'review-overlap': 2} | {'no-unique-coverage': 6, 'legacy-compat': 1} |
| test_plugin_offer.py | 31 | 35 | 25.8 | {'rewrite': 1, 'keep': 29, 'review-overlap': 1} | {'slow': 1, 'waits/sleeps': 1, 'legacy-compat': 7, 'reads-example': 2, 'no-unique-coverage': 1} |
| test_plugin_registry.py | 3 | 3 | 0.1 | {'keep': 3} | {} |
| test_plugin_selftest.py | 11 | 15 | 2.9 | {'keep': 10, 'review-overlap': 1} | {'slow': 1, 'no-unique-coverage': 1} |
| test_plugin_settings_tab.py | 33 | 33 | 11.1 | {'keep': 29, 'review-overlap': 4} | {'no-unique-coverage': 4, 'reads-example': 5, 'slow': 2, 'waits/sleeps': 3} |
| test_plugin_slides.py | 15 | 22 | 1.3 | {'review-overlap': 1, 'keep': 14} | {'no-unique-coverage': 1, 'legacy-compat': 1} |
| test_plugin_terminal.py | 11 | 11 | 0.0 | {'keep': 11} | {'skipped-here': 11, 'waits/sleeps': 1, 'legacy-compat': 1} |
| test_plugin_ui.py | 30 | 32 | 72.6 | {'review-overlap': 7, 'keep': 22, 'rewrite': 1} | {'slow': 6, 'no-unique-coverage': 8} |
| test_plugin_updates.py | 17 | 17 | 1.9 | {'keep': 16, 'review-overlap': 1} | {'no-unique-coverage': 2, 'waits/sleeps': 1, 'legacy-compat': 1} |
| test_plugin_upgrade.py | 16 | 19 | 0.7 | {'keep': 12, 'review-overlap': 4} | {'reads-example': 3, 'legacy-compat': 3, 'no-unique-coverage': 4} |
| test_presentation_core.py | 34 | 34 | 1.4 | {'review-overlap': 4, 'keep': 30} | {'no-unique-coverage': 5, 'reads-example': 1, 'legacy-compat': 4} |
| test_presentation_gui.py | 44 | 46 | 7.5 | {'review-overlap': 7, 'keep': 35, 'rewrite': 2} | {'no-unique-coverage': 11, 'reads-example': 2, 'waits/sleeps': 1, 'legacy-compat': 1, 'FAILED-in-run': 2} |
| test_presentation_launch.py | 15 | 15 | 1.0 | {'review-overlap': 2, 'keep': 13} | {'no-unique-coverage': 2, 'legacy-compat': 1} |
| test_presentation_resume.py | 13 | 13 | 2.1 | {'keep': 13} | {'legacy-compat': 1} |
| test_presenter_app.py | 13 | 17 | 2.0 | {'keep': 12, 'review-overlap': 1} | {'no-unique-coverage': 1, 'waits/sleeps': 3} |
| test_presenter_imports.py | 1 | 1 | 0.5 | {'keep': 1} | {} |
| test_presenter_open_with.py | 14 | 16 | 0.4 | {'keep': 13, 'review-overlap': 1} | {'no-unique-coverage': 2, 'legacy-compat': 1} |
| test_presenter_paths.py | 5 | 5 | 2.8 | {'keep': 5} | {'slow': 1, 'reads-example': 1} |
| test_presenter_update.py | 23 | 31 | 1.0 | {'keep': 19, 'review-overlap': 4} | {'no-unique-coverage': 5, 'legacy-compat': 1, 'reads-example': 1} |
| test_preview_bench.py | 5 | 8 | 0.2 | {'ASK-drop': 5} | {'reads-example': 1, 'TeX': 2} |
| test_preview_benchmark.py | 6 | 14 | 1.8 | {'ASK-drop': 6} | {'reads-example': 1, 'legacy-compat': 1, 'no-unique-coverage': 1} |
| test_preview_build.py | 32 | 32 | 55.7 | {'keep': 30, 'review-overlap': 2} | {'no-unique-coverage': 9, 'TeX': 15, 'legacy-compat': 5, 'reads-example': 2, 'slow': 5} |
| test_preview_dependencies.py | 9 | 9 | 1.0 | {'keep': 9} | {'TeX': 3, 'reads-example': 2, 'no-unique-coverage': 1} |
| test_preview_pages.py | 4 | 4 | 0.5 | {'keep': 4} | {} |
| test_preview_queue.py | 38 | 63 | 60.4 | {'keep': 38} | {'waits/sleeps': 9, 'no-unique-coverage': 13, 'legacy-compat': 2, 'reads-example': 1, 'slow': 2, 'long': 1} |
| test_preview_raster.py | 9 | 16 | 3.8 | {'keep': 9} | {'no-unique-coverage': 2, 'waits/sleeps': 1} |
| test_preview_requests.py | 6 | 8 | 2.4 | {'keep': 5, 'review-overlap': 1} | {'TeX': 3, 'no-unique-coverage': 5, 'waits/sleeps': 2} |
| test_preview_target.py | 14 | 17 | 0.8 | {'review-overlap': 3, 'keep': 11} | {'no-unique-coverage': 6} |
| test_preview_thumbnails.py | 1 | 1 | 0.4 | {'keep': 1} | {} |
| test_preview_views_latex.py | 1 | 2 | 0.0 | {'keep': 1} | {'skipped-here': 1, 'TeX': 1, 'waits/sleeps': 1} |
| test_previews_cache.py | 6 | 6 | 0.3 | {'review-overlap': 1, 'keep': 5} | {'legacy-compat': 5, 'no-unique-coverage': 1} |
| test_project_access.py | 4 | 4 | 0.2 | {'review-overlap': 1, 'keep': 3} | {'legacy-compat': 3, 'no-unique-coverage': 1} |
| test_project_context.py | 3 | 3 | 0.6 | {'keep': 3} | {'no-unique-coverage': 1} |
| test_project_format.py | 4 | 5 | 0.3 | {'keep': 4} | {'no-unique-coverage': 1} |
| test_project_watch.py | 3 | 4 | 0.2 | {'review-overlap': 1, 'keep': 2} | {'no-unique-coverage': 2} |
| test_prompt_stores.py | 3 | 3 | 0.3 | {'review-overlap': 2, 'keep': 1} | {'no-unique-coverage': 2} |
| test_protected_regions.py | 8 | 8 | 0.3 | {'review-overlap': 2, 'keep': 6} | {'no-unique-coverage': 2} |
| test_provider_tasks.py | 7 | 7 | 0.4 | {'keep': 7} | {} |
| test_pty_process.py | 6 | 7 | 0.0 | {'keep': 6} | {'skipped-here': 6, 'no-direct-assert': 2, 'waits/sleeps': 3} |
| test_qr_code.py | 18 | 24 | 1.5 | {'keep': 17, 'review-overlap': 1} | {'reads-example': 10, 'no-unique-coverage': 2} |
| test_qr_code_tex.py | 3 | 3 | 64.5 | {'rewrite': 3} | {'slow': 3, 'reads-example': 3, 'no-unique-coverage': 2} |
| test_qr_dialog_gui.py | 11 | 11 | 2.7 | {'keep': 9, 'review-overlap': 2} | {'reads-example': 8, 'no-unique-coverage': 2} |
| test_readability.py | 31 | 31 | 5.6 | {'review-overlap': 4, 'keep': 27} | {'no-unique-coverage': 5, 'legacy-compat': 1, 'skipped-here': 1, 'reads-example': 1} |
| test_readability_gui.py | 15 | 15 | 18.5 | {'keep': 14, 'review-overlap': 1} | {'slow': 3, 'no-unique-coverage': 3} |
| test_readability_tool.py | 8 | 8 | 2.5 | {'keep': 7, 'review-overlap': 1} | {'no-unique-coverage': 1} |
| test_release_notes.py | 8 | 8 | 1.1 | {'review-overlap': 4, 'keep': 4} | {'no-unique-coverage': 5} |
| test_render_evidence.py | 2 | 2 | 0.1 | {'keep': 2} | {'TeX': 1, 'no-unique-coverage': 1} |
| test_render_key.py | 22 | 22 | 7.5 | {'review-overlap': 3, 'keep': 19} | {'no-unique-coverage': 8, 'legacy-compat': 3} |
| test_render_lookup.py | 2 | 2 | 1.4 | {'keep': 2} | {'no-unique-coverage': 2} |
| test_render_scheduler.py | 18 | 18 | 2.3 | {'keep': 15, 'review-overlap': 3} | {'no-unique-coverage': 3, 'waits/sleeps': 3} |
| test_rerender_deck_gui.py | 5 | 6 | 29.0 | {'rewrite': 1, 'keep': 4} | {'slow': 2} |
| test_restore_version.py | 13 | 16 | 0.8 | {'keep': 6, 'review-overlap': 7} | {'no-unique-coverage': 9} |
| test_reveal_bar_gui.py | 36 | 36 | 24.8 | {'keep': 28, 'review-overlap': 8} | {'no-unique-coverage': 10, 'slow': 2, 'waits/sleeps': 3} |
| test_reveal_flag.py | 13 | 16 | 1.4 | {'keep': 12, 'review-overlap': 1} | {'no-unique-coverage': 2} |
| test_reveal_steps.py | 11 | 33 | 0.3 | {'keep': 9, 'review-overlap': 2} | {'no-unique-coverage': 4} |
| test_reveal_steps_tex.py | 5 | 5 | 187.6 | {'rewrite': 5} | {'slow': 5, 'no-unique-coverage': 3} |
| test_revealed_footnotes.py | 7 | 9 | 0.4 | {'keep': 7} | {'skipped-here': 5} |
| test_review_ai_backend.py | 2 | 5 | 0.2 | {'keep': 2} | {'no-unique-coverage': 1} |
| test_review_compiler.py | 3 | 6 | 0.5 | {'keep': 3} | {'TeX': 2, 'legacy-compat': 1} |
| test_review_gui.py | 4 | 6 | 9.7 | {'review-overlap': 1, 'keep': 3} | {'slow': 2, 'no-unique-coverage': 2} |
| test_review_persistence.py | 5 | 6 | 0.4 | {'keep': 5} | {'no-unique-coverage': 3, 'reads-example': 1, 'long': 1} |
| test_review_transcript_import.py | 11 | 19 | 0.9 | {'keep': 11} | {'reads-example': 1, 'no-unique-coverage': 3} |
| test_scan_cache.py | 7 | 7 | 0.3 | {'keep': 7} | {'no-unique-coverage': 1} |
| test_section_editor.py | 20 | 93 | 3.8 | {'keep': 16, 'review-overlap': 4} | {'no-unique-coverage': 10, 'legacy-compat': 1} |
| test_selection.py | 20 | 27 | 0.9 | {'keep': 15, 'review-overlap': 5} | {'no-unique-coverage': 6} |
| test_selection_tasks_gui.py | 21 | 22 | 27.4 | {'keep': 17, 'review-overlap': 4} | {'slow': 5, 'no-unique-coverage': 7} |
| test_settings_ai_gui.py | 12 | 12 | 4.0 | {'review-overlap': 4, 'keep': 8} | {'no-unique-coverage': 5, 'waits/sleeps': 1, 'legacy-compat': 1} |
| test_settings_deck_groups_gui.py | 18 | 20 | 2.2 | {'review-overlap': 3, 'keep': 15} | {'no-unique-coverage': 3} |
| test_settings_gui.py | 34 | 34 | 15.9 | {'review-overlap': 4, 'keep': 30} | {'waits/sleeps': 2, 'no-unique-coverage': 7, 'legacy-compat': 2} |
| test_shared_widgets_gui.py | 4 | 9 | 0.5 | {'keep': 4} | {'no-unique-coverage': 1, 'waits/sleeps': 1} |
| test_side_panels_gui.py | 69 | 74 | 47.6 | {'keep': 51, 'review-overlap': 18} | {'waits/sleeps': 4, 'no-unique-coverage': 32, 'legacy-compat': 2, 'slow': 9} |
| test_slide_add.py | 24 | 32 | 1.9 | {'review-overlap': 10, 'keep': 14} | {'no-unique-coverage': 14, 'reads-example': 1} |
| test_slide_branch.py | 6 | 6 | 0.3 | {'keep': 4, 'review-overlap': 2} | {'legacy-compat': 1, 'no-unique-coverage': 2} |
| test_slide_ids.py | 12 | 13 | 0.4 | {'keep': 10, 'review-overlap': 2} | {'no-unique-coverage': 2} |
| test_slide_list_gui.py | 54 | 62 | 2.8 | {'keep': 49, 'review-overlap': 5} | {'waits/sleeps': 9, 'no-unique-coverage': 15, 'legacy-compat': 1} |
| test_slide_notes.py | 12 | 14 | 0.4 | {'review-overlap': 2, 'keep': 10} | {'no-unique-coverage': 5, 'reads-example': 1} |
| test_slide_preview_cleanup.py | 5 | 5 | 0.2 | {'keep': 5} | {'legacy-compat': 1} |
| test_slide_search.py | 3 | 3 | 0.1 | {'review-overlap': 1, 'keep': 2} | {'no-unique-coverage': 1} |
| test_slide_usage.py | 7 | 7 | 0.5 | {'keep': 7} | {'no-unique-coverage': 1} |
| test_slide_versions_gui.py | 11 | 14 | 1.4 | {'review-overlap': 2, 'keep': 9} | {'no-unique-coverage': 2} |
| test_slug_collision.py | 6 | 6 | 0.4 | {'review-overlap': 1, 'keep': 5} | {'no-unique-coverage': 1} |
| test_sm_rename.py | 7 | 7 | 0.1 | {'keep': 6, 'review-overlap': 1} | {'no-unique-coverage': 1} |
| test_small_helpers.py | 3 | 3 | 0.0 | {'keep': 1, 'review-overlap': 2} | {'no-unique-coverage': 2} |
| test_smoke.py | 3 | 305 | 4.5 | {'keep': 2, 'drop-candidate': 1} | {'no-direct-assert': 1} |
| test_snippets.py | 5 | 5 | 0.1 | {'keep': 4, 'review-overlap': 1} | {'no-unique-coverage': 2, 'legacy-compat': 1} |
| test_source_freeze.py | 2 | 2 | 5.2 | {'keep': 1, 'review-overlap': 1} | {'slow': 2, 'reads-example': 2, 'waits/sleeps': 1, 'no-unique-coverage': 2} |
| test_source_indent_gui.py | 5 | 5 | 0.1 | {'keep': 5} | {} |
| test_source_view_gui.py | 32 | 32 | 3.1 | {'keep': 25, 'review-overlap': 6, 'rewrite': 1} | {'reads-example': 2, 'no-unique-coverage': 11, 'FAILED-in-run': 1, 'waits/sleeps': 4, 'legacy-compat': 1} |
| test_splash.py | 2 | 2 | 0.0 | {'keep': 1, 'review-overlap': 1} | {'no-direct-assert': 2, 'no-unique-coverage': 1} |
| test_stall_monitor.py | 4 | 4 | 1.0 | {'keep': 4} | {'waits/sleeps': 2, 'no-unique-coverage': 1} |
| test_status_trace.py | 1 | 1 | 0.0 | {'keep': 1} | {'TeX': 1} |
| test_step_renders.py | 8 | 8 | 2.2 | {'review-overlap': 3, 'keep': 5} | {'no-unique-coverage': 5, 'waits/sleeps': 5} |
| test_steps_edit.py | 19 | 21 | 0.9 | {'review-overlap': 7, 'keep': 12} | {'no-unique-coverage': 8} |
| test_stray_windows_gui.py | 3 | 3 | 2.0 | {'keep': 2, 'review-overlap': 1} | {'waits/sleeps': 2, 'no-unique-coverage': 2} |
| test_task_card_gui.py | 20 | 20 | 51.5 | {'keep': 12, 'review-overlap': 8} | {'slow': 13, 'no-unique-coverage': 10} |
| test_tasks.py | 34 | 55 | 1.1 | {'keep': 19, 'review-overlap': 15} | {'no-unique-coverage': 19, 'legacy-compat': 1} |
| test_tasks_gui.py | 58 | 58 | 121.3 | {'review-overlap': 23, 'keep': 35} | {'slow': 21, 'no-direct-assert': 4, 'no-unique-coverage': 29} |
| test_template_catalog.py | 15 | 22 | 2.5 | {'review-overlap': 1, 'keep': 14} | {'no-unique-coverage': 1, 'TeX': 2, 'reads-example': 1, 'skipped-here': 1} |
| test_templates.py | 10 | 11 | 0.5 | {'keep': 7, 'review-overlap': 3} | {'reads-example': 1, 'no-unique-coverage': 3} |
| test_terminal_draft.py | 5 | 5 | 0.1 | {'keep': 5} | {'legacy-compat': 1} |
| test_terminal_theme.py | 1 | 2 | 0.0 | {'keep': 1} | {} |
| test_tex_source.py | 5 | 5 | 0.1 | {'keep': 5} | {'reads-example': 1} |
| test_theme_sources.py | 14 | 27 | 3.2 | {'review-overlap': 5, 'keep': 9} | {'legacy-compat': 3, 'no-unique-coverage': 9} |
| test_theme_sources_gui.py | 11 | 12 | 75.5 | {'rewrite': 1, 'keep': 9, 'review-overlap': 1} | {'slow': 1, 'no-unique-coverage': 1} |
| test_theme_tokens.py | 4 | 6 | 0.1 | {'keep': 4} | {} |
| test_themes.py | 31 | 55 | 4.4 | {'keep': 20, 'review-overlap': 11} | {'no-unique-coverage': 14, 'legacy-compat': 3, 'TeX': 2, 'skipped-here': 1} |
| test_themes_gui.py | 6 | 6 | 0.4 | {'review-overlap': 2, 'keep': 4} | {'no-unique-coverage': 2} |
| test_tls_trust.py | 9 | 9 | 0.1 | {'review-overlap': 3, 'keep': 6} | {'no-unique-coverage': 3} |
| test_tool_guidance.py | 1 | 1 | 0.0 | {'keep': 1} | {} |
| test_topbar_tab_order_gui.py | 9 | 11 | 14.0 | {'keep': 8, 'review-overlap': 1} | {'waits/sleeps': 5, 'no-unique-coverage': 5, 'slow': 1} |
| test_transcript_conversion.py | 10 | 11 | 0.4 | {'keep': 8, 'review-overlap': 2} | {'no-unique-coverage': 3} |
| test_transcript_languages.py | 4 | 6 | 0.2 | {'keep': 2, 'review-overlap': 2} | {'no-unique-coverage': 2} |
| test_transcript_options.py | 7 | 7 | 0.1 | {'keep': 7} | {} |
| test_transcript_policy.py | 3 | 8 | 0.2 | {'keep': 3} | {'no-unique-coverage': 2} |
| test_transcript_preview_gui.py | 2 | 2 | 0.1 | {'keep': 2} | {} |
| test_translation_chip_gui.py | 2 | 2 | 1.9 | {'keep': 1, 'review-overlap': 1} | {'waits/sleeps': 2, 'no-unique-coverage': 2} |
| test_translation_groups.py | 25 | 25 | 1.9 | {'review-overlap': 8, 'keep': 17} | {'no-unique-coverage': 9} |
| test_translation_languages.py | 11 | 11 | 0.3 | {'review-overlap': 9, 'keep': 2} | {'no-unique-coverage': 9, 'legacy-compat': 3} |
| test_translation_placement.py | 8 | 19 | 6.8 | {'review-overlap': 5, 'keep': 3} | {'no-unique-coverage': 6} |
| test_ui_kit_gui.py | 22 | 25 | 1.0 | {'keep': 20, 'review-overlap': 2} | {'no-unique-coverage': 6, 'waits/sleeps': 5} |
| test_update_check_gui.py | 5 | 11 | 0.2 | {'keep': 5} | {} |
| test_updater.py | 10 | 10 | 0.2 | {'review-overlap': 2, 'keep': 8} | {'no-unique-coverage': 7, 'reads-example': 3} |
| test_updater_folder.py | 8 | 8 | 1.9 | {'review-overlap': 1, 'keep': 7} | {'no-unique-coverage': 1, 'legacy-compat': 5, 'waits/sleeps': 1} |
| test_version.py | 1 | 2 | 0.0 | {'keep': 1} | {} |
| test_view_themes.py | 8 | 8 | 0.1 | {'keep': 5, 'review-overlap': 3} | {'no-unique-coverage': 3} |
| test_wizard_portal.py | 5 | 5 | 0.3 | {'keep': 5} | {'legacy-compat': 1, 'waits/sleeps': 1} |
| test_workspace_state.py | 12 | 18 | 0.5 | {'keep': 12} | {'no-unique-coverage': 3} |
| test_workspace_window.py | 87 | 135 | 262.8 | {'keep': 61, 'review-overlap': 24, 'rewrite': 2} | {'slow': 10, 'no-unique-coverage': 53, 'legacy-compat': 5, 'waits/sleeps': 16, 'FAILED-in-run': 1} |