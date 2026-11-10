# Plan: one simple render store

Status: **implemented** on `feature/one-render-store` (v0.15.0, 2026-11-10; steps, commits and measurements in
[one-render-store-steps.md](one-render-store-steps.md)). Design history: revised design, 2026-11-06, amended the same day after evaluation (inventory scope, stale keys, compile
import, guard cost, canonical text hash, batch dependencies) and after a review against the code (just-saved slide
key, alt-text probe, stale keys of unswept labels, compile-import guard, fast-path rule; §1–§3, §7, §8), then
completed (stage assignments, chooser consumers, decisions, risks, done criteria; §4, §6, §9, §10), then the fast
lane brought into scope as stage 4 with a measured pre-started-TeX prototype (§8). Re-checked against `develop` on
2026-11-08 (code references updated; helper stdin for §8 A, frozen versions in compile import, #110's failure
bookkeeping, probe-test allow-list), and again on 2026-11-09 against v0.14.58 (compile-import line, cross-drive
inputs, the slide list's debug-log spans, `.latexmkrc` digest sets, three local tests that call a removed
function). The design is complete; nothing is open that blocks implementation. Store
consolidation is not implemented yet; its prerequisites (#110, #111) have merged. Focused-preview speed improvements
are implemented locally and marked for PR inclusion in §7. Replaces the earlier step 5.1 plan. Tracked in issue #112
(label "plan ready"), which carries a copy of this plan as of 2026-11-08.

Base: `develop` at f168d0a8 (v0.14.58, checked 2026-11-09), which includes #110 (failure bookkeeping, v0.14.24) and
#111 (v0.14.25–34: `slide_templates.py` split out of `slide_snapshot.py`; `previous_preview`, `cached_preview`,
`equivalent_views`, `submit_neighbours`, `cancel_priority` and `slide_snapshot.page_png` removed), both merged
2026-11-07. Every code reference below holds on that commit. Since the previous base 0ef8ba38 (v0.14.49), `develop`
added what the plan has to keep or account for: debug-log spans and events around saves, the slide list's thumbnail
pass and deck reloads, plus a stall monitor (`timing.py`, `stall_monitor.py`, v0.14.52–56); `.bib` paths
from biber's log that are absolute and relative to the deck folder, and project paths on another drive
(`deck_snapshot._is_outside`, v0.14.54); `.latexmkrc` audit entries that accept a set of digests (v0.14.54); one
deck-membership scan per header sync (v0.14.57). None of it changes the design. Check `VERSION_NUMBER` on `develop` again before naming v0.15.0.

Implementation order, subagent tasks and checks: [one-render-store-steps.md](one-render-store-steps.md).

## Goal

One persistent store for complete slide renders. One freshness validator, one image chooser and one rendering
path for interactive requests, bulk actions and the idle sweep. Simplify the data model rather than moving the
preview cache's histories, aliases and special cases into the render store.

## Why (for the PR description)

Today one slide picture can come from two stores with two freshness rules, chosen by two different selection
chains. They disagree, and each fix so far has added another special case.

- **Two stores.** The preview cache (`preview_cache.py`, `render-results/`) holds what the Preview renders; the
  render store (`render_store.py`) holds what the sweep, the reveal bar and deck compiles produce. The same slide,
  view and language is rendered and stored in both.
- **Different freshness rules.** The preview cache reads every input in full and compares an inventory of every
  file name in the project and `latex/`, so a new `media/unrelated.png` or a new deck PDF makes it miss. The render
  store trusts the hash cache's (size, mtime) shortcut and ignores new files, but refuses any slide saved less than
  3 s ago (`render_key.py:174`). Compile import accepts a compile when no input's mtime is *after* its start
  (`compile_records.py:278`). So the same picture is "current" on one surface and "outdated" or missing on the
  other: right after a save the Preview shows it as current while the store has no key for it; after a new
  picture the store shows it as current while the preview cache misses.
- **Different keys.** The preview cache hashes the captured text, the store hashes the file's bytes. A CRLF slide
  gets two keys and is rendered twice.
- **Many selection functions with their own precedence.** The pane's `_image` tries, in order: the render being
  recorded, an ad-hoc cached spec, `select_image` (group lookup, display lookup, display history, transient
  history, `previous_display`), the render store, a held pixmap, the retained previous image, and a flat-snapshot
  reference. The slide list
  uses `preview_thumbnails` (`select_image` with thumbnails) plus `stored_page_path`. The reveal bar has
  `stored_pages`. The store adds origin precedence (`.bg` over provisional, `Lookup.final` by origin, `partial`
  compile pages). `RenderService` adds `cached_spec`, `selected_preview`, `previous_preview`, `is_cached` and
  image-group aliases (`_ImageConsumer`), with leases (`_ArtifactLease`, `_retain_display`, `lent`/`drop_temp`).
- **Several batch paths.** `batch_render.py`, `preview_batch.py`, `update_all_previews.py`,
  `deck_preview_refresh.py` and `BackgroundRenderer.render_batch` each orchestrate multi-slide renders.

What the PR changes for users and maintainers: one store, one key, one validator and one chooser, so the Preview,
the slide list, the reveal bar, the AI tools and the sweep agree on what is current; a render made in the Preview
fills the slide list and the sweep's work at once; the preview path no longer stats every project file before
each render; and the preview cache, image groups, display histories, leases and duplicate batch orchestration
are deleted rather than kept beside the store. The focused-preview speed work in §7 ships with it.

## 1. Store complete results only

Every stored result contains:

