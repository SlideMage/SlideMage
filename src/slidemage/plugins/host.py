# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The real Host: the services behind slidemage.plugin_api.Host, one object per plugin.

PluginHost is a Registrar (it records the add_* calls) plus everything a plugin calls: its own cache folder and
settings, background work, the deck edits, reading slides, opening URLs, logging. The calls that need a window
(Page, Field, caption, open_deck_settings, open_slide, show_message) go to a HostUi; step 6 implements it on the main window. Without a
HostUi they raise RuntimeError("no window").
"""
from __future__ import annotations

import dataclasses
import json
import logging
import os
import types
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal, Protocol, TypeVar
from urllib.parse import urlparse

from .. import (app_settings, deck_editor, deck_scan, diagnostics, open_path, plugin_api, project, slide_ids, slide_language,
               transcript)
from ..deck_scan import Deck as CoreDeck
from ..fileio import StaleFileError as CoreStaleFileError
from ..fileio import atomic_write, read_text_exact
from ..project import ProjectContext
from .credentials import PluginCredentials
from .manifest import Manifest
from . import slide_reader
from .registry import Registrar

T = TypeVar("T")
# Host.log's levels, by name, as plugins pass them.
_LOG_LEVELS = {"debug": logging.DEBUG, "info": logging.INFO, "warning": logging.WARNING, "error": logging.ERROR}


class HostUi(Protocol):
    """What the main window offers a plugin host (step 6)."""

    def try_start_route_task(self, route_id: str, label: str, owner: object) -> bool: ...
    def end_route_task(self, route_id: str, owner: object) -> None: ...
    def open_deck_settings(self, deck: plugin_api.Deck, tab: str | None = None) -> None: ...
    def open_slide(self, path: Path) -> None:
        """Show the slide file at `path` in the editor (the Source view)."""
    def Page(self) -> Any: ...
    def Field(self, label: str, widget: Any) -> Any: ...
    def caption(self, text: str, tone: str = "") -> Any: ...
    def show_message(self, text: str, error: bool = False) -> None: ...
    def deck_edit_blocker(self, path: Path) -> str | None:
        """Why a plugin may not edit the deck at `path` now (a Deck settings sheet of it has unsaved changes), or
        None."""
    def after_deck_edit(self, path: Path, summary: str, previous_text: str) -> None:
        """A plugin edit was written to the deck at `path`: do what a core deck edit does (rescan, refresh, history
        with previous_text for Undo)."""

    def track_plugin_window(self, window: Any) -> None:
        """A plugin's Window: to be asked to close before SlideMage closes."""
    def add_theme_listener(self, listener: Callable[[bool], None]) -> Callable[[], None]:
        """Call listener(dark) after a theme switch; returns the function that removes it."""

    # Optional (the host asks with getattr): the terminal's colours, what the user is looking at, and the theme.
    # def terminal_tokens(self) -> Tokens
    # def focus(self) -> plugin_api.Focus
    # def dark(self) -> bool | None


# -- deck snapshot ---------------------------------------------------------------------------------------------

class DeckSnapshot:
    """A plugin_api.Deck: the deck as SlideMage last read it."""

    def __init__(self, name: str, path: Path, text: str, groups: tuple[str, ...]) -> None:
        self.name, self.path, self.text, self.groups = name, path, text, tuple(groups)

    def __repr__(self) -> str:
        return f"DeckSnapshot({self.name!r})"


def deck_snapshot(deck: CoreDeck, ctx: ProjectContext | None = None) -> plugin_api.Deck:
    """The plugin's read-only view of a scanned deck. ctx is accepted for symmetry with the host; unused."""
    return DeckSnapshot(deck.name, deck.path, deck.text, tuple(deck.groups or ()))


# -- settings --------------------------------------------------------------------------------------------------

