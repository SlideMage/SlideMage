# Plan: each tab has a context, and the window follows the tab on show

Status: **draft for the user's review (2026-11-13); nothing built.** Decided: E1 to E6 (section 8); E7 (colour-coded tabs) and E8 await the user's answer. It continues [centre-tabs.md](centre-tabs.md): steps 1 to 3 and 2b of that plan are built,
and D9 to D12 (the side panels follow the tab on show) are where this plan starts.

Request (user, 2026-11-09): separate the contexts of the tabs more cleanly.

1. **Opening a new deck:** the tab that was selected stays open, but everything else, the slide list included,
   switches to the new deck, which then belongs to the tab on show. A tab belongs to a deck context; the left side
   shows the context of the active tab.
2. **A slide opened without a deck** (Search everything): the slide list goes away, or offers to open one of the
   decks that use the slide.
3. **A tab with no slide** (a `.bib`): no slide list, or an empty one, so that the window does not jump when switching
   between a tab with a slide list and one without.

## 1. Where things stand (develop, v0.16.30)

* **One state for the whole window.** `WorkspaceState` (`ui/workspace/state.py`) holds *the* deck, the focused slide
  and occurrence, the selection, the view, the language, the mode and the resolved outline. The top bar, the slide
  list, the centre, the side panels, the background renders and the plugins all read it: `state.deck` is read in
  about 100 places in 22 files. `set_deck()` is a switch: focus and selection start empty, view and mode come back
  from the per-deck memory (`workspace_decks` in `app_settings`), the language from the deck's `\decklanguage`; the
  slide list then focuses its first row. The focus, scroll and language look of the deck that was left are lost.
* **Tabs** (`centre_tabs.py`): the first tab is *the slide tab*, always there, never closed, showing the focused slide
  of `state.deck`. File tabs (closable) hold a file: a deck's source, SlideMage.bib, test-slides.tex, a theme's
  template, a slide's file (Open in new tab, a search hit, a frozen version, the language partner). A `CentreTab` has
  `kind`, `path`, `mode`, `on_saved`, `slide`, `occurrence`; **no deck**.
* **Which deck a file tab means** is whatever `state.deck` is at the moment: `CentreColumn._tab_row(tab)` resolves the
  tab's slide in `state.deck` (by bare id and occurrence), and previews it as that deck calls it, or alone
  (`for_path`) when that deck does not use it. So a slide tab opened from deck A previews as deck B calls it once B
  is opened.
* **Opening a deck** (`state.set_deck` from the top bar's switcher, `menus.py`, Ctrl+K "Go to deck", Used in decks'
  Open, New deck, Duplicate deck, the manual, `window.reload_decks`): `CentreColumn._on_deck_changed` sends the slide
  tab to the new deck and *shows the slide tab*, whatever tab was on show; the file tabs stay, without a deck.
* **The side panels follow the tab on show** (step 2b, built): `PanelActions.tab_slide()` gives `(path, row)` of a
  slide file tab, `SidePanel._slide_id / deck_calls / _focused_row / id_slug / slide_path` read it, and
  `SidePanels.follow_tab()` (connected to `tabs.active_changed`) goes through `_defer()`: pending edits are flushed
  against the slide they were typed for, the old content is shielded, the rebuild waits `SETTLE_MS`. A tab of a file
  that is no slide (`.bib`) leaves the panels on the focused slide without a rebuild. `deck_calls` still matches in
  `state.deck`.
* **The slide list** (`slide_list.py`) lists `state.deck`'s slides (`SlideList.deck`; a test deck has none) and
  rebuilds on `deck_changed`. It is always there, whatever the tab; only the user's column toggle hides it.
* **Restore at start** (D7, step 3): `centre_tabs` in the per-project `app_settings` holds
  `{"tabs": [{"path", "mode"}], "active"}` for the file tabs; the deck is `LAST_DECK_KEY`'s, chosen by
  `reload_decks()` before `restore_tabs()` runs.

## 2. The model: a tab's context

A tab's **context** is the deck it belongs to, or none:

| Context | Meaning | Left column | Tabs that get it |
|---|---|---|---|
| `deck(D)` | the tab is part of deck D's work | D's slide list | D's working tab; a slide opened from D (Open in new tab, Details or Versions' Open, the language partner); D's own source; a search hit in a slide D uses, while D is the context on show |
| `none` (slide) | a slide outside any open deck | placeholder: "Not in an open deck", with the decks that use it (section 5) | Ctrl+K "Go to slide" not in this deck; a text hit in a slide the deck on show does not use; a frozen version opened from a `none` tab |
| `none` (file) | a file that is no slide | placeholder: "No slide list for this file" (section 5) | SlideMage.bib, test-slides.tex, a theme's template, a text hit in another file |

**Working tabs replace the one slide tab** (E1): each open deck has one *working tab*, which shows that deck's focused
slide, exactly what the slide tab does today. A working tab remembers its deck's **working state**, so that coming back
to it is coming back to where one was:

```
CentreTab
    kind        "deck" | "file"            (SLIDE is renamed DECK; one per open deck)
    context     Path | None                (the deck's file; None: no deck)
    path, mode, on_saved, slide, occurrence  (as now)
    work        DeckWork | None            (working tabs only)

DeckWork  (what WorkspaceState holds for the deck on show today)
    focused_slide, focused_occurrence, selection, view, language, outline,
    list_scroll, collapsed_sections, list_filter
```

The context is stored **as the deck's path**, never as a `Deck` object: a rescan (`reload_decks`) replaces the objects
and the tab finds its deck by path, then by name (archived), as `reload_decks` does for the current deck now.

**Invariant I1:** every tab whose context is `deck(D)` has D's working tab open. So "the decks that are open" are
exactly the working tabs, a deck's tabs are always reachable from its list, and closing a deck has one meaning (E2).

**Invariant I2:** `WorkspaceState` holds the context of the tab on show. `state.deck` is the active tab's deck; for a
`none` tab it stays the deck of the most recently used working tab (E3), so the ~100 readers of `state.deck` never see a
`None` they do not see today, and the top bar's Compile still compiles a deck while the .bib is open.

This keeps **one** `WorkspaceState` and swaps what is in it, instead of one state per deck: every widget connects to
the state's signals when it is built, so several states would mean rebuilding the wiring of the whole window. Swapping
costs a deck switch per change of context (section 7, risk R2), which is what the user does by hand today.

## 3. What follows the tab on show, and what stays global

| Part | Follows the active tab | Notes |
|---|---|---|
| Slide list | yes | the deck's list with its focus, selection, scroll, closed sections and Find text (`DeckWork`); a placeholder for `none` (section 5) |
| Top bar: deck switcher | yes | names the active tab's deck; for `none` the last deck (E3). Picking a deck there *opens* it (rule O1) |
| Top bar: View as, language switch | yes | per working tab; the language "look" is kept per working tab instead of being lost at the next deck switch |
| Top bar: Compile and its caret menu | yes | compiles `state.deck` (I2) |
| Top bar: mode switch | yes | per tab already (D2) |
| Side panels (Details, Versions, Language, Notes, Images, Used in, Citations, Visibility, plugin boxes) | yes | the slide of the tab on show (D9), in the tab's deck: `deck_calls` matches in the tab's context deck, not `state.deck`; a `none` slide tab has no deck calls (Visibility and the pin say "not in an open deck") |
| Deck menu (Source, Settings, Duplicate, ...) and Ctrl+K's Slide group, the Slide menu | yes | they act on the list's deck and selection (D12), which is now the active tab's |
| Lint chip, dirty chip, Ctrl+S, Ctrl+R, Readability, AI fix | already per tab | read the file on show (`centre.path`, `shown_slide`) |
| Assistant (chat, task cards, offers) | the scope follows | the conversation stays one; its scope ("this slide") reads the tab on show, as now |
| Background renders | priority follows | which slide is "focused" for priority follows the working tab on show; which decks render stays the dial's setting |
| Images page, Settings, AI route, autosave, the job panel, the debug log | global | not tied to a deck |
| Undo of deck edits (Ctrl+Z in the list) | per deck | `SlideList` keeps its undo per deck already |

## 4. Opening and closing rules

