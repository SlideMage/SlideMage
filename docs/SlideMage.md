# SlideMage

A PySide6 (Qt) GUI for compiling and archiving this project's `decks/`
(originally a Tkinter GUI, built 2026-07-19, before the full migration --
see `PYSIDE6_MIGRATION.md`). This file is the "what and why" for future
sessions working on this code -- the module docstrings cover the "how" at
the code level.

> How the app itself is built, module by module. The app lives in
> `src/slidemage/` of this repository, next to the LaTeX framework it
> drives (`latex/`) and a demo project (`example/`); see
> [PROJECT_OVERVIEW.md](PROJECT_OVERVIEW.md) for the layout. Before v4.0.0
> this repository was only the app folder, exported by `git subtree` from
> a larger private project; its history continues here.

## What it does

Launch with `slidemage` (after `pip install -e .` from the repo root), or
build a stand-alone executable with `pip install -e ".[build]"` then
`pyinstaller packaging/slidemage.spec` from the repo root -- lands at
`dist/SlideMage` (`dist/SlideMage.exe` on Windows). PyInstaller never
cross-compiles: run it on the OS you want the executable for. Pushing a
`v*` tag builds both platforms via `.github/workflows/release.yml` and
attaches them to a GitHub Release instead, no local build needed. The tag
must equal `VERSION_NUMBER` in `src/slidemage/version.py` (e.g. `v3.31.0`),
or the workflow stops -- the update check below compares the two.

On Linux, `SlideMage-linux.zip` also bundles `icon.svg` and
`slidemage.desktop.template` next to the binary -- unzip the release to
one folder and see that template's own header for the one-line `sed`
command that turns it into a real GNOME/KDE app-grid entry (PyInstaller
doesn't embed an icon into a Linux binary the way it does on
Windows/macOS, so a desktop entry needs its own icon file alongside it).

