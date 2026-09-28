""""Update previews": regenerate every slide's compile-time preview
snapshot (slide_snapshot.py) so it matches what every deck in the project
actually needs, and delete whatever's cached that no deck needs any more.

2026-08-16, direct instruction, replacing the original single-template
design: "each deck has a specific template linked to it... scan all decks
that I have, make a list of slide-template combinations, and
automatically render each slide for all templates that any deck uses
them with... the routine should also delete all rendered versions that
are no longer in use." There is no longer a template to *pick* -- every
deck already carries its own (slide_snapshot.detect_template(), from its
own preamble), so this scans every deck instead of asking.

For each (template, [slide ids]) group, builds one throwaway deck
containing just that group's own slides, compiles it through the
*normal* `compiler.run_job()` pipeline (instructor version), and deletes
the temp deck once the compile itself finishes. No new compile or
snapshot logic here at all -- run_job()'s own PDF-move-with-retry and its
slide_snapshot.capture_deck() hook already do the actual work; this
module's only job is building, per template, a deck file that hands them
exactly the slides that template actually needs.
"""
from __future__ import annotations

import re
import uuid
from typing import Optional

from . import deck_editor, slide_snapshot
from .compiler import CancelToken, CompileJob, LogCallback, run_job
from .deck_scan import Deck, scan_decks
from .slide_preview import DECKS_DIR, GENERIC_PREAMBLE

# The exact line GENERIC_PREAMBLE selects Graz with -- swapped wholesale
# for another institution's own \input{} line to build that template's
# preamble instead. Matches slide_snapshot.TEMPLATE_RE's own pattern
# (kept as a plain string here, not a shared regex, since this side needs
# to *substitute* a specific key, not merely detect one already present).
_GRAZ_INPUT = "\\input{Slidemaster_preamble_uni-graz}"

# qt_gui.py's own log parser watches every "==== PASS: <jobname> ->" line
# globally (it's the only channel this background compile has back to the
# GUI) to auto-open the resulting PDF when the "Auto-open" checkbox is on
# -- fine for a real per-deck row, but this job's own PDF is a throwaway
# megadeck nobody wants popping open, regardless of that checkbox
# (2026-08-15, direct instruction: "irrespective of the global Auto-open
# setting"). A recognizable prefix lets qt_gui.py exclude every one of
# this module's own PASS lines from that behavior without needing any
# other channel back from this module.
JOBNAME_PREFIX = "preview_all_"

# Matches a cached snapshot's own filename (slide_snapshot.snapshot_path):
# "<bare id>-<TemplateDisplayName>-<width>-<height>.png", e.g.
# "22s-UniGraz-1920-1080.png" (bare id first since 2026-08-17, direct
# instruction: "shift the three-letter slug to the front of the filename
# to facilitate searching" -- was "<TemplateDisplayName>-<bare id>-..."
# before that). A bare slide id can never itself contain "-" (\setSlideID
# takes everything up to the *first* "-", so by construction there isn't a
# second one to misparse), which is what makes `[^-]+` safe/unambiguous
# here -- anchoring the *template* half on the known display names
# (slide_snapshot.TEMPLATES' own values) is still cheap insurance against
# a stray file this module didn't itself produce.
_SNAPSHOT_FILENAME_RE = re.compile(
    r"^(?P<bare_id>[^-]+)(?:-(?:EN|DE|mult))?-(?P<template_name>" +
    "|".join(re.escape(name) for name in slide_snapshot.TEMPLATES.values()) +
    r")-\d+-\d+\.png$"
)
# The optional (?:-(?:EN|DE|mult))? group above (2026-08-24) recognizes
# slide_snapshot.snapshot_path()'s own new <Lang> segment so a migrated
# slide's cached files aren't silently treated as "not a recognized
# snapshot filename" and left un-prunable forever -- pruning itself still
# keys off bare_id only (language-independent, same as before): a slide
# renamed from one language to another leaves its *old* language's cached
# file behind as a harmless orphan rather than actively pruned, a known,
# minor gap (this cache is already documented as best-effort, never
# guaranteed-fresh) rather than something worth the added complexity of
# pruning by (bare_id, language) pairs for.


def needed_slides_by_template() -> dict[str, set[str]]:
    """Every (template, full id_slug) combination actually in use across
    every deck this project knows about -- active *and* archived, since
    an archived deck's own editor tab still shows cached previews, so its
    slides still need a cache same as any active deck's. Keyed by
    template key (slide_snapshot.TEMPLATES), not display name; values are
    full id_slugs (e.g. "22s-More-Exotic-Bonds", not "22s") since that's
    what a \\slide{} call in the temp deck needs -- _prune_stale_snapshots()
    below converts to bare ids itself, the shape a cached filename encodes.
    """
    needed: dict[str, set[str]] = {}
    for deck in scan_decks():
        template = slide_snapshot.detect_template(deck.preamble_text)
        bucket = needed.setdefault(template, set())
        for call in deck_editor.parse_slide_calls(deck):
            bucket.add(call.id_slug)
    return needed


