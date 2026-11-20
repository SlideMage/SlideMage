# Installing a package re-renders only what uses it: implementation steps

Status: **started 2026-11-19.** Orchestrated by the main session; Sonnet and Haiku subagents implement. One
branch, `fix/pkg-rerender` (worktree `.worktrees/pkg-rerender`), one commit per step. Base: `develop` at 3e7142f9 (v0.17.23). Names and line numbers below
were checked against that commit.

## The problem

On 2026-11-19 at 09:04 the APA citation package was installed. No deck in the project uses it (none sets
`\SMCitationFormat`, and neither does the Uni Graz template). Even so, the next background scan found
`2017 units, 0 fresh; reasons: no render: 2017`, and SlideMage started rendering every preview of the project
again. In the minutes after that, a new precompiled preamble format was built about once a minute.

Three rules make a package install, or even a new file, count for every render:

1. **The render key contains every package folder.** `compiler.build_env` puts the folders of installed theme and
   citation packages on `TEXINPUTS` (`compiler.py:646-654`, through `packages.texinputs`). The key
   (`render_key.Resolver.fast_key`, `render_key.py:177-193`) contains `configuration_state`, which contains every
   `TEX*` environment variable (`render_evidence.py:255-276`). Installing the first package of a kind, or any
   further package, changes `TEXINPUTS`, so every unit gets a new key and finds no record under it. Removing a
   package does the same. Updating one does not, because its folder keeps its name.
2. **Any citation or layout file name counts for every render.** `PROBES` (`render_evidence.py:28`) holds
   `SlideMage_citation_*` and `SlideMage_layout_*`. A name that matches a probe in any search folder goes into the
   `conservative` digest, which every render's inventory evidence compares. So even with rule 1 fixed, the new
   `SlideMage_citation_apa.tex` makes every render stale.
3. **The precompiled format counts every file in every search folder.** `preview_format._fresh`
   (`preview_format.py:135-142`) compares `search_state`, which walks the whole tree of every search root,
   including the project folder (`render_evidence.py:161-182`). A new slide file, which is what the AI chat was
   making at the time, makes every deck's format stale. That is the format built once a minute.

The log also misnames the first case. When a unit's key changes, `lookup` reports `no render`
(`render_key.py:367`), although a render of the unit is stored under its old key.

## What TeX actually depends on

- The base loads exactly one citation file: `SlideMage_citation_\SMCitationFormat.tex` (`SlideMage_base.tex:6330`).
  The setup loads exactly one layout file: `SlideMage_layout_\SMLayoutProfile.tex` (`SlideMage_setup.tex:176`).
  When that file is missing, both raise a `\PackageError`, so the render fails. Neither falls back silently.
- A file a render reads is recorded (`.fls` → manifest → `tex_files`). A new file of the same name anywhere on the
  search path is caught by the `stems` part of `inventory_state`, which covers shadowing.
