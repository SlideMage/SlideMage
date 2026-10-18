# Thumbnail and Preview consistency

Investigated and corrected in v8.21.1 (2026-10-15).

The left panel previously read shared Instructor PNG snapshots keyed by slide,
slide language and template. Those filenames do not identify the deck's footer,
pinned version, repeated occurrence, reveal-step selection or course view. The
main Preview resolves those details and can also render an editor buffer, region,
element or individual reveal step. A recent timestamp on a shared snapshot did
not establish that its content matched the main Preview.

The list now resolves each row against the persistent render cache using the same
source content and render identity as the main Preview. It prefers the same final
whole-slide image for the selected view and language, deck context, frame number,
occurrence and pinned version. It validates recorded dependencies and image
integrity. Shared dependency checks are reused only within one list refresh.
Nothing compiles or rasterizes while constructing the list.

If validation expires, both surfaces can retain their own previous render for the
exact view, source and deck identity, marked as old. These historical images pass
artifact integrity checks but never count as fresh results or skip rendering.
A shared Instructor snapshot is a last-resort reference, explicitly labelled in
the list. Hidden rows show no image for the selected view. Region, element and
individual-step previews can intentionally differ from the whole-slide thumbnail.
Editor changes debounce thumbnail freshness updates without replacing tree items
or disturbing the selection. View, language and footer timestamp changes refresh
the matching context.

The installed-project investigation also found that the TeX recorder included the
generated `.build/preview-formats/.../preamble.fmt` file as a dependency. Rebuilding
that format invalidated otherwise unchanged previews. Dependency recording now
excludes those generated files and retains the format's expanded source inputs.
Adding search candidates, including newly frozen slide versions or images, still
conservatively expires freshness. Previous per-view renders remain visible with
an older-preview notice instead of only Instructor having a fallback.

The deck-wide **Rerender all previews for this deck** command now populates the
same exact occurrence/view cache as the pane and tools, with selected/all-view
scope. Compatible Instructor results still publish legacy reference snapshots.
See [optimization validation](PREVIEW_RENDER_OPTIMIZATION_VALIDATION.md) for the
18 October follow-up.

Validation: 180 targeted cache, request, build, batch, target, pane and list tests
passed, including restart fallback in all three views, hidden rows, pinned and
repeated calls, German translation sources, unchanged-version edits, changed
framework/images, corruption rejection, and selection-preserving list refresh.

The real LuaLaTeX three-view acceptance probe also passed (78.64 seconds),
including warm/restart reuse and source, image and framework invalidation.
The v8.21.1 one-file Linux executable was built and its `--help` entry checked.

Broader tool/MCP/deck-outline/chat/compare integration: 201 passed; the existing
`test_a_six_line_input_and_send_row_fit_at_640px` chat layout test still failed.
This preview change does not modify chat layout. Repository lint and diff checks passed.