def _prune_stale_snapshots(needed: dict[str, set[str]], log: LogCallback) -> None:
    """Delete every cached preview file whose (template, bare id) isn't in
    `needed` any more -- a slide no deck references under that template
    (removed from every deck, or moved to a different institution) leaves
    an orphaned file otherwise, the same class of dead weight the old
    flat-naming cleanup (ALT_TEXT_NOTES.md, Phase 8) removed by hand once.
    """
    valid_bare_ids_by_template_name: dict[str, set[str]] = {
        slide_snapshot.TEMPLATES.get(template, template):
            {slide_snapshot.bare_id(slug) for slug in full_slugs}
        for template, full_slugs in needed.items()
    }
    removed = 0
    for path in slide_snapshot.SNAPSHOT_DIR.glob("*.png"):
        match = _SNAPSHOT_FILENAME_RE.match(path.name)
        if match is None:
            continue  # not a recognized snapshot filename -- leave it alone
        template_name = match.group("template_name")
        bare_id = match.group("bare_id")
        if bare_id not in valid_bare_ids_by_template_name.get(template_name, set()):
            path.unlink(missing_ok=True)
            removed += 1
    if removed:
        log(f"    (removed {removed} stale preview file(s) no longer used by any deck)")


def _preamble_for(template: str) -> str:
    if template not in slide_snapshot.TEMPLATES:
        template = slide_snapshot.DEFAULT_TEMPLATE
    return GENERIC_PREAMBLE.replace(
        _GRAZ_INPUT, f"\\input{{Slidemaster_preamble_{template}}}")


def _build_deck_text(template: str, slide_ids: list[str]) -> tuple[str, int]:
    """(full deck text, offset just past `\\begin{document}`) -- the
    latter is `Deck.preamble_end`, needed so `Deck.preamble_text` (used by
    run_job()'s own template-detection call) returns exactly the preamble
    this function built, not something offset by a stray rstrip().
    """
    preamble = _preamble_for(template)  # already ends "\begin{document}\n"
    body = "\n".join(f"\\slide{{{id_slug}}}" for id_slug in slide_ids)
    text = f"{preamble}{body}\n\\end{{document}}\n"
    return text, len(preamble)


def _run_one_template(
    template: str, slide_ids: list[str], log: LogCallback,
    cancel: Optional[CancelToken], base_jobname: Optional[str],
) -> bool:
    """Compile one throwaway deck for exactly this template's own needed
    slides -- same mechanics run() always used, just scoped to a subset
    of the project's slides instead of every one of them."""
    DECKS_DIR.mkdir(parents=True, exist_ok=True)
    jobname = base_jobname or f"{JOBNAME_PREFIX}{uuid.uuid4().hex[:8]}"
    temp_path = DECKS_DIR / f"_slidemage_{jobname}.tex"
    text, preamble_end = _build_deck_text(template, slide_ids)
    temp_path.write_text(text, encoding="utf-8")

    deck = Deck(
        name=jobname,
        path=temp_path,
        archived=False,
        text=text,
        supports_version=True,
        uses_biblatex=True,
        preamble_end=preamble_end,
        chapters=[],
        output_folders={},
    )
    job = CompileJob(deck=deck, version="instructor", chapter=None)
    try:
        return run_job(job, log, cancel=cancel)
    finally:
        # Safe as soon as the compile itself is done: nothing downstream
        # (the PDF move, the snapshot capture -- both possibly still
        # running in the background, see compiler.py) touches this source
        # file again, only the PDF it already produced.
        temp_path.unlink(missing_ok=True)


def run(log: LogCallback, cancel: Optional[CancelToken] = None,
       base_jobnames: Optional[dict[str, str]] = None,
       needed: Optional[dict[str, set[str]]] = None) -> bool:
    """Scan every deck for which (template, slide) combinations it
    actually needs, compile one throwaway deck per template containing
    just that template's own needed slides, then delete every cached
    preview file that isn't part of that valid set any more. Returns
    whether every template's compile succeeded.

    base_jobnames: {template key: jobname} -- lets the caller (qt_gui.py)
    pick each template's own job name in advance and register a
    progress-status label for it before that compile's first log line --
    and therefore the status lookup for it -- ever arrives. A template
    with no entry falls back to a fresh uuid-based one.

    needed: the result of needed_slides_by_template(), if the caller
    already computed it (e.g. to show a confirmation dialog first) --
    recomputed here if not given, so a direct/test call doesn't need to
    call that separately first.
    """
    if needed is None:
        needed = needed_slides_by_template()
    total_slides = sum(len(ids) for ids in needed.values())
    log(f"==== Update previews: {total_slides} slide-template combination(s) "
       f"across {len(needed)} template(s) ====")

    all_ok = True
    for template in sorted(needed):
        slide_ids = sorted(needed[template])
        template_name = slide_snapshot.TEMPLATES.get(template, template)
        if not slide_ids:
            # A real, if unusual, case -- e.g. this project's own
            # test-ibk.tex/test-mci.tex \input{} a shared test-slides
            # fragment rather than calling \slide{} directly, so they
            # detect a template with nothing of their own to compile.
            # Still counts toward _prune_stale_snapshots() below (an
            # empty valid set for a template means every cached file
            # under it is stale), just nothing to spend a compile on.
            log(f"---- {template_name}: no directly-\\slide{{}}'d slides, "
               f"nothing to compile ----")
            continue
        log(f"---- {template_name}: {len(slide_ids)} slide(s) ----")
        base_jobname = (base_jobnames or {}).get(template)
        ok = _run_one_template(template, slide_ids, log, cancel, base_jobname)
        all_ok = ok and all_ok
        if cancel is not None and cancel.is_set():
            break

    if cancel is None or not cancel.is_set():
        _prune_stale_snapshots(needed, log)
    return all_ok
