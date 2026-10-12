# SlideMage streamlining plan

Revised 12 October 2026: preserve every existing feature; savings re-estimated bottom-up per step. This replaces the earlier feature-cut proposal. Scope is a plan revision; no application rewrite has been performed.

## Recommendation and expected savings

Streamline the implementation behind the existing workflows. Preserve the native AI agent, embedded Claude terminal, focused Claude tasks, Anthropic API and Ollama support, reproducible snapshots, presentation conversion, selective PDF patching, model administration, app updates, course automation, and detailed compile progress. Keep all current editor modes and both image-description editing entry points.

Retain PySide6, LuaLaTeX, current project formats, supported platforms, and public CLI behavior. Consolidate repeated operations using existing helpers. A new framework, general scheduler, database, or wholesale rewrite would add migration work without demonstrated savings.

**Planning estimate: roughly 1,500–4,000 fewer physical lines of application Python (about 3–8%), with all features retained.** This range is the sum of the per-step budgets below. In the current tree about 70% of physical lines are code-bearing, so this corresponds to roughly **1,000–2,800 fewer code-bearing lines**. The figures are preliminary engineering estimates, not measured removable duplication or promised savings. They are net of replacement code.

An earlier revision of this plan gave 4,000–7,000 physical / 2,000–4,000 code-bearing lines. That was a top-down figure not tied to any step, and the two ranges implied that removed code would be unusually comment-heavy; it is withdrawn. A larger reduction would require consolidation inside the large domain modules (`transcript.py`, `deck_snapshot.py`, `alt_draft.py`, `compiler.py`, `kit_qss.py`), which this plan has not yet shown to contain duplication.

### Savings budget by step

Budgets are net physical lines of application Python. Each is a hypothesis to be replaced by the measured figure when the step lands.

| Step | Work | Budget | Basis |
| --- | --- | ---: | --- |
| 1 | Image form/validation, widget kit and QSS | 350–900 | Two independent `ImageForm` classes (`ui/pages/image_form.py`, 314 lines; `ui/workspace/panels/images.py`, 215 lines) and duplicated review validation; `ui/kit/` is 2,763 lines with unaudited overlap. |
| 2 | Edit validation/application | 200–600 | Separate write paths in `claude_runner.apply_result`, `claude_tasks._apply_edits`, `tools/edits.write_text`, two `apply_to_buffer` implementations, and `terminal/tasks._apply`. |
| 3 | Explicit project context, window ownership | 0 (may add 100–300) | Ownership change; not a deletion target. |
| 4 | Compile execution primitive | 300–800 | Repeated process startup, environment, cancellation and output validation across compiler, preview, snapshot and export paths. The status-event change contributes nothing (see section 3). |
| 5 | Parsing, settings helpers, specialised workflow plumbing | 550–1,600 | Comment/brace/argument handling across `tex_source.py`, `latex_lint.py`, `transcript.py`, editing; two existing atomic-write helpers (`alt_images.atomic_write_text`, `compat._atomic_write`); repeated process/progress plumbing in snapshot, update and import/export code. |
| 6 | Integration checks | 0 | Verification only. |
| | **Total** | **≈1,400–3,900** | |

**Stop rule.** After steps 1 and 2, compare measured savings with their combined budget (550–1,500). If the measured total is below 550, or extrapolates to under about 1,500 for the whole plan, revise the target or narrow the remaining scope before starting step 4, which carries the most behavioral risk.

The previous 20–30% target depended on removing features and is withdrawn. Do not achieve the new target through denser formatting, compressed expressions, deleted explanations, relocated code, or fewer tests. Re-estimate after the first two consolidation changes; retain useful code if removing it requires a more complicated abstraction.

## Baseline and evidence

The working-tree count on 12 October 2026 (at `3925f65`) is **47,019 physical Python lines in 190 application files** under `src/slidemage/`. The tree keeps changing (46,259/189 at the original inspection, 46,923 at the previous revision of this plan). Freeze an agreed revision before implementation so ongoing feature work is not attributed to this refactor, and refresh every figure in this document at that point, not only the totals.

A token/AST-based count gives **32,896 code-bearing lines**, excluding blank lines, comment-only lines, and module/class/function docstrings. Multiline strings used as data, including QSS, still count as code-bearing lines. This is a reproducible source-size proxy, not executable statement count. Tests, assets, documentation, benchmark JSON, and the LaTeX framework are outside both totals.

