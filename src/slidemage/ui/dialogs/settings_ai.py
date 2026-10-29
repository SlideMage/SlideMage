# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The AI tab of the Settings sheet (PLUGINS_REMAINING_PLAN.md, step 3c): one page for everything about AI.

From top to bottom: the German address and the glossary; the project's Local | Cloud policy and which cloud route
Cloud means; the model of each task on the local route and on the chosen cloud route (every registered route offers
its own models); the prompts (ui/dialogs/settings_prompts.py); then one section per service of the registered AI
routes (ai/routes.py) that have a `settings_section`, titled by the service, then the plugins' sections
(`Host.add_settings_section("ai", title, build)`).

Routes of one service share a section: Claude's two routes (Anthropic API, Claude Code) are both service "Claude",
so their `settings_section` widgets are stacked in one section, and a plugin that registers one route of its own
needs nothing from any other. The built-in routes' builders (`build_*_section`) find the sheet's app through
`building()`, which is set only while the page builds its sections.

The tab is only in the sheet when at least one AI route is registered (settings.py).
"""
from __future__ import annotations

import logging

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QGridLayout, QLabel, QVBoxLayout, QWidget

from ...ai import ai_profile, routes, translation_style
from ...ai.ai_profile import CHAT, CLAUDE_CODE, CLOUD, LOCAL, TASKS, TASK_LABELS
from ...project import ProjectContext
from ..kit.widgets import Field, Page, SegmentedControl, caption
from .settings_prompts import PromptsTab

log = logging.getLogger(__name__)
PROMPTS_KEY = "prompts"             # the key of the prompts section (Settings alias PROMPTS)
NO_MODEL = "(none chosen)"
POLICIES = ((LOCAL, "Local"), (CLOUD, "Cloud"))


def profile_key(route) -> str:
    """The key ai_profile saves the route's settings under (a plugin's route: its id)."""
    return route.id


_building: AiPage | None = None


def building() -> AiPage:
    """The page that is building its sections (for the built-in routes' builders)."""
    if _building is None:
        raise RuntimeError("a settings section is built only by the AI tab")
    return _building


class LanguageBlock(Page):
    """How Claude Code translations address the audience in German, and the glossary."""

    def __init__(self, project: ProjectContext) -> None:
        super().__init__()
        layout = self.body
        self.address = SegmentedControl(tuple((a, a) for a in translation_style.ADDRESSES),
                                        current=translation_style.de_address(project))
        self.address.changed.connect(lambda value: translation_style.set_de_address(project, value))
        layout.addWidget(Field("German address in Claude Code translations (this project)", self.address))
        layout.addWidget(caption(
            f"Put terms that must be translated one way in {translation_style.GLOSSARY_PATH}, one \"English = "
            "German\" per line; every translation request carries the file as it is."))


class ModelsGrid(QWidget):
    """The model of each task on the local route and on the chosen cloud route, saved as the user's defaults."""

    def __init__(self, app) -> None:
        super().__init__()
        self.app, self.project = app, app.project
        self.installed: list = []
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 1)
        grid.addWidget(QLabel("Task"), 0, 0)
        self.heads = {LOCAL: QLabel(), CLOUD: QLabel()}
        grid.addWidget(self.heads[LOCAL], 0, 1)
        grid.addWidget(self.heads[CLOUD], 0, 2)
        self.cells: dict[tuple[str, str], QComboBox] = {}
        for index, task in enumerate(TASKS, start=1):
            grid.addWidget(QLabel(TASK_LABELS[task]), index, 0)
            for column, side in ((1, LOCAL), (2, CLOUD)):
                combo = QComboBox()
                combo.setAccessibleName(f"{TASK_LABELS[task]} · {'Local' if side == LOCAL else 'Cloud'} model")
                combo.activated.connect(lambda i, s=side, t=task: self._on_cell(s, t, i))
                self.cells[(side, task)] = combo
                grid.addWidget(combo, index, column)
        self.refresh()

    def _route(self, side: str):
        """The route a column shows: the first local one, or the chosen cloud one."""
        if side == LOCAL:
            return next(iter(routes.on_side(True)), None)
        chosen = ai_profile.cloud_conn(self.project)
        cloud = routes.on_side(False)
        return next((r for r in cloud if profile_key(r) == chosen), cloud[0] if cloud else None)

    def _offered(self, route, task: str) -> list[str]:
        return list(route.model_choices(routes.context(self.project, route.id), task))

    def set_installed(self, installed: list) -> None:
        self.installed = installed
        self.refresh()

    def refresh(self) -> None:
        for side in (LOCAL, CLOUD):
            route = self._route(side)
            self.heads[side].setText(f"{'Local' if side == LOCAL else 'Cloud'} · {route.service}" if route else "—")
            for task in TASKS:
                combo = self.cells[(side, task)]
                combo.setEnabled(route is not None)
                self._fill(combo, route, task)

    def _fill(self, combo: QComboBox, route, task: str) -> None:
        combo.blockSignals(True)
        combo.clear()
        if route is not None:
            key = profile_key(route)
            saved = ai_profile.model_choice(self.project, key, task)
            if route.is_local:
                combo.addItem(NO_MODEL, "")
            elif key == CLAUDE_CODE and task == CHAT:
                combo.addItem("Claude Code default", "")
            for choice in self._offered(route, task):
                combo.addItem(ai_profile.choice_label(key, choice), choice)
            if saved and combo.findData(saved) == -1:
                combo.addItem(f"{ai_profile.choice_label(key, saved)} (not available)", saved)
            combo.setCurrentIndex(max(0, combo.findData(saved)))
        combo.blockSignals(False)

    def _on_cell(self, side: str, task: str, index: int) -> None:
        route = self._route(side)
        if route is None:
            return
        choice = self.cells[(side, task)].itemData(index) or ""
        ai_profile.set_model_choice(self.project, profile_key(route), task, choice)
        refresh = getattr(self.app, "refresh_ai_models", None)
        if refresh is not None:
            refresh()


