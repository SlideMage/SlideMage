# Small UI todos: plan (13 October 2026)

Source: `docs/small_ui_todos.md`. Item 6 there (image source lookup by reverse image search) is left out for now.
Each step is one Sonnet agent, reviewed by the orchestrator, tested in full and committed with a version bump.
No step waits for approval.

| Step | Todo items | Version |
|---|---|---|
| S1 | Rerender all previews for this deck; agent tools to refresh one slide and one deck | v8.11.0 |
| S2 | Reference / citation box in the Image descriptions side panel; "To review" status for the source | v8.12.0 |
| S3 | Side-by-side rendered before / after for AI edits | v8.13.0 |
| S4a | Readability check: measure text and image sizes on rendered slides (UI action and agent tool) | v8.14.0 |
| S4b | Readability fix: enlarge text and images and re-lay out the slide until it fits | v8.15.0 |

## S1: Deck preview rerender and refresh tools
- `update_all_previews` gains a deck filter: its needed-slides list narrowed to one deck's slides, sharing the
  compile, prune and progress code. Pruning must not delete previews that other decks still need.
- UI action **Rerender all previews for this deck**: registered as a command (⌘K) and in the ⋮ menu's This deck
  column. It is distinct from the single-slide rerender and the project-wide Update slide previews.
- Agent tools (chat and MCP, `ai/tools/`):
  - `refresh_preview`: one slide, or the focused slide when none is given;
  - `refresh_deck_previews`: one deck, or the current deck.
  Both report which slides succeeded and which failed. The deck tool and the UI action share one implementation.

## S2: Image source in the side panel, with review status
- The Image descriptions side panel shows the Reference / citation (`source`, and `source_de` for German) with
  the same content and editing behaviour as the full image editor (`ui/pages/image_form.py`). One store, so both
  views stay in sync, including while both are open.
- A separate review status for the source: any change to `source` / `source_de`, by the user or by an agent
  (chat tool, Claude Code hook, image pipeline), marks it **To review** and clears its reviewed state. Both views
  show it and let the user mark it reviewed. It is stored in the alt-images store, and older stores without it
  load as reviewed, or as not reviewed if the source is empty.

## S3: Side-by-side rendered before / after
- One **Compare rendered** view that renders the slide's text before and after an AI edit through the shared
  RenderService (as drafts; nothing is written) and shows the two pages side by side, with overlay-step
  navigation, labels "Before" and "After", and a fallback message when one side fails to render.
- Entry points:
  - the task card (Review, Conflict, Done);
  - the chat's edit cards (DiffCard);
  - edits Claude Code makes in the terminal, where the hook or backup records the earlier text (find what
    `ai/claude_hook.py` and `ai_review` keep).
- This is a dialog or a full-width centre view, whichever the existing preview widgets make simplest; it is not
  squeezed into the 360 px assistant column.

## S4a: Readability check (measure)
- A pure measurement module that reads the rendered PDF of a slide or deck with MuPDF (in the raster child
  process, like the other MuPDF work). For every text span it reads the font size (scaled to the page),
  position and colour. For every placed image it reads the displayed size as a share of the slide.