- A failed render records the inputs TeX could not find: `preview_build.py:705` reads
  ``LaTeX Error: File `x' not found``, and `preview_requests.py:416` stores them through
  `missing_input_entry` (`render_key.py:276-281`), so making such a file available invalidates the failure.
  Today this only catches `\input` of a missing file, not SlideMage's own `\PackageError`s.

So a package folder on the path, and the names of formats no render reads, change no render. The one case the
wildcard covers on its own is a render that failed because its format or profile was missing. Step 3 moves that
case to the missing-input mechanism.

## Goal

Installing, removing or updating a theme or citation package re-renders only the units that read a file from it,
or that failed because a file it provides was missing. Adding a slide does not rebuild any preamble format. Every
render that really changes is still caught; when in doubt, re-render.

## How the steps run

Same rules as the earlier plans ([run-plan-steps-without-pausing], [simple-clean-concise-code],
[oom-safe-test-runs]):

- One branch per step, stacked: `fix/pkg-rerender-1` from `develop`, each next step from the previous one.
- Each step writes its failing test first, then the change. It runs its own tests and the render tests
  (`tests/test_render_key.py`, `tests/test_preview_*.py`, `tests/test_framework_probes.py`,
  `tests/test_background_renders.py`), capped, one run at a time. The full suite runs once, at step 5.
- Version and changelog: one entry per step under the scheme still in force. If #247 lands first, use a change
  fragment instead.
- No push or PR before the user has tested step 5's build. Then: one PR for all steps, into `develop`, from a
  branch on SlideMage/SlideMage.

## Steps

### Step 1: Tests that show the problem

Add `tests/test_package_install_rerender.py`. It sets up a project with a stored render (the fixtures of
`tests/test_render_key.py` / `tests/test_background_renders.py`) and checks, through `RenderKeyResolver.lookup`:

- a. Installing a citation package that no deck uses leaves the render `FRESH`.
- b. Installing a theme package that no deck uses leaves the render `FRESH`.
- c. Removing an unused package leaves it `FRESH`.
- d. A deck whose `\SMCitationFormat` is `apa`, with no APA installed, fails. After installing APA, the failure is
  no longer `FAILED`, so the render runs again.
- e. The same as d for a layout profile named by the template.
- f. Copying a package file into the project folder (a file of the same name earlier on the search path) makes the
  renders that read it stale. This holds today and must stay so.
- g. Adding a slide file does not make the precompiled format stale (`preview_format._fresh`).

a, b, c, d (after step 3), e and g fail on `develop`; f passes. Mark the failing ones `xfail(strict=True)` with the
step that fixes each one, and remove the marks in that step.

### Step 2: The key leaves out package folders (cause 1)

In `render_evidence.configuration_state`, drop from `TEXINPUTS` the entries that are installed package folders
(`themes.installed_dirs()`, `citations.citation_dirs()`, or the two package parents `themes.themes_dir()` and
`citations.citations_dir()`) before the environment goes into the evidence. `search_roots` keeps reading the
full `env`, so files from package folders are still recorded inputs and still count in `stems`.

- Keep it one small helper, e.g. `_without_package_dirs(value)`, used only there.
- `preview_format._fresh` and `configuration_state`'s other callers get the same evidence; check that a theme
  update (same folder, new file contents) still makes the format and the renders stale through their inputs.
- One-time effect: every stored key changes once, because the configuration digest does. Bump
  `render_key.RENDER_SCHEMA` only if the tests show a mixed state; otherwise say in the changelog that previews
  render once more after this update.

Step 1 found two more things this step must do:

- **Empty roots out of the conservative digest.** `search_inventory` keys `conservative` by every search root, so
  a new package folder adds a key (an empty list) and changes the digest. Leave out roots with no probe names and
  missing roots (`None`).
- **Package files count for shadowing.** `background_renders.store_render` (`background_renders.py:911`) and
  `Resolver.lookup` (`render_key.py:381`) build the inventory `paths` from the slide and the manifest's relative
  names only, not from the absolute `tex_files`. So a project copy of a file the render read from a package (a
  copied theme template) does not make the render stale today. Add the `tex_files` paths to `paths` in both places
  (and in `publishable`, which already lists them), so their stems are compared.

Test b, c[theme] and f[package] pass. a and c[citation] stay xfail until step 3 (the probe name).

### Step 3: Missing formats and profiles are recorded inputs; drop the two wildcards (cause 2)

1. Make the two `\PackageError`s name the missing file in a form the failure parser reads. Either put the file
   name in the error message in the same form as LaTeX's
   (``File `SlideMage_citation_apa.tex' not found``), or add one more pattern to `preview_build.py:705` for
   SlideMage's message. Prefer the first: one regex stays the only reader.
   `SlideMage_base.tex:6330-6337` and `SlideMage_setup.tex:176-179`.
2. `missing_input_entry` (`render_key.py:276-281`) looks for the name in the decks folder, template folders and
   citation folders. Add the theme package folders, because a layout profile can live next to its template in a
   theme package.
3. Remove `SlideMage_citation_*` and `SlideMage_layout_*` from `PROBES`. Update the audit in
   `tests/test_framework_probes.py`: a probe whose name contains `\SMCitationFormat` or `\SMLayoutProfile` must now
   sit in an `\IfFileExists` whose false branch raises the error that step 3.1 made parseable. The fixed counts at
   the end of the test do not change.
4. Update the comment above `PROBES`.

Test a, c[citation], d, e pass; f still passes. The `\PackageError` message must keep the file name on one log
line: the log wraps at 79 columns and the regex at `preview_build.py:705` reads `[^\n]+?`.

### Step 4: The precompiled format checks names, not whole trees (cause 3)

`preview_format._fresh` compares `search_state`, the full list of files under every search root. Replace that
with the evidence renders use: `search_inventory` plus `inventory_state` over the format's recorded inputs
(`format.json`'s `inputs`). That covers the conservative probe names and a new file with the stem of anything the
preamble read. Keep `search_state` only if another caller needs it; otherwise remove it.

- Bump `preview_format.SCHEMA` (the `4-` in `preview-formats/4-<key>`), since `format.json` changes shape. Old
  folders are swept by the existing cleanup in `preview_build.py:226`.

Test g passes.

### Step 5: Name the reason, check in the app, finish

1. In `RenderKeyResolver.lookup`, when no record exists under the key but `store.latest_for_unit(unit.label)`
   finds one, report `why="key changed"` instead of `no render`, so the scan log tells the two apart.
2. Full test suite, once, capped.
3. Build and run the app from the branch with `SLIDEMAGE_DEBUG=1` ([test-builds-debug-log],
   [one-app-per-render-store]) on `~/tmp/slidemaster-library-test`, after the store has caught up:
   - remove APA, then install it again from Settings → Extensions → Citation formats: the next scan reports no
     units stale;
   - insert a slide: no new folder appears in `.build/preview-formats`;
   - set `\SMCitationFormat{apa}` in one deck: only that deck's units re-render.
4. **USER GATE:** the user tests the build. After their go: push, one PR into `develop`.

## Not in this plan

- `SlideMage_project_macros.tex`, `*.bib`, `.latexmkrc`, hyphenation and alt-text probes stay. They are single
  fixed names or are read by every render.
- Fewer re-renders after a template change (the 1795 stale units of 2026-11-18). Those renders did read the
  changed template, so re-rendering them is correct.
- The versioning scheme (#247).
