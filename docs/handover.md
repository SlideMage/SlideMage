# SlideMage handovers

All handovers live in this one file, one section per topic. Each section starts with a level-one heading between two
horizontal rules, with its date and status under it, and stands on its own. Add a new section at the end; when a topic
is finished, say so in its status line rather than deleting it unless the user asks.

Sections:

1. Tabs in the centre column, and the Ollama update progress (open: steps 3 and 4)
2. Framework redesign (open: small items; the text also holds working rules)
3. Website session (open: small items; working notes)
4. Plugins status, from Jürgen (open: acceptance checks)
5. Citation formats on the website (open)
6. Footnote marker styles (open: the Graz theme)
7. SlideMage Presenter: things to watch (finished; reference)
8. Manual: the divider tks runs into the footer (open)
9. Debug log: what is left (plan finished; small items open)
9. Own slides: from per-slide layout numbers to the framework (open: batches B to F)
10. Render store cleanup (open: steps 4 and 5)

Sections 2 to 6 were folded in on 2026-11-02 from separate files: each starts with what is still open, checked that day
against the repositories, followed by the original text, which is older and whose own status lines may be out of date.

---

# Tabs in the centre column, and the Ollama update progress

Written 2026-11-01. Status: **open**. Steps 1, 2 and 2b merged; steps 3 and 4 and the checks below are pending. Nothing
is running, and no step may start without the user's go.

The authority is `docs/plans/centre-tabs.md` on develop (decisions in its section 6, step 2b in section 4b). This section
says where things stand and what to watch for.

## What is done

| What | Where | State |
|---|---|---|
| Step 1: tab strip; deck source, .bib, test-slides.tex as tabs | SlideMage/SlideMage#65, v0.13.14 | merged with `--admin` |
| Step 2: slides in tabs (search, Open in new tab, frozen versions) | SlideMage/SlideMage#68, v0.13.17 | merged with `--admin`, 9b32f1f8 |
| Step 2b: the side panels follow the tab on show, decisions D9-D12 | SlideMage/SlideMage#90, v0.14.3 | merged with `--admin` on 2026-11-03, conflicts resolved (see "Render store cleanup" for why three PRs collided on the version number) |
| Ollama update progress: bar and step text | SlideMage/slidemage-plugin-ollama#2, v1.0.2 of the plugin | merged 2026-11-01, released 2026-11-03 (tag v1.0.2) |

## Pending, in order

### A. Check what is already merged

Neither step has been opened in the real window, and #65 and #68 went in with no CI result. Before more is built on them:

1. Run the full suite on develop.
2. Make a local folder build (see "How to work" below) and try the tabs in it. Not seen yet: **deferred on the user's
   request (2026-11-04) — do this one next, not yet done**: the top bar's greyed-out Preview, Split and Details on a
   deck source or .bib tab; the frozen bar in a tab. ~~The scroll arrows with many tabs~~: **checked 2026-11-04** in the
   real window (installed `D:\SlideMage` v0.14.0, against the real Slidemaster project) — the strip compresses each
   tab's width instead of scrolling; got to 13 open tabs with no overflow and no scroll arrows ever appearing, so the
   compress-before-scroll design may mean arrows only show at a narrower window width or far more tabs than tried; not
   conclusively seen either way. ~~Ctrl+Tab with a real Ctrl release~~: **checked 2026-11-04** — sent as a single
   `ctrl+Tab` key combo twice (once after clicking a tab, once after clicking blank tab-strip space first), neither
   switched the active tab. Could be a real gap, or could be that a single synthetic combo doesn't reproduce "hold Ctrl,
   tap Tab, release Ctrl" the way a real keyboard does (this exact caveat was already flagged here) — try it by hand.
   Not seen yet: the new menu entries; Preview and Details of a slide tab. The Mac key bindings are untested. The strip
   itself was only rendered to images, in step 1's state.
3. Not tested: a slide tab whose file changes on disk while it is in the background. Switching back should use the same
   check as returning to any slide.
