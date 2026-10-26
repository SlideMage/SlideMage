# Step 1a status (2026-10-26)

Branch `claude/fw-step1a-names-bee1b7`, two commits on top of `86ce5196`. Nothing pushed, no VERSION bump, no CHANGELOG.

## Done

- `a13eeaac`: all renames and the compat change `slidemage-names-and-setup-layer` (`src/slidemage/compat_names.py`,
  `since="v9.0.0"`, BREAKS). `compat.run_update` deletes files (`None` in the plan) and is all or nothing.
  Old env vars are ignored, logged once (stderr and the window log) and listed in the compat sheet and report.
  `preview_equivalence` pins are re-pinned (names and comments only changed); the stock Graz template, as the
  migration leaves it, is pinned too.
- `1c373ce1`: visible file names on manual slides 1cb, 1nz, 1d7, 1pf, hd5 (`-current` only) and snippets 1jv-1, 1y5-1.
  This is the only commit that changes rendered pages: 6 pages per manual deck (e.g. 5, 6, 19, 29, 60/61, 80/87 in
  `slidemage-manual`). Drop it with `git revert 1c373ce1` if pixel identity is wanted for the whole step.

## Verified

- pytest (`-n auto`): 3282 passed, one failure per run on a different load-sensitive test
  (`test_preview_requests::test_cache_identity_reads_the_raster_version_once`, `test_preview_queue::...no_check_starts...`);
  both pass alone. Two `test_templates` failures were real and are fixed.
- In-repo regression at `a13eeaac`: 12 entries, 1084 pages, 0 differences.
- Private regression at `a13eeaac` on `Slidemaster-copy-1a`, migrated by `compat_names`: 57 entries, 7160 pages, 0 differences.
- At `1c373ce1` the in-repo set differs on the pages listed above, as intended (diff images in `regression/repo/diff`).

## Migration on the private copy (what the real project will get)

Renamed (old file removed, backed up): `Slidemaster.bib`, `Slidemaster_project_macros.tex`,
`Slidemaster_preamble_{mci,uni-graz,uni-ibk}.tex` to the new names. Rewritten: `.latexmkrc`, `decks/.latexmkrc`,
18 decks in `decks/` (incl. `#workdeck.tex`, `#workdeck-mini.tex`), `.scripts/add_deck_headers.py`,
`.scripts/check_color_contrast.py`. Not touched: slides and frozen versions (about 200 hold only comments naming
`Slidemaster_preamble_base.tex`), the `R_Slidemaster` package, `.slidemage/*.json` (no file names in them).
The user must set `$SLIDEMAGE_LATEX` if they set `$SLIDEMASTER_LATEX` themselves.

## Remaining `slidemaster` hits

History (CHANGELOG, `docs/plans`, and the dated `docs/*PLAN*`/`STREAMLINING_*` files), the compat tables/tests,
the harness backward compatibility, the `R_Slidemaster` package path (`project.py`, `slide_ids.py`,
`slide_versioning.py`, `.gitignore`, tests, README), `RSlidemaster` and the real project's path in README, one slide
id in a base comment, frozen slide versions `1d7-v1-0-0` and `1pf-v1-0-0/v1-1-0`.

## Open

- Decide whether `R_Slidemaster` is renamed (project-side folder, not done).
- Older pinned Graz template variants (`fb8bcd1f…`, `13c039dc…`) are not re-pinned in their migrated form.
- Frozen slide versions still show old names on screen.

## Resume

```
PYTHONPATH="$(pwd -W)/src" C:/Users/ms/SlideMage/venv/Scripts/python.exe -m pytest tests -n auto
C:/Users/ms/SlideMage/venv/Scripts/python.exe tools/framework_regression.py compare tools/framework_regression_repo.json --out C:/Users/ms/SlideMage/regression/repo --jobs 4
C:/Users/ms/SlideMage/venv/Scripts/python.exe tools/framework_regression.py compare C:/Users/ms/SlideMage/regression/private-1a.json --out C:/Users/ms/SlideMage/regression/private --jobs 4
git grep -n -i slidemaster -- . ':!src/slidemage/CHANGELOG.md' ':!docs/plans'
```
