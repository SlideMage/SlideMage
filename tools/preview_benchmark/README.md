# Preview benchmark

Run from the repository root with the app dependencies and LuaLaTeX installed:

```sh
export PYTHONPATH=src
export SLIDEMASTER_PROJECT="$PWD/example"
python tools/preview_benchmark/run.py --output /tmp/slidemage-bench/baseline
python tools/preview_benchmark/probe_format.py
python tools/preview_benchmark/matrix.py --output /tmp/slidemage-bench
```

Do not run other TeX compilers during measurement. The corpus is every active
slide call in `example/decks/slidemage-manual.tex`, including repeated
`slidestep` calls. Just like the app's preview, each call is rendered as an
instructor preview even if its deck condition normally hides it.

- Baseline uses the original fresh-job compiler, including PNG capture.
- 1: reusable latexmk build state and its recorded dependencies. The format
  probe separately tests whether the research's `.fmt` approach is usable with
  the actual LuaLaTeX/fontspec/manual setup.
- 3: a complete slide-source region in memory, using the owning deck preamble.
- 4: overlay 1 of each frame; an explicit preview selection overrides slidestep.
- 2: `preview.sty` elements are a different output type, not whole Beamer frames.
  They must not be ranked as equivalent full-slide previews.

Each cached combination has a separate build directory. `cold_seconds` includes
its initial compilation; `seconds` measures an input change after that build.
A harmless macro changes between runs, forcing TeX to rebuild while keeping
pixels comparable. This is not a measured word edit, font-cache cold start,
or cache-hit latency. `unchanged_seconds` separately measures an unchanged
request. Noncached configurations always rebuild from scratch.

PDFs, complete logs and per-call JSON are retained. Pixel comparison uses
PyMuPDF at 72 dpi, with visible timestamps disabled in every configuration.
Full-slide output is compared to the original preview path; single-overlay
output is compared to the matching baseline page. This does not claim identity
to a full-deck compilation: existing standalone-preview navigation limitations
still apply. Raw region and overlay previews never overwrite the canonical
full-slide PNG snapshot.

Run `python tools/preview_benchmark/elements.py --output /tmp/slidemage-bench`
after the matrix for result 2 and 1+2, using the manual's actual formula, nested
list, figure and table selections. These are a separate corpus and are not
ranked against complete-slide output.

The matrix holds an interprocess lock. To pause cleanly, create
`/tmp/slidemage-bench/STOP`; it stops after the current preview. Remove that file
and rerun the command to resume completed rows. Do not interrupt only the parent
shell, which can leave a compiler or benchmark child running.

Generate the report and raw JSON using:

```sh
python tools/preview_benchmark/report.py /tmp/slidemage-bench docs/preview-benchmark-2026-10-09.md
```
