# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The real Host: the services behind slidemage.plugin_api.Host, one object per plugin.

PluginHost is a Registrar (it records the add_* calls) plus everything a plugin calls: its own cache folder and
settings, background work, the deck edits, opening URLs, logging. The calls that need a window (Page, Field,
caption, open_deck_settings, show_message) go to a HostUi; step 6 implements it on the main window. Without a
HostUi they raise RuntimeError("no window").
"""
from __future__ import annotations

import json
import logging
import os
import types
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal, Protocol, TypeVar
from urllib.parse import urlparse

from .. import deck_editor, deck_scan, open_path, plugin_api, project, slide_ids, slide_language, transcript
from ..deck_scan import Deck as CoreDeck
from ..fileio import StaleFileError as CoreStaleFileError
from ..fileio import atomic_write, read_text_exact
from ..project import ProjectContext
from .manifest import Manifest
from .registry import Registrar

T = TypeVar("T")


class HostUi(Protocol):
    """What the main window offers a plugin host (step 6)."""

    def open_deck_settings(self, deck: plugin_api.Deck, tab: str | None = None) -> None: ...
    def Page(self) -> Any: ...
    def Field(self, label: str, widget: Any) -> Any: ...
    def caption(self, text: str, tone: str = "") -> Any: ...
    def show_message(self, text: str, error: bool = False) -> None: ...
    def after_deck_edit(self, path: Path, summary: str, previous_text: str) -> None:
        """A plugin edit was written to the deck at `path`: do what a core deck edit does (rescan, refresh, history
        with previous_text for Undo)."""


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
        try:
            new = deck_editor.apply(deck.path, deck.text, change)
        except CoreStaleFileError as e:
            raise plugin_api.StaleFileError(str(e)) from e
        if new != deck.text:
            self._edited(deck, f"Edited {deck.name} ({self.manifest.name})")
        return new

    def deck_language(self, deck: plugin_api.Deck) -> Literal["de", "en"]:
        return "en" if transcript.deck_language_of(deck.text) == "en" else "de"

    def open_url(self, url: str) -> None:
        if urlparse(url).scheme.lower() not in ("http", "https"):
            raise ValueError(f"only http and https links can be opened, not {url!r}")
        open_path.open_in_default_app(url)

    def log(self, message: str) -> None:
        self._logger.info("%s", message)

    def show_message(self, text: str, error: bool = False) -> None:
        if self.ui is not None:
            self.ui.show_message(text, error)
        else:
            self._logger.log(logging.ERROR if error else logging.INFO, "%s", text)

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

    # -- helpers

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
