# Responsive layout plan: window sizes, resizable and hideable sidebars

Status: draft, 2026-10-12. Each step needs the user's go; pause after each committed step.
Cost figures are rough, from the usage calibration of ~5% of a 5-hour window per ~100k agent tokens.

## What happens today (measured)

Measured by rendering the workspace window offscreen with the demo project at 1920, 1280, 1100, 960
and 800 px width:

- **The window cannot be narrower than 1,568 px.** Its minimum width comes from the top bar, whose items
  never shrink: deck switcher 176, View as + Instructor/During course/After course 309, EN/DE 168,
  Saved 34, Preview/Split/Source/Details 332, Compile PDF · Instructor 233, Images 80, ⋮ 48, plus 14 px
  spacing and 24 px margins. The default size (1280 × 860) is silently widened to 1,568, so on a
  1,366, 1,440 or 1,536 px wide screen (or 1920 at 125 % scaling) the window runs past the screen edge.
- **The centre column needs 913 px even when it shows Preview/Source/Details** (whose own minimum is
  368): the centre is a stack of pages, and a stack takes the largest minimum of all its pages -- the
  hidden Images page needs 913. So even with a compact top bar, the columns alone need about 1,560 px.
- **The slide list is fixed at 280 px**; it cannot be made wider or narrower.
- **The right column** can already be dragged between 340 and 900 px and remembers its width, but cannot
  be hidden. Its split between the side panel and the assistant starts at fixed heights; at 600 px window
  height the assistant's suggestions are squeezed into a tiny scrolling area.
- **Window size and position are not remembered**; every start opens at the default size.
- Minimum height is 548 px.

## Goals

1. The window works from **1024 × 640** up to 4K: nothing runs off-screen, nothing overlaps or is cut
   without an ellipsis and a tooltip.
2. Both sidebars can be **dragged wider or narrower**, and the widths are remembered.
3. Both sidebars can be **hidden and shown again** (command, shortcut, button), and that is remembered.
4. The window opens at its last size and position, fitted to the screen it is on.

## Steps

| Step | What it does | Cost |
| --- | --- | --- |
| L1 Centre minimum | The centre stack's minimum is the shown page's (Preview/Source/Details: 368 px), not the hidden Images page's. The Images page itself shrinks too: its image list and form columns get sensible minimums (target ≤ 700 px). | ~20-40k, 1-2% |
| L2 Compact top bar | The top bar adapts to its width in three steps instead of forcing 1,568 px. **Full** (≥ 1,600 px): as today. **Compact** (1,250-1,600): "View as" label hidden, "Saved" becomes a dot with a tooltip, deck name elided (max ~180 px, full name in the tooltip), Compile label shortened to "Compile ▾". **Narrow** (< 1,250): the view and mode switches show short labels or icons with tooltips (Instr. / During / After; Preview / Split / Source / Details as icons), Images moves into ⋮. Target minimum width of the top bar: ≤ 1,000 px. | ~60-100k, 3-5% |
| L3 Window size and position | Remember size, position and maximised state (Qt saveGeometry/restoreGeometry, per user and machine like the other UI settings); on first start, and when the remembered screen is gone, open at ~90 % of the available screen area, never larger. Window minimum 1024 × 640. | ~20-30k, 1-2% |
| L4 Resizable slide list | The slide list (left column) can be dragged between ~220 and ~520 px like the right column, and the width is remembered (`left_column_width`). Slide rows elide long titles; thumbnails keep their size. Double-clicking a splitter handle resets that column to its default width. | ~30-50k, 2-3% |
| L5 Hide and show sidebars | Commands "Hide/Show slide list" and "Hide/Show side panel" in the command palette and in ⋮ → View, with shortcuts (proposal: **Ctrl+Alt+[** and **Ctrl+Alt+]**; Ctrl+B is taken by bold in the editor -- checked against all registered shortcuts in the step). Two small toggle buttons at the left and right ends of the top bar show the state. Dragging a column below its minimum collapses it (splitter snap), and the toggle brings it back at its last width. Hidden/shown is remembered. The Images page keeps hiding the right column itself, without changing the user's choice. | ~50-80k, 3-4% |
| L6 Right column height | The split between the side panel and the assistant is remembered as a ratio; both parts get minimum heights (the assistant at least its input, mode row and two suggestion lines), and at small window heights the side panel gives way first. Suggestion buttons wrap instead of forcing a scroll area. | ~30-50k, 2-3% |
| L7 Layout tests and screenshots | GUI tests: the window's minimum size is ≤ 1024 × 640; at 1024, 1280, 1600 and 1920 px no top-bar item is cut without an ellipsis; widths, hidden state and geometry survive a restart; the shortcuts toggle the columns. A small tool (`tools/ui_screenshots.py`) renders the workspace offscreen at those sizes for a visual check before a release. | ~40-60k, 2-3% |

Order: L1 and L2 first (they remove the 1,568 px minimum, the actual bug), then L3, then L4-L5 (the new
options), then L6-L7.

## Decisions (recommendations in bold)

- **Shortcuts:** **Ctrl+Alt+[ / Ctrl+Alt+]** for the slide list / side panel. Alternatives: F9 / F10, or
  only the command palette and buttons.
- **Automatic hiding on narrow windows:** **no** -- columns only hide when the user hides them; the compact
  top bar and the column minimums keep 1024 px usable. (Alternative: below ~1,100 px the side panel
  hides itself and comes back when the window grows.)
- **Where the hide/show buttons sit:** **at the outer ends of the top bar** (left of the deck switcher,
  right of ⋮). Alternative: only in ⋮ → View and the palette.
- **Remembered per project or per user:** **per user and machine** (window geometry and column widths are
  about the screen, not the project), like the update settings. Today the right column's width is kept in
  the project's `.slidemage/app_settings.json`; it would move along with the new settings.

## Progress

| Step | Status |
| --- | --- |
| L1 Centre minimum | Done, v8.0.21: columns need 996 px instead of ~1,560. |
