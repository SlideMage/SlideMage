# BIG CHANGE 2 — independent Astra review and commit plan

Follow-up, 2026-10-11: the required findings below are now implemented in
SlideMage 6.1.1. An independent Astra re-review found no remaining blockers
after correcting second-edit visibility validation. See
[the fix and verification record](BIG_CHANGE_2_REVIEW_FIXES.md) and
[the passing four-call benchmark](preview-benchmark-review-fixes-2026-10-11.md).
The original review and optional performance proposals remain unchanged below.

Reviewer: `gpt-6-astra`, in a fresh session without the author's conversation history.

Review date: 2026-10-11. Scope: the current uncommitted preview implementation, both benchmark reports and their raw JSON, the benchmark tools, and `/home/juergen/beamer_fast_preview_research.md`. This is a review and implementation plan, not an implementation or commit. Existing production files, tests, examples, and benchmark reports were not changed by this review.

**User constraint added during review:** new benchmarking must use a small subset; an hour-long benchmark is too long. All new gates below target roughly ten minutes or less. The existing 81-call matrix remains historical evidence; no full-corpus rerun is required by this plan.

## Decision

**Keep the main design, but do not commit the current working tree wholesale or describe it as a demonstrated real-edit speed improvement.** The queue, deferred snapshot publication, raster-process isolation, dependency watching and bounded image reuse are useful changes. Fix the lifecycle, context-freshness and cleanup races below, and make the next benchmark reproducible before closing BIG CHANGE 2 as verified. These are bounded fixes; a new renderer is unnecessary for this delivery.

The measured gain is approximately **96 ms per unchanged saved-preview request**: median 0.234 s to 0.138 s. Real edits still take about 4.8–4.9 s in the follow-up controls. The main run actually has a 7.1% higher edit mean after the change. The four controls weaken the case for a persistent regression, but cannot establish its absence across the corpus. Neither dataset supports a new “3× faster while editing” claim.

Real-edit performance deserves a separate, gated commit. The most concrete lead is unnecessary auxiliary-file churn: most measured title edits cause two LuaLaTeX passes, and a retained log identifies the `.aux` change as the rerun reason. The theme writes the edited title into agenda metadata even for a standalone ordinary slide. That is a promising cause to isolate, **not a proved safe pass to remove**.

## What the measurements establish

The following numbers were independently recalculated from the JSON records, rather than copied from the summary tables.

| Measurement | Baseline | Candidate | Interpretation |
| --- | ---: | ---: | --- |
| Oct 9, 77 calls, total | 576.329 s fresh jobs | 191.849 s reused state (1) | 3.004× for a forced rebuild that changes an unused macro, not visible content |
| Oct 9, complete-region reused state (1+3) | Same fresh-job baseline | 187.892 s | Snapshot work differs from the saved-file path; a region is also an input/scope feature |
| Oct 11, 162 visible edits, saved path | 795.001 s; mean 4.9074 s | 851.301 s; mean 5.2549 s | Candidate is 7.08% slower in the full run |
| Oct 11, saved edit median / p95 | 4.8657 / 5.4613 s | 4.8868 / 7.4883 s | Median is close; the candidate tail is materially worse in this run |
| Oct 11, saved cold mean | 7.9065 s | 8.5358 s | No demonstrated first-build gain; both have warm TeX font caches |
| Oct 11, saved unchanged median | 0.233871 s | 0.137823 s | 0.096048 s, or 41.07%, lower observed latency |
| Four interleaved controls, eight edits per implementation | Mean 4.857433 s | Mean 4.817526 s | Difference 39.9 ms / 0.82%; insufficient evidence for a real-edit improvement |

The newer baseline already contains latexmk state reuse. It is not the old fresh-job baseline. The Oct 9 unused-macro injection is explicit in `tools/preview_benchmark/matrix.py:35–42`; the Oct 11 visible edits are generated in `tools/preview_benchmark/compare.py:35–79`. A visible edit can change auxiliary state and require an additional pass, explaining why roughly 2.4 s in the older table and roughly 4.9 s in the newer table are compatible observations.

The Oct 11 JSON contains 405 call/configuration records, 1,620 requests, zero recorded failures, 1,288 matching after-change PDF comparisons, and eight explicitly incomparable overlay requests. The saved and buffer configurations each have 324 comparable results; overlay and buffer-overlay each have 320. These counts agree with the report. The earlier report's totals also agree with its JSON.

