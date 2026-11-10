# Focused preview updates, 2026-11-06

The focused slide now starts rendering on the next event-loop turn after a save, removing the additional
300 ms preview debounce. The source editor already debounces autosave; its existing 1.5-second typing delay
and the live-render setting still control automatic saves and rendering.

A newer request detaches the pane from the obsolete request through a consumer cancellation event. The
existing render service stops the compiler only when its last active consumer leaves. Tool consumers can
finish independently. Identical requests keep sharing their work; rapid edit/undo reacquires a request if
it was cancelled while pending. Cancellation and process termination happen off the GUI thread. Previous
pixels stay visible until the new result arrives, and generation checks reject obsolete completions.

Two rendering costs were reduced without changing freshness rules or TeX pass convergence:

- Dependency collection normalizes its excluded roots once and compares path prefixes, avoiding repeated
  ancestor walks for every recorder input. Generated files remain excluded; similar sibling directory
  names, relative paths and bibliography inputs retain their previous behavior.
- Rasterization parses the PDF page once and replays its display list for all requested image sizes.
  Tests compare exact PNG bytes, including rotated/cropped pages, annotations and transparency.

## Measurements

Linux, Python 3.14.5, TeX Live 2025, LuaHBTeX 1.22.0, latexmk 4.87. The existing
`tools/preview_bench.py` ran seven comment edits of `1b2-EN-Managing-a-Slide-current` in Instructor view,
with the font cache warm for both versions. Raw edit timings are in `preview-update-performance.json`.

| Measurement | Before | After |
| --- | ---: | ---: |
| Additional save-to-render timer | 300 ms | 0 ms (next event-loop turn) |
| Median service request to pixels | 1.761 s | 1.744 s |
| Median PDF copy and dependency collection | 25 ms | 2 ms |

The service benchmark excludes the GUI's save timer and queueing. Its small improvement should not be
presented as a large compiler speedup: TeX still dominates a warm render. The main improvements are the
removed save delay and avoiding completion of an obsolete, unshared render before rendering a newer edit.

An initial run with a newly populated font cache recorded far more dependencies and spent about 250 ms
collecting them. That run is excluded from the before/after comparison because its font-cache state differed.
Dependency lists were also compared against the old implementation for 30 existing recorder files: all
were identical (median collection time 24.76 ms before, 1.83 ms after).

Real TeX renders interrupted 0.15, 0.6 and 1.0 seconds after process registration all successfully rendered
the next revision, taking 1.886, 1.815 and 1.779 seconds respectively. Regression tests cover last-consumer
cancellation, continuing shared consumers, identical-request sharing, rapid edit/undo and stale publication.