Evidence from the original inspection:

- `WorkspaceWindow` inherits three application mixins. `CompileJobsMixin` (`ui/workspace/compile_jobs.py`) was 671 lines at the original inspection and is 802 now; it coordinates builds, snapshots, preview refresh, and PPTX export. These operations need common lifecycle handling but retain distinct behavior.
- 44 Python files mentioned `PROJECT_ROOT`; `deck_scan.py` chooses it at import time. Tests must set environment variables before importing dependent modules.
- `compile_status.py` and `compile_progress.py` both derive application state from formatted log lines. The status patterns themselves are already shared through `compile_log.py`, and log-driven status is deliberate: a whole run can be tested by replaying a captured log. Little duplication remains here.
- The image-description form exists twice: `ui/pages/image_form.py` and the `ImageForm` in `ui/workspace/panels/images.py`, with the "informative image needs a long description" check repeated in both `_save` methods.
- Three AI interaction paths exist. Their user experiences are distinct; share edit validation and result application rather than replacing them with one interface.
- `ui/kit/` contained 2,763 lines. Consolidate equivalent style rules and widget behavior without removing appearance, accessibility, or interaction features.
- Transcript conversion, partial compilation, and reproducible snapshots contain substantial domain-specific logic. Their size is not proof of duplication.
- `preview_build.compile_cached()` invokes `preview_format.ensure()`, which can attempt format creation. The README's unsuccessful-probe discussion does not prove that path is dead. Retain its capability while resolving documentation and test coverage; no savings from deleting it are assumed.

The existing `WorkspaceState`, command registry, pure editing functions, `SourceFile`, background lifetime helpers, and shared image-description store are the starting points. Extend these only where they replace repeated implementation.

### Why the current PR looks much larger

The local comparison `git diff origin/develop...origin/responsive-layout` exactly reproduces the reported **129,724 additions and 24,277 deletions**, across 436 files and a branch containing 100 commits not in `origin/develop`.

| Area | Added | Deleted |
| --- | ---: | ---: |
| `docs/` | 78,325 | 291 |
| `src/slidemage/` (including changelog) | 30,541 | 19,434 |
| `tests/` | 17,671 | 3,733 |
| Everything else | 3,187 | 819 |

Three raw benchmark reports accounted for 73,683 additions (all benchmark results and finished plans were removed from `docs/` on 12 October 2026; they remain in Git history): `preview-benchmark-2026-10-11.json` (58,576), `preview-benchmark-2026-10-09.json` (7,638), and `preview-benchmark-review-fixes-2026-10-11.json` (7,469). Ignoring end-of-line whitespace does not change the totals. App-source net growth in that comparison is 11,107 lines, including non-Python files; the PR's additions are not the app's current size. Local HEAD is ahead of that remote-tracking branch, so its totals differ.

These are local-ref observations; live PR metadata was unavailable. Do not change the PR base merely to lower the count: first determine whether it is intentionally stacked on an unmerged branch.

## Feature preservation contract

All previously proposed cuts are cancelled:

| Capability | Requirement during refactoring |
| --- | --- |
| Native AI chat/agent | Preserve conversation, streaming, tool execution, scope, edit approval/rejection, and undo. |
| Embedded Claude Code | Preserve terminal interaction, PTY/WebEngine integration, focus/deck context, MCP, hooks, and lifecycle. |
| Focused AI tasks and providers | Preserve task buttons, CLI runner, direct Anthropic API, Ollama, task-specific models, credentials, cancellation, and local-only policy. |
| Reproducible deck snapshots | Preserve dependency/font/environment/application capture options, manifests, render scripts, verification, and reading existing snapshots. |
| Presentation conversion | Preserve PPTX and ODP import, PPTX export, and supported overlay behavior. |
| Partial compilation | Preserve selected-page recompilation, PDF patching, link retargeting, and overlay grouping. Full rebuild plus extraction is not an equivalent replacement. |
| Administration | Preserve Ollama management, manual/automatic app updating, breaking-release handling, bundled-copy updates, and course/schedule helpers. |
| Compile progress | Preserve percentage estimates, historical pass counts, current stage, job status, logs, Stop, and retry. |
| Editor and image UI | Preserve Preview, Source, Split, Details, inspector editing, full Images page, shortcuts, resizing, and remembered layout. Share implementation behind these surfaces. |
| Content and safety | Preserve accessibility/transcripts, bibliography, language links, frozen versions, undo/backups, protected regions, compatibility checks, and conflict handling. |
| Preview behavior | Preserve saved/unsaved rendering, overlays/scopes, caches, format-cache capability, fresh-reference mode, stale-result rejection, and raster isolation. |