For the candidate saved path, independently counted LuaLaTeX passes are:

| Phase | Pass-count distribution |
| --- | --- |
| Cold, 81 requests | 79 with three passes, one with four, one with five |
| Edit 1, 81 requests | 77 with two passes, three with one, one with five |
| Edit 2, 81 requests | 76 with two passes, four with one, one with five |
| Unchanged, 81 requests | 80 with no TeX pass, one with five |

Thus 153 of 162 edits use two passes. The spacing-reference case still uses five passes even when unchanged. The median per-request difference between total edit time and the latexmk stage is **82.0 ms**. Eliminating all that remaining Python/image work cannot halve a typical real-edit request. These are observed wall times, not engine CPU profiles; the stage intervals overlap.

### Limits that matter to the decision

- **The full before/after comparison is not interleaved.** `compare.py:3` and the README prescribe one before run, then one after run. Alternating configuration order at `compare.py:161` interleaves the candidate scopes within the after run, not the two implementations. Time-dependent environment variation is therefore a real confounder. The slower TeX intervals and the four adjacent controls make it plausible, but CPU load, frequency and thermal state were not recorded, so the cause is unproved.
- **The two edits are different workloads, not repeated measurements of an identical edit.** Corpus p95 mixes slide complexity with timing variation. The four diagnostic controls are selected cases, not a representative repeated sample; they omit the five-pass spacing case. Do not replace the slower full-run totals with the control mean.
- **The workload is overwhelmingly title changes.** Per configuration, 156 of 162 edits change titles; the rest are two quote, two body and two graphic-annotation edits. A graphic annotation is not an image-file replacement or a costly TikZ edit. Formula, list structure, wrapping body text, actual media replacement, citation-key changes and overlay-structure changes remain performance evidence gaps, despite those types of slides appearing in the corpus.
- **The combination ranking is not an optimization ranking.** Saved versus buffer is a source choice; selected overlay versus all overlays is an output choice. Their 2–9 ms mean differences are too small and too confounded to choose semantics by speed. Oct 9 region/overlay modes also omitted canonical snapshot work. Keep saved, complete-buffer, region, element and overlay behavior explicit.
- **Element results are separate.** Their 7.725 s fresh and 2.445 s reused means concern four elements with a forced unused-macro change. They do not establish an element word-edit speedup, nor equivalence to a complete slide.
- **PDF comparisons are useful but bounded.** They compare standalone previews at 72 dpi and page dimensions; they do not prove whole-deck equivalence, identical links/annotations/text extraction, or identity at display resolution. A selected overlay intentionally discards other pages. The buffer benchmark also inserts the owning call's `SMSlideSteps`, whereas the GUI can request all buffer steps.
- **Queue responsiveness is not timed by the matrix.** First-plus-latest coalescing demonstrably avoids intermediate work, but the newest request can still wait for the active request and its own TeX passes. The 300 ms automatic-save debounce adds latency to an isolated save; explicit rendering starts immediately. The matrix omits this delay, Qt event delivery and painting.
- **No `.fmt` implementation is established.** Both recorded dumps fail before restore. They justify keeping this probe disabled on the tested installation, not a universal claim that LuaLaTeX format caching is impossible. Component rendering, engine changes and blanket TikZ externalization remain unproved proposals.

## Findings and readiness gates

### F1 — the new pane-destruction handler does not run on actual Qt destruction

**Proved, current implementation; fix before accepting the queue/lifecycle commit.** `src/slidemage/ui/workspace/preview_view.py:202` connects the pane's `destroyed` signal to its own bound `_dispose` method. An actual `deleteLater()` followed by `DeferredDelete` emits `destroyed` to an independent callback, but leaves `_closed == False`. This was reproduced with the installed PySide6, not inferred from a mock. Consequently the guards at lines 428, 439 and 444 do not know the pane has died. The later `RuntimeError` handler around signal emission is useful containment, but is not the lifecycle promised in the implementation document; obsolete raster work and references to pending work remain possible.

