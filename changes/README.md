# Changelog fragments

Every PR that changes the app (`src/slidemage/`, `add_deck_headers.py`) adds one file here and leaves
`VERSION_NUMBER` in `src/slidemage/version.py` and `src/slidemage/CHANGELOG.md` alone. Separate files never
conflict, so PRs open at the same time no longer collide over the version (issue #247).

Name the file after the branch, with `/` turned into `-`: `fix-scan-and-stuck-renders.md`. Any unique name works.

```
kind: fixed
reason: direct request: "Render now" did nothing and the debug log did not say why

The technical description, as a CHANGELOG entry's text used to be: what changed, in which modules, which tests.
Further paragraphs are separated by blank lines. Use plain backslashes for LaTeX commands.

NEW: An optional one-sentence summary.
- One bullet per change users notice, in plain words: what they can do now, what was fixed. No module names.
```

- `kind`: `fixed` (a fix), `new` (a feature or a visible change) or `breaking` (a project, deck, setting or
  workflow that worked before no longer does, or now behaves differently; raising `project.PROJECT_FORMAT` is
  always breaking).
- `reason`: why: `direct request: ...`, `issue #252 step 3 of docs/plans/ui-stalls.md`, ...
- A `breaking` fragment also has `compat: <id>[, <id>]`, naming its entries in `slidemage.compat.CHANGES`, and a
  paragraph starting `BREAKING:` that says what changes and what to do about it. Those `CHANGES` entries use
  `since="NEXT"`: the release puts the version in.
- Exactly one `NEW:` paragraph with at least one `- ` bullet.

Check: `python -m slidemage.change_fragments --check` (the PR check runs it too).

**Releasing** (`packaging/make_release.py`): it works out the version from the biggest kind among the fragments
(0.x: `breaking` raises the minor, anything else the patch; from 1.0: major / minor / patch), writes one
CHANGELOG entry for the release, sets `VERSION_NUMBER`, replaces `NEXT`, deletes the fragments, then commits and
tags. See the README, "Releases and updates".
