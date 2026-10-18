"""The tools that refresh the cached previews (the PNG snapshots the Preview, the slide list's pages and
the appendix show without compiling anything): one slide, or every slide of one deck (v8.11.0).

They write only preview caches under `.previews/`, and never deck sources. They run beside an open
window: a slide renders through the same locked, reusable preview build as the Preview pane
(preview_build.py), a deck through the window's own compile slot (the same run as "Rerender all
previews for this deck", Workspace.refresh_deck_previews), so neither can race the GUI's compiles.
"""
from __future__ import annotations

import threading
import time
from contextlib import contextmanager

from ... import compiler, slide_language
from .base import ToolContext, ToolError, tool
from .slidemage import PREVIEW_VIEW, open_deck, preview_batch_output, slide_or_file

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
      "Rerender one slide's saved source into the preview cache; no images are returned for inspection. "
      "view may be instructor, during-course, after-course, or all; omitted view defaults to all "
      "so switching course views has matching previews. Instructor refresh also updates legacy "
      "thumbnails. Reports each view as rendered/cached/displayed/superseded/hidden/failed. "
      "Use render_preview(view=...) to look at images, including unsaved edits.",
      {"slide": {"type": "string", "description": "A slide id (1y8) or a path; default the slide in focus."},
       "view": {**PREVIEW_VIEW, "description": PREVIEW_VIEW["description"] + " Default: all views."}})
def refresh_preview(ctx: ToolContext, args: dict) -> str:
    text, _ = preview_batch_output(ctx, slide_or_file(ctx, args.get("slide")),
                                   args.get("view", "all"), saved=True)
    return text


def _listed(slugs: list[str]) -> str:
    ids = [slide_language.bare_id(slug) for slug in slugs]
    return ", ".join(ids[:LISTED_MAX]) + (f" and {len(ids) - LISTED_MAX} more" if len(ids) > LISTED_MAX else "")


@tool("refresh_deck_previews",
      "Refresh the exact occurrence previews of one deck using the shared render cache. "
      "scope defaults to all course views; selected uses the workspace's selected view. "
      "Reports partial failures and per-view cached, rendered and hidden counts.",
      {"deck": {"type": "string", "description": "Deck name; default the open deck."},
       "scope": {"type": "string", "enum": ["all", "selected"],
                 "description": "All course views (default) or the selected course view."}})
def refresh_deck_previews(ctx: ToolContext, args: dict) -> str:
    deck = open_deck(ctx, args.get("deck"))
    scope = args.get('scope', 'all')
    if scope not in ('all', 'selected'):
        raise ToolError("scope must be all or selected")
    with _deadline(ctx, DECK_TIMEOUT_S) as token:
        try:
            result = (ctx.workspace.refresh_deck_previews(deck, token, scope=scope) if 'scope' in args
                      else ctx.workspace.refresh_deck_previews(deck, token))
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
    if result.details is not None:
        details = result.details
        lines.append(f"{details.scope} views, {details.language}: " + ", ".join(
            f"{details.count(status)} {status}" for status in
            ('rendered', 'cached', 'hidden', 'failed', 'cancelled')))
        for item in details.failed:
            spec = item.request
            lines.append(f"Failed frame {spec.target.frame_number} ({spec.view}, "
                         f"{spec.target.id_slug}): {item.error or item.publication_status}")
    if result.refreshed:
        lines.append(f"Refreshed: {_listed(result.refreshed)}")
    if result.failed:
        lines.append(f"Failed: {_listed(result.failed)}")
        if result.error:
            lines.append(f"First error: {result.error}")
    return "\n".join(lines)