def _safe_build(owner: str, title: str, build) -> QWidget:
    """The section's widget, or, when its build() raises, a line that says so (the sheet still opens)."""
    try:
        return build()
    except Exception as exc:
        log.exception("settings section %r of %s failed", title, owner)
        return caption(f"{owner} could not build this section: {exc}", "error")


class AiPage(Page):
    changed = Signal()               # the Ollama address or models, or the API key changed: ask Ollama again

    def __init__(self, app, plugin_sections=()) -> None:
        """`app` is the window. `plugin_sections` is [(plugin name, SettingsSection)] of the active plugins."""
        super().__init__()
        global _building
        self.app, self.project = app, app.project
        self.ollama = None
        self.cloud = None
        self.sections: dict[str, QWidget] = {}          # key (service, PROMPTS_KEY or a plugin's title) -> section
        layout = self.body
        layout.addWidget(caption(
            "A cloud route receives whatever its task sends: slide text, images, notes. Which side the project "
            "uses is the Local | Cloud switch at the top of the assistant; the settings below are its defaults."))
        self.language = LanguageBlock(self.project)
        layout.addWidget(self.language)

        self.policy = SegmentedControl(POLICIES, current=ai_profile.policy(self.project))
        self.policy.setAccessibleName("Project setting")
        self.policy.changed.connect(lambda value: ai_profile.set_policy(self.project, value))
        layout.addWidget(Field("Project setting: where the switch starts when the project opens", self.policy))
        self.cloud_route = SegmentedControl(
            tuple((profile_key(r), r.service) for r in routes.on_side(False)) or ((CLAUDE_CODE, "—"),),
            current=ai_profile.cloud_conn(self.project))
        self.cloud_route.changed.connect(self._on_cloud_route)
        self.cloud_route_field = Field("Cloud means", self.cloud_route)
        self.cloud_route_field.setVisible(len(routes.on_side(False)) > 1)
        layout.addWidget(self.cloud_route_field)
        self.models = ModelsGrid(app)
        if hasattr(app, "model_choices_changed"):
            app.model_choices_changed.connect(self.models.refresh)
        layout.addWidget(Field("Model of each task", self.models))

        self.prompts = PromptsTab(app)
        self._add_section(PROMPTS_KEY, "Prompts", self.prompts)
        _building = self
        try:
            by_service: dict[str, list[QWidget]] = {}
            for route in routes.all():
                try:
                    builder = route.settings_section()
                except Exception as exc:
                    log.exception("settings section of %s failed", route.service)
                    by_service.setdefault(route.service, []).append(
                        caption(f"{route.service} could not build this section: {exc}", "error"))
                    continue
                if builder is not None:
                    by_service.setdefault(route.service, []).append(
                        _safe_build(route.service, route.service, builder))
            for service, widgets in by_service.items():
                holder = QWidget()
                inner = QVBoxLayout(holder)
                inner.setContentsMargins(0, 0, 0, 0)
                for widget in widgets:
                    inner.addWidget(widget)
                self._add_section(service, service, holder)
            for plugin_name, section in plugin_sections:
                self._add_section(section.title, section.title, _safe_build(plugin_name, section.title, section.build))
        finally:
            _building = None
        layout.addStretch(1)

    def _add_section(self, key: str, title: str, widget: QWidget) -> None:
        field = Field(title, widget)
        self.sections[key] = field
        self.body.addWidget(field)

    def _on_cloud_route(self, value: str) -> None:
        try:
            ai_profile.set_cloud_conn(self.project, value)
        except ValueError:
            return                       # a plugin's route: not one ai_profile can start on yet
        self.models.refresh()

    def set_installed(self, installed) -> None:
        self.models.refresh()