Use a small lifecycle token independent of the QWidget, or explicit owner disposal before deletion plus an independent destruction callback. Do not rely on a bound slot on the object currently being destroyed. Completion after destruction must discard its temporary PDF, skip PNG preparation/publication and never launch pending work. Also discard a newly produced temporary PDF when raster preparation fails (`_on_finished`, lines 477–479 currently retains it).

Regression gate: start a genuinely blocked worker, enqueue a second request, actually destroy the parent/pane through Qt, process `DeferredDelete`, then release the worker. Assert the token is closed, no second compile, no raster/publication/open-PDF/UI call, and temporary output removed. A test that directly calls `_dispose()` does not cover this bug.

### F2 — timestamp changes invalidate active requests but not already accepted image identity

**Proved; inherited cache-key omission exposed by the new context signal, not a newly introduced rendering regression.** The new signal correctly rejects an in-flight result after a timestamp change. However `_image` at `preview_view.py:285–296` and insertion at lines 492–498 key session images only by target, view and language. `_on_context_changed` invalidates requests but retains those images. Toggling the footer timestamp after a successful saved render leaves the old image returned as fresh, with no pending render or stale notice. Ad-hoc buffer images have the same missing dimension.

Fix narrowly: carry the timestamp option in accepted-image identity and freshness; keep the old page visible with a clear stale status until a matching render completes. A new context must not immediately fall back to a disk thumbnail and claim that it is verified for that context. Add a test for both saved and buffer renders, and for switching away and back. No timer-driven recompile is required merely because the visible clock later advances a minute.

The broader disk-thumbnail limitation is pre-existing: `preview_target.py:81–91` and `slide_snapshot.py:393–405` validate only source mtime, and disk names do not encode deck preamble, version or dependencies. The new preamble hash protects session target identity, but does not make disk thumbnail freshness exact. Keep these thumbnails explicitly best-effort; a complete persistent provenance redesign is outside the minimum commit.

### F3 — housekeeping's activity check and deletion are not atomic

**Proved race; the new protection narrows an inherited cleanup problem but does not fully solve it.** `housekeeping.py:58–64` releases the activity lock before deleting. A render can enter `active_build` between `is_active` and `rmtree`/`unlink`; the active artifacts are then deleted. A deterministic scheduling reproduction did exactly that. `compile_cached` also creates/touches cache paths before registering them active (`preview_build.py:174–180`). The existing test covers a job that is already active when rechecked, not a job starting just after the check.

Register the build reservation before its first filesystem mutation, and introduce a common guarded cleanup operation that performs the inactive check and deletion under the same synchronization used to reserve a build. Include wrapper deletion and pruning in that contract. Test both orderings with barriers, not sleeps. Preserve compile records and snapshot timestamp exclusions.

`_ACTIVE` is process-local; it cannot protect a concurrent CLI or another application process. OS build locks are already part of the backend, so cleanup must not unlink a cache/lock owned by another process. Use a persistent maintenance-lock protocol outside the removable directory, or conservatively skip the locked preview entries. A child-process lock test is required before claiming general active-build protection. This is cleanup safety, not a reason to introduce parallel TeX execution.

### F4 — benchmark resumption and report generation do not bind results to the complete experiment

**Proved tooling gap; fix before producing a new commit-gating report.** The manifest at `compare.py:116–130` records preamble and slide hashes, but not implementation identity, options, framework/media inputs or tool versions. At line 168 an existing `result.json` is accepted unconditionally. Changing code, `--no-cache`, `--no-images`, `--defer-images`, the edit generator, or an interrupted call's retained cache can silently reuse incompatible results or make a reported “cold” phase warm. A `/tmp` path check alone does not enforce an immutable experiment.

The checked-in JSON has valuable source/environment hashes and supplementary controls, but the documented `summarize.py` path emits only the manifest, summaries and records (`summarize.py:154–165`). Supplemental assembly, including the follow-up control narrative, lives partly in `/tmp/slidemage-big-change-2/finish_docs.py`. Re-running the documented summary command therefore does not reconstruct the delivered report. `/tmp` PDFs, logs and frozen sources are not durable release evidence.

Add a run identity containing normalized source/commit identity, dirty patch digest, framework/project dependency hashes, interpreter/tool versions, options, edit-generator version and ordering seed. Reject incompatible resumes; clean or create a unique per-attempt cold cache for unfinished records. Store attempts atomically and retain failed attempts explicitly. Put control orchestration and final evidence aggregation in repository tools. Archive the frozen inputs, logs and representative/all comparison artifacts with a checksum manifest in a durable artifact location; large PDFs need not enter Git.