- `slide.pdf`, with every reveal step of one whole slide;
- `p001.png`, … at 1920 px wide;
- `thumb.png` (168×95) for the slide list, shrunk from the last 1920 px page with Pillow (Lanczos,
  `preview_cache.thumbnail_png`, as `RenderStore.put` does today), never rendered separately from the PDF. Every
  size then comes from the one stored page, so the thumbnail shows exactly what the Preview shows, and pages
  imported from a deck compile need no second rasterization. Measured on a 1920 px page: shrinking 19 ms, rendering
  at 168×95 4.7 ms. Both run after the pane has its pixels (§3), about 30 s over a full sweep of ~2,200 slides;
  the appendix's 304×171 images (§4) are shrunk the same way;
- `meta.json`: key, logical unit, dependency evidence, frame number and render time.

Keep the existing local object folders, rebuildable SQLite index, disk limit and protected-deck eviction.

**One current object per fast key.** Remove `.bg`, provisional objects, origin precedence and origin-dependent
`Lookup.final`. Every producer uses the same `put`. A successful forced render replaces the existing result.
Producer names belong in logs, not selection rules. An edited slide's older keys stay only until a current
result of the same unit is stored. Until then they are its "Previous render", and afterwards the existing
`_drop_stale` removes them (render-store-cleanup.md step 2, merged). Keeping them until normal eviction would
bring back the 10,000-object store of that plan's finding 1.1. Do not keep user-visible generations of the same key.

**Stale keys of labels the scan does not cover.** `_drop_stale` returns early for a label the last scan did not
see (`background_renders.py:543`): a view or language the sweep does not cover, a slide outside every deck. With
foreground publication, every autosave of such a slide stores one more object and nothing removes the older
ones. So `put` itself drops the same label's other objects, except keys the last scan lists as current; the
scan's restriction applies only to its own leftover clearing. (The early return is at `background_renders.py:546`.)

**Persist only complete, stable results.** Region, element, overlay, presenter and restricted-step renders stay
temporary, owned by the request/pane. Results whose input stability cannot be established may be shown as
unverified temporary results but never become store hits. Failed runs leave the previous result intact. Keep
existing scheduler failure/backoff bookkeeping separate from render objects. That bookkeeping is #110's and stays
whole: the `failures` table with its manifests, including `KIND_MISSING_INPUT` entries
(`Resolver.missing_input_entry`, `render_key.py:238`), so a restored missing file retries the slide; the
`preview_inputs` and `missing_inputs` a failed build attaches to its exception (`preview_build.run_preview`); the
`-g` rerun of a build whose last run failed (`preview_build.py:369`); `current_failures`, which counts only keys the
current decks use; and the one-time `FAILURE_INPUTS_TRACKED` reset. The schema bump (§5) changes every fast key,
so old failure rows simply stop matching; drop them with the old objects rather than converting them.
`missing_input_entry` searches `decks/` and the template folders only; extend it to the citation-format folders
on TEXINPUTS (`citations.citation_dirs`) when moving it, so a restored citation format also retries.

Deck compiles may populate the store only when their evidence is valid and the extracted run is complete,
meaning it has every page this view typesets for the call. Extract the run's own PDF and use the same `put`.
`\slidestep` and `\slidefinal` calls typeset only a selection, so they are skipped and the sweep fills them. A slide
with `\SMFinalStateForStudents` in a student view is complete with its one page, as the owner decided on 2026-11-01
(render-store-cleanup.md D1): the reveal bar shows one step there, which is what students see. Reveal-bar renders
follow the same rule. No partial flags, PDF-less records or producer-specific upgrades are needed.

**Frozen versions.** A deck compile typesets a "+" slide (changed since its last version) from its frozen file
through `\declare@file@substitution` (`slide_versioning.saved_version_lines`); since 851b1761 page compiles do the
same, while the Preview opts out (`deck_context.render_in_deck`, `_saved_versions = False`). Today `ingest_compile`
skips such a slide only because its current file is missing from the compile record (`known is None`,
`background_renders.py:733`). With the key on the captured text hash (§3) that check must stay explicit: import a
slide's run only when the compile record lists the slide's current file with the hash of the text the key was
computed from. Otherwise a page typeset from the frozen version would be stored under the current text's key.

Stage complete objects before publication. Publication, replacement, eviction and reading/copying artifacts use
the same store lock; compilation and rasterization happen outside it. Readers receive bytes or temporary copies,
not unprotected paths for later use. One exception: the slide list's thumbnail delegate keeps receiving a
`thumb.png` path, because a file that eviction removes only shows a placeholder (as today). Multi-page consumers
receive a consistent set or a miss. Open PDF receives a temporary copy. Reuse the existing locking mechanism rather than adding a persistent lease system.

## 2. One freshness implementation

Move the preview cache's reusable evidence helpers into the render-key/validation code before deleting it.
Preserve its before/after stability guard and configuration checks. The hash cache's three-second mtime test is
not a replacement for evidence that inputs stayed unchanged during compilation.

The fast key describes captured slide text, call, view, language, template, preamble, required deck context,
render schema and configuration (environment, tools and rc files). Frame numbering remains outside the key:
numbering-only differences are usable and refreshed last, as previously decided.

Validate recorded dependencies and configuration. Read project inputs in full for the selected Preview;
retain the hash shortcut and audit for the list and sweep. Strict reads must include the source, rc files and
alt-text dependencies. Preserve the existing stronger TeX-file checks when moving the evidence helpers.
Configuration (`configuration_state`: environment, tool stats, rc files) is computed once per validation pass,
like the inventory, not once per unit: the sweep asks for thousands of units.

**A just-saved slide has a key.** Today `fast_key` returns None while the slide file is less than 3 s old
(`render_key.py:174`), so right after every autosave the list and the pane find "Missing" or "Previous" for a slide
the Preview has just rendered. With the captured text hash in the key, drop that test for the source file: a recent
file is hashed by reading its text (slides are a few KB), without entering the shortcut table. The publication
guard below, not the 3-second test, protects against writes during a run.

