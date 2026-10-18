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

from PySide6.QtWidgets import QComboBox, QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ...ai import ai_profile, resolver
from ...ai.ai_profile import API, CHAT, CLAUDE_CODE, CLOUD, IMAGE_DESCRIPTION, LOCAL, TASKS, TASK_LABELS
from ..dialogs.settings import AI
from ..kit import kit_qss as q
from ..kit.widgets import Popover, SegmentedControl, announce, apply_shadow, caption, set_property
from .ai_popups import link

WIDTH = 480
TASK_COLUMN = 130
HEADS = {LOCAL: "Local · Ollama", CLAUDE_CODE: "Cloud · Claude Code", API: "Cloud · API"}
TOAST_ROUTES = {LOCAL: "Local", CLAUDE_CODE: "Cloud · Claude Code", API: "Cloud · Anthropic API"}
CONNECTIONS = ((CLAUDE_CODE, "Claude Code"), (API, "Anthropic API"))
POLICIES = ((LOCAL, "Local"), (CLOUD, "Cloud"))
NOTE = ("Saved as your defaults. Each side keeps its own models; switching back to Local restores these Ollama "
        "models and the Ollama address of Settings. Pickers elsewhere (Images page, chat) start on these.")
NO_MODEL = "(none chosen)"


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
        for column, route_key in ((1, LOCAL), (2, CLAUDE_CODE)):
            self.heads[route_key] = QLabel(HEADS[route_key])
            self.heads[route_key].setObjectName(q.AI_SETUP_HEAD)
            grid.addWidget(self.heads[route_key], 0, column)
        self.cells: dict[tuple[str, str], QComboBox] = {}       # (column: LOCAL or "cloud", task)
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

        self.conn = SegmentedControl(CONNECTIONS, current=ai_profile.cloud_conn(self._project), roving=True)
        self.conn.setAccessibleName("Cloud connection")
        self.conn.changed.connect(self._on_conn)
        self.body.addLayout(self._setting("Cloud connection", "", self.conn))
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
        models = self._window.local_models
        if route == LOCAL:
            return models.vision if task == IMAGE_DESCRIPTION else models.tools if task == CHAT else models.models
        if route == CLAUDE_CODE:
            return ai_profile.claude_code_choices()
        return resolver.api_models(self._project)

    def refresh(self) -> None:
        """Show the saved defaults and the lists, and which side is in use."""
        project = self._project
        cloud = ai_profile.cloud_conn(project)
        in_use = ai_profile.active_route(project)
        self.heads[CLAUDE_CODE].setText(HEADS[cloud])
        for route_key in (LOCAL, CLAUDE_CODE):
            set_property(self.heads[route_key], "active", (in_use == LOCAL) == (route_key == LOCAL))
        self.conn.set_current(cloud)
        self.policy.set_current(ai_profile.policy(project))
        for task in TASKS:
            for side, route_key in ((LOCAL, LOCAL), (CLOUD, cloud)):
                combo = self.cells[(side, task)]
                set_property(combo, "active", (in_use == LOCAL) == (side == LOCAL))
                self._fill(combo, route_key, task)

    def _fill(self, combo: QComboBox, route: str, task: str) -> None:
        """The offered models of `route` for `task`, the saved default selected; a default that is not on offer
        stays listed as "(not available)" instead of being dropped, so an unreachable Ollama never changes it."""
        saved = ai_profile.model_choice(self._project, route, task)
        combo.blockSignals(True)
        combo.clear()
        if route == LOCAL:
            combo.addItem(NO_MODEL, "")
        elif route == CLAUDE_CODE and task == CHAT:
            combo.addItem("Claude Code default", "")
        for choice in self._offered(route, task):
            combo.addItem(ai_profile.choice_label(route, choice), choice)
        if saved and combo.findData(saved) == -1:
            combo.addItem(f"{ai_profile.choice_label(route, saved)} (not available)", saved)
        combo.setCurrentIndex(max(0, combo.findData(saved)))
        combo.blockSignals(False)
        fit_list_to_items(combo)
        self._cell_tooltip(combo, route, task)

    @staticmethod
    def _cell_tooltip(combo: QComboBox, route: str, task: str) -> None:
        text = combo.currentText()
        if route == CLAUDE_CODE and task == CHAT:
            text += "\nUsed for new sessions. Restart Claude Code to apply a changed default."
        combo.setToolTip(text)

    def _on_cell(self, side: str, task: str, index: int) -> None:
        route = LOCAL if side == LOCAL else ai_profile.cloud_conn(self._project)
        combo = self.cells[(side, task)]
        choice = combo.itemData(index) or ""
        self._cell_tooltip(combo, route, task)
        ai_profile.set_model_choice(self._project, route, task, choice)
        label = ai_profile.choice_label(route, choice) if choice else (
            "Claude Code default" if route == CLAUDE_CODE and task == CHAT else NO_MODEL)
        text = f"Default for {TOAST_ROUTES[route]} · {TASK_LABELS[task]}: {label}"
        if route == CLAUDE_CODE and task == CHAT:
            text += ". Restart Claude Code to apply it to the terminal."
        self._window.toast.show_message(text)
        announce(self, text)
        self._window.refresh_ai_models()

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