For the new subset runs, store the selected immutable call identities and original indices in that manifest. `summarize.py:38–44` currently demands every index from 1 to the full manifest length, so a legitimate `--indices` run is marked incomplete. Make completeness relative to the declared subset, rather than treating `--allow-incomplete` as a passing gate. A time-budget stop must retain usable completed records and explicitly identify missing phases.

The current source differs from the recorded after-source hashes partly because of line endings and formatting. An AST comparison against the retained source snapshot found semantic changes in `preview_raster.py`, version metadata and three GUI files (`centre.py`, `source_view.py`, `preview_view.py`), consistent with later Windows/lifecycle/status work. This does not invalidate Linux backend timing, but the exact final commit still needs its own provenance and targeted checks.

### Release risks and inherited limitations, kept separate from the minimum fixes

- `preview_raster_client.py:63–85` has blocking pipe writes/reads with no deadline. A live but unresponsive raster process can hold `_lock`, block all later raster requests, and obstruct `close()` at shutdown. Process-exit recovery tests do not exercise this case. Add a bounded request timeout and terminate/kill/reap recovery before relying on the helper in packaged releases; validate response shape as a complete request failure. Do not fall back to MuPDF work on a Python GUI worker thread.
- The Windows frozen dispatch/handle restoration is tested through simulations, not a native packaged binary. A native Windows smoke test is a **binary release gate**, not a reason to block reviewable platform-neutral commits. Check first/subsequent render, helper death/hang, non-ASCII/space paths and shutdown without an extra window.
- GUI `_accepts` checks selected source mtime and current buffer, not recorded graphic/include/bibliography state (`preview_view.py:457–465`). Dependency changes while an active preview is compiling can therefore escape GUI freshness checks. This is an inherited limitation, distinct from the new CLI watch support. Avoid “complete invalidation” language; extend to dependency generations later if that guarantee is required.
- The watch path intentionally cannot retry solely because a dependency first mentioned by an unsuccessful initial build appears later. Retaining known missing inputs is useful, but is not complete discovery after failure (`preview_cli.py:69–82`). Keep the documented limitation rather than expanding this change into a file-watcher redesign.
- Rerun-limit acceptance/fresh-state fallback preserves existing behavior and is tested. It is not convergence. Keep the spacing case in totals, and do not silently mark its auxiliary layout stable.
- The fresh-job reference path's error policy and broad disk-thumbnail semantics predate this diff. Reusing the fresh path as a timing reference does not itself prove correctness of every failure case. Do not replace latexmk convergence, bibliography handling or fatal-error checks with a source-only PDF hit.

## Concrete implementation and commit sequence

Use explicit path/hunk staging during implementation. Do not stage `example/*`, `.claude/`, `uv.lock`, or unrelated test edits with the preview work. Keep the original Oct 9/Oct 11 measurement reports as historical evidence; publish any new timings under a new clearly identified run.

