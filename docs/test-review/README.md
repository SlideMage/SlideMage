# Test review: inventory (2026-11-11, develop cc17f511)

Files: `test-inventory.csv` (one row per test function, 3377 rows = 4628 collected cases; filter by `verdict`/`flags`),
`per-file.md` (one row per test file). Open the CSV in Excel and annotate the `verdict`/`reason` columns.

## How it was made (and what it is not)
- Every test function was read mechanically (AST): name, line, size, parametrize count, marks, sleeps/waits, reads of `example`, TeX use.
  "Protects" = the docstring, else the test name (names are full sentences in this project).
- Full run with 8 workers and `--junitxml`: 4628 cases, 4536 pass, 84 skipped here, 3 fail + 1 setup error under load; 850 s summed
  (time per test is inflated by 8-worker load, use it for ranking only). A second run with per-test coverage contexts found, per test,
  the src lines no other test covers.
- **Verdicts are rule-based, not a line-by-line human read of 3377 bodies.** The rules: `ASK-drop` (benchmark tool tests, the user's call);
  `drop-candidate`; `rewrite` (failed under load, or >15 s per case); `merge` (>=4 tiny sibling tests); `review-overlap` (short test whose
  every covered src line is also covered by another test: a hint to look at its assertion, not proof of redundancy, mostly GUI/glue);
  everything else `keep`. Nothing was deleted.

## Result (per function)
keep 2683, review-overlap 641, rewrite 37, ASK-drop 11, merge 4, drop-candidate 1.

## Delete candidates (need the user's OK)
1. `tests/test_preview_bench.py` + `tests/test_preview_benchmark.py` (11 functions): only test `tools/preview_benchmark`/`preview_bench`. Drop together with the tool if the benchmark is finished.
2. `test_smoke.py::test_module_imports`: bare import smoke, every other test imports the modules (4 s).
3. `test_plugin_catalogue.py::test_multi_best_release_*` (4): merge into one parametrized test (not a delete of behaviour).
4. 641 `review-overlap` tests (CSV): only after a look at each; biggest groups `test_centre_gui` 30, `test_workspace_window` 24, `test_tasks_gui` 23, `test_side_panels_gui` 18.
5. 191 `legacy-compat` tests (migrations/old formats, e.g. `test_compat_*`, `test_languages` migrating): keep while old projects can occur; ask for a cut-off version.

## Rewrite (slow for what they guard, or flaky)
- `test_chat_gui::test_at_640px_every_suggestion_is_reachable...` 12 cases, 700 s summed (the single biggest cost; shrink the layout grid).
- `test_background_renders::test_a_real_background_render_creates_nothing...` 287 s (real TeX).
- 26 real-TeX tests of 18-88 s each (`*_tex.py`, `test_theme_sources_gui` add-from-github 74 s, `test_workspace_window` narrow top bar 52 s): put them behind one `tex` marker and share compiled fixtures.
- Load-flaky GUI (failed in the 8-worker run): both eraser-circle tests in `test_presentation_gui`, `test_workspace_window::test_a_typing_pause_renders_once...`, worker crash in `test_source_view_gui::test_a_slide_is_saved_as_you_type...`.
- 129 tests wait/sleep (flag `waits/sleeps`), 94 read the real `example` project (`reads-example`), 26 have no direct `assert` (helper-based; check the helper).

## Not covered
`tools/` regression configs (`framework_regression_repo.json`, `tools/preview_benchmark`) were not inventoried per test; they are not pytest tests apart from `test_framework_regression.py`.
