# Plan: tabs in the centre column

Status: all decisions made by the user 2026-11-01 (section 6). Step 1 is done (v0.13.12, branch tabs/step1-strip, not merged); steps 2 to 4 next, after the go.

Request (2026-11-01): "I liked working in tabs in SlideMage versions up to v5. Draft a plan to open source views, the
.bib edit view, and slides that the user opens using the search functionality in tabs. When opening a deck source or
the .bib, in a way SlideMage already does this - at least it returns to the previously viewed slide when closing
these views. Modify that so it shows them as tabs instead, so the user can easily switch back and forth."

## 1. What SlideMage does today

* **One file at a time.** `CentreColumn` (`ui/workspace/centre.py`) holds one `_path`: the focused slide's file, or a
  file "opened on purpose". The Source view (`ui/workspace/source_view.py`, `SourcePane`) keeps a `SourceFile` per
  file, but drops every clean file that goes out of view (`show_path`: "a clean one is dropped and read from disk
  again when it comes back, so it is never stale"); only files that cannot be written stay (`keep_open`).
* **Deck source, SlideMage.bib, test-slides.tex** (`window.open_deck_source_editor`, `_on_edit_bib`,
  `_on_edit_test_slides` → `open_slide_editor` → `centre.open_file`): they replace the slide in the Source view and
  switch to the Source mode. `centre._return_mode` remembers the mode before; the toolbar's "x"
  (`SourcePane.close_requested` → `centre.close_explicit_file`) asks Save / Discard / Cancel for lost edits, then goes
  back to the focused slide in that mode. Switching to Preview or Details closes the file the same way (`_on_mode`).
  Focusing another slide in the list also replaces it.
* **Search** (`ui/workspace/palette.py`, Ctrl+K):
  * "Go to slide", slide in the open deck: `state.set_focused_slide` (same as a click in the slide list);
  * "Go to slide", slide not in this deck: `window.open_slide_editor(path)`: shown in Source, previewed alone
    (`centre._preview_context` → `for_path`);
  * "Text in project files": `window.open_slide_editor(hit.path, line=hit.line)`: any file, at the line.
  Each replaces what the centre shows; the way back is the slide list.
* **The .bib sorts** on open (only when it is not open yet) and on close (`window._on_source_closed`, from
  `SourcePane.file_closed`).

## 2. What it should do

A **tab strip** at the top of the centre column, above Preview / Source / Split / Details:

```
 [ 1y8 · Market efficiency ]  [ lecture-03.tex  x ]  [ SlideMage.bib  x ]  [ 2ab · CAPM  x ]
```

* **The slide tab** (first, always there, no "x"): the focused slide, as today. The slide list, "Go to slide" for a
  slide of the deck, the Preview's wheel past the last step and the language chip all act on it.
* **File tabs** (closable): a deck's source, SlideMage.bib, test-slides.tex, what search opens (see decision D1),
  and a slide of the list opened with its right-click menu's **Open in new tab** (D0). A slide tab of a slide the
  open deck uses previews it as the deck calls it (`for_call`, like the slide tab), one the deck does not use alone
  (`for_path`).
  Opening a file that has a tab selects that tab (and goes to the line of a text hit); it does not open a second one.
* **Each tab keeps its own state**: the file, its editor (undo history, cursor, scroll, find bar) and the mode it was
  last shown in (D2). Switching tabs never loses an edit and never reloads a buffer behind the user's back: a file
  coming back into view is checked against disk (`SourceFile.sync()`, which already exists).
* **Closing a tab** (its "x", middle click, Ctrl+W): Save / Discard / Cancel for edits that could not be written, as
  `close_explicit_file` does now; then the tab shown before it comes back (most recently used, not the neighbour),
  in the mode it had. That keeps today's "returns to the previously viewed slide" behaviour.
* **Switching**: click, Ctrl+Tab / Ctrl+Shift+Tab (most recently used order), Ctrl+PgDn / Ctrl+PgUp (strip order).
* **Modes of a file that is no slide**: a deck's source and the .bib have no Preview or Details. Their tab shows the
  Source view alone; the mode switch shows Preview / Split / Details disabled with a tooltip, instead of closing the
  file as today (D3).
* **Overflow**: tabs shrink to a minimum width and elide (`ElidedLabel`, as the Source toolbar's name does), then
  scroll arrows; no limit on the count (D4).

## 3. How

### 3.1 A tab model in the centre

New `ui/workspace/centre_tabs.py`:

* `CentreTab` (dataclass): `kind` ("slide" | "file"), `path` (None for the slide tab, which follows the focus),
  `mode` (the mode last shown in), `on_saved` (the deck source's `after_deck_edit` hook, the .bib's none).
* `CentreTabs` (QObject): the list, the active tab, the MRU order; signals `active_changed`, `tabs_changed`.
  Pure Python apart from the signals, so the logic is tested without a window.
* `TabStrip` (widget, from the kit: `Surface`, `ElidedLabel`, `IconButton("close")`): draws the model, emits
  activate / close / middle-click; a context menu with Close, Close others, Close all to the right, Reveal in
  Explorer (D5).

`CentreColumn` keeps `_path` as "the active tab's file": `open_file`, `_set_path`, `_preview_context`, `refresh`
stay as they are, read through the active tab. `_return_mode` and `close_explicit_file` go; the mode memory moves
into `CentreTab.mode`, closing into `close_tab(tab)`.

### 3.2 The Source view keeps tabbed files open

`SourcePane.show_path` drops clean files that go out of view. A file that has a tab must stay instead: a new
`SourcePane.hold(path)` / `release(path)` (or `SourceFile.keep_open` becoming "held by a tab or blocked"). A held
file is still written before it goes out of view (as now) and synced when it comes back. `file_closed` (and so the
.bib's sort on close) fires when its tab closes, not when it goes out of view. The toolbar's "x"
(`_close_button`, `close_requested`) goes: the tab's "x" replaces it.

Memory: a `SourceFile` is an editor with its lint and fix panels; a dozen open tabs is fine. The slide tab still
drops the slides the focus leaves, as now.

### 3.3 Who opens tabs

| Opener | Today | With tabs |
|---|---|---|
| Deck → Source (`open_deck_source_editor`) | replaces, Source mode | file tab, Source mode |
| ⋮ → Edit .bib (`_on_edit_bib`) | replaces, Source mode | file tab; sorted only when its tab is new (as now) |
| Edit test-slides.tex | replaces | file tab |
| Ctrl+K "Text in project files" | replaces, at the line | file tab at the line (D1) |
| Ctrl+K "Go to slide", not in this deck | replaces | file tab; Preview shows it alone (as now) |
| Ctrl+K "Go to slide", in the deck | focuses it | the slide tab, focused (D1) |
| Slide list, right-click → Open in new tab (`slide_list._slide_menu`) | (new) | file tab of that slide, as the deck calls it (D0) |
| Details → open a version (`open_requested`) | replaces | a file tab of that frozen version, read-only as now (D6) |
| Preview's language chip (`partner_requested`) | replaces, keeps the mode | the slide tab, as now |
| Restore a version (`restore_version`, also from a frozen version's tab) | opens the current file | the slide tab; the frozen version's tab stays |

`window.open_slide_editor` gets `tab: bool = False`; the openers above that make tabs pass `tab=True`, so the AI
tools, the image pages and the error list that call it today keep their behaviour unless we decide otherwise.

Step 1 as built: a file that is no slide always opens as a file tab, whichever caller opens it (a text hit in a .tex
that is no slide, the error list, the citations panel), so the Source-only rule (D3) has one home, in
`CentreColumn.open_file`. `tab=True` is accepted for a slide's file but changes nothing yet: slides stay on the slide
tab until step 2. In step 1 Notes' Save notes, the slide list's Preview command and the AI tools' show-slide also
show the slide tab, as focusing a slide does.

### 3.4 What else reads "the file shown"

`centre.path` is read by the chat focus (`Host.focus()`, the assistant's scope), Ctrl+S, Ctrl+R, the lint chip, the
Readability panel and the AI fix. They keep reading the active tab's file, so a chat about "this slide" in a slide
file tab means that slide. Check each in step 1 and list them in the PR.

### 3.5 Restoring tabs at the next start (D7)

Per project, in `layout_settings` (`centre_tabs`: the file tabs' paths relative to the project, the active one, their
modes); files that no longer exist are skipped silently.

## 4. Steps

Each step a PR into develop with its own minor version, after the user's go (feedback rule: pause between steps).

1. **Tab model and strip; deck source, .bib, test-slides.tex as tabs.** `centre_tabs.py`, the strip, the held files
   in the Source view, closing with Save / Discard / Cancel and the MRU return, the mode switch for non-slide tabs,
   Ctrl+W / Ctrl+Tab. Removes `_return_mode`, `close_explicit_file`, the toolbar "x". Tests: the model (pure),
   centre GUI tests (open, switch, edit in two tabs, close a dirty tab, Cancel keeps it, .bib sorted once on open and
   once on close, a file changed on disk while its tab is in the background).
2. **Slides in tabs: search, the slide list, frozen versions.** The palette's text hits and not-in-deck slides; a
   text hit in a file with a tab goes to the line there. The slide list's right-click **Open in new tab** (D0).
   Frozen versions opened from Details in a tab of their own, named with the version (`1y8 v1.2`) (D6). Slide file tabs get
   Preview / Split / Details (as the deck calls the slide, or alone). Tests in the palette, the slide list and centre
   GUI tests.
3. **Context menu, keyboard order, restore at start** (D5, D7). Tests: layout settings round trip, missing files.
4. **Docs.** The manual slide on the workspace and the shortcuts dialog (`ui/dialogs/shortcuts.py`); the CHANGELOG
   entries are written per step.

Steps 1 and 2 are the request; 3 and 4 can be merged into them if the user prefers fewer PRs.

## 5. Risks

* **One path, many readers.** `centre._path` is read in many places (3.4); a missed one acts on the slide tab's file
  while a file tab is shown. Mitigation: route every reader through one property and grep for `_path` / `.path`.
* **Background renders** follow the focused slide (`background_previews`): a file tab must not stop them, nor make
  them render the file tab's slide as "the focused one".
* **Two buffers of one file**: a slide open in a file tab that the slide list also focuses must be one `SourceFile`
  (the pane keys files by path already): focusing it in the list selects the slide tab, which shows the same
  buffer; its file tab stays.
* **A deck slide in its own tab** (D0) keeps its deck context (`for_call` needs its row): if the deck changes so that
  it no longer uses the slide, the tab falls back to previewing it alone; if another deck is opened, the same.
* **Split view width**: the strip sits above both halves, so it does not change the Source pane's minimum width.

## 6. Decisions

Decided by the user 2026-11-01:

* **D0. Open in new tab** from the slide list's right-click menu (user's addition): yes, in step 2.
* **D1. Which search results open a tab?** Text hits and slides not in this deck open (or select) a tab; "Go to
  slide" for a slide of the open deck stays a focus change of the slide tab, like a click in the list.
* **D2. Mode per tab:** yes (the .bib in Source, the slide in Preview, and switching restores each).
* **D3. Preview / Details on a deck source or the .bib tab:** disabled, with a tooltip.
* **D8. v5 details to bring back:** none; the strip follows the current design kit.

* **D4. Limit on open tabs:** none; tabs shrink and elide, then scroll.
* **D5. Context menu on a tab** (Close, Close others, Close all to the right, Reveal in Explorer): yes, in step 3.
* **D6. Frozen versions opened from Details:** a tab of their own (not the recommendation, which was the slide tab),
  so a version and the current slide can be compared by switching; in step 2.
* **D7. Restore the file tabs when the project is opened again:** yes, per project, in step 3; missing files are
  skipped silently.
