# SlideMage

A PySide6 (Qt) app for compiling, editing and archiving this project's `decks/`
and `slides/`: since 6.0 one workspace window per open deck, with an AI assistant
(it was a Tkinter GUI until 2026-08 and a window of tabs and tables until 6.0). This file is the "what and why" for future
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
or the workflow stops -- the update check below compares the two. The
release notes are built by `packaging/release_notes.py` from the history
entries of every version since the previous release: their `NEW:` bullets
(what users get), then their `BREAKING:` paragraphs and a changelog link.
It stops the workflow when a version lacks a `NEW:` paragraph, or when the
major number goes up without a `BREAKING:` paragraph.

On Linux, `SlideMage-linux.zip` also bundles `icon.svg` and
`slidemage.desktop.template` next to the binary -- unzip the release to
one folder and see that template's own header for the one-line `sed`
command that turns it into a real GNOME/KDE app-grid entry (PyInstaller
doesn't embed an icon into a Linux binary the way it does on
Windows/macOS, so a desktop entry needs its own icon file alongside it).

It opens the project given by `--project`,
`$SLIDEMASTER_PROJECT`, the nearest folder above the current directory
that holds `slide_ids.csv`, or the last project opened, else it asks.
The window is one workspace for the deck that is open (the last one used, else the
deck switcher offers the rest). From top to bottom and left to right:

- **Top bar** (`ui/workspace/topbar.py`, menus in `menus.py`): the **deck switcher**
  (active decks under their group headings, archived decks at the foot), *View as*
  **Instructor / During course / After course** and **EN / DE** (the version and language
  the Preview shows and the slide list judges "hidden" and "no DE" by), the save state,
  **Preview | Split | Source | Details**, the **Compile PDF** split button, and
  the **⋮** menu (one popover in two columns, *This deck* | *Project, Housekeeping, Info*, with Settings… in
  its footer -- what the old menu bar and the deck table's per-row buttons held; the rest, such as the
  column toggles, Import, Refresh, Log, Open latest PDF and Exit, is in `Ctrl+K`).
- **Compile PDF** compiles the deck for the view chosen in the top bar; its arrow lists
  every version the old deck table's checkboxes made (Instructor, During course, After
  course, *All views*, *After course, one PDF per chapter*, *Presenter*), the pages of the
  selected slides, *Pages by number…*, *Several decks…*, *All decks except archive*, the
  accessible transcripts, *Stop compilation* and *Build options…* (appendix TOC, pages replace theirs, auto-open). Runs show as a floating **card** (one
  line per job with its state, a progress bar, Stop, *Retry failed*, *Open PDFs*); the
  **log drawer** (Ctrl+L) streams the `latexmk` output and opens by itself on a failure,
  with *Open in Source* on the failed line. Compiles still run on background threads, one job
  at a time, and one job failing doesn't stop the rest.
- **Left, the slide list** (`slide_list.py`, `slide_tree.py`; backend `deck_outline.py`):
  the deck's slides in sections, with thumbnails, status notes and the call variant;
  find-as-you-type, drag and drop, multi-select with a bulk bar, undo, right-click menus.
  Every edit goes through `deck_editor` and rescans the decks.
- **Centre** (`centre.py`): **Preview** (`preview_view.py`), **Source** (`source_view.py`
  on a `SourceEditor`, today the `LatexPlainTextEdit` of `source_editor.py`, with the lint
  line, Insert, Cite, Tools and the conflict bar when a file changes on disk under edits
  that are not yet written; edits are autosaved, 1.5 s after the last keystroke), **Split**, **Details** (`details_view.py`), and the **Images page**
  (`ui/pages/images.py`) as a sibling that replaces the columns.
- **Right, upper:** one **side panel** (`side_panels.py`, `panels/`): Used in decks, Slide
  versions, Visibility, Citations, Language, Image descriptions, Transcript entry, Speaker
  notes. **Lower:** the **assistant card** (`assistant.py`; 360 px column, the panels take 38 %
  and give way first, "Focus assistant" hides them): a header with the route, the scope
  (This slide | Whole deck), at most two task buttons and the running task, and a body that
  follows the AI switch: the native chat (`chat/`) on Local and Cloud · API, the real terminal
  (`terminal/`) on Cloud · Claude Code. A task on one slide takes the body's place with its
  **task card** (`task_card.py`; its state is `task_card_model.TaskCard`, owned by
  `terminal/tasks.py:TaskRunner`): Generate → Review → Apply → Check preview, or
  Conflict / Preview failed / Stopped / Setup needed; Back to conversation leaves a pill
  in the header. Batches, image tasks and the summary use the task row (`task_row.py`).
- **Compare rendered** (v8.13.0, `compare_rendered.py`): a non-modal dialog, not in the 360 px column, that typesets
  two texts of one slide as drafts for the same target, view and language as Check preview
  (`preview_view.render_context`) and shows "Before" and "After" in equal panes. Both go through a `RenderService` of
  the dialog's own (shared persistent preview cache and build locks; sources stay unchanged), each on a `QThread`
  that reuses validated reveal images or `preview_pages`' content-addressed PDF page cache; ‹ › and the
  arrow keys move both sides to the same reveal step (a side with fewer pages says "No page N"), a side that fails
  says why while the other is shown, *Text diff* swaps in the chat's `DiffCard`, Esc/Close cancels the pending
  renders. Opened from the task card (Review, Conflict: the proposal against the slide as it is now, Done), the
  chat's diff cards (slide files with a text before, not new files, .bib or others), and for Claude Code's edits
  and every other AI edit that went through `ai_review.mark(before=)`: the text before the last edit is kept per
  slide in `.slidemage/ai-before/` (`ai_review.last_before`; the hook's PostToolUse takes it from its PreToolUse
  snapshot), offered by the command `slide:compare` "Compare rendered with last AI edit" (palette, slide list menu) and by
  the Details view's *Not reviewed* row.