| Commit | Scope and dependency | Acceptance gate |
| --- | --- | --- |
| 1. `preview: add reproducible stage tracing and benchmark runs` | `preview_metrics.py`; measurement hooks in `slide_preview.py`/`preview_build.py`; `preview_cli --profile`; `tools/preview_benchmark/{compare,summarize,validate}.py` and README. Implement F4. No behavior claim from this commit. | Metrics disabled has no observable render change; nested stages remain non-additive; identical run resumes, changed implementation/options reject; interrupted cold attempt restarts cold; duplicate/missing/failed phases cannot become a passing report. Recreate a miniature before/after/control report entirely from checked-in commands. |
| 2. `preview: isolate and reuse raster preparation` | `preview_raster.py`, `preview_raster_client.py`, early `cli.py` dispatch, `slide_snapshot.py` prepare/publish/cache, `capture_snapshot` options in `slide_preview.py` and `preview_target.py`; raster tests. Depends on 1's metrics API. | Exact canonical size/pixels, 4:3/cropped display proportions, content-change invalidation at same PDF path, bounded entries/bytes, first/subsequent request, bad/empty PDF, helper exit and unresponsive-helper recovery. No extra Qt window. Existing non-GUI snapshot callers retain their behavior. |
| 3. `preview: publish only the current request and dispose safely` | `preview_view.py`, `state.py`, `centre.py`, `source_view.py`; queue/centre tests. Depends on 2. Implement F1 and F2; clean temporary outputs on raster failure. | Real Qt lifecycle test described above; first/latest only; debounce and explicit bypass; obsolete success/error/source/buffer/preamble/view/language/timestamp cases; accepted-image freshness after timestamp change; valid previous page remains visible on error. Genuine worker test demonstrates event-loop progress. |
| 4. `preview: protect build state and watch recorded inputs` | `preview_build.py` configuration/dependency/locking functions, `preview_cli.py` watching, `compiler.py`, `housekeeping.py`, `deck_headers.py`; dependency/build tests. Depends on 1. Implement F3. | Barrier-based deletion/start race and cross-process lock tests; config/tool/rc invalidation; failed-edit recovery without stale success; missing/recreated dependency; change during compile retriggers watch; wrappers absent from real deck membership. Verify cached SyncTeX disabled while full-deck behavior is unchanged. |
| 5. `preview: document measured latency and release gates` | README, BIG CHANGE 2 planning/implementation docs, new final report/artifact index, version note. Depends on 1–4 and their verification. | Exact final source revision recorded; focused and full suites, required lint/whitespace checks pass; representative adjacent before/after gate below passes or regression is explicitly unresolved. Describe unchanged-request gains and queue behavior, not a new real-edit multiplier. Correct “title/footer edits” to the actual visible-edit workload. |

The unrelated-looking change to `tests/test_review_transcript_import.py` follows the changed manual's call count. Review/commit it separately with the relevant corpus work if needed; it is not preview-speed evidence. Existing `tests/test_centre_gui.py` changes tied to the prepare/publish path belong with commits 2–3.

### Minimum final performance gate for commits 1–5

Use this **fixed four-call subset** of the recorded Oct 11 manifest; retain its slide hashes and original call indices so a later corpus reordering cannot silently select different slides:

| Index | Identity | Role in the subset |
| --- | --- | --- |
| 54 | `1sv-EN-Lists-and-Formulas` | Ordinary text plus formula/list content and an included code fragment |
| 58 | `1c9-EN-Placing-Figures` | Graphic, remembered placement and body text |
| 70 | `1mu-EN-Slidestep-Demo`, steps `1,2` | Multi-page overlays with a comparable overlay-1 reference |
| 80 | `2v9-EN-Itemize-Spacing-Reference` | Known oscillating auxiliary state and fresh fallback |

Run sequential TeX jobs on a frozen scratch project. For each call run the cached saved-file baseline and the four candidate scopes (saved, buffer, overlay, buffer-overlay), one cold build, two visible edits and one unchanged request each: **20 records / 80 requests**. Alternate before-first/after-first order by call, and candidate-scope order within the call. Use versioned edit recipes: one ordinary title change and one actual body/formula or graphic change as appropriate, visibly affecting overlay 1 where it is compared. Do not count two different edits as repeatability. Supplement bibliography/agenda/timestamp/error cases with small deterministic correctness fixtures, or swap one subset identity in a new declared manifest if those are the focus; do not grow the timing subset.

The historical timings of exactly these 80 requests sum to **587.1 s**, including that run's slower interval. Budget approximately 8–10 minutes; this is an estimate, not a deadline guarantee for TeX. Add a wall-time budget checked between requests (finish the active process cleanly) and a STOP check at that same boundary. Report an incomplete run honestly if the budget expires, rather than starting an hour-long matrix. Record ordering and available machine load/frequency information without claiming an unmeasured CPU diagnosis.

The existing `--indices` option can select the calls. After adding subset-aware manifests/completeness, the constituent commands are:

```sh
PYTHONPATH=/tmp/frozen-before-src SLIDEMASTER_PROJECT=/tmp/manual-copy \
  SLIDEMASTER_LATEX="$PWD/latex" .venv/bin/python tools/preview_benchmark/compare.py \
  --output /tmp/bc2-subset --label before --configs saved --indices 54 58 70 80 --repeats 2
PYTHONPATH=src SLIDEMASTER_PROJECT=/tmp/manual-copy \
  SLIDEMASTER_LATEX="$PWD/latex" .venv/bin/python tools/preview_benchmark/compare.py \
  --output /tmp/bc2-subset --label after --indices 54 58 70 80 --repeats 2 --defer-images
```

