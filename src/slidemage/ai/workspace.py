"""The agent's window into the application: what the user has open, and the few
things only the application can do for it (2026-10-10, UI redesign step 10a).

`Workspace` is a plain class, not a Qt object: the default implementation is a
headless project (no editor buffers; nothing to ask; a compile runs right
here), which is what the tests and any command-line use get. The chat in the
main window (10b) subclasses it and overrides the methods that need widgets.

Threading contract: the agent loop runs on a worker thread and calls every
method here on that thread. An implementation that touches widgets (buffers,
dialogs, the job panel) must do that work on the GUI thread itself -- e.g.
through a blocking queued call -- and return the result; the default
implementation touches no widget, so it may be called from anywhere. Nothing
in ai/ imports Qt.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .. import compiler, preview_target, slide_snapshot, update_all_previews
from ..deck_scan import Deck
from ..project import ProjectContext
from ..selection import Selection, SelectionError
from ..preview_requests import RenderRequest
from .providers import ChatProvider


@dataclass(frozen=True)
class WorkspaceContext:
    """What the user is looking at when they send a request."""
    deck: Deck | None = None             # the open deck
    slide_id: str | None = None          # bare id of the focused slide
    path: Path | None = None             # the file the Source view shows (a slide, a deck, the .bib ...)
    view: str = "instructor"             # "View as": instructor / during-course / after-course
    language: str = "EN"                 # the language being edited
    footer_timestamp: bool = True        # previews show the compile time in the footer


class Workspace:
    def __init__(self, project: ProjectContext, context: WorkspaceContext | None = None) -> None:
        self.project = project
        self._context = context or WorkspaceContext()

    @property
    def root(self) -> Path:
        return self.project.root.resolve()

    def context(self) -> WorkspaceContext:
        """A snapshot of the focus, taken when a request starts."""
        return self._context

    def is_open_deck(self, path: Path) -> bool:
        """Recheck the live deck at commit time, beyond the request's focus snapshot."""
        deck = self.context().deck
        return deck is not None and deck.path.resolve() == path.resolve()

    # -- editor buffers: a file that is open is edited there, not on disk --------------------------

    def is_open(self, path: Path) -> bool:
        """Whether `path` has an editor buffer (clean or not)."""
        return False

    def is_dirty(self, path: Path) -> bool:
        """Whether the buffer of `path` has unsaved edits."""
        return False

    def buffer_text(self, path: Path) -> str:
        """The text of an open file's buffer, unsaved edits included ("\\n" line ends)."""
        raise FileNotFoundError(path)

    def buffer_snapshot(self, path: Path) -> tuple[str, bool]:
        """Buffer text and dirtiness together; GUI implementations also refresh clean buffers."""
        return self.buffer_text(path), self.is_dirty(path)

    def apply_to_buffer(self, path: Path, expected_text: str, new_text: str) -> str | None:
        """Replace the buffer's whole text as one undo step, leaving it unsaved. None when done;
        else why not: the buffer is read-only (a frozen version), or its text is no longer
        `expected_text` (the user typed while the edit waited for their answer)."""
        return "it is not open for editing"

    def selection(self) -> Selection:
        """The text selected in the slide the editor shows (selection.capture); SelectionError says why there is none."""
        raise SelectionError("There is no editor here, so nothing is selected.")

    # -- asking and telling the user ---------------------------------------------------------------

    def confirm_edit(self, call_id: str, path: Path, before: str, after: str) -> bool:
        """Show the change of the tool call `call_id` (whole-file texts; a new file has `before` "") and
        wait for Apply or Reject. Headless there is nobody to ask, so nothing is applied."""
        return False

    def confirm_cloud(self, provider: ChatProvider) -> bool:
        """The first cloud request in a project: say what leaves the machine (the focused slide,
        files the model reads, rendered previews) and ask once. True to go ahead. Headless there is
        nobody to ask, so nothing is sent."""
        return False

    def file_changed(self, path: Path, previous_text: str | None) -> None:
        """A tool wrote `path` on disk (`previous_text` None: it is new). The application refreshes
        what shows it: the slide list, a clean buffer, the deck header sync."""

    def review_changed(self) -> None:
        """Refresh slide labels after Claude provenance changes, including buffer edits."""

    def show_slide(self, path: Path) -> None:
        """Bring the slide file `path` into focus for the user: its preview and its source. Headless
        there is nobody to show it to."""

    def render_preview(self, target, text, view, language, footer_timestamp, cancel) -> bytes:
        """Headless render; GUI workspaces share the pane's build and publication path."""
        def render(token):
            pdf = preview_target.render_text(target, text, view, language, footer_timestamp=footer_timestamp,
                                             log=lambda _: None, capture_snapshot=False, cancel=token)
            png = slide_snapshot.page_png(pdf, 1280)
            if png is None:
                raise RuntimeError('The rendered PDF could not be read')
            return png

        return RenderRequest(render, lambda: None).wait(cancel)

    def translate_slide(self, path: Path) -> str:
        """Start SlideMage's own translation of the slide `path` (its Translate bubble); what to tell the
        model."""
        return "SlideMage cannot translate here: there is no window."

    def switch_to_deck_mode(self) -> str:
        """Widen the Claude Code scope from one slide to the deck; what to tell the model."""
        return "There is no scope to widen here."

    # -- compiling -------------------------------------------------------------------------------

    def compile_deck(
        self, deck: Deck, kind: str, cancel: compiler.CancelToken, log: Callable[[str], None],
    ) -> dict[str, bool]:
        """Compile `deck` as compiler.build_jobs(deck, kind) says; {jobname: success}. Blocks until
        done (the Stop of the chat ends it through `cancel`). The window overrides this to run
        the jobs through its job panel."""
        return compiler.run_jobs(self.project, compiler.build_jobs(deck, kind), log, cancel)

    def refresh_deck_previews(self, deck: Deck, cancel: compiler.CancelToken) -> update_all_previews.DeckResult:
        """Rerender the cached previews of every slide of `deck` and no other deck's. Blocks until the
        snapshots are written (the Stop of the chat ends it through `cancel`). The window overrides this
        to run it on the compile slot, with its job panel; raises RuntimeError when it cannot run."""
        return update_all_previews.rerender_deck(self.project, deck, lambda _line: None, cancel)
