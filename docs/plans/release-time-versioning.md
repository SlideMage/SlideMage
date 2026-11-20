# Release-time versioning (issue #247)

Goal: a PR no longer touches `VERSION_NUMBER` or the end of `CHANGELOG.md`. It adds one fragment file; a release
collects the fragments, works out the version, writes one CHANGELOG entry and tags. Two open PRs then never conflict
on versioning.

Existing history entries stay as they are. The scheme starts with the first release after this lands.

## What is there today (checked on develop 9e4977f2, v0.17.38)

- `src/slidemage/version.py`: `VERSION_NUMBER` (hand-bumped), `parse_history()` (regex over `vX.Y.Z (meta): ...`
  entries; the last `NEW:` paragraph of an entry gives `summary`/`news`), `VERSION` = number plus commit date for
  source runs.
- Readers of `parse_history()`: `ui/dialogs/about.py` (Info → Version history), `packaging/release_notes.py`,
  `tests/test_compat.py` (each `BREAKING:` entry needs a `compat.CHANGES` entry with that `since`),
  `tests/test_release_notes.py`.
- `packaging/release_notes.py <tag>`: entries after the previous tag up to `<tag>`, summary of the tagged entry,
  all bullets, `## Breaking changes`; exit 2 for a minor (0.x) bump without `BREAKING:`, exit 3 for a missing `NEW:`.
- `.github/workflows/changelog-check.yml`: runs `release_notes.py` on `VERSION_NUMBER` for PRs that touch
  CHANGELOG/version.py. It picks the previous tag with `git tag --sort=-v:refname`, which sorts the legacy `v8.*` tags
  above `v0.17.*`; the new check below picks it by `updater.parse_version` instead.
- `.github/workflows/release.yml`: on a `v*` tag, requires tag == `VERSION_NUMBER` (build and presenter jobs),
  builds the notes, builds and attaches. Tags sit on develop; releases have been several a day.
- `compat.CHANGES[*].since` names a version; `compat._tuple()` returns None for anything else and `evaluate()`
  then skips the change. `project.PROJECT_FORMAT` is an int and names no version. `requires_slidemage` is only
  checked in this repo; plugins and themes set it in their own repos.
- The bump rule is repeated in: the CHANGELOG intro, README "Releases and updates", `.claude/skills/finish/SKILL.md`
  (steps 1-2: bump, renumber on conflict), `.claude/skills/handover/SKILL.md` (step 4), `.claude/agents/*`
  briefs, `docs/handover.md` "How to work" (not in git), and several `docs/plans/*` (historical; leave those).

## Design

### 1. Fragment files: `changes/<branch-name>.md` (repo root)

```
kind: fixed            # fixed | new | breaking
reason: direct request: "Render now" did nothing
compat: some-change-id # breaking only; one or more ids, comma-separated

Technical description, one or more paragraphs (goes to CHANGELOG.md, as today's entry body).

NEW: Optional one-sentence summary.
- Bullet in plain words.

BREAKING: What breaks and what to do (breaking only).
```

- Header lines `key: value` up to the first blank line; then the body in today's entry format.
- Name: the branch name with `/` → `-` (`fix-scan-and-stuck-renders.md`). Any unique name works; one PR may add more
  than one.
- Repo root, not `src/slidemage/`: a frozen build is made from a tag, where the folder is empty, so it is not bundled.
- `changes/README.md` holds the format and is ignored by the parser.

New module `src/slidemage/change_fragments.py`:
- `Fragment` dataclass (path, kind, reason, compat ids, paragraphs, summary, news, breaking) and `read_all(folder)`.
- `problems(fragment) -> list[str]`: unknown kind; no `NEW:` bullets; `breaking` without a `BREAKING:` paragraph or
  without a `compat:` id; a `BREAKING:` paragraph in a non-breaking fragment; a `compat:` id missing from
  `compat.CHANGES` or whose `since` is not `NEXT`.
- Reuse `version._parse_news` (make it public as `parse_news`).
- `python -m slidemage.change_fragments --check [files]` prints problems, exit 1 if any (used by CI and the release
  script).

### 2. Version arithmetic: `next_version(last, kinds)`

In `change_fragments.py` (pure, tested):
- 0.x: any `breaking` → minor + 1, patch 0; otherwise patch + 1.
- ≥ 1.0: `breaking` → major + 1; `new` → minor + 1; `fixed` → patch + 1.
- `last` is `VERSION_NUMBER` on develop, which after this change always equals the last release tag.

### 3. Placeholder `NEXT`

- `compat.CHANGES` entries added by a PR use `since="NEXT"`.
- `compat._tuple("NEXT")` returns the running `VERSION_NUMBER` plus one patch step, so a source run (whose
  `VERSION_NUMBER` is the last release) applies the change, and `since > current` never skips it.
- To check while implementing: `acknowledge()` stores `checked_version` = `VERSION_NUMBER`. After the release a change
  stamped `vX.Y.(Z+1)` is above that, so a project opened in a dev build is offered it once more. Detectors find
  nothing by then; if the sheet still shows, record applied ids too (`compat.dismissed_ids` already exists) so a
  change applied in a dev build is not offered again.
- The release script replaces `"NEXT"` with the new version in `src/slidemage/compat.py` (the one place it is
  allowed; a test fails `NEXT` anywhere else in `src/`). Plugins and themes keep naming released versions.

### 4. Release script: `packaging/make_release.py`

`python packaging/make_release.py [--dry-run] [--summary "..."] [--publish]`, run on an up-to-date develop:

1. Read and check all fragments (stop on any problem, or when there are none).
2. Version = `next_version(VERSION_NUMBER, kinds)`.
3. Append one CHANGELOG entry:
   `vX.Y.Z (YYYY-MM-DD, release of N changes): <each fragment's technical text, prefixed by its reason, as its own
   paragraph; breaking first, then new, then fixed>`, then one merged `NEW:` paragraph (summary from `--summary`,
   else the summary of the only fragment, else none; all bullets), then each `BREAKING:` paragraph.
   One `NEW:` paragraph per entry, so `parse_history()` needs no change.
4. Set `VERSION_NUMBER`, replace `NEXT` in compat.py, delete the fragments (keep `changes/README.md`).
5. Run `release_notes.py <version>` as the final check; `--dry-run` prints the entry and notes and writes nothing.
6. `--publish`: branch `release/vX.Y.Z`, commit "Release vX.Y.Z", push, `gh pr create`, `gh pr merge --admin --merge`,
   tag the merge commit `vX.Y.Z`, push the tag. (develop is merged with `--admin`, so a direct push is not assumed.)

`release.yml` keeps the tag == `VERSION_NUMBER` check and gains one: no fragments in `changes/` and no `"NEXT"` in
compat.py at the tagged commit.

`release_notes.py` needs no logic change: with one entry per release, `history_since()` returns that entry and the
"This release covers" line drops out by itself. Keep it for re-building old releases; update its docstring.

### 5. CI: `changelog-check.yml` becomes the fragment check

On every PR to develop:
- Changed files under `src/slidemage/**` (minus `CHANGELOG.md`) or `add_deck_headers.py` → at least one added file in
  `changes/`, unless the PR has the label `no-changes-entry` (tests-only or docs-only touches of `src/`).
- Every added or changed fragment passes `change_fragments --check`.
- `VERSION_NUMBER` and `CHANGELOG.md` unchanged, except on a `release/*` branch.
- On `release/*`: today's `release_notes.py` run, with the previous tag picked by parsed version.

### 6. Version string between releases

`version._compute_version_string()`: when `changes/` beside the checkout holds fragments, or HEAD is not the tag
`VERSION_NUMBER`, show `v0.17.38+dev (3e7142f9, 2026-11-18 14:02)`; on the tagged commit, as today. Only the display
string changes; `VERSION_NUMBER` (updater, project.json, plugin checks) stays a plain release number.

### 7. About sheet

`about.py`: on a source run with fragments, an "Unreleased" block on top with each fragment's `NEW:` bullets (and the
technical text under "show more"), then the history as today.

### 8. Tests

- `tests/test_change_fragments.py`: parsing, every `problems()` case, `next_version()` for 0.x and ≥ 1.0, the
  fragments currently in `changes/` all pass.
- `tests/test_make_release.py`: on a temp copy (CHANGELOG, version.py, compat.py, fragments): the entry text, the
  version, `NEXT` replaced, fragments gone, `parse_history()` reads the new entry with all bullets, `release_notes.py`
  accepts it; a breaking fragment raises the minor and its `BREAKING:` reaches the notes.
- `tests/test_compat.py`: the BREAKING ↔ CHANGES test also accepts `since == "NEXT"` with a breaking fragment naming
  the id; `NEXT` only in compat.py.
- `tests/test_version.py`: the `+dev` string.

### 9. Instructions to rewrite

- CHANGELOG.md intro: drop the bump instruction; say entries are written by `make_release.py` from `changes/`, point to
  `changes/README.md`; keep the history-format and BREAKING/NEW explanations (they now describe fragments).
- README "Releases and updates": the new two-step release (`make_release.py --dry-run`, then `--publish`).
- `.claude/skills/finish/SKILL.md`: "add a fragment" instead of "bump and append"; drop "renumber the version if it was
  taken"; keep the `NEW:` warning, pointed at the fragment check.
- `.claude/skills/handover/SKILL.md` step 4 and the `.claude/agents/*` briefs that repeat the rule.
- `docs/handover.md` "How to work" (main checkout only, not in git): same change.

## Order of work

One PR (`chore/release-time-versioning`), in this commit order so each commit is testable:

1. `change_fragments.py` + `changes/README.md` + tests (nothing uses it yet).
2. `NEXT` in compat + its tests.
3. `make_release.py` + tests; `release.yml` guard; `release_notes.py` docstring.
4. CI check rewritten.
5. `+dev` version string and the About sheet's Unreleased block.
6. Docs, skills, agent briefs, CHANGELOG intro, README.
7. This PR's own `changes/release-time-versioning.md` (kind `new`); no `VERSION_NUMBER` bump. The first release after
   the merge is made with the script: `--dry-run` first, check the notes, then `--publish`.

Open PRs at merge time still bump the old way; each needs its bump undone and a fragment instead (the finish skill's
step 2 says so until none are left).

## Out of scope (follow-ups)

- The same scheme for exam-forge, campusonline, the theme and citation packages (each has its own CHANGELOG and
  release flow).
- Automatic releases (a workflow that releases on every merge or on a schedule): possible later on top of
  `make_release.py --publish`, once the manual flow has run a few times.

## Decisions for the user

1. **Release cadence.** Today nearly every merge is released. With fragments, release when wanted (manual
   `make_release.py --publish`), or keep one release per merge by running it right after each merge. The plan assumes
   manual.
2. **Fragment location** `changes/` at the repo root (plan), or `src/slidemage/changes/` (would let a frozen build show
   Unreleased, but there never are unreleased fragments in a tagged build).
3. **Release entry meta**: `(date, release of N changes)`, or keep each fragment's reason as a sub-heading only.
