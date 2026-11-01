# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""What a plugin may use from SlideMage: the Host that SlideMage passes to activate(), and the types around it.

A plugin imports this module (and nothing else from SlideMage), so it is standard library only: no PySide6 at
import, and no other SlideMage module at runtime. The concrete host lives in slidemage.plugins; this file is
the contract, versioned by API_VERSION (a plugin's manifest names the version it was written for).

Conventions of all calls:

- Threads. Every call is made on the UI thread, and every callback the plugin hands over (run, enabled, when,
  build, done) is called on the UI thread, except soon (see add_render_priority) and the work of
  run_in_background, and ChatSurfaceContext.build_tools (which may be called by an MCP worker).
- When. The add_* calls are for activate() only; after it returns, they raise RuntimeError. activate() runs at
  start, so nothing in it may use the network or take long.
- Decks. A Deck is a snapshot of one deck as SlideMage last read it. Changing the file does not change the
  object; a call that writes checks the file against deck.text and raises StaleFileError.
- Deck edits. insert_slides and edit_deck_text are edits like SlideMage's own: after one succeeds SlideMage rescans
  the deck, refreshes its views and records one undo step, so the next Deck it hands out has the new text; the Deck
  the plugin holds stays as it was and a second write with it raises StaleFileError. While the Deck settings sheet
  of that deck has unsaved changes on its General or PDF output tab, both calls are refused with EditRefusedError
  (nothing is written) and the footer action of a plugin tab is disabled; the user saves or discards those changes
  first. An edit made while the sheet is clean is taken over by the sheet: its own settings are read again from the
  new text, so a later Save of the sheet does not conflict with it.
- Widgets. Widgets are PySide6 widgets, typed Any here so that this module needs no PySide6.
- Lazy AI definitions. Task and the named task constants (TRANSLATE, FIX_LATEX, UPDATE_TRANSLATION, PROOFREAD,
  CONCISE, TITLE, NOTE, SUMMARISE, READABLE, REWRITE, PROOFREAD_SELECTION and REWRITE_PRESETS) define tasks.
  translate_request, update_request, proofread_request, concise_request, title_request, rewrite_request,
  proofread_selection_request, note_request, summarise_request, fix_request, readable_request, answer_note,
  repair_request and check build requests and validate answers. SlideContext, DraftResult, TranslationResult, build_prompt, draft_from_fields,
  effective_system_prompt, IMAGE_DESCRIPTION_SCHEMA, ImageEntry, en_text_hash, PromptConfig and get_effective_prompt provide
  image drafting and translation data and prompts. de_address and glossary read translation style.
  IMAGE_DESCRIPTION_RULES and CLAUDE_CODE_PRE_APPROVED describe image rules and Claude Code's allowed tools.
  Outcome is the neutral task result. CancelToken supports process-aware cancellation for ai_tools. These names
  load their implementation on first access; importing plugin_api itself uses only the standard library.
"""
from __future__ import annotations

import importlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Protocol, TypeVar

if TYPE_CHECKING:
    import threading

    from .ai.providers import ChatProvider
if TYPE_CHECKING:       # for type checkers only: at run time these load on first use (see __getattr__)
    from .ai.agent_types import (  # noqa: F401
        EDIT_ASK, EDIT_AUTO, AgentEvent, AgentMessage, AssistantMessage, Done, EditApplied, EditProposed,
        EditRejected, TextDelta, ToolCall, ToolFinished, ToolResult, ToolResultsMessage, ToolSpec, ToolStarted,
        UserMessage,
    )
    from .ai.providers import Cancelled, ChatProvider, ChatReply, ProviderError, parse_json_object  # noqa: F401
    from .ai.tools import ToolBox  # noqa: F401
    from .protected_regions import protected_spans  # noqa: F401
    from .ai.tasks import (  # noqa: F401
        Task, TRANSLATE, FIX_LATEX, UPDATE_TRANSLATION, PROOFREAD, CONCISE, TITLE, NOTE, SUMMARISE, READABLE,
        REWRITE, REWRITE_PRESETS, PROOFREAD_SELECTION, answer_note, repair_request, translate_request,
        update_request, proofread_request, concise_request, title_request, rewrite_request,
        proofread_selection_request, note_request, summarise_request, fix_request, readable_request, check,
    )
    from .ai.task_result import Outcome  # noqa: F401
    from .alt_draft import (  # noqa: F401
        SlideContext, DraftResult, TranslationResult, build_prompt, draft_from_fields, effective_system_prompt,
        RESPONSE_SCHEMA as IMAGE_DESCRIPTION_SCHEMA,
    )
    from .alt_images import ImageEntry, en_text_hash  # noqa: F401
    from .translation_prompts import PromptConfig, get_effective_prompt  # noqa: F401
    from .ai.translation_style import de_address, glossary  # noqa: F401
    from .ai.image_instructions import IMAGE_DESCRIPTION_RULES  # noqa: F401
    from .ai.tools import CLAUDE_CODE_PRE_APPROVED  # noqa: F401
    from .compiler import CancelToken  # noqa: F401

API_VERSION = 1
SUPPORTED_API_VERSIONS = frozenset({1})

T = TypeVar("T")

Widget = Any

COURSE_GROUP = "course"
"""The tag of the deck group "Course deck" in Deck.groups. The group belongs to SlideMage; a plugin only reads it."""

TABLE_ENVIRONMENT = "SMTable"
"""The framework's table environment (booktabs rules, optional [gap=<n>pt]) for slide text a plugin writes. Added in
v10.12.2; a SlideMage without it has gothamtable, so read it as getattr(plugin_api, "TABLE_ENVIRONMENT", "gothamtable")."""


class StaleFileError(Exception):
    """The deck file changed on disk since the Deck was read: reload the deck and retry. Nothing was written."""


class EditRefusedError(ValueError):
    """SlideMage refused the edit and wrote nothing: the user has unsaved changes in the Deck settings sheet of this
    deck. The message says what to do ("Save or discard the changes on the other tabs first"); show it as it is."""


class AiChatError(Exception):
    """An AI chat request failed. Its message can be shown to the user."""


class Deck(Protocol):
    """One deck, read-only."""

    name: str
    """The jobname: the file name without .tex."""
    path: Path
    """The deck's .tex file."""
    text: str
    """The file's text when SlideMage read it, line endings as on disk."""
    groups: tuple[str, ...]
    """The tags of the deck groups the deck is in, in the switcher's order ("course", "work", ...)."""


@dataclass(frozen=True)
class InsertPosition:
    """A place in a deck's slide list where slides can be inserted."""

    label: str
    """Shown in the Insert choice: "At the beginning", "After 3. abc-DE-intro"."""
    insert_at: int
    """Character offset in Deck.text."""
    indent: str
    """The indent the inserted call lines get."""


@dataclass(frozen=True)
class FooterAction:
    """The button of a deck settings tab, in the sheet's footer, shown on that tab instead of Save."""

    label: str
    """"Insert slides"."""
    run: Callable[[Widget], None]
    """Called with the tab's widget when the button is pressed. It may call the host's edit calls itself."""
    enabled: Callable[[Widget], bool] = lambda page: True
    """Asked after the tab's widget emits changed (a signal with no arguments) and when the tab is shown."""


class Settings(Protocol):
    """A plugin's own small key-value store (JSON values), kept on this computer between starts."""

    def get(self, key: str, default: Any = None) -> Any:
        """The stored value for key, or default."""
        ...

    def set(self, key: str, value: Any) -> None:
        """Remember value (anything JSON can hold) under key in memory; save() writes it to disk."""
        ...

    def save(self) -> None:
        """Write the store to disk. Raises OSError if that fails."""
        ...


@dataclass(frozen=True)
class Focus:
    """What the user is looking at, as Host.focus() reads it."""

    deck: Path | None
    """The open deck's file, or None."""
    slide: Path | None
    """The slide file the editor shows, or None (a deck, a .bib or nothing is shown)."""
    scope: Literal["slide", "deck"]
    """How far an AI request may reach: this slide, or the whole deck."""


# -- reading slides: Host.deck_slides and Host.slide_source ------------------------------------------------------

@dataclass(frozen=True)
class SlideRef:
    """One slide as a deck calls it, from Host.deck_slides. Only the host makes these; later versions of SlideMage
    may add fields (with defaults), so read the fields you need by name and do not build one with positional
    arguments. A slide the deck calls twice (or at two versions) is two refs at two positions."""

    id: str
    """The slide's permanent ID, without language or slug ("abc")."""
    id_slug: str
    """The ID with language and slug as the file is named ("abc-EN-Hello"); for a translation it is the
    translation's, not the original's."""
    path: Path
    """The exact file the ref names: the slide's current file, or the frozen file of the version the deck pins."""
    language: str | None = None
    """The language of that file, "de" or "en" (or "mult" for a slide in both), or None for a slide that was never
    tagged. When the deck is read in a language the slide has no translation for, this is the other language."""
    version: str | None = None
    """The version of that file in its file-name form ("1-0-0"); None for a current file that was never given
    one."""
    pinned: bool = False
    """True when the deck pins this version (\\slideversion); False when it follows the slide's current file."""
    title: str = ""
    """The frame title of that file, or the slug when there is none."""
    position: int = 0
    """The slide's place among the deck's slide calls, from 1, hidden slides counted."""
    hidden: bool = False
    """True when the view asked for does not show the slide (an instructor-only slide in the other views)."""
    language_read: str | None = None
    """The language requested from deck_slides ("de" or "en"), used for picture descriptions, including multilingual
    files. None for a ref without a requested language: slide_source falls back to the file's language."""
    title_text: str = ""
    """The title as plain text to show (SlideMage v0.13.18): no LaTeX markup, so "VO Grundlagen \\\\ Digitalisierung"
    reads "VO Grundlagen Digitalisierung". title keeps the markup."""
    section: str = ""
    """The title of the \\section the slide call stands under, as plain text, or "" before the first section
    (SlideMage v0.13.18)."""


@dataclass(frozen=True)
class ThemeTokens:
    """SlideMage's colours, radii and fonts in the current theme, from Host.theme() (SlideMage v0.13.18). Only the host
    makes these; later versions may add fields (with defaults), so read the fields you need by name. Colours are
    strings QSS and QColor take: hex, except hover, which is translucent and in rgba() form."""

    dark: bool
    bg: str
    surface: str
    text: str
    text_2: str
    text_3: str
    text_4: str
    line: str
    hover: str
    inverse: str
    on_inverse: str
    focus: str
    on_solid: str
    ok: str
    ok_bg: str
    ok_fg: str
    warning: str
    warning_bg: str
    warning_fg: str
    error: str
    error_bg: str
    error_fg: str
    info: str
    info_bg: str
    info_fg: str
    radius_sm: int
    radius_md: int
    font_sans: str
    font_mono: str


@dataclass(frozen=True)
class MediaDescription:
    """What SlideMage's image store says about one picture a slide uses, in the requested reading language."""

    image: str
    """The store's key: the file relative to the project folder with forward slashes ("media/plot.png"), or
    "tikz:<id>" for a drawing in the slide's own source."""
    decorative: bool = False
    """The picture is marked as carrying no information."""
    short: str = ""
    long: str = ""
    takeaway: str = ""
    """What this slide takes from the picture, its own text or the picture's default."""


@dataclass(frozen=True)
class SlideSource:
    """What a slide file holds, from Host.slide_source: all the text that decides how it looks and reads."""

    text: str
    """The file's text, line endings as on disk."""
    media: tuple[Path, ...] = ()
    """The picture files the source includes that exist, in the order of their references' names, each once; a
    picture the file names but that is missing is left out, and so is a macro-valued path or a tikz drawing."""
    descriptions: tuple[MediaDescription, ...] = ()
    """The image store's entry for each picture and drawing the source includes, in the order of their references'
    names, each once; none for a picture the store does not know."""


class Credentials(Protocol):
    """A plugin's secrets (an API key), kept apart from its settings and from other plugins. A secret has a name
    ("key" by default; a plugin with two secrets names them). Where one lives, in order of lookup: the environment
    variable the plugin named in Host.credentials(env_var=...) (for the default name only; read-only), the system
    keychain (when the optional keyring package is installed and has a backend), a 0600 file in SlideMage's folder
    on this computer. A secret is kept in one place only. Never in the project folder."""

    def get(self, name: str = "key") -> str | None:
        """The secret, or None."""
        ...

    def set(self, value: str, name: str = "key") -> str:
        """Store the secret (an empty value clears it) and return where it went: "keychain" or "file", "" when
        cleared. Raises OSError when it cannot be stored or an old copy cannot be removed."""
        ...

    def clear(self, name: str = "key") -> None:
        """Remove the secret from the keychain and the file (the environment variable is not the plugin's to
        change)."""
        ...

    def where(self, name: str = "key") -> str:
        """Where the secret is read from: "environment", "keychain" or "file", or "" when there is none."""
        ...


class ExternalEdits(Protocol):
    """What changed in the project's text files since the last look (an external program, a terminal program,
    edited them). Paths are absolute."""

    added: tuple[Path, ...]
    removed: tuple[Path, ...]
    modified: tuple[Path, ...]


class EditWatch(Protocol):
    """A watch over the project's text files, from Host.watch_external_edits(). A cheap poll once a second, on the
    UI thread; hidden files, dot-folders, pdf/ and generated wrappers are not seen. Also a context manager:
    `with host.watch_external_edits(cb):` starts it and stops it at the end."""

    def start(self) -> None:
        """Take a first look and begin polling. Calling it again does nothing."""
        ...

    def stop(self, *, last_look: bool = True) -> None:
        """Stop polling. With last_look, one last poll first, because a program may have written a file in its
        final moment. Safe to call twice."""
        ...


class TerminalSession(Protocol):
    """One program on a terminal, from Host.terminal().start(). Callbacks run on the UI thread."""

    widget: Widget | None
    """The terminal view to put into a layout (None if started without one)."""
    running: bool

    def write(self, data: bytes) -> None:
        """Send keystrokes (or pasted text) to the program."""
        ...

    def resize(self, cols: int, rows: int) -> None: ...

    def stop(self) -> None:
        """End the program politely, then by force; its late output and exit are not reported. Safe to call twice."""
        ...

    def close(self) -> None:
        """stop(), and free the view."""
        ...


class HookContext(Protocol):
    """Window-independent project operations for an external hook. Paths are absolute; file writes and review
    records follow the same rules as SlideMage. A context comes from hook_context_from_environment()."""

    @property
    def root(self) -> Path:
        """The project root selected by the hook environment."""
        ...

    def slide_kind(self, path: Path) -> Literal["current", "frozen"] | None:
        """Classify a slide path as current or frozen, or return None for other files."""
        ...

    def read_text(self, path: Path) -> str:
        """Read UTF-8 text preserving line endings; raises on unreadable files."""
        ...

    def read_snapshot(self, identity: str) -> dict:
        """Read a hook's JSON snapshot by opaque identity; missing or invalid snapshots return {}."""
        ...

    def write_snapshot(self, identity: str, data: dict) -> None:
        """Atomically store a JSON snapshot by opaque identity."""
        ...

    def delete_snapshot(self, identity: str) -> None:
        """Delete a snapshot; an absent snapshot is harmless."""
        ...

    def is_image_store(self, path: Path) -> bool:
        """Whether path is the project image-description store."""
        ...

    def flag_edited_sources(self, path: Path, before: str) -> bool:
        """Mark image citations changed since before for review; return whether any changed."""
        ...

    def is_deck(self, path: Path) -> bool:
        """Whether path is a TeX file in the project's deck directory."""
        ...

    def mark_review(self, path: Path, kind: str, source: str, *, before: str | None = None) -> None:
        """Record a slide draft, translation, or edit for review, optionally preserving the old text."""
        ...

    def record_inserted_slides(self, path: Path, before: str, after: str, source: str) -> None:
        """Record the slide calls inserted in a deck edit for review."""
        ...

    def timing_event(self, name: str) -> None:
        """Record an optional timing event; a no-op unless timing is enabled."""
        ...


def hook_context_from_environment() -> HookContext:
    """Find the project named by the hook environment and return its window-independent operations."""
    return importlib.import_module("slidemage.plugins.hook").from_environment()


class TerminalWidget(Protocol):
    """A terminal view. write displays bytes even before a process is started; shutdown frees it."""

    ready: Any          # Qt signal: cols, rows, when the terminal can start
    resized: Any        # Qt signal: cols, rows
    input_data: Any     # Qt signal: bytes to send to the program
    files_dropped: Any  # Qt signal: list[str]
    image_pasted: Any   # Qt signal: QImage

    def write(self, data: bytes) -> None: ...
    def shutdown(self) -> None: ...
    def reset(self) -> None: ...
    def read_screen(self, callback: Callable[[list], None]) -> None: ...
    def focus_terminal(self) -> None: ...


class TerminalService(Protocol):
    """SlideMage's embedded terminal (a pseudo-terminal and an xterm view in SlideMage's colours)."""

    def create_widget(self, parent: Widget | None = None) -> TerminalWidget:
        """Create a view without a process. It can display startup errors; pass it to start to attach a process."""
        ...

    def refresh_widget(self, widget: TerminalWidget) -> None:
        """Apply the current theme to an existing terminal view."""
        ...

    def start(
        self, argv: list[str], env: dict[str, str] | None = None, cwd: Path | None = None, *,
        on_output: Callable[[bytes], None] | None = None, on_exit: Callable[[int], None] | None = None,
        with_widget: bool = True, cols: int = 80, rows: int = 24, widget: TerminalWidget | None = None,
    ) -> TerminalSession:
        """Run argv (env defaults to SlideMage's own, cwd to the project folder). With a widget the program
        starts when the view has its size (once the widget is shown), and its output goes to the view as well as
        to on_output; without one it starts at once at cols x rows. on_exit(code) is called when it ends by itself.
        A supplied widget is attached instead of creating one; it must not already belong to a session.
        Raises OSError if the program cannot be started (when it starts at once)."""
        ...


class ToolWorkspace(Protocol):
    """Opaque GUI workspace for Host.ai_tools; close it when the surface shuts down."""

    def close(self) -> None: ...


@dataclass(frozen=True)
class ChatFocus:
    """Editor state for an external agent; paths are absolute, and deck excludes test decks."""
    slide_id: str | None
    slide: Path | None
    deck: Path | None
    view: str
    language: str
    dirty: bool


class ChatSurfaceContext(Protocol):
    """UI-thread operations supplied to chat_surface_v2. It holds no publicly exposed core window or state."""

    @property
    def project_root(self) -> Path:
        """Project directory for file dialogs and processes."""
        ...

    def selected_route(self, route_id: str, task: str, choice: str = "") -> Route:
        """The saved model and effort for a route and task, or a valid explicit choice when supplied."""
        ...

    def focus_details(self) -> ChatFocus:
        """Snapshot of the editor and deck for an external agent's focus file."""
        ...

    def build_tools(self, host: Host, scope: Literal["slide", "deck"], cancel: Any) -> ToolBox | None:
        """Build a fresh GUI-aware toolbox from any thread; return None after close releases a wait."""
        ...

    def scope(self) -> Literal["slide", "deck"]:
        """The current assistant scope."""
        ...

    def set_scope(self, value: Literal["slide", "deck"]) -> bool:
        """Set and broadcast scope; return False if deck scope is unavailable."""
        ...

    def on_scope_changed(self, callback: Callable[[str], None]) -> None:
        """Call callback on the UI thread when scope changes."""
        ...

    def open_ai_setup(self) -> None:
        """Open AI setup."""
        ...

    def attach_file(self, path: Path) -> str | None:
        """Place a file in the project and return its relative path, or None."""
        ...

    def attach_image(self, image: Widget) -> str | None:
        """Save a Qt image in the project and return its relative path, or None."""
        ...

    def apply_external_edits(self, changes: ExternalEdits) -> None:
        """Update open buffers, conflicts, decks and views after an external edit watch reports changes."""
        ...

    def tool_workspace(self) -> ToolWorkspace:
        """Return the GUI-aware workspace handle accepted by Host.ai_tools."""
        ...

    def translate_slide(self, path: Path) -> str:
        """Show a slide and start its translation task; return a message describing the result."""
        ...

    def close(self) -> None:
        """Release waits held by the tool workspace when the surface is closed."""
        ...


class ChatSurfaceRoute(Protocol):
    """Optional addition to AiRoute: a route may implement this instead of the legacy chat_surface call."""

    def chat_surface_v2(self, context: ChatSurfaceContext) -> Widget | None:
        """Build a conversation surface using the typed context; return None to use the normal chat. The
        surface closes context when it shuts down. Core prefers this method when present."""
        ...


class RouteTaskLease(Protocol):
    """A reservation of one route's long-running work, usable as a context manager."""

    def release(self) -> None:
        """Release this reservation once. Further calls do nothing."""
        ...

    def __enter__(self) -> RouteTaskLease: ...
    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None: ...


class Host(Protocol):
    """The calls SlideMage offers a plugin. activate(host) gets one object of this type."""

    # -- what it is given ---------------------------------------------------------------------------------------

    def cache_dir(self) -> Path:
        """The plugin's own folder for data it can recreate. Created if missing, the same for every start of one
        project; not shared with other plugins. May be called any time."""
        ...

    def legacy_cache_dir(self) -> Path | None:
        """The folder where SlideMage kept its files before there was a plugin (project.cache_dir()), or None if
        there is none (no project open, or a new install). Read-only for the plugin: it may copy from it, never
        write there. May be called any time; cheap."""
        ...

    def settings(self) -> Settings:
        """The plugin's own settings store."""
        ...

    # -- what it registers (activate() only) --------------------------------------------------------------------

    def add_command(
        self, id: str, title: str, run: Callable[[Deck], None],
        enabled: Callable[[Deck | None], bool] = lambda deck: True,
    ) -> None:
        """Register a command for the command palette and menu entries. id is unique and starts with
        "<plugin id>." ("campusonline.admin_slides"); a duplicate raises ValueError. run is called with the
        current deck, only when enabled is true for it; enabled gets None when no deck is open and is asked often,
        so it must be cheap and must not use the network. A command that is not enabled is shown greyed out. An
        exception in run is shown to the user as an error and logged."""
        ...

    def add_menu_entry(self, menu: Literal["deck"], command_id: str) -> None:
        """Put a registered command into a menu (the plugin's entries follow SlideMage's own). "deck" is the Deck
        menu; more menus when a plugin needs them. An unknown command_id or menu raises ValueError."""
        ...

    def add_deck_settings_tab(
        self, title: str, build: Callable[[Deck], Widget], footer_action: FooterAction | None = None,
    ) -> None:
        """Add a tab to the Deck settings sheet, after SlideMage's own. build(deck) is called when the sheet opens
        for a deck and returns the tab's widget (a Page); it must not block, so a tab that loads something starts
        it with run_in_background when the tab is first shown. The sheet closing destroys the widget, and a result
        that arrives later must be ignored by the plugin. With a footer_action the footer shows that button while
        the tab is selected."""
        ...

    def add_settings_tab(self, title: str, build: Callable[[], Widget]) -> None:
        """Add a tab to the Settings sheet (not a deck's), after SlideMage's own. build() returns the tab's
        widget (a Page), is called when the sheet opens and must not block."""
        ...

    def add_ai_route(self, route: AiRoute) -> None:
        """Register an AI route during activate(); duplicate route ids fail the plugin."""
        ...

    def add_settings_section(self, page: Literal["ai"], title: str, build: Callable[[], Widget]) -> None:
        """Add a titled section to a page of the Settings sheet; only page "ai" (the AI tab) exists. The section
        follows SlideMage's own, in registration order. build() returns the section's widget, is called when the
        sheet opens and must not block. A build that raises shows an error line in its section."""
        ...

    def add_sidebar_box(
        self, key: str, title: str, build: Callable[[Deck], Widget], size: Literal["compact", "large"] = "compact",
        when: Callable[[Deck], bool] = lambda deck: True,
    ) -> None:
        """Add a box to the workspace's right column. key is unique within the plugin (it remembers the box's
        collapsed state). build(deck) is called when the box is shown for a deck, and again when the current deck
        changes or its file does, when refresh_sidebar_box(key) is called, and when the calendar date changes;
        when(deck) decides whether the box is shown at all, cheap and without the network. "compact" is a few lines
        at a glance (an entry of the panel picker); "large" is a working surface in the dock below the slide panels
        (not supported yet: raises NotImplementedError)."""
        ...

    def refresh_sidebar_box(self, key: str) -> None:
        """Say that the box key of this plugin shows data that has changed (a cache it reads was filled, say). The
        box is built again at once if it is shown, and otherwise the next time it is shown. Call it from the UI
        thread only: from done of run_in_background, or from a timer. An unknown key raises ValueError."""
        ...

    def add_render_priority(self, soon: Callable[[Deck], bool]) -> None:
        """Give a deck priority in the background renders when soon(deck) is true: it is rendered earlier than
        decks for which it is false. soon is asked for every deck whenever the render queue is ordered, on a worker
        thread, so it must be thread-safe, quick and not use the network; it reads what is already cached. An
        exception counts as False."""
        ...

    def add_entry_point(self, name: str, fn: Callable[[list[str]], int]) -> None:
        """Register a program entry: `SlideMage --plugin <plugin id>:<name> args...` loads only this plugin, with no
        window, and exits with fn(args)'s return code (a hook that another program runs as a command, say). name is
        lower case letters, digits, "-" and "_"; a duplicate raises ValueError. fn runs in a fresh process without
        a window, so it must not use widgets; run_in_background and the window calls raise there."""
        ...

    # -- what it calls ------------------------------------------------------------------------------------------

    def entry_point_command(self, name: str) -> list[str]:
        """The argv that runs the entry point `name` of this plugin: [SlideMage's executable, "--plugin",
        "<id>:<name>"] in an installed app; [python, "-m", "slidemage", "--plugin", "<id>:<name>"] from source.
        Hand it to another program as a command (shlex.join / subprocess.list2cmdline). May be called any time."""
        ...

    def ai_chat(self) -> AiChat:
        """Text requests on the selected Chat route."""
        ...

    def terminal(self) -> TerminalService:
        """The embedded terminal service (the window must exist: raises RuntimeError("no window") otherwise)."""
        ...

    def watch_external_edits(self, on_change: Callable[[ExternalEdits], None]) -> EditWatch:
        """A watch over the project's text files; on_change(changes) is called on the UI thread when a poll sees
        files added, removed or modified. If on_change raises, the changes are offered again at the next poll.
        Not started: call start() (or use it in a with)."""
        ...

    def credentials(self, env_var: str | None = None) -> Credentials:
        """The plugin's secrets; env_var names the environment variable that wins over a stored secret of the
        default name ("ANTHROPIC_API_KEY")."""
        ...

    def acquire_route_task(self, route_id: str, label: str) -> RouteTaskLease | None:
        """Reserve a route for a long job on the UI thread. Return None and show the busy reason if another job
        holds it. Release after the worker has stopped, including on failure; leases are route-specific.
        Raises RuntimeError when no window exists."""
        ...

    def model_choices_changed(self, route_id: str) -> None:
        """Notify the UI after this route's cached model choices change. Pickers and open settings refresh on
        the UI thread; the call is harmless before a window exists. It does not perform network I/O."""
        ...

    def legacy_secret(self, name: Literal["anthropic_api_key"]) -> str | None:
        """Read the old built-in secret, without removing it. Unknown names raise ValueError."""
        ...

    def legacy_ollama_host(self) -> str:
        """Read the former built-in Ollama address, including its environment and default fallback."""
        ...

    def run_in_background_with_progress(
        self, work: Callable[[Callable[[T], None]], Any], progress: Callable[[T], None],
        done: Callable[[Any, BaseException | None], None],
    ) -> None:
        """Run work(report) on a worker. report(value) is worker-safe and queues progress(value) on the UI
        thread, before done(result, error). Report only while work is running. Callbacks may outlive the requesting
        widget."""
        ...

    def ai_tools(
        self, scope: Literal["slide", "deck"] = "slide", *, focus_slide: Path | None = None,
        mode: Literal["ask", "auto"] = "auto", cancel: Any = None, workspace: ToolWorkspace | None = None,
    ) -> "ToolBox":
        """The agent's tools as SlideMage's embedded Claude Code is offered them (read files, lint, render a preview,
        create/modify/add/insert slides, QR codes, guides...), for an MCP server or an agent loop of the plugin's
        own. scope limits where edits may reach ("slide": only focus_slide; "deck": the deck). mode "auto" applies
        edits at once, "ask" proposes them. cancel is a compiler.CancelToken (None: a fresh one). workspace is a handle from ChatSurfaceContext.tool_workspace() (None: the project's files, with no editor buffers). Use
        box.specs and box.execute(ToolCall(...)). Heavy to import: call it when needed, not in activate()."""
        ...

    def focus(self) -> Focus:
        """What the user is looking at now (the deck, the slide, the scope of an AI request). Focus(None, None,
        "slide") when no window shows one."""
        ...

    def run_in_background(self, work: Callable[[], T], done: Callable[[T | None, BaseException | None], None]) -> None:
        """Run work() on a worker thread (a network fetch, say) and then call done(result, None), or
        done(None, error) if work raised, on the UI thread. work must not touch widgets. done is called even when
        the tab that asked has closed; the plugin checks that itself. Returns at once."""
        ...

    def insert_positions(self, deck: Deck) -> list[InsertPosition]:
        """The places where slides can be inserted into deck: at the beginning, after each slide call (labelled
        with its number and id), or at the end of an empty deck. Never empty. Reads deck.text only."""
        ...

    def insert_slides(
        self, deck: Deck, position: InsertPosition, slides: list[tuple[str, str]], language: Literal["de", "en"],
    ) -> list[Path]:
        """Create one new slide per (id_suffix, frame) (frame is the slide's LaTeX body; SlideMage adds its file
        header and version), named <new id>-<DE|EN>-<id_suffix>, and add their calls to the deck at position as one
        edit, in order. Returns the new slide files. All or nothing: on any failure the new files are removed and
        the deck is untouched (the deck is replaced atomically, and checked against deck.text at that moment).
        Raises StaleFileError if the deck changed, EditRefusedError while the Deck settings sheet of the deck has
        unsaved changes, OSError if a file cannot be written.
        Takes a moment (disk); call it from a button, not from a background thread."""
        ...

    def edit_deck_text(self, deck: Deck, change: Callable[[str], str]) -> str:
        """Replace the deck's text by change(text) in one write, and return the new text (the caller shows it; the
        next Deck SlideMage hands out has it too). Raises StaleFileError if the file differs from deck.text,
        EditRefusedError while the Deck settings sheet of the deck has unsaved changes; an
        exception from change (a ValueError for a bad value) passes through and nothing is written. One undo step
        in SlideMage's deck history. change must be pure: no I/O."""
        ...

    def deck_language(self, deck: Deck) -> Literal["de", "en"]:
        """The language a compile of the deck uses. Reads deck.text only."""
        ...

    def project_root(self) -> Path:
        """The open project's folder (decks/, slides/, media/ are inside it). May be called any time, from a
        worker too."""
        ...

    def deck_output_folder(self, deck: Deck, view: str = "instructor") -> Path:
        """The folder the deck's PDF of `view` ("instructor", "during-course" or "after-course") is written to: the
        folder its \\deckoutputfolder line names (a relative one from the project folder), else the project's pdf/
        folder. A line that names a file gives that file's folder. The folder need not exist. Reads deck.text
        only; may be called from a worker. An unknown view raises ValueError."""
        ...

    def deck_slides(self, deck: Deck, view: str, language: Literal["de", "en"]) -> list[SlideRef]:
        """The deck's slides in the order SlideMage lists them for `view` ("instructor", "during-course" or
        "after-course") read in `language`: one ref per slide call, hidden ones included (SlideRef.hidden), and a
        slide with a translation into `language` as that translation. A slide without one is the slide in its own
        language: compare SlideRef.language. Reads deck.text and the slide files as they are now and changes
        nothing; may be called from a worker. Slides in included fragments are not listed.
        Raises ValueError for an unknown view or language."""
        ...

    def slide_source(self, ref: SlideRef) -> SlideSource:
        """The text, picture files and picture descriptions of the file `ref` names (ref.path): the pinned version
        for a pinned ref, the current file otherwise, with descriptions in ref.language_read (the language requested
        from deck_slides). If unset, the file's language is used; "de" gives German, anything else English.
        Reads files and changes nothing; may be called from a worker. Raises
        OSError when the file cannot be read, and ValueError when ref.path is not a slide file of this project."""
        ...

    def open_slide(self, ref: SlideRef) -> None:
        """Show the file `ref` names in SlideMage's editor (the Source view), as it is: a pinned version too.
        Raises RuntimeError("no window") when there is no window, and ValueError when ref.path is not a slide file
        of this project."""
        ...

    def open_url(self, url: str) -> None:
        """Open an http(s) URL in the user's default browser. Raises ValueError for any other scheme, and OSError
        when nothing could be started."""
        ...

    def open_deck_settings(self, deck: Deck, tab: str | None = None) -> None:
        """Open the Deck settings sheet for deck, on the tab with the title tab (a plugin's own tab, or one of
        SlideMage's) if given."""
        ...

    def log(self, message: str, level: Literal["debug", "info", "warning", "error"] = "info") -> None:
        """Write a line to SlideMage's log, marked with the plugin's id (area plugins.<id>). Warnings and errors
        always reach the error log; debug and info lines only the debug log, while it is on. The level argument
        came with SlideMage v0.13.5: a plugin that passes it says requires_slidemage = ">=0.13.5"."""
        ...

    def debug_enabled(self) -> bool:
        """Whether SlideMage writes its debug log now: check it before building an expensive debug line
        (SlideMage v0.13.5)."""
        ...

    def show_message(self, text: str, error: bool = False) -> None:
        """Tell the user something in SlideMage's status line; error=True shows it as an error."""
        ...

    # -- widgets, so that the tab and the box look like SlideMage's ---------------------------------------------

    def Page(self) -> Widget:
        """A vertical page for a tab or a box: page.body is the layout to add widgets to, and the page emits
        changed (no arguments) when the plugin's state changed."""
        ...

    def Field(self, label: str, widget: Widget) -> Widget:
        """widget with a label above it, in SlideMage's form style."""
        ...

    def caption(self, text: str, tone: Literal["", "error"] = "") -> Widget:
        """A small grey line of text; tone="error" makes it an error line. Its setText changes it later."""
        ...

    def Surface(self) -> Widget:
        """A plain themed surface."""
        ...

    def Button(self, text: str, kind: str = "secondary", *, compact: bool = False) -> Widget:
        """A themed button."""
        ...

    def Chip(
        self, text: str, tone: str = "neutral", *, icon: str | None = None, elide: bool = False,
        pressable: bool = False,
    ) -> Widget:
        """A status chip with set_text, set_tone and set_icon; it emits clicked. tone is "neutral", "muted", "info",
        "warning", "error" or "ok". icon is a Material icon's name; an elide chip shortens its text with "…" rather
        than widen its column; a pressable chip is a button for the keyboard too, named by its tooltip (the keyword
        arguments came with SlideMage v0.13.18)."""
        ...

    def Window(self, title: str) -> Widget:
        """A top-level, non-modal window in SlideMage's look: window.body is the layout to fill. Keep a reference to
        it, and show() it yourself; it stays yours to open and close. It is not restored at the next start. When
        SlideMage closes (a project switch restarts it) it asks this window to close first: ignoring the closeEvent,
        for unsaved work, keeps SlideMage open (SlideMage v0.13.18)."""
        ...

    def Card(self, raised: bool = False) -> Widget:
        """A rounded panel on the window's background: fill card.layout(), a vertical layout. raised adds a shadow; leave
        it off for big panels (SlideMage v0.13.18)."""
        ...

    def SegmentedControl(self, items: list[tuple[str, str]], current: str | None = None) -> Widget:
        """A switch of (key, label) segments, the first current unless current says otherwise. It emits changed(key)
        when the user picks one, not for set_current(key); current() is the key, and clear_current() leaves none current
        (SlideMage v0.13.18)."""
        ...

    def Badge(self, text: str, tone: str = "neutral") -> Widget:
        """A small round count. tone is "neutral", "info" or "error". It has set_text and set_tone (SlideMage
        v0.13.18)."""
        ...

    def ElidedLabel(self, text: str) -> Widget:
        """One line of text, cut with "…" to the width it gets, with the whole text as its tooltip. set_full_text
        changes it and full_text() reads it (SlideMage v0.13.18)."""
        ...

    def RowButton(
        self, title: str, sub: str = "", *, icon: str | None = None, chip: tuple[str, str] = ("", ""),
        selectable: bool = False,
    ) -> Widget:
        """A clickable row with a title, shortened with "…" when narrow, a second line, and an optional Material icon
        and (text, tone) chip; row.layout() takes more at its right end (a Badge). It emits clicked. A selectable row
        becomes selected when clicked; set_selected(False) clears the others of your list, and selected() reads it
        (SlideMage v0.13.18)."""
        ...

    def PlainList(self) -> Widget:
        """A QListWidget that shows what is behind it, on a Card say, for rows that bring their own hover and selection
        (RowButton): fill it with setItemWidget. Do not give a list of such rows a stylesheet of its own: Qt then drops
        the rows' styling when they are rebuilt (SlideMage v0.13.18)."""
        ...

    def Label(self, text: str, role: str = "body") -> Widget:
        """Text in SlideMage's type scale. role is "title", "heading", "body", "secondary", "caption" or "mono"; any
        other raises ValueError (SlideMage v0.13.18)."""
        ...

    def ModalSheet(self, title: str, parent: Widget | None = None) -> Widget:
        """A modal dialog in SlideMage's look, over parent: add_tab(label, widget) fills it, add_button(text, kind=...,
        role="accept" or "reject") adds a footer button, exec() runs it (SlideMage v0.13.18)."""
        ...

    def toast(self, parent: Widget, text: str) -> None:
        """Show text for a moment at the bottom of parent, a window of yours. To tell the user something in the main
        window use show_message (SlideMage v0.13.18)."""
        ...

    def theme(self) -> ThemeTokens:
        """The current theme. May be called before the main window exists (SlideMage v0.13.18)."""
        ...

    def on_theme_changed(self, callback: Callable[[ThemeTokens], None]) -> Callable[[], None]:
        """Call callback(tokens) on the UI thread after the user switched between light and dark and SlideMage's styles
        are applied. Host widgets follow by themselves: use it only for what you draw yourself. Returns the function
        that unsubscribes: call it when the widget you update closes. What callback raises is logged and shown
        (SlideMage v0.13.18)."""
        ...

    def IconButton(self, icon: str, tooltip: str) -> Widget:
        """A themed icon button."""
        ...

    def IconLabel(self, icon: str, size: int) -> Widget:
        """A themed icon label."""
        ...

    def style_chat_widget(self, widget: Widget, role: Literal["surface", "cloud_card", "title"]) -> None:
        """Apply the named conversation surface style to a Qt widget."""
        ...

    def theme_color(self, role: Literal["info"]) -> str:
        """The current theme color for widgets that cannot use QSS."""
        ...


# -- AI routes ---------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Route:
    """What one AI request runs on: a route (an AiRoute's id), the task, and the model chosen for it. Frozen: a
    request keeps the Route it was started with, whatever the AI switch does meanwhile."""

    route: str
    """The id of the AiRoute that answers ("ollama", "claude_code", "anthropic_api", a plugin's own)."""
    task: str
    """One of ai_profile.TASKS ("chat", "image_description", "translation", "fixes_notes_transcripts")."""
    model: str = ""
    """What the route's model choice names; "" when none is chosen (Claude Code's chat then inherits its default)."""
    effort: str | None = None
    """The effort part of a route's choice, for the routes that have one (Claude Code's "haiku:medium")."""

    @property
    def is_local(self) -> bool:
        """Whether the route keeps everything on this computer (AiRoute.is_local); False for an unknown route."""
        found = _route_lookup(self.route)
        return bool(found and found.is_local)

    @property
    def name(self) -> str:
        """The route as the assistant's header names it: "Local · Ollama", "Cloud · Claude Code"."""
        found = _route_lookup(self.route)
        if found is None:
            return self.route
        return f"{'Local' if found.is_local else 'Cloud'} · {found.service}"

    @property
    def label(self) -> str:
        """What to show next to the work, as the route words it (AiRoute.work_label): "translategemma:12b ·
        Ollama", "Claude Code · Haiku · effort medium"."""
        found = _route_lookup(self.route)
        return found.work_label(self) if found else f"{self.model or 'no model chosen'} · {self.route}"


def _no_lookup(route_id: str) -> "AiRoute | None":
    return None


_route_lookup: Callable[[str], "AiRoute | None"] = _no_lookup


def set_route_lookup(lookup: Callable[[str], "AiRoute | None"]) -> None:
    """Core only: tell Route where the registry is (ai/routes.py does this when it is imported), so that this
    module needs no import of it. A plugin never calls it."""
    global _route_lookup
    _route_lookup = lookup


class RouteCredentials(Protocol):
    """Obtain the registering plugin's credentials, optionally with an environment override."""

    def __call__(self, env_var: str | None = None) -> Credentials: ...


@dataclass(frozen=True)
class RouteContext:
    """Project and plugin services for one route call. Values describe the current project; settings and
    credentials belong to the plugin that registered the route. Legacy readers never modify old storage.
    cache_dir is the plugin's private cache path; create it before writing if needed.
    """

    root: Path
    settings: Settings
    cache_dir: Path
    legacy_cache_dir: Path | None
    credentials: RouteCredentials
    legacy_secret: Callable[[Literal["anthropic_api_key"]], str | None]
    legacy_ollama_host: Callable[[], str]
    de_address: str
    glossary: str


class AiRoute(Protocol):
    """Something that answers AI requests: Ollama, Claude Code, the Anthropic API, or a plugin's own. Core
    registers one object per route (ai/routes.py) and asks it everything route-specific; no core module outside
    a route's own names a service. Every call is on the UI thread unless its text says otherwise, and none of
    them may use the network or take long except where noted. add_ai_route and this context are part of the
    unreleased API 1 additions; no released API 1 route contract is changed."""

    id: str
    """Stable and lower-case ("ollama"); stored in settings and in a Route, so it never changes."""
    service: str
    """What the user calls it ("Ollama", "Claude Code", "Anthropic API"): the header reads "Local · <service>" or
    "Cloud · <service>"."""
    is_local: bool
    """Nothing leaves this computer: the route belongs to the Local side of the AI switch, else to Cloud."""
    tasks: frozenset[str]
    """Which of ai_profile.TASKS it can answer."""

    def problem(self, ctx: RouteContext, route: Route) -> str:
        """Why `route` (this route's, with its task and model) cannot run now, as a sentence ready to show, or ""
        when it can: no model chosen, no key, not installed. Asked before every request and for the pickers; cheap,
        no network."""
        ...

    def model_choices(self, ctx: RouteContext, task: str) -> list[str]:
        """The choices a picker offers for `task` without asking anyone: Claude Code's fixed list, the API's
        known models once a key is set. A route whose choices come from a server (Ollama's installed models) returns
        its most recent cached list here and refreshes it in the background. Never the network."""
        ...

    def default_choice(self, task: str) -> str:
        """The choice used for `task` while the user has chosen none; "" for none (a picker then offers
        what is available)."""
        ...

    def choice_label(self, choice: str) -> str:
        """A choice as a picker shows it ("Sonnet · medium" for "sonnet:medium")."""
        ...

    def split_choice(self, choice: str) -> tuple[str, str | None]:
        """A choice as (model, effort), the parts of a Route; effort is None for a route without one."""
        ...

    def valid_choice(self, ctx: RouteContext, choice: str) -> bool:
        """Whether `choice` is one this route offers; a stored or picked choice that is not is ignored. A route
        with open-ended choices (any model name) accepts every non-empty string."""
        ...

    def work_label(self, route: Route) -> str:
        """What to show next to work done on `route`: "qwen3:8b · Ollama", "Claude Code · Haiku · effort medium"."""
        ...

    def provider(self, ctx: RouteContext, route: Route) -> "ChatProvider | None":
        """A new chat provider for `route` (one request's: abort() ends only that one), or None when the route
        has no chat provider of its own (Claude Code answers through task_runner and chat_surface). Does not check
        problem(): core does, and never falls back to another route."""
        ...

    def request_provider(self, ctx: RouteContext, route: Route) -> "ChatProvider | None":
        """Provider for one self-contained ai.chat request; by default problem() is checked, then provider().
        A route may override this while keeping provider() as None so the assistant uses its own chat surface: an
        override does its own checks and raises ProviderError with a sentence to show, as problem() is not asked.
        No other feature calls it."""
        if reason := self.problem(ctx, route):
            raise importlib.import_module("slidemage.ai.providers").RouteUnavailable(reason)
        return self.provider(ctx, route)

    def draft_backend(self, ctx: RouteContext, route: Route, cancel: "threading.Event | None" = None) -> Any:
        """What describes images on `route` (alt_draft's backend protocol: draft(), label, provider), or None:
        core then wraps provider() in alt_draft.ModelBackend. `cancel` ends a running request of a route that runs a
        process. Raises ProviderError when it cannot be made."""
        ...

    def translation_backend(self, ctx: RouteContext, route: Route, cancel: "threading.Event | None" = None) -> Any:
        """What translates image descriptions on `route` (alt_draft's translation protocol: translate()), or None:
        core then wraps provider() in alt_draft.ModelTranslationBackend."""
        ...

    def slide_translator(self, ctx: RouteContext, route: Route) -> Any:
        """What translates a slide body for the Add slide sheet (translate(body) -> (text, error), abort()), or
        None: core then wraps provider() in slide_add.translate_body."""
        ...

    def task_runner(self, ctx: RouteContext, route: Route) -> Callable[..., Any] | None:
        """For a route that runs the bubble tasks itself (Claude Code's `claude -p`): run(task, captured, request,
        cancel, span) -> Outcome, called on a worker thread. None: core runs them on provider()
        (ai/provider_tasks.py)."""
        ...

    # Optional addition: implementations may provide chat_surface_v2(context: ChatSurfaceContext) -> Widget | None.
    # Core prefers it when present; API 1's original chat_surface remains supported. The returned surface follows
    # the same lifecycle as chat_surface and closes its context on shutdown.
    def chat_surface(self, *args: Any, **kwargs: Any) -> Widget | None:
        """The widget that is the assistant's conversation on this route, built by the assistant with the
        arguments it has; None: core's chat view over provider(). Claude Code returns its terminal, which also
        has stop() and restart(choice, continue_conversation) for the AI setup's Switch now."""
        ...

    def settings_section(self) -> Callable[[], Widget] | None:
        """A builder for the route's own section of Settings' AI tab, or None for no section. Built when Settings opens."""
        ...


# -- AI chat: one text request -------------------------------------------------------

@dataclass(frozen=True)
class AiChatRequest:
    """One text turn: instructions is the system prompt, text the user message. Put the wanted answer format
    in instructions; no files or chat history are added."""

    instructions: str
    text: str
    max_tokens: int = 4096


@dataclass(frozen=True)
class AiChatResult:
    """The reply and the captured route/model for provenance. Check truncated before using the text."""

    text: str
    route: Route
    truncated: bool = False


class AiChat(Protocol):
    """Host-owned text generation on the current Chat route/model; no route or model fallback.
    A route without a request provider is unavailable. Cloud requests require the host's confirmation each time,
    showing the full instructions and text. Local routes (AiRoute.is_local) need no confirmation."""

    def available(self) -> bool:
        """Whether the selected Chat route/model offers self-contained requests. Quick, UI thread, never raises.
        A missing API key still counts as available: request() explains it. No request or network call is made."""
        ...

    def request(self, request: AiChatRequest,
                done: Callable[[AiChatResult | None, AiChatError | None], None]) -> Callable[[], None]:
        """Call on the UI thread with a running GUI event loop; returns a cancel function, also UI-thread only.
        The host captures the route/model now, confirms if needed, and runs the provider on a worker; plugins
        need no worker. done(result, error) runs once, later on the UI thread, including for an unavailable route.
        Decline or cancel gives done(None, None). Cancel is repeatable: it asks the provider to abort and discards
        its reply; completion waits for the worker to end. Errors are AiChatError with a message ready to show.
        Callbacks can outlive the requesting widget; check it still exists. Nothing is streamed."""
        ...


# -- the neutral AI types -----------------------------------------------------------------------------------------
# Lazy additions: Task, TRANSLATE, answer_note, repair_request, translate_request, check are the task
# definition, prompts and validation; SlideContext, DraftResult, TranslationResult, build_prompt,
# draft_from_fields, effective_system_prompt, IMAGE_DESCRIPTION_SCHEMA, ImageEntry, en_text_hash and
# get_effective_prompt define image drafting and translation. de_address and glossary read project translation
# style. IMAGE_DESCRIPTION_RULES and CLAUDE_CODE_PRE_APPROVED supply Claude launch instructions. CancelToken
# is the process-aware cancellation token accepted by ai_tools. Outcome is the task runner result.
# Re-exported from SlideMage's modules, which are not standard library, so they load on first use: importing this
# module stays cheap, and `from slidemage.plugin_api import ChatProvider` works. They are:
#   ai.providers   ChatProvider (Protocol of a model backend), ChatReply, ProviderError, Cancelled,
#                  parse_json_object(text) -> dict | None (the first JSON object in a model's answer)
#   ai.agent_types the agent chat's messages (UserMessage, AssistantMessage, ToolResultsMessage, AgentMessage),
#                  tool calls and results (ToolSpec, ToolCall, ToolResult), events (TextDelta, ToolStarted,
#                  ToolFinished, EditProposed, EditApplied, EditRejected, Done, AgentEvent), EDIT_ASK, EDIT_AUTO
#   ai.tools       ToolBox
#   protected_regions  protected_spans(text) -> [[start, end], ...]: the parts of a slide that tools and hooks
#                  refuse to change (header comment, \setSlideVersion); read-only use.
_LAZY = {
    **{name: "slidemage.ai.providers" for name in
       ("ChatProvider", "ChatReply", "ProviderError", "Cancelled", "parse_json_object")},
    **{name: "slidemage.ai.agent_types" for name in
       ("ToolSpec", "ToolCall", "ToolResult", "UserMessage", "AssistantMessage", "ToolResultsMessage", "AgentMessage",
        "TextDelta", "ToolStarted", "ToolFinished", "EditProposed", "EditApplied", "EditRejected", "Done",
        "AgentEvent", "EDIT_ASK", "EDIT_AUTO")},
    "ToolBox": "slidemage.ai.tools",
    "protected_spans": "slidemage.protected_regions",
    **{name: "slidemage.ai.tasks" for name in (
        "Task", "TRANSLATE", "FIX_LATEX", "UPDATE_TRANSLATION", "PROOFREAD", "CONCISE", "TITLE", "NOTE",
        "SUMMARISE", "READABLE", "REWRITE", "REWRITE_PRESETS", "PROOFREAD_SELECTION", "answer_note",
        "repair_request", "translate_request", "update_request", "proofread_request", "concise_request",
        "title_request", "rewrite_request", "proofread_selection_request", "note_request", "summarise_request",
        "fix_request", "readable_request", "check")},
    **{name: "slidemage.alt_draft" for name in (
        "SlideContext", "DraftResult", "TranslationResult", "build_prompt", "draft_from_fields",
        "effective_system_prompt")},
    "IMAGE_DESCRIPTION_SCHEMA": "slidemage.alt_draft",
    "ImageEntry": "slidemage.alt_images",
    "en_text_hash": "slidemage.alt_images",
    "PromptConfig": "slidemage.translation_prompts",
    "get_effective_prompt": "slidemage.translation_prompts",
    "de_address": "slidemage.ai.translation_style",
    "glossary": "slidemage.ai.translation_style",
    "IMAGE_DESCRIPTION_RULES": "slidemage.ai.image_instructions",
    "CLAUDE_CODE_PRE_APPROVED": "slidemage.ai.tools",
    "CancelToken": "slidemage.compiler",
    "Outcome": "slidemage.ai.task_result",
}
# Every SlideMage module this file loads by name. PyInstaller doesn't see those imports, so the spec bundles these
# and `slidemage --self-test --plugins` imports them (slidemage/plugins/selftest.py); without slidemage.plugins.hook
# the frozen app's Claude Code hook failed with ModuleNotFoundError.
_RUNTIME_MODULES = tuple(sorted({*_LAZY.values(), "slidemage.plugins.hook", "slidemage.project", "slidemage.ai.tasks",
                                 "slidemage.alt_draft", "slidemage.translation_prompts"}))


def _helper_project(ctx: RouteContext):
    return importlib.import_module("slidemage.project").ProjectContext.at(ctx.root)


def check(ctx: RouteContext, *args: Any, **kwargs: Any):
    """Validate a task answer using this route's project and bibliography."""
    return importlib.import_module("slidemage.ai.tasks").check(_helper_project(ctx), *args, **kwargs)


def effective_system_prompt(ctx: RouteContext) -> str:
    """The effective image description prompt for this route's project."""
    return importlib.import_module("slidemage.alt_draft").effective_system_prompt(_helper_project(ctx))


def get_effective_prompt(ctx: RouteContext, model: str, source_lang: str, target_lang: str):
    """The effective image translation prompt for this route's project."""
    return importlib.import_module("slidemage.translation_prompts").get_effective_prompt(
        _helper_project(ctx), model, source_lang, target_lang)


def __getattr__(name: str) -> Any:
    module = _LAZY.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(importlib.import_module(module), "RESPONSE_SCHEMA" if name == "IMAGE_DESCRIPTION_SCHEMA" else name)
    globals()[name] = value
    return value
