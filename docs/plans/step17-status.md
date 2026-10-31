# Step 17 status (2026-10-31, v10.17.0)

Done and committed on `claude/fw-step17-private-themes-687742`:
- App: `theme_sources.py`, Settings → Plugins → Themes "Add theme from GitHub…", per-row "Check for update" and
  last-failure line, start-up check under the update setting, offer with notes (Install now / Not now / Skip this
  version), `source.json`, previews of decks using the key replanned. Tests: `test_theme_sources.py`,
  `test_theme_sources_gui.py` (fake GitHub API), fixture `tests/fixtures/theme_package/sample-theme-1.0.0.smtheme`.
  Full suite: 3930 passed, 70 skipped; TeX tests of touched files: 115 passed.
- Docs: `docs/THEME_PACKAGE.md` (From GitHub, the token from GitHub's docs), README Themes bullet, CHANGELOG, version.
- Framework: catalog hook `\SMCardHeadingStyle` (setup), base points `\SMCardHeadingFont` at it; pins renewed.
- `tools/framework_regression.py` `extra_dirs` with a test.
- Theme: `D:/uniCLOUD/slidemage-theme-uni-graz/` commit `78419bc` (main, no remote); `dist/uni-graz-1.0.0.smtheme`,
  sha256 `72acac42101c5ff224d134a761a8d3440b32e34556a39fbd88c73dcdfc4a57c0`.

Regression:
- In-repo vs `repo-v1016`: 575 pages, all identical (`step17-repo-compare.log`).
- Theme folder vs `repo-v1015` @uni-graz (`private-uni-graz-v1017`, config
  `C:/Users/ms/SlideMage/regression/private-uni-graz-theme.json`): only 1pf (manual p6) and hd5 (copy p8-9), the
  step 16 change; images in `.regression/step17-images/`.
- Still running when the session stopped, read their logs: private set (`step17-private-compare.log`, config
  `private-step17.json` vs `private-v1014`) and the installed-package compile in a temporary config dir
  (`step17-installed-theme-compile.log`, baseline = the theme-folder run, expect "All identical").

Left: outward steps (create the private repo, the forking setting, push, tag and release), and checking the two logs.