- **Readability check** (v8.14.0; `readability.py`, `readability_pdf.py`, `readability_check.py`,
  `ui/workspace/readability_panel.py`, the tool `ai/tools/readability.py`): "can an audience read this?", measured
  on the rendered pages, with no AI. `readability_pdf.read_pages` runs in the raster child (op `layout`; the GUI
  never opens the PDF): per page the visible text as lines (dominant size, colour, box; invisible text such as the
  slide-id stamp and alt text is dropped), the placed raster images, the opaque fills (the background under the
  text, the footer bar) and the vector figures (clusters of at least 12 paths). `readability.analyse` classifies
  each line (the footer and the id stamp are not content): **figure text** (centre inside an image or figure),
  **citation** (starts like a source or a footnote symbol of the template, or small print low on the slide or
  sideways, as `\source` sets it), **heading** (the title bar at the top, larger text in the upper third), else
  **body**; then applies the rules with the thresholds of the frozen `Thresholds` (all sizes are % of the slide
  height, quoted as pt for a 7.5 in slide): body ≥ 3.3 %, heading ≥ 3.3 % and not below the slide's body, citation ≥ 2.2 %,
  figure text ≥ 2.6 % (error below, warning within 5 % above); the largest image of a slide under 25 % of its area,
  or under 35 % of its width unless it fills 75 % of the height, is a warning (images under 3 % and backgrounds
  over 80 % are not judged); contrast under WCAG 4.5:1 (3:1 for headings and text from 5 %); clipped text and
  overlapping lines are errors; more than 90 words or 14 lines of body text and lines closer than 1.0 × the font
  size are warnings. A slide's last page of a run of pages with one footer slide id is judged (the rule of the slide
  snapshots, `slide_snapshot.slide_runs`), earlier pages only for clipped text. A `Finding` carries the page, slide,
  file, rule, class, severity, measured value and threshold, the box (fractions of the page), an excerpt or the image
  file (matched by pixel size to the `\includegraphics` of the slide) and a suggestion; `Report.to_text()` is what the
  tool returns and `Report.to_dict()` the JSON for the "Make readable" step. "This slide" renders a draft through a
  `RenderService` (view and language of the top bar); "this deck" reads the PDF of the compile record
  (`compile_records.check_record(record, None)`: the PDF and every file the compile read must be unchanged) and never
  compiles by itself: the panel offers *Compile the deck first*, which runs the normal compile and the check when it
  ends. The panel (`ReadabilityPanel`) takes the conversation's place until *Back to conversation*; the header offers
  *Check readability* when no AI task is on show, and Ctrl+K has `slide:readability` and `deck:readability`.
  **Template-level findings** (v8.15.0): `readability_check._mark_template_level` sets `Finding.template_level` on the
  citation-class text-size findings of a slide whose source (the draft for a slide check, else the file) sets no
  font size (`\tiny`, `\scriptsize`, `\footnotesize`, `\small`, `\normalsize`, `\large` ... , `\fontsize` or the
  matching environment, outside comments): such a size is the template's (`\setbeamerfont{footnote}` in the
  preamble), the same on every slide, and a slide cannot change it without overriding the template. The panel
  shows them "set by the template" with a hint (`TEMPLATE_HINT`), `to_text` says so, `SlideReport.fixable` leaves
  them out, and so does the Make readable request.
