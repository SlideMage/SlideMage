# Code review fix plan

Status: draft, 2026-10-11. Based on the full-codebase review by Claude (structure, redundancies, the
slide/deck/translation/version model, code economy), with the additional findings of an adversarial
check by Codex (task `task-mv3u1eog-q0n2ud`) folded in. Where Codex objected to a recommendation, its
objection is kept as a caveat on that step. Each step needs the user's go before it starts; pause after
each committed step.

Order: phase A fixes wrong behavior; phases B-D follow the review's sections (redundancies, the slide
model, structure). Within a phase the order is a suggestion.

Cost figures are rough, from the usage calibration of ~5% of a 5-hour window per ~100k agent tokens.

## Phase A: wrong behavior

| Step | Finding and fix | Source | Cost |
| --- | --- | --- | --- |
| A1 Instructor only | `\omitslide` is typeset in every view (the LaTeX skips it only after `\studentversion`, which nothing calls), yet the *Call as* menu offers it as **"Instructor only"** and `SlideCall.included_in` and the transcript treat it that way: slides marked instructor-only reach students. Four visibility rules exist (`deck_editor:118`, `transcript:411`, `appendix_toc:63`, `latex_lint:577`). Fix: one rule in `deck_editor`, used by all four, and the LaTeX made to match it (decision below). Includes `\conditionalslide[]{id}` (empty list): "all views" in UI and transcript, "none" in LaTeX. A test checks every macro × view. A changed LaTeX meaning is a `compat.py` entry and a BREAKING release. | Claude; empty list: Codex | ~60-100k, 3-5% |
| A2 Transcripts | `transcript.py` parses decks with its own regex and skips `deck_language`: a DE transcript describes the English originals, and an explicitly called partner (`tks` in the manual) appears twice. It also counts calls inside `\iffalse…\fi` and verbatim. Fix: transcripts use `parse_slide_calls` on masked text, `deck_language` and the A1 rule. *Codex caveat:* `deck_language`'s fragment expansion handles only `\input`; it must learn `\include` first, which the transcript supports today. | Claude; masking: Codex | ~100-150k, 5-8% |
| A3 Unused-content archiving | No slide-call regex accepts legal TeX such as `\slide {id}` or a line break before the argument, so `unused_content` offers that slide for archiving and the slide list does not show it. Fixed together with B1 (one parser that tolerates whitespace); this step adds the regression tests and does B1's parser part first if B1 is not yet done. | Codex | ~20-40k, 1-2% |
| A4 Image side panel | The panel saves all three fields from its form, overwriting values written meanwhile (`panels/images.py:157`, `alt_images.py:789`); save only changed fields, as the Images page does (`image_review`). A redraft result is matched by image reference only and can land on another slide showing the same image; key it by slide and image. Also the review's point: the two `ImageForm`s keep separate save logic, so the panel should reuse the page's. | Codex; two forms: Claude | ~40-60k, 2-3% |
| A5 Version marker | `parse_version` reads a commented-out `\setSlideVersion`; `strip_marker` removes only the first marker; a save then freezes and bumps from the wrong version. | Codex | ~15-25k, 1% |
| A6 New projects | An empty new project has no slide template: adding a standard slide raises `FileNotFoundError`. Creating a project from a source checkout copies `_slidemage_preview-*.tex` wrappers along. | Codex | ~20-30k, 1-2% |
| A7 Biber failure | A compile with a failed biber run reports success, with citation keys in the PDF; deck snapshots already detect this (`deck_snapshot:495`). Log a warning on such a compile. | Codex | ~10-20k, 1% |
| A8 Page compiles | Partial compiles probably cannot match slides that come from `\input` fragments (`partial_compile:194`). Reproduce first; if confirmed, use the whole-deck expansion. | Codex | ~30-60k, 2-3% |

**Decision for A1 (2026-10-11): option 1, make "Instructor only" true in LaTeX.**

- **(Chosen) Make it true in LaTeX.** `\omitslide` / `\omitslideversion` are skipped in during-course
  and after-course compiles, frame number still counted. The menu tells the truth, and slides already
  marked this way stop reaching students. Breaking for a deck relying on today's behavior. *Codex caveat:*
  do not do it by calling `\studentversion` in the wrappers; that also switches beamer to handout mode.
- **Make the UI match today's LaTeX.** The label becomes "Marked as omitted"; hiding uses
  `\conditionalslide[instructor]`. Pinned versions then have no instructor-only form.

