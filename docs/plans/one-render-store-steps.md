# One render store: implementation steps

How to implement [one-render-store.md](one-render-store.md) (the design, "the plan" below) step by step, with one
subagent per task. The design says *what*; this file says *in which order, by whom, and how each step is checked*.
Where the two disagree, the design wins; fix this file.

Base: `develop` at f168d0a8 (v0.14.58, 2026-11-09). Check `origin/develop` again at Step 0 and before the release
step; Stefan merges in between.

## How the steps run

**Roles.**

- **Orchestrator** (the main Claude session): prepares each brief, starts one subagent at a time, reads the diff,
  runs the checks, sends fixes back, commits, updates the progress table below and starts the next step without
  waiting for "continue". It stops only at the user gates (marked **USER GATE**) and for decisions that only the user
  can make.
- **Implementer** (one per step): changes code and tests in the shared worktree, does not commit, and finishes with
  the report format below. Default: Codex `gpt-6.1-sol --effort high` for every step, *hard* and *routine*
  (user, 2026-11-09; never the Codex default model). Fallback if Codex is unavailable: a Claude `general-purpose`
  subagent.
- **Reviewer** (one per stage, plus one for every *hard* step): Codex `gpt-6.1-sol --effort high` in review mode,
  or `/code-review high` on the step's diff. Read-only. Reports findings; the orchestrator decides and sends fixes
  to a fresh implementer task.

**Rules for every step.**

- One agent at a time, never in parallel (a system crash ended the last run of parallel agents).
- Work in the worktree `.worktrees/one-render-store` on the branch `feature/one-render-store`, created from
  `origin/develop` in Step 0. Push only to the fork `JuergenFleiss/SlideMage`, never to `origin`. No PR before the
  user has tested (Step R).
- One commit per step (or per fix round), message `Render store <step id>: <what>`, ending with the attribution
  line. Steps do not bump the version or write `CHANGELOG.md`; the orchestrator keeps notes for the final entry
  in the progress table and writes the entry in Step R.
- Every step keeps the app working: the full suite passes at the end of each stage, and the relevant suites pass at
  the end of each step.
- Tests: from the worktree,
  `PYTHONPATH=src QT_QPA_PLATFORM=offscreen /home/juergen/github/SlideMage/.venv/bin/python -m pytest -n 12 -q -p no:cacheprovider --rootdir=. <files or tests>`.
  Lint: `.venv/bin/ruff check src tests`. Known failures that are not caused by this work: the zip-fixture tests in
  `test_citations.py` and `test_theme_sources.py`, and `test_the_default_is_loaded_...` in a worktree (Step 0
  records the exact baseline list).
- A subagent that runs past its size limit (stated in its brief) finishes the change it is on, stops and reports.
  The orchestrator splits the rest into a new task.

**Simplicity rules.** The goal of the whole plan is less code with one way to do each thing. Every step is
judged on that as much as on its tests.

1. **Delete first.** Before adding code, look for what the step makes redundant and remove it in the same step:
   functions, parameters, branches, constants, flags, tests of behaviour that no longer exists. Each step's
   "Done when" names what must be gone.
2. **One way.** One key, one hash function, one guard, one chooser, one batch routine, one put. A second path
   "for now" is allowed only where this file names it (the preview cache written in parallel until 2.6) and is
   removed in the step named.
3. **No new layers.** New modules only where this file names them (`render_evidence.py`, `render_lookup.py`).
   No wrapper that only forwards, no base class or protocol with one implementation, no registry, no manager
   object, no config object for values that are constants.
4. **No options without a caller.** A parameter, keyword or setting exists only if a caller in this branch passes
   both values. No "just in case" hooks; tests observe behaviour through the live code, the existing `timing`
   events or `monkeypatch`, not through test-only hooks in `src/`.
5. **No compatibility code.** Old store objects, old failure rows, `render-results/` and flat snapshots are
   deleted, never converted or read. No aliases for renamed functions (except where the design keeps a name for
   the Claude plugin: `prepare_preview_images`).
6. **Plain code.** Small functions with names that say what they return; data as plain dicts or dataclasses as the
   surrounding code does; comments only for *why* (a measured cost, a decision, a platform quirk), with the
   date or version, as the codebase does now.
7. **Tests: essentials only.** The test suite should end up clean, focused and slim too.
   - A test is essential when it guards a rule the plan exists for and that a user would notice breaking: one
     key per slide text, a store hit after save, stale on a relevant change and current on an unrelated one, no
     result stored when inputs changed during the run, the chooser's four results, pixels before storing, one
     batch routine, the migration, the fast lane's output matching latexmk's.
   - Not essential (do not write them): edge cases and variants (each folder, each rename/add/remove, each
     rerun or discard condition, every view), timing races, corrupt-file handling, error paths that only log,
     tests of private helpers or plain data classes, tests that a signature stayed the same.
   - One test per rule, through the public function, named after the rule. Prefer one end-to-end test of a rule
     over several unit tests of its parts. Parametrize only when the rule itself is "the same for all X".
   - Each step's task block lists its essential tests; that list is the ceiling, not the floor. A step may
     write fewer if one test covers two rules.
   - Delete tests of deleted behaviour and existing tests a new one makes redundant, in the same step. Edge
     cases the design names (§6) are checked in review or at the user gate, not by new tests.

**The brief.** Every subagent prompt is this frame plus the step's task block, copied as written below:

```text
You implement one step of SlideMage's render-store consolidation.
Design: docs/plans/one-render-store.md (read the sections named below in full before you write).
Steps: docs/plans/one-render-store-steps.md (your step only).
Worktree: <path>; branch feature/one-render-store. Do not commit, push or change CHANGELOG.md or version.py.
Treat the instructions as the intent, not a script: if another route reaches the goal more simply, take it and
say so. Small adaptations: make them and list them. Big ones (API shape, user-visible behaviour, moving work
between core and plugins, anything a design decision in §9 settled): do not make them; list them under
"Needs a decision" with your recommendation.
Keep the code as simple, clean and short as the task allows; the simplicity rules in the steps file apply in
full. Delete what your change makes redundant in the same step. No new modules, classes, parameters, settings
or test-only hooks beyond what the task names; no compatibility shims; no duplicated logic; match the
surrounding style. Tests: essentials only (rule 7); write at most the tests your task block lists, delete
the tests your change makes obsolete or redundant, no edge-case tests. Before you report, reread your diff
once only to shorten it: inline single-use helpers, drop unused parameters and branches, merge duplicate tests.
Run: <test command for the step>; ruff check src tests.
Size limit: about <N>k tokens. Past it, finish the current change, stop and report.

Report (at the end, in this order):
1. What changed, file by file (one line each), and `git diff --stat` for src/ and tests/.
2. What you deleted (names), and anything you could not delete yet and why.
3. Tests added or changed, and the test command's result (pass/fail counts; every failure with its first error line).
4. Adaptations you made, and why.
5. Needs a decision (with a recommendation), or "none".
6. Anything you noticed outside your step that the orchestrator should know.
```

