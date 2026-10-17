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

The user chose to continue through steps 3–6 despite the stop rule, with two goals: **clean code and
structure, and fewer lines** (user, 12 October). Delete what a clearer structure makes redundant and prefer
the shorter of two equally clear designs; where a structural improvement costs lines, the step report says so. Steps run without pausing.

| Step | Work | Hard token cap |
| --- | --- | ---: |
| 3 | Explicit project context; window coupling outside compilation | 800k |
| 4 | Compile execution and controller (replace CompileJobsMixin) | 900k |
| 4b | Finish the project-context migration: editing and AI layers off `project.transitional_context()`, then delete it (user, 12 October) | 800k |
| 5 | Parsing, settings helpers, specialised workflow plumbing | 800k |
| 6 | Integration: full checks, fixtures, Linux build, final report | 300k |

| Step | Commit | Version | Physical | Code | Net physical | Tests | Notes |
| --- | --- | --- | ---: | ---: | ---: | --- | --- |
| 3 | (this commit) | v8.3.4 | 47,250 | 32,951 | +138 | 1,858 passed, 8 skipped | ProjectContext in project.py; no project chosen at import (0 import-time path constants left); app_settings, deck_scan, housekeeping, snapshots and all of ui/ take an explicit context; 41 backend modules (compile, editing, AI stacks) use project.transitional_context() at call time. MaintenanceMixin and DeckActionsMixin removed (plain functions); side panels use PanelActions instead of reaching into the window. Lines: +~180 src, −~67 tests (−~200 lines of path patching). ~546k tokens, 67 min |
| 4 | (this commit) | v8.3.5 | 47,212 | 32,894 | −38 | 1,864 passed, 8 skipped | CompileJobsMixin replaced by CompileController (state, thread, progress, retry) + CompileDisplay + compile_actions functions; compiler.run_latexmk/Build/latexmk_command is the one latexmk launch and judgement (run_job, partial_compile, deck_snapshot, run_preview); cached and fresh preview share run_preview/publish_preview; compile layer takes an explicit ProjectContext (85 transitional calls in 34 files left). Status-event refactor not done (no saving). Fixtures OK. Interrupted once by the usage limit; ~400k+ tokens |
| 4b | (this commit) | v8.3.6 | 47,222 | 32,914 | +10 | 1,865 passed, 8 skipped | Editing and AI layers take ProjectContext (or the one path they need); project.transitional_context() and project.use() deleted — no global current project; two projects side by side through editing and AI layers in tests. Caches made per project (latex_lint keys, transcript .bib). One wrong-type call (Path for ProjectContext in maintenance.py) found and fixed; others unaudited → step 6. ~678k tokens, 99 min |
| 5 | (this commit) | v8.3.7 | 47,069 | 32,761 | −153 | 1,876 passed, 8 skipped | fileio.py (atomic_write with fsync and Windows retry, read/write_json, exact-text I/O) replaces 5 hand-rolled writers and the JSON store boilerplate; tex_source.comment_start/braced_argument/blanked_verbatim shared by lint, transcript, protected regions, bibliography, editor; deck_editor.ALL_MACROS the one slide-macro list; processes.command_output/move_file/delete_file replace 4+3 copies; last window reach-through (DetailsPane, ImagesPage, AddSlideSheet, private window methods) removed. Orchestrator fixed an invalid-escape docstring. ~186k tokens, 19 min |
| 6 | (this commit) | v8.3.8 | 47,071 | 32,763 | +2 | 1,877 passed, 8 skipped | Wrong-argument audit (mypy, AST scan, call-time check over the whole suite): no Path-for-context call found; unannotated context parameters annotated; locked-file atomic_write test. Linux build OK. ~110k tokens, 40 min |

## Final report