class PluginSettings:
    """A plugin's key-value store: JSON at config_dir()/plugins/settings/<id>.json, in memory until save()."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._data: dict[str, Any] = {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                self._data = data
        except (OSError, ValueError):
            pass

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        json.dumps(value)               # refuse what JSON cannot hold now, not at save()
        self._data[key] = value

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        try:
            tmp.write_text(json.dumps(self._data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            os.replace(tmp, self.path)
        finally:
            tmp.unlink(missing_ok=True)


# -- the host --------------------------------------------------------------------------------------------------

class _RouteTaskLease:
    def __init__(self, release: Callable[[], None]) -> None:
        self._release = release

    def release(self) -> None:
        release, self._release = self._release, lambda: None
        release()

    def __enter__(self) -> _RouteTaskLease:
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.release()


def acquire_route_task(ui: HostUi, route_id: str, label: str) -> plugin_api.RouteTaskLease | None:
    """Use the same ownership and lease semantics for core and plugin work."""
    owner = object()
    if not ui.try_start_route_task(route_id, label, owner):
        return None
    return _RouteTaskLease(lambda: ui.end_route_task(route_id, owner))


class PluginHost(Registrar):
    def __init__(self, manifest: Manifest, ctx: ProjectContext, ui: HostUi | None = None) -> None:
        super().__init__(manifest)
        self.ctx = ctx
        self.ui = ui
        self._settings: PluginSettings | None = None
        self._logger = logging.getLogger(f"slidemage.plugins.{manifest.id}")

    # -- what it is given

    def cache_dir(self) -> Path:
        path = project.cache_dir() / "plugins" / self.manifest.id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def legacy_cache_dir(self) -> Path | None:
        path = project.cache_dir()
        return path if path.is_dir() else None

    def settings(self) -> PluginSettings:
        if self._settings is None:
            self._settings = PluginSettings(
                project.config_dir() / "plugins" / "settings" / f"{self.manifest.id}.json")
        return self._settings

    # -- what it calls

    def run_in_background(
        self, work: Callable[[], T], done: Callable[[T | None, BaseException | None], None],
    ) -> None:
        from PySide6.QtCore import QThread

        from ..ui.background import start_detached

        class Worker(QThread):
            result: Any = None
            error: BaseException | None = None

            def run(self) -> None:
                try:
                    self.result = work()
                except BaseException as e:      # handed to done(), never lost on the thread
                    self.error = e

        thread = Worker()

        def finished() -> None:
            try:
                done(thread.result, thread.error)
            except Exception:
                self._logger.exception("done() of run_in_background raised")
            finally:
                thread.deleteLater()

        start_detached(thread, finished)

    def insert_positions(self, deck: plugin_api.Deck) -> list[plugin_api.InsertPosition]:
        view = types.SimpleNamespace(text=deck.text, chapters=deck_scan.parse_chapters(deck.text))
        return [plugin_api.InsertPosition(p.label, p.insert_at, p.indent)
                for p in deck_editor.slide_insert_positions(view)]     # type: ignore[arg-type]

    def insert_slides(
        self, deck: plugin_api.Deck, position: plugin_api.InsertPosition, slides: list[tuple[str, str]],
        language: Literal["de", "en"],
    ) -> list[Path]:
        ctx = self.ctx
        self._check_editable(deck)
        self._check_fresh(deck)
        csv = ctx.slide_ids_csv
        csv_before = csv.read_bytes() if csv.is_file() else None
        created: list[Path] = []
        id_slugs: list[str] = []
        try:
            for id_suffix, frame in slides:
                slide_id = slide_ids.mint_slide_id(ctx)
                id_slug = f"{slide_id}-{'EN' if language == 'en' else 'DE'}-{id_suffix}"
                path = ctx.slides_dir / slide_language.current_name(id_slug)
                path.parent.mkdir(parents=True, exist_ok=True)
                if path.exists():
                    raise FileExistsError(f"{path.name} exists already")
                slide_ids.append_slide_id(ctx, slide_id)        # reserved before the deck is edited
                created.append(path)        # tracked before it is written: a failure midway removes it too
                atomic_write(path, _slide_source(frame))         # staged beside, then renamed: never half a slide
                id_slugs.append(id_slug)
            try:
                # one atomic replacement of the deck, checked against deck.text at the moment of the commit
                deck_editor.insert_slide_calls(deck.path, deck.text, position.insert_at, position.indent, id_slugs)
            except CoreStaleFileError as e:
                raise plugin_api.StaleFileError(str(e)) from e
        except BaseException:
            for path in created:
                path.unlink(missing_ok=True)
            if csv_before is None:
                csv.unlink(missing_ok=True)
            else:
                atomic_write(csv, csv_before)
            raise
        self._edited(deck, f"Inserted {len(created)} slide(s) into {deck.name} ({self.manifest.name})")
        return created

    def edit_deck_text(self, deck: plugin_api.Deck, change: Callable[[str], str]) -> str:
        self._check_editable(deck)
        try:
            new = deck_editor.apply(deck.path, deck.text, change)
        except CoreStaleFileError as e:
            raise plugin_api.StaleFileError(str(e)) from e
        if new != deck.text:
            self._edited(deck, f"Edited {deck.name} ({self.manifest.name})")
        return new

    def deck_language(self, deck: plugin_api.Deck) -> Literal["de", "en"]:
        return "en" if transcript.deck_language_of(deck.text) == "en" else "de"

    def project_root(self) -> Path:
        return self.ctx.root

    def deck_output_folder(self, deck: plugin_api.Deck, view: str = "instructor") -> Path:
        return slide_reader.output_folder(self.ctx, deck, view)

    def deck_slides(self, deck: plugin_api.Deck, view: str, language: Literal["de", "en"]) -> list[plugin_api.SlideRef]:
        return slide_reader.deck_slides(self.ctx, deck, view, language)

    def slide_source(self, ref: plugin_api.SlideRef) -> plugin_api.SlideSource:
        return slide_reader.slide_source(self.ctx, ref)

    def open_slide(self, ref: plugin_api.SlideRef) -> None:
        self._window().open_slide(slide_reader.check_slide_path(self.ctx, ref))

    def open_url(self, url: str) -> None:
        if urlparse(url).scheme.lower() not in ("http", "https"):
            raise ValueError(f"only http and https links can be opened, not {url!r}")
        open_path.open_in_default_app(url)

    def log(self, message: str, level: str = "info") -> None:
        number = _LOG_LEVELS.get(level)
        if number is None:
            raise ValueError(f"level must be one of {', '.join(_LOG_LEVELS)}, not {level!r}")
        self._logger.log(number, "%s", message)

    def debug_enabled(self) -> bool:
        return diagnostics.debug_enabled()

    def show_message(self, text: str, error: bool = False) -> None:
        if self.ui is not None:
            self.ui.show_message(text, error)
        else:
            self._logger.log(logging.ERROR if error else logging.INFO, "%s", text)

    def ai_chat(self) -> plugin_api.AiChat:
        from ..ai.chat import ChatService

        return ChatService(self.ctx)

    # -- services of the AI host API

    def terminal(self) -> plugin_api.TerminalService:
        from ..ui.workspace.terminal.service import TerminalService

        ui = self._window()
        tokens = getattr(ui, "terminal_tokens", None)
        return TerminalService(self.ctx.root, tokens)       # type: ignore[return-value]

    def watch_external_edits(self, on_change: Callable[[plugin_api.ExternalEdits], None]) -> plugin_api.EditWatch:
        from ..ui.workspace.terminal.sync import ExternalEditWatch

        return ExternalEditWatch(self.ctx.root, on_change)      # type: ignore[return-value]

    def credentials(self, env_var: str | None = None) -> PluginCredentials:
        return PluginCredentials(self.manifest.id, env_var)

    def acquire_route_task(self, route_id: str, label: str) -> plugin_api.RouteTaskLease | None:
        return acquire_route_task(self._window(), route_id, label)

    def model_choices_changed(self, route_id: str) -> None:
        notify = getattr(self.ui, "model_choices_changed", None)
        if notify is not None:
            notify(route_id)

    def legacy_secret(self, name: Literal["anthropic_api_key"]) -> str | None:
        if name != "anthropic_api_key":
            raise ValueError(f"unknown legacy secret: {name}")
        from .migrate import legacy_anthropic_key

        return legacy_anthropic_key(self.ctx)

    def legacy_ollama_host(self) -> str:
        from ..app_settings import peek_ollama_host

        return peek_ollama_host(self.ctx)

    def run_in_background_with_progress(self, work, progress, done) -> None:
        from PySide6.QtCore import QObject, QThread, Signal

        from ..ui.background import start_detached

        class Worker(QThread):
            reported = Signal(object)
            result = None
            error = None

            def run(self) -> None:
                try:
                    self.result = work(self.reported.emit)
                except BaseException as exc:
                    self.error = exc

        class Receiver(QObject):
            def report(self, value) -> None:
                try:
                    progress(value)
                except Exception:
                    self_logger.exception("progress callback raised")

        self_logger = self._logger
        thread = Worker()
        receiver = Receiver()
        thread.reported.connect(receiver.report)

        def finished() -> None:
            try:
                done(thread.result, thread.error)
            except Exception:
                self._logger.exception("done callback raised")
            finally:
                receiver.deleteLater()
                thread.deleteLater()

        start_detached(thread, finished)

    def ai_tools(
        self, scope: Literal["slide", "deck"] = "slide", *, focus_slide: Path | None = None,
        mode: Literal["ask", "auto"] = "auto", cancel: Any = None, workspace: Any = None,
    ) -> Any:
        if scope not in ("slide", "deck"):
            raise ValueError(f"scope must be 'slide' or 'deck', not {scope!r}")
        if mode not in ("ask", "auto"):
            raise ValueError(f"mode must be 'ask' or 'auto', not {mode!r}")
        from ..ai.agent_toolbox import agent_toolbox
        from ..ai.workspace import Workspace

        if workspace is not None:
            from ..ui.workspace.chat.plugin_surface import ToolWorkspace
            if isinstance(workspace, ToolWorkspace):
                workspace = workspace._workspace
        return agent_toolbox(workspace or Workspace(self.ctx), scope, focus_slide, cancel, mode)

    def focus(self) -> plugin_api.Focus:
        read = getattr(self.ui, "focus", None)
        return read() if read is not None else plugin_api.Focus(None, None, "slide")

    # -- the window

    def _window(self) -> HostUi:
        if self.ui is None:
            raise RuntimeError("no window")
        return self.ui

    def open_deck_settings(self, deck: plugin_api.Deck, tab: str | None = None) -> None:
        self._window().open_deck_settings(deck, tab)

    def Page(self) -> Any:
        return self._window().Page()

    def Field(self, label: str, widget: Any) -> Any:
        return self._window().Field(label, widget)

    def caption(self, text: str, tone: Literal["", "error"] = "") -> Any:
        return self._window().caption(text, tone)

    def Surface(self):
        from ..ui.kit.widgets import Surface
        return Surface()

    def Button(self, text, kind="secondary", *, compact=False):
        from ..ui.kit.widgets import Button
        return Button(text, kind, compact=compact)

    def Chip(self, text, tone="neutral", *, icon=None, elide=False, pressable=False):
        from ..ui.kit.widgets import Chip
        return Chip(text, tone, icon, pressable=pressable, elide=elide)

    def Window(self, title):
        from ..ui.kit.widgets import ToolWindow
        window = ToolWindow(title)
        self._window().track_plugin_window(window)
        return window

    def Card(self, raised=False):
        from ..ui.kit.widgets import Card
        return Card(raised=raised)

    def SegmentedControl(self, items, current=None):
        from ..ui.kit.widgets import SegmentedControl
        return SegmentedControl(items, current=current, roving=True)

    def Badge(self, text, tone="neutral"):
        from ..ui.kit.widgets import Badge
        return Badge(text, tone)

    def ElidedLabel(self, text):
        from ..ui.kit.widgets import ElidedLabel
        return ElidedLabel(text)

    def RowButton(self, title, sub="", *, icon=None, chip=("", ""), selectable=False):
        from ..ui.kit.widgets import RowButton
        return RowButton(icon, title, sub, chip=chip, selectable=selectable, elide_title=True)

    def PlainList(self):
        from ..ui.kit.widgets import PlainList
        return PlainList()

    def Label(self, text, role="body"):
        from ..ui.kit.widgets import text_label
        return text_label(text, role)

    def ModalSheet(self, title, parent=None):
        from ..ui.kit.widgets import ModalSheet
        return ModalSheet(title, parent)

    def toast(self, parent, text):
        from ..ui.kit.widgets import Toast
        toast = next((c for c in parent.findChildren(Toast)), None) or Toast(parent)
        toast.show_message(text)

    def IconButton(self, icon, tooltip):
        from ..ui.kit.widgets import IconButton
        return IconButton(icon, tooltip)

    def IconLabel(self, icon, size):
        from ..ui.kit.widgets import IconLabel
        return IconLabel(icon, size)

    def style_chat_widget(self, widget, role):
        from ..ui.kit import kit_qss as q
        widget.setObjectName({"surface": q.SURFACE, "cloud_card": q.CLOUD_CARD, "title": q.ASSISTANT_TITLE}[role])

    def theme_color(self, role):
        if role != "info":
            raise ValueError(role)
        return self.theme().info

    def theme(self) -> plugin_api.ThemeTokens:
        read = getattr(self.ui, "dark", None)
        dark = read() if read is not None else None
        return _theme_tokens(bool(app_settings.get(self.ctx, "dark_mode", True)) if dark is None else dark)

    def on_theme_changed(self, callback: Callable[[plugin_api.ThemeTokens], None]) -> Callable[[], None]:
        def changed(dark: bool) -> None:
            try:
                callback(_theme_tokens(dark))
            except Exception as exc:        # a plugin's bug is a message, not a crash
                self._logger.exception("a theme listener raised")
                self.show_message(f"{self.manifest.name}: a theme listener failed: {exc}", error=True)

        return self._window().add_theme_listener(changed)

    # -- helpers

    def _check_editable(self, deck: plugin_api.Deck) -> None:
        """Refuse a plugin edit while the Deck settings sheet of this deck holds unsaved changes."""
        blocker = getattr(self.ui, "deck_edit_blocker", None)
        reason = blocker(deck.path) if blocker is not None else None
        if reason:
            raise plugin_api.EditRefusedError(reason)

    def _edited(self, deck: plugin_api.Deck, summary: str) -> None:
        """The edit is on disk: let the window run what a core deck edit runs. A failure here is the window's
        problem and is logged; the plugin's edit did succeed."""
        after = getattr(self.ui, "after_deck_edit", None)
        if after is None:
            return
        try:
            after(deck.path, summary, deck.text)
        except Exception:
            self._logger.exception("the window's refresh after a deck edit raised")

    def _check_fresh(self, deck: plugin_api.Deck) -> None:
        try:
            current = read_text_exact(deck.path)
        except OSError as e:
            raise plugin_api.StaleFileError(f"{deck.path.name} cannot be read: {e}") from e
        if current != deck.text:
            raise plugin_api.StaleFileError(f"{deck.path.name} changed on disk since it was last loaded.")


