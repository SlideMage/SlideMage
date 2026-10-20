# Preview passes: latexmk's third pass, and LuaLaTeX without latexmk (2b)

Status: section 1 implemented in v8.37.0 (`preview_build.PREVIEW_LATEXMKRC`, `RUN_XML_NOTE`, the framework's two
"No file" lines); section 2 is a plan. Base: `feat/parallel-previews` @ 42c6ad0 (v8.36.0).
Follows `docs/plans/parallel-previews-handoff.md` (option 2a/2b). Owner, 2026-10-20: **"Okay, don't skip biber,
but look into the third latexmk pass and make a plan for 2b."**

---

## 1. The third LuaLaTeX pass

### 1.1 What happens

A cold preview render (a slide's first render, a render after its preamble changed, a forced deck refresh, most
background renders) runs `lualatex, biber, lualatex, lualatex`. An **edit** render of a slide that was rendered
before runs one pass, and an unchanged slide none (measured, section 1.4). So the third pass costs only cold renders,
but those are the ones that make up a deck refresh.

Rendered by hand, pass by pass (`lualatex`, `biber`, then three more passes, every helper file hashed after each):

| after | changed helper files | pixels |
|---|---|---|
| pass 1 | everything (all new) | first state |
| pass 2 | `.aux`, `.bbl` (biber), `.run.xml` | final |
| pass 3 | nothing | identical to pass 2 |
| pass 4 | nothing | identical |

Pass 3 is never needed for the example slide; latexmk runs it for three separate reasons, each of which alone forces it:

1. **biblatex's `.bbl` checksum in the `.aux`.** biblatex writes `\abx@aux@read@bbl@mdfivesum{nohash}` +
   `\abx@aux@read@bblrerun` in pass 1 (no `.bbl` yet) and `\abx@aux@read@bbl@mdfivesum{<md5>}` in pass 2. The `.aux`
   changed during pass 2, so latexmk reruns to see whether the document settled. The line only repeats what latexmk
   already tracks through the `.bbl` file itself.
2. **Two spellings of the build folder.** latexmk normalises its output folder with Git-for-Windows Perl's
   `abs_path`, which yields POSIX names (`/c/...`, `/d/...`, `/tmp/...` for `%TEMP%`); LuaLaTeX's `.fls` records the
   same files as `C:/...`. latexmk then holds every helper file twice, and the `C:/` twin of `.nav`/`.aux` is "newly
   in use" in pass 2. Seen in all three places tried: the project folder, `C:\smrc`, and `%TEMP%` (background
   renders' workspace).