**Totals, baseline `378f50b` (v8.3.0) to `c49d731` + step 6 (v8.3.8).** Physical 47,258 to 47,071 (-187), code 33,056 to 32,763 (-293), files 190 to 194 (new: fileio.py, compile_controller.py, compile_display.py, compile_actions functions, test_project_context.py and others), tests 1,853 to 1,877 passed (8 skipped), ruff clean. Per step (net physical): 1 -158, 2 0, 3 +138, 4 -38, 4b +10, 5 -153, 6 +2. The planned 1,500-4,000 line reduction was not reached: the duplication the plan estimated was smaller than assumed (step 0 and 2 found it), and the explicit context costs lines. Against the pre-merge `07c0ea5` (47,019) the tree is +52 lines with the develop merge (+239) included. The structure, not the size, is what this run bought.

**Structurally different.**
- `project.ProjectContext` is created once at each entry point (GUI, CLI, tools) and handed on; no import-time paths, no global "current project", `transitional_context()` and `project.use()` are gone, two projects can run side by side in one process (tested). Caches that were global are per project.
- No window mixins: MaintenanceMixin, DeckActionsMixin and CompileJobsMixin are plain functions or objects; `CompileController` owns a run (state, thread, progress, stop, retry), `CompileDisplay` shows it.
- One latexmk launch and judgement (`compiler.run_latexmk` / `Build`) for jobs, partial compile, snapshots and previews; cached and fresh previews share `run_preview` / `publish_preview`.
- Shared helpers: `fileio` (atomic_write, JSON, exact text), `tex_source` (comment_start, braced_argument, blanked_verbatim), `deck_editor.ALL_MACROS`, `processes.command_output/move_file/delete_file`, `write_text` as the one edit write path.
- Side panels, Images page, details pane and Add-slide sheet no longer reach into the window.

**Behaviour changes users could notice (CHANGELOG v8.3.0-v8.3.8).** v8.3.0: develop v5.35.4-v5.36.0 merged (two Images edge-case bugs fixed). 8.3.1: the reviewed-without-long-description warning reads the same in the panel as on the Images page. 8.3.2: a background task can no longer write into a frozen slide version. 8.3.3: the Claude Code tab's model and effort also start the terminal (Restart to apply). 8.3.5: a fresh preview reads latexmk output the way the cached one does. 8.3.6: a reference added to Slidemaster.bib shows in the next transcript without restarting. 8.3.7: settings, prompts and project files are written atomically with fsync (no half-written files); Source-view brace highlight treats `\\{` as a real brace; JSON stores always use `\n` line ends. 8.3.8: none.

**Verification in step 6.** Wrong-argument audit: mypy over src (annotated parameters) found no Path/ProjectContext mismatch; an AST scan listed every `ctx.root` argument (all go to Path parameters); a temporary pytest plugin checked every context and root parameter at call time through the full suite, with zero violations (and caught a deliberate wrong call). Retained-feature check: only 3 test names were removed since baseline (crashing compile run, batch end frees slot on GUI thread, picker before a project exists); each is covered by the new controller and context tests. Manual CLI runs on a disposable example copy: `--check-project`, `deck_scan`, `deck_snapshot create` (created and verified, identical to reference, 7 min) and `list`, `preview_cli` one slide: all fine. Fixtures `--check` OK (page-17 image WARN known). Four-mode screenshots at 1280x800 render. Linux PyInstaller build OK (about 2 min, 308 MB, exe reports v8.3.8 from this tree). Windows build not run.

**Known risks and not done.** No status-event refactor (compile status is still derived from log lines; no saving was found). Transcript and lint command knowledge was not centralised. Terminal and chat panels still take the window as their API. No runtime ProjectContext guard was added: annotations plus mypy plus the suite cover it, but mypy is not part of the project, so a Path passed for a context through an untyped `window.project` would still fail silently. Gaps from the baseline that remain untested: base `Workspace` defaults, snapshot font/app capture, PPTX export, PPTX/ODP overlay conversion, QSS appearance. Windows behaviour of the new atomic writer and the process helpers is untested here.

**Recommendation.** Merge `streamlining` into `ui-redesign` after the user reviews the diff by step (one commit per step, so it can be read in order or reverted at step 4/4b/5 boundaries): tests, ruff, fixtures and the Linux build are green, and the context migration removes a real class of hidden-global bugs. Before releasing, open and compile a real project on Windows once (project switching, atomic writes, snapshot create) and consider adding mypy to CI for the context parameters.
