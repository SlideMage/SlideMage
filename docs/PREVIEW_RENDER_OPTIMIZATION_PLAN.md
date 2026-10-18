# Preview rendering optimization plan

Draft started 16 October 2026. This is the next optimization phase after
[the implemented preview-view plan](PREVIEW_VIEWS_IMPLEMENTATION_PLAN.md).
Implementation of steps 1–6 is complete as of 18 October 2026. The requirements
below are retained as the specification. Checks, measured compile avoidance,
Qt display latency and packaged evidence are recorded in
[optimization validation](PREVIEW_RENDER_OPTIMIZATION_VALIDATION.md).

**Core requirement agreed in discussion:** Instructor, During course and After
course use the same slide source. Render once and reuse across views whenever
the supported view rules and effective deck context produce equivalent output.
Do not require three initial renders merely because three views were requested.

**1. Establish when views can share a render.**

Create an explicit inventory of supported view-dependent behavior in the
framework and deck resolver. Cover slide visibility, content visibility,
conditional pauses, reveal selection, final/omitted slide calls, footer labels,
and frame numbering. Include view-dependent behavior reached through included
files, framework macros and project macro definitions.

Resolve each requested view before grouping it. The grouping must account for
the actual source revision, language, pinned version, occurrence, effective
frame number, preamble/theme, footer settings, reveal sequence and render scope.
A hidden view has no image and requires no compile. Different resolved source
files or versions must never be treated as one shared source revision.

Classify visible views into groups with equivalent effective rendering inputs.
The presence of a supported rule does not automatically require three renders:
a rule may distinguish only one view, leaving the other two equivalent.

| Case | Intended result |
|---|---|
| No applicable view differences, including deck context | One render shared by all three views |
| Instructor differs; During and After are equivalent | Two renders |
| All three effective outputs differ | Three renders |
| Slide hidden in a view | Hidden result, zero renders for that view |
| Custom TeX behavior cannot be classified | Separate rendering for the uncertain views |

Absence of a keyword in the slide file alone is insufficient. The analyzer needs
an audited contract for supported framework behavior and explicit handling of
custom definitions and includes. It should report a reason for each split or
uncertain classification. Commented-out commands must not affect classification.
Changes to relevant definitions, dependencies or the analyzer contract invalidate
the classification. Ordinary supported slides must qualify without requiring
authors to add an opt-in annotation.

Acceptance: independent real-LaTeX reference renders confirm the grouping across
complete ordered page sequences, including dimensions, intermediate reveals,
footers and numbering. Test macro overrides and included view rules as well as
plain slides. Matching only the final page is insufficient for sequence reuse.

**2. Make render requests use those groups.**

Add the classification to the shared request/batch path. Capture source revisions
once, render one representative of each missing group, and associate its result
with every equivalent requested view. Apply this to single-view requests too:
rendering Instructor followed by an equivalent During-course request should reuse
the first result. Share matching in-flight work and preserve cancellation per
consumer, publication guards, per-view statuses and hidden results.

Integrate the continuous-saving follow-ups from [Small UI todos](small_ui_todos.md):
preserve the existing live-render setting, debounce rapid autosaves, and coalesce
queued work to the newest requested revision. Manual render and tool requests for
that same revision should join the existing work. An obsolete completion must
never replace the current image. Saving alone must not trigger extra view renders
when live rendering is disabled; explicit render commands retain their behavior.
Keep source-save status separate from preview freshness so typing does not create
misleading unsaved warnings or flickering render status.

Persist the group evidence so it survives restart. Maintain separate view
provenance even when artifacts are shared. Reuse of a PDF must also account for
view-dependent links, text and metadata; image equality alone cannot authorize
substituting a PDF. If only image reuse is established, obtain a view-specific PDF
when requested. Force rerender bypasses completed reuse and refreshes the affected
group consistently. Cache hits retain the artifact's original timestamp; new
batch renders use one captured timestamp.

Acceptance: an eligible cold all-view batch performs one compile; a warm batch
and a later equivalent-view request perform zero compiles and zero raster jobs.
Two distinct groups perform two compiles. Unknown behavior retains correct output.
With live rendering enabled, a burst of edits leaves at most the already-running
render and the newest queued revision to finish; matching manual/tool requests do
not introduce duplicate work. With it disabled, autosaves update freshness without
starting compilation.

**3. Give the left panel and main pane one image-selection policy.**

Use a shared selection result carrying artifact identity, view/group, source
revision and freshness. Both surfaces should select the same whole-slide final
page for the same context. Preserve intentional differences for region, element,
individual-step, presenter and separately opened standalone previews.

When an edit invalidates a preview, retain the last matching course-view image
with an old-preview label on both surfaces. Add an explicit historical lookup
that can find the previous source revision while preserving the relevant deck,
occurrence, version, language and scope boundaries. Historical results must never
satisfy a fresh render request. After restart, the same fallback policy should
apply. Any legacy Instructor reference must carry the same explicit reference
status on both surfaces; neither surface should silently substitute it.

Acceptance: common edits and view-specific edits do not make the list and main
pane choose different fallback views. Hidden rows remain image-free. Scoped main
previews leave whole-slide thumbnails intact. Newer drafts reject older publication.
Exercise external Claude Code edits as well as editor edits: freshness must follow
actual content and dependencies even before a version marker changes. A missing
or unchanged "+" marker must never establish that the preview is current.

**4. Make cache display inexpensive.**

