# Preview image equivalence contract (Step 1)

`preview_equivalence.classify_views()` accepts **already resolved, captured**
`PreviewRequest` objects. It returns a stable group for each visible view, a
hidden result for a resolved hidden call, a reason per view, and an evidence
digest with source dependency hashes. The render scheduler consumes this to
share proven image sequences while keeping PDFs bound to their requested view.

The contract concerns the **complete ordered image sequence**, including every
reveal and page dimensions. It does not establish PDF text, links, or metadata
equivalence. Unknown TeX gets a separate group per view. The scheduler
must reclassify when the contract, source, input files, framework, or TeX search
configuration changes.

The audited framework rules are:

| Input | Effective view behavior |
| --- | --- |
| `\omitslide`, `\omitslideversion`, `\conditionalslide`, `\slidestep` | Resolved visibility; hidden calls produce no image. `\slidestep` also restricts selected reveals and can change later frame numbers. |
| `\deckonly`, `\deckuncover`, `\deckvisible` | Instructor emits the original overlay regardless of the optional version list. Student views emit it only when listed. |
| `\conditionalpause` | Adds a pause in listed views; the default list is Instructor. `\slidefinal` suppresses it. |
| `\deckreveal` | Overlay in Instructor, absent During course, immediately present After course. |
| `\deckrevealfinal`, `\deckitem`, `\SMFinalStateForStudents` | Instructor reveal behavior; both student views use the final state. |
| `\fullbleedframe` with several literal image names | Instructor shows image layers across reveals; both student views show the final image. A single image is view invariant. |
| Footer | The deck label differs across all views unless the effective preamble has literal `\def\SMFooterHide{deck}` (or includes `deck` in that list). Omission marker, slide version/language, frame number and footer timestamp are part of the compared context. |

The grouping input includes the project root, exact source path and content
hash, language, pinned version, effective frame number, reveal selection,
call type, occurrence key, preamble text or resolved default template, footer
settings and scope. Cached artifacts retain their original render timestamp. Pinned or translated source paths are
never equated with a different file. Hidden views are resolved before any
source analysis.

Only the pinned framework files (the setup layer, the layout profiles `SlideMage_layout_fira.tex`, `SlideMage_layout_lmsans.tex` and `SlideMage_layout_lmroman.tex`, the base preamble, the generic
template, the greyscale template `SlideMage_template_greyscale.tex` (since v10.18.0) and the bundled citation format `SlideMage_citation_default.tex` and its old-name loader `SlideMage_bibliography_default.tex`, the SlideMage theme `beamerthemeSlideMage.sty` and the Lua files) and
the institution templates whose digests were audited (`AUDITED_PROJECT_TEMPLATES`: a project's own copy, or an installed theme package's, docs/THEME_PACKAGE.md) are trusted. The theme and the layout
profiles (fonts and font metrics) contain no view-dependent rule (no version, footer-hide or
deck-label condition; a test checks that), so pinning their text is the whole audit. A layout
profile of a project's own is not pinned: only a template that names it can select it, and a
template with an unaudited digest is rendered on its own. The default template is accepted when its generated preamble
matches the audited bundled version. Project/deck `.latexmkrc` files must match
the audited search configuration; `TEXINPUTS` may hold exactly the installed theme folders SlideMage puts
there for every compile and preview (after the project root and the framework; any other value is a custom
search path, and a `.sty`/`.cls` in a theme folder fails closed); without `SLIDEMAGE_LATEX`, the stock
`<project parent>/latex` fallback is used. The classifier checks for actual
deck/project search-path shadows, top-level framework import, custom
packages/classes, user search configuration, source and preamble definitions,
dynamic inputs, TeX character escapes, unknown commands/environments, and
conditional preamble code. Such cases fail closed. Literal slide `\input`
files are read recursively using the stock deck/root search roots and become
evidence dependencies. The source scanner is an allowlist of audited commands,
not a general TeX parser; expanding the supported set requires a framework
audit and real reference renders. Custom theme/package behavior, unusual TeX
catcodes, and unsupported render scopes remain separate per view. If a file
cannot be inspected during classification, the affected view remains unknown
and ordinary rendering can proceed.

Bibliography commands and citation consumers are also unknown. A `.bib` field
or custom BibLaTeX style can execute TeX that inspects the deck version, and
this classifier does not inspect those executable inputs. The bundled default
preamble may load BibLaTeX; a plain slide still qualifies if it does not use
bibliography commands.

With a compatible SlideMage preamble that hides only the deck footer
label, 58 of the 91 current slides in the bundled example qualify for a
certain classification. Most remaining slides contain local macro definitions
or commands outside the audited source set. This is a scope measure, not a
render-speed measurement.

The slide list and main Preview use `preview_selection.select_image` for the
same whole-slide final page. Its result records the requested view, original
artifact revision and representative view, stable image identity, freshness,
and exact-view PDF availability. Freshness requires the current cache identity
and dependencies to validate. After an edit, per-requested-view display
history retains the actual artifact used, including group aliases, without
reclassifying the old source. History preserves deck, occurrence, version,
language, scope and saved/buffer context and is never a render cache hit.
Accepted whole-slide images without a validated cache entry use bounded
display-only transient history. The most recently requested eligible saved or
buffer image wins. A legacy Instructor snapshot is an explicit reference on
both surfaces, using the same canonical image path. Hidden slides show no
image; region, element, step, presenter and standalone previews retain their
separate main-pane behavior.

Whole-slide and explicit scoped cache selection run in bounded background
workers. The GUI captures the target, view, language, source/editor text and
generation before dispatch; it accepts a result only when those still match.
Each list batch shares one `ValidationPass`. The worker rechecks the content
hashes of inspected files and the search configuration before returning; the
GUI also rechecks source/editor revisions before publishing. Concurrent edits
cause a new validation rather than publication as a fresh image. Previously
shown pixels remain visible with an unverified label while validation runs.
Render completion refreshes only rows for the affected source path.

New cache generations store a small, aspect-preserving Pillow thumbnail of
the same final-page PNG. The thumbnail has its own content hash, while both
surfaces report the canonical full-image identity. A thumbnail lookup validates
its dependency evidence and thumbnail pixels without decoding the full image
or reading every reveal blob. If a thumbnail is damaged, the validated full
final-page blob remains a display fallback. The main pane validates final
pixels and its exact-view PDF separately; a damaged PDF or unrelated reveal
does not hide good final pixels, and Open PDF can request a fresh exact-view
PDF. Full render/sequence cache consumers still validate their required
artifacts, including the complete sequence used by sequence comparison.
Validation metrics separately record total worker time, dependency hash time
and bytes, configuration time, stability recheck time, GUI event delay and row
publication time. Recorder input collection remains unchanged.

Contract revision 2 uses one captured-text wrapper for saved and buffer renders.
The saved flag remains publication provenance, not a rendering identity input.
Changed draft text still changes the source hash; presenter, scope and overlay
settings remain identity inputs. Compare Rendered uses the validated 144 dpi
reveal sequence for its 130 dpi minimum; additional page-image cache keys include
PDF content, renderer version, page range and resolution. Corrupt cached pages
are regenerated, and PDF mutation during reading cannot publish a cached result.

Audited pinned records retain the classifier contract revision as resolution
evidence. They can survive newly frozen sibling files only when configuration,
recorded dependencies and all existing search candidates are unchanged, the new
files live directly in `slides/`, and none can shadow a recorder basename.
Unknown rules, removed/changed candidates, symlinks and a changed contract still
miss. This does not promote old source revisions after edits or infer reuse from
previous pixel equality.