It opens the project given by `--project`,
`$SLIDEMASTER_PROJECT`, the nearest folder above the current directory
that holds `slide_ids.csv`, or the last project opened, else it asks.
Three permanent tabs:
**Active decks**, **Archived decks** and **Images** (the
green one -- see "Images tab" below). The two deck tabs are
each a table: one row per deck, checkboxes for `Instructor` /
`During-course` / `After-course` (each an independent *whole-deck* compile
of that version) plus `After-course, per chapter` (independent of the
other three -- always the after-course version, split into one PDF per
`\section{}` chapter, since that's what students get for post-course
review), a `Create PDF` button, and (Active tab only) `Archive`,
`Edit`, and `Duplicate` buttons per row -- `Edit` opens that deck's own
`.tex` straight into a source-editor tab (the same one a slide's own
source uses), `Duplicate` asks for a name and copies the deck's `.tex`
file under it (`deck_duplicate.py`; no content rewriting needed, since a
deck's name is just its filename stem, never embedded in the file
itself). Both replaced a `Quick compile` button (2026-08-16, direct
instruction) that ignored a row's own checkboxes entirely and always
compiled the instructor version -- `Create PDF` with just that
checkbox ticked already covered the same need. Any combination of the
four checkboxes can be ticked at
once. A status dot next to each checkbox tracks its job through four
states as a batch runs: animated blue dots while actively compiling, a
static orange arrow while the PDF itself has compiled fine and it's now
trying to relocate it into `pdf/` in the background (see
`_relocate_pdf_and_finish()` below -- this no longer blocks anything else
in the app, including the next queued job), green on success, or red on
failure -- for `After-course, per chapter`, that one shared dot reflects
the whole set of per-chapter jobs, and a fail is sticky (a later chapter
starting/moving/passing won't paint over an earlier one's failure). A
status bar above the log pane shows which
specific job is running right now -- `Compiling <deck>: Compile 2/4 in
progress...` for whole-deck jobs (counted against the whole batch's
whole-deck job total) or `Compiling <deck>: Chapter 5/12 in progress...`
for per-chapter jobs (counted against that one deck's own chapter total,
since batch-wide chapter position wouldn't mean anything); it also reflects
the "moving" wording during a PDF relocation retry, and shows the final
`Done: N passed, M failed` line once the whole batch finishes. A toolbar
above that has `Empty pdf/ folder`, `Empty .build/ folder`, and `Archive
unused content` buttons (each asks for confirmation first; the first two
for clearing out generated output, `.build/` refused mid-compile;
`Archive unused content` refused mid-compile too, since a running compile
could still need a file it would move -- see `unused_content.py` below for
what it actually scans). A shared log pane at the bottom streams live
`latexmk` output; compiles run on a background thread so the GUI stays
responsive, one job at a time, and one job failing doesn't stop the rest.
Archiving a deck (see below) also asks for confirmation before moving
anything.

It replaces things that were previously manual: hand-editing the `DECKS=`
line in `compile-all.bat`/`compile-all-versions.bat`, hand-crafting a
one-off wrapper file to get a per-chapter PDF during PPTX conversion
review, and manually eyeballing `media/`/`slides/` for files nothing
references anymore. It also adds two things that didn't exist before at
all: archiving a finished course's deck out of `decks/` while keeping it
compilable, and archiving unreferenced `media/`/`slides/` files out of the
way without deleting them.

## Updates

**Info → Check for updates…** compares this copy's version with the
latest release of `stpalan/SlideMage` on GitHub. When a newer one
exists, the packaged app offers to download that platform's release zip,
unpacks it into the folder the running app lives in, and restarts. The
old binary is kept as `SlideMage.old` (`SlideMage.exe.old` on Windows)
until the next start deletes it. A copy running from source only reports
the new version -- update it with `git pull`.

### Access token for a private repository

While the repository is private, GitHub only shows its releases to a
logged-in account, so the check needs a GitHub token. Without one, the
check reports that no release was found.

1. **Create the token.** On GitHub: Settings → Developer settings →
   Personal access tokens → Fine-grained tokens → Generate new token
   (https://github.com/settings/personal-access-tokens/new). Set an
   expiry date, Repository access → Only select repositories →
   `stpalan/SlideMage`, and Repository permissions → Contents →
   Read-only; leave everything else at No access. Copy the token
   (`github_pat_…`) -- GitHub shows it only once. When it expires, the
   update check reports that no release was found until a new one is
   saved.
2. **Add it in SlideMage.** System → Preferences… → General → Updates:
   paste the token into "GitHub token" and press Enter. It's saved for
   your user account only -- in `~/.config/slidemage/github_token`
   (readable only by you) or `%APPDATA%\SlideMage\github_token` -- never
   in the project folder, which may be synced or shared. Clearing the
   field removes it.

   Alternatively, set the environment variable `SLIDEMAGE_GITHUB_TOKEN`,
   which takes precedence over the saved token:
   - Linux -- a desktop launcher doesn't read `~/.bashrc`, so use the
     session environment, then log out and back in:
     ```bash
     mkdir -p ~/.config/environment.d
     echo 'SLIDEMAGE_GITHUB_TOKEN=ghp_yourtoken' > ~/.config/environment.d/slidemage.conf
     chmod 600 ~/.config/environment.d/slidemage.conf
     ```
     When SlideMage is only ever started from a terminal,
     `export SLIDEMAGE_GITHUB_TOKEN=ghp_yourtoken` in `~/.bashrc` is enough.
   - Windows -- in PowerShell, then restart SlideMage:
     ```powershell
     setx SLIDEMAGE_GITHUB_TOKEN "ghp_yourtoken"
     ```
     or Settings → System → About → Advanced system settings →
     Environment Variables → User variables → New.
3. **Check it.** Info → Check for updates….

Every user needs their own token with read access to the repository, which
doesn't scale beyond its collaborators. To hand SlideMage to anyone else,
publish the releases from a public repository (it can hold nothing but the
release zips) and point `REPO` in `src/slidemage/updater.py` at it, or make
this repository public -- then no token is needed.

## Images tab

The third permanent tab, added 2026-08-14 (labelled "Image descriptions"
until 2026-08-15, renamed once slide-level summaries -- unrelated to any
one image -- also landed on it). It is where every image in the
project gets described for screen-reader users, and where per-deck accessible
transcripts are generated. The design, the decisions and the measured
findings are in `ALT_TEXT_NOTES.md` (not part of this copy); the
user-facing workflow is in the main README's "Describing images" section.
What matters when touching *this code*:

- **The tab is built at startup but its first scan is deferred** until it is
  actually opened (`qt_gui.py`'s `_on_tab_changed` -> `ensure_loaded()`).
  That scan walks every slide, hashes the bytes of every image they
  reference, and *writes* new rows to `media/alt-text.json` -- none of which
  belongs in the startup path of an app usually opened to compile a deck.
- **Drafting and batch runs happen on a `threading.Thread(daemon=True)`** and
  come back over a `Signal`, the same pattern `qt_slide_source_tab.py` uses
  for its render button. One image takes 10-60s; a full batch takes hours.
- **Drafts are written to the shared store per image as they finish**, not
  buffered to the end, and the batch queue is *derived* from the store and
  the slide files rather than kept anywhere of its own -- which is what
  makes it resumable across sessions with no job state to corrupt.
- **A running batch must not overwrite an image the user reviewed mid-run,
  and two writers (the batch thread, the GUI thread's own saves) must not
  interleave and lose each other's change to the one shared JSON file.**
  `alt_images.update_store()` closes both: it holds a process-wide lock for
  the whole load-check-save round trip, and the "is this still safe to
  write" check re-reads the store fresh rather than trusting whatever the
  batch queue looked like when it started. Getting the file-scoped version
  of this wrong once already caused a save to land in the wrong slide's
  file; see ALT_TEXT_NOTES.md.
- **Modal dialogs block forever under `QT_QPA_PLATFORM=offscreen`**, with no
  one to click them. Any GUI test here must stub `QMessageBox` and run
  Python with `-u`; the first attempt hung silently with no output at all.
- **This tab is only for image descriptions -- a slide's transcript
  *summary* and its compile-time *preview* are edited elsewhere**
  (`qt_slide_source_tab.py`), deliberately: this tab's own slide list only
  shows slides that reference at least one image (the whole point of the
  list), and both of those features need to work for *any* slide. They
  still share this tab's underlying store and lock (`alt_images.py`,
  `slide_snapshot.py`) -- see those modules' own entries in the module map
  below.
- **A hand-drawn tikz illustration (`\tikzillustration{ID}`,
  Slidemaster_preamble_base.tex) shows up in this same per-slide list as a
  synthetic `tikz:ID` reference (2026-09-07)** -- see ALT_TEXT_NOTES.md's
  own "Phase 9" section for the full design. It has no file on disk at
  all, so this tab's own preview panel and the drafting pipeline's image
  resolution are the only two places with a tikz-specific branch
  (`tikz_render.py`, below); every other piece of this tab (role radios,
  short/long/takeaway/source fields, Draft/Tune prompt) is built generically
  from `(reference, ImageEntry)` and needed no changes at all.

## Module map

- [`alt_images.py`](../src/slidemage/alt_images.py) -- reads/writes `media/alt-text.json`,
  the single store for everything about an image: role, confirmation
  status, short/long description, a source citation, a default takeaway,
  and per-slide state (`used_on`: which slides reference it, each with
  its own takeaway override and reviewed stamp). `source` (2026-08-16) is
  independent of `role` -- a decorative Midjourney illustration still
  needs attribution even though it carries no alt text, confirmed against
  a real slide (`dh6-Private-Equity-Categorization`) that already
  hand-authors exactly that combination; step 1 of a planned feature to
  auto-pull it into a compiled slide's own footnote, prefixed "Image
  source(s):" -- see ALT_TEXT_NOTES.md for the full plan and why the
  schema/UI landed before the compile-time half. Replaced two former
  stores 2026-08-14 --
  `alt_manifest.py`'s CSV (role/status/short only) and a `%%ALT` comment
  block `alt_blocks.py` used to read/write at the bottom of every slide
  file (long/takeaway/review state) -- once JSON removed the CSV cell-size
  reason for the split. `sync_store()` only ever *adds* rows/references,
  never rewrites or deletes one, so authored alt text cannot be lost by
  renaming an image; vanished images are reported instead. Role is guessed
  for new rows by directory first (everything in `scheme_*` is
  institutional branding) then filename prefix, defaulting to
  *informative* -- an undescribed informative image is a visible gap, while
  one wrongly marked decorative silently disappears from both the PDF and
  the transcript. A tikz illustration (2026-09-07, ALT_TEXT_NOTES.md's
  "Phase 9") gets a row the same way, discovered from the same
  `alt_blocks.scan_slides_raw()` pass `sync_store()` already runs rather
  than a second walk over every slide file, keyed `"tikz:ID"`
  (`ImageEntry.is_tikz`) instead of a real path, defaulting to
  *informative* unconditionally (no directory/prefix to guess from). No new
  `kind` field or `FORMAT_VERSION` bump needed for this: the prefix is
  already a stable, self-describing key, and every existing on-disk row
  (all real paths) reads as `is_tikz == False` for free.
  `content_hash()` (an image's own bytes) and
  `slide_context_hash()` (one slide's own text) are the two staleness
  inputs -- deliberately separate, since an image's description goes stale
  when the *picture* changes, not when some slide showing it does.
  Also holds `SlideNotes` (2026-08-15): a slide's free-text transcript
  *summary*, unrelated to any one image, in the same file's top-level
  `"slides"` section rather than inside any `ImageEntry` -- `save_store()`
  and `_save_slide_notes()` each read-preserve the other's section before
  writing, so an image save can never silently wipe out a summary and vice
  versa (both go through the same `_store_lock`). Edited from the
  slide-source editor tab, not the Images tab -- a summary makes sense for
  a slide with no images at all, which the Images tab's list never shows.
- [`alt_blocks.py`](../src/slidemage/alt_blocks.py) -- slide-scanning utilities shared by the
  rest of the accessibility system: which images a slide references
  (`referenced_images()`), its id/title (`_slide_title()`), and the
  `braced_argument()`/`extract_macro_calls()` brace matcher -- a non-greedy
  `\{(.*?)\}` stops at the wrong brace whenever an argument contains a
  braced macro, which 70 slide files' frame titles do. No longer owns any
  review state (that's all `alt_images.py` now) -- just "what does this
  slide reference and what is it called." `referenced_images()` only
  matched literal `\includegraphics{...}` until 2026-08-16 -- it missed
  `\chapterlogo{...}` and `\begin{sideimageframe}{title}{path}`, whose own
  arguments are real literal paths even though the `\includegraphics{...}`
  they *internally* feed (`\gothamChapterLogoPath`, `#3`) is itself
  macro-valued and correctly stays skipped. Measured impact, not assumed:
  105 of 281 images had an empty `used_on` before the fix, 121 new
  (image, slide) uses turned up on the very next `sync_store()` after it.
  `TIKZ_PREFIX`/`referenced_tikz_illustrations()`/`find_tikz_illustration()`
  (2026-09-07) extend the same "what does this slide reference" job to
  `\tikzillustration{ID}` calls (`Slidemaster_preamble_base.tex`) --
  defined here rather than in `alt_images.py` since this is the lower
  module in the import order (`alt_images.py` already imports
  `alt_blocks`, not the reverse), so both share the one `"tikz:"` literal.
  Body extraction is a plain literal search for the environment's own
  `\end{tikzillustration}`, not `braced_argument()`'s brace-matching -- a
  tikz body is full of braces that don't pair up the way one `{...}`
  argument's do. `TIKZILLUSTRATION_RE`'s options group became *capturing*
  (2026-09-14, found rendering real illustrations rather than just
  compiling them embedded in their own slide) -- it was matched only to
  find where the ID begins, options themselves silently discarded, which
  degraded a *built-in* tikz hook set there with no error but hard-failed
  ("I do not know the key '/tikz/box'") the moment the body referenced a
  *custom* style the options themselves defined. `referenced_tikz_illustrations()`
  now returns `(id, options, body)` triples and `find_tikz_illustration()`
  `(path, options, body)` accordingly.
- [`alt_draft.py`](../src/slidemage/alt_draft.py) -- vision-model drafting, plus (2026-08-25)
  English-to-German translation of drafted text. Slide-context extraction
  (tikz layout stripped, `\note{}` excluded so instructor notes can never
  reach a student), the prompt, a pluggable `DraftBackend`, an Ollama
  backend, the batch runner, and the bake-off harness. stdlib only.
  Two safeguards worth not removing: `think` is never sent as an explicit
  `false` (it makes qwen3-vl return its answer in the `thinking` field and
  an empty `content`), and `detect_value_ramp()` strips tables whose numbers
  rise in near-equal steps, which is what fabricated chart values look like.
  `OllamaTranslationBackend.translate()` sends three separate plain
  "translate this text" calls (short/long/takeaway), not one combined
  structured-JSON call -- the combined approach, tried first, came back as
  three empty strings on a same-settings retry against `sun_leaf/HY-MT:7b`,
  a dedicated MT model (Ollama `capabilities=["completion"]` only, no
  `"tools"`) that doesn't reliably follow multi-field JSON-output
  instructions the way a general instruction-tuned model does; confirmed
  directly against real content (including Markdown-table preservation),
  not assumed from the model card. Each call's exact prompt text and
  blank-line spacing before the source text comes from
  [`translation_prompts.get_effective_prompt()`](../src/slidemage/translation_prompts.py),
  not a hardcoded string -- see that module. `list_all_models()` (every
  installed Ollama model, not just vision-capable ones -- translation is
  text-only) backs the Images tab's own "Translation model:" picker.
  `images_needing_translation()` checks `entry.short or entry.long` (real
  text present), not `entry.has_content` (which also counts a decorative
  role alone) -- the latter produced spurious "failed" batch entries: an
  empty request to a real model returns an empty, non-`.ok` response.
  `_resolve_for_drafting()` (2026-09-07) is the one dispatch point
  `draftable_images()`/`images_needing_drafts()` now share for turning a
  reference into something the vision model can read: a real image (as
  before, through `_resolve_describable()`) or a tikz illustration (through
  `tikz_render.ensure_rendered()`, below) -- a tikz reference has no file at
  all for `alt_blocks.resolve_image()` to find, so it has to be
  special-cased before that call rather than after it.
- [`tikz_render.py`](../src/slidemage/tikz_render.py) -- renders a `\tikzillustration{ID}`
  (Slidemaster_preamble_base.tex) to a cached PNG for the drafting pipeline
  above, since there is no `media/` file behind one of these at all
  (ALT_TEXT_NOTES.md's "Phase 9"). Compiles the illustration's own
  *current* tikz body (`alt_blocks.find_tikz_illustration()`, always
  freshly re-read, never trusted stale) into a tiny standalone one-frame
  PDF, reusing `slide_preview.py`'s own `GENERIC_PREAMBLE`/
  `_compile_and_extract()` wrapper-compile machinery verbatim so the
  drawing renders with the same colors/tikz libraries a real slide would
  give it, then rasterizes it via PyMuPDF and auto-crops to its own
  non-white content bounding box (PIL `ImageChops.difference` against a
  solid white background) rather than reaching for a `standalone`/
  `preview`-package crop, which would have meant a second way to compile a
  tikz picture alongside the one already proven for every real slide.
  Cached by `(id, alt_images.tikz_source_hash(options + slide_preamble + body))`,
  not by mtime the way `media_render.py`'s own `.pdf` cache is -- there is
  no file whose mtime would mean anything, so the cache key itself is the
  content fingerprint, making a stale cache structurally impossible rather
  than something to separately check for. Two more real-illustration
  rendering bugs found and fixed 2026-09-14, alongside the options-passthrough
  fix above (see ALT_TEXT_NOTES.md's "Phase 9 follow-up" for the full
  story): `_slide_preamble_text()` copies everything in the slide file
  before its own frame opens (`alt_blocks.FRAME_OPEN_RE`) into the wrapper
  verbatim, since a `\newcommand`/`\definecolor`/`\usetikzlibrary` declared
  there (and referenced from the illustration) is otherwise undefined in a
  standalone recompile even though a real deck compile already sees it
  (the slide file is `\input{}`'d straight into the deck body); and the
  wrapper sets `\pagewidth=60cm`/`\pageheight=60cm` (LuaTeX-native --
  `\pdfpagewidth`/`\pdfpageheight` are undefined under LuaHBTeX) right
  after `\begin{document}`, since an illustration a real slide scales down
  via an *external* `\resizebox{}{}{...}` (outside the environment itself)
  otherwise renders at native size and gets silently clipped by a real
  slide's own small `aspectratio=169` page before the auto-crop step ever
  sees the missing part.
- [`slide_language.py`](../src/slidemage/slide_language.py) -- multi-language parsing
  primitives (2026-08-24), the Python-side twin of
  `Slidemaster_preamble_base.tex`'s `\setSlideLanguageFromSlug`: a slide's
  language lives in its own id-slug's *second* hyphen segment
  (`<id>-<LANG>-<slug>`, `LANG` one of `EN`/`DE`/`mult`), so `own_language()`
  is pure string parsing, no file I/O. `cross_referenced_language()` reads
  a slide's `%% Translation of: ...`/`%% <LANG> translation: ...` header
  comment (alongside `deck_headers.py`'s existing `%% Included in decks:`
  block) to find its translation partner's language. `LanguageBadge`/
  `badge_for()` build the one shared "what should this row's language chip
  say" fact for `qt_deck_editor_tab.py`, `qt_add_slide_dialog.py`, and
  `qt_slide_source_tab.py` to each render in their own widget style --
  `both` (own language *and* a cross-referenced translation into a
  *different* language) is the case meant to be visually highlighted. A
  slide with no language segment at all (any of the ~665 not yet migrated)
  parses to `None` and shows no badge -- no forced migration.
- [`slide_rename.py`](../src/slidemage/slide_rename.py) -- changes a slide's language
  segment: `set_slide_language()` renames `current.tex` plus every frozen
  `-vX-Y-Z.tex` sibling (`git mv` when tracked, else a plain move, same
  fallback `archive.py` already established), rewrites every
  `\slide`-family reference across every deck **including** `#workdeck.tex`
  (unlike `deck_headers.py`'s own header regeneration, which deliberately
  excludes it), then re-runs `deck_headers.regenerate_headers()` and this
  module's own `regenerate_translation_links()`. `set_slide_languages_bulk()`
  is the batched sibling used for one-time migrations (e.g. the 2026-08-24
  "tag all 641 untagged slides as EN" pass, see LANGUAGE_NOTES.md) -- reads
  and writes each deck file **once** with every applicable rename applied
  in a single regex pass, and runs the two regeneration scans once at the
  end, instead of once per (slide, deck) pair; validates every rename's
  destination doesn't already exist *before* moving anything, so a
  collision found on slide 400 of 665 can't leave the project half-migrated.
  `regenerate_translation_links()` mirrors `deck_headers.regenerate_headers()`'s
  own "recompute from disk state, don't trust old text" approach for the
  translation cross-reference comments specifically -- never invents a link
  that doesn't already exist in at least one direction (same add-only
  caution `add_deck_headers.py` and `alt_images.sync_store()` already
  apply), and reports (rather than silently drops) any link whose target
  bare ID no longer resolves to a `-current.tex` file, same as
  `alt_images.SyncReport.missing`. Wired in three places: automatically
  after a rename, automatically after `AddSlideDialog`'s "base on existing
  slide" flow, and as **Housekeeping → Reestablish broken translation
  links** (a plain toolbar button until 2026-08-25) for running by hand
  any time.
- [`translation_prompts.py`](../src/slidemage/translation_prompts.py) -- per-(model, source
  language, target language) prompt configuration for
  `alt_draft.OllamaTranslationBackend`, editable from **Settings →
  Preferences… → AI models → Translation prompts…** (opens
  `qt_translation_prompts_dialog.py`'s own dialog -- a permanent tab of
  the Settings dialog until 2026-09-27, when it moved next to the
  Translation model picker it configures). Different
  Ollama models expect very different prompt shapes -- a dedicated MT model
  wants a short bare instruction with an exact blank-line count before the
  text, a general instruction-tuned model tolerates a longer one -- so each
  `PromptConfig` carries both the prompt text and a `blank_lines` count;
  `build_message()` is the one place that assembles them into the single
  message actually sent (no separate system-role turn -- see `alt_draft.py`'s
  own note on why a system/user split proved less reliable here).
  `get_effective_prompt()` resolves in two fallback steps: an exact
  model+pair entry if one exists, else the single user-editable **default**
  prompt, else a last-resort hardcoded default for a fresh install that has
  never configured anything. Tracked in git (unlike `app_settings.py`
  below) -- which models translate this project's content, and exactly
  how, is project config worth sharing/versioning, not one machine's own
  throwaway state. On-disk shape changed 2026-08-25 to add the "default"
  key (`{"default": {...}, "models": {...}}`, was a bare `{model: ...}`
  dict) -- caught one real migration bug the same day: the old loader read
  an old-format file as empty, so the very next save silently dropped both
  already-configured per-model prompts, found by re-verifying
  `get_effective_prompt()`'s resolution afterward rather than assuming the
  format change was safe (see `version.py`'s v3.2.0 history note).
- [`app_settings.py`](../src/slidemage/app_settings.py) -- local SlideMage UI preferences
  (currently just dark mode), a plain gitignored JSON file living inside
  `SlideMage/` itself rather than the Windows registry (2026-08-25,
  replacing a one-day-old `QSettings` design, direct instruction: "I want
  everything pertaining to SlideMage to be saved in its proper folder,
  and for the app to work as long as that folder is synched" -- a registry
  key is tied to one PC and wouldn't travel with the folder to another
  machine the way a file inside it does). Gitignored but *not*
  sync-ignored -- carried across
  machines by the project folder's own cloud-sync client, not git.
- [`compile_progress.py`](../src/slidemage/compile_progress.py) -- the thin blue progress bar at
  the top edge of the log (2026-09-27), the same blue as the Create PDF button.
  `BatchProgress.feed(line)` is called by `qt_gui.py`'s `_log()` for every log
  line: pass K comes from `Run number K of rule 'lualatex'`, the position inside
  the pass from the `(…/slides/<id>-…` lines LaTeX prints when it starts reading
  a slide file. `fraction = ((pass-1) + slides_seen/slides_total) / passes`, with
  4 passes for a deck that uses biblatex and 3 without; held at 99% until the job
  really finishes (an extra pass just keeps it there). Slide totals use the same
  scoping as the syntax check (version/chapter filters, `\input` fragments). A
  queue is one bar, each job weighted by passes × slides. It also covers
  single-slide renders (3 passes, 1 slide; a buffer render has no slide file to
  read, so it moves per pass), Update previews (one 4-pass megadeck per template)
  and Export PPTX; a job of unknown size shows the busy animation. The status
  label shows e.g. "pass 2/4, slide 137/395".
- [`qt_settings_dialog.py`](../src/slidemage/qt_settings_dialog.py) -- the **Settings →
  Preferences…** dialog (this app's first menu bar, added 2026-08-25). A
  General tab (dark mode, moved off the main toolbar), an **AI models** tab
  (2026-09-26: the default Ollama model for Syntax check, AI drafting, Image
  descriptions and Translation -- every model picker preselects it, and
  picking another one there applies to that dialog only; nothing is
  remembered as "last used" any more) with a **"Translation prompts…"**
  button next to the Translation row (2026-09-27; see
  `qt_translation_prompts_dialog.py` below -- a separate dialog now, no
  longer a permanent tab here) and, below a divider, the Ollama models
  section (2026-09-27; since v4.0.0 headed by the Ollama host URL). Since
  v4.0.0 also an **Updates** group on the General tab (the GitHub token for
  Info → Check for updates…, stored per user in `project.config_dir()`,
  never in the project folder) and an **AI prompts** tab (editable system
  prompts for image-description drafting and the slide rewrite, stored by
  `draft_prompts.py`). The per-task model pickers are refilled by
  `_reload_ollama_models()` whenever the host changes or a model is
  deleted/updated; `qt_gui.py`'s `_on_open_settings()` then passes the
  dialog's `available_models`/`vision_models` to every open picker's
  `refresh_model_preference(s)()`, so a changed default reaches them
  without another Ollama round trip. Close-only dialog -- every field
  saves immediately, except the two AI prompt texts, which have their own
  Save buttons and an unsaved-changes check in `reject()`.
- [`qt_translation_prompts_dialog.py`](../src/slidemage/qt_translation_prompts_dialog.py) --
  `TranslationPromptsDialog`, split out of `qt_settings_dialog.py` 2026-09-27
  (direct instruction: reach it from a button next to the Translation model
  picker instead of a permanent tab). Unchanged content/behavior from the
  old tab: a "Default prompt" group plus a per-(model, source, target)
  list/editor backed by `translation_prompts.py`, with the model combo
  populated from `alt_draft.list_all_models()` (editable, so a not-yet-
  installed model name can still be pre-configured) -- including its own
  unsaved-changes-on-close check (`reject()`), since it now closes
  independently of `SettingsDialog` rather than sharing that dialog's own.
- [`qt_archive_unused_dialog.py`](../src/slidemage/qt_archive_unused_dialog.py) --
  `ArchiveUnusedDialog` (2026-09-27, direct instruction, after a real batch
  run archived far more than expected -- see `unused_content.py`'s own
  entry above for the two bugs that caused it): lists every file
  `find_unused_media()`/`find_unused_slides()` found, with Cancel (the
  default button) or "Archive N file(s)"; `qt_gui.py`'s
  `_on_archive_unused_content` runs both scans on the GUI thread (fast
  enough not to need a background thread) and shows this dialog before
  starting the actual move, which still runs on a background thread as
  before.
- [`transcript.py`](../src/slidemage/transcript.py) -- per-deck accessible transcripts,
  Markdown source and HTML delivery. Resolves deck versions exactly as the
  PDF compile does and keeps PDF slide numbering. Student versions only.
  A slide's `SlideNotes.summary` (alt_images.py), when set, renders as
  `**Summary.**` right after the `*Slide ID ...*` line and before the
  slide's own body -- ahead of the content, not after, so a reader gets
  oriented before the bullet points rather than as an afterthought.
  `deck_language_of()` (2026-08-24) parses a deck's own `\decklanguage[...]`
  to render the whole transcript in German where applicable (UI strings via
  a `STRINGS` EN/DE table, image text from the `_de` fields with English
  fallback) -- uses `finditer()` and picks the first value that isn't a
  bare `\decklanguageoverride` macro reference, not `.search()`, since a
  plain `.search()` always matches the `\ifdefined\decklanguageoverride`
  branch first (a macro name, not a literal value) and so always read as
  English even on a real German deck -- caught by generating a transcript
  against a deck temporarily set to `\decklanguage[de]` and confirming
  German output, not assumed from the regex alone.
- [`slide_snapshot.py`](../src/slidemage/slide_snapshot.py) -- compile-time PNG previews.
  Every compile that touches a slide (a single-slide preview render, or a
  full-deck instructor compile) refreshes a pair of files named
  `<bare id>-<TemplateName>-<width>-<height>.png` (e.g.
  `22s-UniGraz-1920-1080.png` and `22s-UniGraz-304-171.png` -- bare id
  first since 2026-08-17, direct instruction, so the directory sorts and
  glob-matches by slide before institution), or, for a slide that's been
  migrated to the language-tagged id-slug convention (2026-08-24, see
  [README.md](../README.md)'s "Multi-language (EN/DE) slides"), `<bare
  id>-<Lang>-<TemplateName>-<width>-<height>.png` -- `<Lang>` (`EN`/`DE`/
  `mult`) is resolved via `_own_language_for_bare_id()`, which reads it
  straight off that slide's own id-slug, not off whichever deck happens to
  be compiling it (a migrated slide's language is fixed by its filename
  regardless of which deck includes it). A not-yet-migrated slide's
  filename is untouched -- no `<Lang>` segment -- so the ~665 already-cached
  preview files never needed mass-regenerating on rollout day. From that
  slide's *last* page (its final `\pause`/overlay step) -- a best-effort
  cache so a review UI can show *something current-ish* without paying a
  LaTeX compile to do it, never a guaranteed-fresh source of truth.
  `detect_template(preamble_text)` regexes a preamble's own
  `\input{Slidemaster_preamble_(uni-graz|uni-ibk|mci)}` line (falling back
  to `uni-graz`), so a Uni Graz and a Uni Innsbruck compile of the same
  slide id keep separate caches -- computed once by the caller
  (`compiler.py`/`slide_preview.py`) from `Deck.preamble_text`/the render's
  own preamble and threaded through, not re-detected per snapshot call.
  `_save_page()` renders each of `FULL_SIZE` (1920x1080) and `THUMB_SIZE`
  (304x171 as of 2026-08-16, up from an initial 240x135 -- "approximately
  25% wider"; the closest exact-16:9 pair, since 300x168.75 isn't an
  integer pixel size and a non-16:9 target would apply very slightly
  different x/y zoom factors and stretch the image) directly from the
  compiled PDF page via its own per-axis zoom matrix -- never by
  downsampling the larger bitmap afterward, which is both simpler and
  visibly crisper.
  Requires PyMuPDF (`pymupdf`, imported `as fitz` -- `import fitz` alone
  still works but is deprecated in current releases), the one addition
  beyond this project's former "PySide6 only" dependency policy; justified
  by precedent, since `decks/render/compare_render.py`'s own
  page-identification approach (every compiled page's footer carries
  `"slide id: XXX"`, read via `page.get_text()`) is reused here almost
  verbatim. Each resolution's zoom is computed via a per-axis zoom factor
  from each page's own point size (`zoom = target_px / page_size_pt`)
  rather than picked via a DPI value, since no DPI lands on that exact
  pixel size after rounding but this always does. `bare_id(id_slug)` --
  everything up to the first `-` -- is what every snapshot is actually
  keyed under, because that's what `\setSlideID`
  (Slidemaster_preamble_base.tex) itself derives from the full `id_slug` a
  `\slide{}`/`\slideversion{}` call takes; a caller with only the full
  slug (a deck/slide-editor row, which needs it whole to `\input{}` the
  right file) has to convert. Missing this conversion once already shipped
  a hover-tooltip/Preview-popup that could never find a real snapshot --
  caught by a test that exercised the actual conversion path instead of a
  hand-picked bare id, see ALT_TEXT_NOTES.md.
- [`update_all_previews.py`](../src/slidemage/update_all_previews.py) -- the "Update
  previews" button's logic. Rewritten 2026-08-16 (direct instruction:
  "I forgot that each deck has a specific template linked to it... scan
  all decks that I have, make a list of slide-template combinations, and
  automatically render each slide for all templates that any deck uses
  them with... also delete all rendered versions that are no longer in
  use") -- the original version asked which single institution to
  compile every slide in the project under, which is wrong once a slide
  can legitimately need caching under more than one template (or none).
  `needed_slides_by_template()` scans every deck `deck_scan.scan_decks()`
  finds (active *and* archived -- an archived deck's own editor tab still
  shows cached previews) and groups every `\slide{}`-family call's own
  full `id_slug` by that deck's own detected template
  (`slide_snapshot.detect_template()`), giving `{template key: {full
  id_slugs}}`. `run()` then compiles one throwaway deck per template
  (`_run_one_template()`, same `compiler.run_job()` mechanics the
  original single-template version always used, just scoped to that
  template's own needed slides instead of every slide in the project),
  skipping a template with an empty set entirely rather than wasting a
  compile on nothing (this project's own `test-ibk.tex`/`test-mci.tex`
  hit exactly that: they `\input{}` a shared fragment rather than calling
  `\slide{}` directly, so their own template detects with nothing of its
  own -- confirmed directly, not assumed, when it first showed up as a
  test failure). `_prune_stale_snapshots()` then deletes every cached
  file (`_SNAPSHOT_FILENAME_RE`, anchored to `slide_snapshot.TEMPLATES`'
  own display names) whose (template, bare id) isn't in that scan's
  result any more -- skipped if the run was cancelled partway through, so
  an aborted "Stop creation" doesn't delete caches based on a scan
  that never got to run its compiles. Wired into `qt_gui.py`'s toolbar,
  reusing the same `self.compiling` busy-state machine (detached thread,
  `CancelToken`, log signal) every real compile already goes through,
  since underneath each template is still just one `CompileJob`.
  `run()` accepts an optional `base_jobnames` dict (one entry per
  template, not just one job any more) so `_on_update_previews()` can
  generate every job's name itself, register a `self._job_progress_texts`
  entry for each (keyed by `f"{base_jobname}-instructor"`, matching
  `CompileJob.jobname`'s own `-{version}` suffix), and pass them in before
  any compile's first log line ever arrives -- without this, the status
  line by "Log:" stays blank for the whole run: `_log()`'s
  `RUNNING_LOG_RE` handling matches the line fine, but its
  `_job_progress_texts` lookup finds nothing, since that dict is normally
  only populated by `_start_jobs()` for the real compile queue, which
  this ad-hoc job never goes through.
- [`qt_slide_preview_popup.py`](../src/slidemage/qt_slide_preview_popup.py) -- the small
  in-app dialog that shows a slide_snapshot.py PNG, shared by
  `qt_deck_editor_tab.py`'s per-row "Preview" button and
  `qt_slide_source_tab.py`'s own "Preview" button. Deliberately dumb about
  *how* to render -- the caller passes a zero-argument `render_fn` closure
  (raises on failure) for the popup's "Render now" fallback when nothing's
  cached yet, since a deck row and the source editor need different
  compile calls (own preamble/frame number vs. the saved file's own
  macro/version) but the popup itself only needs to know how to display
  the result. Also surfaces staleness (`slide_snapshot.is_fresh()`): a
  snapshot older than the slide's own source file is flagged, not hidden.
  `qt_deck_editor_tab.py`'s hover tooltip points at the cached
  `THUMB_SIZE` file directly (not the full-size one scaled down by Qt's
  rich-text `<img width=N>`, which was the actual source of the "not
  crisp" complaint), and its toolbar's "View: List / Thumbnail / Grid"
  radio trio (a `QButtonGroup`, exclusive by default) picks between them.
  Each is a genuinely different tradeoff, not three names for the same
  thing:
  - **List** and **Thumbnail** share one widget tree -- the per-slide row
    grid `_build_row` builds. Thumbnail just flips a `_show_thumbnails`
    flag and rebuilds; `_build_thumbnail_row` then inserts one extra grid
    row directly under a slide's controls, holding just the cached image
    in the id link's own column, so every row control (variant, remove,
    +before/+after, Preview) stays exactly where List puts it (2026-08-15,
    direct instruction: thumbnail view should "resemble the list view --
    same buttons and options", after an earlier version made it a
    separate read-only card browser and lost every row control).
  - **Grid** is a real second widget tree (`self.view_stack`, a
    `QStackedWidget`) -- a fixed-column `QGridLayout` of plain cards
    (image + id caption, click to open, no row controls at all). This
    was that same earlier card-browser design, reinstated by direct
    request once Thumbnail stopped covering that "quick visual scan,
    nothing else" use case -- recovered from this conversation's own
    transcript (the file as read immediately before being rewritten),
    since nothing had been committed yet to `git log` it back from.
  Since a 3-way exclusive group can't tell *which* option just became
  active purely from "the button that turned true" (the 2-way trick List/
  Thumbnail used), all three radios connect to the same
  `_on_view_toggled`, which ignores the `checked=False` calls and reads
  `.isChecked()` off `thumbnail_view_radio`/`grid_view_radio` directly.
  A chapter combo between Undo and Close jumps straight to a chapter in
  both List/Thumbnail and Grid at once (so whichever the user is looking
  at is already lined up, and switching to the other stays lined up too),
  computing each view's own header's y position relative to its own
  scrolled widget (`header.mapTo(inner, QPoint(0, 0))`) and setting that
  view's vertical scrollbar to exactly that value -- `QScrollArea.
  ensureWidgetVisible` was tried first but only guarantees the heading
  becomes visible *somewhere* in the viewport, which could leave it at
  the bottom edge instead of the top depending on scroll direction
  (direct instruction: land it at the top, always). Chapter-header dicts
  (one per view) are keyed by occurrence index rather than title text,
  since two chapters sharing an exact title would otherwise collide on
  the same dict key. (A preview-template dropdown next to "View:" briefly
  existed here -- letting a user browse a deck's cached snapshots under a
  *different* institution's template -- but was removed the same day,
  direct instruction: "I forgot that each deck has a specific template
  linked to it... Remove the template dropdown again." Every deck already
  carries exactly one real template; there was nothing meaningful to
  switch between.)
- [`deck_duplicate.py`](../src/slidemage/deck_duplicate.py) -- the Active decks table's own
  "Duplicate" button. A plain `shutil.copy2` under a new filename stem, no
  content rewriting needed (unlike `archive.py`'s `archive_deck()`): a
  deck's name is derived purely from its filename, never embedded in the
  `.tex` content itself. `is_valid_deck_name()` is exposed separately from
  `duplicate_deck()` so the caller can show a validation reason directly
  in the UI before attempting anything, rather than parsing an exception
  message; `duplicate_deck()` re-checks it anyway rather than trusting the
  caller blindly.
- [`slide_versioning.py`](../src/slidemage/slide_versioning.py) -- the automatic freeze-then-
  bump workflow behind `qt_slide_source_tab.py`'s own Save button for a
  slide's `current.tex` (2026-08-20, direct instruction), replacing manual
  `slide.archive()` as the everyday path. Pure logic, no Qt/file-path
  assumptions beyond a `Path` -- `qt_slide_source_tab.py`'s own
  `_prompt_version_choice()` is the only place that shows a dialog.
  `parse_version()` reads a `\setSlideVersion{X-Y-Z}` line embedded near
  the top of `current.tex` (mirrors the `%% Included in decks: ...` header
  `add_deck_headers.py` maintains -- another tool-managed line nobody
  hand-edits); `plan_save()` maps the dialog's own major/minor/patch/
  overwrite choice plus that parsed version to `(final_version, freeze_as)`
  -- `freeze_as` is `None` for "Overwrite" (never freezes), otherwise the
  version being retired (the parsed one, or `DEFAULT_BASELINE` `1.0.0` if
  this is the slide's first-ever tracked save). `freeze_slide()` is a
  plain `shutil.copy2` of whatever's on disk *before* the save lands, same
  raw-copy convention `deck_duplicate.py` and `slide.archive.R` both
  already use -- returns `None` (not an error) if that exact version was
  somehow already frozen, so a `_on_save()` that hits this doesn't
  silently clobber real history, just logs and moves on.
  `\slideversion{ID-slug}{X-Y-Z}` reads the version from its own second
  argument, never from a frozen file's content -- so frozen files
  themselves never need a `\setSlideVersion{}` of their own, and this
  module never writes one.
- [`bibliography.py`](../src/slidemage/bibliography.py) -- a small BibTeX reader so citations
  in transcripts read as references rather than keys. Hand-written rather
  than a dependency because this project declares exactly one and the data
  is well behaved (89 entries, no `crossref`, no `@string`).
- [`qt_transcript_tab.py`](../src/slidemage/qt_transcript_tab.py) -- the tab itself.
- [`deck_scan.py`](../src/slidemage/deck_scan.py) -- finds every deck (`decks/*.tex` and
  `decks/archive/*.tex`) and parses it. A "deck" is any `.tex` file
  containing `\documentclass` -- the same heuristic README.md already uses
  for "top-level compilable file," which naturally excludes fragments like
  `decks/test-slides.tex`. Also detects, per deck: whether it supports the
  `\deckversionoverride` pattern (regex search), whether it uses biblatex
  (`\addbibresource` present), and its ordered list of chapters (each
  `\section{Title}` match, sliced through to the next `\section{}`/
  `\end{document}`, with a slugified title).
- [`compiler.py`](../src/slidemage/compiler.py) -- builds a wrapper `.tex` and runs it
  through `latexmk`, reusing `compile-all-versions.bat`'s own proven trick
  (a wrapper file that `\def`s `\deckversionoverride` then `\input{}`s the
  real deck -- latexmk's `-usepretex` strips braces/backslashes from its
  argument, so a real wrapper file is used instead of that). Extended here
  to also support a **per-chapter** wrapper: instead of `\input{}`ing the
  whole deck, it copies the deck's entire preamble text verbatim (up to and
  including `\begin{document}`) plus just one chapter's slide-call lines,
  then `\end{document}`. Always invoked with `cwd=PROJECT_ROOT` so the one
  shared root `.latexmkrc` governs `$aux_dir`/`$do_cd`. Pass/fail is decided
  by scanning `.build/<jobname>.log` for a line starting with `!` plus
  checking the PDF exists -- never by latexmk's exit code (nonzero even on
  a clean compile, from harmless Fira Sans font-substitution warnings). On
  success, moves the PDF (+ `.synctex.gz`) into a new top-level `pdf/`
  folder and cleans `.build/<jobname>.*`; on failure, leaves the log for
  debugging and leaves no PDF in `pdf/`.
- [`archive.py`](../src/slidemage/archive.py) -- moves `decks/<name>.tex` to
  `decks/archive/<name>.tex` (`git mv` when tracked, else a plain move) and
  patches its own path fallbacks for the extra directory depth. See
  "Archiving gotchas" below -- this module's docstring has the full story,
  but the short version is that the naive fix (extend the two-branch
  `\IfFileExists` bib check to three branches) silently breaks citations,
  and the actual fix is simpler than that.
- [`unused_content.py`](../src/slidemage/unused_content.py) -- two independent scans: every
  `media/` file actually `\includegraphics{}`-ed (or similar -- just looks
  for the literal `media/<name>` substring rather than enumerating every
  macro that can carry one) from any `slides/*.tex` file is "in use," and
  every `slides/<id>-current.tex`/`slides/<id>-vX-Y-Z.tex` actually
  `\slide{}`/`\slideversion{}`/`\conditionalslide{}`/`\omitslide{}`/
  `\omitslideversion{}`-ed from any `*.tex` directly inside `decks/` or
  `decks/archive/` is "in use." Everything else in each folder (not
  already inside its own `archive/` subfolder) gets moved into one. See
  "Archiving unused content" below for the two deliberate wrinkles (the
  extensionless-reference case and the source/derived-file convention).
  The slide-usage macro list also covers `\slidestep{}` since 2026-09-27
  (added late -- see that section's own entry for the false-positive batch
  this caused before it was), and `MEDIA_NEVER_UNUSED` excludes
  `media/alt-text.json`/`.csv` outright: they're read directly by
  `Slidemaster_alt.lua`, never `\includegraphics{}`-ed, so the media scan
  could never see them as "used." **Housekeeping → Archive unused slides
  and media files** (`qt_gui.py`'s `_on_archive_unused_content`,
  `qt_archive_unused_dialog.py`) now runs both scans up front and shows
  every file in `ArchiveUnusedDialog` before moving anything -- Cancel
  (the default button) leaves the folders untouched, "Archive N file(s)"
  is the only action that starts the actual move.
- [`qt_gui.py`](../src/slidemage/qt_gui.py) -- the main window (the Tk
  `gui.py` it replaced has been removed). `DeckRow`
  ([`qt_deck_table.py`](../src/slidemage/qt_deck_table.py)) owns one row's
  checkboxes and turns them into a list of `CompileJob`s.

## GUI framework: PySide6 (Qt), migrated from Tkinter/ttk

The app now runs on PySide6 (`qt_gui.py` and the other `qt_*.py` modules) --
`__main__.py` launches it. See [`PYSIDE6_MIGRATION.md`](PYSIDE6_MIGRATION.md)
for the full history: why (permanent ttk limitations -- no per-tab colors,
no native tab scrolling, dark mode only working via a hand-rolled
widget-registration workaround), the file-by-file/widget-by-widget mapping,
and the phased implementation log. The original Tk implementation has
since been removed. Install for development with `pip install -e ".[dev]"`
from the repo root and run `slidemage` (or `python -m slidemage`).

## Non-obvious things worth knowing before touching this code

**Archiving and biblatex don't mix the way you'd first guess.** The
original two-location support (`decks/foo.tex` compiles correctly whether
invoked from the project root or from inside `decks/`) works via
`\IfFileExists{Slidemaster.bib}{...}{\addbibresource{../Slidemaster.bib}}`.
The obvious extension for a third location (`decks/archive/`, one level
deeper again) is a third `\IfFileExists` branch trying
`../../Slidemaster.bib`. **This was tried and empirically confirmed
broken**: biber recorded `../Slidemaster.bib` (one level short) as the
resolved path even though `decks/Slidemaster.bib` doesn't exist, and
latexmk then silently *vetoed* running biber at all (not a fatal error --
just `Latexmk: Veto of running of 'biber ...'` in the log, plus every
citation showing as an undefined-citation warning instead of a real
reference). Root cause not fully chased down (some kpathsea/`\IfFileExists`
interaction), but the fix is simpler than debugging it further: since this
tool *always* compiles an archived deck through latexmk with `$do_cd` (cwd
is always `decks/archive/` -- there's no second "compiled from a different
depth" case to support, unlike `decks/` itself), the correct path is
knowable up front. `archive.py` replaces the whole `\IfFileExists` cascade
with a single unconditional `\addbibresource{../../Slidemaster.bib}`.
Confirmed working end-to-end (citations resolved, biber ran, no veto) on a
throwaway duplicate of `t-Uni-IA2-2026w-preview.tex`.

**Archiving refuses decks with a sibling `\input{}`.** `test.tex`/
`test-mci.tex`/`test-ibk.tex`/`test-student.tex` all `\input{test-slides}`
-- a fragment living in `decks/` itself, not the project root. Archiving
moves *only* the requested deck's own `.tex` (that's how the feature was
scoped), so a deck depending on such a same-directory sibling would
silently break once it's one directory deeper than that sibling. This was
hit directly while testing (a duplicate of `test-mci.tex` failed to compile
after archiving with `! LaTeX Error: File 'test-slides.tex' not found`).
`archive.py`'s `_sibling_dependencies()` detects this pattern (a bare
`\input{X}` where `X.tex` exists next to the deck, excluding the
`Slidemaster_preamble_uni-*` institution input) and raises before moving
anything, rather than silently producing a broken archived file. The real
course decks (`t-Uni-FM2-2027s*`, `t-Uni-IA2-2026w*`) are self-contained and
never hit this.

**`git mv` fails outright on an untracked file** (`fatal: not under version
control`) -- hit directly while testing with a throwaway scratch file that
had never been committed. `archive.py` checks `git ls-files
--error-unmatch` first and falls back to a plain `shutil.move` when the
file isn't tracked (there's no history to preserve for it anyway).

**PDFs land in `pdf/`, not next to the source -- and only the PDF, no
`.synctex.gz`.** The `pdf/`-not-next-to-source part was a deliberate choice
(confirmed with the user) rather than matching
`compile-all.bat`/`compile-all-versions.bat`'s own convention of leaving
the PDF next to the `.tex` file -- `compiler.py` lets latexmk do that as
normal, then moves the result into a flat top-level `pdf/` folder
afterward. The user separately confirmed they don't want the `.synctex.gz`
latexmk also produces copied into `pdf/` at all (unlike the PDF, it's just
deleted wherever it lands, not moved). Both `pdf/` and `.build/` already
fall under the project's existing `.gitignore` (`*.pdf`, `.build/`), so
nothing further was needed there; a `__pycache__/`/`*.pyc` rule was added
to `.gitignore` since this is the first real Python package in the repo.

**Chapter-split PDFs contain only that chapter's own slides** -- no shared
front-matter (title/admin/agenda slides before the first `\section{}`) is
repeated into each one. Also a deliberate choice confirmed with the user,
not a default I picked unilaterally.

**latexmk's own copy-back rename can hang forever, not just fail.** This
project lives under `D:\uniCLOUD\...` -- almost certainly a cloud-sync
client's watched tree. `$do_cd` in `.latexmkrc` leaves `$out_dir` at its
post-cd default (the deck's own directory), so latexmk's own last step
copies/renames the finished PDF there from `$aux_dir` (`.build/`). The
first symptom found (chapter 1 of an 11-chapter deck reporting FAIL while
chapters 2-11 passed, log showing `Latexmk: Moving '.../.build/....pdf' to
'....pdf' -- That failed, with message 'Device or resource busy'`, zero
`!` fatal LaTeX errors anywhere in that chapter's own log) looked like a
simple locked-destination case -- e.g. a PDF viewer with a previous run's
output still open -- and was originally fixed by falling back to
`.build/<jobname>.pdf` as the move source whenever the deck-directory copy
is missing but the log confirms no fatal error. **That fallback alone
wasn't enough**: a later real run reported the exact same "Device or
resource busy" line and then produced *no further output at all* -- the
whole batch stalled permanently, confirmed directly by the user. A PDF
viewer's lock is released as soon as you close it; a sync client's lock on
a freshly-written ~90MB PDF (while it hashes/uploads) can last far longer,
long enough that latexmk's own internal retry around the rename apparently
never returns control to the Python side at all -- no fallback logic can
run if the subprocess itself never exits.

First fix: `compiler.py`'s own `latexmk` invocation now passes
`-outdir=<.build/, absolute>` on the command line (CLI beats the rc file),
making `$out_dir` equal `$aux_dir` for that invocation only -- latexmk then
has nothing to copy back, so *that* rename (and its hang) never happens at
all. Only compiler.py's own compiles get this; `.latexmkrc` itself is
untouched, so a direct `latexmk`/TeXstudio compile still gets the PDF next
to the source as before (matching `compile-all.bat`/`compile-all-versions.bat`'s
old convention, back when those scripts still existed). Confirmed working: a later real run's
log showed latexmk logging `Latexmk: Undoing directory change` and nothing
about moving anything -- no more risky rename inside latexmk itself.

**But the one rename still left -- this module's own move of the finished
PDF from `.build/` into `pdf/` -- hit the exact same stall, just one level
up.** The user had by then excluded `.build/` from the sync client's
watched folders but kept `pdf/` synced (deliberately -- that's the folder
they want to end up synced). A first attempt at fixing *this* move used a
retry-with-sleep loop (`_move_with_retry()`, 10 attempts, a few seconds
apart) on the assumption that a cloud-sync lock would make the rename fail
fast, the same way a PDF-viewer lock does, so a short pause and retry
would ride it out. **Confirmed directly to be wrong**: a real run stalled
forever right after logging `==== MOVING: ... ====`, with *no exception
ever raised* -- not even one caught-and-retried instance. A retry loop can
only run once the call it's retrying raises and returns control; if the
call itself never returns at all, the loop never gets a turn. This is
consistent with a cloud-sync client that uses a placeholder-file mechanism
(e.g. Windows' Cloud Files API) rather than a plain file lock: a
delete/rename on a file that isn't fully local yet can trigger a
synchronous network round-trip *inside* the OS call itself, which blocks
for however long that round-trip takes -- no different, mechanically, from
why latexmk's own internal retry hung earlier.

Second, corrected fix (superseded below, kept for the history): `_relocate_pdf()`
ran inside `_run_with_timeout()`, which put it on a background daemon
thread and waited up to `PDF_MOVE_TIMEOUT_SECONDS` (60s) via
`Thread.join(timeout=...)` rather than calling it directly. On timeout it
stopped *waiting* -- raised `TimeoutError`, reported the job FAIL with the
PDF left behind at `.build/<jobname>.pdf` for manual recovery, and
abandoned the thread. `run_job()` itself still *waited* for that whole
60s, though -- and waited on the GUI's behalf, since `run_jobs()` runs
every job strictly sequentially: a stuck move on job 1 held up job 2, held
up `self.compiling` resetting, held up the "Compile" button re-enabling.

**Third fix (2026-08-14): still not enough.** The user hit the identical
stall a third time compiling a real deck -- 60s wasn't generous enough to
reliably outlast a slow sync round-trip, and worse, a *bounded single
wait* means giving up there means giving up for good: the only way to try
again was recompiling the whole deck from scratch, expensive for a large
deck, just to get another shot at a move that has nothing to do with
whether the LaTeX itself was fine. Explicit ask: make the move threaded so
the rest of the app isn't blocked by it, and retry it every 10 seconds for
up to 15 minutes rather than giving up after one.

The single-bounded-wait design had rejected a retry loop with two stated
reasons: "retrying a call that might still be blocked on the very same
lock wouldn't obviously help" (true for the *specific* call, but a fresh
attempt only has to succeed once the underlying cloud round-trip
eventually resolves, whenever that is -- so periodically trying again over
a much longer window than 60s is exactly what rides that out), and
"starting a second thread against the same source/destination paths while
the first one might still be quietly running risks the two racing each
other" -- true in general, but every retry attempt here copies the exact
same already-compiled, never-changing `.build/<jobname>.pdf` to the same
destination: two attempts racing are copying *identical bytes from an
identical source*, not two different pieces of content, so the worst case
is a redundant write, not corruption. That reconsideration is what made a
real retry loop safe to bring back.

`_relocate_pdf_and_finish()` replaces `_run_with_timeout()`: it runs
entirely on its own detached daemon thread that `run_job()` fires and does
**not** wait for -- `run_job()` returns `True` (compile succeeded) the
moment latexmk itself is done, logging the fixed `MOVING` line (parsed by
`qt_gui.py`'s `MOVING_LOG_RE` for the row's status dot, so that wiring
didn't need to change) with extra context appended, then moves on. Inside
that detached thread: fire a fresh attempt every `PDF_MOVE_RETRY_INTERVAL_SECONDS`
(10s) regardless of whether an earlier attempt ever returned (abandoned
attempts are harmless daemons, per the same-content-copy reasoning above),
until one succeeds or `PDF_MOVE_RETRY_TOTAL_SECONDS` (15 min) elapses. A
heartbeat logs roughly once a minute so a long wait doesn't look stuck.
Once it does succeed, the aux-file cleanup, the slide-preview PNG snapshot
refresh (`slide_snapshot.py` -- also silently skipped if the move never
lands, which is what the user meant asking "this probably also prevents
the .png, right?"), and the final `PASS` line all run right there, exactly
where they used to run synchronously in `run_job()` -- they're contingent
on the move actually succeeding, whenever that turns out to be. If the
whole 15 minutes elapses with no success, the same `*** FAIL ...` message
as before is logged, still pointing at `.build/<jobname>.pdf` for manual
recovery -- but that FAIL now costs nothing but itself; every other job in
the batch already ran while this one was quietly retrying in the
background.

**The status bar tracks latexmk's own rerun count, not a fixed job-batch
position.** The first attempt at this kept the old "Compile X/Y" phrasing
but repurposed X/Y as *batch* position (which whole-deck job out of how
many in this run) -- confirmed directly as not what was wanted: for a
single-deck compile that's always "1/1", which reads as frozen/not
updating even while the log below it streams several separate "Run number
N of rule 'lualatex'"/"...'biber /path/jobname'" lines. The user wanted
those *reruns* themselves labelled as "Compile N" instead. Deliberately
**no fixed total on the other side of a slash** (a real design question,
asked and answered directly by the user rather than assumed): latexmk
decides how many lualatex/biber passes a compile actually needs as it
goes, so there's no honest number to put there -- `$max_repeat`'s default
of 5 was considered and rejected as misleading (it's a ceiling almost
never actually reached, not a real prediction of how many passes a given
compile will take). So whole-deck jobs show just `Compiling <deck>`,
counting up live as `Compiling <deck>: Compile 1...`, `Compile 2...`, etc.
(a colon, not the em-dash first tried, per explicit user preference) as
latexmk's own "Run number N..." lines stream past (matched directly -- raw
latexmk output, not one of compiler.py's own synthetic `====` lines, so it
carries no jobname; safe to attribute to "whichever job most recently
logged Compiling" because `run_jobs()` runs strictly sequentially, one job
at a time). Per-chapter jobs keep their own "Chapter 5/12" (a real, fixed
total known up front) with the same live "Compile N..." appended alongside
it. When a batch spans more than one distinct deck, `_build_progress_texts()`
prefaces every line for that job with `Deck I/N | ` (I = this job's deck's
1-based position among the batch's distinct decks in job order, N = how
many distinct decks total) -- omitted entirely for a single-deck batch,
where it would just be a constant, uninformative "Deck 1/1".

**Every subprocess call passes `creationflags=subprocess.CREATE_NO_WINDOW`
on Windows.** `slidemage` is installed as a GUI script, so it has no console of its
own (the whole point -- a normal-looking app window, not a terminal), so
without this, Windows pops up a brand-new console window -- floating on
top of the GUI -- for every child process: `compiler.py`'s own `latexmk`
call (and confirmed directly as the "inelegant" window reported by the
user), plus `archive.py`'s two `git` calls (`ls-files`/`mv`), which would
otherwise flash the same way. Guarded with `if os.name == "nt"` since the
flag doesn't exist on other platforms, even though this project is
Windows-only already.

**Version checkboxes are auto-disabled per deck**, not just per compile:
`deck_scan.py` detects whether a deck actually contains
`\deckversionoverride` at all. A deck without it (e.g. `test.tex`) would,
per `compile-all-versions.bat`'s own comment, "silently produce three
identical PDFs" if all three versions were compiled -- so the GUI only
enables `Instructor` for such decks (compiling with `version=None`, i.e. no
`\deckversionoverride` def at all, just whatever's hardcoded in the file).
**Bug found and fixed directly by the user**: the first implementation
computed the checkbox `state` once (`"normal" if deck.supports_version
else "disabled"`) and applied it to *all three* checkboxes, so a deck
without `\deckversionoverride` had `Instructor` disabled too -- completely
uncompilable through the GUI, not just missing the two version-aware
options. Fixed by requiring `deck.supports_version` only for
During-course/After-course; `Instructor` is now unconditional.

**Archiving unused content (`unused_content.py`) has two deliberate
wrinkles, both confirmed against the real repo.** First: a
`\includegraphics{}` (or `\chapterlogo{}`/`\fullbleedframe{}`/
`\begin{sideimageframe}{}{}`/etc.) call can omit the file extension
entirely and let LaTeX's own default-extension search pick one --
confirmed directly, `slides/vpk-Collateralized-Debt-Obligations-current.tex`
does exactly this for `media/midjourney-bankers-slicing-bonds` (no
`.jpeg`). The media scan handles this by falling back to a bare-stem match
across every file in `media/` when the reference has no extension of its
own, rather than only ever looking for an exact filename match. Second:
every media file is grouped with every other file sharing its stem (e.g.
`chart-portfolio-frontier.svg`/`.pdf`) and the whole group counts as used
if any member does -- confirmed directly against a genuine real case:
`slides/fmn-Minimum-Variance-Portfolio-Derivation-current.tex`'s own
`\includegraphics` call uses `media/chart-portfolio-frontier.pdf`, and its
sibling `media/chart-portfolio-frontier.svg` (the vector source, which
LaTeX/lualatex can never `\includegraphics` directly) is correctly kept
alongside it rather than flagged as unused, while an *unrelated*, genuinely
orphaned file the same slide's own header comment mentions in passing --
`media/chart-minimum-variance-portfolio.png`, an old raster diagram
superseded by that same vector redraw in a past edit -- is correctly
flagged, since nothing shares *its* stem and no `\includegraphics` call
anywhere still names it. (At the time this was tested, 2026-08-16, neither
scan stripped LaTeX comments first, and this file's own passing mention in
a header comment happened not to include the literal `media/` prefix
`MEDIA_REF_RE` requires -- so it stayed correctly flagged either way. Since
2026-08-25 both scans strip comments first regardless -- see the module
docstring -- so this particular case is no longer order-dependent, but
wasn't re-verified against this exact file after that change.)

**The slides/ scan deliberately does *not* use `deck_scan.scan_decks()`.**
That function only returns files containing `\documentclass` (the "real
deck" heuristic) -- but `decks/test-slides.tex` is a shared `\input{}`-ed
fragment with real `\slide{}`/`\omitslide{}` calls of its own
(`test.tex`/`test-mci.tex`/`test-ibk.tex`/`test-student.tex` all `\input{}`
it rather than listing their own slides), so excluding it would make every
slide it lists (the `ZZ*`-prefixed test/demo slides) look unused and get
archived. `unused_content._deck_texts()` instead reads every `*.tex` file
directly inside `decks/`/`decks/archive/` (skipping only SlideMage's own
`_`-prefixed generated wrapper files), regardless of whether it has
`\documentclass`.

## Known limitations (not built, not requested)

- No "un-archive" / restore action. The archive fixups deliberately don't
  remove the shallower-path branches they didn't need to touch (there
  aren't any left after the bib simplification above, but the
  `\input@path`/`\graphicspath` change is a direct edit, not reversible by
  the tool) -- a manual move back plus a manual path fix would be needed.
- No dependency-graph-aware archiving: `_sibling_dependencies()` only
  catches the specific "bare `\input{X}` where `X.tex` sits next to the
  deck" shape. A deck depending on something else decks/-local in a
  different way wouldn't be caught the same way.
- No real GUI tooltips (Tkinter has none built in) -- disabled-checkbox
  reasoning is instead a static caption line under each table.
- No scrollable table -- fine at the current ~8-deck scale; would need a
  canvas+scrollbar if the deck count grows a lot.
- ~~`unused_content.py`'s scans don't strip LaTeX comments before
  matching~~ -- fixed 2026-08-25, direct instruction: both scans now strip
  every unescaped `%...` comment tail first (`_strip_comments()`), so a
  commented-out `\slide{}`/`\includegraphics{}` reference no longer
  masks an otherwise genuinely unused file.

## What was actually tested

Every check below ran against real repo state but only ever compiled
`test.tex`, duplicates of `test-mci.tex`, and duplicates of
`t-Uni-IA2-2026w-preview.tex` (a per-deck preview file retired since,
when `decks/#workdeck.tex` took over that role -- don't go looking for
it) -- never the real course decks
(`t-Uni-FM2-2027s.tex`, `t-Uni-IA2-2026w.tex`), per this project's
"don't auto-compile the main deck" convention.

- `deck_scan.scan_decks()` against the real `decks/` folder: correct deck
  list, correct chapter counts (12 for FM2, 11 for IA2, 0 for both
  `-preview` decks -- they have no `\section{}` calls), correct
  version-override detection.
- `find_unused_media()`/`find_unused_slides()` (the read-only detection
  half of `unused_content.py`) run against the real, live `media/`/
  `slides/` folders: 15 media files and 8 slides flagged, every one spot-
  checked by hand and confirmed correct (superseded `-v1-0-0.tex` slide
  versions no deck references anymore; `qxr-Introduction-to-R-Assignments-
  current.tex`, since both decks pin frozen versions of it instead; the
  genuinely-orphaned `chart-minimum-variance-portfolio.png` case described
  above). **The actual move (`archive_unused_content()`/`_archive_files()`,
  and the GUI button itself) was not exercised** -- no files in the real
  `media/`/`slides/` folders were moved during this work; only the
  detection logic was run, read-only, against real data. Try the button
  directly to confirm the moving half before trusting it on a folder you
  care about.
- GUI launched and screenshotted (via a PowerShell `System.Drawing`
  screen-capture, since there's no browser-based way to inspect a native
  Tkinter window here) -- table renders with the right tabs/columns.
- Whole-deck compile of `test.tex`: PASS, `pdf/test.pdf` produced,
  `.build/test.*` cleaned up, no leftover wrapper file.
- Per-chapter compile of `t-Uni-IA2-2026w-preview.tex`'s one chapter:
  PASS, resulting PDF opens starting directly with the section-divider
  slide (no front matter), footer/logo/colors all correct, biblatex
  citation rendered correctly on page 2.
- Archive-refusal path: a duplicate of `test-mci.tex` correctly raises
  (sibling dependency).
- Archive-success path: a duplicate of `t-Uni-IA2-2026w-preview.tex`
  (self-contained, uses biblatex + version override) archived cleanly,
  fixups verified by grepping the moved file, then compiled from
  `decks/archive/` -- PASS, citations resolved correctly (this is what
  caught the `\IfFileExists`-cascade bug above; the first attempt at this
  exact test is what failed and led to the fix).