**A file-name inventory of the search roots, scoped so that new content does not invalidate everything.** It is
collected once per validation pass.

The preview cache's inventory as it stands cannot be used for the store. It compares every file name under the
project and `latex/`, and its skip list leaves out `pdf/`, `.temp/` and `snapshots/`. Measured on #111's tip
(this code is the same on `develop`):
a new `media/unrelated.png` or a new `pdf/newdeck-instructor.pdf` makes a stored record miss. For the store, every
first compile of a deck version, every new picture or slide and every deck snapshot would then make all of its
thousands of results stale, and the sweep (about 45 minutes on the real project) would start over each time.

The rule instead:

- **Not inventoried:** what SlideMage writes and TeX does not search: `pdf/`, `.temp/`, `snapshots/`, plus the
  existing skips.
- **`slides/`, `media/`, `snippets/`:** TeX reads files there only by name. Every `\IfFileExists` in `latex/` (4)
  names a file in the project root, `decks/` or `latex/`. So a name added or removed there invalidates only the
  results that read a file with the same stem. That covers shadowing and graphicx's extension alternatives (a new
  `fig.pdf` beside a recorded `fig.png`).
- **Exception: `media/alt-text.csv` and `media/alt-text.json`.** `SlideMage_alt.lua:89` opens the CSV with Lua
  `io.open`, which the recorder does not log, and the file may not exist when a result is made. These two names
  belong to the conservative part below: creating or removing one invalidates every result. (Changes to their rows
  stay narrowed per picture, `narrow_alt_text`.)
- **Everywhere else in the roots** (the project root, `decks/`, `latex/`, template dirs, TEXINPUTS): any name
  added or removed invalidates every result. That covers the optional inputs (project macros, layout profile,
  citation format, the `.bib` fallback) with no probe list and no TeX resolver.

Each record stores the inventory digest of the conservative part and its input stems. A check is set lookups
after the one walk. If a probe is ever added in `latex/` for a file in a name-scoped folder, a test fails: it greps
the framework's TeX and Lua for probes (`\IfFileExists`, `\InputIfFileExists`, `io.open`, `kpse.find_file`,
`lfs.attributes`) and checks their folders against the rule and its alt-text exception. It allow-lists what is not
a project-folder probe, or it fails on day one: the job's own auxiliary files (`\InputIfFileExists{\jobname.ovl}`,
`\jobname.top`), TeX-tree lookups (`kpse.find_file` of the hyphenation patterns and of the framework's own
`SlideMage_alt.lua` and `SlideMage_measure.lua`) and the `io.open` of a path `kpse.find_file` returned. Counted on
0ef8ba38 and unchanged on f168d0a8 (recounted in step 1.3): 4 `\IfFileExists` calls (plus 2 in comments), 2 `\InputIfFileExists`, 6 `kpse.find_file`, 3 `io.open`.

**The inventory is cached per directory.** Adding, removing or renaming a file always changes its directory's
mtime, so the inventory keeps each directory's names with that mtime and lists a directory again only when it
changed. Capturing the inventory then stats the directories (hundreds), not the files (thousands). It must still be
captured before TeX starts, not concurrently: a file created after TeX looked for it would otherwise be recorded as
present for a result made without it.

Capture evidence before rendering and validate it before publication for every producer. Reject publication
when inputs changed during the run; hashing dependencies only afterward is insufficient. Concretely, note the
start time and the inventory before the run. At publication, reject the result if:

- any recorded project input has an mtime or ctime at or after the start;
- the fast key, computed again, differs;
- the inventory (as above) changed.

This is the preview cache's guard for the files that matter. It does not stat every file in the project twice per
render (`search_state(stability=True)`), which the sweep would pay thousands of times, and which today's Preview
pays before TeX starts (`PreviewCache.begin`, `preview_requests.py:616`).

Import compile results only with equivalent evidence. `compile_records` does not provide it yet: it checks only
that no input's mtime is *after* the compile's start (`compile_records.py:278`), with no ctime, no "at", and no
inventory. Bring it to the same rule (mtime or ctime at or after the start, the inventory as above, the fast key
recomputed at import) or skip the import. Since v0.14.54 a record's `.bib` sources are absolute (biber's relative
names are resolved against the deck folder), and an input on another drive than the project has no relative path
(`deck_snapshot._is_outside`). The import checks such inputs as recorded dependencies by
their content hash (the record already stores a `sha256` per input) and never maps them into a name-scoped
inventory folder.

**Batch and compile dependencies.** A slide gets every file the document read outside `slides/`, `media/` and
`snippets/`, its own slide file, and the media and snippets its text (or a snippet it uses) names, as
`unit_inputs` does now. New: a media or snippet file that **no** slide of the document names goes to **every**
slide, instead of being dropped. The whole batch's dependencies for every slide would be safe too, but for a deck
compile they would make every slide stale whenever any slide's file or picture changed, which would make compile
import worthless.

Missing or undecodable images invalidate the object. Keep validation off the GUI thread.

## 3. One request and rendering path

Extend the existing immutable preview request rather than adding a second request model. It carries the resolved
target, captured text, view, language and options. Background callers capture saved text; interactive and AI
callers may capture unsaved text. The compiler renders that exact text.

Use the captured text hash in the key, replacing the source-file dependency for that request. Do not also
validate against an older on-disk copy. Saving identical text reuses the result. **One canonical hash for every
producer:** SHA-256 of the UTF-8 text as read with universal newlines (`SourceRevision.capture`). Today the render
key hashes the file's raw bytes instead (`HashCache.hash`), which differ for a CRLF file, so on Windows a slide
would get one key from the Preview and another from the sweep and be rendered twice. The hash cache keeps the
canonical text hash under its (size, mtime) shortcut. Retain source identity so
reference selection can check whether a result matches the saved slide.