- Classifies text as body, heading, citation/footnote (by position, size and the slide's source commands) or
  text inside figures (spans inside an image's area, e.g. vector PDF figures).
- Rules, with thresholds in one place and documented in the module's docstring:
  - minimum effective text size per class, relative to the slide height (so a projected slide is judged, not
    LaTeX point sizes), with a looser floor for citations and footnotes;
  - images too small to read, e.g. charts or figures with text below the floor, or a figure shown at a small
    share of the slide;
  - text clipped by or overlapping the page edge or other text;
  - low contrast against the background;
  - too much text on one slide.
- UI action: **Check readability** for this slide and for this deck (⌘K and the assistant's task buttons),
  showing the findings per slide (which text or image, measured size, threshold, suggestion), with a click
  taking you to the slide.
- Agent tool `check_readability` (slide or deck) returning the same findings as text.
- No AI in this step; it is deterministic.

## S4b: Readability fix (enlarge and re-lay out)
- A new AI task **Make readable** for one slide, run through the task card (Generate, Review, Apply, Check
  preview).
  - Its request carries the S4a findings and the slide source.
  - The model enlarges text and images and re-lays out the slide: columns, image width, spacing, trimming
    wording only where needed, and protected parts kept. It must still fit on one page. If it cannot fit, the
    answer says so and suggests splitting the slide.
- Check preview re-runs the S4a measurement on the new render. The card's Done state reports what is now
  readable and what is still below the floor; overfull or clipped output counts as a failure.
- Runs on every route through the resolver (Claude Code task, Local and API providers), with no fallback.
- Offered as a task button when S4a finds problems on the slide; for a deck, the S4a findings list offers
  Make readable per slide.

---

# Small UI todos, batch 2: continuous saving (14 October 2026)

Source: `docs/small_ui_todos.md`, "Continuous saving, like Overleaf".

How each step runs (from C3 on; C1 was done directly):
- Execution goes to one Sonnet 5.5 subagent at medium effort per step, given this plan's section for the step
  and the relevant files.
- The orchestrator (Opus) reviews the result: reads the diff, checks it against the plan and the "+" rules,
  fixes or sends back what is wrong, and runs the full test suite.
- The orchestrator commits with a version bump and a CHANGELOG.md entry, then stops and waits for the go.

| Step | What | Version |
|---|---|---|
| C1 | Autosave in the Source view, and "Update Version" in place of "Save" (one step: autosave breaks the old Save) | v8.18.0 |
| C3 | Retire the unsaved-state plumbing (close prompt, chips, "save first" checks) | v8.19.0 |
| C4 | Manual, screenshots, release notes | v8.19.1 |

What exists today: `SourceFile.save()` (`ui/workspace/source_file.py`) asks the bump level
(`prompt_version_choice`), freezes the *outgoing* on-disk text (`slide_versioning.freeze_slide`), asks what each
deck uses (`ask_deck_versions`), and writes with `save_slide_source(..., expected_text=...)`, which keeps a
backup and refuses stale files. The Versions panel has "Freeze as" (`CentreColumn.freeze_version` →
`slide_versioning.freeze_current`).

## The version line: "+" for edits since the last version
`\setSlideVersion{1-2-0+}` (footer "v1.2.0+") means "changed since 1.2.0". Without "+", the content is
version 1.2.0 itself. The preamble's `\setSlideVersion` already prints the "+" (it ends up in its third part).
- First autosave of a slide whose line has no "+": if that version is not frozen yet (every slide saved the
  old way, and slides with no version line, as 1.0.0), the file on disk is frozen as it first (what the old
  Save did, done lazily, so no migration). The written text gets the "+".
- **Update Version** (Source view button, and the Versions panel's "Freeze as"): asks major / minor / patch
  for the change since the last version, writes the line as the new version without "+", freezes the file as
  that version, asks what each deck uses; decks that keep the old content are pinned to the last version,
  which is frozen already. A slide without "+" whose version is not frozen yet is frozen as it is, no bump.
- Restore of a slide with "+": its content is first frozen as the next patch version, then restored.
- A version number is never reused: Update Version refuses when the new number is frozen already.
- Decks that call the current version see the edits as they are autosaved; a deck that must stay fixed pins a
  version. (Snapshot / export may warn about "+" slides: later.)

## C1: Autosave and Update Version
- `SourceFile.write_now()` replaces `save()`: no prompt; the "+" handling above for a slide's current file;
  same `expected_text` stale check and `on_saved(previous_text)`.
- A debounce timer per file (1.5 s after the last keystroke) calls it. Also written at once when: another
  file is shown, the window closes, a compile / snapshot / preview run starts, and on Ctrl+S (which also
  renders, as Save did). An autosave does not start a render.
- Autosave pauses while: the conflict bar is up (file changed on disk with edits here; Claude Code in the
  terminal), the editor is read-only, or an AI fix is running on the file. It never overwrites a stale file: a
  `StaleFileError` shows the conflict bar instead of a message box.
- Backups: one per file per editing session (first write after load / reload), not one per pause.
- Status chip: "Saving…" while a write is pending, "Not saved: changed on disk" during a conflict.
- Frozen `-vX-Y-Z.tex` files stay read-only, with unlock still possible; once unlocked they autosave plainly.
- The "Save" button becomes **Update Version**, shown for a slide's current file only.
- Tests: debounce writes after idle; write on switch; no write in conflict or read-only; stale file not
  overwritten; lazy freeze and "+"; Update Version numbering, refusal and deck pin target; restore of a "+"
  slide; one backup per session.

Done in v8.18.0. Follow-ups found on the way:
- Claude Code's own edits in the terminal do not get the "+" (they bypass `save_slide`). Update Version still
  sees them, by comparing with the frozen version; the footer shows no "+" until the next in-app write.
- An autosave does not start a render (Ctrl+S / Ctrl+R do). Live re-render on autosave could be an option.
- Snapshot and export could warn about slides with "+".

## C3: Retire unsaved state
- Remove or reduce to a flush call: the close prompt (`window._resolve_dirty_edits`) for source files, the
  "Save or revert them first" check in `freeze_version`, the .bib "save first" question in `source_view`, the
  maintenance check (`maintenance.py`), the "N more unsaved" chip, the topbar dirty indicator for source files.
- "Revert" goes: with autosave there is nothing unsaved to discard. Going back is the Versions panel's restore
  (and the editor's undo).
- Side panels (speaker notes) and the Images page keep their own dirty state in this batch; they already flush
  into buffers that now autosave.
- Tests: closing with recent edits loses nothing and asks nothing; the existing dirty-state tests updated.

## C4: Docs
- Manual sections on saving and versions, screenshots (`tools/manual/make_screenshots.py`: the Source view
  toolbar), release notes in `version.py`.

## Decisions (14 October 2026)
- C2: frozen `-vX-Y-Z.tex` files stay read-only, with unlock still possible.
- C1: debounce delay 1.5 s; no setting to switch autosave off.