def _theme_tokens(dark: bool) -> plugin_api.ThemeTokens:
    """The plugin's view of the design tokens (tokens.py): a chosen subset, so that the others can still change."""
    from ..ui.kit import tokens

    t = tokens.tokens_for(dark)
    names = (f.name for f in dataclasses.fields(plugin_api.ThemeTokens) if hasattr(t, f.name))
    return plugin_api.ThemeTokens(
        dark=dark, radius_sm=tokens.RADIUS_SM, radius_md=tokens.RADIUS_MD, font_sans=tokens.FONT_SANS,
        font_mono=tokens.FONT_MONO, **{name: getattr(t, name) for name in names})


def _slide_source(frame: str) -> str:
    """A generated LaTeX frame in the normal editable slide format: file header, version, the frame (CRLF)."""
    frame = frame.strip().replace("\r\n", "\n").replace("\r", "\n")
    return slide_ids.build_new_slide_header() + "\r\n".join([r"\setSlideVersion{1-0-0}", frame, ""])


# -- render priority -------------------------------------------------------------------------------------------

def plugin_render_priority(loaded: list, ctx: ProjectContext | None = None) -> Callable[[CoreDeck], bool]:
    """One soon(core deck) over every loaded plugin's render priorities: true if any says true. An exception
    counts as False and is logged once per plugin."""
    entries = [(p.id, soon) for p in loaded if p.state == "loaded" for soon in p.contributions.render_priorities]
    failed: set[str] = set()

    def soon(deck: CoreDeck) -> bool:
        if not entries:
            return False
        snapshot = deck_snapshot(deck, ctx)
        for plugin_id, check in entries:
            try:
                if check(snapshot):
                    return True
            except Exception:
                if plugin_id not in failed:
                    failed.add(plugin_id)
                    logging.getLogger(f"slidemage.plugins.{plugin_id}").exception(
                        "render priority raised; counted as False")
        return False

    return soon
