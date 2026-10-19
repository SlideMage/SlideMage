# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The project compatibility sheet (UI_REDESIGN_PLAN.md, step 9; compat.py): what a newer
SlideMage changed that may affect this project, with the choices the user has.

Start-up (something breaking is pending): Update project / Show report / Not now / Don't ask
again. *Not now* leaves everything as it is, so the sheet comes back on the next open; *Don't ask
again* remembers it per change. ⋮ -> Project compatibility (review): the same list including the
quiet (appearance-only) changes, with Update project / Show report / Mark all as read / Close.
After either, `choice` says which button closed it.
"""
from __future__ import annotations

from html import escape
from typing import Callable, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLabel, QScrollArea, QVBoxLayout, QWidget

from ... import compat
from ..kit import kit_qss as q
from ..kit.widgets import ModalSheet, Surface

UPDATE = "update"
NOT_NOW = "not-now"
DONT_ASK = "dont-ask"
MARK_READ = "mark-read"
CLOSE = "close"
MAX_FINDINGS_SHOWN = 6
LIST_HEIGHT = 340


def _label(text: str, name: str = "", *, rich: bool = False) -> QLabel:
    """A wrapped label; `rich` text is HTML (escape what comes from files or the user)."""
    label = QLabel(text)
    label.setTextFormat(Qt.TextFormat.RichText if rich else Qt.TextFormat.PlainText)
    label.setObjectName(name)
    label.setWordWrap(True)
    return label


class CompatSheet(ModalSheet):
    def __init__(self, parent: Optional[QWidget], evaluation: compat.Evaluation, app_version: str,
                 project_name: str, *, review: bool = False,
                 on_report: Optional[Callable[[], None]] = None) -> None:
        super().__init__("Project compatibility", parent, width=680)
        self.choice = CLOSE if review else NOT_NOW
        body = Surface()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        if review:
            intro = ("Changes of this SlideMage that may affect the project. Those that only change "
                     "how slides look are listed here and need no action.")
        else:
            intro = (f"SlideMage {app_version.lstrip('v')} changed things that may affect "
                     f"<b>{escape(project_name)}</b>. Nothing has been changed yet.")
            if evaluation.quiet:
                intro += (f" {len(evaluation.quiet)} more change(s) only affect how slides look; they "
                          "are listed under ⋮ → Project compatibility.")
        layout.addWidget(_label(intro, rich=True))

        self.items = evaluation.everything if review else evaluation.loud
        if self.items:
            box = QFrame()
            box.setObjectName(q.SURFACE)
            rows = QVBoxLayout(box)
            rows.setContentsMargins(0, 0, 8, 0)
            rows.setSpacing(10)
            for item in self.items:
                rows.addWidget(self._card(item))
            scroll = QScrollArea()
            scroll.setObjectName(q.SURFACE)
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            scroll.setMaximumHeight(LIST_HEIGHT)
            scroll.setWidget(box)
            layout.addWidget(scroll)
        else:
            layout.addWidget(_label("Nothing to report: no change of this SlideMage affects the project."))
        self.add_tab("", body)

        self.add_footer_note(_label("Update project backs up what it changes first.", q.PANEL_CAPTION))
        if review:
            mark = self.add_button("Mark all as read", kind="ghost")
            mark.setToolTip("Stops listing these changes.")
            mark.setEnabled(bool(evaluation.everything))
            mark.clicked.connect(lambda: self._finish(MARK_READ))
            self.add_button("Close").clicked.connect(lambda: self._finish(CLOSE))
        else:
            dont = self.add_button("Don't ask again", kind="ghost")
            dont.setToolTip("Never ask about these changes again (they stay on the list under "
                            "⋮ → Project compatibility).")
            dont.clicked.connect(lambda: self._finish(DONT_ASK))
            not_now = self.add_button("Not now")
            not_now.setToolTip("Ask again the next time the project is opened.")
            not_now.setDefault(True)
            not_now.clicked.connect(lambda: self._finish(NOT_NOW))
        report = self.add_button("Show report")
        report.setToolTip("Writes .slidemage/compat-report.md (and .json) for you or an AI tool, and opens it.")
        report.setAutoDefault(False)
        report.clicked.connect(lambda: on_report() if on_report else None)
        update = self.add_button("Update project", kind="primary")
        update.setEnabled(evaluation.can_update)
        update.setAutoDefault(False)
        update.setToolTip("Runs the automatic fixes. Every file that changes is backed up first, "
                          "to .slidemage/backups/.")
        update.clicked.connect(lambda: self._finish(UPDATE))

    def _card(self, item: compat.Pending) -> QFrame:
        change = item.change
        card = QFrame()
        card.setObjectName(q.LIST_BOX)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(6)
        severity = compat.SEVERITY_LABELS.get(change.severity, change.severity)
        layout.addWidget(_label(f"<b>{escape(change.title)}</b> &nbsp; <small>{escape(severity)} · since "
                                f"{escape(change.since)}</small>", rich=True))
        layout.addWidget(_label(change.description))
        shown = item.findings[:MAX_FINDINGS_SHOWN]
        for finding in shown:
            where = f"{finding.file}:{finding.line}" if finding.line else finding.file
            layout.addWidget(_label(f"{where}: {finding.message}", q.PANEL_MONO))
        if len(item.findings) > len(shown):
            layout.addWidget(_label(f"… and {len(item.findings) - len(shown)} more (see the report).", q.PANEL_CAPTION))
        if change.fix:
            layout.addWidget(_label(f"<b>Fix by hand:</b> {escape(change.fix)}", rich=True))
        if change.severity in compat.LOUD:
            layout.addWidget(_label("Update project fixes this automatically." if change.migrate
                                    else "No automatic update: fix by hand or with the report.", q.PANEL_CAPTION))
        return card

    def _finish(self, choice: str) -> None:
        self.choice = choice
        self.accept()
