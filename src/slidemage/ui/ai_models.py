# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Qt glue shared by every AI model picker (UI redesign step 2, reworked by the workspace v6 route audit): filling
a picker with the models of the active route, turning the selection into a Route, and the one-time privacy
confirmation before the first cloud request in a project. One helper set so the pickers behave alike.

A picker lists only the models of the route the switch is on (ai_profile.resolve) and preselects the saved
default of that route for its task; its item data is the choice that ai_profile.route_for takes: an Ollama or
API model name, for Claude Code "<model>:<effort>". The caller turns the Route into a provider or backend
(ai/resolver.py). A picker is filled for one route: it is filled again when the route changes.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtWidgets import QComboBox, QMessageBox, QWidget

from ..ai import ai_profile, resolver
from ..ai.ai_profile import OLLAMA, Route
from ..ai.ollama_route import InstalledModel, OllamaProvider
from ..ai.providers import ChatProvider, ProviderError
from ..project import ProjectContext
from . import background
from .kit.widgets import ModalSheet, ModeBadge


class _Lister(QThread):
    loaded = Signal(object, object)         # this thread, [InstalledModel]

    def __init__(self, project: ProjectContext) -> None:
        super().__init__()
        self.project = project

    def run(self) -> None:
        self.loaded.emit(self, OllamaProvider.for_project(self.project).installed(detailed=True))


