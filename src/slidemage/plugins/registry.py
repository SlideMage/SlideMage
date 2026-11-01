# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""What one plugin registered during activate(), and the Registrar that records it.

The Registrar is the part of the Host that only collects: step 2 subclasses it into the real host, which adds
the services (cache folders, deck edits, background work) and which the UI later reads the Contributions from.
The calls that are not add_* raise NotImplementedError here, so a half-built host fails loudly.
"""
from __future__ import annotations

from collections.abc import Callable
import re
import sys
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

from ..plugin_api import FooterAction
from .manifest import Manifest

MENUS = ("deck",)
ENTRY_NAME = re.compile(r"[a-z][a-z0-9_-]*\Z")
PLUGIN_FLAG = "--plugin"       # cli.py: SlideMage --plugin <id>:<name> [args...]
SETTINGS_PAGES = ("ai",)

BoxRefresher = Callable[[str, str], None]
"""(plugin id, box key) -> None: the window's side panels build that box again (see refresh_sidebar_box)."""
_box_refresher: BoxRefresher | None = None


def set_box_refresher(refresher: BoxRefresher | None) -> None:
    """Where Registrar.refresh_sidebar_box goes; plugin_ui sets it when the window attaches."""
    global _box_refresher
    _box_refresher = refresher


@dataclass(frozen=True)
class CommandEntry:
    id: str
    title: str
    run: Callable[[Any], None]
    enabled: Callable[[Any], bool]


@dataclass(frozen=True)
class DeckSettingsTab:
    title: str
    build: Callable[[Any], Any]
    footer_action: FooterAction | None


@dataclass(frozen=True)
class SettingsTab:
    title: str
    build: Callable[[], Any]


@dataclass(frozen=True)
class SettingsSection:
    page: str
    title: str
    build: Callable[[], Any]


@dataclass(frozen=True)
class SidebarBox:
    key: str
    title: str
    build: Callable[[Any], Any]
    size: str
    when: Callable[[Any], bool]


@dataclass
class Contributions:
    """Everything a plugin registered, in registration order."""

    commands: list[CommandEntry] = field(default_factory=list)
    menu_entries: list[tuple[str, str]] = field(default_factory=list)  # (menu, command id)
    deck_settings_tabs: list[DeckSettingsTab] = field(default_factory=list)
    settings_tabs: list[SettingsTab] = field(default_factory=list)
    settings_sections: list[SettingsSection] = field(default_factory=list)
    sidebar_boxes: list[SidebarBox] = field(default_factory=list)
    render_priorities: list[Callable[[Any], bool]] = field(default_factory=list)
    entry_points: dict[str, Callable[[list[str]], int]] = field(default_factory=dict)
    ai_routes: list[Any] = field(default_factory=list)


class Registrar:
    """Records the add_* calls of one plugin, only while activation() is open."""

    def __init__(self, manifest: Manifest) -> None:
        self.manifest = manifest
        self.contributions = Contributions()
        self._open = False

    @contextmanager
    def activation(self):
        """The window in which add_* calls are allowed; the loader wraps activate() in it."""
        self._open = True
        try:
            yield
        finally:
            self._open = False

    def _check_open(self) -> None:
        if not self._open:
            raise RuntimeError("add_* calls are only allowed while activate() runs")

    def add_command(
        self, id: str, title: str, run: Callable[[Any], None], enabled: Callable[[Any], bool] = lambda deck: True,
    ) -> None:
        self._check_open()
        if not id.startswith(self.manifest.id + "."):
            raise ValueError(f"command id {id!r} must start with {self.manifest.id + '.'!r}")
        if any(c.id == id for c in self.contributions.commands):
            raise ValueError(f"command {id!r} is already registered")
        self.contributions.commands.append(CommandEntry(id, title, run, enabled))

    def add_menu_entry(self, menu: str, command_id: str) -> None:
        self._check_open()
        if menu not in MENUS:
            raise ValueError(f"unknown menu {menu!r}")
        if not any(c.id == command_id for c in self.contributions.commands):
            raise ValueError(f"unknown command {command_id!r}: register it before putting it in a menu")
        self.contributions.menu_entries.append((menu, command_id))

    def add_deck_settings_tab(
        self, title: str, build: Callable[[Any], Any], footer_action: FooterAction | None = None,
    ) -> None:
        self._check_open()
        self.contributions.deck_settings_tabs.append(DeckSettingsTab(title, build, footer_action))

    def add_settings_tab(self, title: str, build: Callable[[], Any]) -> None:
        self._check_open()
        self.contributions.settings_tabs.append(SettingsTab(title, build))

    def add_ai_route(self, route: Any) -> None:
        self._check_open()
        if any(existing.id == route.id for existing in self.contributions.ai_routes):
            raise ValueError(f"AI route {route.id!r} is already registered")
        self.contributions.ai_routes.append(route)

    def add_settings_section(self, page: str, title: str, build: Callable[[], Any]) -> None:
        self._check_open()
        if page not in SETTINGS_PAGES:
            raise ValueError(f"unknown settings page {page!r}")
        self.contributions.settings_sections.append(SettingsSection(page, title, build))

    def add_sidebar_box(
        self, key: str, title: str, build: Callable[[Any], Any], size: str = "compact",
        when: Callable[[Any], bool] = lambda deck: True,
    ) -> None:
        self._check_open()
        if size == "large":
            raise NotImplementedError("large boxes are not supported yet")
        if size != "compact":
            raise ValueError(f"unknown box size {size!r}")
        if any(b.key == key for b in self.contributions.sidebar_boxes):
            raise ValueError(f"sidebar box {key!r} is already registered")
        self.contributions.sidebar_boxes.append(SidebarBox(key, title, build, size, when))

    def add_render_priority(self, soon: Callable[[Any], bool]) -> None:
        self._check_open()
        self.contributions.render_priorities.append(soon)

    def add_entry_point(self, name: str, fn: Callable[[list[str]], int]) -> None:
        self._check_open()
        if not ENTRY_NAME.match(name):
            raise ValueError(f"entry point name {name!r} must be lower case letters, digits, '-' and '_'")
        if name in self.contributions.entry_points:
            raise ValueError(f"entry point {name!r} is already registered")
        self.contributions.entry_points[name] = fn

    def entry_point_command(self, name: str) -> list[str]:
        """The argv that runs an entry point: a frozen build has no `python -m`, its executable takes the flag."""
        spec = f"{self.manifest.id}:{name}"
        if getattr(sys, "frozen", False):
            return [sys.executable, PLUGIN_FLAG, spec]
        return [sys.executable, "-m", "slidemage", PLUGIN_FLAG, spec]

    def refresh_sidebar_box(self, key: str) -> None:
        if not any(b.key == key for b in self.contributions.sidebar_boxes):
            raise ValueError(f"unknown sidebar box {key!r}")
        if _box_refresher is not None:
            _box_refresher(self.manifest.id, key)

    # The services belong to the real host (step 2).
    def _unavailable(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError("this host does not offer that call")

    cache_dir = legacy_cache_dir = settings = run_in_background = insert_positions = _unavailable
    insert_slides = edit_deck_text = deck_language = open_url = open_deck_settings = _unavailable
    log = show_message = Page = Field = caption = _unavailable
    project_root = deck_output_folder = deck_slides = slide_source = open_slide = _unavailable
    terminal = watch_external_edits = credentials = ai_tools = focus = ai_chat = _unavailable