4. ~~The look: the slide tab has a grey background even when it is not active...~~ **Checked 2026-11-04** in the real
   window: inactive tabs are uniformly dark with no stuck-hover grey, only the active tab is distinct — matches intent,
   no fix needed. **Separately, on the user's direct instruction (2026-11-04): the active tab's underline is now the
   usual SlideMage blue** (`t.view_instructor`, the same blue the selected deck version/Instructor uses) instead of the
   generic dark `t.inverse` accent — `kit_qss.py`'s `QFrame#TAB[active="true"]` rule, one-line change, verified by
   generating the QSS and checking the rule contains `#3072c1`/`#6aa7f4`; not seen live (no running build had the edit
   — rebuilding a fresh folder build and finding it isn't registered with the computer-use permission system so it
   can't be clicked into was the blocker). **PR #94, v0.14.7, open, not merged** — flags its own version collision with
   #92 and #93 (both also took v0.14.6 independently); whichever of the three merges last will need renumbering, the
   same dance as #89/#90/#91 earlier.

**2026-11-03:** the full suite on develop gave 4467 passed and 4 failed: the two packed-fixture tests (fixed by #87, merged)
and two `test_ai_switch_gui.py` tests that pass alone. The installed `D:\SlideMage` is a build of v0.14.1, the same code as
develop, so the window checks are done there. Step 2b ran in a cloud session ("Tabs step 2b", branch `feature/tabs-step2b`)
and is **merged** (#90, v0.14.3, see below): not yet opened in the real window.

**2026-11-04, side note from the live check above:** opening the installed app against the real Slidemaster project and
then separately running from source against `example/` (to check the blue-underline edit) each triggered SlideMage's own
compat conversion of `media/alt-text.json`/`.csv` to the newer format on open — harmless and expected behavior, but it
left modified files in the working tree that had to be reverted before committing the unrelated color-tab change; watch
for this stray diff if you open a project with a newer SlideMage than last touched it.

### B. Step 2b: the side panels follow the tab on show — done, merged 2026-11-03 (#90, v0.14.3)

Details are in section 4b of the plan; the user accepted decisions D9 to D12. About 60 lines plus tests, one PR.

* `panels/base.py`: `_focused_row`, `id_slug`, `slide_path` and `deck_calls` are the one home of "the slide". A new
  `PanelActions.tab_slide()` returns `(path, row)` while a slide file tab is on show, else None, and then they work as
  today. `SidePanels` is built *before* the centre in `window.py` and its constructor refreshes, so the window's lambda
  must answer None while there is no centre. Default the field to "no tab" so that test fakes need no change.
* `side_panels.py`: `_panel_state()` gains the tab's path, and the centre's active tab connects to `_defer()`, so that a
  pending note is flushed against its own slide first. Going to a .bib tab gives the same state and rebuilds nothing.
* `centre.edit_slide_text(show=True)` (Save notes) stays when the tab on show has that path, instead of jumping to the
  slide tab and showing the wrong file there.
* `centre.restore_version`: from the Versions panel, it shows that file's tab if it has one.
* D10, Open buttons: Versions' Open of a frozen version always gives it a tab of its own. Language's Open of the other
  language gives it a tab while a slide tab is on show, else stays on the slide tab.
* D11: a rename keeps the tab. `_forget_missing_tabs` closes a tab whose file is gone, which today also hits Rename in
  Details (`details_view.py`) and Set language (`panels/language.py`). Add `CentreColumn.retarget_file(old, new)`, moving
  the tab and its hold. **This bug is live on develop.**
* D12: Ctrl+K's "Slide" group and the Slide menu keep acting on the slide list's selection. Check whether the Slide menu
  names the slide, as Ctrl+K's heading does. If it does not, tell the user.

### C. Step 3: context menu, keyboard order, restore at start

D5: a tab's right-click menu with Close, Close others, Close all to the right, Reveal in Explorer. Ctrl+PgDn / Ctrl+PgUp
in strip order. D7: restore the file tabs per project at start, in `layout_settings`, skipping missing files silently.
Also fix: quitting with a file tab on show makes the deck reopen in Source view, because `state.set_mode("source")` is
remembered for the deck.

### D. Step 4: docs

The manual slide on the workspace and the shortcuts dialog (`ui/dialogs/shortcuts.py`).

### E. Ollama plugin

#2 is merged, and v1.0.2 was released on the user's request on 2026-11-03 (annotated tag on the merge `10c2140`; the
release workflow published the `.smplugin` and `.sha256`). It was not tried against a real Ollama in the real app.

### F. A test suite clean-up, if the user wants it

These fail or wobble without the tabs, and each cost time in review:

* Fixed by #87 (2026-11-03): `test_citations.py::test_the_fixture_asset_is_the_packed_fixture_folder`, its theme
  counterpart in `test_theme_sources.py` (line endings), and `test_the_default_is_loaded_for_a_plain_deck_...` (wrapped log).
* `test_tasks_gui.py::test_a_translation_creates_the_partner_after_the_source_and_links_both` failed 12 of 24 runs on clean
  develop, on a `%% Included in decks:` header-sync race.
* `test_tasks_gui.py::test_two_clicks_start_one_task` failed once on clean develop.
* `test_tasks_gui.py::test_the_german_address_and_the_glossary_reach_the_request` fails about a third of runs, alone and on
  clean develop, with `RuntimeError: Signal ...`.
* Under `-n auto` only, passing alone: `test_centre_gui.py::test_an_unsaved_draft_offers_...`,
  `test_preview_requests.py::test_cache_identity_...`, `test_updater_folder.py`, `test_workspace_layout_fits_the_window`,
  `test_parallel_runs.py::test_a_batch_renders_its_views_at_once_and_keeps_their_order`,
  `test_reveal_bar_gui.py::test_the_stored_steps_are_read_and_decoded_off_the_gui_thread`,
  `test_background_previews_gui.py::test_the_chip_opens_the_status_window...`.
* **Not ruled out as caused by the tabs:** `test_reveal_bar_gui.py::test_a_current_stored_render_gives_the_steps_without_counting`
  failed in 2 of 3 full runs on the step 2 branch and 0 of 2 on develop, though it also failed once on the step 1 branch. It
  passes alone. Its error was never captured; capture it with `--tb=short` when it next fails.

## How to work

* Stop after each step and wait for the go: the user checks their usage between steps. Nothing is implemented without it.
* Each step gets a worktree and a branch from `origin/develop`. The main checkout stays on develop.
* Tests from a worktree must set `PYTHONPATH`, because the venv has slidemage installed editable from the main checkout:
  `PYTHONPATH="$(pwd -W)/src" C:/Users/ms/SlideMage/venv/Scripts/python.exe -m pytest tests -n auto`
* Local build: `SLIDEMAGE_BUILD=folder C:/Users/ms/SlideMage/venv/Scripts/pyinstaller.exe --noconfirm packaging/slidemage.spec`
* Version: bump the third number with each app-code commit, and append the CHANGELOG entry at the end. A second-number bump
  demands a BREAKING paragraph. **Other sessions merge often and the number was taken three times during this work: fetch
  right before pushing and again before merging, and merge develop in and renumber if it moved.** Check with
  `packaging/release_notes.py --previous <develop's> <yours>`. A number in a comment of a pinned `latex/` file is part of its
  hash: renumbering #59 broke `AUDITED_FRAMEWORK` in `preview_equivalence.py` (fixed in v0.13.19, #71). Run
  `tests/test_preview_equivalence.py` after any renumbering, and let a failed test stop the push.
* Another session may hold the same PR: on 2026-11-01 one merged #59 and removed its worktree during this work. Look at
  `list_sessions` before taking over a branch that has a session.
* Merges go through `gh pr merge <n> --admin --merge` on the user's say, as a bare command (the allow rule matches nothing
  else). Develop's ruleset blocks other merges.
* Sub-agents do implementation where that saves tokens. Tell them to commit as they go: a session limit stopped one, and its
  worktree was gone afterwards. Review what they report and rerun the tests: on step 1 a sub-agent's report said a citations
  test failed on develop, and the reason turned out to be the checkout's location; review also found real bugs in both steps.

## Loose ends

* None left: the old plan copy and the step worktrees were removed on 2026-11-02, and the main checkout is on develop.

---

# Framework redesign

Folded in 2026-11-02 from `docs/Handover_2026-10-26-Framework-Redesign.md`. Status: **open, small.** The redesign itself is complete and merged (PR #40, then #41, #44, #51, #53).

Still open:

* Stefan: v1.0.0 and renaming the repository to `SlideMage_pre_v1`, only when he calls a version stable. The plan's "fresh
  public repository" step is unclear now, as SlideMage/SlideMage is already public. Not verified.
* Stefan: the Graz theme's update check fails until his GitHub token gets Contents: Read-only on the private
  `slidemage-theme-uni-graz`.
* Minor: the items under "Loose ends" below (footer constants left internal, palette colours exempt from the catalog test).

Still useful below: "Rules that are not obvious" and "Machines, venv, regression data". "What is done" is history, and is
also in `docs/plans/template-owned-layout-and-own-theme.md` and `docs/plans/layout-from-metrics.md`.

## Original text

## Handover: framework redesign (templates own the layout, own SlideMage theme)

Updated 2026-10-31 evening (step 17c merged; the redesign is in develop, PR #40, merge `3ab6bd3d`; the real
project is migrated). Originally rewritten in full on 2026-10-29 (afternoon, machine `palans`); it
replaces all earlier versions of this file before that date. Specs:
`docs/plans/template-owned-layout-and-own-theme.md` (the main plan, steps 0-19) and
`docs/plans/layout-from-metrics.md` (the layout plan, steps 8-13, with "Done" notes per step and the user's
decisions), both on branch `dev-framework-redesign`. This handover is the state and the working rules.

### State

- **v10.19.0 is in develop** (2026-10-31, user: "push and merge it"): PR SlideMage/SlideMage#40 merged with
  `--admin`, merge `3ab6bd3d`; the main checkout `D:\uniCLOUD\SlideMage` is fast-forwarded to it. The branch
  `dev-framework-redesign` (pushed, worktree `fw-redesign`) is no longer where work goes: work continues on develop.
  Not released (no tag); the installed app at `D:\SlideMage` is still v9.4.x until a release.
- **Step 17c (v10.19.0) merged** before that: A `ff2b6b15` (`\SMBodyFontSize`, greyscale at 10pt via the catalog,
  private 57/7160 and repo 9/864 identical), B `f2c37515` (manual slides 1ym, 1im, 1nt, 1gr, 1rv, 1td, 1w4, 1uw;
  opt-in test `tests/test_manual_fits_templates.py`, `SLIDEMAGE_TEX_TESTS=1`, 0 findings under both templates;
  approved by the user), C `fbd6c075`+`261c0270` (1nz/2rg wording). Final compare against `repo-v10181`: only those
  slides differ (8 pages per version under SlideMage, 10 under greyscale).
- **Real project `D:\uniCLOUD\Slidemaster` migrated** (2026-10-31, user request): compat run with the develop code,
  214 files changed (backups `.slidemage\backups\2026-10-31_180434` and `_180436`), the Graz template's full citation
  format replaced by `\input{SlideMage_bibliography_default}`, 1uw's `gothamfloating...block` fixed by hand. Not
  committed in the project's git (the user had uncommitted changes there). See "Real project" below for the Graz
  theme question and the project's manual copy.
- **Step 18 decisions (user, 2026-10-31, in the plan):** full history as 0.x (v10.19.0 -> v0.10.19.0); stay in 0.x,
  next feature release v0.11.0, three parts, until the user calls a version stable; then v1.0.0, and the current
  repository is renamed `SlideMage_pre_v1` before a fresh public `SlideMage/SlideMage`. Order: develop first (done),
  then the renumbering on develop.
- **After step 18 (user, 2026-10-31), in this order, each on a branch off develop once step 18 is merged:**
  1. **Step 18b: the framework loads project macros.** `SlideMage_base.tex` loads `SlideMage_project_macros.tex`
     itself when a project has one (where the templates did: after the base, before the citation format); a
     compat entry removes `\input{SlideMage_project_macros}` from project templates (the real project's three:
     uni-graz, mci, uni-ibk); manual slide 1im's box 10 and docs updated. Then the real project drops its own
     `SlideMage_template_uni-graz.tex` and uses the GitHub theme (uni-graz 1.0.1, committed locally `87e4f81` in
     `D:\uniCLOUD\slidemage-theme-uni-graz`, packed in its `dist/`, not pushed or released: ask before pushing and
     releasing). Differences checked: the theme has dark mode (no project deck uses it) and lacks the macros line.
  2. **Step 18c: citation formats as a third category** besides themes and plugins. Decided: files are
     `SlideMage_citation_<key>.tex` (`SlideMage_bibliography_default.tex` renamed to `SlideMage_citation_default.tex`,
     the old name kept as a one-line file loading the new one); a catalog setting `\SMCitationFormat{default}`, a
     template may set another and a deck may override it before `\SMUseBibliography`, which loads the chosen file
     (templates then need no `\input` line); other formats come as packages like themes (`.smcite`,
     `citation.toml`, installed into the config folder and put on the TeX path, install from file or GitHub,
     update offers, a third website category).
- **Step 19 done 2026-11-01 (user approved the list):** redesign worktrees and local branches deleted (nine empty
  folders under `.claude/worktrees` stay until their idle sessions are archived), remote branches
  dev-framework-redesign/step18-renumber-0x/step18b-project-macros/step18c-citation-formats deleted, the stash
  `fw-redesign-sync-leftover-v941-theme-header` dropped, regression data deleted except
  `.regression\repo-v10190` and `C:\Users\ms\SlideMage\regression\real-v0120.json` (34 GB -> 41 MB), old app
  backups/builds in `C:\Users\ms\SlideMage` deleted (kept: `SlideMage-v9.4-folder-backup`, `ui-redesign-v8.20.0`,
  the venv), status notes removed (PR #53). The redesign is complete; v1.0.0 only when the user calls a version stable.
- **Done 2026-11-01 (night):** step 18c (v0.13.0, citation formats as a category: `\SMCitationFormat`,
  `SlideMage_citation_<key>`, `.smcite` packages like themes, `docs/CITATION_PACKAGE.md`, website handover
  `docs/Handover_2026-10-31-Citation-Formats-For-Website.md`; themes/citation packages may not shadow bundled files,
  the website's request) merged, PR #51; main checkout and installed app at v0.13.0. Graz theme 1.0.1 pushed and
  released (`SlideMage/slidemage-theme-uni-graz` v1.0.1 with package); the installed theme's `source.json` written
  by hand (release id 430240858), because the app's GitHub token cannot read the private repo: update checks for it
  fail until the user's token gets Contents: Read-only on that repository (owner SlideMage).
- **Done 2026-10-31 night:** step 18 (v0.11.0, PR #41) and step 18b (v0.12.0, PR #44) merged into develop; main
  checkout and the installed app `D:\SlideMage` at v0.12.0. Real project: compat removed the macros line from its
  three templates; its own `SlideMage_template_uni-graz.tex` moved to
  `.slidemage\backups\2026-10-31_graz-template-to-theme\`; Graz theme 1.0.1 installed from the local package into
  `%APPDATA%\SlideMage\themes\uni-graz` (from file, so no GitHub source link yet). Compare of all 15 project decks
  (45 versions, config `C:\Users\ms\SlideMage\regression\real-v0120.json`, theme as `extra_dirs`) against
  `.regression\real-v10190`: identical except the manual (newly synced). Command-line latexmk in the project does
  not see installed themes (its `.latexmkrc` adds only the framework and the project); the app does. Step 18c
  (citation formats, session `fw-step18c-citations`) running; it also takes the website's request from
  `docs/Handover_2026-10-31-Website-To-App-Theme-Checks.md` (themes.py must refuse a bundled layout profile copy).
- **Done 2026-10-31 evening:** the installed app `D:\SlideMage` is a local folder build of develop v10.19.0
  (self-test ok; old one backed up in `C:\Users\ms\SlideMage\SlideMage-v9.4-folder-backup`). The real project got
  the repo's current manual: 70 new and 59 changed files under slides/snippets/media plus `decks/slidemage-manual.tex`
  (the project had no manual edits of its own since importing it on 2026-10-11); `media/alt-text.json`,
  `alt-text.csv`, `qr-codes.json` merged per image (the project's `used_on` links kept); ids 1im and 1vw added to
  `slide_ids.csv`. Not committed in the project.
- **Current in-repo baseline `repo-v10190`** (at `6e6c3d9c`, marker `BASELINES-READY-v10190-repo`). `private-v1014`
  is valid up to 17c A; 17c B/C change manual slides only (the private set's manual entries would differ there).
- **Done and merged: steps 0-14, develop up to `f4f243df` (v9.3.0), v10.12.1** (the base's lowercase expl3 names
  `__smqr_`/`__sm_mlt_` renamed to `__SM_qr_`/`__SM_mlt_`, render identical), **v10.12.2** (the plugin API names the
  table environment), **v10.13.0** (step 13, merge `4fc76fcd`: the calibration tool and the layout checker check
  what actually compiled; slide 1ub's image-source line, which was below the page, is fixed), **and v10.14.0** (step
  14, merge `bd51c459`: the house citation format moves out of the SlideMage template into its own framework file
  `latex/SlideMage_bibliography_default.tex`; renders identically everywhere).
- **Current baselines: `repo-v1016`** (in-repo, at `28b1f569`, step 16 merged: 6 entries, the manual and its copy
  under the SlideMage template only, since the uni-graz entries left the repository; recorded 2026-10-31 from
  `.claude/worktrees/fw-baseline-v1016`, marker `BASELINES-READY-v1016-repo`), **`repo-v1015`** (12 entries at
  `d7e0c391`; its 6 `@uni-graz` entries are the baseline for the private uni-graz config
  `C:\Users\ms\SlideMage\regression\private-uni-graz-base.json`, whose template copy is in
  `C:\Users\ms\SlideMage\regression\uni-graz-template\` and project in `uni-graz-project\`; re-record it as its own
  set when the render changes) **and `private-v1014`** (ms's 57
  entries / 7160 pages at `7cf5c432`, after the develop v9.4 merge, 0 failed; config
  `C:\Users\ms\SlideMage\regression\private-v1014-base.json`, marker `BASELINES-READY-v1014-private`; step 15 left
  `latex/` untouched, so it stays valid). `repo-v1014` (12 / 1126, at `7cf5c432`) is outdated by step 15's manual
  slides; `repo-/private-v1013` and older are outdated by develop's `\href` change.
- **Develop merge `7cf5c432` (2026-10-31, develop v9.4.0-v9.4.1):** develop's `\SMHrefContent` (linked pictures
  without underline) landed in `SlideMage_base.tex` (pin renewed); `protected_regions.py` took develop's text with
  `SlideMage_base.tex`; LICENSE's new no-warranty paragraph says "SlideMage framework"; CHANGELOG has 9.4.0/9.4.1
  after 9.3.0, before 10.0.0. Suite 3832 passed.
- **Develop merge `fcd2b65b` (2026-10-29/30):** develop's CHANGELOG entries (8.x and 9.x) come first, then the
  redesign's 10.x; `VERSION_NUMBER` stays 10.x. Develop's names were renamed in the merge (`SLIDEMASTER_PROJECT/LATEX`
  -> `SLIDEMAGE_*`, `Slidemaster.bib` -> `SlideMage.bib`, `Slidemaster_preamble_` -> `SlideMage_template_`,
  `[gotham plain enumerate]` -> `[SMPlainEnumerate]`); develop's deletions (`claude_launch.py`, `course_schedule.py`
  and their tests, moved to the plugins) were accepted; compat `CHANGES` holds develop's `campusonline-plugin`
  (v9.0.0) and `ai-plugins` (v9.1.0) before the redesign's entries ("Newest last"); the base pin was renewed for
  develop's QR change. Suite after the merge: 3797 passed. When develop moves again, merge the same way.
  CHANGELOG.md has CRLF line endings: match conflict markers with `\r?\n` and write with `newline=""`.
- **The main checkout** `D:\uniCLOUD\SlideMage` is on develop; another session's worktree `agent-a529ad18e5c1d4f20`
  is on develop too. Leave both alone.
- **Stash** `fw-redesign-sync-leftover-v941-theme-header` (`2290bc7a`): a sync leftover set aside on 2026-10-28;
  obsolete (v9.4.1 was folded into the layout plan, and its branch `fw-redesign-conflict-copy-28170940` is gone).
  Drop it in step 19 or when the user agrees.
- No `(conflicted copy ...)` files are left under `.git` or `docs` (checked 2026-10-29), and
  `git fsck --connectivity-only` was clean on 2026-10-29 morning.

### Rules that are not obvious

1. **Never change `D:\uniCLOUD\SlideMage\latex` (the main checkout) or switch the main checkout to the redesign
   branch.** The user's real project `D:\uniCLOUD\Slidemaster` compiles against `../SlideMage/latex`. All work
   happens in worktrees under `.claude/worktrees/`. Untracked handover documents in the main checkout's `docs/` may
   be edited.
2. **Pause after every step.** Finish, verify, merge, report, wait for the user's "go".
3. **Merging:** the user approved merging each verified step branch into `dev-framework-redesign`, and merging
   develop into it. Never merge into develop and never push without asking. Before anything reaches develop, tell
   the user exactly what Info → Project compatibility will change in the real project (list below).
4. **Versions:** the redesign is 10.x.x (renumbered in step 11; steps 1-11 are v10.0.0-v10.10.0). Breaking steps
   get a `BREAKING:` paragraph on a minor bump (user: fine). CHANGELOG format `vX.Y.Z (date, reason): ...`, no
   parentheses inside the reason, then `NEW:` with `- ` bullets, then `BREAKING:` if needed. Check with
   `PYTHONIOENCODING=utf-8 PYTHONPATH=src <venv python> packaging/release_notes.py --previous v8.61.0 v10.X.0`.
   Every BREAKING release needs a `slidemage.compat.CHANGES` entry (`tests/test_compat.py` checks it).
5. **Naming:** every SlideMage TeX name is `SM` + CamelCase (macros, environments, counters `SM...Counter`, tikz
   styles, beamer templates, `\SM@...` csnames, expl3 `\g_SM_...`). Lua stays lowercase (`slidemage_measure`).
6. **Regression is the safety net.** A step renders existing decks identically with the same PDF font lists, unless
   the user approved the change with before/after images. A difference stops the step and goes to the user.
7. **Tests:** `PYTHONPATH="$(pwd -W)/src" <venv python> -m pytest tests -n 8` from inside the worktree (without
   `PYTHONPATH` the venv tests the main checkout). **Run the full suite after the step's CHANGELOG entry exists**,
   before merging (step 8 was once merged without, and a missing compat entry slipped through). GUI and process
   tests fail under compile load and pass alone (`test_preview_queue`, `test_preview_requests`,
   `test_accessibility_gui`, `test_topbar_tab_order_gui`, `test_ai_switch_gui`, `test_side_panels_gui`,
   `test_reveal_bar_gui`, `test_chat_gui`, `test_workspace_window`, `test_background_previews_gui`,
   `test_parallel_runs`, ...): rerun a failure alone before calling it real. Opt-in compile tests with
   `SLIDEMAGE_TEX_TESTS=1`; pre-existing failures there (also on older commits): `test_deck_snapshot` (3, incl.
   `test_real_omitslide_is_instructor_only[current|pinned]`) and `test_a_real_beamer_deck_is_read_slide_by_slide`.
   The venv needs `segno` 1.6.6 (in `uv.lock`).
8. **Preview-equivalence pins** (`src/slidemage/preview_equivalence.py`): every change to a pinned framework file
   needs a new pin from `preview_equivalence._digest(path.read_bytes())` (normalises CRLF; a plain sha256 is wrong).
   Follow `docs/PREVIEW_RENDER_EQUIVALENCE_CONTRACT.md`.
9. **Editing gotchas in the Bash tool:** heredocs, `sed` and `printf` lose or reinterpret backslashes (`\e`, `\f`,
   `\s`, `\i`, `\b`, `\n`). Write TeX and Python with the Write/Edit tools, or build backslashes with `chr(92)`. Use
   forward slashes in Windows paths inside Python (`C:/...`, not `/c/...`).
10. **Two machines, one `.git` in uniCLOUD** (`palans` and `ms`). Work on one machine at a time and let uniCLOUD
    finish syncing before switching. After a switch: look for `*conflicted copy*` under `.git` and `docs`, and run
    `git fsck --connectivity-only`. On 2026-10-27 a parallel commit on both machines left conflicted refs and three
    missing blobs (repaired). git also fails with "unable to create temporary file: Invalid argument" while the
    uniCLOUD client is not running (online-only placeholders in `.git/objects`).
11. **Sub-sessions:** steps go to sessions in their own worktrees (`use_worktree: true`,
    `source_branch: dev-framework-redesign`): Sonnet at high effort for well-specified steps, Opus (the user chose
    medium effort for step 10) for design-heavy ones. A session can only be started from a message the user typed in
    the desktop app: not over Remote Control, and not from a turn that a background task or another session started;
    a proposal card drops `source_branch`, so do not use cards for this. The brief carries the rules above, the
    regression commands with their own config and logs, "commit on your branch, don't push or merge, write
    `docs/plans/step<N>-status.md` if budget runs low". **Verify every result yourself** (harness logs, diff images,
    tests) before merging. The user may talk to a sub-session directly; read its transcript afterwards.

### Machines, venv, regression data

- **venv:** `C:\Users\palans\SlideMage\venv` on `palans`, `C:\Users\ms\SlideMage\venv` on `ms`.
- **Shared regression folder** `D:\uniCLOUD\SlideMage\.regression\` (synced, excluded from git through
  `.git/info/exclude` entry `/.regression/`; **never commit from it: private renders**):
  - `repo-v1012` (in-repo baseline at `f9fd72c2`, step 12 merged; 12 entries, 1126 pages, 0 failed, recorded on
    `ms` 2026-10-30 from `.claude/worktrees/fw-baseline-v1012`; marker `BASELINES-READY-v1012-repo`) - **current**,
    also valid for v10.12.1 (render identical).
  - `private-v1012` (ms's 57-entry private baseline at `f9fd72c2`, 7160 pages, 0 failed; config
    `C:\Users\ms\SlideMage\regression\private-v1012-base.json`; marker `BASELINES-READY-v1012-private`) -
    **current on `ms`**. It needs ms's project copy `Slidemaster-copy-s6`; `palans` has no baseline after the
    develop merge yet: record its 48-entry `private-v1012` from a detached worktree at `f9fd72c2` (or later) before
    comparing there.
  - `repo-v1011`, `private-v1011` (at `fcd2b65b`, before step 12), and `step12-images\` with step 12's logs.
  - `repo-v99`, `private-v99` (at `7c97584e`, valid up to v10.11.0 before the develop merge), outdated since the
    merge (develop's manual and QR changes alter the render).
  - `repo-v98`, `private-v98` (recorded on `ms` at `3088c4b9`; `private-v98` is ms's 57-entry set), outdated since
    step 10.
  - `step10-images\`, step 10's and step 11's logs.
- **Per machine** (configs and migrated project copies do not sync):
  - `palans`: `C:\Users\palans\SlideMage\regression\` (see its `README.txt`): `Slidemaster-copy` (pristine, never
    modify), `Slidemaster-copy-2b` (migrated, 16 decks, 48 entries, 5274 pages; its project macros carry an inert
    regression-only `\SMQRCode` stub), configs `private-vNN-base.json`, **current private baseline `private-v99`** at
    `7c97584e` (config `private-v99-base.json`, marker `BASELINES-READY-v99`), older `private-v96/v97/v98`, step 8/9
    images and logs.
  - `ms`: `C:\Users\ms\SlideMage\regression\` (copy `Slidemaster-copy-s6`, 57 entries, 7160 pages; configs
    `private-v98-base.json`, `private-v99-base.json`, `private-step10.json`, `private-step11b.json`). Its private
    baselines live in the shared folder (`.regression\private-v99`).
- **Never `pkill`/`taskkill` all `lualatex` processes** (step 11b's session did once while a baseline was recording;
  it was unharmed). Kill only your own task.
- **Commands** (from the worktree whose `latex/` you test; one harness run at a time; start long runs in the
  background and log to a file next to the folders):
  ```
  <venv python> tools/framework_regression.py record  <config> --out <dir> --jobs 4
  <venv python> tools/framework_regression.py compare <config> --out <dir> --jobs 4
  ```
  In-repo config: `tools/framework_regression_repo.json` in the tested worktree (about 5-8 min, longer under load).
  Private: copy the base config, point `"framework"` at the tested worktree's `latex/` (about 40-70 min). `compare`
  recompiles differing entries one at a time and prints FLAKY when they then match; a first pass can flag many
  entries under load (step 11: 30 of 48, all identical on recompile). **Record baselines only from a clean detached
  worktree** of the commit compared against (`git worktree add --detach .claude/worktrees/fw-baseline-vNN <commit>`),
  never from a worktree being edited. Re-record after any step that changes the render, and after a develop merge
  that touches `latex/` or `example/`. MiKTeX installs missing packages on demand, so a first run can fail on one.

### What is done

| Step | Merge / commits on dev-framework-redesign | Version | Result |
|---|---|---|---|
| 0 Regression harness | `86ce5196` | | `tools/framework_regression.py` |
| 1 Names, setup layer, catalog | `a13eeaac`, `1c373ce1`, `e226a71d` | v10.0.0 | SlideMage_* files, `latex/SlideMage_setup.tex` |
| 2 Content names, own theme | `18825d76`, `c2521b92`, `c3827f9f` | v10.1.0 | `latex/beamerthemeSlideMage.sty`, LPPL fork of Gotham |
| 3 Consolidation | `ca55ed8b` | v10.2.0 | each look defined once, in the theme |
| 4 Layout profiles | `bd8334d1` | v10.3.0 | `SlideMage_layout_fira.tex`, `\SMLayoutProfile` |
| 5 Values classified | `fb3c32e0` | v10.4.0 | catalog hooks, font numbers in the profile |
| 6 Margins for the tools | `e827817b` | v10.5.0 | PDF info keys; `check_layout.py` reads them |
| 7 lmsans, calibration, stress | `bd95097c`, `14c4aa12` | v10.6.0 | `SlideMage_layout_lmsans.tex`, `tools/calibrate_font_profile.py`, `tests/fixtures/template_stress/` |
| 8 Geometry from hooks | `be38b98e`, compat `332e75d9` | v10.7.0 | content top, title bar bottom, right edges derived |
| 9 Font measurements | `3088c4b9` | v10.8.0 | twelve profile numbers derived from the font |
| 10 Top placement measured | `7c97584e`, `9fddaf6d` | v10.9.0 | fixed pull-ups replaced by measurement |
| 11 Hooks mean their names | `9eb79f96` (`1e82d249`, `6066f0be`, `04260ccb`) | v10.10.0 | renumbering to 10.x; title-frame bottom pad; hook audit, geometry checks |
| 11b Hook renames | `9c04b963` (`f0b5cb81`) | v10.11.0 | two hooks renamed, three removed, compat `hook-renames-and-removals` |
| 12 Two Fira bugs | `f9fd72c2` (`2ea026f8`) | v10.12.0 | footnotes in revealed content covered; `columns[T]` below content keeps a list's gap; 38 manual slides lost hand-made space |
| expl3 names | `802e1481` | v10.12.1 | `__smqr_`/`__sm_mlt_` -> `__SM_qr_`/`__SM_mlt_`, render identical |
| Table name for plugins | `e105754d` | v10.12.2 | `plugin_api.TABLE_ENVIRONMENT = "SMTable"`, compatible addition to API 1 |
| develop merged in | `5e912d66`, `e70c73d5`, `cfed3c21`, `1d2e9350`, `fcd2b65b`, `7cf5c432` | | last: develop v9.4.1 (`6d1fbf8c`) |
| 13 Proof and tools | `4fc76fcd` (`88027d27`) | v10.13.0 | calibration tool and layout checker check what actually compiled; slide 1ub's image-source line fixed; stress deck's progress-bar-in-foot findings left open |
| 14 Bibliography file | `bd51c459` (`8ae20d07`) | v10.14.0 | `latex/SlideMage_bibliography_default.tex` (new, pinned); template says one `\input` line instead of carrying ~165 lines; optional compat change shortens a project's own old-style template; renders identically |
| 15 Documentation | `d7e0c391` (`84ebc2fb`) | v10.15.0 | new manual slides 1im (load order) and 1vw (making a template); 1ym, 1pf/hd5, 1gr, 1d7, 1uw, 1dt updated; README, PROJECT_OVERVIEW |
| 16 Templates out, theme packages | `28b1f569` (`d0c879ff`) | v10.16.0 | uni-graz template and institution screenshots out of the repo; `docs/THEME_PACKAGE.md`, `themes.py`, install from file, `tools/make_theme_package.py` |
| 17 Private themes | `6c32d21e` (`79d125b1`, `defe820e`) | v10.17.0 | themes from private GitHub repos with updates; `\SMCardHeadingStyle`; Graz theme repo v1.0.0 |
| 17b Test template | `07848c8d` (`47880c43`) | v10.18.0 | `latex/SlideMage_template_greyscale.tex`, profile `lmroman`, six catalog hooks, footnote signs the font has, checker and calibration-tool fixes |
| 17c Manual fits every template | `a309edc2` (`ff2b6b15`, `f2c37515`, `261c0270`) | v10.19.0 | `\SMBodyFontSize`; eight manual slides template-independent; 1nz/2rg wording; opt-in fit test |

Details per step: the "Done" notes in the two plans. Highlights the next steps need:
- **Step 10:** every top-aligned frame records its body origin and where a top-level list's first line would land;
  the common pull-up goes to `\jobname.top` (Fira 11.6007pt). The reference line is a list's first line, not a plain
  paragraph (deviation from the plan, explained there). `[c]` frames keep no pull-up but a first `columns` keeps
  its measured correction; `\SMAutoTopMarginfalse` now places frames like `\SMManualTopMargin` instead of switching
  the measurement off. No deck needs extra LaTeX runs. The plan's step 10 notes record a probe macro step 12 can
  reuse.
- **Step 11:** `\SMTitleframeBottomPad` = space from the bottom of the last subtitle line's box to the title box's
  bottom edge (default 8.505pt, render identical). The base writes every geometric hook into the PDF info;
  `check_layout.py` has checks `edge` and `titlepad`; `tests/test_hook_geometry.py` (opt-in) measures every catalog
  length or lists why not. `check_layout.py` on the calibration deck: 10 / 6 / 6 exemptions (stress / fira /
  lmsans).
- Optional theme features (all off by default, switches at the end of `SlideMage_setup.tex`): mini frames
  `\SMMiniFramesPosition`, progress bar `\SMProgressBarPosition`, divider slides `\SMDividerFrames`/`\SMDividerLook`,
  watermark `\SMWatermarkDefault`. The stress deck switches them on; the manual does not document them yet (step 15).

### User decisions (all recorded in the plans)

- Plain `\begin{frame}` lists get SlideMage's bullets (v10.2.0).
- A template only picks a layout profile or ships its own; it never overrides a single profile value. `lmsans`
  ships to users.
- The layout plan (`layout-from-metrics.md`) approved 2026-10-28 with its five proposed answers: sub-point shifts
  from deriving values are accepted once shown with before/after images; `\SMFootlineVOffset` derived with
  `\SMFootnoteFooterGap` as the hook; `\SMTitleframeBottomPad` changed its meaning with a recomputed default;
  step 12's bug fixes are made now (affected slides listed with before/after images).
- Approved visible changes: v10.7.0's sub-point shifts (incl. second-order moves on 12 real-project slides), the
  footer number's advance box on the edge; v10.8.0's list shifts (lists not at 10pt, -1.4 to +2.6pt, 18 real-project
  slides); v10.9.0's `columns[T]` fix.
- Step 11's questions: the bottom pad stays measured from the last line's box (the user said "Do 1"; read as keep);
  BREAKING on minor bumps is fine; no theme LPPL item for step 11.
- The theme's LPPL Current Maintainer is Stefan Palan.
- Versions move to 10.x (done); later step 18 re-designates all history to 0.x and starts the public repository at
  v1.0.0 (see below).
- Theme packages for the website catalogue: main plan section 8 (`.smtheme` zip with `theme.toml`, installed to
  `config_dir()/themes/<key>/`; private themes never in the catalogue); define by step 16 and tell the website side.
- Step 15 adds manual appendix slides "What a compile reads, in order" and "Making a template".
- Uni Graz becomes a private theme repository shared with Jürgen; Uni Innsbruck and MCI stay local project
  templates (step 17).

### Next

1. **Step 11b, v10.11.0: done and merged 2026-10-29 evening (`9c04b963`).** Results: the two renames done (PDF info
   keys follow); `\SMRightFooterPadding` removed (its `\hspace` and its term in `\SMFooterRightShift`);
   `\SMFootlineHeight`/`Depth` were not fully inert (the two `mini nav progress` templates read them), so they are
   theme-internal `\SM@footlineheight` (1.5ex) / `\SM@footlinedepth` (0.1ex) now, no longer hooks; the five old names
   raise a package error in `SlideMage_setup.tex`; compat `hook-renames-and-removals` in
   `src/slidemage/compat_hooks.py` (`migrate` renames in templates, profiles, macros; `detect` reports the rest); pins
   renewed. Verified: in-repo 12 / 1084 and private (ms, 57 / 7160) identical to v99; `check_layout.py` 0 findings,
   10 / 6 / 6; suite 3439 passed on the merged tree (GUI flakes pass alone); TeX tests only the known failures.
   The original brief, for reference: rename `\SMProgressStripHeight` ->
   `\SMProgressStripRoom` and `\SMSideFootnoteTopSep` -> `\SMSideFootnoteTitleBlockSep`; keep
   `\SMFrametitleBottomPadding`; remove `\SMFootlineHeight`, `\SMFootlineDepth`, `\SMRightFooterPadding` (they move
   nothing). Brief for a Sonnet session (high effort): rename everywhere (catalog, base, theme, profiles, stress
   template, `check_layout.py`, `calibrate_font_profile.py`, `test_template_catalog.py`, `test_hook_geometry.py`,
   README, plans) with catalog comments that say exactly what each does; replace the removed hooks' uses so the
   render stays identical (keep one if it moves something after all, and report); a LaTeX error when a template sets
   an old or removed name (pattern of step 8's guard); a compat entry for v10.11.0 whose `migrate` renames the two in
   project templates (idempotent) and whose detector reports the three removed ones, with tests; CHANGELOG with
   `BREAKING:`; pins; the layout plan's step table (12/13 become v10.12.0/v10.13.0) and "Done" notes; full suite
   after the CHANGELOG; `check_layout.py` 10 / 6 / 6 or fewer; both harness sets identical against `repo-v99` and
   `private-v99` (on `palans`; copy `private-v99-base.json` to `private-step11b.json`), logs
   `step11b-*-compare.log`, images on any difference to `.regression\step11b-images\`. Merge develop in first if
   the user wants the redesign current (then re-record baselines).
2. **Step 12, v10.12.0: done and merged 2026-10-30 (`f9fd72c2`).** The user decided its options in the session
   `fw-step12-bugs`: a `\source{}` after a `\pause` appears with the last step, the "Image source(s)" line shows on
   every step, `columns[T]` below content gets option (a), a list's gap. Real project: 34 course slides now hide a
   footnote until its content appears (list in the layout plan's "Done" note); the project's own copy of the manual
   shows the column shift without the fit edits, so its full slides overflow until it gets the updated manual
   slides. Found on the way, for step 13: 1ub's "Image source(s)" line sits below the page (older than step 12), and
   `check_layout.py` cannot see text inside or below the footer.
3. **Step 13, v10.13.0: done and merged 2026-10-30 (`4fc76fcd`, step branch `88027d27`).** `calibrate_font_profile.py`
   is now a check that follows what actually compiled (a template's `\renewcommand` override, not just the catalog's
   default) instead of the catalog's own default; its label-gap check no longer mismatches a frame's own title text
   as a list label. `check_layout.py` now sees text an overfull frame pushes into or under the footer box (the step
   12 gap), and its logo-detection window now reads `\SMLogoHeight` instead of a flat 20pt guess (was blind to the
   stress-test template's taller calibration logo). Found and fixed this way: slide 1ub's "Image source(s))" line was
   below the page (a 12-item list's column was too narrow, now 0.52/0.45 instead of 0.59/0.38; only this one slide
   changes anywhere, verified by regression). `test_template_catalog.py` gained three checks (allowed profile font
   names, no template sets a profile-owned name, every geometric hook has a `test_hook_geometry.py` entry). The
   calibration deck is clean under all four profile/template combinations (0 findings, 6/6/10/10 exemptions). Left
   open, documented in the layout plan's Done note: the stress deck's progress-bar-in-foot feature (off by default,
   unused by the real project) still has real `check_layout.py` findings under the stress-test template. Verified:
   full suite 3806 passed (one unrelated, pre-existing GUI-test flake confirmed on the clean branch tip too, not a
   regression); in-repo regression 12/1126 pages, exactly 1 page differs per entry (slide 1ub only); private
   regression 57/7160 pages, 0 differences. No compat entry (not breaking), no pin changes.
4. **Step 14, v10.14.0: done and merged 2026-10-30 (`bd51c459`, step branch `8ae20d07`).** The house format moved
   from `latex/SlideMage_template_slidemage.tex` into the new, pinned `latex/SlideMage_bibliography_default.tex`;
   the template now says `\input{SlideMage_bibliography_default}` instead of carrying it. `bibliography_house.py`'s
   old `BLOCK` is now `FULL_TEXT` (kept for recognizing a pre-v10.14.0 literal copy); the new `BLOCK` is the one
   `\input` line. `compat_bibliography.py`'s existing change accepts either form as "ready"; a new, separate,
   optional change (`bibliography-default-file`) offers to shorten a project's own institution template still
   carrying the full copy (`example/SlideMage_template_uni-graz.tex` is deliberately left on the full copy as a
   live example). Not breaking. Verified: full suite 3813 passed, 0 failed; in-repo (1126 pages) and private (ms,
   7160 pages) regression both 0 differences against `repo-v1013`/`private-v1013` — expected, this step only moves
   where the format's text lives.
5. **Step 15, v10.15.0: done, approved by the user and merged 2026-10-31 (`d7e0c391`, step branch `84ebc2fb`,
   session `fw-step15-docs`).** New appendix slides **1im "What a compile reads, in order"** (12-box TikZ load-order
   diagram, verified against the `\input`s: deck, template, setup, which loads the layout profile, then the theme,
   then defines the catalog, then the template's settings, base with the two Lua files, project macros, bibliography
   file, slides) and **1vw "Making a template"** (minimal template snippet `snippets/1vw-1.tex`, rules, profiles,
   the four optional theme features), in English only. Changed: 1ym (no Gotham), 1pf and German hd5, 1gr and 1d7
   (`\SMAutoTopMarginfalse` places frames like `\SMManualTopMargin`), 1uw, 1dt, snippet 1y5-1 (`\SMUseBibliography`),
   comments in 1xf/2v9; README (directory layout, load order, making a template), `docs/PROJECT_OVERVIEW.md`. No
   `latex/` change, no screenshots needed. Verified: only the manual's changed and new slides differ (plus frame
   numbers after the insertion and the appendix agenda); the harness's recompile pass crashed on a locked file in
   `.regression\repo-v1014\work` (WinError 32), so its summary line is missing; check_layout no new findings; suite
   3831 passed (2 GUI flakes pass alone).
   **Loose end from it:** `check_layout.py` did not flag a bullet an early 1gr draft pushed under the footer,
   although step 13 was meant to make it see text in or under the footer. Look into it in a later step.
6. **Step 16, v10.16.0: done, approved by the user and merged 2026-10-31 (`28b1f569`, step branch `d0c879ff`,
   session `fw-step16-themes`).** The user decided the theme package: the plan's section 8 proposal. Removed from the
   repository: `example/SlideMage_template_uni-graz.tex`, `example/schemes/scheme_uni_graz/`, the uni-graz/uni-ibk/mci
   screenshots (copy in `C:\Users\ms\SlideMage\regression\uni-graz-template\`; the real project has its own). Slides
   1pf/hd5 (and 1pf's frozen v1-0-0/v1-1-0, whose images were gone) show the SlideMage and the stress-test template.
   Tests use `tests/fixtures/template_acme/`. Theme packages: `docs/THEME_PACKAGE.md`, `src/slidemage/themes.py`
   (installed themes on TEXINPUTS for compiles and previews, after project and framework; template pickers list them;
   snapshots and Export LaTeX include their files; Settings -> Plugins: Install from file takes `.smtheme`, Themes list
   with Remove), `tools/make_theme_package.py`. No compat entry. Verified: suite 3888 passed; private 57/7160
   identical; manual changes only on 1pf/hd5 (also under the private uni-graz copy). Website side told in
   `docs/Handover_2026-10-31-Theme-Package-For-Website.md` (main checkout, untracked).
   **Loose ends from it:** one comment in `example/.latexmkrc` still names an institution (pinned file every project
   carries; change it with the next real `.latexmkrc` change); the harness cannot add the stress-test template to a
   run (a `template` entry only swaps the `\input` key; needs an `extra_dirs` option, useful for step 17b); **the
   manual's during-course view is not deterministic on slides 2v9 and 1vn** (sub-0.05pt shifts, reproduced on the
   baseline commit `d7e0c391` against its own baseline, so not caused by step 16); expect them in compares.
7. **Step 17, v10.17.0: done and merged 2026-10-31 (`6c32d21e`, step branch `79d125b1`/`defe820e`, session
   `fw-step17-private-themes`).** User decisions: the Graz theme repository is private in the `SlideMage` org;
   Jürgen (`JuergenFleiss`, active org member, org default permission read) reads it without an invitation and
   proposes changes as pull requests from a fork (org and repository allow private forks; free plan has no branch
   protection for private repositories, so no write access); the user maintains it. App: `theme_sources.py`,
   Settings -> Plugins -> Themes "Add theme from GitHub...", update check at start under the update setting with
   Install now / Not now / Skip, `source.json`, quiet failures; token = the updater's `github_token`;
   `docs/THEME_PACKAGE.md` has the token instructions from GitHub's docs (fine-grained, resource owner `SlideMage`,
   Contents: Read-only; **the org requires owner approval of each fine-grained token by default**: the user approves
   Jürgen's under the org's Settings -> Personal access tokens -> Pending requests). Framework: new catalog hook
   `\SMCardHeadingStyle` (the base's `\SMCardHeadingFont` follows it), so the Graz template no longer sets a profile
   value; pins renewed; render identical. `tools/framework_regression.py` has `extra_dirs`. Verified: suite 3930
   passed; in-repo identical to `repo-v1016`; private 57/7160 identical to `private-v1014`; the Graz theme folder
   (config `C:\Users\ms\SlideMage\regression\private-uni-graz-theme.json`, set `.regression\private-uni-graz-v1017`)
   differs from `repo-v1015`'s `@uni-graz` only on 1pf/hd5 (step 16); the installed package compiles identically to
   the folder. **Theme repository:** local `D:\uniCLOUD\slidemage-theme-uni-graz` (`dist/` git-ignored), remote
   `SlideMage/slidemage-theme-uni-graz` (private), `main` at `78419bc`, release `v1.0.0` with
   `uni-graz-1.0.0.smtheme` + `.sha256` (SHA-256 `72acac42...`, matches the local build); the user created, pushed
   and released it. `requires_slidemage = ">=10.17"`, so nobody can install it before the redesign is released.
   **Still open:** the real project's own Graz copy can go once the theme is installed there from the repository
   (ask the user first); Innsbruck and MCI stay local project templates.
8. **Step 17b, v10.18.0: done, approved by the user and merged 2026-10-31 (`07848c8d`, step branch `47880c43`,
   session `fw-step17b-test-template`).** The user's test template: `latex/SlideMage_template_greyscale.tex` (key
   `greyscale`; Latin Modern Roman via the new profile `latex/SlideMage_layout_lmroman.tex`, made by
   `tools/calibrate_font_profile.py --new` alone; greys only, light title bar, dark footer; en-dash bullets, numbered
   footnotes; taller title bar and 11pt footer; SlideMage logo with more padding; 1cm margins; catalog settings
   only, commented as a starting point; listed in the app, exported, pinned, in the in-repo regression config).
   Framework findings, each a new catalog hook with today's value as default: `\SMBulletSymbol`,
   `\SMFootnoteMark`, `\SMStandoutTextColor`, `\SMHighlightTitleTextColor`, `\SMAlertTextColor`,
   `\SMProgressBarColor`; and Latin Modern lacks five currency signs, so footnotes 3-7 had no marker under `lmsans`
   since v10.6.0: the theme now uses only the signs the font has (Fira unchanged). Calibration tool: `--new`, the
   footer-centering check no longer fooled by a grey footer, foreign fonts reported. `check_layout.py`: sees text
   pushed into or under the footer or off the page (step 15's gap; 18 more overfull slides under greyscale), and
   no longer flags a side image's own drawings. Verified: in-repo identical except 1vw (now names the greyscale
   template); private 57/7160 identical; suite passes; calibration deck 0 findings under greyscale, stress and
   SlideMage+lmroman. **Left for the user:** 43 manual slides overflow under greyscale (fixed-width drawings,
   screenshots of the SlideMage look, 1nz/2rg describe the currency-sign markers, 1gr draws a dark bar): list in
   `.regression\step17b-images\b-manual-content\findings.txt`; making the manual template-independent would be its
   own task.
   **v10.18.1 (`e5751aac`, user request "for the time being"):** the greyscale template sets the body sizes to
   beamer's 10pt ones (redefines `\normalsize`, `\small`, `\footnotesize`, `\scriptsize` after the base; titles and
   footer unchanged), a stopgap commented as such until the catalog gets a body-size setting. Manual under greyscale:
   14 findings per version instead of 79; left: 1ym, 1nt, 1im (fixed-width or fixed-position drawings), 1rv, 1td,
   1w4, 1uw (still too full). SlideMage-template decks unchanged; pin renewed; suite passes.
9. **Step 18: only on the user's explicit authorization, not even preparation.** All versions so far get a leading
   0 (v10.1.12 -> v0.10.1.12, as I read the user's example); the public repository `SlideMage/SlideMage` is cut
   fresh (one initial commit) and versions go on from v1.0.0; the full history moves to the private repository
   `SlideMage_pre_v1` (the user and Jürgen). The plan lists what the code needs (four-part CHANGELOG entries,
   project.json versions, compat `since` values, the update check that never offers 1.0.0 to an older build,
   release tags). Open then: whether the history CHANGELOG ships in full; the order of the repository move.
10. **Step 19, last:** clean up everything no longer needed (worktrees, branches, the stash, regression data,
   temporary and build files, finished handovers); list it and ask before deleting what cannot be recreated.

### Project compatibility for the real project (tell the user before anything reaches develop)

The real project `D:\uniCLOUD\Slidemaster` is not migrated. When the branch goes to develop, the user runs
Info → Project compatibility once. Entries of the redesign (`src/slidemage/compat*.py`):
- `slidemage-names-and-setup-layer` (v10.0.0) and `own-theme-and-content-names` (v10.1.0): on the regression copy
  they renamed 3 templates, `SlideMage.bib` and the project macros, and rewrote 20 decks, 174 slides, 3 snippets and
  a few scripts; one line of slide 1uw (`gothamfloating...block` in prose) needs a hand fix. Frozen slide versions
  are migrated too; editor backups are skipped.
- `derived-layout-names` (v10.7.0), `font-measurements-derived` (v10.8.0), `top-pullups-measured` (v10.9.0),
  `titleframe-bottom-pad` (v10.10.0, APPEARANCE): report project templates/profiles that set now-derived or
  re-defined names; none of the real project's templates sets any (checked on the copy).
- `hook-renames-and-removals` (v10.11.0): renames `\SMProgressStripHeight`/`\SMSideFootnoteTopSep` in project
  templates, profiles and macros; reports `\SMFootlineHeight`, `\SMFootlineDepth`, `\SMRightFooterPadding` (none set
  in the real project).
- No compat entries for v10.12.0-v10.13.0, but step 12 changes the look: 34 course slides hide a footnote until its
  content appears, and the project's own copy of the SlideMage manual shows the `columns[T]` shift without the fit
  edits (full slides overflow, 1be's footnote below the page) until the project gets the updated manual slides.
  Step 13 (v10.13.0) only touches the SlideMage manual's own slide 1ub (an example slide, not a tool other projects
  carry), so it needs the same "get the updated manual slides" step and nothing else; so does step 15 (v10.15.0,
  manual slides only, including the new 1im and 1vw) and step 16 (v10.16.0: 1pf/hd5 pictures; the SlideMage app no
  longer ships the uni-graz template, but the real project carries its own, so nothing breaks). Plugins: the user needs Claude
  plugin v1.0.3 and CampusOnline v1.0.1 or later with the redesign.
- `bibliography-default-file` (v10.14.0, LAYOUT, optional): offers to replace a project's own institution template's
  full copy of the house citation format with `\input{SlideMage_bibliography_default}`; not breaking either way
  (the full copy keeps compiling), so this is a convenience, not something the real project must act on.

### Loose ends

- Items left internal in step 5 because their class was unclear: the footer's `2em`/`-4em`/`0.4ex`, the side-footnote
  offsets `+2.1pt`/`+3.1pt`/`-2.31pt`, `\SMFloatingInfoblockRightAlign`/`TopAlign`, `\SMSectionframeBarBottom`.
- Palette colours `c_tertiary_*`, `c_custom_green/brown`, `c_secondary_yellow` are used only by slides (manual 1pf);
  the catalog test lists them as exempt.
- Commit `87644490` (step 2b) says v10.0.0 in its subject; after the renumbering step 2b is v10.1.0.
- **Plugins and the old names: fixed, PRs open** (2026-10-30). Both fixes work with develop's v9.x and the
  redesign; plugin tests pass against both (the Claude plugin's 10 hook-test failures against the main checkout's
  develop fail the same without the change):
  - Claude plugin `D:\uniCLOUD\slidemage-plugin-claude`, branch `fix/slidemage-env-names`, `2f90c15`, v1.0.3: the
    terminal sets `SLIDEMAGE_PROJECT` (read from v10 on) and `SLIDEMASTER_PROJECT` (before). Without it the hook
    under v10 falls back to the working folder.
  - CampusOnline plugin `D:\uniCLOUD\slidemage-plugin-campusonline` (cloned 2026-10-30), branch
    `fix/slidemage-names`, `c099cc6`, v1.0.1: the sessions table uses
    `getattr(plugin_api, "TABLE_ENVIRONMENT", "gothamtable")` (SlideMage v10.12.2 adds the name). The first version
    imported `slidemage.compat_own_theme`, which the plugin's `build.py --check` forbids (only `slidemage.plugin_api`
    is allowed); CI passes now. Deliberately not a version check, since step 18 renumbers.
  - Ollama plugin (cloned to `D:\uniCLOUD\slidemage-plugin-ollama`): no old names.
  - Pushed with the user's OK on 2026-10-30: PRs SlideMage/slidemage-plugin-claude#3 and
    SlideMage/slidemage-plugin-campusonline#1, merged by the user 2026-10-30 (local `main` pulled), and released on the
    user's request the same day: tags `v1.0.3` (Claude) and `v1.0.1` (CampusOnline), lightweight on the merge commit
    like earlier tags; the release workflows published the `.smplugin` and `.sha256` files. The website's scheduled
    catalogue job picks them up.
- Develop still has the lowercase `__smqr_` names. When develop is merged in again and touches `\SMQRCode`, keep the
  redesign's `__SM_qr_` names in the resolution and rename any new lowercase ones.
- Cleanup candidates (step 19, or earlier with the user's OK): worktrees `fw-baseline-2b`, `-v96`, `-v97`, `-v98`,
  `-v99`, `-v1011` (keep `-v1012` while it is the baseline), `fw-check-4`, `fw-check-5`, `fw-step5-...`,
  `fw-step8-...`, `fw-step9-...`, `fw-step10-...`, `fw-step11-...`, `fw-step11b-...`, `fw-step12-...`, their merged
  `claude/fw-*` branches (also `fw-step3`, `fw-step4`, `fw-step7` without worktrees), the stash above, outdated
  regression folders (`repo-/private-v98`, `-v99`, `-v1011`, step images and logs), the merged plugin branches
  `fix/slidemage-env-names` and `fix/slidemage-names` (local and on GitHub), and the private config
  `private-v10121.json`.

---

# Website session

Folded in 2026-11-02 from `docs/Handover_2026-10-26-Website-Session.md`. Status: **open, small.** The site is live, and the catalogue serves the plugins.

Still open:

* Website session: link GitHub Discussions from the site. Discussions is on for SlideMage/SlideMage; the site's docs do not
  mention it.
* Stefan: whether Uni Graz IT was asked about publishing `docs/UGO_api.md`, which is now public in the CampusOnline plugin's
  repository. Not verified.
* ~~Website session: `REUSE.toml` declaring `example/**` CC-BY-SA, which may include the Uni Graz logo.~~ **Checked
  2026-11-03: resolved.** No Uni Graz logo or template is tracked in git under `example/**` any more (framework-redesign
  step 16 already removed them); the only Graz-named paths on disk are gitignored local build/preview artifacts. The
  blanket CC-BY-SA declaration needs no change.

Still useful below: section 5, the working notes.

## Original text

## Website session: handover

Written 2026-10-26 for a fresh session to continue; updated 2026-10-27. Read this first, then
`docs/Handover_2026-10-26-Plugins-For-Website.md` (the plugins plan's requirements for the website: catalogue
format, conventions, approval, pages), then `docs/Handover_2026-10-27-Website-To-App.md` (the drafted answer to
the app side). This file only records what was decided and built; it doesn't repeat those.

**Where to pick up:** the domain is live (2026-10-27) and the note to the app side is complete. Everything still
open waits on other work: real plugin releases, the framework redesign, the public repo.

### 1. Where things stand

| Piece | State |
|---|---|
| Website | **Live** at https://slidemage.org/ (since 2026-10-27; the old `stpalan.github.io/slidemage-website/` redirects) from the public repo `stpalan/slidemage-website` (local: `D:\uniCLOUD\slidemage-website`) |
| Test plugin | **Published**: public repo `stpalan/slidemage-plugin-hello` (local: `D:\uniCLOUD\slidemage-plugin-hello`, pinned and pulled on 2026-10-27). Releases `v0.1.0` (listed) plus the 2026-10-27 test releases 0.2.0 (yanked), 0.3.0 (pre-release), 0.4.0 (refused) |
| Catalogue | **Live**: `/plugins/index.json` (no plugins yet), `/plugins/index-test.json` (hidden `hello` 0.1.0) |
| Plugins handover steps | 1–6 **done** (5 and 6 on 2026-10-27); 7 waits on real plugin releases |
| Plugin template | **Published** 2026-10-27: public template repo `stpalan/slidemage-plugin-template` |
| Domain `slidemage.org` | **Live** 2026-10-27: registered at all-inkl (KAS account `w021e5db`, renews 2027-10-27), verified for GitHub account `stpalan`, custom domain of the website repo, HTTPS enforced (certificate for the bare domain and `www`) |
| Report to the app side | **Complete**: `docs/Handover_2026-10-27-Website-To-App.md`; give it to the app side |
| SlideMage repo | Still **private**; the plan is to go public later as a fresh repo (section 4) |

### 2. Decisions taken

- **GitHub only, no WordPress.** Website on GitHub Pages, plugins/themes through the catalogue, discussion in
  GitHub Discussions (not set up yet). Reasons: no server upkeep, templates and plugins can be checked
  automatically, SlideMage can read the catalogue.
- **Website repo on Stefan's account** (`stpalan`), not an organisation; the plugins handover fixed this.
- **Static site: MkDocs Material**, pinned `mkdocs==1.6.1`, `mkdocs-material==9.7.7`. MkDocs 2.0 breaks
  Material; don't let the pin drift. A move to Material's successor may be needed some day, not now.
- **Website content license: CC BY-SA 4.0** (as SlideMage's docs). Builder code is in the same repo; if that
  needs a code license, add GPL-3.0-or-later for `tools/` and `tests/`.
- **Domain:** `slidemage.org` (`.com` is taken). Registered as one of Stefan's included domains at all-inkl;
  DNS stays at all-inkl, the site stays on GitHub Pages. DNS zone since 2026-10-27: GitHub Pages A and AAAA records
  for the bare domain, `www` CNAME `stpalan.github.io.`, the TXT `_github-pages-challenge-stpalan` (keep it: GitHub
  re-checks verification), and all-inkl's mail records (MX, SPF, DMARC, DKIM), so `@slidemage.org` mail would
  run through all-inkl. all-inkl's default A record and its `*` wildcard CNAME were deleted (a wildcard invites
  subdomain takeover). KAS → Tools → DNS Settings → History can restore the old zone.
- **Institution templates leave the SlideMage repo** before it goes public: Uni Graz template and logo,
  Innsbruck and MCI screenshots. This is **step 10 of the framework redesign plan**
  (`docs/plans/template-owned-layout-and-own-theme.md` on `dev-framework-redesign`, commit `398fea13`),
  not website work.
- **Going public: a fresh public repo** with filtered history (without the logo and screenshots); today's
  `stpalan/SlideMage` stays private as an archive. Reason: GitHub keeps `refs/pull/*` refs even after a
  force-push, so rewriting in place can't fully remove files.
- **Themes share the plugin catalogue** (Stefan, 2026-10-27): a top-level `"themes": [...]` list beside
  `"plugins"` in `index.json` (and `index-test.json`), with the same release, approval, pinning and SHA-256 rules,
  and `[[theme]]` entries in `registry/plugins.toml` (or a sibling registry file). **Not before** the theme
  package is defined with the framework redesign: its files, and where SlideMage installs it. `"themes"` is an
  optional new field, so `schema` stays 1. Until then the catalogue stays plugins-only.
- **Private plugin/theme sources** (answered, not built; belongs in the app's plugins plan, after its phase 1):
  per-user sources in Settings → Plugins (a GitHub repo or a private `index.json`); sign-in by reusing `gh`,
  a device-flow GitHub App with read-only Contents access to chosen repos, or a fine-grained token; token in
  the system keychain; downloads through the API (`/releases/assets/{id}`, `Accept: application/octet-stream`);
  marked "Not reviewed"; SHA-256 pinned on first install.

### 3. What was built

#### SlideMage repo (`stpalan/SlideMage`)

- **History audit** before going public: no secrets in any version of any file. Lecture material exists only
  in pre-split history, which `origin` doesn't contain.
- **Local tags cleaned**: the local-only tags `v0.0.1`–`v0.0.11` and `v3.32.1`–`v3.33.2` were rewritten as
  parentless commits with identical trees (lecture history behind them removed); `pre-split` was deleted (its
  commit also exists in `D:\uniCLOUD\Slidemaster`, the SlideMaster_SP repo). Jürgen's `jf/*` remote branches
  still reach the old history locally; nothing of it is on `origin`.
- **PR #17 merged** into `develop` (`537559ab`): 12 finished docs removed (completed plans, run logs, design
  briefs, benchmarks); the two with local paths among them.

#### Website repo (`stpalan/slidemage-website`)

| Path | What |
|---|---|
| `docs/` | Site content: Home, Download ("coming soon", releases are private), Plugins (with Submit a plugin), About |
| `docs/plugins/index.md` | Hand-written, except between `<!-- catalogue:cards:start/end -->`, which the builder fills |
| `docs/plugins/submit.md` | Hand-written `/plugins/submit/`: conventions, review, how to submit |
| `.github/pull_request_template.md`, `.github/ISSUE_TEMPLATE/submit-plugin.yml` | Review checklist; "Submit a plugin" issue form (label `plugin submission`) |
| `docs/plugins/index.json`, `index-test.json`, `<id>/…` | **Generated** by the builder; don't edit |
| `registry/plugins.toml` | Approved plugins; only `hello` (`hidden = true`) |
| `schema/plugins-index.schema.json` | The handover's schema; `deploy.yml` also publishes it at its `$id`, https://slidemage.org/schema/plugins-index-1.json (since `da8c48e`) |
| `catalogue/pins.json`, `last-run.txt` | Pinned SHA-256 per published version (with the `plugin.toml` fields); monthly heartbeat |
| `tools/build_catalogue.py` | The builder (`--check`, `--full-check`, `--report FILE`) |
| `tools/plugin_pages.py` | Plugin pages and cards; defuses third-party Markdown |
| `tests/test_build_catalogue.py` | 26 tests against a fake GitHub |
| `.github/workflows/deploy.yml` | Builds MkDocs and deploys Pages on push to `main`; also callable |
| `.github/workflows/build-catalogue.yml` | Hourly at :17 and on "Run workflow"; full re-hash at the 03:17 UTC run or on request; commits and calls `deploy.yml` only when something changed; opens an issue for a changed asset; on PRs runs tests and `--check` only |

Behaviour worth knowing:
- A run without news changes no file (the `generated` timestamp alone doesn't count), so there's no hourly
  commit noise. Commits by the workflow's token don't trigger `deploy.yml`, hence the explicit call.
- If GitHub can't be read for a plugin, its previous catalogue entry and page are kept.
- New releases are refused without `README.md` and `CHANGELOG.md` at the tag, besides the handover's rules.
- Plugin texts are defused before rendering: raw HTML and `{: …}` attribute lists escaped, links other than
  http(s)/mailto/anchors removed, relative links pointed at the repo at the tag, images reduced to alt text.
  Known limitation: `<` inside an indented (not fenced) code block shows as `&lt;`.
- URLs in the catalogue are absolute, built from `site_url` in `mkdocs.yml`; pages use relative links.
- Both test commits (`322b55a` removing the hello icon, `f8aeec4` the job restoring it) are deliberate: they
  proved the commit-and-deploy path.

#### Test plugin (`stpalan/slidemage-plugin-hello`)

Exactly section 8 of the plugins handover, plus `build.py`, which writes `dist/<id>-<version>.smplugin` and
its `.sha256` reproducibly (fixed zip timestamps, so a rebuild never changes the hash). The `.sha256` file is
in `sha256sum` format (`<hash>  <file name>`); the builder reads the first word.

#### Done on 2026-10-27

- **Submit a plugin** (website `21dbf2e`): `/plugins/submit/` (conventions, what the site builds, review, how
  to submit), `.github/pull_request_template.md` (the review checklist), the issue form
  `.github/ISSUE_TEMPLATE/submit-plugin.yml` with the label `plugin submission`; `/plugins/` links there.
  The page is `docs/plugins/submit.md`, **not** `submit/index.md`: the builder deletes the `index.md` of any
  folder under `docs/plugins/` that isn't a listed plugin. The registry refuses the id `submit` for that reason.
  The form and template link to `https://slidemage.org/…` since the domain went live.
- **`stpalan/slidemage-plugin-template`** (public, template repository): `example/` package, `plugin.toml`,
  `build.py` (checks the manifest, `activate()`, imports, compiled files and a CHANGELOG entry, then builds
  reproducibly; `--check`, `--tag`), workflows **Check** (every push; green) and **Release** (a pushed tag
  `v<X.Y.Z>` builds and publishes the release with the CHANGELOG entry as notes; **not run yet**).
  **Convention it sets, tell the app side:** the package folder is the id with hyphens as underscores
  (`my-plugin` → `my_plugin/`); the plugins plan didn't say how a hyphenated id maps to a package.
- **Pipeline exercise on `hello`** (next step 4 below): all four cases behaved as intended, no builder bug.
  0.2.0 listed and pinned; 0.3.0 (pre-release) ignored; 0.4.0 (asset `hello_0.4.0.zip`) refused with
  "no asset named hello-0.4.0.smplugin" in the Build step's log; 0.2.0's asset replaced → dropped at the
  full-check run and issue #1 opened, then `yanked = ["0.2.0"]` (`fa35644`) and the issue closed. The test
  catalogue lists hello 0.1.0 only; the public one stays empty. hello's GitHub "Latest" release is now the
  refused 0.4.0; harmless.
- **Pre-public clean-up**: SlideMage PR #18 (`claude/prepublic-cleanup-578670` → `develop`, v8.61.1): test
  fixtures use "Erika Musterfrau"; `wizard-poses.png` (2.4 MB) → `wizard-poses.webp` (403 KB; the spec packs
  all of `assets/`, the build has `qwebp.dll`). **Merged** into `develop` on 2026-10-27 (`c3df1bd7`).

### 4. Next steps, in order

1. ~~Plugins handover step 5~~ (done 2026-10-27, above).
2. ~~Domain~~: **done 2026-10-27** (website `9106113`, template `bf6d03f`, repo homepages updated, catalogue rewritten
   by run 40498542071, whose call into `deploy.yml` also proved that path on the new action versions). The steps,
   kept for reference: **Domain, as soon as all-inkl has registered it** (check: `Resolve-DnsName slidemage.org -Type NS`, or the
   registry itself: `https://rdap.publicinterestregistry.org/rdap/domain/slidemage.org` answers 404 until it
   is registered):
   1. GitHub → Settings → Pages (account level) → Add a domain → `slidemage.org`; put the TXT record
      `_github-pages-challenge-stpalan` it shows into KAS → Tools → DNS-Einstellungen; Verify.
   2. In KAS DNS for the bare domain: delete all-inkl's own A/AAAA records (and any `*` wildcard), add A
      `185.199.108.153`, `.109.153`, `.110.153`, `.111.153`; AAAA `2606:50c0:8000::153` … `8003::153`; `www`
      CNAME `stpalan.github.io`. Keep MX records (e-mail can stay at all-inkl). If CAA records exist, allow
      `letsencrypt.org`.
   3. Website repo → Settings → Pages → Custom domain `slidemage.org`; tick "Enforce HTTPS" when offered.
   4. Change `site_url` in `mkdocs.yml` to `https://slidemage.org/` (and the repo homepage); push. The next
      catalogue run rewrites every absolute URL. Also replace `stpalan.github.io/slidemage-website` in
      `.github/pull_request_template.md`, `.github/ISSUE_TEMPLATE/submit-plugin.yml`, and in the template
      repo's `README.md` and homepage.
   5. Tell the app side the final catalogue URL: `https://slidemage.org/plugins/index.json`.
3. **Report back to the app side**: complete in `docs/Handover_2026-10-27-Website-To-App.md` (domain filled in
   on 2026-10-27); it only needs handing to the app side. What it covers:
   - domain and catalogue URL (after step 2);
   - schema as committed: `schema/plugins-index.schema.json` in the website repo;
   - test catalogue: `https://<domain>/plugins/index-test.json` with `hello`;
   - `.sha256` format; the README/CHANGELOG requirement; the icon rules (SVG without scripts, PNG square
     ≥128 px);
   - the template's package naming (id with hyphens as underscores) and the reserved id `submit`;
   - **themes**: decided, in the same catalogue (section 2), once the theme package is defined with the
     framework redesign. When it is: add `"themes"` to the schema and the builder, plus `[[theme]]` registry
     entries, theme pages and cards.
4. ~~Exercise the pipeline with more `hello` releases~~ (done 2026-10-27, above).
5. ~~`slidemage-plugin-template`~~ (done 2026-10-27, above). Its Release workflow gets its first real run
   with the first plugin made from it; watch that one.
6. **GitHub Discussions** for the forum: enable on the public SlideMage repo once it exists (categories:
   Announcements, Q&A, Ideas, Show & tell, Template submissions); link from the website.
7. ~~**Going public**~~ **STALE, resolved: `SlideMage/SlideMage` is already public** (checked 2026-11-03,
   `gh repo view` reports `visibility: PUBLIC`). This handover section predates whatever later work actually made it
   public (not recorded here) — the "fresh filtered repo" plan described above never happened and is moot; the
   existing repo went public as-is. Nothing left to do on this item. Still genuinely open: whether Uni Graz IT was
   asked about `docs/UGO_api.md` (now public either way), and whether `docs/UGO_api.md` should still move to the
   CampusOnline plugin repo.

Smaller follow-ups found along the way:
- ~~wizard-poses.png~~ and ~~the real colleague's name in test fixtures~~: SlideMage PR #18, merged.
- ~~Node 20 actions~~: raised on 2026-10-27 (website `8dd381e`, template `1b78e97`) to `checkout@v7`,
  `setup-python@v7`, `configure-pages@v6`, `upload-pages-artifact@v5`, `deploy-pages@v5`; all paths green,
  including the catalogue's call into `deploy.yml`.
- `REUSE.toml` declares all of `example/**` CC-BY-SA-4.0, which would include the Uni Graz logo; step 10
  removes the logo, otherwise it needs its own entry.
- The one-off allow rule `Bash(gh pr merge 17 …)` is not on this machine (`C:\Users\palans`); if it exists in
  `C:\Users\ms\.claude\settings.json` on Stefan's other computer, it can go (the general rule covers it).

### 5. Working notes

- **The local website copy `D:\uniCLOUD\slidemage-website`** was unusable for git until 2026-10-27: its
  `.git\objects` were uniCLOUD online-only placeholders, and git failed with `fatal: mmap failed: Invalid
  argument`. Stefan set the folder to "always keep on this device"; status, pull and fsck work since. If git
  hangs in a uniCLOUD folder again, check for online-only files first (attribute `0x1000`).
- **Line endings:** on Windows (`core.autocrlf=true`) a local builder run shows `docs/plugins/hello/icon.svg`
  as modified (LF → CRLF only); restore it with `git checkout --`, don't commit it.
- **Running the builder and tests locally:** in a clone of the website repo, create a venv
  (`python -m venv .venv`, ignored by git), then
  `pip install -r requirements.txt -r requirements-catalogue.txt pytest==8.3.3`.
  Tests: `python -m pytest -q tests`. Builder: `python tools/build_catalogue.py` (set `GITHUB_TOKEN` to
  `gh auth token` to avoid the 60-requests-per-hour limit). Site: `mkdocs build --strict`.
  The venv used on 2026-10-26 was in that session's scratchpad and is gone.
- **To preview a hidden plugin's page**, build a copy of the repo with `hidden = false` and serve the built
  site locally; don't commit that change.
- **DNS checks:** this network blocks direct DNS queries (port 53 to `ns5.kasserver.com` times out); use
  DNS-over-HTTPS instead, e.g. `curl "https://dns.google/resolve?name=slidemage.org&type=A"`.
- **KAS and the browser:** the all-inkl login doesn't carry over to new tabs; Stefan logs in to KAS in the tab
  Claude in Chrome uses. Never enter the password yourself.
- **Merging into SlideMage's `develop` or `main`:** a ruleset ("Protect develop and main") allows only
  admins, so merge with `gh pr merge <n> -R stpalan/SlideMage --merge --admin`. Since 2026-10-27 Stefan's user
  settings allow `Bash(gh pr merge:*)`, so auto mode lets it through (use the Bash tool, not PowerShell). Merge
  only when Stefan asks for that PR, and name it first.
- **Splitting work:** Stefan wants sub-sessions where they help, on a model fitting the task (Sonnet for
  mechanical pieces), each with a self-contained brief; verify their results before reporting them.
- **Website and plugin repos:** a fresh `git clone` into the session's scratchpad is quickest and never touches
  the uniCLOUD copies; push from there, then `git pull` the local copy if Stefan uses it.
- **Don't touch** the main SlideMage checkout's working tree (`feature/qr-code` with uncommitted changes) or
  the `fw-*` worktrees; other sessions work there. Use a new worktree from `origin/develop` for SlideMage
  changes.
- **Commit style:** sentence-case subject without prefix, a body saying what and why, ending with the
  `Co-Authored-By` line the session's system reminder gives. SlideMage app-code commits need a
  `VERSION_NUMBER` bump and CHANGELOG entry (format checked by `packaging/release_notes.py`); docs-only and
  website commits don't.
- **Names:** every SlideMage TeX name starts with uppercase `SM` (not relevant to the website, but to theme
  packages later).

---

# Plugins status, from Jürgen

Folded in 2026-11-02 from `docs/Handover_2026-10-28-Plugins-Status.md`. Status: **open: checks never closed.** All the code is merged and the plugins are released.

Still open (none of these was verified as done):

* Stefan or Jürgen: an acceptance test from an installed `.smplugin`, with a real course fetch and insertion.
* Jürgen: a real Anthropic call from a Windows release build.
* Stefan: the Ollama plugin's network tests need a runner that allows TCP on loopback.
* Jürgen: the Claude plugin's integration tests still import SlideMage internals.
* Jürgen: whether the template branch `plugin-api-1`, on his machine only, still matters now that
  `SlideMage/slidemage-plugin-template` exists.
* ~~Stefan: section 7's item 7, limiting "Install from file…" to catalogue ids.~~ **Decided 2026-11-03: no restriction.**
  Users may install any `.smplugin` that passes the structural/manifest checks, same as today — the confirm dialog's
  warning ("not from the SlideMage plugin list... install only if you trust where it came from") stays as the only
  gate. No code change needed.

New work, not from this text: Claude plugin 1.1.0 (SlideMage/slidemage-plugin-claude#5) is merged, not released; the app side
is SlideMage v0.13.20 (#63).

## Original text

## Plugins: handover to Stefan, 2026-10-28

From Jürgen's side of the plugins work. It says what has been built since your handovers of 2026-10-26, the pull
requests we will open (with their drafts), and every change or addition to your plan and handovers. Status: see
section 0; PR 1 was merged as #19 on 2026-10-27, and #22 (the GUI tests) is merged too.

Your documents this refers to: `docs/PLUGINS_PLAN.md` (your draft 2, now draft 3 with a section 6),
`Handover_2026-10-26-Plugins-For-Website.md`, `-CampusOnline-Plugin.md`, `-Claude-Plugin.md`,
`-Ollama-Plugin.md` (the last one we haven't seen).

### 0. Update, end of 2026-10-28: the whole plan is built

Everything in the plan is now implemented and in pull requests on `SlideMage/SlideMage` (the repository moved to
the organisation during the day; the old `stpalan/SlideMage` URLs redirect). Sections 1–8 below are the state of
the morning; where they differ, this section wins.

| PR | What | Base | State |
|---|---|---|---|
| #20 | Phase 4: Anthropic API without the SDK; HTTPS proxy support (`HTTPS_PROXY`/`NO_PROXY`, CONNECT, proxy auth) and Stop ending a stuck connect/TLS handshake (review findings 6, 7) | `develop` | draft |
| #21 | Phases 0–1: plugin host; all review findings on it fixed (1–5, 8, 11, and the release points: separate migration offers, self-test of the PySide6 set); `plugin_api` contract test; manual chapter and README | `develop` | draft |
| #22 | `develop`'s 8 failing GUI tests | `develop` | merged |
| #23 | Phase 2: CampusOnline out of core (v9.0.0, `Migration('campusonline', 'v9.0.0')`) | #21 | draft |
| #24 | Phases 3 and 6 (core): AI routes in a registry, the AI UI and one AI tab over them, the host for AI plugins (`add_ai_route`, `add_settings_section`, entry points, terminal service, credentials, `ai_tools`, `RouteContext`, route task leases, chat surface context, …) | #21 (+#20 merged in) | draft |
| #26 | Phase 7: the AI-free core (v9.1.0, migrations for Claude and Ollama, `--claude-hook` dispatches to the plugin); tests on shared fake routes; full suite clean apart from the font test #22 fixes | #24 | draft |

Merge order: #22 (merged), #20, #21, then #23 and #24 (both on #21), then #26. Version numbers get renumbered at merge (and
see section 6 on renumbering for publication).

**Since then (evening of 2026-10-28):**
- **`uv.lock` regenerated on every open PR branch**, so each matches its own `pyproject.toml` (`uv lock --check`
  passes). On #20 the `anthropic` SDK and the 14 packages that came only with it are out. #20's "regenerate
  `uv.lock`" item (3.2) is done.
- **The stack is merged upward again:** #21 into #23 and #24, #20 into #24, #24 into #26. The only conflict was
  `uv.lock`, fixed by locking again. No code changed, so the test results above still hold.
- **The review of 2026-10-28** that findings 1–11 refer to is now in the repository:
  `docs/Code_Review_2026-10-28-Plugins.md`.
- **CampusOnline:** its fixes for findings 8–10 are pushed (now in its own repository, see below).
- **Local checkouts:** a clone made before the move still has `origin` on `stpalan/SlideMage`, and its `git fetch`
  fails over SSH; `git remote set-url origin git@github.com:SlideMage/SlideMage.git` fixes it.

**Still open or not verified** (from 3.2, 3.3, the review and the plugins' own `docs/PLAN.md`):
- **Never built or run frozen:** no PyInstaller build of any of the PRs. The `--self-test --plugins` step in the
  release workflow is the first real check, so the size the bundled stdlib adds is unknown too. No real Anthropic
  call from a Windows release build yet (certificates now come from the system store, not `certifi`).
- **The plugins' CI doesn't test against SlideMage.** Their Check workflows don't install SlideMage, and
  `requires_slidemage` (`>=9.0` for CampusOnline, `>=9.1` for Claude and Ollama, decided 2026-10-29) names releases that don't exist
  yet. Pin CI to a SlideMage release and set the ranges once the version question (section 6) is decided.
- **No acceptance test from an installed `.smplugin`.** The CampusOnline end-to-end test loads the checkout and
  pretends the app is v9.0.0. It doesn't install a release archive or drive a real course fetch and insertion.
- **Ollama plugin:** its `docs/PLAN.md` gap list predates #26. Gaps 1–3 (built-in route, built-in UI paths,
  the settings reader that migrates on read) are gone in #26, which has no built-in routes and reads with
  `peek_ollama_host`. Still open: its network tests need a runner that allows TCP on loopback.
- **Claude plugin:** its integration tests and the benchmark still import SlideMage internals (the package
  itself imports only `slidemage.plugin_api`). We suggest keeping that until core offers public test fixtures.
- **Only on Jürgen's machine:** the template branch `plugin-api-1`. It waits for your answer on the template.

**Plugin repositories (2026-10-28, evening):** `SlideMage/slidemage-plugin-campusonline`, `-claude` and `-ollama`
are created, public, with issues on. Each plugin's branch is pushed as both `main` and `develop`, and each `plugin.toml`
`homepage` points there. Before publishing, CampusOnline's history was rewritten with `git filter-repo` to replace a
colleague's real name in old test fixtures (the one #18 replaced in SlideMage), so its commit hashes changed; the
hashes in this handover are the new ones. The Claude and Ollama branches never contained the name and are unchanged.
SlideMage's old version tags, which came along with the filtered histories, were not pushed. GitHub didn't run the
Check workflows for the first pushes; they run from the next push on. The old `plugin-campusonline` branch on
`JuergenFleiss/SlideMageS` now holds the rewritten history too.

**Plugins** (all on the real `plugin_api`, packaged code importing nothing else from SlideMage; `build.py --check`
passes; review findings 8–10 fixed in CampusOnline; #20's proxy and abort fixes ported into both AI plugins):

| Plugin | Where now | Next |
|---|---|---|
| CampusOnline | `SlideMage/slidemage-plugin-campusonline` (public; `main` and `develop`) | 1.0.0 with SlideMage 9.0, registry entry |
| Claude | `SlideMage/slidemage-plugin-claude` (public; `main` and `develop`) | 1.0.0 with SlideMage 9.1, registry entry |
| Ollama | `SlideMage/slidemage-plugin-ollama` (public; `main` and `develop`; yours to maintain) | same |
| Template | local branch `plugin-api-1` of your template: the real API in the example, frozen-app import contract, relative-import check, a changelog checker (`release_notes.py`) | pull request to you, if you want it |

**Needed from you now:**
1. ~~Organisation access~~: done. Jürgen is a member now and created the three plugin repositories on 2026-10-28
   (see the next paragraph). Ollama is yours to maintain: give yourself or others the rights you want on it.
2. Review #21 and #24 as the owner of the API; the decisions taken along the way are below.
3. The version question (section 6) before #23 and #26 are released.

**Decisions taken on the way** (Jürgen said to go ahead with the recommended option):
- `edit_deck_text` instead of `add_deck_marker`; the extra host calls of 5.2; `add_*` only inside `activate()`;
  render priority on a worker thread.
- Plugin updates and removals are staged and applied at the next start; reserved plugin ids for the host's own
  folders.
- First-start onboarding and migration offers are separate (`upgrade.MIGRATIONS`); the CampusOnline project hint
  doesn't nag on the same start as its migration sheet.
- Routes: only the first local route is used (a chooser needs a design); a chat surface has no "session is live"
  property, so the switch asks before leaving any surface; route methods get a typed `RouteContext`.
- The plugin API grew by additions only (`API_VERSION` stays 1), guarded by the contract test's snapshot.

### 1. In short

- **Phase 4** (stdlib Anthropic client) is done, ahead of the order, because nothing depends on it.
- **Phases 0 and 1** (plugin host and installing) are built by us, as their own pull request from `develop`.
  Nothing built in moves out yet.
- **CampusOnline plugin**: steps 0–4 of its own plan done. It runs against the real host in an end-to-end test.
- **Where we went another way than your plan, or added to it**: section 5. Most important: `plugin_api` follows
  the CampusOnline plugin's drafted host (`edit_deck_text` instead of `add_deck_marker`, and more), and the host
  is **v8.68.0, not v9.0** (section 6).
- **What we need from you**: section 7.

### 2. Branches and repositories

| Where | Branch | Base | Commits | Version | Pushed |
|---|---|---|---|---|---|
| `stpalan/SlideMage` | `feature/ai-tools-fixes` | `develop` | 14 | v8.64.1 – v8.65.0 | merged as #19 (2026-10-27) |
| `stpalan/SlideMage` | `feature/anthropic-stdlib` | `develop` | +6 | v8.67.1 – v8.67.2 | yes, draft PR #20 |
| `stpalan/SlideMage` | `feature/plugin-host` | `develop` | 12 | v8.68.0 | yes, draft PR #21 |
| `JuergenFleiss/SlideMageS` (private fork) | `plugin-campusonline` (history of its own) | – | 6 ahead of the fork | plugin 1.0.0 (undated) | partly: up to `48b7a26` |

`feature/plugin-host` is independent of the other two; the merge conflicts this causes are listed in 3.3.

### 3. Pull request drafts

#### 3.1 PR 1: AI tools fixes (`feature/ai-tools-fixes` → `develop`)

Already merged as #19 (2026-10-27). Not part of the plugins work; PR 2 was stacked on it.

> **Title:** AI tools: fixes from the 2026-10-27 review (v8.64.1 – v8.65.0)
>
> Implements `docs/AI_TOOLS_FIX_PLAN.md`:
> - the Slide scope enforced in the agent tools, not only in the Claude Code hook (v8.64.1);
> - `modify_slide` edits the file it was given, and only a bare id follows the EN/DE switch (v8.64.2);
> - one source of tool guidance: the prompts keep the workflow, the tool descriptions the details (v8.64.3);
> - tool arguments checked recursively against their schema (v8.64.4);
> - one preview path through `preview_batch_output`, `insert_slide` as its own tool, the `create_slide` deck default,
>   cleanups (v8.65.0);
> - `docs/` overview of the AI tools.
>
> **Tests.** The AI tool, MCP, hook and chat tests pass. 8 GUI tests fail, the same 8 that fail on `develop`
> itself (section 8), so none of them comes from this branch.

#### 3.2 PR 2 (#20, draft): Anthropic API without the SDK (`feature/anthropic-stdlib` → `develop`)

> **Title:** Plugins plan phase 4: the Anthropic API without the anthropic SDK (v8.67.1 – v8.67.2)
>
> Phase 4 of `docs/PLUGINS_PLAN.md`, brought forward because nothing depends on it. The Claude plugin must be pure
> Python, and the SDK needs the compiled `pydantic_core`.
>
> - `ai/anthropic_provider.py` (new, the path the Claude handover asks for, so its history extracts cleanly):
>   `AnthropicProvider` on `http.client` with server-sent events, a subclass of the Ollama provider's
>   `_HttpProvider`. It covers plan §2.3's table: streaming for `chat()` too; tool input from `input_json_delta`
>   pieces; thinking, redacted-thinking and unknown blocks kept as wire dicts and replayed unchanged
>   (`AssistantMessage.raw` is now a list of plain dicts); `cache_control`, `output_config.effort`, images, usage
>   with cache tokens; two retries on 408/409/429/5xx and dropped connections, only before any answer arrived,
>   honouring `retry-after` (capped at 60 s); the same error messages; `/v1/models` with pagination; `abort()`
>   during connect, backoff or a blocked read; unknown events and deltas ignored; TLS with the stdlib's default
>   context, as the updater uses.
> - `anthropic` and what came only with it (`pydantic`, `pydantic_core`, `httpx2`, `httpcore2`, `anyio`, `jiter`,
>   `sniffio`, `idna`, `h11`, `annotated-types`, `typing-inspection`, `docstring_parser`) leave `pyproject.toml`,
>   the spec and `THIRD_PARTY_NOTICES.md`; `tools/third_party_notices.py` no longer lists it.
> - `docs/PLUGINS_PLAN.md`: your draft 2 restored unchanged as sections 1–5, and draft 3's section 6 (what
>   changed since), plus this handover.
> - Claude Code is untouched: it never used the SDK.
>
> **Tests.** New in `test_agent_claude.py` and `test_ai_providers.py`: retry on 529, `retry-after`, no retry after
> streaming started, a mid-stream error event, unknown events, tool input in pieces, replayed thinking blocks,
> pagination, abort during backoff. The full suite: 3553 passed, 14 skipped, 8 failed, all 8 being `develop`'s
> own (section 8).
>
> **Before merging:** `uv.lock` is regenerated (the SDK and its dependencies are out). Check one real
> API call from a Windows release build (certificates come from the system store now, not from `certifi`).

#### 3.3 PR 3 (#21, draft): the plugin host (`feature/plugin-host` → `develop`)

> **Title:** Plugins plan phases 0 and 1: the plugin host (v8.68.0)
>
> Implements `docs/PLUGIN_HOST_PLAN.md` (the step plan for phases 0 and 1 of `docs/PLUGINS_PLAN.md`). Nothing
> built in moves out: CampusOnline and the AI stay in core until phase 2 and later.
>
> - **Loading** (`plugins/manifest.py`, `loader.py`, `registry.py`):
>   - a plugin is a package with a `plugin.toml` (the website handover's rules);
>   - it is installed unpacked in `config_dir()/plugins/<id>/`, or is a checkout named by `SLIDEMAGE_PLUGIN_PATH`
>     (a checkout replaces an installed copy of the same id);
>   - it is imported under its own name (the id with `-` as `_`) from its folder, and refused when the name is
>     already importable;
>   - a failing, disabled or incompatible plugin is recorded with its reason and never stops the start.
> - **`slidemage.plugin_api`** (API 1, stdlib only): the types and the `Host` Protocol. They follow the CampusOnline
>   plugin's drafted host (section 5.2), plus `settings()`, `add_settings_tab`, `log`, `show_message`. `add_*` works
>   only inside `activate()`.
> - **Host** (`plugins/host.py`, `ui/plugin_ui.py`):
>   - services: cache folders (with `legacy_cache_dir()`), per-plugin settings, background work, deck edits with
>     the stale-file check, slide insertion (ids minted, all or nothing), deck language, `open_url` (http/https only);
>   - UI hooks: commands into the registry and palette, Deck menu sections named after the plugin, Deck settings
>     tabs with a footer action that replaces Save on that tab, Settings tabs, compact side-panel boxes after a
>     "Plugins" separator (`when` decides; `large` refused until the dock is built), render priority ORed with
>     core's rule.
> - **Installing**:
>   - `plugins/installer.py` checks the SHA-256 and refuses absolute paths, `..`, symlinks, backslashes, compiled
>     files and oversized archives, then swaps the folder atomically. Plugin downloads are http/https only, with
>     the size checked;
>   - `plugins/catalogue.py` reads `https://slidemage.org/plugins/index.json` (override
>     `SLIDEMAGE_PLUGIN_CATALOGUE`), caches it, ignores unknown fields, skips broken entries, and picks the newest
>     release that fits. It never reads GitHub's "latest release".
> - **UI**:
>   - Settings → Plugins: installed plugins with state, details, needs, network, enable, remove and update;
>     available plugins with install; Install from file… with a warning and an optional `.sha256`; "Restart now";
>   - Help → Plugins…;
>   - a first-start sheet, shown only when the list has something to offer;
>   - plugin updates following the app's update mode (off, ask, auto), at most once a day;
>   - withdrawn versions are flagged;
>   - the upgrade detection (which built-in features a user used) is written and tested, but switched off
>     (`PRESELECT_ON_UPGRADE = False`).
> - **Frozen build**: the spec bundles the stdlib (minus `tkinter`, `turtle*`, `idlelib`, `test`, `ensurepip`,
>   `lib2to3`, `pydoc_data`, `this`, `antigravity` and private modules) and `QtCore`, `QtGui`, `QtWidgets`,
>   `QtNetwork`, `QtSvg`; `--self-test --plugins` imports them and loads a plugin, in the release workflow on Linux
>   and Windows.
>
> **Tests.** About 255 in `tests/test_plugin_*.py`, with fixture plugins (good, bad manifest, raising, future API,
> needs newer, name clash, relative imports, late `add_*`, a UI plugin). `test_plugin_campusonline_e2e.py` loads
> the real CampusOnline plugin when `SLIDEMAGE_E2E_CAMPUSONLINE` names its checkout: it activates, and its commands,
> Course tab and box work. The full suite fails on the same 8 tests as `develop` and no others (section 8).
>
> **Not verified here:** a PyInstaller build (the self-test in the release workflow is the check), and how much the
> stdlib adds to the download.
>
> **Merge conflicts with PRs 1–2**, all mechanical:
> - `version.py` and `CHANGELOG.md`: renumber at merge;
> - `packaging/slidemage.spec`: PR 2 sets `HIDDEN_IMPORTS = []`, PR 3 builds the stdlib list with
>   `collect_submodules("anthropic")` in it; keep PR 3's list without the anthropic line;
> - `tests/test_settings_gui.py` and `tests/test_menu_bar_gui.py`: both add expectations.

#### 3.4 PR 4: CampusOnline plugin, public repository (after PR 3 is merged)

Not a pull request into SlideMage. Its plan's steps 5 and 6:

1. Step 5: replace `campusonline/host.py`'s Protocol by imports from `slidemage.plugin_api`, delete `bridge/`, and
   test against the oldest and newest SlideMage allowed.
2. Create `JuergenFleiss/slidemage-plugin-campusonline` (public, issues open), push the branch as `main`, replace
   the template's icon, add screenshots, date 1.0.0, and tag `v1.0.0`.
3. A pull request to `stpalan/slidemage-website` `registry/plugins.toml` (`releases = "all"`, first-party).

#### 3.5 PR 5: phase 2 in core, CampusOnline out (after 1.0.0 is listed)

Remove `course_schedule.py`, `admin_slides.py`, `ui/dialogs/admin_slides.py`, the course-link code of `deck_scan`,
`deck_settings` and `deck_editor`, the Deck settings field, the command and its menu entry, and the core
"session soon" rule, with their tests. Switch on the upgrade preselection for CampusOnline. Add the project hint
for decks with a course link. With a `BREAKING:` paragraph and a `compat.py` entry, this would be **v9.0.0**
(section 6).

#### 3.6 PR 6 (#22, merged): the 8 GUI tests failing on `develop` (`fix/develop-gui-tests` → `develop`)

All 8 were tests that had fallen behind the app; no app code changes:
- the AI switch moved out of the top bar, and Claude Code got session ids (both v8.61.0);
- a tuple index typo;
- Qt listing a font family under two foundries.

One trade-off for you to look at: the SemiBold font check now runs only off Linux, because Qt on Linux doesn't list
a variable font's named instances. CI runs on Linux, so it no longer runs in CI.

#### 3.7 Later

Phase 3 (the AI route registry, yours), the Ollama plugin (yours), phase 6 (the Claude plugin, ours), phase 7
(AI-free core), phase 8 (manual).

Small pull requests to your repositories we can open if you like:
- `slidemage-plugin-template`: refuse relative imports that leave the package; name the bundled stdlib and
  PySide6 set; show the real `plugin_api` calls in `example/__init__.py`.
- `slidemage-plugin-hello`: a release with a lower `requires_slidemage` (section 6).

### 4. Work done

#### 4.1 Phase 4 in SlideMage (PR 2)

As in 3.2. On the way:
- **A suspected hang wasn't one.** A full-suite run without `pytest-xdist` (not in the venv, so `-n auto` fails)
  is serial and takes about 35 minutes. No test hangs; the slowest file takes 73 s.

#### 4.2 Phases 0 and 1 in SlideMage (PR 3)

As in 3.3. Built as nine steps (`docs/PLUGIN_HOST_PLAN.md`), each reviewed and committed on its own.

#### 4.3 CampusOnline plugin (its repository, `docs/PLAN.md` there)

| Step | What | Commit |
|---|---|---|
| 0–1 | history filtered from `stpalan/SlideMage` `develop`; template adopted; the package stdlib-only, SlideMage internals in `bridge/` | up to `896f041` |
| 2 | the host drafted as a `typing.Protocol` (`campusonline/host.py`), a `FakeHost`, `activate()` registering everything | `100cabc` |
| 3 | "Course" Deck settings tab (link with Save link and Open, admin slides, Insert slides as the footer action) and the compact box (title, next session with date, time and room, Open course page, Admin slides…) | `1f2c2ed` |
| 4 | SlideMage's old `course-schedules.json` adopted once at activation | `063bd61` |
| – | the cache keeps the course title and full sessions, read through a public `cached_entry()` | `0fc20d5` |
| – | box sizes `compact` / `large` as in your plan | `2d6faa4` |

120 tests; `build.py --check` passes.

### 5. Changes and additions to your plan and handovers

#### 5.1 `docs/PLUGINS_PLAN.md`

| Your draft 2 | Now | Why |
|---|---|---|
| Order 0 → 1 → 2 → 3 → 4 → … | 4 done first; 0 and 1 done; 2 next | 4 depends on nothing; 0 and 1 were the bottleneck for the plugin |
| Phases 0–1 implied yours | built by us (PR 3) | to keep CampusOnline moving; review it as if it were yours |
| §2.1 "own vendored pure-Python code" | the package imported under its own name from its folder; a name already importable (stdlib, SlideMage, a dependency, another plugin) refuses that plugin | no `sys.path` entries, and no plugin can shadow a module |
| §2.2 | the build bundles the whole stdlib and five PySide6 modules for plugins, checked by `--self-test --plugins` | a plugin using e.g. `csv` would otherwise fail only in the installed app |
| §2.5 `factory(WindowApi)`, `when(DeckApi)` | `build(deck)` and `when(deck)` with a deck snapshot; only `compact` | what CampusOnline needs; `large` and the dock wait for a plugin that uses them |
| §2.7 extension points | see 5.2 | |
| §2.8 first-start sheet | shown only when the catalogue lists something offerable; offline, an empty list or a too-new catalogue leave it for a later start without setting the flag | the public catalogue is empty now: otherwise everyone would see an empty sheet once, and never the real one |
| §2.8 upgrade preselection | written and tested, `PRESELECT_ON_UPGRADE = False` until the release that removes a feature | nothing is removed yet |
| §2.8 updates "in the same pass as its own" | their own check, following the same mode, at most once a day, also in source checkouts | the app's own check is skipped in a source checkout; plugins can still update there |
| §2.6 Plugins tab | as specified, plus Details… for a load error, "Withdrawn from the plugin list", and a real restart through the existing relaunch | |
| §3 version numbers (implicit in the handovers: host ≥9.0) | host v8.68.0; v9.0 for the release that removes CampusOnline | section 6 |

Section 6 of `PLUGINS_PLAN.md` (draft 3) records the website's answers and the first half of this; this handover
supersedes it where they differ.

#### 5.2 `plugin_api` against your §2.7

| Your §2.7 | `plugin_api` (API 1) | Why |
|---|---|---|
| `add_command(id, title, scope, run, enabled, shortcut=None)` | `add_command(id, title, run, enabled)`; `id` must start with `<plugin id>.`; `enabled(None)` without an open deck | `scope` and `shortcut` are easy to add when a plugin needs them |
| `add_menu_entry(menu, command_id, section=None)` | `add_menu_entry("deck", command_id)`, one section per plugin at the end of the Deck menu, headed with its name | the only menu a plugin uses so far |
| `add_menu(title, sections)` | not built | no user |
| `add_settings_section(page="ai", …)` | not built | phase 3 |
| `add_deck_settings_tab(title, factory)` with footer action and dirty state | `add_deck_settings_tab(title, build, footer_action=FooterAction(label, run, enabled))`; the action's button replaces Save on that tab | the same, made concrete |
| `add_deck_marker(name)` | **`edit_deck_text(deck, change)`**; the plugin parses its own comment | smaller, more general; keeps the stale-file check |
| – | `open_deck_settings(deck, tab)` | "Admin slides…" opens the sheet on the Course tab |
| – | `cache_dir()`, `legacy_cache_dir()` | the plugin's cache, and where core kept a file before the plugin |
| – | `insert_positions(deck)`, `insert_slides(deck, position, [(suffix, frame)], language)`, `deck_language(deck)`, `open_url(url)` | the admin slides' deck edits |
| – | `Page()`, `Field(label, widget)`, `caption(text, tone)` as host methods | the tab and box look like SlideMage's |
| `settings(plugin_id)` | `settings()` (the host is per plugin) | |
| `add_render_priority(fn)` | the same; called on a worker thread; an exception counts as False | `BackgroundRenders` asks there |
| `add_ai_route`, `terminal()`, `ai_tools()`, `credentials` | not built | phases 3 and 6 |

#### 5.3 Website handover

- The client follows your answer of 2026-10-27: the fixed URL, `index-test.json` for tests, unknown fields
  ignored, the package-folder rule, the catalogue as the only source.
- **Download URLs:** the client accepts any `https` download URL. The schema's
  `github.com/…/releases/download/` pattern isn't enforced, since the catalogue is trusted either way. Say if you
  want it enforced.
- **Test overrides:** `SLIDEMAGE_PLUGIN_CATALOGUE` points the app at another catalogue, and
  `SLIDEMAGE_PLUGIN_PATH` at plugin checkouts.
- **Copies in our tests:** the schema and `index-test.json` are copied into `tests/fixtures/catalogue/`. Update
  them when the schema changes.

#### 5.4 CampusOnline handover

- **Repository:** on Jürgen's private fork `JuergenFleiss/SlideMageS` (branch `plugin-campusonline`) until 1.0.0,
  then `JuergenFleiss/slidemage-plugin-campusonline`. The handover's clone URL `JuergenFleiss/slidemage.git`
  doesn't exist; the history was filtered from `stpalan/SlideMage`.
- **Host:** `add_deck_marker` is replaced by `edit_deck_text` (5.2). The calls of its §2 table all exist, with the
  additions in 5.2.
- **Course tab:** the link has its own Save link button (Return saves too). After saving or inserting, the tab asks
  to reopen Deck settings, because the deck it holds is a snapshot.
- **Box:** shows cached data only and never fetches: title, next session (date, time, room), Open course page,
  Admin slides…. The cache now keeps the title and sessions. The weekday names are English for now.
- **Old cache:** `course-schedules.json` is adopted from `legacy_cache_dir()` once, never overwritten, and only
  when it is valid JSON.
- **§7 questions, Jürgen's answers:**
  - **Owner:** `JuergenFleiss/slidemage-plugin-campusonline` for now, with a counterproposal for later: a SlideMage
    organisation (section 5.7).
  - **Settings tab:** none for 1.0.
  - **Box:** as built. The weekday follows the deck's language (Mo/Di… for a German deck). There's no "group of
    the next session", because a course's groups usually have decks of their own.

#### 5.5 Claude handover

- **§4 (the stdlib client):** done by us, in `ai/anthropic_provider.py`, as asked.
- **`raw`:** now holds plain wire dicts, which matters for the plugin's tests.
- **§8 (feedback on the `AiRoute` shape for Claude Code):** still to come from us before phase 3. What we know
  it needs:
  - the `chat_surface` lifecycle: `stop()` and `restart(model, continue_conversation)`;
  - effort as part of the model choice;
  - a `problem()` that can say "not installed".

#### 5.6 Ollama handover

Not seen on our side; nothing changed.

#### 5.7 Counterproposal: a SlideMage organisation on GitHub

Your plan (§2.9) puts each plugin on its maintainer's personal account. That works for now, and CampusOnline
starts on Jürgen's account. For the longer run we propose **a GitHub organisation for SlideMage**, as aTrain has
for its transcription app, or as Flathub does for its apps:

- **Each plugin gets a repository in the organisation**, first-party and third-party alike.
- **The plugin's developer owns their repository** (admin rights on it).
- **One organisation member has access to every plugin repository**, for review, security fixes, and taking over
  a plugin whose developer has gone.
- SlideMage itself, the website and the template can live there too, or stay where they are: your call.

Please look at how Flathub is organised; it is the closest model we know:
- every app is a repository `github.com/flathub/<app-id>`;
- a new app comes in as a reviewed pull request to the submission repository;
- once it is approved, the organisation creates the app's repository and gives its maintainers write access to
  that repository only;
- builds and publishing run centrally.

In our terms, the submission pull request is the website registry's approval pull request (handover §4), and the
build bot is the catalogue builder.

What it gains:
- **A neutral home** that outlives any one person's account.
- **Stable repository URLs** for the registry and for each plugin's `homepage`.
- **One place to look** for "every approved plugin".
- **A simpler review.** The registry could require plugin repositories to be in the organisation, which makes the
  review checklist's "maintainer reachable" and "repository follows the conventions" easier to keep true.

Moving the repositories later is cheap, since GitHub redirects the old URLs, but the registry entries and the
`homepage` fields would change. So deciding before the first real plugin is listed is best.

### 6. Version numbers: a decision for you

The release tooling (`packaging/release_notes.py`) refuses a major version without a `BREAKING:` paragraph, and
a `BREAKING:` paragraph needs a `compat.py` entry. The plugin host breaks nothing, so it is **v8.68.0**. The handovers assumed 9.0:

- `hello` 0.1.0 and CampusOnline ask for `requires_slidemage = ">=9.0"`, so neither installs on the 8.x host. The
  end-to-end test loads CampusOnline as if the app were v9.0.0.
- **Proposal:**
  - **v9.0.0** is the release that removes CampusOnline (PR 5), a real `BREAKING:` change, and CampusOnline 1.0.0
    keeps `">=9.0"`;
  - `hello` gets a release with `">=8.66"`, so the installer can be tested against `index-test.json` on the host
    release;
  - **v10.0** stays the AI-free core, as the Claude handover says. (Superseded 2026-10-29: the AI-free core is
    v9.1.0; 10.x is the framework redesign's.)
- The alternative: ship the host as v9.0.0 with a `BREAKING:` paragraph and a `compat.py` entry anyway.

**Jürgen's proposal on top: renumber SlideMage for publication**, to something like **0.4**. A public first
release numbered 8 or 9 suggests a maturity and history the public hasn't seen. The plugins'
`requires_slidemage` values would then follow the new numbers: the host's release, then the release that removes
CampusOnline, then the AI-free core.

What a renumbering has to solve: the updater (`updater.py`) installs a release only when its version is higher,
so installs on 8.x would never take a 0.4. Options:
- a last 8.x release whose updater knows the new scheme;
- the public numbering starting in a new repository or release channel;
- installs of the current testers moved by hand.

Your call, since it's your release process.

### 7. What we need from you

1. Review PR 3 as the owner of phases 0–1, and confirm or change 5.2's API, before the CampusOnline plugin moves
   onto it (step 5). The calls that matter most: `edit_deck_text` vs `add_deck_marker`, and the extra calls.
2. Version numbers (section 6), and a `hello` release with a lower `requires_slidemage`, if you agree.
3. `add_render_priority` on a worker thread, `enabled(None)`, and `add_*` only inside `activate()`: OK?
4. The template: the relative-import check, the stdlib/PySide6 set in its README, and the real `plugin_api` in
   `example/__init__.py`. Shall we send the pull request?
5. The Ollama handover.
6. The 8 GUI tests that fail on `develop` itself (section 8): fixed in #22 (3.6), merged.
7. ~~**Install from file…:**~~ **Decided 2026-11-03: no, leave it as built.** Any `.smplugin` that passes the checks
   installs after a warning ("not from the SlideMage plugin list", plus its network lines); it stays unrestricted to
   catalogue ids.
8. The organisation (5.7) and the renumbering (section 6): what you think.

### 8. Full test suite, `feature/plugin-host` against `develop`

Both run in full on 2026-10-28, serially (`pytest-xdist` is not in the venv), side by side on one machine:

| | Passed | Skipped | Failed | Time |
|---|---|---|---|---|
| `develop` (clean copy) | 3510 | 14 | 8 | 36 min |
| `feature/plugin-host` | 3765 | 18 | 11 | 39 min |

- **The 8 failures of `develop`:** `test_workspace_window.py::test_top_bar_densities_*` (3),
  `test_accessibility_cards_gui.py::test_the_headers_icons_have_names`, `test_claude_code_gui.py` (2),
  `test_compare_rendered_gui.py::test_the_task_card_compares_in_review_and_done`,
  `test_ui_kit_gui.py::test_font_files_are_bundled_and_registered`. The plugin host's run fails on these 8 too.
- **Its 3 extra failures:**
  - `test_claude_tasks_gui.py::test_a_translation_creates_the_partner_after_the_source_and_links_both`
  - `test_workspace_window.py::test_column_toggles_…[shortcut-left…]`
  - `test_workspace_window.py::test_column_toggles_…[shortcut-right…]`

  All three pass alone, and their two files pass in full (apart from the 3 top-bar tests). They are timing
  failures under the load of two suites running at once, not failures of the branch.
- **Result:** the plugin host adds no failure. The 8 are `develop`'s own.

---

# Citation formats on the website

Folded in 2026-11-02 from `docs/Handover_2026-10-31-Citation-Formats-For-Website.md`. Status: **open.** The app side is built (`src/slidemage/citations.py`, `docs/CITATION_PACKAGE.md`, v0.13.0).

Still open:

* Website session: the `citations` catalogue category (schema, builder, pages, the reserved id `default`). The website repo
  has none of it, checked 2026-11-02.
* App: the catalogue client does not read `citations` yet. It waits until the website lists one, and no citation format
  repository exists.
* Standing rule: tell the website side when SlideMage ships another bundled template or citation format.

## Original text

## Handover: citation formats as a third category on the website

For whoever works on the website repository (separate from this one). Decided 2026-10-31, built in SlideMage v0.13.0
(step 18c). The full definition is `docs/CITATION_PACKAGE.md` in the SlideMage repository; this note is what the
website needs from it.

### What it is

Plugins add features, themes (`docs/THEME_PACKAGE.md`) add slide templates, and now **citation formats** add ways
references look (biblatex options and bibliography drivers: "Author, Initials., year. "Title", ..."). A deck or
template chooses one by its key with the catalog setting `\SMCitationFormat`; the format file is
`SlideMage_citation_<key>.tex`. The built-in house format is `default` and is not a package.

### What a package contains

A zip named `<key>-<version>.smcite` with `citation.toml` at its top level, plus `<key>-<version>.smcite.sha256`
(`sha256sum` format: `<64 lowercase hex>  <file name>`). Both are attached to a GitHub release with tag
`v<version>`. Inside:

```
citation.toml                         manifest
SlideMage_citation_<key>.tex          the format
SlideMage_citation_<key>_<name>.*     optional extra TeX files (.tex .bbx .cbx .dbx .lbx)
README.md, CHANGELOG.md, LICENSE      required
preview.png                           optional: sample of a reference list, for the catalogue
LICENSES/                             optional
```

`citation.toml` fields (all required text): `id` (the key, `^[a-z][a-z0-9-]{1,31}$`, never `default`), `name` (1-40
characters), `version` (`1.2.3`, equal to the tag without `v`), `requires_slidemage` (`">=0.13.0"`, comma-joined
comparisons), `summary` (1-120), `author`, `homepage` (http/https), `license`. No `api_version`, `needs`, `network` or
`layout`: a format runs no code but TeX. A package is checked by `tools/make_citation_package.py` (it also builds
the two release files); the website can run the same checks on a submitted repository.

### How the catalogue lists it

Following the website's schema for themes (`Handover_2026-10-31-Website-To-App-Theme-Checks.md`, section 2): a
top-level `"citations"` key beside `"plugins"` and `"themes"`, `schema` stays 1, and the key is only present once a
citation format is listed (today's catalogue is unchanged). An entry has:

- `id` (the key, also the asset prefix), `name`, `summary`, `homepage` (`https://slidemage.org/citations/<id>/`),
  `source`, `license`, `maintainer`, `recommended`;
- optional `preview` (the package's `preview.png`, copied to the site);
- `releases`, each with `version`, `requires_slidemage`, `url`, `sha256`, `size`, `published` and optional
  `notes_url`. (No `layout`: a citation format has none.)

`name`, `summary`, `license`, `requires_slidemage` come from `citation.toml`; release notes from `CHANGELOG.md` at
the tag. Release rules are the plugins' and themes': published (not draft, not pre-release), both assets present
with `<version>` equal to the tag without `v`, the zip's `citation.toml` carrying that version, the download
matching the hash.

**Reserved ids:** at least `default` (the built-in house format). The app's `citations.bundled_keys()` reads every
`SlideMage_citation_*.tex` in `latex/`, the builder's list is fixed: **whenever SlideMage ships another bundled
template or citation format, its key must be reported to the website side** so the builder reserves it too.

**Checks the builder should apply**, the app's: `citation.toml` fields as above (refuse `api_version`, `needs`,
`network` and `layout`; the app tolerates any other unknown key); the file list of `docs/CITATION_PACKAGE.md`; and, new in v0.13.0, refuse a package that
contains a file named like one of SlideMage's own framework files (`latex/`: `SlideMage_citation_default.tex`,
`SlideMage_base.tex`, a bundled layout profile...), because installed packages sit on TEXINPUTS ahead of the
framework. The same rule was added for themes in the same release: a theme with `layout` fira, lmsans or lmroman may
not ship `SlideMage_layout_<layout>.tex`.

A page for the category can say "A citation format changes how references look; it contains a TeX file and no
program", and how to use one: install from the catalogue or from a file in Settings → Plugins → Citation formats,
then in a template `\renewcommand{\SMCitationFormat}{<key>}` (before `\input{SlideMage_base}`) or in a deck the same
before `\SMUseBibliography`.

### What the app does not do (yet)

The app installs from a file and from a GitHub repository (with update offers) like for themes. It does not read the
catalogue's `"citations"` list yet (the schema stays 1, so no version decision is needed): that comes once the website
lists one, as for `"themes"`.

---

# Footnote marker styles

Folded in 2026-11-02 from `docs/Handover_2026-10-31-Footnote-Marker-Styles.md`. Status: **finished** (2026-11-03: the user
says the Graz theme with boxed markers is released; the item below is kept for reference). The styles are built and merged (PR #66, v0.13.15; manual slide 2mk). The original text below
still says "not implemented"; that is out of date.

Still open:

* Stefan: the Graz theme's switch to `\SMSetFootnoteMarkers{boxed}` is committed only on the local branch
  `footnote-markers-boxed` of `D:\uniCLOUD\slidemage-theme-uni-graz` (8efafd5, theme v1.1.0, needs SlideMage >= 0.13.15). It
  waits for a tagged SlideMage release of 0.13.15 or later (the latest tag was v0.13.11), and the user is asked before
  pushing, as the theme is shared with Jürgen. Then re-render the user's decks and look at footnote-heavy slides, as "User's
  Graz template" below says.

## Original text

## Handover 2026-10-31: footnote marker styles (dice, boxed arabic numbers)

Status: **designed and mocked up, not implemented.** The user decided (2026-10-31) to implement this
**after the framework redesign is done** (`dev-framework-redesign`, see
`docs/Handover_2026-10-26-Framework-Redesign.md`). Do not start before the redesign has landed, and do not
build it on develop now: the marker code lives in a different file on each branch (see "Where it goes").

### What the user decided

1. **Two new marker styles** beside the existing symbol sequence (`\setfootnotesymbols`, default 14 currency
   signs):
   - **Boxed arabic numbers**: the number in a thin rounded box in the text colour. Two-digit numbers get a
     **wider box** with the digits at full size (the user's pick over "same square, digits squeezed", which is
     unreadable in the footnote line).
   - **Dice**: TikZ-drawn die faces. 1-6 one die. Above 6 two dice read **positionally, bijective base 6**
     (digits 1-6, no zero), most significant die first: 7 = ⚀⚀, 8 = ⚀⚁, 12 = ⚀⚅, 13 = ⚁⚀, 18 = ⚁⚅,
     19 = ⚂⚀, 42 = ⚅⚅ (the largest with two dice). The user confirmed "7 = one and one".
2. **Markers a little smaller in the running text**, not in the footnote line (small enough there): scale to
   75 % when the font the marker is set in is 6 pt or larger.
3. **Transcripts stay as they are.** `transcript.py` already inlines each footnote's text in parentheses at
   its place ("Seventh point (Two dice: ...)"), so no marker style ever reaches a screen reader. The user said
   explicitly: don't change anything there.
4. **The user's own Uni Graz template is to use the boxed arabic numbers** once the feature exists (see
   "User's Graz template" below).

### Where it goes

- On develop the marker code is in `latex/Slidemaster_preamble_base.tex` (around line 2860-2905).
- On `dev-framework-redesign` it moved to `latex/beamerthemeSlideMage.sty` (around line 1727-1772):
  `\g_SM_footnote_symbols_seq`, `\setfootnotesymbols`, `\SMFnSymbol`, `\thefootnote`, `\thempfootnote`.
  Implement there, as its own step branch cut from `dev-framework-redesign` after the redesign's open steps
  are merged (step 16, `claude/fw-step16-themes-86bdbf` at d0c879ff, was unmerged on 2026-10-31; in the footnote
  section it only changes a comment). Run the redesign's regression (`tools/framework_regression.py`) against
  the current baselines: with the default style unchanged there must be 0 differences.
- Names follow the SM rule (uppercase SM + CamelCase). Suggested interface, to agree with the user:
  `\SMSetFootnoteMarkers{symbols|boxed|dice}`, default `symbols`, `\setfootnotesymbols{...}` unchanged and
  implying `symbols`. Internally `\SMFnSymbol{n}` dispatches on the style, so `\thefootnote` and
  `\thempfootnote` need no change.
- Document it where `\setfootnotesymbols` is documented (theme comment, manual slide on footnotes, LaTeX
  reference) and in the CHANGELOG (no parentheses in the reason; check with `packaging/release_notes.py`).

### Technical notes from the mock-ups

- Both markers are TikZ drawings in font-relative units (ex), so they scale with the font, take the current
  text colour and sit on the baseline. Dice glyphs U+2680-2685 are not in Fira Sans, hence TikZ.
- The macros must be `\protected`: `\thefootnote` gets expanded (marks, footnote storage).
- `\numexpr` rounds half up, so floor((n-1)/6) is `\numexpr(n-4)/6\relax`; the low digit is
  `n-6*((n-4)/6)`.
- Macro definitions with `#1` inside a beamer frame body break ("Illegal parameter number in definition of
  \iterate"): frame bodies are macro arguments. In a slide file put them before the frame; in the theme this
  doesn't arise.
- Above 42 dice would need a third die; footnote counters reset per frame and no slide of the user's has more
  than 6 markers (856 of 1,011 slides have none), so wrapping or a third die is an edge case, but decide one.
  Boxed numbers just grow wider.
- Many footnotes eat height: the er9 draft with 8 + 3 footnotes overflowed by 13.85 pt and needed
  `\shrinklists{1}`.

Macros as mocked up (final rules: positional dice, wider box):

```latex
\protected\def\SMMarkerInText#1{%
	\ifdim\csname f@size\endcsname pt<6pt #1\else\scalebox{0.75}{#1}\fi}
\protected\def\SMDiePip#1#2{\fill (#1*1.7,#2*1.7) circle (0.14);}
\protected\def\SMDieFace#1{%
	\draw[rounded corners=0.22ex] (0,0) rectangle (1.7,1.7);
	\ifcase#1\or
		\SMDiePip{0.5}{0.5}\or
		\SMDiePip{0.27}{0.27}\SMDiePip{0.73}{0.73}\or
		\SMDiePip{0.25}{0.25}\SMDiePip{0.5}{0.5}\SMDiePip{0.75}{0.75}\or
		\SMDiePip{0.27}{0.27}\SMDiePip{0.73}{0.27}\SMDiePip{0.27}{0.73}\SMDiePip{0.73}{0.73}\or
		\SMDiePip{0.27}{0.27}\SMDiePip{0.73}{0.27}\SMDiePip{0.5}{0.5}\SMDiePip{0.27}{0.73}\SMDiePip{0.73}{0.73}\or
		\SMDiePip{0.27}{0.25}\SMDiePip{0.73}{0.25}\SMDiePip{0.27}{0.5}\SMDiePip{0.73}{0.5}\SMDiePip{0.27}{0.75}\SMDiePip{0.73}{0.75}%
	\fi}
% bijective base 6, most significant die first: 7 = 1|1, 12 = 1|6, 13 = 2|1, 42 = 6|6
\protected\def\SMDieMarker#1{\SMMarkerInText{%
	\tikz[baseline=0pt, x=1ex, y=1ex, line width=0.08ex, line cap=round]{%
		\ifnum#1>6
			\SMDieFace{\numexpr(#1-4)/6\relax}%
			\begin{scope}[xshift=2.1ex]\SMDieFace{\numexpr#1-6*((#1-4)/6)\relax}\end{scope}%
		\else
			\SMDieFace{#1}%
		\fi}}}
% wider box for two digits, digits at full size
\protected\def\SMBoxedNumberMarker#1{\SMMarkerInText{%
	\tikz[baseline=(SMBoxedNumber.base)]{%
		\node[draw, line width=0.07ex, rounded corners=0.22ex, inner xsep=0.28ex, inner ysep=0.2ex,
			minimum width=1.3ex, minimum height=1.55ex, align=center] (SMBoxedNumber) {#1};}}}
```

In the theme these become expl3-style internals or keep these names; the `\SMDiePip`/`\SMDieFace` helpers
should not be public commands.

### User's Graz template

The user wants **their own Uni Graz template switched to the boxed arabic numbers** once the style exists.

- Today it is `D:\uniCLOUD\Slidemaster\Slidemaster_preamble_uni-graz.tex` in the user's project (develop
  naming). The redesign migrates project templates and step 16 makes Uni Graz a private theme repository
  shared with Jürgen (installed into `config_dir()/themes/<key>/`); change it wherever the Graz template
  lives at that point, not in SlideMage's repo (step 16 removed `example/SlideMage_template_uni-graz.tex`).
- The change is one line after the theme is loaded, e.g. `\SMSetFootnoteMarkers{boxed}`. Since it is shared
  with Jürgen, mention it to the user before pushing the theme repo.
- Then re-render the user's decks and look at a few footnote-heavy slides (e.g. fk7, xv8, j6h) for the marker
  size and for overflow.

### The manual shows the options

The user wants the manual (`example/`, deck `slidemage-manual` and its copy `slidemage-manual-copy`) to show
the marker styles; this replaces the draft slide er9 in the user's own project. Part of the same step:

- `example/slides/1nz-EN-Footnotes-Sources-Citations-current.tex` (main part of the manual): its bullet on
  `\setfootnotesymbols` gets a sibling for `\SMSetFootnoteMarkers{boxed}` / `{dice}`, pointing to the
  appendix sheet like it does now.
- `example/slides/2rg-EN-Footnote-symbol-options-current.tex` (appendix reference sheet, today only the
  Fira Sans symbols): add the two styles with live examples, at least 1, 7, 12 and 13 for the dice and 1, 9,
  10, 12 for the boxes, in running text and in the footnote line. If that doesn't fit on 2rg, a new appendix
  slide right after it in both manual decks. Both slides are 1-0-0 frozen versions in a deck; follow the
  manual's versioning rules when changing them.
- Re-record the in-repo regression baselines afterwards: these slides differ on purpose.

Nothing else from the mock-ups needs keeping: the macros above are the complete result, and the manual
slides become the visual reference. The mock-up script was a throwaway in the session's scratchpad.

### The draft slide er9 is gone

The draft slide `slides/er9-EN-Footnote-Markers-Dice-current.tex` in the user's project (in no deck) was
deleted on the user's instruction on 2026-10-31 (Slidemaster commit 4ecb3b9, not pushed): the manual will show
the styles instead. Its last version is in commit 4485d55 if anyone needs it; the macros above supersede it.

---

# SlideMage Presenter: things to watch

Kept 2026-11-02 from `docs/Handover_2026-10-31-SlideMage-Presenter.md`. Status: **finished; reference.** The Presenter is released (v0.13.11), and the rest of that handover is in `docs/plans/presenter-app.md`.

- **Shared settings file.** Both programs read and write the same `layout.json` (presentation settings, and 5c's
  remembered places). They may run at the same time. Writes must stay atomic, and a program must re-read before
  writing instead of overwriting the whole file with what it loaded at start, or one program wipes the other's
  changes.
- **One-file vs folder build.** The one-file exe unpacks itself on every start, which defeats the fast start. The
  folder build is the main asset. Offer a one-file build only if the user asks for it.
- **PyMuPDF stays below 2.0** (`pymupdf<2` in `pyproject.toml`): 2.0 loads a layout model at import that
  PyInstaller does not bundle. The Presenter's `--self-test` in the release workflow guards this as SlideMage's does.
- **Keep the presenter modules clean.** The import-boundary test from step 1 is the guard. When it fails later, the
  fix is a lazy import or moving project-specific code out of `presentation/`, never loosening the deny list
  without asking.
- **Frame-map naming.** In the code, "frames" are beamer frames (slides) and their reveal steps, from beamer's
  `.nav` file (`presentation/frames.py`). They are not the picture frames in `assets/frames`.
- **macOS specifics:** Gatekeeper on an unsigned app, Apple silicon vs Intel (a second runner or universal2),
  `keep_awake.py` has no macOS branch yet, the updater replaces a `.app` folder.

---

---

# Manual: the divider tks runs into the footer

Written 2026-11-02. Status: **finished.** PR #88 (v0.14.2) is merged into develop (checked 2026-11-03). The user chose
to take `tks` out of both manual decks; the slide stays as `1f8`'s translation, and the layout test passes under all
three templates. Found while documenting the debug log; it does not come from that work.

**The problem.** `tests/test_manual_fits_templates.py::test_the_manual_has_no_layout_finding_under_the_template`
fails for the `slidemage` and `greyscale` templates, on clean `develop` too (checked at `f28f4657`). Every finding is
the same one, in every view of `slidemage-manual` and, under the SlideMage template, of `slidemage-manual-copy`: the
slide `tks` (`example/slides/tks-DE-Chapter-Installation-current.tex`), page 95 or so, last agenda entry:

- SlideMage template: `bottom: text reaches y=254.85`, footer box at 247.89, `'Making a template'`
- greyscale template: `bottom: text reaches y=246.47`, footer box at 244.16, `'–Makingatemplate'`

**What is known.**

- `tks` is the German translation of the Installation chapter's divider `1f8`, but it is the last `\slide` of both
  manual decks, inside `\section{Appendix: Reference}`. Its `\SMChapterAgenda` lists the appendix's slides, not the
  installation slides its text announces ("folgen auf den nächsten Folien").
- Its intro paragraph is long, so the agenda has less room than on `1dt`, the appendix's own divider, which has no
  finding.
- The agenda (`latex/SlideMage_base.tex`, comment at about line 5798) is two columns and picks `\normalsize`, `\small`
  or `\footnotesize` by `\SMChapterAgendaMaxHeight`.

**Likely cause, not verified.** The test reported 0 findings at v10.19.0 (step 17c). Commit `90fc77e5` ("WIP: footnote
marker styles") then added one slide to both decks, probably `2mk-EN-Footnote-marker-styles` in the appendix, which
would add a row to the two-column list. Adding `t8w` to the appendix as a trial did not move the text at all, which
fits a list that only grows every second entry.

**Questions to settle first.** Why is `tks` at the end of the appendix: is it there on purpose, as a German example or
to keep the translation in the deck? `git log` on the decks should say. That decides the fix:

- If it is only parked there: move it, or give it a body that does not need the agenda.
- If it belongs there: shorten its intro. It is a translation of `1f8`, so check the `%% Translation of:` link and the
  version line; a changed slide usually shows `+` in `\setSlideVersion`.
- A `%% layout-check: skip bottom` comment only hides this: the text overlaps the footer. Do not use it unless the user
  agrees. Changing the agenda's height rule touches `latex/` and needs the preview-equivalence pins renewed, so
  prefer a fix in the slide or the deck.

**How to check.** From the worktree, about 5 minutes:

```bash
PYTHONPATH="$(pwd -W)/src" SLIDEMAGE_TEX_TESTS=1 C:/Users/ms/SlideMage/venv/Scripts/python.exe -m pytest tests/test_manual_fits_templates.py -n 3 -q
```

**Done means:** that test passes for all templates, the slide reads correctly under them, and `VERSION_NUMBER` and
`src/slidemage/CHANGELOG.md` are updated in the same commit, with the next free number (check `origin/develop` and the
open PRs: numbers move fast here).

**Not part of this.** Two tests in `tests/test_citations.py` also fail on clean `develop`
(`test_the_fixture_asset_is_the_packed_fixture_folder`, `test_the_default_is_loaded_for_a_plain_deck_and_a_legacy_input_changes_nothing`).

---

# Own slides: from per-slide layout numbers to the framework

Written 2026-11-02. Status: **open.** Batch A is done and reviewed by the user; batches B to F are not started. Nothing is
running. Start a batch only on the user's go, and stop after each batch.

The user asked for what step 17c part B did for the manual (f2c37515): in `D:\uniCLOUD\Slidemaster`, replace per-slide
layout fixes with the framework, for example images sized from the available space. The plan with the six groups is
`docs/plans/own-slides-framework-fit.md` (main checkout, uncommitted). It names the user's private slides, so it must
never go into the public SlideMage repository; the private Slidemaster repository is its place if it is committed.

## Where things stand

- **Framework:** `\SMContentHeight` (Top Margin to Bottom Margin) is on develop since v0.13.18, the pin fixed in v0.13.19
  (PRs #59 and #71). The main checkout is at v0.13.19.
- **Slides:** batch A's 24 slides are committed on branch `framework-fit` in Slidemaster (f4f6929, the user's review in
  9d3bac7, the patch bump in fa96cfb). The branch is local, not pushed and not merged into `main`, and it is **checked out in the project**, so
  the user's compiles there use it. Whether and when it goes into `main` is the user's call; ask.
- **Not ours, leave alone in Slidemaster:** `.slidemage/bundled_copies.json`, `.slidemage/project.json`, `Future prompts -
  do not run on your own.txt`, the three deleted `media/screenshot-slide-template-*.png`, `.previews/`, the
  `decks/_slidemage_*` file. Commit only the slides of the batch, file by file.
- **Comparison page for batch A:** https://claude.ai/artifact/REAYqBsu9mjV7r73S3hcSA (private to the user).

## What is left

1. **Batch B — running, started 2026-11-03/04 on the user's go.** Image beside text with hand-computed heights and
   widths: dsk ice zwk cy9 xv8 e84 qdz fh6, plus wjx v5y c2t fuv zkx. zax is already done. This is where
   `\SMContentHeight` belongs. Preflight passed: the installed app's bundled framework already has it (checked
   2026-11-03). `brief-B.md` (adapted from `brief-A.md`, same folder) explicitly allows `\SMContentHeight` here, unlike
   batch A. Both baselines recorded clean before any edit (uni-graz: 21 entries/4379 pages/0 failed; greyscale: 7
   entries/1773 pages/0 failed; `C:\Users\ms\SlideMage\regression\own-slides-fit\reg\{graz,grey}\baseline.json`).
   Two sub-agents split the 13 slides 7/6. **Group 1 (dsk ice zwk cy9 xv8 e84 qdz): done**, reported in full — every
   slide's hand-derived length replaced by a named framework length (`\SMContentHeight` and combinations with
   `\SMImageBorderWidth`), one real bug fixed along the way (dsk overflowed the greyscale template before, not after),
   one slide (qdz) deliberately left alone (no `besidefigure`/`cornerfigure`/`fitfigure` fits its symmetric two-up
   layout, and it already used named lengths, nothing to replace); `check_layout` findings identical before/after on
   both templates except dsk's fix. **Group 2 (fh6 wjx v5y c2t fuv zkx): stopped partway**, hit its own session rate
   limit (resets 2026-11-04 01:50 Europe/Vienna) mid-way through c2t; its work so far is saved — resume with
   `SendMessage` to the same agent once the limit clears, don't start a fresh one. Not yet done for either group: the
   `compare` run against the baselines, the visual review, the comparison page, and the stop-for-review step the plan
   requires before any patch-bump commit.
2. **Batch C:** `\cornerfigure` with a fixed width beside full-width text, to `\besidefigure`: acw aqe bfa f6m h5z p8i za2
   zn5 zsg wmu wum i7z scs y4p zjs. Small logos and icons stay (baa y5z jky jkf qbj waj tgz).
3. **Batch D:** inline images and tables in fixed cm or pt, to fractions of `\linewidth`: shw h36 xci eaq szi n8e fm6 bbt nin
   dxg n3m qnb gi7 wvf pm2 and others. fmn, q3b and j6f are done.
4. **Batch E:** overlays at absolute page coordinates, anchored to what they mark: ayr sas dsk zwk y89 mpn m7c wjx c4c d76
   dh6 eau fiq gtt ha9 jae n2u nc8 neb nt5 p33 q3q s55 vtm w83 wbd x49. hbt, ni4, qq5, sch, svu and wmm are done.
5. **Batch F:** negative `\vspace`, removed, and the slide shortened or rebalanced if it then overflows (German partner too):
   cae crc djt ebq emv gk7 pgk q5x xqq y57 zve.
6. **Leftovers in batch A:** bwi (3.4cm) and d5j (3.642cm) plot heights can now use `\SMContentHeight`; a7b's 12pt offset
   above the Bottom Margin; hbt's manual `\\` line breaks; sch's fixed 2.1cm text box, which keeps the image off the corner
   diagram.

Fix the exact list when a batch starts, and do each slide once, in its first batch. On 2026-11-02 the search in the plan
still matched about 130 slides in the decks, including the manual's copies, the logos and a few false hits such as comments.
Not all of them are fixes.

**Slide versions (user, 2026-11-02):** "The slides get a patch bump." All 24 of batch A went from v1.0.0 to v1.0.1, and later
batches do the same, whether or not the change is visible. Bump last, after the user's review. If a leftover in item 6 is fixed
later, that slide gets another patch bump.

**Outside this work:** the manual's own 1pf and hd5 still use `width=98pt` screenshots. That is a fix for the SlideMage repo's
`example/`. The manual's slides copied into Slidemaster (1pf hd5 1vh 1w4 2v9 ZZL ZZO) stay out of these batches.

## How a batch runs

Helpers are in `C:\Users\ms\SlideMage\regression\own-slides-fit\`. Run them with the venv's Python.

- `fitdeck.py NAME <uni-graz|greyscale> <slide-id> ...` compiles chosen slides into a test deck, removes the deck again and
  runs `check_layout.py`. About a minute. Compile before editing as well as after.
- `graz.json` and `grey.json` are the regression configs for the seven course decks. `.build` is excluded on purpose: the
  user's app compiles there, and copying it while it changes makes the copy fail. Their `--out` folders need to be new.
- `gather2.py` pairs before and after pages by slide id, and `build_page.py` with `page_template.html` builds the comparison
  page. Both hold batch A's slide list, per-slide notes and folder layout, so adapt them, and keep them next to a `reg/`
  folder with the two `--out` folders, as `gather2.py` expects. `brief-A.md` is the sub-agent brief.
- `bump_a.py` makes the patch bump with the app's Update Version (`slide_versioning.update_version`): it first freezes each
  slide's content from before the batch, taken from git, as the old version, because edits outside the app freeze nothing.
  It holds batch A's slide list and commit, and assumes the old version is 1.0.0, so adapt all three; a slide can be at another
  version, and then its old version may already be frozen.

Order:

1. Record both baselines **before the first edit**, and leave the slides alone until each run has copied the project, or
   point `grey.json` at a snapshot of the project (about 950 MB). Batch A's baselines are out of date: record new ones.
2. Edit. Sub-agents with about 8 slides each worked; give them the brief.
3. Run `compare` for both configs, then look at the pairs yourself, under **both** templates.
4. Publish the side-by-side page of every visibly changed slide (the user asked for this), commit, stop for the review.
5. After the review, make the patch bump and commit the slides with their frozen versions.

Times on this machine with six jobs: Uni Graz record about 30 min, compare about 100 min; greyscale record about 15 min,
compare about 25 min. Compare recompiles every deck that differs one at a time, which is most of its time. The sub-agents of batch A hit the user's
usage limit on 2026-11-01, so say so before starting a batch's sub-agents.

## What the user wants to see, from the review of batch A

"Everything else looks very fine indeed", apart from these four, now fixed:

- A figure must not look stuck to what is above it. wki's diagram had to become smaller (0.62 of the line width); sch needed
  more space below the diagram above the image (`gap=14pt`).
- A figure must not be needlessly small when there is room. ni4's chart had to grow.
- Lines must not cross text. igr's arrows are now curved, level with the text and rising just before the chart.

## Traps

- **`check_layout.py` does not see a figure overlapping text.** A fixed-width ni4 chart ran over a list line under greyscale
  with 0 findings. Only looking at the page shows it.
- **`\fitfigure` with `top=here`** starts below what comes before it, and an overlay's `\vbox` before it adds space. Put it
  directly after the list. `gap=` is 6pt by default.
- **Sub-agents' size figures can be wrong.** One reported sch at 12.5cm against 8cm; the images showed about 10%.
- **A change to `latex/SlideMage_base.tex`, even a comment, changes its pin** in `preview_equivalence.py`, and renumbering
  a version in a comment counts. The hash is over the file with CRLF turned into LF. Recheck `tests/test_preview_equivalence.py`
  on the final commit, in a checkout nobody else is using. On 2026-11-02 PR #59 was merged with a stale pin, because the
  test passed in a worktree where another session had an uncommitted fix; that session repaired it in PR #71.
- **Other sessions use and merge branches here.** Version numbers move quickly, and a worktree you made can be in use. Look at
  `git status` and the latest commit before removing a worktree. On 2026-11-02 one was force-removed with another session's
  uncommitted version bump in it; that session recovered in its own worktree.
- **Git Bash mangled backslashes** in `sed -i` and `python -c` arguments, without an error. Use the Edit tool, or a script in a
  file, for TeX.
- ~~Not checked: whether the installed app `D:\SlideMage` compiles against the main checkout's `latex/` or its own copy.~~
  **Checked 2026-11-03, before starting batch B: it bundles its own copy**
  (`D:\SlideMage\_internal\slidemage_template\latex\SlideMage_base.tex`), and that bundled copy already defines
  `\SMContentHeight` (comment dates it to v0.13.18), so it is new enough — no blocker for batch B.

---

---

# Debug log: what is left

Written 2026-11-02. Status: **the plan is finished; the items below are open and none of them was asked for yet.** All
six steps of `docs/plans/debug-log.md` are in `develop` and in the release tagged v0.13.22 (merge `5467beca`). The
design and the decisions D1 to D5 are in that plan; `README.md`, "Logs and problem reports", describes the result.

- ~~Two citation tests fail on clean `develop`~~: **fixed by PR #87** (merged, `tests/packed-fixture-line-endings`;
  checked 2026-11-03, confirmed merged into develop).
- **The Settings note is more absolute than the manual.** Settings -> About says the log holds "no slide text and no
  API keys". The manual and the README say these are left out on purpose and tell people to look through a log before
  sharing it, because a traceback or a compile line can still carry a fragment. Soften the note in
  `src/slidemage/ui/dialogs/settings.py` to match.
- ~~The Presenter has no log.~~ **User decision (2026-11-03): not for the time being.** It still loads `diagnostics.py`
  through `app_settings` and `updater` but never calls `diagnostics.setup`, so its warnings and exceptions still reach
  no one in a windowed build — left as is, on purpose, for now. Revisit if the Presenter actually needs diagnosing.
- **Plugin authors.** The README explains `Host.log(level=...)` and `Host.debug_enabled()` (`requires_slidemage =
  ">=0.13.5"`). `stpalan/slidemage-plugin-template` and the website's plugin pages are not updated, and no plugin uses
  them yet.
- **A successful compile was not read end to end in a debug log.** A real compile ran with the log on, but it failed
  because the copied project could not find the framework, and the log recorded that correctly. `tests` cover the
  success path. Look at one real log the next time the debug log is on.
- **One test run hung.** A full suite under `-n auto` stopped at 99% for two hours on 2026-10-31 and was killed, with
  no stack dump. Later `test_batch_render`'s real-LaTeX test took over 2 minutes under load, which is the likely cause
  but not proven. Run long suites with `timeout` and `-o faulthandler_timeout=120`.

---

# Render store cleanup

Written 2026-11-02. Status: **open**. Steps 1 to 3 of 5 merged; steps 4 and 5 pending. Nothing is running, and no step may
start without the user's go.

The authority is `docs/plans/render-store-cleanup.md`: findings in its section 1, steps in section 2, decisions D1 to D3 in
section 3. It is on develop since 2026-11-03 (PR #86, merge `82754582`), and the main checkout is fast-forwarded to it.

## Why this exists

The user saw 10000+ renders in Settings, cleared them, compiled all views of all decks, and got 3973 renders. SlideMage
then started rendering 4289 previews at 0 %, although the user expected a full deck compile to refresh the previews. They
also saw the rendering status text jump upwards now and then.

## What is done

- **Step 1, the status text:** PR #76, v0.13.40. `BackgroundPreviews.refresh` called `adjustSize()` on the chip every second,
  which shrank it from 34 to 20 px until the layout ran again. It now runs only without a status row. A test covers it, but
  **nobody has seen the fix in the running app**.
- **Hyphenation tests on Windows:** PR #77, test change only. Two tests in `tests/test_language_tex.py` failed because their
  project sat under `%TEMP%` (see Traps). Hyphenation itself is fine.
- **Jürgen's content languages, PR #75:** merged at the user's request (v0.13.24 to v0.13.39); no one reviewed its code here.
- **Step 2, stale renders go:** PR #89, v0.14.4 (renumbered, see "Version collision" below). When a render of a unit is
  stored, delete older renders of the same label whose key the deck no longer uses; clear the existing leftovers once.
  Merged with `--admin` 2026-11-03, not yet seen in the running app.
- **Step 3, the double renders stop:** PR #91, v0.14.5 (stacked on step 2's branch, renumbered). In `scan()`, refresh a
  page number only if no other unit in the plan has the same key. Merged with `--admin` 2026-11-03, not yet seen in the
  running app.

### Version collision across #89, #90, #91 (resolved 2026-11-03)

Three PRs (step 2b of the tabs plan, and render-store-cleanup steps 2 and 3) all branched around the same point on
develop and each independently bumped `version.py`/`CHANGELOG.md` to v0.14.2 or v0.14.3, colliding with each other and
with a fix (#88) already on develop. Resolved by merging in dependency order in a scratch clone (the main checkout's
`.git` was mid-sync and had missing objects at the time — see "Loose ends"), renumbering each on top of the latest
develop: #90 -> v0.14.3, #89 -> v0.14.4, #91 (stacked on #89) -> v0.14.5. Each renumbered CHANGELOG chain was checked
with `packaging/release_notes.py <tag> --previous v0.14.1` before pushing. All three merged with `gh pr merge --merge
--admin`.

## Pending, in order

Each step is one PR with its own version and CHANGELOG entry, and a pause for the user's go after it.

1. **Step 4, a deck compile counts as finished.** `ingest_compile` stores every page of a slide, without `partial`, and
   `Lookup.final` accepts that. Only `\slidestep` and `\slidefinal` calls stay with the sweep, about 32 units. **Start by
   checking the reveal bar** (see D1 below). Then, on the real project, compile all views, confirm what the sweep has left,
   and time the ingest. Steps 2 and 3 are merged (see above); step 4 can start on the user's go.
2. ~~Step 5~~, **confirmed done by #75** (checked 2026-11-03): `languages_for` (`background_renders.py:388`) starts from
   `deck_language_code`, the deck's own `\decklanguage`, and extends it with the project's other languages only via the
   second-language setting — never the language last viewed. No code change needed; worth a real-project sanity check
   whenever step 4 runs, but not blocking.

## What the user decided (2026-11-01)

- **D1, against my recommendation:** for `\SMFinalStateForStudents` slides (54 files, about 142 units), the PDF counts as
  finished in student views, and the reveal bar shows one step there. The instructor view keeps every step. Open risk: the
  bar's rows (`reveal_bar.py`, `RowSpec`, the "deck steps only" switch) may expect more pages than are stored.
- **D2:** contents, agenda and section slides (about 300 units) also come from the PDF. `ingest_compile` must then call
  `deck_units` with a `context_ready` that says yes.
- **D3:** a slide called twice with one key keeps one render, with whichever page number it has. The user does not mind which.

## Traps

- **Never delete stale renders by label alone.** A slide called twice in a deck has one label but can have two current keys:
  `g96-EN-Climate-Impact-Beliefs` and `jww-EN-Pecking-Order-Theory`, 3 views each. Deleting by label would make them delete
  each other for ever. I first took these 6 for leftovers of edits and told the user so, wrongly.
- **`%TEMP%` on Windows.** Git for Windows' Perl calls it `/tmp`, and `.latexmkrc` converts only `/c/...` paths, so a project
  there is not on `TEXINPUTS`. Tests that need a project's own files use the `ctx_on_tex_path` fixture in
  `tests/test_language_tex.py`.
- **Auditing the store while the app runs.** To do it safely, copy `index.sqlite` with SQLite's backup API, build
  `RenderStore(ctx, local_dir=copy)` with `forget_project_copy` patched out, then set `store.root` to the real folder. The
  store is `%LOCALAPPDATA%\SlideMage\render-store\2560ac40a2eab96a` for `D:\uniCLOUD\Slidemaster`, whose disk limit is 10 GB.
- **Old numbers.** Every count here and in the plan was measured on 2026-11-01. The project's slides and the store have changed
  since; #75 also changed how languages work, so recheck `languages_for` and `deck_language_code` before step 5.

## What is inferred, not proven

- **Why there were 10000 renders.** Those renders are gone. The code leaves old renders when a slide or preamble changes, and 1049
  of 3398 slide files and 22 deck files changed in the 30 days before, which fits.
- **The layout difference on contents and section slides.** 73 of 258 background renders differ from the PDF's last page. In the 4
  compared by eye the content was the same but the layout was not. Cause not traced; D2 takes the PDF's version instead.
- **About 45 units needing their deck had no background render.** Not checked why.
- **The pixel comparison of ordinary slides** covered 393 slides from the first decks alphabetically, not all decks.

## How to work

- **Merging:** a plain `gh pr merge` is refused by the rule on `develop`. The user approved `gh pr merge <n> --merge --admin` for
  #75, #76 and #77 by name; ask each time. Run it as a bare command, not in a loop or after `cd`.
- **Versions:** `develop` moves quickly, so take the next free version just before the PR and check with
  `packaging/release_notes.py`. No parentheses in a CHANGELOG reason. A change to tests only needs no bump.
- **Tests in a worktree:** `PYTHONPATH="$(pwd -W)/src" C:/Users/ms/SlideMage/venv/Scripts/python.exe -m pytest tests -n auto`.
  Without `PYTHONPATH` they silently test the main checkout.
- **Last full suite** (before #77, on the #76 branch): 4453 passed, 75 skipped, 8 failed.
  - `test_language_tex` (2): fixed by #77.
  - `test_citations` (2): fail every time; not investigated.
  - `test_accessibility_gui`, `test_reveal_bar_gui`, `test_tasks_gui` (1 each): fail only in parallel runs. Across 6 runs each of the
    three files, clean `develop` had a failure in 3 and the #76 branch in 5, on different tests each time; too few runs to
    rule anything out, though #76 only skips one sizing call.
  - `test_preview_requests::test_cache_identity_reads_the_raster_version_once`: failed twice on the #76 branch, then passed 3 of 3.

## Loose ends

- **2026-11-03: the main checkout's `.git` had missing objects while uniCLOUD was still syncing the folder** (`git fsck`
  showed missing trees/commits, `git diff`/`git log` on some commits failed with "bad tree object", and the reflog shows
  this has happened before — "re-parent plans commit onto e3df3b66 after sync rollback"). A plain `git fetch origin`
  re-downloaded the missing objects and fixed it (the object store is many small files, which a file-level sync tool can
  desync from git's own refs; fetch is safe to retry any time this happens again). Separately, the working tree had five
  files (`example/decks/slidemage-manual-*.tex`, `example/slides/tks-DE-Chapter-Installation-current.tex`,
  `tests/test_citations.py`, `tests/test_theme_sources.py`) already matching a newer commit's content than `HEAD`, also
  from the sync; stashed, fast-forwarded, then dropped the stash once confirmed identical to the new tree — the usual
  "look before `git restore`/`checkout`" rule applies if this recurs, but it was safe here only because the diff against
  the fetched `origin/develop` was empty.
- **2026-11-03: the main checkout is now fast-forwarded to `origin/develop` (past #89, #90, #91).**
- v0.14.0 is tagged at `20d13750` and `D:\SlideMage` is a local build of it (2026-11-02), with the old app in
  `D:\SlideMage-v0.13.22-backup`. v0.14.0 replaced the release v0.13.41, withdrawn with no downloads. **It converts
  `media/alt-text.json` the first time a project is opened, and older versions then refuse to write it:** update every machine first.
- `.claude/worktrees/render-store-step1` is detached at v0.14.0. Its branches are merged, so it and the
  branches can go, with the user's OK.

---
