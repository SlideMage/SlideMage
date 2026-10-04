# Slidemaster Manual

A concise reference for core functionality.

## Deck Version System

This project supports three deck versions:

| Deck | Purpose | Footer Text |
|------|---------|-------------|
| `instructor` | Instructor copy | `(slide id: xxx | instructor deck | date)` |
| `during-course` | Given to students at start | `(slide id: xxx | student course deck | date)` |
| `after-course` | Given to students at end | `(slide id: xxx | student final deck | date)` |

### Setting the Deck Version

In your deck file (e.g., `decks/slidemage-manual.tex` -- see its own `\ifdefined\deckversionoverride` block, the pattern every real course deck uses so SlideMage's own version checkboxes can drive it), add `\deckversion[]` after `\input{Slidemaster_preamble_uni-graz}`:

```latex
\input{Slidemaster_preamble_uni-graz}
\deckversion[instructor]           % or during-course, after-course
```

### Omitting Entire Slides

Use `\omitslide{}` instead of `\slide{}` for slides that should be excluded from the student decks:

```latex
% In deck file:
\slide{k7f-EN-Standard-content}      % in all decks
\omitslide{q4m-EN-Answer-key}        % instructor only
```

### Controlling Individual Reveal Steps

To hide specific reveal steps within a slide, wrap the step in
`\deckonly<overlay-spec>[versions]{content}` rather than tagging `\item`
itself: beamer's own `\item<overlay-spec>[...]` already uses a trailing
`[...]` for its own, unrelated purpose (the text to show before that item is
revealed), so a version list can't be layered onto `\item` the same way
without colliding with that existing meaning. `\deckonly{}` wraps the whole
`\item` (text and all) instead:

```latex
% Syntax: \deckonly<overlay-spec>[versions]{content}

\begin{itemize}
  \item Always visible (no tag needed)
  \deckonly<2>[during-course,after-course]{\item Hidden in instructor deck}
  \deckonly<3>[instructor]{\item Instructor only (answer reveal)}
\end{itemize}
```

**Rules:**
- Untagged content (plain `\item`, or `\deckonly<4>{...}` with no `[...]`) is
  visible in all decks
- Tagged steps (the `[versions]` argument) appear only in the specified
  versions
- `\deckuncover<overlay-spec>[versions]{content}` and
  `\deckvisible<overlay-spec>[versions]{content}` follow the same syntax,
  wrapping beamer's own `\uncover`/`\visible` instead of `\only`

### Using `\pause` with Deck Versions

The standard `\pause` command works normally in all decks. For cases where you want to control which deck versions see step-by-step reveals, use `\conditionalpause`:

```latex
% Pause only for instructor deck:
\conditionalpause[instructor]

% Pause for instructor and after-course decks:
\conditionalpause[instructor,after-course]

% Pause for all decks (same as \pause):
\conditionalpause[instructor,during-course,after-course]
```

`\deckrevealfinal[step]{content}` is the same idea for an `\only`-style reveal (a picture, a tikz overlay): the instructor deck builds it from overlay `step` (default 2), every other version shows the content at once with no extra pages. (`\deckreveal`, by contrast, omits the content from the during-course deck.)

### Including Slides Conditionally

Use `\conditionalslide[versions]{ID}` instead of `\slide{ID}` to include a slide only in specified deck versions:

```latex
% Slide visible in instructor and after-course decks:
\conditionalslide[instructor,after-course]{xyz-Answer-key}

% Slide visible only in during-course deck:
\conditionalslide[during-course]{xyz-Demo-slide}
```

### Showing a Slide at Several Places, With Different Reveal Steps

Use `\slidestep{ID}[versions]{steps}` to include the same multi-step slide at several places of a deck, each time showing only some of its overlay steps, and different steps per deck version:

```latex
\slidestep{egk-EN-Structure-of-a-Scientific-Paper-Overview}[instructor]{1,2}
\slidestep{egk-EN-Structure-of-a-Scientific-Paper-Overview}[during-course,after-course]{1}
```

`steps` is a beamer overlay specification without the angle brackets (`1,2`, `3`, `2-`). A call that does not list the current deck version does nothing (it does not count as a frame either, so slide numbers stay identical in all versions). The presenter deck compiles as the instructor version. The slide file itself uses plain overlay specifications and no version conditionals. See README.md, "`\slidestep`", for the details.

### Compiling Different Versions

Compile each deck version separately:

```bash
# Instructor version (default)
lualatex test.tex

# During-course version
# Edit deck file: \deckversion[during-course]
lualatex test.tex

# After-course version
# Edit deck file: \deckversion[after-course]
lualatex test.tex
```

### Multi-Deck Compilation

Use SlideMage (`slidemage`) instead of
editing a deck's `\deckversion[]` by hand: its checkbox table lets you compile
any combination of Instructor/During-course/After-course, whole-deck or
split into one PDF per chapter, in a single run -- see
[SlideMage.md](SlideMage.md).

---

## Accessibility: image descriptions and transcripts

Every image is either **decorative** (an illustration, icon or logo that adds
nothing to the slide text) or **informative** (a chart, screenshot or photo a
reader needs described). That classification, along with its short and long
description, lives in `media/alt-text.json` — one record per image, shared
across every slide that uses it, so an image only needs describing once.
**Do not hand-edit that file** — SlideMage writes it, and it carries a
hash per image that tracks whether the description is still current.
(`media/alt-text.csv` also exists, but only as a generated compile-time copy
of the JSON store's role/short-alt columns — the LaTeX/Lua side that runs at
compile time reads that one, since it has no JSON support.)

At compile time, role decides what happens to each image:

- decorative → marked as a PDF `/Artifact`, so a screen reader skips it
  instead of announcing a bare filename;
- informative → its short alt text is typeset beside it invisibly, so text
  extraction (the route a screen reader takes through an untagged PDF)
  finds it.

One thing stays specific to a slide rather than shared: the **takeaway** —
why an image is on *that* slide. It has a default (set automatically the
first time you write one), and a slide can override it independently via a
"Set as default" button that pushes new text up without touching any other
slide's own override.

Everything is driven from SlideMage's **Images** tab:

| Action | What it does |
|---|---|
| **Draft all…** | Runs a local vision model over every image still needing a description. Resumable — stop and resume across sessions. |
| **Draft descriptions** | Same, for the selected slide only. |
| **Tune prompt…** | Re-draft one image with an editable prompt and a per-image hint, iterating without saving until you accept. |
| **Mark reviewed** | Records that you checked the description against the image. |
| **Clear draft** | Discards an unreviewed draft. Never touches a reviewed one. |
| **Generate transcript** | Writes a Markdown + HTML transcript of a deck to `transcripts/`. |

**Drafts are never trustworthy until reviewed.** On faint scanned charts the
model will invent plausible-looking values; on linear-axis charts the flat
early region reads worst. The tab shows each image at full size for exactly
this reason.

Transcripts are generated for **during-course and after-course only**, resolve
`\omitslide`/`\conditionalslide`/`\deckonly` exactly as the PDF compile does,
keep PDF slide numbering, and never include `\note{}` content.

A slide can also carry a free-text **transcript summary**, independent of
any image — it shows up at the top of that slide's transcript entry,
before its own body text. Set it in the **slide-source editor** (a
"Transcript summary" field with its own "Save summary" button), not the
Images tab: a summary should work for any slide, including ones with no
images, which the Images tab's own list never shows.

Full detail is in README.md's "Screen-reader accessibility"/"Describing
images"/"Describing tikz illustrations"/"Accessible transcripts" sections.

## Slide previews

SlideMage caches a PNG of how each slide last looked, refreshed
automatically whenever a compile happens to touch it (rendering it on its
own, or compiling a whole deck's instructor version). Previews are kept
per institution template (so a second institution's own preamble, if you
ever add one, gets its own separate cache rather than sharing/corrupting
Uni Graz's). Several ways to
use the cache, all instant — no LaTeX compile needed:

- **Hover** over a slide's id in the deck editor for a quick preview
  tooltip.
- Click **Preview** (the deck editor's per-row button, or the button next
  to "Render to PDF" in the slide-source editor) for a larger look. If
  nothing's cached yet, "Render now" inside the popup generates one.
- Switch **View: List / Thumbnail / Grid** (top right of the deck
  editor's toolbar). **Thumbnail** shows a rendered thumbnail below each
  slide's id, alongside its usual row controls — nothing is hidden or
  replaced, it just adds the image. **Grid** browses the whole deck as
  visual cards instead, grouped by chapter — click a card to open that
  slide; no editing controls here, it's for a quick overview.
- Use the **chapter dropdown** (top toolbar, between Undo and Close) to
  jump straight to a chapter instead of scrolling for it; its heading
  lands right at the top of the view, in whichever View mode you're in.
- In List or Thumbnail view, each `\section{...}` appears as an editable
  section row, even when it has no slides yet. Use **Add section** to append
  one, or **+ section** beside a slide to insert one before that slide. A
  section row can be renamed or removed while keeping its slides. Its
  arrow buttons move the heading past the adjacent slide, changing which
  section contains that slide; moving past another section carries the
  section's slides with it. Use **+ slide here** to add the first slide to
  an empty section. These changes update the deck's `.tex` source
  and can be undone with **Undo**.
- A slide's number in List or Thumbnail view is editable: type a new
  position and press Enter to move the slide there. The slides between the
  old and new position shift one place to make room, and the moved slide
  joins the section of the slide whose number it takes.

This is a cache, not a live view — it only updates when something actually
compiles, so it can lag behind an edit you haven't recompiled yet. "Render
to PDF" in the slide-source editor is unaffected and always compiles your
current buffer directly.

To refresh every slide's preview at once — e.g. after a theme change —
click **Update previews** in the main toolbar and confirm. No institution
to pick: it scans every deck (active and archived) for which slides it
actually uses under which template, compiles one temporary deck per
template containing exactly those slides, and deletes any cached preview
no deck uses any more. It's one long compile (well over an hour is
plausible for the whole project) that runs in the background but
occupies the compile slot, so no other compile can start until it
finishes.

## Quick Reference

| Command | Purpose |
|---------|---------|
| `\slide{ID}` | Include slide in all decks |
| `\omitslide{ID}` | Exclude from student decks |
| `\conditionalslide[versions]{ID}` | Include slide only in specified versions |
| `\slidestep{ID}[versions]{steps}` | Include slide only in specified versions, showing only the given reveal steps |
| `\deckonly<1>[versions]{...}` | Control per-step visibility |
| `\conditionalpause[versions]` | Pause for specified versions only |
| `\deckversion[instructor]` | Set deck version |

---

## Notes

- The deck version system does not use beamer's handout mode
- Each version compiles as a separate PDF with its own overlay sequence
- Footer date format: `YYYY-MM-DD HH:MM`