Keep `RenderService`'s in-flight sharing. All complete results use the same validator and store write. Drop image
groups and aliases: each view has its own result.

Sharing across producers: when the sweep and the Preview share one build (same key), interrupting idle work on
user input (`user_active`) only detaches the sweep's consumer, as in §7; it never stops a build a foreground waiter
holds. "One rendering path" means one request/validation/publication path, not one build folder: the foreground
keeps its own warm build folders, the sweep its background workspace. Build folders are locked per slide and view
(`preview_build._compile_cached`), so a shared folder would let a sweep job block the slide the user just opened.
Explicit bulk actions bypass idle gating but still yield to the foreground priority: no new bulk job starts while
a foreground request waits.

### The fast path: edit to pixels

Measured on this checkout (`tools/preview_bench.py`, edit scenario, warm, `1an-EN-Slide-Versions-current`,
Instructor): 1.70 s request to pixels = `lualatex` 1.41 s + latexmk's own overhead ~0.17 s + rasterization 93 ms
(`prepare_preview_images`, five sizes including the flat snapshots) + lookup, `begin` guard and the rest ~30 ms;
then 13 ms PNG decode on the GUI thread. Per 1920 px page: raster 27 ms, PNG encode 52 ms, QPixmap decode of the
PNG 13 ms, of raw samples 3 ms.

The rule, for every interactive request:

1. **Before TeX** only: the fast key, the miss lookup (a new key misses without strict reads) and the cached
   inventory. Strict full reads happen only on hits (slide selection), never on the edit path.
2. **Pixels next**: rasterize the last page only, at display width, and hand the pane raw samples (or PPM), decoded
   to a `QImage` off the GUI thread. No PNG encoding before delivery. The raster child writes the samples to a file
   in the request's temp folder and returns its path; they do not travel over its JSON pipe. Measured for one
   1920 px page (6 MB): base64 through JSON 77 ms, which would cancel the gain; a file 5.5 ms.
3. **Everything else after delivery**, on the request's worker: PDF copy, every page at 1920 px as PNG, the
   thumbnail, the publication guard, `put` and the same-label cleanup. The pane's step bar and Open PDF read the
   stored object once `put` is done; the pane never holds the request's temp PDF, so the loan machinery
   (`lent`, `_loans_closed`, `drop_temp`'s finalizer) goes away.

This keeps today's deliver-then-record order (`preview_requests.py:662`) as a written rule, so stage 2 cannot put
publication of every page ahead of the pixels.

Use one batch routine for compatible saved requests, with single-render fallback. Initially render unsaved
requests singly through the same service. Fallback preserves force, foreground priority, cancellation and
per-request results. Explicit forced requests bypass failure backoff. Remove duplicate orchestration only after
its callers use this path.

| Action | Scope |
| --- | --- |
| Render all previews now (replaces Update previews) | All decks and views planned by the sweep |
| Rerender all | Current deck, selected or all views, forced |
| Render all views | Current slide, all views, captured editor text |
| AI batch/deck tools | Their captured requests and existing result contract |

Explicit actions bypass idle/battery gating, show progress and support Cancel. The sweep differs only in
planning, priority and gating.

## 4. One image chooser

`render_lookup.select(request, strict=...)` returns a record and one of:

1. **Current:** valid for the request, including numbering-only differences.
2. **Previous render:** last result for the same logical unit, explicitly outdated.
3. **Instructor reference:** eligible saved Instructor result for this slide/template/language from another context.
4. **Missing or hidden.**

The Preview and slide list use this chooser. Temporary scoped renders and held pixmaps remain pane state.

Its consumers and what they pass:

| Consumer | Today | `strict` | Uses |
| --- | --- | --- | --- |
| Preview, selected slide | `selected_preview`, `cached_spec`, `stored_page`, `previous_display` (via `select_image`), the retained image | yes | last page; PDF as a temporary copy |
| Preview read-ahead | `_preload_page` (`stored_page`) | no | last page; confirmed by a strict select when the slide is selected |
| Slide list | `preview_thumbnails` (`select_image`), `stored_page_path`, `ValidationPass.stable` | no | `thumb.png` path |
| Reveal bar | `stored_pages` | yes | every page |
| AI tools, comparisons | `RenderService` lookups, page cache | yes | pages at 1920 px |
| Sweep planning | `Resolver.lookup`, `Lookup.final` | no | state only |

The slide list's thumbnail pass writes debug-log lines since v0.14.56 (`thumbnails.for_outline`,
`thumbnails.stable`, `thumbnails.states` with a count per `select_image` state, `thumbnails.published`). The freeze
investigation reads them. When the chooser replaces `select_image` and `ValidationPass.stable`, keep the event
names and count the chooser's four results in `thumbnails.states`; drop `thumbnails.stable` with the preview cache.

The pane-only states stay outside the chooser: the render being recorded (pixels delivered, `put` not yet done),
temporary scoped renders, and the held pixmap shown as "checking" while a strict select runs.

A request the store cannot answer gets **Missing** and is rendered as a temporary result: a `\slidestep` call with
its own step restriction, region, element, overlay and presenter renders, and unsaved drafts that differ from every
stored key. A `\slidestep` call without a restriction, or the reveal bar's all-steps request for it, is a normal
unit. **Previous render** is the newest object of the same unit label by `rendered_at`; it is never offered for a
hidden slide.

