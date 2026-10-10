"""Opening a project (UI_REDESIGN_PLAN.md, step 9): the project picker and the "Made with a newer
SlideMage" sheet.

OpenProjectSheet lists the projects opened last (project.recent_projects()) with a chip each, lets
the user open any folder, or create a new project (project.init_project). It is the first-run /
start screen when no project can be found (cli.py), and ⋮ -> "Open project…" in the window. Either
way it only *chooses* (`chosen`): the project is fixed for the life of a process, so the caller
starts SlideMage again on it.

This module must stay free of anything that imports deck_scan, which fixes the project folder at
import time: the picker runs before there is one. That is why the chip "needs a check" (a
pending change of compat.py) is the caller's to supply when it can.

NewerProjectSheet asks what to do with a project that a newer SlideMage made.
"""
from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QCheckBox, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QVBoxLayout, QWidget

from ... import project
from ...version import VERSION_NUMBER
from ..kit import kit_qss as q
from ..kit.widgets import Button, Field, ModalSheet, RowButton, Surface, caption, set_property

ICON_PATH = Path(__file__).resolve().parents[2] / "assets" / "icon.ico"
NEW_FOLDER_NAME = "my-slides"


class OpenProjectSheet(ModalSheet):
    def __init__(self, parent: Optional[QWidget] = None, *, current: Optional[Path] = None, first_run: bool = False,
                 needs_check: Optional[Callable[[Path], bool]] = None, app_version: str = VERSION_NUMBER) -> None:
        """`current` is the project that is open now (marked, and where a new one is suggested);
        `first_run` is the start screen: no Cancel, an introduction. `needs_check(path)` says
        whether compat.py has something pending for a project (a chip), for callers that may
        import it. After exec(), `chosen` is the folder of the project to open, or None."""
        super().__init__("Open a project", parent, width=620)
        self.chosen: Optional[Path] = None
        self._current = current.resolve() if current is not None else None
        self._app_version = app_version
        self._needs_check = needs_check
        self._base = current.parent if current is not None else (project.last_project_hint() or Path.home())
        body = Surface()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        if first_run:
            layout.addLayout(self._header())
            layout.addWidget(caption(
                "SlideMage works on a project: a folder with your decks, slides and media. Open one "
                "you have, or create a new one."))

        layout.addWidget(Field("Recent projects", self._recent_list()))
        self.form = self._new_project_form()
        self.form.hide()
        layout.addWidget(self.form)
        self.add_tab("", body)

        if current is not None:
            self.add_footer_note(caption("Opening another project restarts SlideMage."))
        if not first_run:
            self.add_button("Cancel", role="reject")
        self.new_button = self.add_button("New project…")
        self.new_button.clicked.connect(lambda: self._show_form(self._base / NEW_FOLDER_NAME))
        open_folder = self.add_button("Open folder…", kind="primary")
        open_folder.clicked.connect(self._on_open_folder)

    # -- building --------------------------------------------------------------------------

    def _header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(12)
        logo = QLabel()
        logo.setPixmap(QIcon(str(ICON_PATH)).pixmap(36, 36))
        row.addWidget(logo)
        title = QLabel("<b style='font-size:20px'>SlideMage</b>")
        row.addWidget(title)
        row.addWidget(caption(self._app_version.lstrip("v")))
        row.addStretch(1)
        return row

    def _chip(self, status: project.ProjectStatus) -> tuple[str, str]:
        """(text, tone) of the chip of a project; no text, no chip."""
        made_with = f"made with {status.last_version.lstrip('v')}" if status.last_version else ""
        if not status.exists:
            return "not found", "error"
        if status.path == self._current:
            return "open now", "ok"
        if status.newer:
            return " · ".join(filter(None, (made_with, "newer"))), "error"
        if self._needs_check is not None and self._needs_check(status.path):
            return " · ".join(filter(None, (made_with, "check"))), "warning"
        return made_with, "neutral"

    def _recent_list(self) -> QWidget:
        box = Surface()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.rows: list[RowButton] = []
        for path in project.recent_projects():
            status = project.project_status(path, self._app_version)
            row = RowButton("folder", status.name, str(status.path), mono_sub=True, chip=self._chip(status))
            row.setEnabled(status.exists)
            row.status = status
            row.clicked.connect(lambda path=status.path: self.choose(path))
            self.rows.append(row)
            layout.addWidget(row)
        if not self.rows:
            layout.addWidget(caption("No projects yet. Open a folder that holds a project, or create a new one."))
        return box

    def _new_project_form(self) -> QWidget:
        form = QFrame()
        form.setObjectName(q.LIST_BOX)
        layout = QVBoxLayout(form)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)
        title = QLabel("New project")
        title.setObjectName(q.ROW_NAME)
        layout.addWidget(title)
        folder = Surface()
        row = QHBoxLayout(folder)
        row.setContentsMargins(0, 0, 0, 0)
        self.folder_edit = QLineEdit()
        self.folder_edit.textChanged.connect(lambda _text: self._set_status(""))
        browse = Button("Browse…", "secondary")
        browse.clicked.connect(self._on_browse)
        row.addWidget(self.folder_edit, 1)
        row.addWidget(browse)
        layout.addWidget(Field("Folder (created if it does not exist)", folder))
        self.with_manual = QCheckBox("Add the manual and sample slides")
        self.with_manual.setChecked(project.has_example_template())
        self.with_manual.setEnabled(project.has_example_template())
        layout.addWidget(self.with_manual)
        layout.addWidget(caption(
            "Creates decks/, slides/ and media/, and a copy of the SlideMage framework in latex/. "
            "The manual is a finished deck to look at and copy slides from; you can delete it later."
            if project.has_example_template() else
            "Creates decks/, slides/ and media/. This copy of SlideMage carries no manual to add."))
        self.status = caption("")
        self.status.hide()
        layout.addWidget(self.status)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = Button("Cancel", "secondary")
        cancel.clicked.connect(form.hide)
        self.create_button = Button("Create project", "primary")
        self.create_button.clicked.connect(self._on_create)
        buttons.addWidget(cancel)
        buttons.addWidget(self.create_button)
        layout.addLayout(buttons)
        return form

    # -- choosing ---------------------------------------------------------------------------

    def choose(self, path: Path) -> None:
        self.chosen = path.resolve()
        self.accept()

    def _show_form(self, folder: Path, note: str = "") -> None:
        self.folder_edit.setText(str(folder))
        self._set_status(note, error=False)
        self.form.show()
        self.folder_edit.setFocus()

    def _set_status(self, text: str, *, error: bool = True) -> None:
        self.status.setText(text)
        set_property(self.status, "tone", "error" if error else "")
        self.status.setVisible(bool(text))

    def _on_open_folder(self) -> None:
        chosen = QFileDialog.getExistingDirectory(
            self, f"Open a SlideMage project (a folder containing {project.MARKER})", str(self._base))
        if not chosen:
            return
        path = Path(chosen)
        if project.is_project(path):
            self.choose(path)
        else:
            self._show_form(path, f"{path.name} is not a project yet (it has no {project.MARKER}). "
                                  "Create one in this folder?")

    def _on_browse(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "Folder for the new project", self.folder_edit.text() or str(self._base))
        if chosen:
            self.folder_edit.setText(chosen)

    def _on_create(self) -> None:
        text = self.folder_edit.text().strip()
        if not text:
            self._set_status("Give the folder of the new project.")
            return
        path = Path(text).expanduser()
        try:
            project.init_project(path, copy_example=self.with_manual.isChecked())
        except (project.ProjectCreationError, OSError) as exc:
            self._set_status(str(exc))
            return
        self.choose(path)