No feature moves out of the app into an external utility. Dependencies supporting retained features remain. Equivalent output alone is insufficient if an existing interaction, supported platform, or important performance characteristic disappears.

## Implementation changes

### 1. One explicit project context

Evolve `project.py` to create a small immutable context containing root and derived paths. Pass it to the window and the operations that need it. Pure text operations continue to take strings and values.

Remove import-time project discovery and project-specific module constants incrementally: settings first, then editing, then compilation. Keep the existing environment variable at the CLI boundary. Do not add a service locator or a generic repository layer. Project switching can continue to restart the application until changing that behavior provides a real benefit.

Success: tests can operate on two temporary project roots without module reloads or patching many path globals; importing backend modules does not select a project.

### 2. One owner for each editing operation

Use the existing `SourceFile` and editing helpers as the starting point. The editor owns the buffer, dirty state, and save/discard handling. A shared apply operation checks the expected original text, protected regions, frozen-version rules, and undo/backup behavior. AI task results and UI actions call that operation rather than implementing another write path.

Keep slide-level text edits separate from multi-file operations such as rename and translation-partner creation. Those operations need explicit preflight and rollback/recovery for partial failure; a generic `save()` is insufficient. Reuse established helpers in `latex_edit.py`, `slide_add.py`, `slide_rename.py`, and `protected_regions.py`.

Success: typing while an AI task runs cannot be overwritten; failed translation creates no orphan slide; repeated slide calls remain distinguishable; all current save/discard behavior survives.

### 3. One compile execution primitive, explicit modes

Consolidate repeated process startup, environment construction, cancellation, current-run log/PDF validation, and output publication behind the existing compiler. Keep explicit wrapper construction for deck, chapter, and slide preview. A cached build and a fresh build use the same execution primitive with different build-directory policies.

Optionally replace parsing SlideMage's own formatted status messages with a small job event/result data structure delivered through existing callbacks or Qt signals. **This is a clarity change, not a size reduction:** the patterns are already shared via `compile_log.py`, the formatted lines must still be written for the user-visible log, and the change touches the compiler, `compile_jobs`, `job_panel`, `compile_progress`, and the log-replay tests. No savings are budgeted for it, and it may add lines. Do it only if it removes a demonstrated bug class or simplifies the compile controller; otherwise keep log-driven status and its replay tests. Either way, keep parsing external latexmk output for diagnostics and pass information, preserve the pass-history-based percentage estimator and its persistence, and preserve any externally consumed log format.

The compile controller owns build state; the window displays it. It receives the explicit project context from section 1, which is why that context lands first (delivery step 3) and the compile work follows (delivery step 4). Remove `CompileJobsMixin` after migrating its callers, rather than wrapping it in another layer. Do not force AI, rasterization, network requests, and compilation into one universal scheduler. Use `ui/background.py` for shared thread lifetime behavior while retaining operation-specific cancellation.

Success: a fresh reference build, a reused preview build, and a full deck compile share execution/error handling; cancellation and late output cannot publish an obsolete result.

### 4. Simplify previews without losing their fixes

Keep `preview_format.py`, normal latexmk build reuse, and their fallback behavior. Share execution, dependency collection, and validation where semantics match. Resolve the discrepancy between current code and documentation before changing defaults. Only remove a branch if caller inspection and behavior checks establish that it is unreachable or redundant; unsuccessful benchmarks alone are insufficient.

Keep one active preview and the latest pending request, immutable request identity, stale-result rejection, bounded image caching, and the raster subprocess. The existing documentation records a crash from threaded MuPDF use: deleting process isolation is not an acceptable simplification. Preserve cross-process build/cleanup locks and verified dependency invalidation.

Keep a fresh-build reference mode implemented by the same executor. Do not combine the TeX build cache, PDF-to-image cache, and persisted thumbnail store merely because all three are caches; they serve different purposes.

Success: saved and unsaved previews render correctly across view/language/preamble/overlay changes; superseded requests do not update the image or persisted snapshot; cached and fresh output agree on a fixed corpus.

