# ⋮ menu update: plan (20 October 2026)

Source: the handoff README "SlideMage: ⋮ menu update (since the `develop` re-import)". The updated prototype it
refers to is not on disk (the copy in `~/Downloads/slidemage redesign/` predates this change), so the README is the
spec. Each step is one `ui-step-implementer` agent, reviewed by the orchestrator, tested in full and committed with a
version bump. No step waits for approval (user, 20 October 2026): the orchestrator reviews, corrects or sends a
step back, commits it and starts the next.

Agents get a hard token cap: "when you reach ~N tokens, finish the current change, stop and report".

| Step | Content | Version | Cap | Window |
|---|---|---|---|---|
| M1 | Deck settings → Maintenance group; Settings → Project and About tabs | v8.41.0 | 150k | ~8% |
| M2 | ⋮ menu: new layout without submenus; drop Preview wizard magic | v8.42.0 | 100k | ~5% |
| M3 | Submenu flyouts in `PopoverMenu`; Export ▸ and Housekeeping ▸ | v8.43.0 | 100k | ~5% |
| M4 | Export LaTeX (module, command, ⌘K entry, Export ▸ item) | v8.44.0 | 200k | ~10% |

Total ~28% plus orchestrator review and commits, ~30–35%.

**Status (21 October 2026): all four steps done** (v8.41.0–v8.44.0). M4 follows the sources instead of reusing the
deck snapshot's compile-based file list (that needs LaTeX and about a minute per deck); the export of the manual deck
compiles to the same 97 pages.