- **Make readable** (v8.15.0; `claude_tasks.READABLE`, `ai/provider_tasks.py`, `readability_check.KnownFindings`,
  `terminal/tasks.py`, `task_card_model.Readable`): the task on one slide, a FIXES-kind task on every route. The
  answer is `{"body": <the whole new source>, "note": <optional>}`: a whole-slide relayout (columns, widths, sizes,
  nesting) is not expressible as unique `before` pieces, and `body` goes through the same check as the other body
  tasks (protected parts unchanged, no new lint error); `note` is the model's remark, shown on the card, which is
  where it says that the slide cannot be made readable without losing content and how to split it (the body then is
  the best layout, or the unchanged source: Done with "Nothing to change" and the note). The request
  (`claude_tasks.readable_request`) carries the slide source, the floors in points for the slide's page, and the
  findings the slide can fix (`Report.to_dict(fixable_only=True)`) with the thresholds in their units. The findings
  come from `KnownFindings` (the window's `readability_known`): every check of the panel and every Make readable
  measurement stores its report for exactly the text it measured, so an edit forgets it, the header's button
  (offered when that text has errors) never runs a check to decide, and Run again sends what remained. On Claude Code
  the task is `claude_runner.run_task`; on Local and Cloud · API `provider_tasks.run_task` sends the rules as the
  system prompt and the schema as `schema=` (Ollama `format`, the API's system prompt), parses the reply
  (`parse_json_object`, also from `thinking`), judges it with the same `claude_runner.judge` and gives a bad reply one
  repair round (`repair_request`); a reply cut off at the token limit fails at once. The worker measures the proposed
  text as a draft (`readability_check.check_slide`) before the card reaches Review, which says "After the change: 0
  errors, 1 warning (was 4 errors)"; the written text is that same text, so the Check preview renders the slide as
  usual and Done reuses the numbers ("Now readable: ...; Still below the floor: ..."). Cut-off or overlapping text
  after the change (`task_card_model.FIT_RULES`) ends the card in Overflow (Undo, Run again), also when the preview
  step was stopped. The assistant agent has no tool of its own: its guide says to check, `modify_slide`, and check again.
- **Rewrite selection and Proofread selection** (v8.17.0; `claude_tasks.REWRITE` and `PROOFREAD_SELECTION`, `selection.py`,
  `terminal/tasks.py` `_capture_selection`, `ui/workspace/selection_tasks.py`; step R1 of the Claude Code reviews plan):
  tasks on the text selected in the Source view's slide, both FIXES-kind tasks on every route (Claude Code,
  `provider_tasks.run_task` on Local and the API) and task cards like the other single-slide tasks. The selection is
  captured when the button is clicked (`SourcePane.selection()` -> `selection.capture`: the file, its whole text and the
  range as Python offsets, since Qt counts UTF-16 units): a blank selection, a frozen version and a selection that
  touches a protected part (`protected_regions.protected_spans`: the header comment, `\setSlideVersion`, a `\vbox to 0pt`
  block) are refused with a message, nothing sent. The request carries the instruction, 800 characters of context on
  either side (`<before>`, `<after>`, never returned) and the selection between `<selection>` tags. **Rewrite** answers
  `{"text": ...}`, the replacement for the selection only (the whitespace at its ends is kept by the check); its
  instruction is chosen before generation: Simplify, Shorten (`REWRITE_PRESETS`) or Custom..., which asks in a popover
  (`InstructionPopover`); the LaTeX commands, math, labels, citations and overlays stay unless the instruction is about
  them. **Proofread selection** answers an edit list `{"edits": [{"before", "after"}]}`, each `before` occurring exactly
  once in the selection (chosen over a text answer because it cannot rewrite beyond the fixes, and an empty list means
  nothing to fix). `claude_tasks.check(..., span=(start, end))` runs the answer on that range of the whole file: the
  result is the file with only the range replaced (every character outside it is the captured one), the protected
  parts and the lint errors are those of the whole file, and the repair round is the usual one. Review shows the diff
  in the file's context and Compare rendered; Apply writes through `write_text` into the editor buffer (one undo step:
  Ctrl+Z and the card's Undo work), and the card ends in Conflict, keeping the proposal, if the buffer is no longer
  the captured text. Entry points: the Source editor's context menu (Undo ... Select all, then Rewrite selection with
  Simplify / Shorten / Custom... and Proofread selection, enabled when the selection can be worked on), the assistant
  header's two buttons while there is a selection (they come first in `PRIORITY`, so they replace the slide tasks in
  the two places; the rewrite button opens the Simplify / Shorten / Custom... menu under the selection), the palette
  commands `selection:rewrite` (Ctrl+Shift+R), `selection:rewrite:<choice>` and `selection:proofread` (enabled with a
  selection only). The terminal has a read-only MCP tool `read_selection` (path, range, text, context).