### 5. Share UI implementation and reduce cross-widget dependencies

Keep every current view and editing entry point. Share the image-description form and save/validation logic between the inspector and Images page. Share slide facts/actions between Details and the inspector where they have the same meaning. Preserve each surface's presentation and navigation; reuse behavior without forcing differently sized layouts into one configurable mega-widget.

Keep the command registry as the single command list for menus, shortcuts, and palette. Replace window mixins with a few concrete collaborators only where ownership is needed: compilation and editing first. Simple deck and maintenance commands can remain functions; they do not each need a controller class. Pass required state/callbacks to widgets instead of the entire application object.

Audit the custom widget kit for equivalent rules and wrappers. Consolidate styles through existing tokens and helpers; use standard Qt behavior where it is equivalent. Preserve custom behavior, styling, keyboard navigation, focus indication, resizing, and contrast. Do not assume large QSS files can disappear without a visual regression.

Success: no application behavior mixins in the window; common actions are implemented once; a widget no longer needs to traverse the window to sibling widgets to perform an edit.

### 6. Reduce parsing and settings duplication

Reuse the existing lexical helpers in `tex_source.py` and existing slide-call representations. Consolidate demonstrably equivalent comment/brace/argument handling where callers agree on semantics. Do not introduce a general LaTeX AST or assume regexes in different contexts are interchangeable.

Keep transcript conversion as a distinct operation. Centralize supported command knowledge where it currently disagrees across transcript, lint, and source editing, with fixtures covering the differences. Preserve unknown user-authored source instead of rewriting it into a canonical format.

Keep storage scope explicit: project content and policies, portable project preferences, machine-specific window geometry, and credentials have different requirements. Share a small JSON load/update/atomic-write helper where appropriate; preserve store locking and reviewed-image conflict checks. Do not merge everything into one settings file or move portable preferences into the registry.

Success: shared helpers replace duplicated behavior; existing projects still open without silent data loss; concurrent image review and AI drafting preserve both writers' changes.

### 7. Separate track: framework, documentation, and packaging

This section does not change application Python and contributes nothing to the savings budget. Track it separately (or in its own plan) so it neither inflates nor obscures the line-count measurement.

Treat `latex/` as a separate maintenance area. The base preamble alone is 7,001 lines; the repository also includes Gotham's documented source and theme files. Identify generated files and local theme modifications before changing them. Establish one documented regeneration path; never delete a macro solely because the bundled example does not use it. External projects are part of the compatibility surface.

Keep one quick-start README, one user manual, and one short architecture reference. Archive completed implementation plans and historical commentary; retain concise explanations of non-obvious safety constraints near the relevant code.

Store future raw benchmark output as CI/release artifacts with provenance, input revision, and hashes. Keep concise results and a small regression corpus in Git. The existing raw files have been removed from `docs/`; earlier commits still hold them. Do not rewrite Git history just to reduce PR statistics. Deleting them from the proposed branch can reduce the final diff if they were introduced on that branch, but does not remove historical Git objects.

Keep WebEngine, terminal assets, provider SDK resources, and conversion dependencies because their features remain. Audit only genuinely unused packaged resources. Lazy initialization can improve startup but is not source deletion or a guaranteed reduction in the frozen executable. Measure actual build size and startup; no substantial dependency or package-size reduction is assumed.

### 8. Share AI and specialized workflow plumbing

Keep agent chat, interactive terminal sessions, and headless tasks separate where their protocols differ. Reuse common captured-target identity, protected-region validation, conflict checks, preview refresh, and error reporting. Move reusable editing validation out of agent-specific ownership where callers already share it; do not wrap every transport in an artificial common streaming protocol.

For snapshots, import/export, updates, and course helpers, remove only repeated process, path, serialization, and progress handling. Keep their domain algorithms explicit. Snapshot verification is not ordinary compilation, and an updater replacing the running executable needs a different lifecycle from an image-description task.

Success: the same edit rules apply through all existing AI paths; specialized features retain their options, results, cancellation, and recovery behavior. New helper code must be smaller and easier to understand than the repetitions it replaces.

## Delivery order and acceptance

Each step should be a reviewable change that removes its superseded implementation in the same step. Avoid long-lived parallel architectures, blanket compatibility shims, and formatting-only churn. Refactoring ownership may initially add lines; report that honestly rather than treating moved files as a reduction.