## Already done: README section 1 (wording)
All three strings already match `develop`: "the Ollama address of Settings" (`ui/workspace/ai_setup.py:32`),
" · not saved" (`ui/workspace/assistant_header.py:264`), "Claude Code default" (`ui/workspace/ai_setup.py:160`).
Nothing to do. (The terminal caption in `ui/workspace/terminal/view.py:164` still says "Conversation model: set in
Claude Code"; it is a different place and stays unless the user wants it changed.)

## The user's uncommitted work
The working tree has the user's own changes in `deck_settings.py`, `ui/dialogs/deck_settings.py`,
`ui/workspace/deck_actions.py`, their tests, `README.md`, `docs/SlideMage.md`, the preamble files and the icons.
They stay uncommitted (user's choice): agents build on the tree as it is and never revert them; each step's
commit contains only that step's hunks.

## M1: Maintenance group and the Settings rows
Do this before M2 so nothing leaves the ⋮ menu before its new home exists.

**Deck settings → General** (`ui/dialogs/deck_settings.py`, `_build_general`): a **Maintenance** group at the
bottom, after the appendix checkbox, with three rows, each a label, a one-line caption and a compact button:
- **Deck snapshot**: "Create snapshot…" runs the `create_snapshot` command.
- **Previews**: "Rerender all" runs `rerender_deck_previews`.
- **Slide versions**: "Update changed…" runs `update_deck_versions`.

The buttons close the sheet first if the action opens its own dialog or needs the window (the sheet is modal);
unsaved changes in the sheet ask as Cancel does. The buttons go through the command registry (`ctx.commands[id]`),
so enabled state and behaviour stay in one place. If General gets too long, note it for the open item "separate
Maintenance tab", do not add the tab now.

**Settings** (`ui/dialogs/settings.py`, `SettingsSheet`): the tabs today are General, AI, Cloud, Ollama, Prompts,
Presentation; there is no Project or About tab. Add:
- **Project** tab: rows **Bibliography file** (`Slidemaster.bib`, the project's real file name shown) and
  **Test slides** (`test-slides.tex`), each with an **Edit** button that closes Settings and opens the file in
  Source (`window._on_edit_bib`, `window._on_edit_test_slides`); a row **Project compatibility** with "Check…"
  (`maintenance.on_project_compat`). A missing file shows "not found" and disables Edit.
- **About** tab: **Version history** ("Open…", the existing `AboutSheet` via `maintenance.on_open_version_history`)
  and **Check for updates** ("Check…", `maintenance.on_check_for_updates`), plus the version number.

Tests: `tests/test_deck_settings_gui.py` (rows present, each button runs its command, close-first behaviour),
`tests/test_settings_gui.py` (new tabs, Edit opens Source, missing file disables Edit).

## M2: The new ⋮ menu (no submenus yet)
`ui/workspace/menus.py`, `MORE_COLUMNS`:
- **This deck**: `present`, `deck_settings`, `export_pptx`, `duplicate_deck`; separator; `archive_deck`.
  (Export ▸ becomes a flyout in M3; until then Export PPTX… is a plain row.)
- **Project**: `images`, `open_project`, `new_deck`; separator; `housekeeping`, `archive_unused`.
  (Housekeeping ▸ becomes a flyout in M3.)
- Footer `settings` and the note stay.
- Out of the menu, still in ⌘K: `admin_slides`, `deck_tags`, `deck_source`, `create_snapshot`,
  `rerender_deck_previews`, `update_deck_versions`, `edit_bib`, `edit_test_slides`, `palette`, `version_history`,
  `check_updates`, `project_compat`. The Info column goes.
- Deck settings shows its shortcut ⌘, / Ctrl+, in the menu: add `shortcut="Ctrl+,"` to the command if it has none
  (check it does not clash with an existing binding).
- **Delete Preview wizard magic**: only the `wizard_preview` command (`actions.py:287-288`) and the demo path of
  `play_wizard` if nothing else uses it. `wizard_portal.py` stays: `window.py` uses `review_snapshot` and
  `note_review_updates` from it. Adjust `tests/test_wizard_portal.py` accordingly.
- Update the module comment above `MORE_COLUMNS` and the README/manual where they list the ⋮ menu
  (`docs/SlideMage.md`, `README.md`).

Tests: `tests/test_more_menu_gui.py` (the expected layout list at its top), `tests/test_palette_gui.py` if it checks
the wizard command.

## M3: Submenu flyouts
`ui/kit/widgets.py`, `PopoverMenu`:
- `add_submenu(key, text, build)`: a row with a trailing ▸ (no meta text). `build(parent) -> PopoverMenu` makes the
  flyout's content: a title row (the parent row's text) and its items.
- Click on the row opens the flyout: a second `PopoverMenu` (non-inline, a Qt popup) 280 px wide, to the left of
  the ⋮ menu, top aligned with the row; it flips right or shifts up when the screen edge needs it.
- One flyout at a time: opening one closes the other. Clicking the same row again closes it.
- An item in the flyout emits the **parent's** `triggered(key)` and closes both. A click outside both closes both;
  Esc in the flyout closes only the flyout; the ⋮ button closes everything.
- Keyboard (README TODO) is **out of scope**: rows stay reachable by mouse; ↑/↓ skip nothing. Note it in the
  module docstring.
- QSS: the ▸ glyph and the title row in `ui/kit/kit_qss.py` with the existing menu tokens.

`menus.py`: **Export ▸** (`export_pptx`; `export_latex` follows in M4) and **Housekeeping ▸** (`housekeeping`,
`archive_unused`). `MORE_COLUMNS` gets a way to say "submenu" (e.g. a tuple entry `("submenu", "Export", ids)`).

Tests: `tests/test_ui_kit_gui.py` (open, one-at-a-time, item fires parent signal and closes both, outside click,
Esc, position left of the menu), `tests/test_more_menu_gui.py` (layout with the two submenus).

## M4: Export LaTeX
**Decided (user, 20 October 2026):**
1. *Folder contents*: a folder that compiles as it is: `<deck>.tex`, the used `slides/`, the used `media/`, plus
   the institution preamble (`Slidemaster_preamble_<template>.tex`), `Slidemaster_preamble_base.tex` and the other
   `latex/` files it `\input`s, the `.bib` and any `schemes/` or `snippets/` files the used slides `\input`.
2. *Destination*: a plain folder picker (`QFileDialog.getExistingDirectory`), writing `<chosen>/<deck>-latex/`; if
   that folder exists, ask to replace it. No options dialog.

Implementation:
- New module `src/slidemage/latex_export.py`, no Qt: `export_deck(ctx, deck, dest) -> ExportResult` (files
  written, missing references).
  - Slides: every `\slide{id}` of the deck, resolved the way the compiler resolves them, plus anything those slides
    `\input`.
  - Media: images the copied slides use, with the same matching rules as `unused_content.find_unused_media`
    (bare `media/<name>` without extension included); share the scanning code rather than copying it.
  - The deck file moves from `decks/` to the folder root: rewrite its `\def\input@path{{../}}` and
    `\graphicspath{{../}}` lines (or drop them) so it builds from there.
  - Missing files are reported, not fatal.
- Command `export_latex` "Export LaTeX…" (DECK group, meta "self-contained · with media folder") in
  `ui/workspace/actions.py`; a toast on success with an "Open folder" action; added to the Export ▸ flyout.
- Docs: manual entry in `docs/SlideMage.md`.

Tests: `tests/test_latex_export.py` on the example project (the right slides and only their media copied, path
lines rewritten, missing file reported); one test that compiles the exported folder with latexmk, skipped when
LaTeX is not installed; a GUI test for the command (picker mocked, existing folder asks).

## Not in this plan (README open items)
- Assistant clipped below ~540 px window height.
- Submenu keyboard access.
- A separate Maintenance tab in Deck settings.
- Claude Code model cells still labelled as examples.
- Tags: the README says Tags is in the Deck settings tabs, but there is no Tags tab; after M2 Tags… is in ⌘K only.
  Adding a Tags tab would be a separate step.