These two batch commands alone are **not** interleaved. Commit 1 should add a small checked-in orchestrator that invokes their one-index forms in alternating before/after order, shares the immutable four-index manifest, and enforces the common time budget. Do not reuse a result directory from an older implementation or different subset. `--repeats 2` names two edit revisions in the current tool, not two repetitions of the same experiment.

Report cold, changed, unchanged and GUI request-to-publication separately. Cold means explicitly empty slide state; record whether the raster helper and TeX font cache were already warm. Keep the identical source/scope/output reference and include every slow successful attempt and failure. Compare all subset PDF pages at 72 dpi and a few difficult pages at display resolution; check links/text in deterministic fixtures for any optimization that touches agenda/reference metadata. Treat absent overlay references as excluded coverage, not successes. Eight different edit workloads per configuration do not justify a repeatability claim or a stable p95 estimate; publish per-case results and descriptive aggregates.

Acceptance for the responsiveness delivery: zero new failures/mismatches. Flag a per-case cold/edit slowdown over both 5% and 100 ms for diagnosis; do not average it away across scopes. If necessary, repeat only that implementation pair and identical edit transition within the remaining budget, or as a separately identified short follow-up. Do not repeat the entire matrix or all scopes. The flag is a proposed engineering rule, not a confidence interval or proof of regression from one sample. Verify the unchanged benefit in the adjacent run, and use the existing fake-worker GUI fixture for a short request-burst/publication check rather than adding another TeX campaign.

The existing full matrix supplies historical broad output evidence. **Do not rerun all 81 calls for the final backend or for the optional work below.** Targeted tests plus this subset are the new validation scope. If a proposed TeX optimization cannot be justified safely with a small focused proof and deterministic tests, defer it; do not turn that uncertainty into a mandatory hour-long benchmark.

## Separate real-edit performance work, grounded in the traces

### Commit 6A — capture and explain rerun causes

Add a small diagnostic `tools/preview_benchmark/pass_probe.py`. In an isolated project, wrap the configured engine so each successful pass preserves its PDF and `.aux`, `.nav`, `.out`, `.top`, `.bcf` state; preserve latexmk's original command/options and rule reason lines. Diff pass states and compare the first edited PDF with the converged PDF. This is measurement tooling, not a production pass limit.

Probe only **one or two cases**, starting with the subset's ordinary call 54 and, if needed, spacing call 80. Use a title edit and body edit on the ordinary case, within a short separate diagnostic budget (about two minutes), not a new campaign. Existing retained call-10 evidence already provides the lead: `/tmp/slidemage-big-change-2/results/after/saved/010/edit-1.log:419–421` names the `.aux` as the rerun trigger; its final `.aux` contains `\SMAgendaEntryTitle{1nk}{Installing SlideMage 2}`. The writer is `latex/Slidemaster_preamble_base.tex:6806–6816`; its consumer and previous-pass semantics are explicit at lines 6754–6758 and 6830–6843. This identifies a concrete hypothesis to test; it does not prove the agenda line is the only changed state.

Acceptance: each extra pass is attributed to actual changing state for these one or two cases, with retained first/final output evidence. If a body edit already converges in one pass, report that honestly rather than claiming every edit requires two. No additional full-corpus timing is part of this commit.

### Commit 6B — optional standalone agenda-metadata optimization, only if 6A proves it safe

If agenda-title recording is an otherwise unnecessary second-pass trigger, introduce an explicit standalone-preview context from `slide_preview.py`, and narrowly adapt the theme's agenda recording/reading hook. Preserve current-pass title data for any agenda consumer; disable the fast path or use ordinary converging latexmk when the preview actually consumes prior-pass agenda/navigation/reference state. Account for macro-based consumers; a regex search for a command in the source is not a sound dependency proof. Keep full-deck behavior unchanged and version the preview cache key for the new wrapper semantics.

An alternative is a narrowly proved latexmk auxiliary comparison rule for demonstrably irrelevant metadata, but **never ignore all `.aux` changes**, suppress all rerun warnings, force one pass, or skip Biber unconditionally. If safe consumer detection/state handling cannot be established without broad TeX surgery, do not merge this production optimization; the pass diagnostic remains useful.