Reference eligibility is one shared filter: complete, stable Instructor result whose source text matches the
saved slide. Choose the newest eligible result deterministically. It remains a reference, not proof of freshness
in the current deck. Exclude unsaved drafts. Label it **Instructor reference**, since it is no longer shared by sync.

The Add slide dialog uses this reference. Appendix generation applies the same filter and makes 304×171 images
from the full-resolution last page in `.build/appendix-thumbs/<template>/`. Do not enlarge the 168×95 list
thumbnail. Missing references produce the existing box. Copy reference data before compilation so eviction
cannot affect the running compile.

AI tools and comparisons reuse stored pages when resolution suffices. Keep the arbitrary-PDF page cache and
raster fallback for other PDFs, temporary scoped renders and higher resolutions.

## 5. Removal and migration

Delete the preview cache, its display/transient histories, image groups and duplicate selection branches after
moving reusable helpers. Deleting image groups removes `preview_equivalence.py`'s audit tables
(`AUDITED_FRAMEWORK`, `AUDITED_PROJECT_TEMPLATES`, `AUDITED_LATEXMKRC`, which since v0.14.54 holds a set of accepted
digests per file), so a framework edit such as v0.14.58's no longer needs a new digest and re-audit note. Delete duplicate batch orchestration after migrating callers. Keep shared slide-parsing
helpers; update tests instead of keeping dead functions merely because tests patch them.
`slide_snapshot.prepare_preview_images` is live code, and the Claude plugin's tests (another repository) patch it
by that name. It stays where it is, or the plugin tests change in the same release. The fast path's last-page raw
delivery (§3) is added as an option of this function, not as a new function, so the plugin tests keep patching
the one rasterization entry point.

Remove flat snapshot writers and `.previews/slide_previews/`, as already decided. Ship as **v0.15.0**, with a
`BREAKING:` changelog entry and the existing compatibility mechanism's one-time notice. Deletion is idempotent,
needs no PNG backup, and is recorded in project metadata for the notice. Explain that deletion syncs and every
computer must be updated.

Delete the old local `render-results` cache; retain `page-images`. Bump the render schema once. Old store objects
must not become current results or eligible references under the new contract; remove them through cache cleanup.
Do not build a conversion pipeline.

Accepted costs: references no longer sync; a cold first compile may show appendix boxes; the initial rebuild
can take about 45 minutes on the previously measured project; equivalent views render separately; skipped
partial imports add sweep work; a name added or removed outside `slides/`, `media/` and `snippets/` (a new
template file, project macros, a deck) still invalidates every result.

## 6. Implementation and checks

Four stages, each kept working. The "Test ..." lists below say which behaviour each stage must keep or
establish. They are not a list of tests to write: tests cover the essentials only (one test per rule the plan
exists for, no edge-case tests), as the test policy in [one-render-store-steps.md](one-render-store-steps.md)
(simplicity rule 7) and each step's list of essential tests say; the remaining points are checked in review or
at the user gate.

1. **Store and validation:** complete objects, one replacement rule, shared evidence helpers, configuration
   (once per validation pass), strict reads, stability guard, canonical text hash and schema bump; the key for a
   just-saved slide; the scoped inventory with its alt-text exception and per-directory cache; the same-label
   cleanup in `put`; compile import brought to the publication rule. Test forced replacement, concurrent
   reads/eviction, dependency edits during long compiles, preserved-size/mtime edits,
   shadowing/optional/extension-alternative inputs and corrupt objects. Test the inventory scope: a new unrelated
   picture or deck PDF keeps results current; a same-stem file in `media/` and a new file in `decks/` make them
   stale; the framework-probe test. Test that a CRLF slide gets the same key from the Preview and the sweep, and
   that an unnamed batch input goes to every slide. Partial imports must never become complete hits.
   Test that a slide saved 0.5 s ago gets its key and a current hit; that creating `media/alt-text.csv` makes
   results stale; the probe test over TeX and Lua; that repeated foreground puts of an unswept label leave one
   object; the directory-mtime inventory cache (add, remove, rename, a new subdirectory); and that a compile
   with an input touched at its start second, or with a ctime-only change, is not imported. Test that a deck
   compile with a "+" slide typeset from its frozen file stores nothing for that slide, and that a failure with a
   missing input still retries once the file (also a citation format) is restored.
2. **Requests and readers:** publish foreground results, preserve unsaved text, switch the consumers of §4's table
   to the chooser, then remove the preview cache and image groups. Apply the fast-path rule (§3): last-page raw
   delivery through a file, PNGs and `put` after delivery, the step bar and Open PDF from the stored object, the
   loan machinery removed; the sweep detaches instead of stopping shared builds; separate build folders; bulk jobs
   yield to the foreground. Test preview-to-save reuse, all-view unsaved
   rendering, numbering differences, temporary scopes, PDF opening and cancellation. Test the fast-path order:
   the pane's pixels arrive before any PNG encoding or `put` (a test hook on the request's stages); interrupting
   the sweep keeps a build the pane waits for; the step bar and Open PDF read the stored object.
3. **Bulk actions and snapshots:** unify batching, change reference/appendix readers, remove obsolete writers and
   migrate folders. Test foreground batch fallback, forced retries, reference eligibility, appendix resolution,
   migration and the one-time notice.
4. **Fast lane (§8):** B first (direct `lualatex` with latexmk fallback), then A (the pre-started TeX), C (render
   on a typing pause) and D (other views in the background), each behind its own switch. Test that B's PDFs match
   latexmk's on the example project (references, citations, agenda, reveal steps) and that every rerun condition
   falls back; that A's and B's pages are pixel-identical to latexmk's, including a slide with an alt-text
   "Image source(s)" line and a picture from `media/`; that A's spare starts and takes its wrapper name on Windows
   (its own stdin pipe, §8 A); that A's spare is discarded on each listed change, is never used twice, and that a result whose
   inputs changed after the spare started is not stored; that C cancels obsolete renders and its result makes the
   autosave a store hit; that D stops on the next edit. Repeat the §7 timing run with each switch.

