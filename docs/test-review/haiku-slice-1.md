# Test review, slice 1 (haiku)

Read-only review of the 37 test files in slice 1 (every test body read in full). Flags only where a concrete reason exists.
Test counts are test functions (`def test_`); parametrized cases are not counted separately.

| file | test | line | drop/merge/rewrite | reason | covering test |
|---|---|---|---|---|---|
| tests/test_ai_routes.py | test_registry_starts_empty | 20 | drop | Asserts `routes.all() == []` on a fresh registry, the same assertion as test_no_builtin_routes; the only extra is `get("missing") is None` | tests/test_plugin_ai_free_core.py::test_no_builtin_routes |
| tests/test_ai_routes.py | test_fake_route_can_script_provider_runner_and_surface | 165 | rewrite | Line 175 `fake.chat_surface() == "surface"` returns the lambda the test itself set; no src code runs, so it cannot fail from a src breakage. Keep the provider and task_runner asserts, drop the surface one | - |
| tests/test_batch_render.py | test_refresh_all_views_uses_saved_source_and_returns_statuses_only | 143-144 | drop (the `{'view': 'all'}` case) | The default view is "all" (src/slidemage/ai/tools/previews.py:60 `args.get("view", "all")`), so the `{}` and `{'view': 'all'}` parametrize cases make identical calls | same test, `{}` case |
| tests/test_plugin_credentials.py | test_the_file_is_owner_only | 56 | merge | Checks the same 0o600 mode as test_the_secret_is_owner_only_before_replacement, which asserts the final mode after two writes (line 82); only the `*.tmp` leftover check is extra and should move there | tests/test_plugin_credentials.py::test_the_secret_is_owner_only_before_replacement |
| tests/test_insert_popovers_gui.py | test_nothing_is_inserted_into_a_frozen_version | 167 | rewrite | Only asserts that no CitationPopover is visible. It never checks the frozen file's text or the editor's text, so an insert into the frozen version would still pass. Assert both are unchanged | - |
| tests/test_deck_language.py | test_links_with_wrong_language_or_self_reference_are_not_used | 105 | rewrite | Lines 111-112 assert `call.id == "aaa"`, which is also the result when a self-link is honoured (the EN row stays aaa), so they cannot tell the cases apart. Assert on `translation_group(ctx, "aaa-EN-One") == []` or badge `[EN]` instead | - |
| tests/test_deck_language.py | test_slidestep_slide_counts_as_used | 354 | rewrite | `not in unused` also passes if find_unused_slides returns nothing. Assert the file is among the project's slides and is not in the unused set | - |
| tests/test_wizard_portal.py | test_transparent_artwork_and_all_animation_phases_render | 82 | rewrite | Only asserts the corner pixel is transparent; a no-op paint_scene or a blank poses image passes. Add an assert that some pixel is painted for at least one phase | - |
| tests/test_centre_gui.py | test_an_unsaved_draft_offers_to_render_the_buffer_not_the_saved_file | 619-620 | rewrite (minor) | Line 620 repeats line 619 (`assert not preview._status_draft`) and its comment describes a different button; no extra coverage. Remove the duplicate | - |

Per file (test functions read, flagged):

- tests/test_centre_gui.py: read 120 tests, 1 flagged
- tests/test_deck_language.py: read 26 tests, 2 flagged
- tests/test_ai_switch_gui.py: read 24 tests, 0 flagged
- tests/test_compat.py: read 13 tests, 0 flagged
- tests/test_languages.py: read 20 tests, 0 flagged
- tests/test_render_scheduler.py: read 18 tests, 0 flagged
- tests/test_deck_in_several_groups.py: read 17 tests, 0 flagged
- tests/test_plugin_slides.py: read 15 tests, 0 flagged
- tests/test_ai_chat_service.py: read 15 tests, 0 flagged
- tests/test_compile_flow_gui.py: read 14 tests, 0 flagged
- tests/test_presentation_resume.py: read 13 tests, 0 flagged
- tests/test_ai_routes.py: read 13 tests, 2 flagged
- tests/test_plugin_credentials.py: read 12 tests, 1 flagged
- tests/test_reveal_steps.py: read 11 tests, 0 flagged
- tests/test_debug_instrumentation.py: read 11 tests, 0 flagged
- tests/test_deck_snapshot_gui.py: read 10 tests, 0 flagged
- tests/test_insert_popovers_gui.py: read 9 tests, 1 flagged
- tests/test_translation_placement.py: read 8 tests, 0 flagged
- tests/test_plugin_entry_points.py: read 8 tests, 0 flagged
- tests/test_commands.py: read 8 tests, 0 flagged
- tests/test_scan_cache.py: read 7 tests, 0 flagged
- tests/test_citations_gui.py: read 7 tests, 0 flagged
- tests/test_preview_requests.py: read 6 tests, 0 flagged
- tests/test_deck_settings_maintenance_gui.py: read 6 tests, 0 flagged
- tests/test_wizard_portal.py: read 5 tests, 1 flagged
- tests/test_source_indent_gui.py: read 5 tests, 0 flagged
- tests/test_presenter_paths.py: read 5 tests, 0 flagged
- tests/test_batch_render.py: read 5 tests, 1 flagged
- tests/test_plugin_ai_free_core.py: read 4 tests, 0 flagged
- tests/test_app_settings.py: read 4 tests, 0 flagged
- tests/test_slide_search.py: read 3 tests, 0 flagged
- tests/test_plugin_registry.py: read 3 tests, 0 flagged
- tests/test_about_gui.py: read 3 tests, 0 flagged
- tests/test_plugin_boundary.py: read 2 tests, 0 flagged
- tests/test_deck_new.py: read 2 tests, 0 flagged
- tests/test_status_trace.py: read 1 test, 0 flagged
- tests/test_open_path.py: read 1 test, 0 flagged

Totals: 37 files, 454 test functions read, 9 flagged rows (drop 2, merge 1, rewrite 6), across 7 files. No files left unfinished.
Note: test_presenter_paths.py calls `pathspecs`/`previous_tag`, which live in packaging/presenter_changed.py, not in src/slidemage; they were not treated as missing.