| # | What the user does | Today | Planned |
|---|---|---|---|
| O1 | Opens deck B (top bar, Deck menu, Ctrl+K Go to deck, New / Duplicate deck, the manual) while a tab of deck A is on show | the slide tab moves to B and is shown; A's focus is lost | B's working tab is shown, opened at the end of the strip if B has none; A's tabs, its working tab included, stay with their state; the left side shows B |
| O2 | Used in decks' Open (a slide in deck B) | switches to B, focuses the slide | O1, then focus that slide in B's working tab |
| O3 | Ctrl+K "Go to slide" in the deck on show | focuses it in the slide tab | unchanged (D1): the working tab of the deck on show |
| O4 | Ctrl+K "Go to slide" not in the deck on show | file tab, previewed alone | file tab with context `none` (slide); the placeholder offers the decks that use it |
| O5 | Ctrl+K text hit in a slide | file tab at the line | context = the deck on show if it uses the slide, else `none` |
| O6 | Ctrl+K text hit in another file; Edit .bib; test-slides.tex; a theme's template | file tab | file tab, context `none` (file) |
| O7 | Deck → Source | file tab | file tab, context = that deck |
| O8 | Slide list → Open in new tab; Details / Versions → Open a frozen version; the language chip or Language's Open on a slide file tab | file tab | context = the context of the tab it was opened from |
| O9 | A file that has a tab already is opened again | its tab is shown | unchanged; its context stays (a tab is never moved between decks implicitly; E6 is the explicit way) |
| O10 | Closes a file tab | the most recently used tab is shown | unchanged; if that tab has another context, the window switches to it |
| O11 | Closes a working tab | (the slide tab cannot be closed) | closes the deck: its other tabs close with it, each asking Save / Discard / Cancel as now; Cancel keeps the whole deck open (E2). The last working tab stays while the project has decks |
| O12 | A deck is renamed, archived or deleted (rescan) | `reload_decks` follows by path, then name | each working tab follows its deck by path, then name; a deck that is gone closes its working tab, and its other tabs become `none` (nothing to save is lost) |
| O13 | Restore at start (D7) | file tabs, the last deck | every tab with its context and the working tabs' `DeckWork` (section 6) |

**Strip order** (E7): a deck's tabs stay together, its working tab first; a new tab of deck D goes after D's last tab;
`none` tabs go at the end. A tab shows its slide only; the deck is told by a colour stripe on all its tabs, the tooltip and the
tab's menu (E7).

## 5. Empty and placeholder states, with a stable layout

