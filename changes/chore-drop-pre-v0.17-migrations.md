kind: fixed
reason: direct request: nothing older than v0.17 is migrated or tested any more

Removed the migrations of projects older than v0.17: the compat modules compat_bibliography, compat_citation_format, compat_color_cut, compat_color_roles, compat_hooks, compat_names, compat_own_theme and compat_project_macros and every registry entry before v0.17.20 in compat.py (a project last opened by such a version is no longer offered an update), diagnostics.remove_old_traces, preview_build.remove_legacy_wrappers and project.migrate_previews (the move of .previews/ into the cache). Removed 62 tests of pre-v0.17 formats and the two compat test files for them; jsonschema joins the dev extras so the plugin-catalogue schema tests run. Kept: the generic compat engine and its v0.17.20 entry, the settings, AI-route, plugin and presenter-profile readers of old formats, languages.migrate and the plugin-offer migration list (still wired into the UI; they need a separate pass).

NEW: Projects from before v0.17 are no longer updated automatically.
- Open them once in SlideMage v0.17 first; this version no longer offers the update for older projects.