class NewerProjectSheet(ModalSheet):
    """"Made with a newer SlideMage". `choice` after exec(): "open" (Open anyway), "cancel", or for
    a project that is open already ("opening=False"): "not-now", "never" (Don't ask again) or
    "update" (Check for updates, only when `on_update` is given: it needs a window)."""

    OPEN, CANCEL, NOT_NOW, NEVER, UPDATE = "open", "cancel", "not-now", "never", "update"

    def __init__(self, parent: Optional[QWidget], name: str, last_version: str, app_version: str, *,
                 opening: bool, on_update: Optional[Callable[[], None]] = None) -> None:
        super().__init__("Made with a newer SlideMage", parent, width=520)
        self.choice = self.CANCEL if opening else self.NOT_NOW
        last, current = last_version.lstrip("v") or "a newer version", app_version.lstrip("v")
        name = escape(name)
        body = Surface()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        if opening:
            text = (f"<b>{name}</b> was last saved by SlideMage {last}. This is {current}. Opening it "
                    "here can write files in the older format and break things the newer version "
                    "relies on.")
            advice = "Update SlideMage first. If you open it anyway, nothing changes until you edit something."
        else:
            text = f"<b>{name}</b> was last used with SlideMage {last}, which is newer than this one ({current})."
            advice = "Features of the newer version may not work here."
        label = QLabel(text)
        label.setTextFormat(Qt.TextFormat.RichText)
        label.setWordWrap(True)
        layout.addWidget(label)
        layout.addWidget(caption(advice))
        self.add_tab("", body)
        if opening:
            self.add_button("Cancel", role="reject")
            self.add_button("Open anyway", kind="primary").clicked.connect(lambda: self._finish(self.OPEN))
        else:
            self.add_button("Don't ask again", kind="ghost").clicked.connect(lambda: self._finish(self.NEVER))
            self.add_button("Not now", role="reject")
            if on_update is not None:
                update = self.add_button("Check for updates", kind="primary")
                update.clicked.connect(lambda: (self._finish(self.UPDATE), on_update()))

    def _finish(self, choice: str) -> None:
        self.choice = choice
        self.accept()
