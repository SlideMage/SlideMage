# Integrate develop into PR #1

Prepared 13 October 2026 for [PR #1 — UI redesign](https://github.com/stpalan/SlideMage/pull/1). Planning only; no application changes, merge commit, push, or PR update performed.

## Recommendation and verified baseline

Merge `develop` into the PR's `ui-redesign` branch, preserving the redesigned workspace and porting the newer behavior into its current modules. Use an isolated integration checkout. Keep the PR based on `develop` and preserve its existing history.

The GitHub branch-ref API confirmed these tips; both objects were already available locally:

| Revision | Commit |
| --- | --- |
| PR head: `ui-redesign` | `a57ee536f0373e215b62f15f729725b9e02865f0` |
| Current `develop` | `f8a250b5a9b02ddc74334df5d20ab12ca2ae890e` |
| Merge base | `1fb74f1cc47c45e36da4752f14095ab55af773ff` |

GitHub reports the PR as conflicting. A local `git merge-tree --write-tree` against the verified tips, in a disposable clone under `/tmp`, found **nine conflicted paths: six content conflicts and three modify/delete conflicts**. The six develop-only commits touch 15 files. The PR API's embedded `base.sha` reported the older merge-base revision; this analysis uses the separately verified current `heads/develop` ref.

The working checkout is on `ui-redesign` at `07c0ea5`, one documentation commit ahead of the PR, with existing modified/untracked planning documents. A separate `streamlining` worktree also exists. Leave those changes intact and recheck branch tips before implementation; this plan covers PR #1, not an automatic merge of the sibling work.

## Incoming changes and destinations

Paths below are relative to the repository root; application modules are under `src/slidemage/`.

| Develop commit | Behavior to retain | Destination in the redesign |
| --- | --- | --- |
| `7a0df81` — v5.35.4 | User-facing release summaries and bullets; missing-news gate; separate breaking changes and changelog sections | `version.py`, `CHANGELOG.md`, `packaging/release_notes.py`, `.github/workflows/release.yml`, README |
| `fcc45b3` — v5.35.5 | Declining a slide switch leaves both the displayed slide and actual list selection unchanged after a mouse click | `ui/pages/images.py`, `ui/pages/image_nav.py`; port GUI regressions |
| `c1c6e33` — v5.35.6 | Filter/order changes preserve the current slide and translation; filtering it out asks before discarding a translation | The same Images page/navigation modules |
| `0ff39bd` — v5.35.7 | Locked build files cannot turn a completed render into a hanging job; unexpected failures terminate visibly | `slide_preview.py`, `preview_build.py`, `ui/workspace/preview_view.py`, existing compile-log helpers |
| `4db7a75` — v5.35.8 | Temporary single-slide render PDFs expire after at least 24 hours, swept after rendering and shortly after startup | Shared render cleanup plus `ui/workspace/maintenance.py` |
| `f8a250b` — v5.36.0 | `\SMSubsectionAgenda`: subsection titles linked to first slides, with matching transcript entries | `latex/Slidemaster_preamble_base.tex`, `transcript.py`, navigation tests, documentation |

## Resolution of every conflicted path

| Conflicted path | Resolution |
| --- | --- |
| `README.md` | Combine the redesign's `CHANGELOG.md` location with develop's `NEW:` authoring instructions and subsection-agenda documentation. |
| `packaging/release_notes.py` | Retain develop's summary/bullet aggregation and validation; make documentation and errors consistently name `CHANGELOG.md`. |
| `src/slidemage/version.py` | Keep the small parser module, lazy version string, and shared process helper. Add `HistoryEntry.summary`, `.news`, and news parsing while continuing to read `CHANGELOG.md`. Move incoming history prose there. Keep the newer version series. |
| `src/slidemage/slide_preview.py` | Integrate lock-tolerant output/cleanup into the current `compile_and_extract` implementation, retaining cached builds, the shared subprocess runner, dependency recording, and build reservations. |
| `src/slidemage/transcript.py` | Add subsection metadata and agenda expansion on top of `deck_language.deck_slots()` and `SlideCall.included_in()`. Preserve linked-language resolution and current parsing fixes. |
| `tests/test_review_gui.py` | Keep the workspace fixtures and `window.log_drawer` assertion; move adapted Images regressions into `tests/test_images_page_gui.py`. |
| `src/slidemage/qt_gui.py` (deleted on PR) | Keep deleted; port delayed render sweeping to `ui/workspace/maintenance.py`. |
| `src/slidemage/qt_slide_source_tab.py` (deleted on PR) | Keep deleted; retain the current preview worker's exception handling and ensure error completion/logging covers the old fix. |
| `src/slidemage/qt_transcript_tab.py` (deleted on PR) | Keep deleted; port selection/filter behavior into the current Images page and navigation. |

Also review the six paths Git merges cleanly: `.github/workflows/release.yml`, `docs/SlideMage.md`, `latex/Slidemaster_preamble_base.tex`, `tests/test_navigation.py`, `tests/test_release_notes.py`, and the new `tests/test_slide_preview_cleanup.py`. Clean text merging does not establish compatibility with the new APIs.

## Implementation sequence

### 1. Prepare an isolated integration branch

- Refresh both remote tips and repeat the dry merge if either changed. Use authenticated HTTPS if SSH fetch remains unavailable; the inspection's SSH fetch failed, but GitHub API reads succeeded.
- Create an integration branch from the intended `ui-redesign` tip in a separate checkout. Record exact parent commits and baseline test results there.
- Start a non-fast-forward merge of `develop`, leaving it uncommitted while resolving the following workstreams. Resolve the three deleted modules by retaining their deletion only after mapping their behavior to the replacements above.
- Preserve the redesign's workspace, responsive layout, EN/DE linked slides, providers and Claude tools, optimized previews, and previous review fixes. Avoid unrelated refactoring.

### 2. Integrate release notes and history

- Add develop's history entries v5.35.4–v5.36.0 once, in version order before v6.0.0 in `CHANGELOG.md`. Extract their actual text from the Python docstring so escaped LaTeX backslashes become plain Markdown backslashes.
- Extend the existing file-backed parser with develop's `NEW:` summary/bullet handling; preserve technical paragraphs and `BREAKING:` detection.
- **Backfill the 33 existing redesign entries from v6.0.0 through v8.2.1 that lack `NEW:` paragraphs.** Develop requires news for every included history entry newer than v5.35.3. Adding only an integration-release summary would still fail a bundled release. Use accurate concise bullets, including truthful “maintenance; no user-visible change” descriptions where appropriate; retain the full technical history.
- Keep `generate_release_notes: false` and the explicit Full changelog heading so the updater does not mistake the changelog link for a breaking change.
- Follow the repository's version policy for the integration commit: choose the next unused minor version at landing time because this adds subsection agendas; preserve any later version already landed from concurrent work. Never replace v8.x with v5.36.0. Add the integration entry with `NEW:` bullets; retain existing breaking-change and compatibility entries.
- Verify the packaged app still includes `CHANGELOG.md` and the About history still reads it.

Acceptance: legacy notes still render; actual post-v5.36.0 bundled notes pass the news gate, include all intended bullets, and expose only breaking-change text to the updater.

### 3. Port Images navigation fixes

- Retain the redesign's draft-saving behavior. The old unsaved-edit discard prompt was replaced by `ImagesPage.flush()`; port the data-preservation guarantee without restoring obsolete tab behavior.
- Preserve the selected slide by path across filter/order changes. If it remains visible, keep the same forms and running translation; do not rebuild them or prompt unnecessarily.
- Before a filter would remove the displayed slide, ask about an in-flight translation. On decline, restore the previous filter and selection without replacing forms; on acceptance, perform the normal switch, including an empty result list.
- Fix declined mouse-click selection restoration in `SlideNav`: restore immediately and after Qt finishes the click, guarded against a later accepted selection and widget destruction. Existing tests use `setCurrentRow()`, which does not reproduce the original mouse-event ordering bug.
- Port regression scenarios using real `QTest.mouseClick` and event processing. Cover filtering out a slide, retaining a non-first slide, changing order, and an accepted switch following a declined one. Confirm drafts remain attached to the correct slide/image.

Acceptance: list highlight, displayed forms, and save destination always agree; a declined switch preserves the translation and the selected filter.

### 4. Integrate render resilience and expiration

- Add bounded retry for transient locks when copying the finished PDF out. Cleanup failures must not fail an otherwise valid render. Validate the copied output; a missing source must remain an error rather than inheriting the deletion helper's “already absent is success” behavior.
- Apply the behavior to **both** paths: the fresh/reference build in `slide_preview.compile_and_extract(..., reuse_build=False)` and the default cached path in `preview_build.py`. Porting only the old fresh-build hunk would miss normal workspace previews.
- Preserve dependency sidecars (`write_inputs`), format-cache fallback, accepted-result snapshot publication, raster process isolation, and stale-request rejection. Capture dependency inputs before deleting auxiliary files.
- Keep old `.build/preview-*` cleanup separate from cached build retention. Use existing active-build/maintenance guards, including protection against another process; age alone must not authorize removal of an active build. Schedule cleanup outside reservations it would otherwise contend with.
- Sweep only owned temporary render folders after they and all contained files are at least 24 hours old, after successful cached/fresh renders and on a background task around eight seconds after startup. Skip unrelated folders, directories with unexpected contents, symlinks, and files still locked. Include generated sidecars in expiration checks; preserve outputs still in active app use.
- The current `PreviewView._run` already catches unexpected worker exceptions. Check the complete lifecycle, including PDF opening in `_on_finished`, standardized failure logging via `compile_log`, clearing busy state, and launching the next queued job. Avoid duplicate or contradictory terminal status lines.
- Adapt `test_slide_preview_cleanup.py`: develop calls the removed private `_compile_and_extract` and patches the renamed `_build_env`; use the current API and explicitly select `reuse_build=False` for fresh-path tests. Fake the shared process runner where appropriate, then add cached-path and lifecycle coverage.

Acceptance: transient and persistent lock simulations terminate predictably; successful PDFs survive auxiliary-file cleanup failures; failed output copies are reported; sweeping respects age, ownership, and build activity; warm previews still reuse builds.

### 5. Integrate subsection agendas through the current parser

- Review the cleanly merged LaTeX implementation while retaining the redesign's `\SMLuaOnce` format-cache support and corrected omission/visibility behavior.
- Extend transcript slide metadata with subsection identity. Determine subsection boundaries and titles from the same expanded, masked document body used for active slide calls, and associate them with `slot.original.call_start`/chapter identity. Use the resolved slot for slide language and filename. Share the subsection index between placement and title lookup so includes and ignored TeX cannot produce mismatched numbering.
- Keep the existing shared slide parser and language-slot deduplication. Do not restore develop's independent `_SLIDE_CALL_RE` traversal or reintroduce old default-condition logic.
- Add subsection-agenda placeholders and EN/DE labels; list each subsection with an included slide using its first included slide number. Exclude front matter before the first subsection and empty subsections; retain chapter-agenda behavior and remove placeholders in single-slide transcripts.
- Test literal `input`/`include` fragments, commented or inactive subsection declarations, translated partners, explicit translation calls, repeated slide calls, omitted/conditional slides, and subsection reset between chapters. Check the LaTeX slide-ID-based deduplication when one slide opens multiple subsections so PDF and transcript agree.
- Build a small dedicated fixture containing both agenda types; the existing manual alone may not exercise the new command. Verify PDF link destinations, text/numbering, reruns, and the cached/fresh preview paths. Include German and student/instructor variants.

Acceptance: PDF and transcript describe the same subsections with the correct first-slide targets/numbers, while existing language and conditional-slide regressions remain passing.

### 6. Validate and complete the integration

Run focused checks as each workstream becomes runnable, then the repository checks once after all resolutions:

| Area | Checks |
| --- | --- |
| Release/history | `tests/test_release_notes.py`, `tests/test_version.py`, `tests/test_compat.py`; generate actual integration-release notes with `--previous v5.36.0` and with the actual preceding release tag |
| Images | `tests/test_images_page_gui.py`, `tests/test_review_gui.py`, `tests/test_image_review.py` |
| Preview/cleanup | Adapted `tests/test_slide_preview_cleanup.py`; `tests/test_preview_build.py`, `tests/test_preview_dependencies.py`, `tests/test_preview_queue.py`, `tests/test_preview_raster.py`, `tests/test_compile_status.py`, `tests/test_housekeeping_gui.py` |
| Agenda/language | `tests/test_navigation.py`, `tests/test_deck_language.py`, `tests/test_review_transcript_import.py`, `tests/test_transcript_policy.py`, `tests/test_transcript_conversion.py`; real LaTeX agenda fixture |
| Whole application | `ruff check .`, `pytest -q` with Qt offscreen, `git diff --check`; check no unresolved merge entries, conflict markers, or resurrected legacy UI imports |
| Platforms/package | Existing Linux/Windows Python matrix, especially Windows locked-file behavior; manual builds in instructor/during-course modes; package-data/history smoke check |

The existing CI workflow is `workflow_dispatch` only: do not assume pushing the integration will run it. At implementation time, arrange its explicit run and record the result; Windows MiKTeX is currently allowed to fail, so distinguish an unverified platform from a passing check.

Commit the resolved merge only when these checks pass or concrete environmental limits are documented. Verify that the chosen develop tip is an ancestor of the integration head. When publishing is requested, update `ui-redesign` without rewriting existing history and recheck PR #1's mergeability against the then-current `develop`. The PR remains open for review; this plan does not include merging it into develop, tagging, or releasing.

## Evidence and limits of this planning pass

Completed: live PR/ref inspection, exact-tip dry merge in a disposable clone, all six incoming commit diffs, replacement-module inspection, and a history scan establishing the 33 missing news entries. No application tests or LaTeX builds were run because no integration was implemented. The original checkout's pre-existing changes were preserved; this plan is the only new repository file from this task.
