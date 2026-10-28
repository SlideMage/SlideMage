# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""What a plugin may use from SlideMage: the Host that SlideMage passes to activate(), and the types around it.

A plugin imports this module (and nothing else from SlideMage), so it is standard library only: no PySide6 at
import, and no other SlideMage module at runtime. The concrete host lives in slidemage.plugins; this file is
the contract, versioned by API_VERSION (a plugin's manifest names the version it was written for).

Conventions of all calls:

- Threads. Every call is made on the UI thread, and every callback the plugin hands over (run, enabled, when,
  build, done) is called on the UI thread, except soon (see add_render_priority) and the work of
  run_in_background.
- When. The add_* calls are for activate() only; after it returns, they raise RuntimeError. activate() runs at
  start, so nothing in it may use the network or take long.
- Decks. A Deck is a snapshot of one deck as SlideMage last read it. Changing the file does not change the
  object; a call that writes checks the file against deck.text and raises StaleFileError.
- Widgets. Widgets are PySide6 widgets, typed Any here so that this module needs no PySide6.
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
    from .project import ProjectContext
if TYPE_CHECKING:       # for type checkers only: at run time these load on first use (see __getattr__)
    from .ai.agent_types import (  # noqa: F401
        EDIT_ASK, EDIT_AUTO, AgentEvent, AgentMessage, AssistantMessage, Done, EditApplied, EditProposed,
        EditRejected, TextDelta, ToolCall, ToolFinished, ToolResult, ToolResultsMessage, ToolSpec, ToolStarted,
        UserMessage,
    )
    from .ai.providers import Cancelled, ChatProvider, ChatReply, ProviderError, parse_json_object  # noqa: F401
    from .ai.tools import ToolBox  # noqa: F401
    from .protected_regions import protected_spans  # noqa: F401

API_VERSION = 1
SUPPORTED_API_VERSIONS = frozenset({1})

T = TypeVar("T")

Widget = Any

COURSE_GROUP = "course"
"""The tag of the deck group "Course deck" in Deck.groups. The group belongs to SlideMage; a plugin only reads it."""


class StaleFileError(Exception):
    """The deck file changed on disk since the Deck was read: reload the deck and retry. Nothing was written."""


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


class TerminalService(Protocol):
    """SlideMage's embedded terminal (a pseudo-terminal and an xterm view in SlideMage's colours)."""

    def start(
        self, argv: list[str], env: dict[str, str] | None = None, cwd: Path | None = None, *,
        on_output: Callable[[bytes], None] | None = None, on_exit: Callable[[int], None] | None = None,
        with_widget: bool = True, cols: int = 80, rows: int = 24,
    ) -> TerminalSession:
        """Run argv (env defaults to SlideMage's own, cwd to the project folder). With a widget the program
        starts when the view has its size (once the widget is shown), and its output goes to the view as well as
        to on_output; without one it starts at once at cols x rows. on_exit(code) is called when it ends by itself.
        Raises OSError if the program cannot be started (when it starts at once)."""
        ...


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
        changes or its file does; when(deck) decides whether the box is shown at all, cheap and without the
        network. "compact" is a few lines at a glance (an entry of the panel picker); "large" is a working surface
        in the dock below the slide panels (not supported yet: raises NotImplementedError)."""
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

    def ai_tools(
        self, scope: Literal["slide", "deck"] = "slide", *, focus_slide: Path | None = None,
        mode: Literal["ask", "auto"] = "auto", cancel: Any = None, workspace: Any = None,
    ) -> "ToolBox":
        """The agent's tools as SlideMage's embedded Claude Code is offered them (read files, lint, render a preview,
        create/modify/add/insert slides, QR codes, guides...), for an MCP server or an agent loop of the plugin's
        own. scope limits where edits may reach ("slide": only focus_slide; "deck": the deck). mode "auto" applies
        edits at once, "ask" proposes them. cancel is a compiler.CancelToken (None: a fresh one). workspace is the
        slidemage.ai.workspace.Workspace the tools see (None: the project's files, with no editor buffers). Use
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
        the deck is untouched. Raises StaleFileError if the deck changed, OSError if a file cannot be written.
        Takes a moment (disk); call it from a button, not from a background thread."""
        ...

    def edit_deck_text(self, deck: Deck, change: Callable[[str], str]) -> str:
        """Replace the deck's text by change(text) in one write, and return the new text (the caller shows it; the
        next Deck SlideMage hands out has it too). Raises StaleFileError if the file differs from deck.text; an
        exception from change (a ValueError for a bad value) passes through and nothing is written. One undo step
        in SlideMage's deck history. change must be pure: no I/O."""
        ...

    def deck_language(self, deck: Deck) -> Literal["de", "en"]:
        """The language a compile of the deck uses. Reads deck.text only."""
        ...

    def open_url(self, url: str) -> None:
        """Open an http(s) URL in the user's default browser. Raises ValueError for any other scheme, and OSError
        when nothing could be started."""
        ...

    def open_deck_settings(self, deck: Deck, tab: str | None = None) -> None:
        """Open the Deck settings sheet for deck, on the tab with the title tab (a plugin's own tab, or one of
        SlideMage's) if given."""
        ...

    def log(self, message: str) -> None:
        """Write a line to SlideMage's log, marked with the plugin's id."""
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


class AiRoute(Protocol):
    """Something that answers AI requests: Ollama, Claude Code, the Anthropic API, or a plugin's own. Core
    registers one object per route (ai/routes.py) and asks it everything route-specific; no core module outside
    a route's own names a service. Every call is on the UI thread unless its text says otherwise, and none of
    them may use the network or take long except where noted."""

    id: str
    """Stable and lower-case ("ollama"); stored in settings and in a Route, so it never changes."""
    service: str
    """What the user calls it ("Ollama", "Claude Code", "Anthropic API"): the header reads "Local · <service>" or
    "Cloud · <service>"."""
    is_local: bool
    """Nothing leaves this computer: the route belongs to the Local side of the AI switch, else to Cloud."""
    tasks: frozenset[str]
    """Which of ai_profile.TASKS it can answer."""

    def problem(self, ctx: "ProjectContext", route: Route) -> str:
        """Why `route` (this route's, with its task and model) cannot run now, as a sentence ready to show, or ""
        when it can: no model chosen, no key, not installed. Asked before every request and for the pickers; cheap,
        no network."""
        ...

    def model_choices(self, ctx: "ProjectContext", task: str) -> list[str]:
        """The choices a picker offers for `task` without asking anyone: Claude Code's fixed list, the API's
        known models once a key is set. A route whose choices come from a server (Ollama's installed models) returns
        [] here and lists them itself in the background. Never the network."""
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

    def valid_choice(self, ctx: "ProjectContext", choice: str) -> bool:
        """Whether `choice` is one this route offers; a stored or picked choice that is not is ignored. A route
        with open-ended choices (any model name) accepts every non-empty string."""
        ...

    def work_label(self, route: Route) -> str:
        """What to show next to work done on `route`: "qwen3:8b · Ollama", "Claude Code · Haiku · effort medium"."""
        ...

    def provider(self, ctx: "ProjectContext", route: Route) -> "ChatProvider | None":
        """A new chat provider for `route` (one request's: abort() ends only that one), or None when the route
        has no chat provider of its own (Claude Code answers through task_runner and chat_surface). Does not check
        problem(): core does, and never falls back to another route."""
        ...

    def draft_backend(self, ctx: "ProjectContext", route: Route, cancel: "threading.Event | None" = None) -> Any:
        """What describes images on `route` (alt_draft's backend protocol: draft(), label, provider), or None:
        core then wraps provider() in alt_draft.ModelBackend. `cancel` ends a running request of a route that runs a
        process. Raises ProviderError when it cannot be made."""
        ...

    def translation_backend(self, ctx: "ProjectContext", route: Route, cancel: "threading.Event | None" = None) -> Any:
        """What translates image descriptions on `route` (alt_draft's translation protocol: translate()), or None:
        core then wraps provider() in alt_draft.ModelTranslationBackend."""
        ...

    def slide_translator(self, ctx: "ProjectContext", route: Route) -> Any:
        """What translates a slide body for the Add slide sheet (translate(body) -> (text, error), abort()), or
        None: core then wraps provider() in slide_add.translate_body."""
        ...

    def task_runner(self, ctx: "ProjectContext", route: Route) -> Callable[..., Any] | None:
        """For a route that runs the bubble tasks itself (Claude Code's `claude -p`): run(task, captured, request,
        cancel, span) -> Outcome, called on a worker thread. None: core runs them on provider()
        (ai/provider_tasks.py)."""
        ...

    def chat_surface(self, *args: Any, **kwargs: Any) -> Widget | None:
        """The widget that is the assistant's conversation on this route, built by the assistant with the
        arguments it has; None: core's chat view over provider(). Claude Code returns its terminal, which also
        has stop() and restart(choice, continue_conversation) for the AI setup's Switch now."""
        ...

    def settings_section(self) -> Callable[[], Widget] | None:
        """A builder for the route's own section of Settings' AI tab, or None for no section. Built when Settings opens."""
        ...
# -- the neutral AI types -----------------------------------------------------------------------------------------
# Re-exported from SlideMage's modules, which are not standard library, so they load on first use: importing this
# module stays cheap, and `from slidemage.plugin_api import ChatProvider` works. They are:
#   ai.providers   ChatProvider (Protocol of a model backend), ChatReply, ProviderError, Cancelled,
#                  parse_json_object(text) -> dict | None (the first JSON object in a model's answer)
#   ai.agent_types the agent chat's messages (UserMessage, AssistantMessage, ToolResultsMessage, AgentMessage),
#                  tool calls and results (ToolSpec, ToolCall, ToolResult), events (TextDelta, ToolStarted,
#                  ToolFinished, EditProposed, EditApplied, EditRejected, Done, AgentEvent), EDIT_ASK, EDIT_AUTO
#   ai.tools       ToolBox
#   protected_regions  protected_spans(text) -> [[start, end], ...]: the parts of a slide that tools and hooks
#                  refuse to change (header comment, \setSlideVersion, \vbox to 0pt blocks); read-only use.
_LAZY = {
    **{name: "slidemage.ai.providers" for name in
       ("ChatProvider", "ChatReply", "ProviderError", "Cancelled", "parse_json_object")},
    **{name: "slidemage.ai.agent_types" for name in
       ("ToolSpec", "ToolCall", "ToolResult", "UserMessage", "AssistantMessage", "ToolResultsMessage", "AgentMessage",
        "TextDelta", "ToolStarted", "ToolFinished", "EditProposed", "EditApplied", "EditRejected", "Done",
        "AgentEvent", "EDIT_ASK", "EDIT_AUTO")},
    "ToolBox": "slidemage.ai.tools",
    "protected_spans": "slidemage.protected_regions",
}


def __getattr__(name: str) -> Any:
    module = _LAZY.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(importlib.import_module(module), name)
    globals()[name] = value
    return value
