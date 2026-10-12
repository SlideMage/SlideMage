# SlideMage streamlining plan

Revised 12 October 2026: preserve every existing feature. This replaces the earlier feature-cut proposal. Scope is a plan revision; no application rewrite has been performed.

## Recommendation and expected savings

Streamline the implementation behind the existing workflows. Preserve the native AI agent, embedded Claude terminal, focused Claude tasks, Anthropic API and Ollama support, reproducible snapshots, presentation conversion, selective PDF patching, model administration, app updates, course automation, and detailed compile progress. Keep all current editor modes and both image-description editing entry points.

Retain PySide6, LuaLaTeX, current project formats, supported platforms, and public CLI behavior. Consolidate repeated operations using existing helpers. A new framework, general scheduler, database, or wholesale rewrite would add migration work without demonstrated savings.

**Planning estimate: 4,000–7,000 fewer physical lines of application Python, approximately 9–15%, with all features retained.** From the refreshed 46,923-line baseline this would leave approximately 40,000–43,000 lines. Within that reduction, budget for roughly **2,000–4,000 fewer code-bearing lines**, with the remainder being associated comments, docstrings, and spacing around removed duplicate implementations. These are preliminary engineering estimates, not measured removable duplication or promised savings. Replacement code is included in the intended net reduction.

The previous 20–30% target depended on removing features and is withdrawn. Do not achieve the new target through denser formatting, compressed expressions, deleted explanations, relocated code, or fewer tests. Re-estimate after the first two consolidation changes; retain useful code if removing it requires a more complicated abstraction.

## Baseline and evidence

The refreshed working-tree count is **46,923 physical Python lines in 190 application files** under `src/slidemage/`. It includes current uncommitted work; the tree has changed since the original 46,259-line/189-file inspection. Freeze an agreed revision before implementation so ongoing feature work is not attributed to this refactor.

A token/AST-based count gives **32,822 code-bearing lines**, excluding blank lines, comment-only lines, and module/class/function docstrings. Multiline strings used as data, including QSS, still count as code-bearing lines. This is a reproducible source-size proxy, not executable statement count. Tests, assets, documentation, benchmark JSON, and the LaTeX framework are outside both totals.

Evidence from the original inspection:

- `WorkspaceWindow` inherits three application mixins. `CompileJobsMixin` alone was 671 lines and coordinates builds, snapshots, preview refresh, and PPTX export. These operations need common lifecycle handling but retain distinct behavior.
- 44 Python files mentioned `PROJECT_ROOT`; `deck_scan.py` chooses it at import time. Tests must set environment variables before importing dependent modules.
- `compile_status.py` and `compile_progress.py` independently derive application state from formatted log lines. Keep the progress estimator but share event interpretation.
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

Three raw benchmark reports account for 73,683 additions: `preview-benchmark-2026-10-11.json` (58,576), `preview-benchmark-2026-10-09.json` (7,638), and `preview-benchmark-review-fixes-2026-10-11.json` (7,469). Ignoring end-of-line whitespace does not change the totals. App-source net growth in that comparison is 11,107 lines, including non-Python files; the PR's additions are not the app's current size. Local HEAD is ahead of that remote-tracking branch, so its totals differ.

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

Replace parsing SlideMage's own formatted status messages with a small job event/result data structure delivered through existing callbacks or Qt signals. Keep parsing external latexmk output for diagnostics and pass information. Preserve the pass-history-based percentage estimator and its persistence. Feed it the same parsed events as job status, rather than independently reinterpreting the log. Preserve any externally consumed log format.

The compile controller owns build state; the window displays it. Remove `CompileJobsMixin` after migrating its callers, rather than wrapping it in another layer. Do not force AI, rasterization, network requests, and compilation into one universal scheduler. Use `ui/background.py` for shared thread lifetime behavior while retaining operation-specific cancellation.

Success: a fresh reference build, a reused preview build, and a full deck compile share execution/error handling; logs are presentation rather than the app's internal state protocol; cancellation and late output cannot publish an obsolete result.

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

### 7. Contain framework, documentation, and packaging scope