**Orchestrator check after each step** (before committing):

1. Read the whole diff. Compare it with the step's "Done when" list and the design sections it names.
2. Run the step's tests and Ruff yourself; never trust the report alone.
3. Simplicity check of the diff, against the rules above: anything added that the task did not name (module,
   class, parameter, setting, hook)? Any old path the step should have deleted still there? Any helper used
   once, branch never taken, or test that repeats another? Any test beyond the step's list, or an edge-case
   test? Send each finding back to the same implementer as one short fix round before committing. Record the
   step's net src/ and tests/ lines in the progress table.
4. "Needs a decision": take the recommended option unless it changes user-visible behaviour or a §9 decision;
   note what was decided in the progress table. Take only those exceptions to the user.
5. Commit, update the progress table, start the next step.

**Simplify pass at the end of each stage** (steps 1.S, 2.S, 3.S, 4.S, after the stage review's fixes): a
*routine* subagent with this task block, then the full suite.

```text
Step <n>.S. Simplification only, no change in behaviour. Scope: the diff of this stage
(git diff <stage start>..HEAD -- src tests). Apply the simplicity rules of docs/plans/one-render-store-steps.md:
inline helpers used once, remove parameters every caller passes the same way, remove dead branches and
constants, fold modules or classes that only forward, shorten comments to the why.
Tests: in the test files this stage touched, remove edge-case tests, tests of private helpers and tests that
repeat another (rule 7); merge tests of one rule into one; trim fixtures nothing uses any more. Keep one test
per essential rule.
Also look one level out: code outside the diff that this stage made unused or duplicate. Do not add
features, abstractions or tests. Keep every public name the Claude plugin uses
(prepare_preview_images).
Run: the full suite and ruff. Report the net lines removed (src and tests) and each change in one line.
```


## Progress

| Step | Title | Implementer | State | Commit | Net src / tests lines | Notes for the changelog |
| --- | --- | --- | --- | --- | ---: | --- |
| 0 | Branch, carry §7 work, baseline | orchestrator + sol high | done | 716c218f | 0 / 0 (0b: 2 lines) | §7 speed-ups (text below); bench edit 1.77 s pixels, latexmk 1.63 s |
| 1.1 | Canonical text hash, key for a just-saved slide | sol high | done | 5f328569 | +8 / +15 | Slide list finds a just-saved slide at once. fileio.text_sha256 is the one hash; 3 s rule kept for non-source inputs (manifests). For 1.4: the schema bump must also clear filehash rows (old CRLF byte digests). |
| 1.2 | Evidence helpers move out of the preview cache | sol high | done | 0757bd6e | +29 / −66 | ValidationPass.configuration once per pass |
| 1.3 | Scoped, cached file inventory and the probe test | sol high | done | 12840dd0 | +61 / +122 | Probe counts corrected (4 IfFileExists, 3 io.open active). Not wired yet. |
| 1.4 | One object per key, same-label cleanup, schema bump | sol high + 1 fix round | done | 7dbfc527 | -53 / -103 | First start re-renders (STORE_FORMAT 2 via SQLite user_version; old rows, failures, filehash dropped). Reveal reader no longer capped at 60 pages. Fix round: readers validate outside the store lock. |
| 1.5 | Publication guard for every producer | sol high + orchestrator fix | done | 46a08a46 | 25 / -23 | All puts via _store_render → Resolver.publishable. Fast key holds configuration_state; orchestrator removed PATH from it (terminal vs desktop start would re-render all). tex_current now content states (FileStates memo). Compile import off until 1.6. |
| 1.6 | Compile import under the publication rule | hard | open | | | |
| 1.7 | Failure bookkeeping kept and widened | routine | open | | | |
| 1.R | Stage 1 review and full suite | reviewer | open | | | |
| 1.S | Stage 1 simplify pass | routine | open | | | |
| 2.1 | The chooser `render_lookup.select` | hard | open | | | |
| 2.2 | Foreground results go into the store | hard | open | | | |
| 2.3 | Fast path: pixels first | hard | open | | | |
| 2.4 | Preview pane on the chooser; loans removed | hard | open | | | |
| 2.5 | Slide list, reveal bar, AI tools on the chooser | routine | open | | | |
| 2.6 | Delete the preview cache and image groups | routine | open | | | |
| 2.R | Stage 2 review, full suite, timing run | reviewer + orchestrator | open | | | |
| 2.S | Stage 2 simplify pass | routine | open | | | |
| 3.1 | One batch routine | hard | open | | | |
| 3.2 | References and appendix from the store | routine | open | | | |
| 3.3 | Flat snapshots removed, migration and notice | routine | open | | | BREAKING |
| 3.R | Stage 3 review, full and plugin suites | reviewer | open | | | |
| 3.S | Stage 3 simplify pass | routine | open | | | |
| G1 | (dropped 2026-11-09: its checks move to Step R's user test) | — | dropped | | | |
| 4.1 | B: direct `lualatex` with latexmk fallback | hard | open | | | |
| 4.2 | A: pre-started TeX | hard | open | | | |
| 4.3 | C: render on a typing pause | routine | open | | | |
| 4.4 | D: other views in the background | routine | open | | | |
| 4.R | Stage 4 review and timing run | reviewer + orchestrator | open | | | |
| 4.S | Stage 4 simplify pass | routine | open | | | |
| R | Release v0.15.0, fork push, **USER GATE** test, PR | orchestrator | open | | | |

Baseline (Step 0, f168d0a8 + §7 work, full suite 2026-11-09: 8 failed, 4703 passed, 55 skipped). Failures not
caused by this work: `test_cli_self_test.py::test_self_test_imports_the_window_modules_and_exits_cleanly`,
`test_presenter_app.py::test_self_test_in_a_subprocess` and both tests in `test_tls_trust.py` (the shared venv lacks
`truststore`, which `develop` now uses); `test_presentation_gui.py::test_the_circle_shows_on_the_projector_when_it_takes_the_mouse`.
The three `test_preview_queue.py` failures (`page_png`) are Step 0b's. The zip-fixture and font-log failures listed
above did not occur in this run.
Ruff on `develop` reports one error: `slide_versioning.py:399` F401 (`HEADER_RE` unused); not ours. Codex's
sandbox needs `TEXMFVAR`/`TEXMFCACHE` set to a writable temp folder for the LaTeX tests.

§7 changelog text (local v0.14.23 entry, to renumber in Step R): "Saved-slide previews start on the next
event-loop turn instead of waiting another 300 ms after autosave. A newer revision detaches the pane from an
obsolete render; the old compiler stops when no other consumer needs it, while shared tool requests can finish.
Rapid edit/undo reacquires cancelled work safely. Preview dependency collection uses normalized path-prefix checks
instead of repeated ancestor walks, and rasterization reuses one parsed PDF page for all image sizes." NEW: Faster
preview updates after saving a slide. - Preview rendering starts without an extra delay after saving. - New edits
replace obsolete preview work while renders needed by other tools can finish.

What has to be gone by the end (sizes on f168d0a8, for scale, not as targets): `preview_cache.py` (834 lines),
`preview_equivalence.py` (642), `preview_selection.py`'s histories and `select_image` (most of 190), the duplicate
batch orchestration in `batch_render.py` (92), `preview_batch.py` (151), `deck_preview_refresh.py` (105) and
`update_all_previews.py` (331); in `preview_requests.py` the leases, `_ImageConsumer`, image groups and the cache
lookups; in `render_store.py` the origin rules; the flat-snapshot functions in `slide_snapshot.py`; and the
pane's selection chain in `preview_view.py`; and their tests (`test_preview_cache.py`, `test_preview_equivalence.py`,
`test_preview_image_groups.py`, `test_preview_selection.py`, most of `test_preview_batch.py` and
`test_update_all_previews.py`). Stages 2 and 3 should each end with fewer src lines and fewer test lines than
they started with; if one does not, its review says why.

---

## Step 0 — Branch, carry the §7 work, baseline

**Who:** orchestrator; one *routine* subagent for task 0b.

**0a (orchestrator).**

1. `git fetch` over HTTPS; note `VERSION_NUMBER` on `origin/develop`.
2. Create the worktree `.worktrees/one-render-store` on `feature/one-render-store` from `origin/develop`.
3. Apply the local §7 work from the main checkout (`git diff HEAD` of `fix/background-failure-inputs`: 
   `preview_build.py`, `preview_raster.py`, `ui/workspace/preview_view.py` and their three test files). Take
   `develop`'s `CHANGELOG.md` and `version.py`; keep the §7 changelog text in the progress table for Step R.
4. Copy `docs/preview-update-performance.md` and `.json` into the worktree (the PR includes them, §7 checklist).
   Copy `one-render-store.md` and this file into `docs/plans/` there; from now on edit them only in the worktree.
5. Baseline: run the full suite and record every failure (the known list plus the three below);
   run `tools/preview_bench.py` (edit scenario, warm, the §7 slide `1b2-EN-Managing-a-Slide-current`, Instructor)
   and keep its summary as `docs/preview-update-performance.json`'s "develop" baseline if it differs.

**0b (subagent, routine, ~60k).** Task block:

```text
Step 0b. Three tests in tests/test_preview_queue.py call slide_snapshot.page_png, which #111 removed:
test_edit_then_undo_reacquires_request_that_was_cancelled_while_pending and both cases of
test_new_revision_detaches_obsolete_pane_without_cancelling_other_consumers. Make them build the PNG with the
live rasterizer (slide_snapshot.prepare_preview_images, or a small helper in the test file or conftest on top of
it). Do not change src/. Read §7 of the design.
Tests: tests/test_preview_build.py tests/test_preview_queue.py tests/test_preview_raster.py
tests/test_background.py tests/test_background_renders.py
Done when: all of them pass.
```

**Done when:** the branch builds on current `develop`, the §7 work and its tests pass, the baseline failure list and
timings are recorded. Commit: `Render store 0: carry the focused-preview speed work onto develop`.

---

## Stage 1 — Store and validation

Design: §1, §2, §3 (the canonical hash paragraph), §6 stage 1. Nothing a user sees changes in this stage except
that the slide list finds a just-saved slide sooner, and the first start re-renders (schema bump).

### Step 1.1 — Canonical text hash and the key for a just-saved slide (*hard*, ~150k)

```text
Step 1.1. Read the design §2 ("A just-saved slide has a key") and §3 ("One canonical hash for every producer").
Code: render_key.py (Resolver.fast_key, line ~171; the 3-second test at ~174; unit_inputs), dep_hash.py
(HashCache), preview_requests.SourceRevision.capture.
Goal:
- One canonical hash of a slide's text for every producer: SHA-256 of the UTF-8 text read with universal
  newlines, as SourceRevision.capture computes it. Put the one function where both render_key and
  preview_requests can import it without a cycle; use it in both.
- HashCache keeps the canonical text hash for the slide source under its (size, mtime) shortcut (other files
  keep their byte hash).
- fast_key no longer returns None for a slide file younger than 3 s: a recent source file is hashed by reading
  its text, without entering the shortcut table. The 3 s rule stays for other inputs only if something still
  needs it; say which.
- The fast key accepts captured text (an unsaved buffer) in place of the file, so the Preview can ask for the
  key of what it renders (used from step 2.2 on).
Essential tests (tests/test_render_key.py, at most 2): a CRLF slide's file and its captured LF text get the same
key; a just-saved slide gets a key.
Run: tests/test_render_key.py tests/test_background_renders.py tests/test_preview_requests.py tests/test_preview_queue.py
Done when: the tests above pass, no caller still hashes slide bytes for a key, the 3-second test for the source
file is gone, and there is exactly one function that hashes slide text (grep).
```

### Step 1.2 — Evidence helpers move out of the preview cache (*routine*, ~100k)

```text
Step 1.2. Read the design §2 (first three paragraphs) and §5 (first paragraph).
Code: preview_cache.py: file_state, FileStates, input_state, dependency_state, find_tool, search_roots,
search_state, configuration_state, thumbnail_png, digest, ValidationPass.inputs / dependency_inputs.
Goal: move the reusable evidence helpers, unchanged in behaviour, into a new module render_evidence.py (Qt-free),
next to render_key. preview_cache.py imports them from there until step 2.6 deletes it; render_store.py takes
thumbnail_png from the new module. Move ValidationPass too and let it also hold configuration_state, computed
once per pass, for the sweep's thousands of units (§2: "computed once per validation pass"). No second pass
object.
Keep the stronger TeX-file checks exactly as they are. Do not change keys or store behaviour.
Tests: move the helpers' tests from tests/test_preview_cache.py into tests/test_render_evidence.py, keeping only
those that guard an essential rule (rule 7); no new tests.
Run: tests/test_preview_cache.py tests/test_render_evidence.py tests/test_render_key.py tests/test_preview_dependencies.py tests/test_background_renders.py
Done when: the tests pass, nothing outside preview_cache.py still uses a moved helper through preview_cache.
```

### Step 1.3 — Scoped, cached file inventory and the probe test (*hard*, ~180k)

```text
Step 1.3. Read the design §2 from "A file-name inventory of the search roots" to the end of "The inventory is
cached per directory", and §10's first risk row.
Code: preview_cache.search_state (today's whole-tree inventory and its skip list), render_evidence.py (step 1.2),
render_key.Resolver, the framework files in latex/ (TeX and Lua).
Goal, in render_evidence.py:
- An inventory of the search roots with three parts: not inventoried (pdf/, .temp/, snapshots/ plus today's
  skips); name-scoped (slides/, media/, snippets/: kept as name stems); conservative (everything else in the
  roots, plus the two names media/alt-text.csv and media/alt-text.json).
- A record keeps the digest of the conservative part and the stems of its inputs. A check is: conservative digest
  equal, and no stem of a recorded input added or removed in the name-scoped part (shadowing and extension
  alternatives: a new fig.pdf beside a recorded fig.png makes it stale).
- Per-directory cache: each directory's names with its mtime; a directory is listed again only when its mtime
  changed. A forced full re-list exists for the sweep's planning pass and for a strict check of the directories
  of recorded inputs (§10 risk 1). The inventory is captured before TeX starts.
- The probe test (tests/test_framework_probes.py): greps the framework's TeX and Lua for \IfFileExists,
  \InputIfFileExists, io.open, kpse.find_file and lfs.attributes; checks each probe's folder against the rule and
  the alt-text exception, with the allow-list of the design (\jobname.ovl, \jobname.top, kpse lookups of
  hyphenation patterns and of SlideMage_alt.lua / SlideMage_measure.lua, the io.open of a kpse result). Counts on
  develop (active calls, recounted in 1.3): 4 \IfFileExists (+2 in comments), 2 \InputIfFileExists, 6 kpse.find_file, 3 io.open.
Do not wire it into the store yet (step 1.5 does); the preview cache keeps its own inventory until 2.6.
Essential tests (at most 2): one scope test in tests/test_render_evidence.py (a new unrelated picture keeps a
check current; a same-stem picture and a new file in decks/ make it stale; it runs through the cached inventory,
so it also shows that a change is seen); the probe test over develop's framework.
Run: tests/test_render_evidence.py tests/test_framework_probes.py
Done when: those pass.
```

### Step 1.4 — One object per key, same-label cleanup, schema bump (*hard*, ~200k)

```text
Step 1.4. Read the design §1 in full and §5 (the paragraph "Delete the old local render-results cache ...").
Code: render_store.py (put, find, _same_render, latest_for_unit, ORIGIN_*, BG_SUFFIX, STORE_FORMAT, rescan,
drop_stale, flags), render_key.Lookup (usable, final), background_renders.py (_drop_stale ~542 with its early
return ~546, ingest_compile ~697, render_batch ~878), reveal_steps / step_renders (reveal-bar producer),
ui/workspace/background_previews.py.
Goal:
- One current object per fast key. Remove .bg, provisional objects, the origin precedence in find(), the
  reveal-specific branch of put(), and the origin rule in Lookup.final. `origin` stays in meta.json and logs only.
  A forced render replaces the existing object.
- Only complete results are stored: slide.pdf (every reveal step of the slide), p001.png ... at 1920 px,
  thumb.png from the last page, meta.json. A deck compile's page without its own PDF: extract the run's own PDF
  (step 1.6 brings the import fully under the rule; here make put() require a PDF and adapt ingest_compile to
  pass the extracted one, or skip the slide). `partial` objects are gone; a \slidestep / \slidefinal compile run
  is not stored.
- put() drops the same unit label's other objects except keys the last scan lists as current (§1 "Stale keys of
  labels the scan does not cover"); _drop_stale keeps its role for the scan's own leftovers.
- Bump STORE_FORMAT once. On open, objects of the old format are never current and never references; remove them
  with the existing cleanup (rescan or a one-time flag like LEFTOVERS_CLEARED). Old failure rows stop matching;
  drop them with the old objects. Do not convert anything.
- Staged publication and reads under the store lock as today; readers get bytes or temporary copies, except
  thumbnail_path (the slide list keeps a path).
Essential tests (in the existing store tests, at most 3): renders of one key from two producers leave one
object; repeated puts of one label leave one object; an old-format object is never found. Delete the tests of
.bg, provisional objects, origin precedence and partial compile pages.
Run: tests/test_background_renders.py tests/test_background.py tests/test_background_previews_gui.py tests/test_reveal_bar_gui.py tests/test_step_renders.py tests/test_render_key.py
Done when: those pass, and grep finds no BG_SUFFIX, ORIGIN_REVEAL precedence or `partial` logic left.
```

### Step 1.5 — Publication guard for every producer (*hard*, ~160k)

```text
Step 1.5. Read the design §2 from "Capture evidence before rendering" to "... before TeX starts
(PreviewCache.begin, preview_requests.py:616)", and §2 "Batch and compile dependencies".
Code: render_evidence.py (steps 1.2, 1.3), render_key.Resolver.build_manifest / manifest_current / tex_current,
background_renders.py (the sweep's render path and render_batch), the reveal-bar producer, render_store.put.
Goal:
- Evidence captured before every render: start time, the inventory (step 1.3), the fast key.
- Validation before every put: reject when a recorded project input has mtime or ctime at or after the start, the
  fast key computed again differs, or the inventory changed. A rejected result may still be shown as a temporary
  result by its caller; it never becomes a store hit.
- Records store the inventory digest and input stems; Resolver.lookup checks them (one inventory per validation
  pass, the ValidationPass of step 1.2).
- Batch dependencies: as unit_inputs does now, plus a media or snippet file that no slide of the document names
  goes to every slide of the batch.
- Strict reads (full content of every project input, rc files and alt-text dependencies) are available as an
  option of the lookup; the sweep and the list use the hash shortcut.
Essential tests (at most 2): a dependency edited during the run (patch the compile to touch it) leaves nothing
stored; an input no slide of a batch names goes to every slide.
Run: tests/test_background_renders.py tests/test_render_key.py tests/test_render_evidence.py tests/test_batch_render.py tests/test_preview_dependencies.py
Done when: those pass and every put() caller goes through the guard (list them in the report).
```

### Step 1.6 — Compile import under the publication rule (*hard*, ~150k)

```text
Step 1.6. Read the design §1 ("Deck compiles may populate the store ..." and "Frozen versions") and §2
("Import compile results only with equivalent evidence ...").
Code: compile_records.py (write_record ~228, the mtime test ~278, parse_blg_sources, check_record),
deck_snapshot.py (_is_outside, run_recorded_compile), background_renders.ingest_compile (~697, the
`known is None` test ~733), slide_versioning.saved_version_lines, deck_context.render_in_deck.
Goal:
- write_record captures the same evidence as step 1.5 (start time, inventory) and rejects on mtime or ctime at or
  after the start; ingest_compile recomputes the fast key and checks the inventory before put.
- Import a slide's run only when the record lists the slide's current file with the hash (step 1.1's canonical
  hash) of the text the key was computed from. A "+" slide typeset from its frozen file is skipped.
- Inputs outside the project (absolute .bib paths since v0.14.54, another drive) are checked by their sha256 in
  the record and never mapped into a name-scoped inventory folder.
- A run is imported only when it has every page this view typesets for the call; \slidestep / \slidefinal runs
  are skipped.
Essential tests (at most 2): a compile with an input changed during it imports nothing; a deck compile with a
"+" slide stores the other slides and nothing for that one.
Run: tests/test_compile_records.py tests/test_background_renders.py tests/test_deck_snapshot.py
Done when: those pass.
```

### Step 1.7 — Failure bookkeeping kept and widened (*routine*, ~60k)

```text
Step 1.7. Read the design §1 ("Persist only complete, stable results ..." to the end of that paragraph).
Code: render_key.Resolver.missing_input_entry (~238), citations.citation_dirs, render_store failures tables,
preview_build.run_preview (preview_inputs / missing_inputs on the exception), the -g rerun (~369),
background_renders.current_failures, FAILURE_INPUTS_TRACKED.
Goal: check that steps 1.4–1.6 kept #110's failure bookkeeping whole (list what you checked). Extend
missing_input_entry to the citation-format folders on TEXINPUTS, so a restored citation format retries.
Tests: the existing missing-input retry test must still pass; no new test (the citation folders go through the
same code path).
Run: tests/test_background_renders.py tests/test_preview_build.py tests/test_render_key.py
```

### Step 1.R — Stage 1 review

- Reviewer task: "Review the commits of steps 1.1–1.7 against the design §1, §2 and §6 stage 1. Look for: a put()
  path that skips the guard, a key computed from bytes instead of the canonical text hash, an inventory captured
  after TeX starts, an object that can be found while incomplete, lost failure bookkeeping, old-format objects
  still found. Also list any second path, duplicate logic or leftover the stage should have deleted. Report
  findings with file:line and a failure scenario; no style comments (the simplify pass handles style)."
- Orchestrator: send confirmed findings to one fix task; run the **full suite**; compare failures with the Step 0
  baseline; commit `Render store 1.R: review fixes`.

---

## Stage 2 — Requests, readers and the fast path

Design: §3, §4, §5 (first paragraph), §6 stage 2, §7 (keep its gains). Users see: the slide list and the Preview
agree right after a save; a Preview render fills the list at once.

### Step 2.1 — The chooser `render_lookup.select` (*hard*, ~150k)

```text
Step 2.1. Read the design §4 in full.
Code: render_key.Resolver.lookup / Lookup, render_store.find / latest_for_unit, preview_selection.py
(select_image, legacy_reference: what it does today), ui/workspace/background_previews.py (stored_page ~507,
stored_page_path ~518, stored_pages ~536).
Goal: a new Qt-free module render_lookup.py with select(request, strict=...) returning a record and one of
Current (including numbering-only differences), Previous render (newest object of the same unit label by
rendered_at; never for a hidden slide), Instructor reference (the shared eligibility filter: complete, stable
Instructor result whose source text matches the saved slide; newest eligible, deterministic; never for unsaved
drafts), Missing or hidden. Requests the store cannot answer (scoped step restriction, region, element, overlay,
presenter, unsaved drafts with no stored key) return Missing. Readers: last page bytes, every page (consistent set
or a miss), thumb path, PDF as a temporary copy. Sweep planning gets a state-only form.
No consumer switches in this step.
Essential tests (tests/test_render_lookup.py, at most 2): one test walks a slide through the four results
(current, edited: previous, another context: Instructor reference, nothing stored: missing); one test that the
newest eligible reference is chosen.
Run: tests/test_render_lookup.py tests/test_render_key.py
```

### Step 2.2 — Foreground results go into the store (*hard*, ~220k)

```text
Step 2.2. Read the design §3 (to "Explicit actions bypass idle/battery gating ..." inclusive) and §7's list of
implemented changes (they must keep working).
Code: preview_requests.py (PreviewRequest, SourceRevision, RenderRequest, RenderService.request, cached_spec,
selected_preview, is_cached, the in-flight sharing), preview_build.py (_compile_cached build-folder locks),
background_renders.py (user_active, interrupt), render_scheduler.py, render_store.put via the step 1.5 guard.
Goal:
- The Preview's complete results (whole slide, all steps, a normal unit) are published with the same guard and
  put as the sweep, keyed on the captured text (step 1.1). Scoped renders stay temporary, owned by the request.
- The request keeps carrying the captured text; the compiler renders that exact text; saving identical text later
  is a store hit.
- In-flight sharing stays. When the sweep and the Preview share one build (same key), user_active detaches the
  sweep's consumer and never stops a build a foreground waiter holds.
- Foreground and sweep keep separate build folders; explicit bulk jobs start no new job while a foreground request
  waits.
- Do not change what the pane shows yet (step 2.4); the preview cache keeps being written in parallel until 2.6
  so nothing regresses in between.
Essential tests (at most 2): render unsaved text, save the same text: store hit, no TeX run; interrupting the
sweep keeps a build the pane waits for. §7's tests still pass.
Run: tests/test_preview_requests.py tests/test_preview_queue.py tests/test_preview_build.py tests/test_background_renders.py tests/test_render_scheduler.py tests/test_background.py
```

### Step 2.3 — Fast path: pixels first (*hard*, ~200k)

```text
Step 2.3. Read the design §3 "The fast path: edit to pixels" and §5 (the paragraph on
slide_snapshot.prepare_preview_images), §10 rows 2 and 6.
Code: slide_snapshot.prepare_preview_images (~181), preview_raster.py, preview_raster_client.py,
preview_requests.py (RenderRequest.wait, the deliver-then-record order ~662), ui/workspace/preview_view.py
(where the pane decodes the PNG).
Goal:
- Before TeX only the fast key, the miss lookup and the cached inventory (no strict reads on the edit path).
- Add a raw last-page option to prepare_preview_images (not a new function: the Claude plugin's tests patch it by
  name): the raster child writes the last page's raw samples (or PPM) at display width to a file in the request's
  temp folder and returns its path over its pipe; the pane decodes it to a QImage off the GUI thread.
- After delivery, on the request's worker: PDF copy, every page at 1920 px as PNG, the thumbnail, the guard, put,
  the same-label cleanup. If the raw file cannot be read, the pane waits for the stored PNG.
- No test-only hook in src/: the order is observed through the existing timing events (timing.span /
  timing.event; add a span per stage only if the debug log benefits from it too) or by monkeypatching the
  PNG encoder and put.
- Delete the flat-snapshot size from this path's raster widths (the fast path rasterizes the last page once).
Essential test (1): the pane's pixels arrive before any PNG encoding and before put, and equal the stored
page's pixels.
Run: tests/test_preview_raster.py tests/test_preview_requests.py tests/test_preview_queue.py tests/test_preview_build.py
Also run tools/preview_bench.py (edit scenario, warm, the §7 slide) and put its summary in the report.
```

### Step 2.4 — Preview pane on the chooser; loans removed (*hard*, ~220k)

```text
Step 2.4. Read the design §4 (table rows "Preview, selected slide" and "Preview read-ahead", and the pane-only
states paragraph) and §3 point 3 ("The pane's step bar and Open PDF read the stored object ...").
Code: ui/workspace/preview_view.py (_image and its chain, _preload_page ~267, _retain_display uses ~776, the step
bar, Open PDF), preview_requests.py (_ArtifactLease, lent, _loans_closed, drop_temp's finalizer,
release_artifact), ui/workspace/background_previews.py (stored_page).
Goal: the pane asks render_lookup.select (strict for the selected slide, non-strict for read-ahead confirmed by a
strict select on selection). Pane-only states stay pane state: the render being recorded, temporary scoped
renders, the held pixmap shown as "checking" during a strict select. The step bar and Open PDF read the stored
object (Open PDF gets a temporary copy). Delete the loan machinery; the pane never holds the request's temp PDF.
Remove the pane's other selection branches (ad-hoc cached spec, select_image, previous_display, the retained
previous image, the flat-snapshot reference) and say in the report which pane behaviour each one covered and how
the chooser covers it now.
Essential tests (at most 2): the pane shows what the chooser returns (one GUI test, current and previous);
a scoped render stays temporary (one scope stands for all). Delete the tests of the removed branches and the
loans. Open PDF during replacement is checked on Windows at the user gate.
Run: tests/test_preview_queue.py tests/test_preview_requests.py tests/test_reveal_bar_gui.py tests/test_background_previews_gui.py and every test file that imports preview_view (list them).
```

### Step 2.5 — Slide list, reveal bar, AI tools on the chooser (*routine*, ~150k)

```text
Step 2.5. Read the design §4 (the table rows "Slide list", "Reveal bar", "AI tools, comparisons", "Sweep
planning", the debug-log paragraph, and the last paragraph on AI tools).
Code: preview_thumbnails.for_outline, ui/workspace/slide_list.py (the thumbnail pass with its timing spans,
validation.stable ~276), ui/workspace/reveal_bar.py, background_previews.stored_pages / stored_page_path,
ai/tools/previews.py, ui/workspace/compare_rendered.py, preview_pages.py, background_renders.scan (Lookup.final).
Goal: each consumer uses render_lookup.select with the strict flag of the table. The slide list gets thumb.png
paths; keep the debug-log events thumbnails.for_outline, thumbnails.states (count the chooser's four results),
thumbnails.published; drop thumbnails.stable with ValidationPass.stable. AI tools and comparisons reuse stored
1920 px pages; the arbitrary-PDF page cache and raster fallback stay for other PDFs, scoped renders and higher
resolutions. Sweep planning uses the state-only form.
Delete: background_previews.stored_page / stored_page_path / stored_pages and preview_view._preload_page's own
lookup once nothing calls them; the stored_page parameter of preview_thumbnails.for_outline; Resolver.lookup if
the chooser's state-only form replaces it (one lookup, not two).
Essential test (1): the slide list shows a just-saved slide's thumbnail from the store. Adapt the existing
reveal-bar and AI tool tests to the chooser instead of adding new ones.
Run: tests/test_preview_thumbnails.py tests/test_reveal_bar_gui.py tests/test_compare_rendered_gui.py tests/test_preview_pages.py tests/test_background_renders.py and the AI tool tests that cover previews (list them).
```

### Step 2.6 — Delete the preview cache and image groups (*routine*, ~150k)

```text
Step 2.6. Read the design §5 (first paragraph) and §6 "Done when" (first bullet).
Delete: preview_cache.py, preview_equivalence.py (with its audit tables), preview_selection.py's histories
(remember_transient, legacy_reference if nothing uses it now, select_image), preview_requests.py's
image_group, cache_identity if unused, _ImageConsumer, remember_group_alias, cached_spec, selected_preview,
is_cached, and the render-results/ writer. Move anything still needed (say what) to render_evidence or
render_lookup. On first start, remove the local render-results/ cache folder (idempotent; keep page-images/).
Delete or rewrite their tests (tests/test_preview_cache.py, test_preview_equivalence.py,
test_preview_image_groups.py, test_preview_selection.py). Delete them; carry over a test only if it guards an
essential rule (rule 7) that no stage 1–2 test covers yet, and say which.
Run: the full suite.
Done when: grep finds no import of preview_cache or preview_equivalence; the full suite passes apart from the
Step 0 baseline failures.
```

### Step 2.R — Stage 2 review and timing run

- Reviewer task: "Review steps 2.1–2.6 against the design §3, §4, §6 stage 2 and §7. Look for: a consumer that
  still decides freshness itself, a selection branch that survived, PNG encoding or put before pixels, a
  foreground build a sweep can stop, a reader handed an unprotected path (other than thumb.png), lost §7
  behaviour (300 ms delay back, obsolete render not detached, edit/undo)."
- Orchestrator: fix round; full suite; then the §7 timing run with `tools/preview_bench.py` (same slide, edit and
  save scenarios, busy-render case). Fill the "Stages 1–3" column of §7 with measured values when stage 3 is done;
  for now record them in the progress table. Commit.

---

## Stage 3 — Bulk actions, references and snapshots

Design: §3 (the batch paragraph and the actions table), §4 (references and appendix), §5 (snapshots, v0.15.0),
§6 stage 3.

### Step 3.1 — One batch routine (*hard*, ~220k)

```text
Step 3.1. Read the design §3 from "Use one batch routine for compatible saved requests" to the end of §3.
Code: batch_render.py, preview_batch.py (render_batch), update_all_previews.py, deck_preview_refresh.py,
background_renders.BackgroundRenderer.render_batch (~878), their callers (ai/workspace.py,
ui/workspace/compile_actions.py, ui/workspace/chat/gui_workspace.py, preview_target.py).
Goal: one batch routine for compatible saved requests with single-render fallback (keeps force, foreground
priority, cancellation and per-request results; forced requests bypass failure backoff). Unsaved requests render
singly through the same service. Move the callers: "Render all previews now" (replaces Update previews: all decks
and views the sweep plans), "Rerender all" (current deck, selected or all views, forced), "Render all views"
(current slide, all views, captured editor text), the AI batch and deck tools (their requests and result contract
unchanged). Explicit actions bypass idle/battery gating, show progress and support Cancel; the sweep differs only
in planning, priority and gating. Then delete the duplicate orchestration. The menu label change (Update previews
-> Render all previews now) is user-visible: it is decided in the design, do it.
Essential tests (at most 2): a batch failure falls back to single renders; Cancel stops a bulk action. Keep
the existing AI tool tests as the check of their result shape. Merge or delete the tests of the removed
orchestration modules.
Run: tests/test_batch_render.py tests/test_preview_batch.py tests/test_update_all_previews.py tests/test_rerender_deck_gui.py tests/test_background_renders.py and the AI workspace tests (list them).
Done when: one module orchestrates batches; the others are gone or call it.
```

### Step 3.2 — References and appendix from the store (*routine*, ~150k)

```text
Step 3.2. Read the design §4 ("Reference eligibility ..." to "... raster fallback ...").
Code: ui/dialogs/add_slide.py, appendix_toc.py, deck_outline.py, preview_target.py, slide_preview.py — every
caller of slide_snapshot.snapshot_path / is_fresh / capture_deck for references.
Goal: the Add slide dialog and appendix generation use render_lookup's reference filter. Appendix images are
304x171, shrunk from the full-resolution last page into .build/appendix-thumbs/<template>/ (never enlarged from
the 168x95 thumbnail). Missing references give the existing box. Reference data is copied before a compile
starts, so eviction cannot affect it.
Essential test (1): the appendix uses the stored Instructor reference and falls back to the box without one.
Adapt the existing Add slide tests instead of adding new ones.
Run: tests/test_appendix_toc.py tests/test_preview_target.py and the add-slide dialog tests (list them).
```

### Step 3.3 — Flat snapshots removed, migration and notice (*routine*, ~150k)

```text
Step 3.3. Read the design §5 (second paragraph and "Accepted costs") and §9 (flat snapshots decision).
Code: slide_snapshot.py (publish_preview, capture_single_slide, capture_deck, snapshot_path, is_fresh,
preview_sequence; prepare_preview_images STAYS), preview_build.publish_preview, compiler.py, update_all_previews.py,
ai/workspace.py, compat.py (the registry of BREAKING entries; tests/test_compat.py enforces one per BREAKING
release), project metadata.
Goal: remove the flat snapshot writers and readers; delete .previews/slide_previews/ once per project (idempotent,
no PNG backup), recorded in project metadata; register the compat entry that shows the one-time notice (text:
the folder is gone, deletion syncs, update SlideMage on every computer; references rebuild from the local store).
Write the BREAKING: paragraph text into the report for the orchestrator (do not edit CHANGELOG.md).
Check the plugins: grep ~/github/slidemage-plugin-* for the removed names and list every hit.
Essential test (1): the first start deletes the folder and shows the notice; the second does neither. The
existing compat registry test covers the entry. Delete the flat-snapshot tests.
Run: tests/test_compat.py tests/test_compat_gui.py tests/test_deck_snapshot.py tests/test_slide_preview_cleanup.py tests/test_update_all_previews.py
```

### Step 3.R — Stage 3 review, full and plugin suites

- Reviewer task: as in 1.R and 2.R (including leftovers that should be gone), for steps 3.1–3.3 and the design §3, §4, §5.
- Orchestrator: fix round; full suite; plugin preview suites (`slidemage-plugin-claude` at least; command in the
  test memory note: `SLIDEMAGE_TESTS=<worktree>/tests PYTHONPATH=<worktree>/src:. ...`), baseline each against
  `develop` first; Ruff; the §7 timing run again, now filling the "Stages 1–3" column with measured values.
  Commit; push the branch to the fork.

### G1 — dropped (user, 2026-11-09)

The user tests once, at Step R, after 4.S; G1's checks are part of that test. Stage 4 starts right after 3.S. The
branch is still pushed to the fork after 3.R, so an early test is possible but not waited for. A problem found at
Step R is narrowed down by switching off A (its setting) and B, C, D (their constants).

---

## Stage 4 — Fast lane for the focused slide

Design: §8, §6 stage 4, §10 (rows on A and B). Each change can be switched off alone (§6), but only A gets a
user-visible setting, because its ~230 MB matter on small machines (§10). B, C and D are switched by one
module-level constant each, in one place, which the timing run and the tests flip with `monkeypatch`; they add
no settings UI. A, B, C and D are on by default. If a step finds a user needs to switch B, C or D, it lists it
under "Needs a decision".

### Step 4.1 — B: direct `lualatex` with latexmk fallback (*hard*, ~180k)

```text
Step 4.1. Read the design §8 (the table of measurements, the paragraph on working folder and TEXINPUTS, row B)
and §10 (rows "Direct or pre-started lualatex ..." and "Direct lualatex misses a needed rerun").
Code: preview_build.py (compile_cached, run_preview, preview_latexmkrc, the -g rerun), compiler.py
(build_env, run_streamed), the preview .latexmkrc.
Goal: for a warm edit, run one lualatex pass directly with latexmk's own command line, working folder (the project
root) and TEXINPUTS; fall back to latexmk when the .aux, .nav, .toc or .bbl changed or the log asks for a rerun,
and for every cold build. Behind its switch (a module constant, on).
Essential tests (at most 2): one LaTeX test (next to tests/test_preview_views_latex.py) that the direct PDF's
pages are pixel-identical to latexmk's for one example slide with a citation, a picture from media/ and an
alt-text "Image source(s)" line; one test that a changed .aux falls back to latexmk.
Report tools/preview_bench.py's edit median before and after.
```

### Step 4.2 — A: pre-started TeX (*hard*, ~220k)

```text
Step 4.2. Read the design §8 row A in full and §10 (rows on the pre-started TeX, its stdin on Windows, its
memory).
Code: step 4.1's direct path, compiler.py (helpers give stdin=DEVNULL since v0.14.46; the spare needs its own
Popen with stdin=PIPE), ui/workspace/window.py (focus), the format rebuild.
Goal: one spare lualatex per focused slide's build folder (format, view, jobname, output folder fixed at start),
started in latexmk's working folder with its TEXINPUTS, waiting on stdin
(\directlua{token.set_macro("smnext", io.read("l"))}\input{\smnext}). A render hands it the wrapper's name; it is
used once; a new spare starts right after. Discard it when the format is rebuilt, the preamble, view, language or
deck changes, the window loses focus, or after 10 minutes idle. The publication guard's start time is the spare's
start. Any start or write failure falls back to B. Behind its user setting (on by default; the only stage 4 setting).
Essential tests (at most 2): extend 4.1's pixel test to A (parametrized: the rule is "the same for A and B");
a spare is used once and a preamble change discards it. Windows (its own stdin pipe, wrapper name received)
is part of the user gate in Step R.
Report tools/preview_bench.py's edit median and the spare's memory.
```

### Step 4.3 — C: render on a typing pause (*routine*, ~100k)

```text
Step 4.3. Read the design §8 row C.
Code: the editor's autosave and live-preview timers (ui/workspace/source_file.py, the 1.5 s autosave), the
lint check, §7's obsolete-render cancellation.
Goal: with live preview on, render the editor text 0.4 s (one constant) after the last keystroke; autosave then
finds a store hit through the canonical text hash. Off when live preview is off; respects the battery setting.
Behind its switch (a module constant, on).
Essential test (1): a typing pause renders once, and the autosave that follows is a store hit.
```

### Step 4.4 — D: other views in the background (*routine*, ~100k)

```text
Step 4.4. Read the design §8 row D.
Code: render_scheduler priorities, background_renders (low-priority jobs), the Preview's focused render.
Goal: after the focused render, render the focused slide's other views at low priority; the next edit cancels
them. Behind its switch (a module constant, on).
Essential test (1): after the focused render a view switch is a store hit, and an edit cancels the queued
views.
```

### Step 4.R — Stage 4 review and timing run

- Reviewer task: as before, for 4.1–4.4 and §8, §10. Focus: stale state in the spare, fallbacks that do not fall
  back, a working folder or TEXINPUTS that differs from latexmk's, settings that do not switch the change off.
- Orchestrator: fix round; full suite; plugin suites; the §7 timing run with each switch on and off; fill the
  "With stage 4" column with measured values. Commit; push to the fork.

---

## Step R — Release v0.15.0 and the PR

**Who:** orchestrator.

1. Fetch `origin/develop`; merge it into the branch; check `VERSION_NUMBER` there and take the next version
   (v0.15.0 unless `develop` has moved past it).
2. `CHANGELOG.md` and `version.py`: one entry with the §7 speed-ups, the store consolidation, the fast lane, and
   the `BREAKING:` paragraph from Step 3.3. Run the version/release tests and the compat test.
3. Update the design: status line "implemented", §7 checklist ticked, measured columns filled; this file's
   progress table complete. Update issue #112 to match (ask before the edit if auto mode blocks it).
4. Full suite, plugin suites, Ruff. Push to the fork.
5. **USER GATE:** the user tests the branch.
   - Windows: open a slide's PDF and keep it open while the slide re-renders (replacement must not fail); a slide
     with CRLF line endings renders once (Preview and sweep share the result); the spare's stdin and wrapper name.
   - Real project: "Render all previews now", "Rerender all" and a full sweep finish; a new picture in `media/` and
     a new deck PDF leave other results current; the slide list and the Preview agree right after a save; the
     first start shows the notice once and removes `.previews/slide_previews/`.
   - A problem found here: switch off A, B, C and D to tell stages 1–3 from stage 4; findings become fix tasks.
6. After the user's go: open the PR from `JuergenFleiss/SlideMage` to `SlideMage/SlideMage` `develop`, with the
   design's "Why" section and the §7 gains table (all columns measured) in the description; link #112.

## Size and cost

Implementer estimates above add up to about 3.3M tokens across 21 tasks, plus about 0.6M for reviews and fix rounds and about 0.4M for the four simplify passes.
Codex runs do not count against the Claude 5-hour window; the orchestrator's own reading and checking is
roughly 30–60k per step. Stages fit separate sessions: the progress table and the commits carry the state.

Orchestrator share of the 5-hour window (estimate of 2026-11-09, at the measured ~5% per 100k tokens of
2026-10-10; that rate was measured with Sonnet, so re-measure after Step 1.1):

| Part | Checkpoints | Orchestrator tokens | 5-hour window |
| --- | ---: | ---: | ---: |
| Step 0 | 2 | ~60k | ~3% |
| Stage 1 (1.1–1.7, 1.R, 1.S) | 9 | ~400k | ~20% |
| Stage 2 (2.1–2.6, 2.R with timing run, 2.S) | 8 | ~450k | ~22% |
| Stage 3 (3.1–3.3, 3.R with plugin suites, 3.S) | 6 | ~260k | ~13% |
| Stage 4 (4.1–4.4, 4.R with timing run, 4.S) | 6 | ~270k | ~13% |
| Step R | 1 | ~60k | ~3% |
| Margin for extra fix rounds (agents overshot most estimates in October) | | ~300k | ~15% |
| **Total** | 32 | **~1.8M** | **~90%, about one full window** |

Run one session per stage, which costs about 15–25% of the window each. In one long session the growing context
makes each later step dearer. If Claude subagents replace Codex as implementers, add about 4.3M tokens (~215%,
two to three more windows).
