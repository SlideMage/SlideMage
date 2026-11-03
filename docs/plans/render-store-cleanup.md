# Plan: the render store keeps only what is needed, and deck compiles count

Status: decisions D1 to D3 made (section 3). Step 1 merged (#76, v0.13.40). Step 2 only after the go.

## 1. What was found

Measured on 2026-11-01 on the Slidemaster project (store `2560ac40a2eab96a`, disk limit 10 GB), after clearing the store and compiling all views of all decks.

| Number | What it is |
|---|---|
| 10000+ | The store before clearing. The cause is inferred, those renders are gone (1.1) |
| 3973 | Reported after the compiles: one last-page render per slide and view. About 3999 by my count; the last 26 or so are not reconciled |
| 4289 | Units the decks need, so what the sweep planned. Contents and section slides and `\slidestep` calls are not taken from a compile, which is most of the gap |
| 5398 | The store afterwards: 4263 background renders, 1128 English compile renders of `t-Uni-IA2-2026w` (1.3), 7 of test decks |

### 1.1 Stale renders stay

The fast key (`render_key.fast_key`) contains the slide file's hash and the deck preamble's hash, so editing either makes a new object and leaves the old one. `RenderStore.enforce_limit` removes the old one only when it is unused for 30 days and not in a protected deck (the open deck and the five most recently opened), when its deck is gone, or when the store is over the limit.

Why this explains the 10000: in the last 30 days 1049 of 3398 slide files and 22 deck files changed, including 284 slide files in the migration to v0.13. One preamble edit orphans every render of that deck.

### 1.2 The sweep ignores deck compiles

`BackgroundRenderer.ingest_compile` stores only the last page of each slide, marked `partial`. `Lookup.final` accepts only `origin == "background"`, so `scan()` plans these slides again and the status shows 0 %. The CHANGELOG entry for v0.8.32.0 records this as intended. The sweep then took about 45 minutes.

Deck PDF against background render, by number of pages per slide (whole-deck records, excluding the presenter PDFs):

| Views | Same count |
|---|---|
| Instructor | about 99 % (13 of about 1430 differ) |
| During-course and after-course | about 94.5 % (about 158 of 2860 differ) |

Almost all the differing student-view slides are in `t-Uni-Masterdeck-Publishing` and `#workdeck`: the PDF has one page where the background render has up to 5. The cause: these slides call `\SMFinalStateForStudents` (54 slide files carry it; 142 of the differing ordinary units), so student PDFs show only their final state. The background render deliberately overrides that (`slide_preview._overlay_line`, `all_steps`) so the reveal bar has every step. The last page is the same either way.

Last page, pixel by pixel: 343 of 393 sampled slides identical, most of the other 50 only in the footer area. A few larger differences were not inspected. The sample covers the first decks alphabetically, not all of them.

Slides that need their deck (contents, agenda, section slides, 303 units): 258 have a background render, and all match the PDF's page count. 73 of the 258 differ from the PDF's last page. In the 4 compared by eye the content was the same but the layout was not: the picture on `xcb-EN-Project-Life-Cycle-Overview` sits about 16 px lower (at 800 px wide) and is cut by the footer, and the agenda band under the title differs in height. So these background renders can be less faithful than the deck. The cause is not traced. The other 45 units have no background render; not checked why.

### 1.3 Compile language and sweep language differ

`languages_for` uses the language last viewed; `ingest_compile` uses the deck's own. `t-Uni-IA2-2026w` is English but was last viewed in German, so the sweep ignored 1128 English compile renders and rendered about 1134 German ones. The deck's own language then has no full renders.

### 1.4 A slide called twice is rendered again on every idle pass

32 labels occur twice in a deck, because a slide is called twice (`\slidestep` calls, or `\slide` and `\slidefinal`).

- **26 with one key:** both calls have the same key but different page numbers. The render of one is `FRESH_NUMBERING_DIFFERS` for the other, so each refresh invalidates its twin. Seen: the same 26 rendered at 14:00 and again at 14:11, with the status still at 100 %.
- **6 with two keys:** `g96-EN-Climate-Impact-Beliefs` and `jww-EN-Pecking-Order-Theory`, 3 views each. Different calls, so two different keys, and **both are current**. Fix 1 must not treat these as stale (step 2).

### 1.5 The status text jumps

`BackgroundPreviews.refresh` calls `chip.adjustSize()` each second. In the status row the layout stretches the chip to 34 px; `adjustSize()` shrinks it to 20 px, moving the text centre from 17 px to 10 px until the layout runs again. Measured in the real window under the test harness. Without the call the chip stays at 34 px.

## 2. Steps

One PR per step, with its own version and CHANGELOG entry; a pause after each.

### Step 1: the status text stays still

In `background_previews.py`, call `adjustSize()` only when `self._row is None` (the floating placement `_place()` still needs it).

Test: in a status row, the chip's height and the label's position are the same across refreshes.

### Step 2: stale renders go

- When a render of a unit is stored, delete older renders of the same label whose key the deck no longer uses. The old preview stays shown as "outdated" until then, since `latest_for_unit` needs it only while no new render exists.
- **Not by label alone** (1.4): compare against the keys the current scan found for that deck, view and language. Deleting by label would have two current calls delete each other for ever.
- A scan that could not read a deck deletes nothing for that deck.
- Once, on the first scan after the update: remove what no current key needs, in a store whose decks all scanned cleanly.
- Protected decks get no exemption from this; they keep theirs from the disk limit.

Tests: slide edit, preamble edit, a slide called twice with different calls (both kept), a slide reverted to its old text (rendered again, accepted), a deck that cannot be read (nothing deleted).

### Step 3: the double renders stop

In `scan()`, refresh a page number only if no other unit in the plan has the same key (D3).

Test: a deck calling a slide twice has nothing outstanding after one pass.

### Step 4: a deck compile counts as finished

- `ingest_compile` stores every page of the slide's run, without `partial`, including slides with `\SMFinalStateForStudents` (D1) and slides that need their deck (D2). For the latter, `ingest_compile` must call `deck_units` with a `context_ready` that says yes, and their key contains the deck (`unit.context`).
- Check first that the reveal bar copes with a student-view render of one page when the slide has more steps: its rows (`reveal_bar.py`, `RowSpec`, the "deck steps only" switch) may expect more pages than are stored (the open risk of D1).
- `Lookup.final` accepts these. That also serves `scan()`, `render_unit` and `render_batch`, so running sweep jobs skip them.
- `ingest_compile` skips a unit only when its render is final. Today it skips any usable one, which would leave old partial records in place.
- `stored_pages` (`background_previews.py:517`) and `store_reveal` keep their `partial` tests for records stored before this step.
- No `slide.pdf` is needed: `pdf_path()` has no callers outside `render_store.py`.
- `\slidestep` and `\slidefinal` calls stay with the sweep, 32 renders: the PDF shows only a selection of their steps.

Tests: after a compile only `\slidestep` and `\slidefinal` calls of that view are planned and the status counts the rest; a slide edited afterwards is planned again; an old partial record is replaced; a final-state slide in a student view shows one step without an error.

Check on the real project: compile all views, confirm the sweep has only the rest left, and time the ingest. It reads more pages than the 45 to 118 s measured per version at v0.8.32.0.

### Step 5: the deck's own language is always covered

`languages_for` returns the deck's language as well as the one last viewed. For a compiled deck this costs no rendering after step 4. A deck viewed in another language gets that one rendered too.

Test: a deck last viewed in another language keeps its compile renders counted.

## 3. Decisions

- **D1: slides with `\SMFinalStateForStudents`, in student views. Decided 2026-11-01: accept the PDF as finished.** No rendering for them after a compile, and the reveal bar shows one step for them in student views, which is what students get. The instructor view keeps every step. This was the alternative to my recommendation, which was to keep sweeping them (about 142 units) so the bar stayed as it is.
- **D2: contents and section slides in a compile. Decided 2026-11-01: take them from the PDF too**, about 300 units. Their page counts match, the PDF shows the deck's real layout, and they go stale when the deck file changes. Like the background renders today, they do not go stale when another slide's text changes.
- **D3: a slide called twice with the same key. Decided 2026-11-01: the simplest.** One stored render, showing whichever call's page number it was rendered with; the footer number of the other call may be off in the Preview. The user does not mind which.