Treat `latex/` as a separate maintenance area. The base preamble alone is 7,001 lines; the repository also includes Gotham's documented source and theme files. Identify generated files and local theme modifications before changing them. Establish one documented regeneration path; never delete a macro solely because the bundled example does not use it. External projects are part of the compatibility surface.

Keep one quick-start README, one user manual, and one short architecture reference. Archive completed implementation plans and historical commentary; retain concise explanations of non-obvious safety constraints near the relevant code.

Store future raw benchmark output as CI/release artifacts with provenance, input revision, and hashes. Keep concise results and a small regression corpus in Git. Before removing existing raw files, preserve them in a durable agreed location. Do not rewrite Git history just to reduce PR statistics. Deleting them from the proposed branch can reduce the final diff if they were introduced on that branch, but does not remove historical Git objects.

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
| 1 | Share image form/validation behavior and equivalent QSS/widget logic. | Both image-editing surfaces and all existing views still work; visual/interaction checks pass; measured net savings recorded. |
| 2 | Consolidate editing validation/application across UI, agent, and headless tasks. | All AI interfaces remain; conflicts, approval/rejection, undo, protected regions, and translation-partner creation pass. Re-estimate total savings from actual changes. |
| 3 | Consolidate compile execution and parse status/progress events once. | Full, chapter, preview, partial/patch, snapshot, and export paths retain their semantics; detailed progress remains. |
| 4 | Reduce window/mixin coupling; introduce explicit project context incrementally. | Clear ownership; two temporary projects work without scattered global patching. No additional savings are assumed merely from changing ownership. |
| 5 | Consolidate equivalent parsing/settings helpers and specialized workflow plumbing. | Existing project formats, imports/exports, snapshots, updates, model management, and course automation still work. |
| 6 | Audit docs/framework regeneration/packaging and run integration checks. | Current documentation, preserved benchmark evidence, full retained-feature checks, supported-platform build results, final measured net reduction. |

Keep new feature work separate from this refactor's baseline and measurements. The scope is current behavior, including in-progress behavior present at the agreed baseline; this plan does not cancel other requested feature work.

## Verification and definition of done

Run the existing affected tests per change, then the full suite before integration. Add tests only for changed contracts or coverage gaps; consolidate duplicate test setup without discarding distinct behavior checks. The tests are not a deletion target to make the repository look smaller.

Use disposable project copies and a frozen representative corpus: multilingual slides, overlays, citations, images/TikZ, an accessible transcript, frozen versions, a large deck, and externally edited source. Compare fresh and cached PDFs by rendered pages/text rather than raw PDF bytes when metadata varies. Exercise busy shutdown, cancellation, stale completion, locked output, and raster-helper failure. Use fake AI runners/providers in automated checks; no paid or credentialed requests are required. Add explicit parity checks for native agent conversations/tools, embedded terminal context/hooks, all provider choices, snapshot reproduction, PPTX/ODP conversion, PDF patch links, updater/model-management behavior, and course automation. Preserve the current progress estimates and every editor/image-review entry point.

Enable a fast PR CI gate instead of relying solely on the current manually triggered workflow. Keep the broader supported-Python matrix and real TeX/platform checks at an appropriate integration/release cadence. Test Linux and Windows packaging when changing process startup or dependency inclusion; report platform checks that were unavailable.

Track four measures: maintained app code excluding comments/generated assets; number of independent implementations of each workflow; startup/build/preview performance on the same inputs; and runtime/package dependencies. Report file moves, documentation trimming, and optional-code relocation separately from actual code deletion.

Acceptance requires all agreed baseline features to remain available, their regression checks to pass, superseded duplicate implementations to be gone, and fewer cross-component changes for routine edits. Keep fresh/cached preview and large-deck timings comparable on the same inputs; investigate sustained slowdowns before accepting a consolidation.

Final reporting must distinguish actual implementation deletion from comments/docstrings, test changes, file moves, and benchmark/documentation changes. Moving the 73,683 benchmark JSON lines out of the PR would improve review size but save **zero application code lines**.

The estimated 4–7k physical / 2–4k code-bearing line reduction is a planning range. There is no verified deletion list yet. Stop pursuing a line-count target when the next abstraction would make the retained behavior harder to understand or maintain. No runtime changes or tests were performed in this plan revision.