Acceptance: the target title-edit workload loses one actual TeX pass, and a few selective repeats of that pair establish at least 20% lower median latency. Keep these repetitions within a short follow-up budget; they are not an all-scope repeat. The fixed subset's corresponding standalone PDFs must match at 72 dpi and difficult subset pages at display resolution. Small deterministic fixtures cover agenda titles, hyperlinks, citations, cross-references, overlay placement, remembered positions, timestamps and error recovery; include a title that wraps and changes frame geometry. Retain ordinary fallback and the spacing case; no global pass-count cap. If the subset and focused proof cannot establish metadata safety, defer the optimization instead of requiring a full-manual rerun. These are proposed gates, **not predicted or measured gains**.

Defer `.fmt` adoption until dump *and restore*, font/theme fidelity and invalidation pass on supported engines. Defer extra graphics caches until a measured expensive independent graphic provides a worthwhile workload. Do not substitute a different engine, draft images, lower resolution or component-level reconstruction for ordinary faithful preview in this commit series.

## Independent validation and minimal reproductions

Completed during this review:

- Recomputed Oct 9 totals and Oct 11 totals/means/medians/nearest-rank p95 and comparison counts; recomputed all four control means and pass-count distributions.
- Independently raster-compared 176 retained after/reference PDFs across indices 1, 10, 46, 47, 49, 51, 55, 57, 70, 80 and 81, covering the corrected visible-edit cases and the slow case. All matched. Independently checked 110 edited PDFs from those cases against their cold output; all changed pixels. This is a sampled artifact audit, not a newly run full TeX matrix.
- Ran the command below: **44 passed in 2.56 s**, exit 0. No full TeX benchmark was rerun. The existing 1,461-pass full-suite result is author-provided evidence, not independently repeated here.

```sh
PYTHONPATH=src QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q -p no:cacheprovider \
  tests/test_preview_build.py tests/test_preview_dependencies.py \
  tests/test_preview_queue.py tests/test_preview_raster.py tests/test_preview_target.py
```

The following inline command reproduces F1 and F2 against the reviewed code without TeX or project writes. The cached image is seeded directly to isolate freshness policy; destruction is real Qt `DeferredDelete`.

```sh
PYTHONPATH=src QT_QPA_PLATFORM=offscreen .venv/bin/python - <<'PY'
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QPixmap
from slidemage import preview_target
from slidemage.ui.kit.theme import ThemeManager
from slidemage.ui.workspace.preview_view import PreviewPane
from slidemage.ui.workspace.state import WorkspaceState

app = QApplication([])
with TemporaryDirectory(prefix='astra-review-') as folder:
    path = Path(folder) / 'abc-EN-Test-current.tex'
    path.write_text('BODY')
    preview_target.SLIDES_DIR = path.parent
    preview_target.cached_image = lambda target: None
    host = SimpleNamespace(theme=ThemeManager(), log=print)
    pane = PreviewPane(host, WorkspaceState(), lambda: ('BODY', ''))
    target = preview_target.for_path(path)
    pane.show_slide(target, None, 'Test', '')
    image = QPixmap(320, 180)
    image.fill()
    pane._pixmaps[(target.key, pane.state.view, pane.state.language)] = (
        image, path.stat().st_mtime_ns)
    pane.state.set_footer_timestamp(True)
    print('old timestamp image still fresh:', pane._image(target)[1])
    destroyed = []
    pane.destroyed.connect(lambda: destroyed.append(True))
    pane.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    print('Qt destroyed:', bool(destroyed), 'dispose ran:', pane._closed)
PY
```

Observed output: `old timestamp image still fresh: True`; `Qt destroyed: True dispose ran: False`. After the fixes, regression assertions must require stale image status and a closed independent lifecycle token, respectively.

F3 was reproduced by intercepting `is_active`, taking its false result, entering `active_build` before returning that result, then allowing `remove_temp_files` to continue. The file was deleted although `is_active(cache)` was true afterward. This models the exact permitted thread interleaving; the permanent regression test should use two threads and barriers around that boundary. It does not depend on a timing-sensitive sleep.

The review created only this document. No source implementation, tests, earlier reports, example content, Git index or commit was changed.