class LocalModelList(QObject):
    """The installed Ollama models, as the last answer of Ollama (asked on a thread, so that no picker waits
    on the network). `refresh()` asks again; `changed` follows each answer, and the pickers are filled from
    `models`, `vision` and `tools` then. Empty until the first answer."""

    changed = Signal()

    def __init__(self, project: ProjectContext, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.project = project
        self.installed: list[InstalledModel] = []
        self._lister: _Lister | None = None
        self._again = False

    @property
    def models(self) -> list[str]:
        return [model.name for model in self.installed]

    @property
    def vision(self) -> list[str]:
        return [model.name for model in self.installed if "vision" in model.capabilities]

    @property
    def tools(self) -> list[str]:
        return [model.name for model in self.installed if model.supports_tools]

    def refresh(self) -> None:
        """Ask Ollama; while an answer is out, one more question follows it."""
        if self._lister is not None:
            self._again = True
            return
        self._lister = lister = _Lister(self.project)
        lister.loaded.connect(self._on_loaded)
        background.start_detached(lister)

    def _on_loaded(self, lister: QThread, installed: list[InstalledModel]) -> None:
        if lister is not self._lister:
            return
        self._lister = None
        self.fill(installed)
        if self._again:
            self._again = False
            self.refresh()

    def fill(self, installed: list[InstalledModel]) -> None:
        """Take a list somebody else has just asked for (the Settings sheet)."""
        self.installed = installed
        self.changed.emit()


def fill_model_combo(
    project: ProjectContext, combo: QComboBox, task: str, empty_text: str, *, local_models: list[str] | None = None,
    vision_only: bool = False, fallback_local: str = "",
) -> bool:
    """(Re)fill `combo` with the models of the active route for `task` and preselect its saved default, else
    `fallback_local` when installed. Local lists `local_models` (the installed ones, asked of Ollama when None);
    API the Claude models once a key is set; Claude Code its models with their efforts. With nothing to offer it
    shows `empty_text` disabled and returns False."""
    route = ai_profile.resolve(project, task)
    combo.clear()
    if route.route == OLLAMA:
        if local_models is None:
            local_models = OllamaProvider.for_project(project).list_models(vision_only=vision_only)
        for model in local_models:
            combo.addItem(model, model)
    else:
        for choice in ai_profile.model_choices(project, route.route, task):
            combo.addItem(ai_profile.choice_label(route.route, choice), choice)
    usable = combo.count() > 0
    combo.setEnabled(usable)
    if not usable:
        combo.addItem(empty_text, "")
        return False
    index = combo.findData(ai_profile.model_choice(project, route.route, task))
    if index == -1 and fallback_local and route.is_local:
        index = combo.findData(fallback_local)
    if index != -1:
        combo.setCurrentIndex(index)
    return True


CLOUD_SUFFIX = " · cloud"


def cloud_label(project: ProjectContext, text: str) -> str:
    """`text` for a button that sends content to the AI: with " · cloud" while the AI switch is on Cloud."""
    return text if ai_profile.mode(project) == ai_profile.LOCAL else text + CLOUD_SUFFIX


def confirm_cloud_request(parent: QWidget, project: ProjectContext, label: str, what: str) -> bool:
    """Ask before the first cloud request in a project: it goes to `label`, naming what `what` is sent. A yes
    is remembered (ai_profile.mark_cloud_seen), so this is asked once per project."""
    answer = QMessageBox.question(
        parent, "Send to the cloud?",
        f"This request goes to the cloud ({label}) and sends {what} to Anthropic. Nothing is sent unless you "
        "agree.\n\nYou are asked this once per project; the Local setting for this project in Settings "
        "keeps everything on this computer.",
    )
    if answer != QMessageBox.StandardButton.Yes:
        return False
    ai_profile.mark_cloud_seen(project)
    return True


def picked_route(parent: QWidget, project: ProjectContext, combo: QComboBox, task: str, what: str) -> Route | None:
    """The Route of the picker's selection, or None after telling the user why not (nothing to pick, the route
    is not ready, or a first cloud request was declined)."""
    choice = combo.currentData() or ""
    route = ai_profile.resolve(project, task, choice)
    reason = resolver.problem(project, route) or ("" if choice else "No AI model is available on this route.")
    if reason:
        QMessageBox.critical(parent, "AI model", reason)
        return None
    return route if confirm_if_new(parent, project, route, what) else None


def confirm_if_new(parent: QWidget, project: ProjectContext, route: Route, what: str) -> bool:
    """Whether a request on `route` may go ahead: Local always; a cloud route once the project has been asked."""
    return route.is_local or ai_profile.cloud_seen(project) or confirm_cloud_request(parent, project, route.label, what)


def built(parent: QWidget, make, project: ProjectContext, route: Route):
    """`make(project, route)` (one of resolver's provider_for, draft_backend, translation_backend), or None
    after telling the user why the route cannot run it."""
    try:
        return make(project, route)
    except ProviderError as exc:
        QMessageBox.critical(parent, "AI model", str(exc))
        return None


def provider_from_combo(parent: QWidget, project: ProjectContext, combo: QComboBox, task: str, what: str) -> ChatProvider | None:
    """The provider for the picker's selection, or None after telling the user why not."""
    route = picked_route(parent, project, combo, task, what)
    return None if route is None else built(parent, resolver.provider_for, project, route)


def task_route(parent: QWidget, project: ProjectContext, task: str, what: str) -> Route | None:
    """The Route of the active route for `task`, for a place with no picker of its own; None after telling the
    user why not (the route is not ready, or a first cloud request was declined)."""
    route = ai_profile.resolve(project, task)
    if reason := resolver.problem(project, route):
        QMessageBox.critical(parent, "AI model", reason)
        return None
    return route if confirm_if_new(parent, project, route, what) else None


class RouteBadge(ModeBadge):
    """The route badge of a dialog (workspace v6 handoff, section 6): the route the switch is on, kept current while
    the dialog is open."""

    def __init__(self, state) -> None:
        super().__init__()
        self._state = state
        state.ai_route_changed.connect(self.refresh)
        self.refresh()

    def refresh(self, _route: str = "") -> None:
        route = Route(self._state.ai_route, ai_profile.CHAT)
        self.set_route(route.name, not route.is_local)


def add_route_badge(sheet: ModalSheet, window) -> None:
    """Put the route badge under `sheet`'s title. `window` is the main window (its `state`); a stand-in without
    one, as in a test, gets no badge."""
    if (state := getattr(window, "state", None)) is not None:
        sheet.add_under_title(RouteBadge(state))
