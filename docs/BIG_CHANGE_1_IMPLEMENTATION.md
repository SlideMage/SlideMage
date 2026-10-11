# BIG CHANGE 1: the language switch follows translations

Implemented 2026-10-11, SlideMage 7.0.0.

The top-bar EN / DE switch now selects each deck slot's linked slide across
the list, preview, source editor, Details and side panels. Saving and rendering
in DE mode use the German file. Each source buffer retains its unsaved edits
when changing languages.

## Decisions

- Keep deck source unchanged and resolve calls in temporary compile wrappers.
  A separately listed translation is folded into its original slot, including
  a translation appended in a different section. Repeated original calls and
  different reveal-step calls remain separate occurrences.
- If there is no partner, retain the called file and its version pin; show the
  existing "No DE version" or "No EN version" flag. Multilingual and legacy
  untagged slides keep their existing behavior.
- A translation is a separate slide, with an independent id and version
  history. An English pin applies in EN. DE uses the German translation's
  current file; version numbers are never transferred between slides.
- The original call owns placement, visibility, view conditions and reveal
  steps. Deck actions edit that physical call. Removing a logical slot removes
  its separately listed partner calls too, preventing their reappearance.
- Keep the Language panel and outdated-translation chip. Slide-content panels
  follow the displayed file; the Visibility panel edits the original call.

The project's version policy requires a major bump for changed workflows.
Version 7.0.0 records the new linked-pair behavior in release history and the
quiet project-compatibility notice. No project-format migration is required.
To include both languages as independent slides, use unlinked copies.

## Implementation

`deck_language.py` resolves existing header links by permanent id, supports
one-sided links and renamed partners, and refuses ambiguous reverse links.
It leaves comments, verbatim examples and disabled TeX blocks intact. A single
resolution shares its file/link scan across every slot.

`deck_outline.py` separates the displayed call from the original physical
call and assigns language-independent row keys. Focus and selection survive
language switches. The centre column, source buffers, Details and side panels
use the displayed file; deck editing uses the original call and offsets.

Open-deck whole, chapter, presenter and selected-page jobs carry the workspace
language. The compiler resolves local body fragments and generated appendix
links as well. Alternate-language job names add `-de` or `-en`; an explicit
output filename declared in the deck still follows the existing output-path
rules. The precompile check and progress counter use the resolved slides.
Selected-page compiles match the translated footer ids and replace the
translated pages. Compile records include original decks and inlined fragments
even when TeX reads only a temporary wrapper.

Cleanup preserves linked translations and the current headers that provide
their links, including when the original call pins an older version. Update
previews renders both files independently. Usage panels and generated deck
headers include partners used through language resolution; snapshots retain
the original inputs needed to resolve those partners.

Raw LaTeX compiles outside SlideMage retain the deck's literal calls. Several-
deck/all-deck jobs and project-wide exports use each deck's default language.

## Validation

Final automated suite: **1,522 passed, 6 skipped**. Ruff and whitespace checks
for the implementation changes passed.

Regression coverage includes linked translations outside the deck, late
partner calls, one-sided links, renamed/deleted partners, independent pinned
versions, hidden slides, repeated calls, reveal steps, nested fragments,
appendix links, selection/focus, German source saves and buffer renders, and
pending panel edits across language switches.

Real LuaLaTeX checks used a temporary project with the Gotham theme and the
SlideMage preamble. English and German whole-deck output each contained two
pages: the requested language's slide and the English fallback. The checks
verified the English pin, independently versioned current German translation,
duplicate suppression, separate default PDF names, saved and buffer German
previews, and a German selected-page replacement. English output and source
remained unchanged. Test artifacts stayed in the temporary project.