3. **Files pass 1 writes but does not read.** latexmk treats a file that a run both reads and writes, and that it did
   not know as an input before, as non-existent at the start of the run, so it always reruns once
   (`latexmk.pl`, `NEW_SOURCE`: code 6 -> `rdb_ensure_file(..., set_not_exists)`). `.aux` and `.nav` escape this
   because LaTeX logs `No file X.nav.` in pass 1, which makes them known inputs. Not so for
   - `.ovl` (`\SMFinalStateForStudents`) and `.top` (Top Margin correction): `Slidemaster_preamble_base.tex` reads them
     with `\InputIfFileExists{\jobname.ovl}{}{}`, which logs nothing when the file is missing;
   - `.run.xml` (biblatex's logreq): read at the end of the document, silently, and its `active="1"` flags flip to
     `"0"` in pass 2 (no effect on the PDF).

### 1.2 The fix (tested)

| cause | fix | where |
|---|---|---|
| 1 | `$hash_calc_ignore_pattern{'aux'} = '^\\\\abx\@aux\@read\@bbl(?:\@mdfivesum\|rerun)';` | a SlideMage-owned rc file passed to preview latexmk runs with `-r` |
| 1b (`.run.xml` flags) | `$hash_calc_ignore_pattern{'xml'} = '^\s*<(?:internal\|external) package="biblatex"';` | same rc file |
| 2 | `$normalize_names = 0;` (previews pass `-outdir`/`-auxdir` themselves, so latexmk's normalisation is not needed) | same rc file |
| 3 `.ovl`, `.top` | `\InputIfFileExists{\jobname.ovl}{}{\typeout{No file \jobname.ovl.}}` (and `.top`): the message `\@input` itself prints | `latex/Slidemaster_preamble_base.tex`, two lines |
| 3 `.run.xml` | `\IfFileExists{\jobname.run.xml}{}{\typeout{No file \jobname.run.xml.}}` | the preview wrapper body (`slide_preview`), after `\begin{document}` |

The rc file only affects previews: deck compiles keep the project's own `.latexmkrc` unchanged. The two framework
lines change nothing but a log line, and help full deck compiles the same way. The wrapper line cannot go into the
framework (biblatex's file) and must not go before `\begin{document}` (that part is the precompiled format).

Each fix alone was tried and is not enough; with all of them a cold render is `lualatex, biber, lualatex`, while an
edit still takes one pass and an unchanged slide none (variants A-F in the session of 2026-10-20).

### 1.3 Consequences to carry with the change

- `preview_equivalence.AUDITED_FRAMEWORK` pins `Slidemaster_preamble_base.tex`'s SHA-256: update it in the same commit
  (the framework rules themselves do not change), or every slide fails closed to per-view rendering.
- The preamble changes, so every precompiled format and preview cache is rebuilt once (automatic).
- `RENDER_SCHEMA` (render_key) does not need a bump if the pixel comparison (1.4) is identical: the render result is
  the same, only fewer passes.
- `configuration_key` must include the new rc file's text (it hashes the rc files it knows), so a change to it
  starts fresh build state.
- The alias of cause 2 has a second form: run from the project root *without* `$do_cd`, latexmk names a build folder
  below the working folder relative (`.build/...`). Every SlideMage project's `.latexmkrc` sets `$do_cd = 1`, so
  previews never meet it; the real-tools test mirrors that.
- A `\textcite` (unlike `\fullcite`, which the slides use) changes the `.bcf` in the second run, so biber and LuaLaTeX
  run once more: a real reason, left alone.
- Keep the file CRLF like the rest of `latex/`.

### 1.4 Measurements

All on this PC (24 logical cores), **while the full test suite ran**, so absolute times are high; compare the ratios.
The fix was applied from outside the code for these runs (an extra `-r` rc file, a copy of `latex/` with the two
lines, the wrapper line added to the wrapper text).

**Pixels.** Every example slide in the Instructor view, plus every fourth slide in both student views: 137 forced
renders in a scratch copy of `example/`, 8 at once, before and after. **All 131 that render are pixel-identical**
(every page, 96 dpi). The other 6 fail both ways: `neg-EN-Installing-LaTeX-Linux` (`\faLinux`, known) and
`dkf-EN-Installing-LaTeX-macOS`, in all three views.

| 131 renders | before | after |
|---|---|---|
| renders with 1 / 2 / 3 / 4+ LuaLaTeX passes | 21 / 22 / 86 / 2 | 21 / 99 / 10 / 1 |
| LuaLaTeX runs | 332 | 254 (-23%) |
| summed render time | 1717 s | 1392 s (-19%) |
| wall time, 137 renders at 8 at once | 264 s | 216 s (-18%) |

The 11 renders that still take 3+ passes need them: a TikZ `remember picture` mark (`\pgfsyspdfmark`) that moves in
pass 2 (e.g. `1jh-EN-Title-Slide`), the Top Margin correction oscillating up to latexmk's limit of 5
(`2v9-EN-Itemize-Spacing-Reference`, already reported as `rerun_limit`), and a view switch in a shared build folder
(the view is set after `\begin{document}`, so all views of a slide share one cache folder; student views write `.ovl`,
Instructor does not).

One slide (`1b2-EN-Managing-a-Slide`), latexmk passes: cold `lualatex, biber, lualatex, lualatex` -> `lualatex,
biber, lualatex`; an edit one pass and an unchanged slide none, before and after.

---

## 2. Option 2b: previews run LuaLaTeX and biber directly

### 2.1 What latexmk does for a preview today

Per preview render (reusable build, `preview_build._compile_reserved` -> `run_preview` -> `compiler.run_latexmk`):

1. **Up-to-date check.** Reads `.fdb_latexmk`, stats (and md5s, when the time changed) every input the last run
   recorded, a few hundred package/font files; "Nothing to do" for an unchanged slide.
2. **Pass logic.** lualatex; biber when the `.bcf` asks for it (and only if every `.bib` exists); lualatex again while
   inputs it watches changed; up to its rerun limit (`run_preview` turns "Maximum runs" into `rerun_limit`).
3. **Configuration.** The project's `.latexmkrc`: engine and options (`$pdf_mode = 4`, `-interaction=nonstopmode
   -file-line-error`), `TEXINPUTS`/`BIBINPUTS` (project root + framework), `$aux_dir`; plus any user/system rc.
4. **Dependency records.** `.fdb_latexmk` is also read by SlideMage itself: `preview_build.recorded_inputs` takes the
   bibliography sources from it (the `.fls` does not list biber's reads); `background_renders._failed_inputs` too.

What it costs: one Perl start (Git for Windows' perl via MiKTeX's latexmk.exe) and the `.fdb_latexmk` work per
invocation, plus a log/fls analysis after every pass. Measured with `preview_metrics` (latexmk stage vs. the time
inside its rules), the 1.2 fix applied, medians of 6, machine busy with the test suite:

| render of one slide | total | LuaLaTeX/biber | latexmk's own | SlideMage around it |
|---|---|---|---|---|
| edit (one pass) | 2.83 s | 1.76 s | **0.56 s** | 0.50 s |
| unchanged ("Nothing to do") | 0.93 s | 0 | **0.48 s** | 0.45 s |
| cold (three steps) | | | ~0.7 s and more | |

"SlideMage around it" is the precompiled format's freshness check (it stats every input of the format), `prune_unused`,
`configuration_key` (six `shutil.which` lookups and the rc files) and publishing the PDF: as large as latexmk's share.

### 2.2 Design

A small pass runner in SlideMage for single-slide previews, in a module of its own (`preview_passes.py`), used by
`preview_build.run_preview` instead of latexmk when the gate (2.3) allows it. Deck compiles keep latexmk.

**State file** per build folder (`<jobname>.passes.json`, written atomically after a successful build):
- the command line, format stamp, environment search state (`preview_cache.search_state`) and wrapper hash;
- every input from the last pass's `.fls` with `(size, mtime_ns, sha256)`, plus the biber inputs (`.bcf`'s
  datasources resolved the way biber did, taken from the `.blg` "Found BibTeX data source" lines);
- the hashes of the helper files after the last pass.

**Up to date** iff the state file exists, the PDF exists, the command/format/search state match, and every recorded
input has the same `(size, mtime_ns)` -- or, where those differ, the same sha256 (as `dep_hash.HashCache` already does
for render keys). No process starts at all for an unchanged slide.

**Passes** (deterministic, so the third-pass problem cannot arise):
1. Snapshot the helper files' hashes (`.aux .nav .out .toc .snm .ovl .top .bbl`), with the two biblatex lines of 1.2
   left out of `.aux` and `.run.xml` not watched.
2. Run lualatex (the same command latexmk runs: format option, `-recorder`, `-synctex=0`, `-interaction=nonstopmode`,
   `-file-line-error`, `-jobname`, `-output-directory`; cwd and TEXINPUTS as today, `preview_format._texinputs` already
   reproduces the rc's search path; BIBINPUTS likewise).
3. Biber when a `.bcf` exists and (no `.bbl`, or the `.bcf` changed since the last biber run, or a recorded `.bib`
   changed, or the log says "Please (re)run Biber"), and every datasource exists (latexmk's veto, so a missing `.bib`
   behaves the same).
4. Run lualatex again while a watched helper file changed during the previous pass, or biber made a new `.bbl`, or the
   log asks for a rerun ("Rerun to get", "Label(s) may have changed", "Please rerun LaTeX"); at most 5 passes in all,
   then `rerun_limit` exactly as now.
5. The font-cache race guard (`font_cache_race`) wraps each lualatex pass (retry that pass), cancellation and
   `lower_priority` per process, `run_streamed` for the log, `preview_metrics` stages per pass.

**Dependency records.** `recorded_inputs` takes the bibliography sources from the state file instead of
`.fdb_latexmk` (keep reading `.fdb_latexmk` when only it exists: older caches, the latexmk fallback);
`background_renders._failed_inputs` the same. `inputs.json` keeps its format. Its content may differ slightly from
today (e.g. no `-1` bibliography entries at all), so some stored background renders count as outdated once.

### 2.3 Gate and fallback

Direct runs only when SlideMage knows what the rc files would do:
- project `.latexmkrc` and `decks/.latexmkrc` match `preview_equivalence.AUDITED_LATEXMKRC` (or are absent), and no
  user/system latexmk rc exists (the paths `configuration_key` already lists);
- engine `lualatex`, biber (not bibtex/makeindex/glossaries) -- detected from the first pass's log/aux; anything
  else hands the build to latexmk (same cache folder, fresh state);
- `SLIDEMAGE_PREVIEW_DIRECT=0` turns it off, like `SLIDEMAGE_PREVIEW_FORMAT=0`.

Otherwise, and whenever the runner meets something it does not handle, latexmk as today (with the 1.2 fix). A build
folder used by one runner is reset before the other uses it (their state files differ).

### 2.4 Expected gain (to confirm in step 1 of 2.5)

- Edit render: about -0.5 s of 2.8 s (-20%); this is the render the user waits for in the editor.
- Unchanged slide: about -0.5 s of 0.9 s, and none of it in a TeX process.
- Cold render: about -0.7 s of ~7 s on an idle machine (-10%); a 17-slide deck refresh correspondingly.

The SlideMage-side ~0.5 s per render (2.1) is as large and much cheaper to cut, with no change in how TeX runs:
cache the format's freshness verdict for a few seconds and per format stamp, run `prune_unused` once per session (or
from the idle scheduler) instead of on every render, and memoise `configuration_key`'s tool lookups per process.
**Recommended order:** the 1.2 fix, then this SlideMage-side trimming, then 2b if edit renders still feel slow.

### 2.5 Steps

1. **Measure** on a quiet machine (no suite running): per render, latexmk's own time (Perl start, fdb analysis,
   per-pass log analysis) for unchanged / edit / cold, from `preview_metrics` rule times vs. the latexmk stage, 17-slide
   deck refresh (`rerender_deck`), and the editor's edit render. Go on only if an edit render saves at least ~0.5 s.
2. **Agree with Jürgen** (`preview_build` and `preview_format` are his): module boundaries, the state file, the gate.
3. `preview_passes.py` + unit tests with a fake engine (pass decisions: no bib, bib unchanged, bib changed, missing
   bib, .bcf change, rerun limit, font-cache race, cancel), then real-TeX tests in `tests/test_preview_build.py`.
4. Switch `run_preview`; port `recorded_inputs` / `_failed_inputs`; keep the latexmk path as fallback.
5. **Equivalence check**: every example slide, all three views, cold and after an edit, direct vs. latexmk: identical
   pixels (the harness of section 1.4), identical `inputs.json` apart from the known differences; then the full suite.
6. Benchmarks again (step 1's set), CHANGELOG, version.

### 2.6 Risks

- latexmk handles cases previews may meet rarely: `\include` files, makeindex/glossaries, a `.bib` found only through
  kpsewhich, `\input` files that appear during a run. The gate and the "unknown -> latexmk" rule cover them; the
  equivalence check over the whole example project is the evidence.
- MiKTeX updates latexmk on its own; a SlideMage runner does not change under it (an advantage), but it also does not
  get latexmk's fixes.
- A wrong "up to date" verdict would show an old preview. The verdict uses the same evidence latexmk uses (the `.fls`)
  plus content hashes, and the PDF is still checked as today (`Build.ok`).