The user's concern is the jump. The left column therefore **never changes width or visibility because of a tab**:
`SlideList` gets a `QStackedWidget` with two pages, the list and a placeholder, inside the same column, so the
splitter's sizes, the minimum width (`slide_list.MIN_WIDTH`) and the user's own column toggle are untouched (E4). The
header row (search field and the bulk bar's place) keeps its height; on the placeholder page it is disabled, not
hidden.

* **A `none` slide tab** (O4, O5): "1y8 · Market efficiency is not in an open deck." Under it the decks that use it
  (`slide_usage.find_usage`, as the Used in decks panel already does), each with **Open in Lecture 3**: it opens that
  deck (O1, in the background if it has no working tab) and gives *this* tab that deck as its context, so the editor,
  its undo history and the cursor stay; the tab now previews as the deck calls it (E6). No deck uses it: "No deck
  uses this slide yet."
* **A `none` file tab** (O6): a quiet card: "SlideMage.bib has no slide list." and a link **Back to Lecture 3** (the
  most recently used working tab).
* **A test deck's tab:** as now (the list is empty, the centre says why).
* **The side panels** keep their place too. On a `none` slide tab they show that slide (D9) without deck calls; on a
  `none` file tab they keep showing the last deck's focused slide without a rebuild, as step 2b decided (E5).

## 6. Restore at start

`centre_tabs` gets a version and one entry per tab, working tabs included:

```json
{"v": 2, "active": 3,
 "tabs": [
   {"kind": "deck", "deck": "decks/lecture-03.tex", "mode": "preview",
    "work": {"focus": "1y8", "occurrence": [...], "view": "instructor", "language": "EN", "scroll": 412, "collapsed": [...], "filter": ""}},
   {"kind": "file", "path": "slides/2ab-EN-CAPM.tex", "deck": "decks/lecture-03.tex", "mode": "source", "occurrence": [...]},
   {"kind": "file", "path": "SlideMage.bib", "deck": null, "mode": "source"}]}
```

* Paths relative to the project, as now. A missing file is skipped silently (D7); a missing deck drops its working tab and
  makes its tabs `none` (O12).
* `LAST_DECK_KEY` stays "the deck of the active tab when the window closed", so `reload_decks()` picks the right deck
  first and nothing else that reads it changes.
* **Old format** (no `v`): one working tab for the last deck, as today; each file tab gets: a deck's source -> that deck
  (opening its working tab too, I1); a slide the last deck uses -> the last deck; anything else -> `none`.
* The per-deck view and mode memory (`workspace_decks`) stays; `DeckWork` is what is new.

## 7. Migration and risks

* **R1. "The current deck" is one global.** About 100 readers of `state.deck`. Invariant I2 keeps them right without
  touching them: the state always holds the context on show. What must change are the readers that mean *a tab's*
  deck while another tab could be on show: `CentreColumn._tab_row`, `_context_for`, `_neighbour_targets`,
  `_go_adjacent` (they read `state.deck` for a file tab), and `SidePanel.deck_calls` / `_focused_row`. Step 0 routes
  them through one method, `centre.tab_deck(tab)`, before anything else moves.
* **R2. A change of context is a deck switch**, with a slide list rebuild (`resolve_outline`), a side panel refresh
  and the background priorities. Mitigations: keep the resolved `Outline` in `DeckWork` (valid while the deck's text,
  view and language are the same; `Outline.matches` exists), so coming back does not resolve again; during a Ctrl+Tab
  series the left side follows only when the series ends or rests `SETTLE_MS` (E8), as the side panels already do.
  Measure with the `timing` spans that are there (`reload_decks.slide_list`, `slide_list.resolve_outline`).
* **R3. `set_deck()` means two things.** Today it is "open a deck" and resets the focus. A change of context needs
  "show this deck as it was": `WorkspaceState.set_deck(deck, work=DeckWork | None)` restores focus, selection, view
  and language instead of resetting them, and emits the same signals, so listeners need no change. The callers that
  *open* a deck (section 1) keep calling `set_deck(deck)`; `CentreColumn._on_deck_changed` turns a switch that did not
  come from a tab into O1 (open or show that deck's tab) instead of sending the slide tab there. A guard flag
  (`_switching_context`) stops the loop tab -> state -> tab.
* **R4. Pending edits when the context changes.** Everything typed must land in the context it was typed in, *before*
  `state.deck` changes, because some flushes edit "the open deck":
  * the side panels' pending edits (`SidePanels.flush()`; `_defer()` flushes only after the state changed: Notes and
    Images capture their path at build time and are safe, but a flush that goes through `edit_deck` would hit the new
    deck);
  * the slide list's inline section rename (an open `QLineEdit`) and its Find text (kept in `DeckWork`);
  * the Preview's step bar (`preview.edit_deck`);
  * the Source view's buffers are written when their tab is left (`_on_tab_active`), as now.
  So the window calls one `about_to_change_context()` (flush panels, commit the list's editors, write the file on
  show) before it touches the state; a test per item.
* **R5. The tab model's "slide tab" assumptions.** `CentreTabs.slide_tab` (`_tabs[0]`), `closable`,
  `state.remember_mode` ("the slide tab is on show"), `_show_slide_tab`, the holds of the slide tab's file
  (`SourcePane.hold`), `restore_version`'s fallback, `edit_slide_text(show=True)`. Each becomes "the working tab of the
  tab's context". `test_centre_tabs.py` and `test_centre_gui.py` test these directly and will need updating in step 3.
* **R6. Tests that call `state.set_deck` directly** (and the many GUI tests built on one open deck) keep
  working: `set_deck(deck)` stays "open this deck", and with one deck open the window behaves as today.
* **R7. Plugins** read `state.deck` and rebuild their boxes on `deck_changed`; they now see it on every change of
  context. Harmless, but it is more rebuilds: plugin boxes are only built when shown.
* **R8. Background renders** follow the focus: a context switch moves the priority, which is right; a Ctrl+Tab series
  must not start work per step (E8 covers it).
* **R9. Memory:** each working tab holds its focused slide's `SourceFile`; a dozen decks open is a dozen editors more,
  which is fine (centre-tabs.md 3.2).

## 8. Decisions for the user

* **E1. Opening a deck: a working tab per open deck. Decided 2026-11-13.** The *working tab* is the tab you know: neutral
  ("Select a slide in the list") until a slide is selected, then showing that slide. There is no extra "deck tab"; a deck
  gets a tab of its own only for Deck -> Source. Opening B adds B's working tab and shows it; A's working tab and its tabs
  stay, and switching back brings A's list back where it was.
* **E2. Closing a working tab closes the deck. Decided 2026-11-13.** The working tab gets an "x" (today it has none);
  closing it closes the deck's other tabs too (extra slides, its source), each asking Save / Discard / Cancel, and Cancel
  keeps the whole deck open. Selecting another slide never closes anything.
* **E3. A `none` tab keeps the last deck in the top bar. Decided:** Compile and the view switch keep working while the .bib is edited.
* **E4. A placeholder in the same column. Decided:** the window never jumps.
* **E5. The side panels on a `none` file tab: keep the last deck's focused slide, as step 2b decided. Decided 2026-11-13.**
* **E6. "Open in <deck>" on a slide in no open deck. Decided:** the tab keeps its editor and undo, gets that deck as its
  context and the deck opens in the background.
* **E7. Strip labels: slide name, deck by colour (proposed 2026-11-13; waits for the user's OK).** Deck plus slide names
  would not fit. A tab shows the slide only (`1y8 - Market efficiency`, elided as now); a working tab with no slide
  chosen shows the deck's name. Each open deck gets a colour from a small palette (about six kit-token hues that work in
  light and dark), shown as a stripe along the top edge of all its tabs; assigned in the order decks are opened, reused
  after six, saved with the tabs (section 6). Not colour alone: the tooltip names deck and slide, the tab's menu gets
  "Show in deck <name>". Tabs with no deck get no stripe. A deck's tabs stay grouped, working tab first.
* **E8. Ctrl+Tab across decks:** the centre shows each tab at once; the left side and the panels follow when the series
  ends or rests (assumed from the recommendation; not asked).

## 9. Steps

Each step is a PR into develop with its own version, after the user's go; the first changes no behaviour.

0. **One seam for "the tab's deck" (no behaviour change).** `CentreTab.context` with a third value, `FOLLOW`, that
   every tab has for now and that means "whatever `state.deck` is", i.e. today. `CentreColumn.tab_deck(tab)` answers
   the deck of a tab; `_tab_row`, `_context_for`, `_neighbour_targets`, `_go_adjacent` and `PanelActions.tab_slide`
   (which gains the deck: `(path, row, deck)`) read it; `SidePanel.deck_calls` and `_focused_row` match in that deck.
   `save_tabs` writes the new format (`v: 2`, `deck` per tab, working tab entry without `work` yet); `restore_tabs` reads
   both formats. Tests: the existing suites unchanged and green; a round trip of both formats.
1. **Placeholders and `none` file tabs** (request 3). The stacked placeholder page in `SlideList`, a `context_changed`
   signal of the centre, O6's tabs get `none`. Tests: switching between a slide tab and a .bib tab leaves the column's
   width and the splitter sizes unchanged; Back to <deck>; the panels unchanged (E5).
2. **Slides outside the deck** (request 2). O4 and O5 give `none` (slide); the placeholder lists the decks that use the
   slide; Open in <deck> (E6, with one working tab still: it switches that working tab, as opening a deck does today, and
   gives this tab the deck); the panels without deck calls on a `none` slide. Tests in the palette, the centre and the
   side panels.
3. **Working tabs** (request 1; the large one, so in two PRs):
   * **3a.** `DeckWork` and `WorkspaceState.set_deck(deck, work=...)` / `snapshot()`, the list's scroll, closed
     sections and Find text read and written through it, the cached outline; `about_to_change_context()` (R4). No UI
     change: nothing calls it with `work` yet. Tests in `test_workspace_state.py` and the slide list.
   * **3b.** The slide tab becomes the working tab, one per open deck (E1); O1, O2, O8 to O12; activating a tab of another
     context restores it (R3's guard); closing a deck (E2); strip order and labels (E7); the Ctrl+Tab rule (E8).
     Tests: two decks, switch, edit in each, close a deck with a dirty tab and Cancel, rescan with a renamed and a
     deleted deck, a pending note flushed to the deck it was typed in.
4. **Restore with contexts** (O13): working tabs with their `DeckWork`, the old-format migration of section 6. Tests:
   round trip, old format, missing deck, missing file.
5. **Docs:** the manual's workspace slide, the shortcuts dialog, the CHANGELOG entry per step; centre-tabs.md's
   section 2 (the slide tab) updated to point here.

Steps 0 to 2 are useful on their own and fit the current single-deck window; step 3 is where the window starts to hold
several decks.