## Phase B: redundancies

| Step | What it does | Cost |
| --- | --- | --- |
| B1 One LaTeX parsing layer | One public module for comment/`\iffalse`/verbatim masking and slide-call parsing, out of `latex_lint`'s and `alt_blocks`' private helpers (49 private cross-module accesses in 18 files). The four slide-call regexes (`deck_editor`, `deck_headers`, `transcript`, `unused_content`) and the four `COMMENT_RE`s go. | ~80-120k, 4-6% |
| B2 Compile status | The app's status lines (`==== Compiling/PASS/MOVING…`) are written by `compiler`, `deck_snapshot`, `slide_preview` and parsed back by `compile_status` and `compile_progress` with duplicated regexes. Replace with structured events passed to a callback, rendered to log text in one place. *Codex caveat:* TeX's own output (passes, slide files read) still has to be parsed for progress. | ~70-100k, 4-5% |
| B3 One latexmk runner | Five call sites (`compiler`, `partial_compile`, `slide_preview`, `preview_build`, `deck_snapshot`) build their own command, environment and process options. One runner for env, Windows flags, cancellation and log capture; each caller keeps its own options and success checks. *Codex caveat:* the pass limits, rerun checks and bibliography checks differ on purpose. | ~60-90k, 3-5% |
| B4 Copy-pasted helpers | `CREATE_NO_WINDOW` set up in 11 files; `_is_git_repo`/`_is_git_tracked` (`archive`, `slide_rename`); `bare_id` ×2; `_slide_id_of` + regex ×2; `compiler._build_env` used privately by 3 other modules; the JSON store load/save (×4+) and atomic writes (×3). *Codex caveat:* the stores' validation rules differ; unify the mechanics, not the policies. | ~50-70k, 2-4% |
| B5 Dead code | The unreferenced-function candidates (11 by Codex's count, including `alt_draft.bake_off`/`write_bake_off`, `deck_language.partner_for`, `slide_rename.set_slide_languages_bulk`), each checked for string or dynamic use before removal. | ~15-25k, 1% |

## Phase C: slides, decks, translations and versions

| Step | What it does | Cost |
| --- | --- | --- |
| C1 Slide file grammar | The file name is the schema (`<id>-<LANG>-<slug>-current.tex`, `-vX-Y-Z.tex`) but no module owns it: `-current.tex` is hard-coded in 36 files, frozen names are assembled in 8 places, and two frozen-file regexes disagree (`deck_editor:77` any number of parts, `slide_versioning:176` exactly three). A `SlideFile` value type (id, language, slug, version) with parse and format, used everywhere; `SlideCall.source_filename` delegates to it. *Codex caveat:* public helpers in `slide_language`/`slide_versioning` might be enough; choose when implementing. | ~80-120k, 4-6% |
| C2 Shared constants | The three views live in `transcript.py` and are imported from there by UI state and `preview_target`, and are redefined in 4 more files; move them to `deck_editor`. A `TRANSLATION_LANGUAGES = ("EN", "DE")` beside `LANGUAGES` replaces the literal pairs. *Codex caveat:* `LANGUAGES` includes `mult`, which translation switching must exclude. | ~25-40k, 1-2% |
| C3 Translation links | Links are stored on both sides as header comments that can disagree, which forces the reverse index and conflict handling in `deck_language._Links` and a repair action in Housekeeping; `slide_language.translation_link` and `deck_language._Links.find` read them by different rules. Make one direction authoritative (`%% Translation of:` in the translation) and derive the other, with one reader. *Codex caveat:* keep the links in the slide files (portable, merge-friendly) rather than a central table. | ~80-120k, 4-6% |
| C4 Translation versions | A new translation inherits the original's `\setSlideVersion` (`tks` got 1-1-0); start it at 1.0.0. A pinned `\slideversion` becomes the partner's *current* file when the language switches; *Codex caveat:* this is the documented contract (`compat.py:84-94`), so the step only makes the slide list show it ("pinned in EN, current in DE") instead of changing it. | ~30-50k, 2% |
| C5 Partner folding | Explicit partner calls in old decks are folded into the original's slot on every read. Offer a one-off Housekeeping action that removes such calls from the deck, after which the folding code can be simplified. *Codex caveat:* `compat.py` promises no automatic migration, so it must stay an explicit user action. | ~40-60k, 2-3% |
| C6 "Included in decks" headers | Generated data in source files: deck edits rewrite slide headers (git noise, `StaleFileError` races), and they go stale (a preview wrapper's name in `1f8`'s header). `deck_headers` also imports in its loop and parses each deck twice. Compute membership on demand for the app and stop writing the headers, or, if the headers should stay for reading slide files outside the app, write them only on an explicit action. *Codex caveat:* the headers are useful outside the app; decide which. | ~40-70k, 2-4% |
| C7 "Version" in the code | One word for three things: deck view (`job.version`), slide version (`call.version`), app version. The UI already says "view"; rename the deck-version fields in Python. The LaTeX macro names stay. | ~40-60k, 2-3% |

## Phase D: structure and economy

| Step | What it does | Cost |
| --- | --- | --- |
| D1 Project paths | `deck_scan.PROJECT_ROOT` is fixed at import and 27 module-level paths derive from it (`SLIDES_DIR` alone 8 times), so switching projects restarts the app and tests patch paths in 50 files. Replace with an immutable per-project paths object passed in. *Codex caveat:* not a mutable "current project" singleton, which would let background jobs cross projects. Large; can go module by module. | ~150-250k, 8-12% |
| D2 Subpackages | The flat folder of 71 modules is grouped by its prefixes: `project/`, `slides/`, `decks/`, `compile/`, `preview/`, `images/`, `transcript/`. Best after B1-B3 and D1, when the dependencies are cleaner. | ~80-120k, 4-6% |
| D3 Release history | `version.py` is 2,035 lines, ~1,950 of them history in a docstring parsed at runtime, and runs git at import. Move the history into a packaged `CHANGELOG.md`, read by the About sheet and `packaging/release_notes.py`; git runs on first use. | ~30-50k, 2% |
| D4 Misplaced files | The slide template moves out of `example/.scripts/R_Slidemaster/inst/templates/` to `latex/` (project copy still wins). `palette.py` moves to `ui/kit/` (used by `ui/kit/theme.py` and `ui/dialogs/about.py`) and loses its stale Tk-migration text. Preview wrappers move out of the user's `decks/` folder into `.build/`. | ~40-60k, 2-3% |
| D5 docs/ and tests | Plans and reviews to `docs/plans/`, benchmark JSON (~75k lines) to `docs/benchmarks/`; remove the 25 references to the missing `LANGUAGE_NOTES.md` / `ALT_TEXT_NOTES.md` (one is in an error message). Tests that write use a temporary copy of `example/`, so the demo project stays clean. | ~30-50k, 2% |
| D6 Lint and comments | Enable ruff `F401`, `F811`, `F841`, then `B` (28 findings, each checked by hand). Dated history in comments ("2026-09-27, direct instruction", 187 dates outside `version.py`) is shortened where git holds it. *Codex caveat:* keep the comments that explain TeX constraints. | ~40-70k, 2-4% |
| D7 Window mixins | `WorkspaceWindow` combines three mixins that rely on window attributes; give them a typed host protocol. Low priority. | ~20-30k, 1% |

## Corrections to the first review

- The claimed disagreement for `\conditionalslide` **without** a list was wrong (all rules agree); the real
  one is the empty list, now in A1.
- The slide list dims and labels omitted slides rather than hiding them.
- Counts corrected above: 71 backend modules (not 75), 7 `preview_*` modules, `_build_env` used by 3
  other modules, 27 root-derived paths, 50 test files patching paths.

## Progress

| Step | Status |
| --- | --- |
| A5 Version marker | Done, v7.0.2: implemented by Codex (gpt-6.1-sol, xhigh), reviewed by Claude. |
| A1a Instructor only (LaTeX) | Done, v8.0.0 (BREAKING): implemented by Codex, reviewed by Claude; manual slides 1u4/1d7 corrected. |
| A1b One visibility rule | Done, v8.0.1: implemented by Codex, reviewed by Claude. |
| A3 Whitespace in slide calls | Done, v8.0.2: implemented by Codex, reviewed by Claude. |
| A2a \include fragments | Done, v8.0.3: implemented by Codex, reviewed by Claude. |
| A2a/A2b Transcripts via the deck parser | Done, v8.0.3 / v8.0.4: implemented by Codex (A2b sent back once), reviewed by Claude. |
| A4 Image side panel | Done, v8.0.5: implemented by Codex, reviewed by Claude. |