Move filesystem inventories, dependency hashing and artifact validation off the
GUI thread. Return validated results with a generation/revision guard so an
intervening edit cannot publish an obsolete result as current. Reuse shared
dependency checks within one validation batch; retain content-based invalidation
for edits that preserve file size and modification time.

Store a small, aspect-preserving thumbnail derived from the same final-page
render for every view group. Validate/load the artifacts needed by each consumer
without reading every reveal image for a thumbnail. Missing or corrupt artifacts
should invalidate the relevant request, with complete sequence validation still
required wherever sequence equivalence is used.

Replace full slide-list rebuilds on each render completion with updates to the
affected rows. Profile recorder inputs created during font initialization before
narrowing dependency tracking; do not discard legitimate dependencies to improve
timings. Record validation time separately from compilation and rasterization.

Acceptance: large-deck cache validation leaves Qt responsive, scrolling and
selection stable; thumbnail display does not decode the full-size image or read
every reveal blob. Source, image, framework and file-shadowing changes still miss.

**5. Route deck-wide refresh through the same model.**

Integration status (18 October 2026): deck-scoped UI and tool refreshes now use
`deck_preview_refresh` and the shared render service, with explicit all/selected
view scope, occurrence/view progress and retained partial results. Compatible
Instructor output still publishes legacy snapshots; project-wide snapshot
maintenance keeps its existing pruning path. `WorkspaceWindow.after_version_updates`
is the batched notification hook, used by the existing whole-deck version update.
It refreshes rows once while preserving selection, re-resolves the pane, and
applies the live-render policy without deleting pinned caches. The selected-slides
context-menu command and full-deck PDF import remain pending.


Make deck-wide refresh resolve actual occurrences, pinned versions, translations,
reveal selections and deck settings, then populate the exact per-view/group cache.
Provide explicit selected-view and all-view scope with accurate progress and
partial-failure reporting. Keep legacy snapshot publication for its remaining
consumers, using the exact result where compatible.

Provide a batched invalidation/notification entry point for the pending
**Update Versions… for selected slides** UI item. When that feature is implemented,
multiple version updates should produce one coordinated row refresh and schedule
only previews required by the live-render policy or an explicit render request.
Re-resolve current and pinned calls independently; include any version text shown
in the rendered output when deciding reuse. The context-menu feature itself stays
in the UI backlog; this phase supplies its rendering integration.

Start with the shared scheduler and validated cache hits. Evaluate importing pages
from an existing full-deck PDF as a later optimization: it requires trustworthy
page-to-occurrence mapping and evidence that deck execution context is compatible
with the requested preview. Do not promote generic Instructor snapshots into
verified deck-specific results.

Acceptance: a deck refresh fills the previews shown by both surfaces, including
repeated slides, pinned sources and course variants. Repeating an unchanged
refresh requires no compilation.
Bulk version updates preserve selection, avoid one full-list rebuild per slide,
and keep unchanged pinned calls reusable when their effective inputs remain valid.

**6. Remove remaining duplicate work.**

Implemented: saved and identical-buffer requests share a captured-text rendering
path and identity, including in-flight work. Comparisons reuse validated reveal
images; `preview_pages` caches additional page ranges/resolutions and also serves
PDF inspection tools. Audited pinned calls retain reusable results across new,
non-shadowing frozen siblings, with dependency and contract guards. Cross-edit
selective reuse remains a further extension; source edits still require fresh
evidence and never reuse merely because previous pixels matched.


Unify saved-source and identical-buffer rendering semantics before sharing their
request identities. Preserve actual draft differences and source/publication
checks. Provide a shared page-image API for Compare Rendered and preview tools;
reuse sequence images at a suitable resolution or cache additional requested
resolutions instead of rasterizing them on every opening.

Treat selective invalidation as a further optimization: if the supported-rule
analysis proves a source edit cannot affect a view, retain that view's result with
new evidence. Previous pixel equality is not sufficient evidence after an edit.
Implement this only after pre-render grouping and dependency validation are sound.

Acceptance: rendering an unchanged buffer after its saved equivalent avoids a
duplicate compile; reopening a comparison avoids repeated page rasterization.
Presenter and transcript outputs retain their distinct rendering semantics.

**Validation and delivery order.**

Implement and verify steps 1–6 in order, with focused regression coverage after
each change. Correct the existing MCP test that assumes `refresh_preview` defaults
to Instructor; the current default is all views. Keep an explicit single-view
publication test as well as a default-all test.

The two completed thumbnail/view items in `small_ui_todos.md` are the baseline
for this plan. Preserve their completed status and track this optimization as a
new follow-up. The unrelated chat/model controls, reverse image search, image
description language workflow and existing chat-layout failures remain separate
UI work; this plan does not depend on completing them.

Extend the small real-LaTeX view probe with the grouping cases above. Measure
compile jobs, actual LaTeX passes, raster jobs, cache hits, dependency bytes read,
validation time, and GUI event/paint latency separately. Run timings without
concurrent compilers or tests and distinguish cold font initialization from warm
operation. Verify restart reuse and mutation during rendering/validation.

Baseline from the 16 October evaluation: 204 focused tests passed and one failed
because of the changed refresh default; the real-LaTeX gate passed in 124.20 s.
In that single run, early cache entries recorded about 1 GB of dependencies and
three warm lookups took about 2.4 s; later warm requests took about 0.14 s. These
are diagnostic observations, not a controlled performance comparison or a clean
full-suite result.

Finish with the integrated preview/MCP/GUI checks, documentation updates and a
packaged smoke test. Report compile avoidance and measured display latency
separately; reduced image storage alone does not establish faster rendering.