- **Keyboard and screen readers** (workspace v6 step 7): the AI switch is a radio group with a single tab stop
  (the selected segment; **←/→** flip Local and Cloud, **Enter**/**Space** activate, then Tab reaches ▾); its popups
  open on their safe button, **Tab** goes secondary, primary, link and round again, **Esc** is the secondary button
  and the focus goes back to the switch; AI setup goes through its cells in reading order and **Esc** returns to the
  ▾. A task card takes the focus on its first action. The kit's buttons and segmented controls show a 2px blue focus
  ring for the keyboard only. `kit.widgets.announce(widget, text)` is the one live-region helper (the switch commit
  and "stopping…", the task card's phase text, the end of an image batch, AI setup's confirmations); the dialogs
  that run or configure AI show the route as a `ModeBadge` under their title (`ai_models.add_route_badge`).
- **Top bar Tab order** (v8.15.1): Tab (Shift+Tab) follows the bar from left to right -- ⇤ slide list, deck switcher,
  the AI switch, View as, EN | DE, Preview | Split | Source | Details, Compile PDF and its ▾, Close images (when the
  Images page is open), ⋮, ⇥ -- and goes on into the slide list, the centre and the assistant (`TopBar._set_tab_order`).
  A segmented control is one stop (**←/→** change it); the deck switcher opens on the current deck with **Enter**,
  **Space** or **↓**, and **Esc** returns to it.
- **Ctrl+K**: the command palette (`palette.py`, commands in `actions.py`); every menu
  entry is a registered command.
- Dialogs are kit **sheets** (`ui/dialogs/`): Add slide, Open project, Settings, Deck
  settings (with Admin slides), Housekeeping, Snapshots, Tags, Import PPTX/ODP, About and
  the project-compatibility sheets.

Archiving a deck (see below) asks for confirmation before moving anything; so do the
Housekeeping tools that empty `pdf/` or `.build/` (refused mid-compile, since a running
compile could still need a file) and **Archive unused slides and media files** (see
`unused_content.py` below for what it scans).

It replaces things that were previously manual: hand-editing the `DECKS=`
line in `compile-all.bat`/`compile-all-versions.bat`, hand-crafting a
one-off wrapper file to get a per-chapter PDF during PPTX conversion
review, and manually eyeballing `media/`/`slides/` for files nothing
references anymore. It also adds two things that didn't exist before at
all: archiving a finished course's deck out of `decks/` while keeping it
compilable, and archiving unreferenced `media/`/`slides/` files out of the
way without deleting them.

## Updates

**⋮ → Info → Check for updates…** compares this copy's version with the
releases of `stpalan/SlideMage` on GitHub. When a newer one
exists, the packaged app offers to download that platform's release zip,
unpacks it into the folder the running app lives in, and restarts. The
old binary is kept as `SlideMage.old` (`SlideMage.exe.old` on Windows)
until the next start deletes it. A copy running from source only reports
the new version -- update it with `git pull`.

Since v4.1.0 the packaged app also checks by itself, three seconds after
it starts, as chosen under **⋮ → Settings… → General → Updates**:
*Don't check for updates*, *Check for updates and ask before installing*
(the default; the question also offers "Always install automatically" and
"Stop checking for updates") or *Check for updates and install them
automatically* (still asks before restarting). The choice is stored per
user and machine, in `update_mode` next to `github_token` below. The check
runs on a background thread; a failure or an up-to-date copy only goes to
the log. A release that breaks with the past -- a paragraph starting
`BREAKING:` in its notes, or a higher major number -- is always asked
about, even in automatic mode, with its `BREAKING:` paragraphs shown and
the choice to install it anyway, stay on the current major version (the
newest release before the first breaking one) or wait. Every release
between the running version and the newest counts, so skipping over a
breaking release to a later one is still asked about
(`updater.plan_update()`). See the README's "Releases and updates" for the
marker convention and the project format guard
(`.slidemage/project.json`).

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
2. **Add it in SlideMage.** ⋮ → Settings… → General → Updates:
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

## Images page

Since 6.0 a full-window page (`ui/pages/images.py`; opened by ⋮ → Project → *Image descriptions*, `Ctrl+K`, or a slide
row's *Images* entry, and closed by the top bar's **Close images** button) that
replaces the workspace's columns -- before, the third permanent tab (added 2026-08-14,
labelled "Image descriptions" until 2026-08-15). It is where every image in the
project gets described for screen-reader users. The design, the decisions and the
measured findings are in `ALT_TEXT_NOTES.md` (not part of this copy); the
user-facing workflow is in the main README's "Describing images" section.
What matters when touching *this code*:

- **The page's first scan is deferred** until it is actually opened
  (`ensure_loaded()`). That scan walks every slide, hashes the bytes of every image they
  reference, and *writes* new rows to `media/alt-text.json` -- none of which
  belongs in the startup path of an app usually opened to compile a deck.
- **What a form means for the store is `image_review.py`'s** (filters, ordering,
  `FormEdit`, `save_slide_forms`, `copy_into_media`, `repoint_slides`, ...): no Qt, so the
  page (`images.py`, with `image_nav.py` for the left column, `image_form.py`,
  `image_preview.py`, `image_dialogs.py` for *Replace image* and *Tune prompt*) only
  draws it. The page is slide-centric (the left column lists the slides that show
  images, with their review state); `repoint_slides` refuses slides with Source
  edits.
- **Drafting and batch runs happen on a worker thread** (`image_runs.py`'s
  `ImageRunsMixin`, `image_jobs.py`'s `Job`/`JobCard`; one job at a time, Stop works at
  once on a single image) and come back over a `Signal`. The thread holds the Ollama
  slot (`try_start_ollama_task`) -- a cloud model needs none. One image takes 10-60s;
  a full batch takes hours. Use `ui/background.stop_worker` for any new worker thread.
- **A batch captures its route when it starts and ends in a results panel.** `Job.route` is the Route of the picker
  at the click (`ai_profile.resolve`), and the backend is built from it once (`image_jobs.draft_job` /
  `translate_job`), so the AI switch moving mid-run changes nothing about it; its progress line reads "Image 2 of 4 ·
  file · route". `alt_draft.run_batch` / `run_translation_batch` settle every image as an `ItemOutcome`
  (`batch_result.py`: done, kept, failed, cancelled); a run that ends, is stopped or is cancelled by *Stop and switch*
  turns them into a `BatchResult` that `image_results.BatchResultView` shows (title "partly done" or "done", the
  route, a summary, a row per image, **Retry failed (n)** and Close). The same widget serves the assistant's image
  tasks (`TaskRunner.result`, `retry_failed`). The question before a batch, `image_results.question`, names the model,
  on Cloud what is sent and the time. The buttons that send content say "· cloud" on Cloud (`ai_models.cloud_label`).
- **Drafts are written to the shared store per image as they finish**, not
  buffered to the end, and the batch queue is *derived* from the store and
  the slide files rather than kept anywhere of its own -- which is what
  makes it resumable across sessions with no job state to corrupt.
- **A running batch must not overwrite an image the user reviewed or edited mid-run (it keeps the person's text and
  reports "kept"; the check compares the entry with the text the queue saw at the start),
  and two writers (the batch thread, the GUI thread's own saves) must not
  interleave and lose each other's change to the one shared JSON file.**
  `alt_images.update_store()` closes both: it holds a process-wide lock for
  the whole load-check-save round trip, and the "is this still safe to
  write" check re-reads the store fresh rather than trusting whatever the
  batch queue looked like when it started. Getting the file-scoped version
  of this wrong once already caused a save to land in the wrong slide's
  file; see ALT_TEXT_NOTES.md.
- **Modal dialogs block forever under `QT_QPA_PLATFORM=offscreen`**, with no
  one to click them. Any GUI test here must stub `QMessageBox` and the kit sheets'
  `exec()`, and run Python with `-u`; the first attempt hung silently with no output
  at all. (`tools/manual/make_screenshots.py` shows and grabs sheets instead.)
- **The page is only for image descriptions -- a slide's transcript
  *summary* and its compile-time *preview* are edited elsewhere** (the Transcript
  entry panel, `preview_view.py`), deliberately: the page's own slide list only
  shows slides that reference at least one image (the whole point of the
  list), and both of those features need to work for *any* slide. They
  still share the page's underlying store and lock (`alt_images.py`,
  `slide_snapshot.py`) -- see those modules' own entries in the module map
  below. The Image descriptions *panel* and the page are the only writers of the
  image forms. Both show the citation field (`image_form.SOURCE_SPECS`,
  `labelled_edit()`, `SourceStatus`: the same label, placeholder, review
  badge and *Mark reviewed*; the panel shows the language of the top bar).
  They are never visible together: `WorkspaceWindow._on_page_changed` saves the
  panel's pending edit when the page opens (`ensure_loaded()` reads the store
  again) and refreshes the panel when the page is left.
- **A hand-drawn tikz illustration (`\tikzillustration{ID}`,
  Slidemaster_preamble_base.tex) shows up in this same per-slide list as a
  synthetic `tikz:ID` reference (2026-09-07)** -- see ALT_TEXT_NOTES.md's
  own "Phase 9" section for the full design. It has no file on disk at
  all, so the page's own preview panel and the drafting pipeline's image
  resolution are the only two places with a tikz-specific branch
  (`tikz_render.py`, below); every other piece of the page (role choice,
  short/long/takeaway/source fields, Draft/Tune prompt) is built generically
  from `(reference, ImageEntry)` and needed no changes at all.
- The transcript preview (`ui/dialogs/transcript_preview.py`,
  `show_transcript_preview()`) is a sheet over the window, from the page's header and
  the Preview's *Render ▾*.

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
  schema/UI landed before the compile-time half. The citation has its own
  review state (v8.12.0, `source_status`, `SOURCE_TO_REVIEW` /
  `SOURCE_REVIEWED`, one state for `source` and `source_de` together):
  `flag_source_change()` is the one rule (a changed source or source_de is
  to review), `set_source()` / `save_source()` apply it to an entry in memory
  / in the store (the Images page's form via `image_review.apply_form_edit`,
  the side panel, the bundled-manual merge), `mark_source_reviewed()` is the
  only way back, and `flag_edited_sources()` applies it to a store file
  written as a file (the chat's `edit_file` / `write_file` and the Claude
  Code hook compare it with the text before the write). It is written to the
  JSON only when `to_review`, so an older store loads as reviewed (and an
  empty source has nothing to review: `source_state()`); the compile CSV
  does not carry it. The Images page's counts and "Needs attention" ignore it;
  the filter "Source to review" lists the slides. Replaced two former
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
  Transcript entry panel, not the Images page -- a summary makes sense for
  a slide with no images at all, which the Images page's list never shows.
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
  they *internally* feed (`\SMChapterLogoPath`, `#3`) is itself
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
  text-only) backs the Images page's own "Translate with" picker.
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
  say" fact for the slide list, the Add slide sheet and the Source view to each
  render in their own widget style --
  `both` (own language *and* a cross-referenced translation into a
  *different* language) is the case meant to be visually highlighted. A
  slide with no language segment at all (any of the ~665 not yet migrated)
  parses to `None` and shows no badge -- no forced migration.
  Where a new translation is called in a deck is `slide_add.translation_call()` /
  `translation_spec()` (v8.16.0): directly after the **first** call of its source (one
  call, because `deck_language` folds a separately listed partner into the original's
  slot and resolves it for every repeat of the source), called the way the source is
  (`PARTNER_MACROS` as `resolve_call`: same views and reveal steps, a pinned version
  becomes `\slide`). The `add_slide` / `create_slide` agent tools (an explicit `after`
  wins), the task card's and the batch's Translate and the Add slide sheet (a translation
  of another slide than the one it was opened for) all use it; a source the deck does not
  call keeps the old place (the end of the deck, or where the sheet was opened).
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
  after a rename, automatically after the Add slide sheet's "Translate"
  flow, and as **⋮ → Housekeeping… → Reestablish broken translation
  links** (a plain toolbar button until 2026-08-25) for running by hand
  any time.
- [`translation_prompts.py`](../src/slidemage/translation_prompts.py) -- per-(model, source
  language, target language) prompt configuration for
  `alt_draft.OllamaTranslationBackend`, editable from **⋮ → Settings…
  → Prompts** (`ui/dialogs/settings_prompts.py`). Different
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
- [`compile_progress.py`](../src/slidemage/compile_progress.py) -- the progress bar of the compile card
  (2026-09-27: the thin blue bar at the top edge of the log).
  `BatchProgress.feed(line)` is called by the workspace's compile jobs
  (`ui/workspace/compile_jobs.py`) for every log line: pass K comes from `Run number K of rule 'lualatex'`, the position inside
  the pass from the `(…/slides/<id>-…` lines LaTeX prints when it starts reading
  a slide file. `fraction = ((pass-1) + slides_seen/slides_total) / passes`, with
  4 passes for a deck that uses biblatex and 3 without; held at 99% until the job
  really finishes. A pass beyond the expected count raises the count (since v5.20.0
  the label reads "pass 5/5", not "(extra pass 5)"); the bar never moves backwards. Slide totals use the same
  scoping as the syntax check (version/chapter filters, `\input` fragments). A
  queue is one bar, each job weighted by passes × slides. It also covers
  single-slide renders (3 passes, 1 slide; a buffer render has no slide file to
  read, so it moves per pass), Update previews (one 4-pass megadeck per template)
  and Export PPTX; a job of unknown size shows the busy animation. The status
  label shows e.g. "pass 2/4, slide 137/395".
- [`ui/dialogs/settings.py`](../src/slidemage/ui/dialogs/settings.py) -- the **⋮ → Settings…**
  sheet (step 9c of the redesign; first a Preferences dialog, 2026-08-25). Tabs:
  **General** (dark mode, the Source editor's tab width, the template single slides render
  with, and the **Updates** group -- since v4.1.0 the update mode and the GitHub token for
  update checks, both stored per user in `project.config_dir()`, never in the project
  folder), **AI** (the German address of Claude Code translations; the
  default model of each task, what Cloud means and the project's Local | Cloud setting are
  **AI setup**, the ▾ of the AI switch in the top bar, `ui/workspace/ai_setup.py`: every
  model picker lists the models of the route in use and preselects its default, picking
  another there applies to that use only; the local chat lists only models that can call
  tools, local image descriptions only vision models; Claude Code chat saves a model and
  effort used on the next start or Restart, or inherits **Claude Code default**), **Cloud** (the Anthropic API key
  with where it is stored), **Ollama**
  (`settings_ollama.py`: the host URL and the installed models, update and delete) and
  **Prompts** (`settings_prompts.py`: the editable system prompt of image descriptions,
  stored by `draft_prompts.py`, and the translation prompts of `translation_prompts.py`:
  a "Default prompt" group plus per-(model, source, target) overrides, the model combo
  filled from `alt_draft.list_all_models()` and editable, so a not-yet-installed model
  can be pre-configured). Every control saves when it changes; only a prompt has its own
  Save button, and closing the sheet asks about prompt text not yet saved. The installed
  models load on a thread (`OllamaProvider`), so opening the sheet never waits on the
  network; the window refreshes the open pickers when the sheet closes. The
  "Slide rewrite" prompt page and the "AI drafting" model went away with the old AI draft
  dialog: whole-slide changes are the chat's job now (`ai/`, below).
- [`ui/dialogs/housekeeping.py`](../src/slidemage/ui/dialogs/housekeeping.py) --
  the **Housekeeping…** sheet and the *Archive unused slides and media files* sheet
  (2026-09-27, direct instruction, after a real batch run archived far more than expected --
  see `unused_content.py`'s own entry below for the two bugs that caused it): lists every
  file `find_unused_media()`/`find_unused_slides()` found, with unticking, Cancel (the
  default) or "Archive N file(s)"; the scans run before the sheet opens and the move runs
  on a thread.
- [`transcript.py`](../src/slidemage/transcript.py) -- per-deck accessible transcripts,
  Markdown source and HTML delivery. Resolves deck versions exactly as the
  PDF compile does and keeps PDF slide numbering. Student versions only.
  Colour commands are dropped with their colour arguments, keeping the
  text (`_COLOR_COMMAND_RE`, v4.1.0; the colour name used to end up glued
  to the text, e.g. "c_primary_highlightdata dredging").
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
  that never got to run its compiles. Wired into the Housekeeping
  commands (*Update slide previews*), reusing the same `self.compiling` busy-state machine (detached thread,
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
  this ad-hoc job never goes through. Project-wide `run()` waits for
  `run_job()`'s background PDF relocation and prunes unused legacy snapshots.
  Deck-scoped `rerender_deck()` uses `deck_preview_refresh` and the shared
  scheduler/cache instead, retaining exact occurrence/view outcomes in
  `DeckResult.details`. The deck UI and `refresh_deck_previews` use this same
  path with all/selected-view scope; `refresh_preview` uses the common per-slide
  batch path. Compatible Instructor results still publish legacy snapshots.
- [`ui/workspace/preview_view.py`](../src/slidemage/ui/workspace/preview_view.py) -- the
  Preview view (the redesign's replacement of the old preview popup and the deck editor's
  List / Thumbnail / Grid views, hover tooltip and chapter dropdown, all gone): the
  matching verified whole-slide image of the focused occurrence and selected view,
  with explicit previous-render or shared Instructor-reference fallback and chips for what it is not showing (`preview_target.py`, `deck_outline`
  facts: pinned version, language, missing translation, hidden in this view; the language
  chip of a slide with a translation partner reads "EN + DE" and is a button (Tab stop,
  Enter or Space, tooltip "Go to the German version" / "Go to the English original") that
  shows the partner file for this one slide, in the deck's theme and typeset in its own
  language, while the top bar's language and the mode stay, and back) and
  content-based freshness (including dependencies and unchanged version markers;
  previous matching images remain visible with an old-preview label). **Render** compiles the saved slide; its menu renders the editor
  buffer instead (Ctrl+Enter, or Ctrl+R in the Source view: whole slide, selection as frame or element, one reveal step),
  a presenter PDF or a transcript. The slide list's thumbnails now use the same verified
  final whole-slide image for the selected view and source/deck identity. Older matching
  renders and shared Instructor references are labelled; region and individual-step
  previews can intentionally differ. See [Thumbnail and Preview consistency](PREVIEW_THUMBNAILS.md).
  Single-slide renders run on a worker thread through
  `preview_build.py`'s cached latexmk graph (see "Interactive preview builds" in the
  README).
- [`deck_duplicate.py`](../src/slidemage/deck_duplicate.py) -- **Duplicate deck…** (⋮ menu, *This deck*). A plain `shutil.copy2` under a new filename stem, no
  content rewriting needed (unlike `archive.py`'s `archive_deck()`): a
  deck's name is derived purely from its filename, never embedded in the
  `.tex` content itself. `is_valid_deck_name()` is exposed separately from
  `duplicate_deck()` so the caller can show a validation reason directly
  in the UI before attempting anything, rather than parsing an exception
  message; `duplicate_deck()` re-checks it anyway rather than trusting the
  caller blindly.
- [`slide_versioning.py`](../src/slidemage/slide_versioning.py) -- the freeze-then-bump
  workflow behind saving a slide's `current.tex` and the Source view's **Update version**
  button (2026-08-20, reworked 2026-10-15 for autosave). Pure logic, no Qt. The version line
  is `\setSlideVersion{X-Y-Z}`, or `{X-Y-Z+}` for "changed since X.Y.Z" (`parse_marker()`,
  `set_marker()`). `save_slide()` is every write of a current file (autosave, Ctrl+S):
  `prepare_autosave()` first freezes the file on disk as its version when that version is not
  frozen yet (`freeze_slide()`, a plain `shutil.copy2`, `None` if already frozen, so history is
  never clobbered), and the written text gets the "+". `update_version()` / `plan_update()`
  turn a major / minor / patch choice into the new number (never one that is frozen already),
  write it without "+" and freeze it; `restore_version()` freezes a "+" slide's content as the
  next patch before restoring. `ui/workspace/source_file.py`'s `prompt_version_level()` is the
  only place that shows a prompt (the Slide versions panel's *Freeze as vX.Y.Z* calls
  `freeze_current()` directly). `SourceFile.write_now()` is the autosave (1.5 s debounce, also on
  file switch, compile and close), paused while the buffer is read-only, in conflict with a
  change on disk or under an AI fix (`SourceFile.blocked`).
  `\slideversion{ID-slug}{X-Y-Z}` reads the version from its own second
  argument, never from a frozen file's content -- so frozen files
  themselves never need a `\setSlideVersion{}` of their own, and this
  module never writes one.
- [`bibliography.py`](../src/slidemage/bibliography.py) -- a small BibTeX reader so citations
  in transcripts read as references rather than keys. Hand-written rather
  than a dependency because this project declares exactly one and the data
  is well behaved (89 entries, no `crossref`, no `@string`).
- [`ui/dialogs/transcript_preview.py`](../src/slidemage/ui/dialogs/transcript_preview.py) --
  the sheet that shows one slide's transcript entry (`generate_single_slide()` and
  `to_html()`); the deck-wide transcripts are built from the Compile menu.
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
  and media files** (`ui/dialogs/housekeeping.py`) now runs both scans up front and shows
  every file in a sheet before moving anything -- Cancel
  (the default button) leaves the folders untouched, "Archive N file(s)"
  is the only action that starts the actual move.
- **The `ui/` package** (everything with Qt; there is no `qt_*` module any more; the
  application starts in `ui/app.py`'s `main()`):
  - `ui/kit/` -- the widget kit and the look: `tokens.py` (light and dark tokens), `kit_qss.py`,
    `theme.py` (`ThemeManager`), `fonts.py` (Roboto, Roboto Mono and Material Icons from
    `assets/fonts/`, loaded at start-up), `widgets.py` (SegmentedControl, Chip, ToggleChip, SplitButton,
    IconButton, Button, PopoverMenu, Popover, Toast, Card, ModalSheet, Field, Page,
    ThumbnailGrid, ...); `python -m slidemage.ui.kit.gallery` shows them all.
  - `ui/commands.py` -- `Command`, `CommandRegistry`, `bind_shortcuts`; the ~95 commands
    are registered in `ui/workspace/actions.py` (`build_registry()`), and the menus in
    `menus.py` are lists of command ids (the ⋮ menu's two columns and footer are `MORE_COLUMNS`, drawn by
    `PopoverMenu.add_column()`/`add_footer()`), so the top bar, the ⋮ menu, the context menus and the
    palette share one definition (`slide:*`, `section:*`, `compile:*`, ...). A new feature
    registers its command there.
  - `ui/workspace/` -- `window.py` (`WorkspaceWindow`) with `state.py` (`WorkspaceState`: the
    deck, focused and selected slides, view, language, mode, lint state), the top bar, the
    mixins `compile_jobs.py` (`CompileSignals` and all compile orchestration), `deck_actions.py`,
    `maintenance.py` and `multi_compile.py`, the floating `job_panel.py` and `log_drawer.py`,
    `render_check.py` (the pre-render lint sheet), and the views listed under "What it does".
  - `ui/dialogs/`, `ui/pages/` -- the sheets and full-window pages (`ui/pages/no_decks.py`
    for a project without decks); `ui/background.py` has `start_detached` and `stop_worker` for
    threads that must not outlive the window.
  - `ui/workspace/chat/` -- the Chat view: `session.py` (`ChatSession`: the history and the
    agent thread), `view.py`, `cards.py` (text, tool and diff cards with Apply / Reject /
    Undo), `gui_workspace.py` (`GuiWorkspace`: runs the agent's workspace calls on the GUI
    thread and waits for them). The assistant card is `ui/workspace/assistant.py` (with
    `assistant_header.py` and `task_row.py`).
  - `ui/workspace/terminal/` -- the Claude Code body: xterm.js (vendored under
    `assets/terminal/`) in a `QWebEngineView` with a `QWebChannel`, on a pty
    (`pty_process.py`: `ptyprocess`, `pywinpty` on Windows). QtWebEngine is what makes the
    one-file build about 300 MB.
- **The `ai/` package** (no Qt): `providers.py` (`ChatProvider`, `OllamaProvider`,
  `AnthropicProvider`; both stream a tool-using turn, `ProviderError`, `Cancelled`),
  `ai_profile.py` (`resolve(ctx, task)`: the route and model of a request from the
  session's Local | Cloud mode, the cloud connection, the project's policy and the models
  per route and task; the once-per-project first-use flag), `resolver.py` (turns that
  Route into a provider or backend, or refuses it with "not available on <route>"), `credentials.py` (API key: environment, then the keychain
  through the optional `keyring`, then the settings file), `ollama_admin.py`; the agent
  (`agent.py`: `Agent(...).run()` on a worker thread, one per request, events in
  `agent_types.py`; `agent_context.py`: the fixed system prompt plus the per-request
  context; `workspace.py`: the `Workspace` the GUI implements; `guides.py`: the guides
  `read_guide` loads) and its tools (`tools/`: `read_file`, `find_files`, `search`,
  `edit_file`, `write_file`, `list_slides`, `lint`, `render_preview`, `add_slide`,
  `add_bib_entry`, `compile_deck`, `read_guide`, `refresh_preview`, `refresh_deck_previews`,
  `undo_edit`; the dot-folders and `pdf/` are
  invisible, edits that touch a protected region -- `protected_regions.py` -- or a frozen
  version are refused, a file open in a buffer is edited in the buffer). The Claude Code
  tab's side: `mcp_server.py` (a small MCP server on `http.server`, 127.0.0.1, bearer
  token: `get_focus`, `read_buffer`, `list_slides`, `lint`, `render_preview`,
  `refresh_preview`, `read_guide`, `add_slide`, `refresh_deck_previews`), `claude_launch.py` (finds `claude`, passes the MCP config, a
  PreToolUse hook and the system prompt; the child environment drops the API key
  variables so the user's own login is used), `claude_hook.py` (exit code 2 blocks an edit
  of a protected region or a frozen version; `python -m slidemage.ai.claude_hook`, or
  `<exe> --claude-hook` in the frozen app) and `project_watch.py` (a 1 s poll that lets
  the Source buffers notice files Claude Code changed).
- Task logic that is not UI stays in its modules: `ai_draft.py` (only
  `mask_protected_regions` now), `syntax_check.py`, `alt_draft.py` (image descriptions and
  translation backends), `image_review.py`, `slide_add.py`, `deck_outline.py`,
  `latex_edit.py`, `preview_target.py`, `snippets.py`, `compile_status.py`, `housekeeping.py`,
  `app_info.py`, `admin_slides.py`.

## GUI framework: PySide6 (Qt)

The app runs on PySide6 (`ui/`, with `ui/app.py` as the application start) --
`__main__.py` launches it. Since 6.0 the window is the workspace described under "What it
does"; the `qt_*` modules of the Tkinter migration are gone. The terminal tab needs
QtWebEngine (`PySide6-Addons`), which the PyInstaller spec bundles; QtWebEngine runs with
`--disable-gpu`. The app moved from Tkinter to Qt because of permanent ttk limitations
(no per-tab colors, no native tab scrolling, dark mode only working via a hand-rolled
widget-registration workaround); the original Tk implementation has since been removed. Install for development with `pip install -e ".[dev]"`
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
`compile_progress.py`'s `_MOVING_RE` for the job card, so that wiring
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
- The AI assistant (6.0): no chat history across sessions (New chat forgets
  the conversation, and so does closing the app); the Claude model list is the
  static `ANTHROPIC_FALLBACK_MODELS`, not the live list; every local model gets
  all the tools and the same system prompt, and a long conversation can outgrow
  the 16384-token window asked of Ollama (`providers.AGENT_NUM_CTX`) without a
  warning; a local model's "thinking" output is dropped, not shown.
- The Claude Code terminal (6.0): URLs in the terminal are not clickable; Windows
  (`pywinpty`, `claude.cmd`, the frozen hook's stdin) and macOS are untested.
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
  Tkinter window here) -- table renders with the right tabs/columns. (Since 6.0 the
  screenshots are made offscreen by `tools/manual/make_screenshots.py`; the 6.0
  one-file build was started on Linux with the example project, and
  `SlideMage --claude-hook` blocked a header edit and a frozen version.)
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

## Preview requests and optimization

The user workflow is described in README.md, “Preview views and reuse”.
`preview_equivalence` classifies supported rules before rendering. `RenderService`
shares equivalent images and matching in-flight requests while preserving each
consumer's view, saved/draft provenance and cancellation. Saved and identical
buffer requests execute the same captured-text wrapper and use one identity.
Presenter, region, element and overlay inputs remain distinct. Image equivalence
does not authorize substituting a view-specific PDF.

`preview_cache` stores immutable artifacts and content-based dependency evidence.
`preview_selection` supplies the same verified/previous/Instructor-reference policy
to both surfaces. `preview_thumbnails` and the pane validate off-thread with
revision guards. `preview_pages` reuses full sequence images when resolution
suffices, or caches additional PDF page ranges/resolutions for comparisons and
inspection tools. Cache-validation timings and bytes read are recorded separately
from LaTeX passes and raster jobs.

`deck_preview_refresh` resolves each occurrence/view, including translated and
pinned calls, before using the common batch scheduler. `rerender_deck` retains a
slide summary and exact results; the project-wide legacy snapshot pruning path
remains separate. `WorkspaceWindow.after_version_updates(paths)` refreshes rows
once, preserves selection, and applies the live-render policy without broadly
deleting caches belonging to unchanged pinned calls.

The completion evidence and reproduction commands are in
[Preview optimization validation](PREVIEW_RENDER_OPTIMIZATION_VALIDATION.md).
