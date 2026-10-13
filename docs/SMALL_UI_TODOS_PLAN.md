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
