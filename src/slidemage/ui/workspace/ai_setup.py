# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""AI setup, the popover of the AI switch's ▾ (workspace v6 handoff, section 2): the default model of every task on
each side, what Cloud means, and the project's own setting.

Every model cell is saved as the user's default at once (ai_profile.set_model_choice) and every picker elsewhere
starts on it. The side that is not in use is greyed but editable. Changing the cloud connection while on Cloud
moves the route, so it goes through the same request as the switch (ai_route.py); the project setting only changes
where the switch starts when the project opens.

The keyboard goes through the cells in reading order (Task rows, Local then Cloud), then the two settings, then the
link; Tab stays inside, and Esc closes it and gives the focus back to the ▾.
"""
from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QGridLayout, QHBoxLayout, QLabel, QMessageBox, QVBoxLayout, QWidget

from ...ai import ai_profile, routes
from ...ai.ai_profile import CHAT, CLOUD, LOCAL, TASKS, TASK_LABELS
from ..dialogs.settings import AI
from ..kit import kit_qss as q
from ..kit.widgets import Popover, SegmentedControl, announce, apply_shadow, caption, set_property
from ..kit.widgets import clear_layout
from .ai_popups import link
from .ai_switch import connection_name

WIDTH = 480
TASK_COLUMN = 130
NO_ROUTE = "(no route installed)"
POLICIES = ((LOCAL, "Local"), (CLOUD, "Cloud"))
NOTE = ("Saved as your defaults. Each route keeps its own models. "
        "Pickers elsewhere (Images page, chat) start on these.")
NO_MODEL = "(none chosen)"
SWITCH, NEW_CONVERSATION = "switch", "new"      # what ask_session_model() answers, else None (Later)


def ask_session_model(parent, label: str, service: str = "Claude Code") -> str | None:
    """A running Claude Code session and a new default (`label`): SWITCH (restart it on the new default in the
    same conversation), NEW_CONVERSATION (restart it on the new default, starting afresh) or None (Later)."""
    box = QMessageBox(QMessageBox.Icon.Question, f"{service} is running",
                      f"{service} is running. Use {label} there now?", parent=parent)
    box.setInformativeText(
        "Switch now restarts the session and continues the same conversation; a reply that is still being "
        "written stops. New conversation starts afresh." + (
            " Text you have not sent comes back with the Up key, and Claude Code's own default model stays as it is."
            if service == "Claude Code" else ""))
    switch = box.addButton("Switch now", QMessageBox.ButtonRole.AcceptRole)
    fresh = box.addButton("New conversation", QMessageBox.ButtonRole.DestructiveRole)
    box.addButton("Later", QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(switch)
    box.exec()
    clicked = box.clickedButton()
    return SWITCH if clicked is switch else NEW_CONVERSATION if clicked is fresh else None


def fit_list_to_items(combo: QComboBox) -> None:
    """Make the open list of `combo` as wide as its longest entry, so full model names show there even
    when the closed box (a fixed share of a narrow popover) cuts them off."""
    view = combo.view()
    metrics = view.fontMetrics()
    longest = max((metrics.horizontalAdvance(combo.itemText(i)) for i in range(combo.count())), default=0)
    scrollbar = view.verticalScrollBar().sizeHint().width()
    view.setMinimumWidth(longest + scrollbar + 32)    # item padding and the frame


class AiSetup(Popover):
    def __init__(self, window, route) -> None:
        """`window` is the main window, `route` its AiRoute (a change of the cloud connection is a request)."""
        super().__init__(window, min_width=WIDTH, inline=True)
        self._window, self._route = window, route
        self._project = window.project
        self.setFixedWidth(WIDTH)
        self.setAccessibleName("AI for all tasks")
        self.body.setContentsMargins(16, 16, 16, 16)
        self.body.setSpacing(12)
        apply_shadow(self, "raised")

        title = QLabel("AI for all tasks")
        title.setObjectName(q.AI_POPUP_TITLE)
        self.body.addWidget(title)
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(6)
        grid.setColumnMinimumWidth(0, TASK_COLUMN)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 1)
        grid.setColumnStretch(0, 0)
        self.heads: dict[str, QLabel] = {}
        task_head = QLabel("Task")
        task_head.setObjectName(q.AI_SETUP_HEAD)
        grid.addWidget(task_head, 0, 0)
        for column, side in ((1, LOCAL), (2, CLOUD)):           # one column per side: the route it means
            self.heads[side] = QLabel()
            self.heads[side].setObjectName(q.AI_SETUP_HEAD)
            grid.addWidget(self.heads[side], 0, column)
        self.cells: dict[tuple[str, str], QComboBox] = {}       # (side: LOCAL or CLOUD, task)
        for row, task in enumerate(TASKS, start=1):
            grid.addWidget(QLabel(TASK_LABELS[task]), row, 0)
            for column, side in ((1, LOCAL), (2, CLOUD)):
                combo = QComboBox()
                combo.setObjectName(q.AI_SETUP_CELL)
                combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
                combo.setMinimumContentsLength(8)
                combo.setAccessibleName(f"{TASK_LABELS[task]} · {'Local' if side == LOCAL else 'Cloud'} model")
                combo.activated.connect(lambda i, s=side, t=task: self._on_cell(s, t, i))
                self.cells[(side, task)] = combo
                grid.addWidget(combo, row, column)
        self.body.addLayout(grid)
        self.body.addWidget(caption(NOTE))

        self._conn_ids: tuple[str, ...] = ()
        self._conn_row = QHBoxLayout()          # the cloud route chooser: one segment per route on the cloud side
        self.body.addLayout(self._conn_row)
        self.conn = None
        self.policy = SegmentedControl(POLICIES, current=ai_profile.policy(self._project), roving=True)
        self.policy.setAccessibleName("Project setting")
        self.policy.changed.connect(lambda value: ai_profile.set_policy(self._project, value))
        self.body.addLayout(self._setting("Project setting", "The switch starts here when the project opens",
                                          self.policy))
        footer = QHBoxLayout()
        footer.addStretch(1)
        footer.addWidget(link("Settings → AI…", self._open_settings))
        self.body.addLayout(footer)

        window.state.ai_route_changed.connect(lambda _route: self.refresh())
        window.local_models.changed.connect(self.refresh)

    @staticmethod
    def _setting(label: str, hint: str, control: QWidget) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(10)
        text = QVBoxLayout()
        text.setSpacing(0)
        text.addWidget(QLabel(label))
        if hint:
            text.addWidget(caption(hint))
        row.addLayout(text, 1)
        row.addWidget(control)
        return row

    # -- the cells -------------------------------------------------------------------------------

    def _prepare(self) -> None:
        self.refresh()
        self._window.local_models.refresh()

    def _offered(self, route: str, task: str) -> list[str]:
        found = routes.get(route)
        return found.model_choices(self._project, task) if found is not None else []

    def _build_conn(self, cloud: str) -> None:
        """The chooser of the cloud route, rebuilt when the routes on the cloud side are not the ones it shows; it
        is not shown for fewer than two."""
        ids = tuple(route.id for route in routes.on_side(False))
        if ids != self._conn_ids:
            self._conn_ids = ids
            while self._conn_row.count():
                item = self._conn_row.takeAt(0)
                if item.layout() is not None:
                    clear_layout(item.layout())
                elif item.widget() is not None:
                    item.widget().deleteLater()
            self.conn = None
            if len(ids) > 1:
                self.conn = SegmentedControl([(route.id, route.service) for route in routes.on_side(False)],
                                             current=cloud, roving=True)
                self.conn.setAccessibleName("Cloud connection")
                self.conn.changed.connect(self._on_conn)
                self._conn_row.addLayout(self._setting("Cloud connection", "", self.conn))
        if self.conn is not None:
            self.conn.set_current(cloud)

    def refresh(self) -> None:
        """Show the saved defaults and the lists, and which side is in use."""
        project = self._project
        cloud, local = ai_profile.cloud_conn(project), ai_profile.local_route(project)
        in_mode = ai_profile.mode(project)
        for side, route_key in ((LOCAL, local), (CLOUD, cloud)):
            found = routes.get(route_key)
            prefix = "Local" if side == LOCAL else "Cloud"
            self.heads[side].setText(f"{prefix} · {connection_name(route_key)}" if found is not None
                                     else f"{prefix} · {NO_ROUTE}")
            set_property(self.heads[side], "active", in_mode == side)
        self._build_conn(cloud)
        self.policy.set_current(ai_profile.policy(project))
        for task in TASKS:
            for side, route_key in ((LOCAL, local), (CLOUD, cloud)):
                combo = self.cells[(side, task)]
                set_property(combo, "active", in_mode == side)
                self._fill(combo, route_key, task)

    def _fill(self, combo: QComboBox, route: str, task: str) -> None:
        """The offered models of `route` for `task`, the saved default selected; a default that is not on offer
        stays listed as "(not available)" instead of being dropped, so an unreachable Ollama never changes it."""
        found = routes.get(route)
        combo.blockSignals(True)
        combo.clear()
        if found is None:                       # that side has no route: its column is off
            combo.addItem(NO_ROUTE, "")
            combo.setEnabled(False)
            combo.setToolTip("Install a plugin that adds an AI route (Settings → Plugins)")
            combo.blockSignals(False)
            return
        combo.setEnabled(True)
        saved = ai_profile.model_choice(self._project, route, task)
        if blank := self._blank(route, task):
            combo.addItem(blank, "")
        for choice in self._offered(route, task):
            combo.addItem(ai_profile.choice_label(route, choice), choice)
        if saved and combo.findData(saved) == -1:
            combo.addItem(f"{ai_profile.choice_label(route, saved)} (not available)", saved)
        combo.setCurrentIndex(max(0, combo.findData(saved)))
        combo.blockSignals(False)
        fit_list_to_items(combo)
        self._cell_tooltip(combo, route, task)

    @staticmethod
    def _blank(route: str, task: str) -> str:
        """The entry for "no choice" of `route` for `task`: Local routes have no default model, a cloud route that
        has none lets the service choose ("Claude Code default"); a route with a default has no such entry."""
        found = routes.get(route)
        if found is None or found.default_choice(task):
            return ""
        return NO_MODEL if found.is_local else f"{found.service} default"

    @staticmethod
    def _cell_tooltip(combo: QComboBox, route: str, task: str) -> None:
        text = combo.currentText()
        if task == CHAT and AiSetup._blank(route, task) and not routes.get(route).is_local:
            text += "\nUsed for new sessions; a running one is asked whether to switch or restart."
        combo.setToolTip(text)

    def _on_cell(self, side: str, task: str, index: int) -> None:
        route = ai_profile.local_route(self._project) if side == LOCAL else ai_profile.cloud_conn(self._project)
        if routes.get(route) is None:
            return
        combo = self.cells[(side, task)]
        choice = combo.itemData(index) or ""
        self._cell_tooltip(combo, route, task)
        ai_profile.set_model_choice(self._project, route, task, choice)
        label = ai_profile.choice_label(route, choice) if choice else (self._blank(route, task) or NO_MODEL)
        found = routes.get(route)
        text = f"Default for {'Local' if found.is_local else ai_profile.Route(route, task).name} · {TASK_LABELS[task]}: {label}"
        if task == CHAT and self._blank(route, task) and not found.is_local:
            text += self._apply_to_session(route, label, choice)
        self._window.toast.show_message(text)
        announce(self, text)
        self._window.refresh_ai_models()

    def _apply_to_session(self, route: str, label: str, choice: str) -> str:
        """The default Claude Code chat model changed while the terminal's Claude Code may be running: ask whether
        the running session moves to it in the same conversation (ClaudeCodeView.switch_session: a restart with
        --resume, model and effort alike) or in a new one. Returns the end of the toast."""
        view = self._window.assistant.surface_for(route)
        if view is None:
            return "."
        service = routes.get(route).service
        if not getattr(view, "session_live", True):
            return f". {service} starts on it."
        new, session = ai_profile.route_for(self._project, route, CHAT, choice), getattr(view, "session", None)
        if session is not None and (new.model, new.effort) == (session.model, session.effort):
            return "."
        answer = ask_session_model(self._window, label, service)
        if answer == SWITCH:
            view.restart(choice, True)
            return f". {service} switches to it and continues the conversation."
        if answer == NEW_CONVERSATION:
            view.restart(choice, False)
            return f". {service} restarted on it with a new conversation."
        return f". The running {service} keeps its model until it is restarted."

    # -- the settings under the grid ---------------------------------------------------------------

    def _on_conn(self, value: str) -> None:
        """What Cloud means. On Cloud this moves the route: the same request as the switch."""
        project = self._project
        if self._window.state.ai_mode == CLOUD:
            self._route.request(CLOUD, value)
        elif value != ai_profile.cloud_conn(project):
            ai_profile.set_cloud_conn(project, value)
        self.refresh()

    def _open_settings(self) -> None:
        self.close()
        self._window.open_settings(AI)