Run relevant suites during each stage, the full suite and plugin preview suites before release, and compare
`tools/preview_bench.py` before/after. Check PDF lifetime and replacement on Windows. Confirm bulk actions on the
real project. Do not use speculative line-count or token estimates as implementation constraints.

**Done when:**

- `preview_cache.py`, `preview_equivalence.py`, the display/transient histories, `_ImageConsumer`, the leases and
  the duplicate batch orchestration are gone; `render-results/` and `.previews/slide_previews/` are removed on
  first start; no caller outside the chooser decides freshness.
- The full suite, the plugin preview suites and Ruff pass; Windows checks of PDF lifetime and replacement pass.
- The §7 timing run is repeated and its "Stages 1–3" and "With stage 4" columns hold measured values no worse than
  "§7 done"; the stage 4 switches each work on their own.
- On the real project: "Render all previews now", "Rerender all" and a full sweep finish; a new picture in `media/`
  and a new deck PDF leave other results current; the slide list and the Preview agree right after a save.
- The PR description carries the "Why" section and the §7 table; the changelog has the `BREAKING:` entry and the
  version is reconciled with `develop`.

## 7. Focused-preview speed improvements — include in PR

**Status: implemented and validated locally on 2026-11-06; include these changes, tests and measurements in the
PR implementing this plan.** They are not yet committed or submitted. Preserve them when consolidating the
rendering paths in stage 2. They improve updates within the same view and do not depend on sharing results
between views, whose footers can differ.

Implemented changes:

- Start the saved-slide preview on the next event-loop turn, removing the additional 300 ms preview delay.
  Continue coalescing save notifications from the same event-loop turn.
- Detach the pane from an obsolete render when a newer revision is requested. Stop the old compiler only
  when no other consumer needs it; keep identical requests shared. Reacquire cancelled work safely after a
  rapid edit/undo, and reject obsolete completions.
- Collect dependency paths with normalized prefix checks instead of repeated ancestor walks, preserving
  the dependency set and validation guarantees.
- Parse the PDF page once and reuse its display list for the requested preview image sizes.

