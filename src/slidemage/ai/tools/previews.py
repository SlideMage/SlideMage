"""The tools that refresh the cached previews (the PNG snapshots the Preview, the slide list's pages and
the appendix show without compiling anything): one slide, or every slide of one deck (v8.11.0).

They write only `.previews/slide_previews/`, and never another deck's files. They run beside an open
window: a slide renders through the same locked, reusable preview build as the Preview pane
(preview_build.py), a deck through the window's own compile slot (the same run as "Rerender all
previews for this deck", Workspace.refresh_deck_previews), so neither can race the GUI's compiles.
"""
from __future__ import annotations

import shutil
import threading
import time
from contextlib import contextmanager

from ... import compiler, preview_target, slide_language, slide_snapshot
from ...deck_editor import VIEW_INSTRUCTOR
from ...update_all_previews import file_stamp
from ...preview_requests import RenderRequest
from .base import ToolContext, ToolError, tool
from .slidemage import open_deck, slide_or_file, slide_target

DECK_TIMEOUT_S = 3600      # a whole deck is one long compile; a single slide has RenderRequest's own timeout
LISTED_MAX = 60            # slide ids named per list before "and N more"


def first_error_line(message: str) -> str:
    """The first TeX error line (`! ...`) of a failure message, else its first line."""
    lines = [line.strip() for line in message.splitlines() if line.strip()]
    return next((line for line in lines if line.startswith("!")), lines[0] if lines else "unknown error")


@contextmanager
def _deadline(ctx: ToolContext, seconds: float):
    """A cancel token that is set by the user's Stop (`ctx.cancel`) or after `seconds`."""
    token, finished = compiler.CancelToken(), threading.Event()

    def watch() -> None:
        deadline = time.monotonic() + seconds
        while not finished.wait(0.25):
            if ctx.cancel.is_set() or time.monotonic() >= deadline:
                token.request_stop()
                return

    threading.Thread(target=watch, daemon=True).start()
    try:
        yield token
    finally:
        finished.set()


@tool("refresh_preview",
      "Rerender the cached preview of one slide (the instructor view, as the open deck typesets it) so the "
      "Preview and thumbnails show its current source. Takes seconds. Reports done, or why it failed "
      "(the first LaTeX error). It does not show you the image: for that use render_preview.",
      {"slide": {"type": "string", "description": "A slide id (1y8) or a path; default the slide in focus."}})
def refresh_preview(ctx: ToolContext, args: dict) -> str:
    path = slide_or_file(ctx, args.get("slide"))
    context = ctx.workspace.context()
    own = slide_language.own_language(path.name)
    language = own if own in slide_language.TRANSLATION_LANGUAGES else context.language
    target = slide_target(ctx.project, open_deck(ctx) if context.deck is not None else None, path,
                          VIEW_INSTRUCTOR, language)
    if target is None:
        raise ToolError(f"{path.name} is not a slide file, so it has no preview.")
    if target.is_frozen_alone:
        raise ToolError(f"{path.name} is a frozen version; only the current slide has a cached preview.")

    def render(cancel):
        # capture_snapshot (the default) writes the cached PNGs; the PDF itself is not needed.
        pdf = preview_target.render(target, VIEW_INSTRUCTOR, language,
                                    log=lambda _line: None, cancel=cancel)
        shutil.rmtree(pdf.parent, ignore_errors=True)

    png = slide_snapshot.snapshot_path(ctx.project, target.bare_id, target.template, id_slug=target.id_slug)
    before = file_stamp(png)
    try:
        RenderRequest(render, lambda: None).wait(ctx.cancel)
    except RuntimeError as exc:
        raise ToolError(f"{target.bare_id}: the preview was not refreshed. {first_error_line(str(exc))}") from None
    stamp = file_stamp(png)
    if stamp is None or stamp == before:
        raise ToolError(f"{target.bare_id}: it compiled, but its cached preview could not be written.")
    return f"{target.bare_id}: preview refreshed ({slide_snapshot.TEMPLATES.get(target.template, target.template)})."


def _listed(slugs: list[str]) -> str:
    ids = [slide_language.bare_id(slug) for slug in slugs]
    return ", ".join(ids[:LISTED_MAX]) + (f" and {len(ids) - LISTED_MAX} more" if len(ids) > LISTED_MAX else "")


@tool("refresh_deck_previews",
      "Rerender the cached previews of every slide of one deck, and of no other deck (the same as SlideMage's "
      "'Rerender all previews for this deck'). One long compile: minutes for a big deck. Reports how many "
      "slides were refreshed and which ones failed.",
      {"deck": {"type": "string", "description": "Deck name; default the open deck."}})
def refresh_deck_previews(ctx: ToolContext, args: dict) -> str:
    deck = open_deck(ctx, args.get("deck"))
    with _deadline(ctx, DECK_TIMEOUT_S) as token:
        try:
            result = ctx.workspace.refresh_deck_previews(deck, token)
        except RuntimeError as exc:
            raise ToolError(str(exc)) from None
    if ctx.cancel.is_set():
        raise ToolError("The refresh was stopped by the user.")
    if token.is_set():
        raise ToolError(f"The refresh took longer than {DECK_TIMEOUT_S // 60} minutes and was stopped.")
    total = len(result.refreshed) + len(result.failed)
    if not total:
        return f"{deck.name} has no slides to refresh."
    lines = [f"{deck.name}: {len(result.refreshed)} of {total} slide preview(s) refreshed, {len(result.failed)} failed."]
    if result.refreshed:
        lines.append(f"Refreshed: {_listed(result.refreshed)}")
    if result.failed:
        lines.append(f"Failed: {_listed(result.failed)}")
        if result.error:
            lines.append(f"First error: {result.error}")
    return "\n".join(lines)