| Step | Work | Exit condition |
| --- | --- | --- |
| 0 | Freeze a revision, record the full feature inventory, tests, and representative build outputs on disposable projects. Preserve ongoing work; clarify stacked PR ancestry. | Reproducible source counts, output fixtures, and a feature-preservation checklist. |
| 1 | Share image form/validation behavior and equivalent QSS/widget logic. Budget 350–900. | Both image-editing surfaces and all existing views still work; visual/interaction checks pass; measured net savings recorded. |
| 2 | Consolidate editing validation/application across UI, agent, and headless tasks. Budget 200–600. | All AI interfaces remain; conflicts, approval/rejection, undo, protected regions, and translation-partner creation pass. Apply the stop rule: compare steps 1–2 with their 550–1,500 budget and re-estimate the remainder before step 4. |
| 3 | Introduce explicit project context incrementally (settings, editing, then compilation paths); reduce window coupling outside compilation. Budget 0. | Clear ownership; two temporary projects work without scattered global patching. No savings are assumed from changing ownership; report any growth. |
| 4 | Consolidate compile execution on top of the project context; replace `CompileJobsMixin` with a compile controller. Status events only if justified per section 3. Budget 300–800. | Full, chapter, preview, partial/patch, snapshot, and export paths retain their semantics; detailed progress remains; log-replay tests still pass or are replaced by equivalent event tests. |
| 5 | Consolidate equivalent parsing/settings helpers and specialized workflow plumbing. Budget 550–1,600. | Existing project formats, imports/exports, snapshots, updates, model management, and course automation still work. |
| 6 | Run integration checks. | Full retained-feature checks, supported-platform build results, final measured net reduction against the per-step budgets. |

The framework, documentation, benchmark-storage, CI, and packaging work in section 7 runs as a separate track with its own exit conditions (current documentation, preserved benchmark evidence, one regeneration path) and is reported separately from the code reduction.

Keep new feature work separate from this refactor's baseline and measurements. The scope is current behavior, including in-progress behavior present at the agreed baseline; this plan does not cancel other requested feature work.

## Verification and definition of done

Run the existing affected tests per change, then the full suite before integration. Add tests only for changed contracts or coverage gaps; consolidate duplicate test setup without discarding distinct behavior checks. The tests are not a deletion target to make the repository look smaller.

Use disposable project copies and a frozen representative corpus: multilingual slides, overlays, citations, images/TikZ, an accessible transcript, frozen versions, a large deck, and externally edited source. Compare fresh and cached PDFs by rendered pages/text rather than raw PDF bytes when metadata varies. Exercise busy shutdown, cancellation, stale completion, locked output, and raster-helper failure. Use fake AI runners/providers in automated checks; no paid or credentialed requests are required. Add explicit parity checks for native agent conversations/tools, embedded terminal context/hooks, all provider choices, snapshot reproduction, PPTX/ODP conversion, PDF patch links, updater/model-management behavior, and course automation. Preserve the current progress estimates and every editor/image-review entry point.

Enable a fast PR CI gate instead of relying solely on the current manually triggered workflow. Keep the broader supported-Python matrix and real TeX/platform checks at an appropriate integration/release cadence. Test Linux and Windows packaging when changing process startup or dependency inclusion; report platform checks that were unavailable.

Track four measures: maintained app code excluding comments/generated assets; number of independent implementations of each workflow; startup/build/preview performance on the same inputs; and runtime/package dependencies. Report file moves, documentation trimming, and optional-code relocation separately from actual code deletion.

Acceptance requires all agreed baseline features to remain available, their regression checks to pass, superseded duplicate implementations to be gone, and fewer cross-component changes for routine edits. Keep fresh/cached preview and large-deck timings comparable on the same inputs; investigate sustained slowdowns before accepting a consolidation.

Final reporting must distinguish actual implementation deletion from comments/docstrings, test changes, file moves, and benchmark/documentation changes. Moving the 73,683 benchmark JSON lines out of the PR would improve review size but save **zero application code lines**.

The estimated 1.5–4k physical / 1–2.8k code-bearing line reduction is a planning range built from the per-step budgets. There is no verified deletion list yet. Stop pursuing a line-count target when the next abstraction would make the retained behavior harder to understand or maintain. No runtime changes or tests were performed in this plan revision.