Estimated time from the user's change to the updated preview, for a warm slide in the same view. "Now" is
`develop`; "§7 done" is the implemented, measured changes; "Stages 1–3" adds the fast-path rule of §3 (last page
only as raw pixels, decoded off the GUI thread, no PNG before delivery; no flat snapshots; cached inventory instead
of `PreviewCache.begin`'s stat of every file; no image-group classification):

| Scenario | Now (measured) | §7 done (measured) | Stages 1–3 (measured) | With stage 4, §8 (measured) | Gain of the PR |
| --- | ---: | ---: | ---: | ---: | --- |
| Change text and immediately press Save | ~2.06 s | ~1.74 s | ~1.70 s | ~0.48 s | ~1.58 s / 77% faster |
| Stop typing and let autosave trigger the preview | ~3.56 s | ~3.24 s | ~3.20 s | ~0.88 s (render on a 0.4 s typing pause) | ~2.68 s / 75% faster |
| An obsolete, unshared preview is already rendering | Finish the old render, then update | Cancel the old render, then update | Same | Same | Also saves the old render's remaining time, minus cancellation overhead |
| Slide list thumbnail after a save | Up to 3 s later than the Preview (store has no key for a file < 3 s old) | Same | With the Preview | Same | Up to 3 s |
| Switch the focused slide to another view | ~1.7 s render | Same | Same | A store hit (~0.05 s) once the background render of that view finished; those renders follow the sweep's idle rules | Up to ~1.7 s |

All rows are for the §7 slide (`1b2-EN-Managing-a-Slide-current`, Instructor). The "Now" and "§7 done" columns
combine the measured median service-request-to-pixels times (1.761 s before, 1.744 s after; a rerun on
2026-11-06 gave 1.74 s, with latexmk 1.60 s and rasterization 110 ms) with the save timers. "Stages 1–3" subtracts
component measurements from §3 (rasterization and decode 110 + 13 ms → about 36 ms: raster 27, file hand-over 5.5,
decode 3; `begin` 16 ms → about 1 ms; image group 3 ms → 0), so it is an estimate, to be confirmed by the
checklist's timing run after stage 2; the `begin` saving grows with the project's file count. "With stage 4"
replaces latexmk's 1.60 s by the measured 0.49 s of a pre-started `lualatex` on the same slide (§8; the other
~0.04 s are SlideMage's own share left after stages 1–3: last-page raster, hand-over, lookup) and, for
autosave, the 1.5 s wait by a 0.4 s typing pause.
Measured after stages 1–3 and after stage 4 (2026-11-10, `tools/preview_bench.py --scenarios cold,unchanged,edit
--slide 1b2 --view instructor --repeat 7`, medians, service request to pixels; the save rows add the save timers):
latexmk only 1.76 s; B (direct `lualatex`) 1.57 s; A + B (pre-started `lualatex`) 0.48 s; a store hit 0.05 s; a cold
forced render 6.3 s. The pre-started process holds about 245 MB. "Stages 1–3" (1.70 s) came out slightly above the
1.64 s estimate: SlideMage's own share is about 60 ms, not 40.
None of these are measured end-to-end GUI paint times. Small file-save and GUI-paint overheads are excluded.
Autosave assumes live preview is enabled and includes the existing 1.5-second delay after typing stops. Work
still needed by another consumer is not cancelled and may contend for the same build workspace. Stages 1–3
leave TeX itself (1.60 s with latexmk) unchanged; stage 4 (§8) removes most of its start-up and the wait for
autosave. The stage 4 column's TeX part is measured with a prototype; the column as a whole is replaced by measured
end-to-end values after stage 4.

Evidence: [implementation and measurement notes](../preview-update-performance.md) and
[raw timing summary](../preview-update-performance.json). Seven warm comment edits of the example slide
`1b2-EN-Managing-a-Slide-current`, Instructor view, on Linux with Python 3.14.5 and TeX Live 2025. An initial
run with different font-cache state is excluded from the comparison.

PR inclusion checklist:

- [x] Implement focused-preview scheduling, dependency collection and rasterization improvements.
- [x] Validate: 428 preview/background regression tests passed, 1 skipped; 9 version/release tests passed;
  Ruff and diff checks passed. Dependency lists match the previous implementation on 30 recorder files.
- [x] Verify real TeX cancellation/recovery at 0.15, 0.6 and 1.0 seconds into a running process; all three
  subsequent renders succeeded. Test shared consumers, identical requests, edit/undo and image equivalence.
- [x] Include the implementation, regression tests, both performance documents and this gains table in the PR.
- [x] Carry the user-facing changelog entry into the final release entry and reconcile the local version bump
  with the merged base and the planned v0.15.0 release. The local entry is numbered v0.14.23, which `develop`
  has already used (it is at v0.14.58); renumber it. Applied onto f168d0a8 (2026-11-09) the code and tests apply
  without textual conflicts; only `CHANGELOG.md` and `version.py` conflict.
- [x] Fix the three local tests that fail on `develop`: `test_edit_then_undo_reacquires_request_that_was_cancelled_while_pending`
  and both cases of `test_new_revision_detaches_obsolete_pane_without_cancelling_other_consumers`
  (`tests/test_preview_queue.py`) call `slide_snapshot.page_png`, which #111 removed (v0.14.25). They were written
  on #110's base, so the 428-test run above did not catch it; the same failure was already there on 0ef8ba38. Build
  the PNG with the live rasterizer (`slide_snapshot.prepare_preview_images`, or a test helper on top of it) instead.
  On f168d0a8 the other 225 tests of `test_preview_build`, `test_preview_queue`, `test_preview_raster`,
  `test_background` and `test_background_renders` pass with the local changes.
- [x] Repeat the same-view timing checks after store consolidation, including save-to-first-paint and busy-render
  cases, to confirm that stage 2 retains these gains and reaches the "Stages 1–3" column; replace its estimates
  with the measured values.
- [x] Put the "Why" section above and the gains table into the PR description, with measured values for every
  column after stage 4.

## 8. Fast lane for the focused slide (stage 4)

In scope of this plan and its PR (owner, 2026-11-06). Stage 4 builds on stages 1–3: the store and the fast-path
rule of §3 stay as they are; these changes shorten the time before TeX produces the PDF. Each is separable and
can be switched off on its own.

Where TeX's time goes, measured on 2026-11-06 on the §7 slide (`1b2-EN-Managing-a-Slide-current`, Instructor),
in its warm build folder after `tools/preview_bench.py --slide 1b2 --keep`, with the precompiled preamble format.
The direct runs use latexmk's own command line, working folder (the project root) and `TEXINPUTS`. The direct and
pre-started rows are the final measurement: 15 rounds, the two alternating so both see the same machine state;
median (range). Two earlier sessions (7 and 2 × 9 runs) gave pre-started medians of 0.54, 0.46 and 0.48 s.

| How the slide is typeset | Time | Output |
| --- | ---: | --- |
| latexmk, as the Preview runs it today (bench edit median; its `lualatex` rule 1.43 s) | 1.60 s | reference |
| `lualatex` run directly, one pass | 1.42 s (1.40–1.54) | pixels identical to latexmk's at 150 dpi, exit status 0 |
| The same wrapper handed to a `lualatex` started 3 s earlier that waits for it | 0.49 s (0.41–0.54) | identical, exit status 0 |
| The same, with the main font loaded before it waits (earlier session, 7 runs; that session's plain pre-started median was 0.54 s) | 0.54 s (0.48–0.55) | identical; no further gain |

For scale, on a trivial document: starting `lualatex` with the format and stopping at once takes 1.04–1.19 s, an
empty document 1.18–1.20 s, one frame with one word 1.23–1.26 s (0.31–0.32 s pre-started). So about 0.9 s of a
warm slide edit's `lualatex` run is start-up (LuaTeX re-initializes Lua and luaotfload in every run; neither is
kept in the format), not typesetting. A started process holds about 230 MB.

The direct and pre-started runs must use latexmk's working folder and `TEXINPUTS` exactly: started from another
folder, pictures in `media/` are not found, and the alt-text file (`SlideMage_alt.lua` opens
`media/alt-text.csv` relative to the working folder) is not read, which drops the visible "Image source(s): …"
line from the slide and the invisible alt text from the PDF.

| Change | Saves | Cost and risk |
| --- | ---: | --- |
| **A. A pre-started TeX for the focused slide.** One spare `lualatex` per focused slide's build folder (format, view, jobname and output folder fixed at start) waits on standard input (`\directlua{token.set_macro("smnext", io.read("l"))}\input{\smnext}`); on a render the wrapper's name is handed to it. It is used once; a new spare starts right after. | ~0.93 s (1.42 → 0.49 s, measured) | ~230 MB while a slide is focused. Discard the spare when the format is rebuilt, the preamble, view, language or deck changes, the window loses focus, or after 10 minutes idle. Needs B (latexmk cannot hand its run to a waiting process). Started in latexmk's working folder with its `TEXINPUTS` (above). Started by its own `Popen` with `stdin=PIPE`: `compiler.run_streamed` and the other helpers give every process `stdin=DEVNULL` since v0.14.46 (a021d645, WinError 6), so the spare cannot go through them. The publication guard's start time is the spare's start. |
| **B. Direct `lualatex` for a warm edit.** Run one pass directly, with latexmk's command line, working folder and `TEXINPUTS`; fall back to latexmk when the `.aux`, `.nav`, `.toc` or `.bbl` changed, or a rerun is requested in the log. | ~0.18 s (1.60 → 1.42 s, measured) | How TeX settles on its final passes (references, biber): tested against latexmk's results on the example project. |
| **C. Render on a typing pause.** With live preview on, render the editor text 0.4 s after the last keystroke instead of waiting for autosave (1.5 s). Autosave then finds a store hit through the canonical text hash. | ~1.1 s (autosave case) | More TeX runs while typing; §7's cancellation of obsolete renders contains them. The lint check runs on the buffer. Off when live preview is off; the delay is one constant to tune. |
| **D. Other views of the focused slide in the background.** After the focused render, render its other views at low priority (cancelled by the next edit). | A view switch shows a current result at once instead of after ~1.7 s | CPU while idle; no effect on the same-view times. |

Combined: change and save at once ~1.64 s → ~0.53 s (A + B: TeX 1.60 s → 0.49 s, measured; the rest of
stages 1–3 unchanged, ~0.04 s); stop typing ~3.14 s → ~0.93 s (A + B + C). Loading the main font before the spare waits
was measured and gains nothing. Skipping the alt text was measured too (same slide, `media/alt-text.csv` with 43
rows renamed, nine runs each): direct 1.40 → 1.36 s, pre-started 0.46 → 0.45 s, within the runs' spread. Not worth
it: the alt text adds the visible "Image source(s)" line, so a preview without it would be wrong.

## 9. Decisions

Made (owner, 2026-11-01 to 2026-11-06):

- A `\SMFinalStateForStudents` slide is complete with its one page in a student view (render-store-cleanup.md D1).
- Image groups are dropped: each view renders and stores its own result.
- Flat snapshots and `.previews/slide_previews/` are deleted; the release is the breaking v0.15.0 with a `BREAKING:`
  entry and the compatibility notice.
- References are no longer synced; the Instructor reference comes from the local store.
- The focused-preview speed work (§7) ships in this PR.
- The fast lane (§8: pre-started TeX, direct `lualatex`, render on a typing pause, other views in the background)
  is in scope, as stage 4 of this PR.
- No code before #110 and #111 merge (both merged 2026-11-07).

Open: none. Tunable during stage 4 without a new decision: the typing-pause delay (0.4 s) and the spare's idle
timeout (10 minutes).

To check at implementation time, not a decision: `VERSION_NUMBER` on `develop` before naming v0.15.0.

## 10. Risks

| Risk | Effect | Mitigation |
| --- | --- | --- |
| A file system or sync client that adds files without changing the directory's mtime | The per-directory inventory cache misses a new name; a shadowing file goes unseen | The sweep's planning pass re-lists every directory in full once per pass; the strict select for the selected Preview re-lists the directories of its recorded inputs |
| The raw-pixel file of the fast path is removed before the pane reads it | No pixels for that render | It lives in the request's temp folder, which is dropped only after delivery; on a read failure the pane waits for the stored PNG |
| Foreground publication on every autosave | Store churn and disk writes per edit | Same-label cleanup in `put` (§1); objects are a few MB; eviction unchanged |
| Deleting flat snapshots syncs to other computers running older versions | Their Add slide dialog and appendix lose references | `BREAKING:` entry and notice: update every computer; references rebuild from the local store |
| The first start after the schema bump | About 45 minutes of sweep on the real project; Preview renders on demand meanwhile | Accepted (§5); explicit "Render all previews now" for those who want it at once |
| Plugin tests patch `prepare_preview_images` | Plugin suites break if the function moves | It stays, with the raw option added (§5); plugin suites run before release |
| Windows: replacing an object while a reader has its PDF open | Replacement fails | Readers get temporary copies (§1); checked on Windows (§6) |
| The pre-started TeX (§8 A) runs with stale state: a framework file or font changed after it started | A wrong picture | Discard rules of §8 A; the publication guard uses the spare's start time, so a changed input keeps the result out of the store |
| The spare's stdin on Windows (§8 A): a GUI process has no console handle to inherit | The spare fails to start or never receives its wrapper name (WinError 6, as before v0.14.46) | Its own `Popen` with `stdin=PIPE`; on any start or write failure the render falls back to B; checked on Windows (§6) |
| Compile import of a "+" slide typeset from its frozen file (§1) | A frozen version's pages stored under the current text's key | Import only when the record lists the slide's current file with the keyed text's hash; tested (§6) |
| The spare's memory (~230 MB) on small machines | Memory pressure | One spare only, for the focused slide; dropped on focus loss and after 10 minutes idle; switch to turn it off |
| Direct or pre-started `lualatex` (§8 A, B) runs in another working folder or with another `TEXINPUTS` than latexmk | Pictures missing (draft boxes), the alt-text "Image source(s)" line and the PDF's alt text silently dropped; exit status 1 | Built from latexmk's own command line, folder and environment; stage 4 test compares pixels with latexmk's |
| Direct `lualatex` (§8 B) misses a needed rerun | Wrong references or citations on the picture | Falls back to latexmk on any changed auxiliary file or rerun request; tested against latexmk's PDFs |
| Typing-pause renders (§8 C) on battery | More CPU while typing | Only with live preview on; obsolete renders are cancelled; the existing battery setting applies |
