"""The project compatibility dialog (compat.py): what a newer SlideMage changed
that may affect this project, with the choices the user has.

Start-up (something breaking is pending): Update project / Show report /
Not now / Don't ask again. *Not now* leaves everything as it is, so the dialog
comes back on the next open; *Don't ask again* remembers it per change.
Info -> Project compatibility (review): the same list including the quiet
(appearance-only) changes, with Update project / Show report / Mark all as
read / Close.
"""
from __future__ import annotations

from html import escape

from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from . import compat

UPDATE = "update"
REPORT = "report"
NOT_NOW = "not-now"
DONT_ASK = "dont-ask"
MARK_READ = "mark-read"
CLOSE = "close"
MAX_FINDINGS_SHOWN = 6


def render_html(evaluation: compat.Evaluation, app_version: str, *, include_quiet: bool = True) -> str:
    items = evaluation.everything if include_quiet else evaluation.loud
    if not items:
        return "<p>Nothing to report: no change of this SlideMage affects the project.</p>"
    parts = []
    for item in items:
        c = item.change
        label = compat.SEVERITY_LABELS.get(c.severity, c.severity)
        parts.append(f"<h3>{escape(c.title)} <small>({escape(label)}, since {escape(c.since)})</small></h3>")
        parts.append(f"<p>{escape(c.description)}</p>")
        if c.fix:
            parts.append(f"<p><b>Fix by hand:</b> {escape(c.fix)}</p>")
        if c.severity in compat.LOUD:
            parts.append("<p><i>Update project fixes this automatically.</i></p>" if c.migrate
                         else "<p><i>No automatic update: fix by hand or with the report.</i></p>")
        if item.findings:
            shown = item.findings[:MAX_FINDINGS_SHOWN]
            rows = "".join(f"<li><code>{escape(f.file)}{':' + str(f.line) if f.line else ''}</code>: "
                           f"{escape(f.message)}</li>" for f in shown)
            more = len(item.findings) - len(shown)
            parts.append(f"<ul>{rows}</ul>" + (f"<p>… and {more} more (see the report).</p>" if more > 0 else ""))
    return "".join(parts)


class CompatDialog(QDialog):
    def __init__(self, parent: QWidget | None, evaluation: compat.Evaluation, app_version: str,
                 *, review: bool = False, on_report=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Project compatibility")
        self.choice = CLOSE if review else NOT_NOW
        self.resize(720, 520)
        layout = QVBoxLayout(self)

        if review:
            intro = ("Changes of this SlideMage that may affect the project. Those that only change "
                     "how slides look are listed here and need no action.")
        else:
            intro = (f"SlideMage {app_version} changed things that may affect this project. "
                     "Nothing has been changed yet.")
        if not review and evaluation.quiet:
            intro += (f" {len(evaluation.quiet)} more change(s) only affect how slides look; "
                      "they are listed under Info → Project compatibility.")
        label = QLabel(intro)
        label.setWordWrap(True)
        layout.addWidget(label)

        view = QTextBrowser()
        view.setHtml(render_html(evaluation, app_version, include_quiet=review))
        layout.addWidget(view, 1)

        buttons = QHBoxLayout()
        buttons.addStretch()
        update = QPushButton("Update project")
        update.setEnabled(evaluation.can_update)
        update.setToolTip("Runs the automatic fixes. Every file that changes is backed up first, "
                          "to .slidemage/backups/.")
        update.clicked.connect(lambda: self._finish(UPDATE))
        report = QPushButton("Show report")
        report.setToolTip("Writes .slidemage/compat-report.md (and .json) for you or an AI tool, and opens it.")
        report.clicked.connect(lambda: on_report() if on_report else None)
        buttons.addWidget(update)
        buttons.addWidget(report)
        if review:
            mark = QPushButton("Mark all as read")
            mark.setToolTip("Stops listing these changes.")
            mark.setEnabled(bool(evaluation.everything))
            mark.clicked.connect(lambda: self._finish(MARK_READ))
            close = QPushButton("Close")
            close.clicked.connect(lambda: self._finish(CLOSE))
            buttons.addWidget(mark)
            buttons.addWidget(close)
        else:
            not_now = QPushButton("Not now")
            not_now.setToolTip("Ask again the next time the project is opened.")
            not_now.setDefault(True)
            not_now.clicked.connect(lambda: self._finish(NOT_NOW))
            dont = QPushButton("Don't ask again")
            dont.setToolTip("Never ask about these changes again (they stay on the list under "
                            "Info -> Project compatibility).")
            dont.clicked.connect(lambda: self._finish(DONT_ASK))
            buttons.addWidget(not_now)
            buttons.addWidget(dont)
        layout.addLayout(buttons)

    def _finish(self, choice: str) -> None:
        self.choice = choice
        self.accept()
