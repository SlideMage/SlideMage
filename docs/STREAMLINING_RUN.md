# Streamlining run, night of 12–13 October 2026

Unattended run of `docs/STREAMLINING_PLAN.md` on branch `streamlining` (worktree
`~/github/SlideMage-streamlining`, branched from `ui-redesign` at `07c0ea5`). The user's
rule "pause after each committed step" is suspended for this night only; the stop rule
below is the one automatic checkpoint. Nothing is pushed.

## Scope tonight

| Order | Step | Hard token cap |
| --- | --- | ---: |
| M | Merge `origin/develop` (`f8a250b`, v5.36.0) | 300k |
| 0 | Baseline: feature checklist, fixtures, counts | 250k |
| 1 | Image form/validation, widget kit and QSS | 600k |
| 2 | Edit validation/application across UI, agent, headless tasks | 650k |

Steps 3–6 are for a later night, after the user has reviewed this one.

**Stop rule.** After step 2, if steps 1+2 together removed fewer than 550 net physical
lines, stop and report instead of planning further steps.

## Rules for every step agent

- Work only in `/home/juergen/github/SlideMage-streamlining`. Never touch `~/github/SlideMage`.
- Python: `/home/juergen/github/SlideMage/.venv/bin/python` with `PYTHONPATH=$PWD/src`
  (the venv's editable install points at the other checkout; PYTHONPATH overrides it).
- Tests: `QT_QPA_PLATFORM=offscreen PYTHONPATH=$PWD/src /home/juergen/github/SlideMage/.venv/bin/python -m pytest -q -p no:cacheprovider`
  (baseline: 1,840 passed, 8 skipped, ~2.5 min). Run affected tests while working, the full suite before finishing.
- Lint: `/home/juergen/github/SlideMage/.venv/bin/ruff check src tests` (baseline clean).
- Line count: `/home/juergen/github/SlideMage/.venv/bin/python tools/count_lines.py .`
  (baseline at `07c0ea5`: files=190 physical=47019 code=32896).
- Do not commit; the orchestrator reviews, tests and commits. Leave the tree in a state that passes tests and ruff.
- Versioning (see `src/slidemage/CHANGELOG.md` header): any app-code change bumps `VERSION_NUMBER`
  in `src/slidemage/version.py` and appends a CHANGELOG entry. Refactor steps: patch bump, entry reason
  "streamlining step N", describing what was consolidated and that behavior is unchanged.
- Preserve every feature in the plan's feature preservation contract. No denser formatting, deleted
  explanations or removed tests to save lines. Remove superseded code in the same step; no shims.
- **Hard token cap:** when you reach the step's cap, finish the current change so tests pass, stop, and report.
  If a change cannot be made safe, revert it (`git checkout -- <files>`) rather than leave it half done.
- Report at the end: what changed (files), net physical/code lines vs. the previous count, test and ruff
  results, anything skipped or reverted and why, and open risks.

## Log

Filled in by the orchestrator after each step.

| Step | Commit | Version | Physical | Code | Net physical | Tests | Notes |
| --- | --- | --- | ---: | ---: | ---: | --- | --- |
| baseline | `07c0ea5` | v8.2.1 | 47,019 | 32,896 | — | 1,840 passed, 8 skipped | |
| M | (this commit) | v8.3.0 | 47,258 | 33,056 | +239 | 1,853 passed, 8 skipped | develop v5.35.4–v5.36.0 ported; both Images edge cases were real bugs, fixed with tests; ~147k tokens, 7 min |
| 0 | (this commit) | v8.3.0 | 47,258 | 33,056 | 0 | 1,853 passed, 8 skipped | Baseline doc (113 checks, 7 gaps), fixture script + manifest (instructor view of manual copy + 4 previews cached/fresh, ~110 s; page 17 image hash unstable, text stable). Found steps 1–2 smaller than budgeted: one real write primitive already exists; image-form duplication is mostly dialog/save plumbing; 6 atomic writers, not 2; latexmk launches already share run_streamed. ~139k tokens, 14 min |
| 1 | (this commit) | v8.3.1 | 47,100 | 32,888 | −158 | 1,854 passed, 8 skipped | Shared review-refused warning; kit QSS text() helper and merged identical rule blocks; clear_layout() replaces 8 loops; caption() replaces 11 label blocks. Screenshots (4 modes × 2 themes + gallery) pixel-identical. Panel warning wording now matches the Images page. Below budget (350–900). ~151k tokens, 8 min |
| 2 | (this commit) | v8.3.2 | 47,100 | 32,888 | 0 | 1,855 passed, 8 skipped | Edit paths already share write_text/save_slide_source; removed apply_result wrapper. Correctness fix: write_text now refuses frozen versions for every caller (headless tasks and undo bypassed the check). Fixtures --check OK. ~68k tokens, 7 min |

**Stop rule triggered.** Steps 1+2 removed 158 net physical lines (threshold 550). The run stops here; steps 3–6 need a re-estimate and the user's decision.
| fix | (this commit) | v8.3.3 | — | — | — | 1,856 passed, 8 skipped | Direct report: Claude Code picker now also sets the terminal's --model/--effort (Restart applies a change). |

## Continuation (user's decision, 12 October evening)

The user chose to continue through steps 3–6 despite the stop rule, with the goal **clean code and
structure** rather than line count. Line counts are still recorded; a step may add lines when
ownership becomes clearer. Steps run without pausing.

| Step | Work | Hard token cap |
| --- | --- | ---: |
| 3 | Explicit project context; window coupling outside compilation | 800k |
| 4 | Compile execution and controller (replace CompileJobsMixin) | 900k |
| 5 | Parsing, settings helpers, specialised workflow plumbing | 800k |
| 6 | Integration: full checks, fixtures, Linux build, final report | 300k |

