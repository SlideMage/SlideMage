"""Phase 4 of the PySide6 migration (see PYSIDE6_MIGRATION.md): the deck
table -- one DeckRow per deck (checkboxes/status dots/Archive/Edit/
Duplicate buttons), gridded into a scrollable DeckTable widget. Ports
gui.py's DeckRow/_build_table/_job_column_key/_build_progress_texts
verbatim in spirit -- same columns, same status-dot lifecycle, same
job-building logic -- onto Qt widgets/layouts instead of ttk grid()/pack().

Quick-compile (a fast "does this deck still compile" check, ignoring the
row's own version/chapter checkboxes) was replaced 2026-08-16 by Edit and
Duplicate, direct instruction -- Create PDF already covers the same
need with the row's own checkboxes ticked, and Edit/Duplicate cover two
gaps that had no button of their own before (jumping straight to a deck's
.tex source, and copying a deck under a new name).

compiler.py's CompileJob/run_jobs/CancelToken and deck_scan.py's
Deck/scan_decks are reused unchanged (confirmed GUI-independent during
planning); only the widget layer and the log-callback plumbing are new.
"""
from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from . import app_settings
from .compiler import CompileJob
from .deck_scan import TAG_COURSE, TAG_RESEARCH, TAG_TEST, TAG_WORK, Deck
from .qt_theme import LINK_LABEL, ThemeManager

# The deck table's groups, top to bottom: (tag, heading, shown even while
# empty on the active table). The workdeck has no heading -- it is pinned
# at the top on its own. Research presentations is the one group reserved
# while still empty, for decks that don't exist yet.
GROUPS = [
    (TAG_WORK, None, False),
    (TAG_COURSE, "Course decks", False),
    (TAG_RESEARCH, "Research presentations", True),
    (TAG_TEST, "Test decks", False),
]

VERSIONS = ["instructor", "during-course", "after-course"]
VERSION_LABELS = {
    "instructor": "Instructor",
    "during-course": "During-course",
    "after-course": "After-course",
}


def job_column_key(job: CompileJob) -> str:
    """Which status indicator a job belongs to -- one of the three version
    keys, "chapter" for every per-chapter job (they all share the single
    "After-course, per chapter" checkbox's status dot), or "presenter" for
    a presenter-mode job (checked first: a presenter job's own chapter is
    always None and its own version is always "instructor"/None, so it
    would otherwise be indistinguishable from a plain instructor job and
    share -- wrongly -- that job's status dot instead of its own)."""
    if job.presenter:
        return "presenter"
    if job.chapter is not None:
        return "chapter"
    return job.version or "instructor"


def build_progress_texts(jobs: list[CompileJob]) -> dict[str, str]:
    """One human-readable "what job is this" line per job, keyed by
    jobname -- identical logic to gui.py's own _build_progress_texts."""
    deck_order: list[str] = []
    for job in jobs:
        if job.deck.name not in deck_order:
            deck_order.append(job.deck.name)
    deck_position = {name: i + 1 for i, name in enumerate(deck_order)}
    total_decks = len(deck_order)

    texts: dict[str, str] = {}
    for job in jobs:
        prefix = (
            f"Deck {deck_position[job.deck.name]}/{total_decks} | "
            if total_decks > 1
            else ""
        )
        if job.chapter is None:
            texts[job.jobname] = f"{prefix}Compiling {job.deck.name}"
        else:
            total_chapters = len(job.deck.chapters)
            texts[job.jobname] = (
                f"{prefix}Compiling {job.deck.name}: Chapter {job.chapter.order}/"
                f"{total_chapters}"
            )
    return texts


class DeckRow:
    """Owns one deck's row of checkboxes/status labels/buttons, gridded
    into a shared QGridLayout -- like gui.py's own DeckRow, this is a
    controller object, not itself a widget."""

    def __init__(
        self,
        grid: QGridLayout,
        row_index: int,
        deck: Deck,
        theme: ThemeManager,
        on_open: Optional[Callable[[Deck], None]] = None,
        on_archive: Optional[Callable[[Deck], None]] = None,
        on_edit: Optional[Callable[[Deck], None]] = None,
        on_duplicate: Optional[Callable[[Deck], None]] = None,
        on_export_pptx: Optional[Callable[[Deck], None]] = None,
        on_tags: Optional[Callable[[Deck], None]] = None,
        on_open_pdf: Optional[Callable[[Deck], None]] = None,
        on_course_link: Optional[Callable[[Deck], None]] = None,
    ):
        self.deck = deck
        self.theme = theme
        self.vars: dict[str, QCheckBox] = {}
        self.status_labels: dict[str, QLabel] = {}
        self._running_keys: set[str] = set()

        name_label = QLabel(deck.name)
        # A test deck has no slide list or source to open (2026-09-19,
        # direct instruction), so its name is plain text -- not the blue,
        # clickable link every other deck's name is.
        if not deck.is_test_deck:
            name_label.setObjectName(LINK_LABEL)
            name_label.setCursor(Qt.CursorShape.PointingHandCursor)
            if on_open is not None:
                name_label.mousePressEvent = lambda event, d=deck: on_open(d)  # noqa: E731
        grid.addWidget(name_label, row_index, 0)

        col = 1
        for version in VERSIONS:
            checkbox = QCheckBox()
            # Instructor is always selectable -- for a deck with no
            # \deckversionoverride at all, checking it just means "compile
            # with whatever's hardcoded in the file" (see
            # selected_versions() below). Only During-course/After-course
            # actually depend on \deckversionoverride existing.
            supported = version == "instructor" or deck.supports_version
            checkbox.setEnabled(supported)
            # A merely-disabled (grayed) checkbox still reads as "this is
            # an option, just currently off" -- hide it outright instead,
            # since a version this deck can't compile at all isn't really
            # an option to begin with.
            checkbox.setVisible(supported)
            self.vars[version] = checkbox
            status = QLabel("")
            status.setFixedWidth(18)
            self.status_labels[version] = status

            cell = QWidget()
            cell_layout = QHBoxLayout(cell)
            cell_layout.setContentsMargins(0, 0, 0, 0)
            cell_layout.addWidget(checkbox)
            cell_layout.addWidget(status)
            cell_layout.addStretch()
            grid.addWidget(cell, row_index, col)
            col += 1

        self.chapter_var = QCheckBox()
        self.chapter_var.setEnabled(deck.has_chapters)
        self.chapter_var.setVisible(deck.has_chapters)
        chapter_status = QLabel("")
        chapter_status.setFixedWidth(18)
        self.status_labels["chapter"] = chapter_status
        chapter_cell = QWidget()
        chapter_layout = QHBoxLayout(chapter_cell)
        chapter_layout.setContentsMargins(0, 0, 0, 0)
        chapter_layout.addWidget(self.chapter_var)
        chapter_layout.addWidget(chapter_status)
        chapter_layout.addStretch()
        grid.addWidget(chapter_cell, row_index, col)
        col += 1

        # Presenter: always available, independent of the three version
        # checkboxes and of "After-course, per chapter" -- same "own
        # checkbox, own status dot, own output file" shape as that one,
        # not gated on deck.supports_version the way During-course/
        # After-course are (a presenter compile always uses instructor
        # content, or the deck's own hardcoded content for a deck with no
        # \deckversionoverride at all -- see build_jobs() below -- so there
        # is no version this checkbox could ever be unavailable for).
        self.presenter_var = QCheckBox()
        presenter_status = QLabel("")
        presenter_status.setFixedWidth(18)
        self.status_labels["presenter"] = presenter_status
        presenter_cell = QWidget()
        presenter_layout = QHBoxLayout(presenter_cell)
        presenter_layout.setContentsMargins(0, 0, 0, 0)
        presenter_layout.addWidget(self.presenter_var)
        presenter_layout.addWidget(presenter_status)
        presenter_layout.addStretch()
        grid.addWidget(presenter_cell, row_index, col)
        col += 1

        # Button order: Open pdf, Course link, Source,
        # Duplicate, Tags, Export PPTX, Archive -- DeckTable.rebuild()'s
        # header list carries one blank cell per button in this same order.
        if on_open_pdf is not None:
            open_pdf_button = QPushButton("Open pdf")
            open_pdf_button.setToolTip(
                "Open the most recently created PDF of this deck (any version)."
            )
            open_pdf_button.clicked.connect(lambda: on_open_pdf(deck))
            grid.addWidget(open_pdf_button, row_index, col)
            col += 1

        if on_course_link is not None:
            course_button = QPushButton("Course link...")
            course_button.setToolTip("Set or open this deck's course page.")
            course_button.clicked.connect(lambda: on_course_link(deck))
            grid.addWidget(course_button, row_index, col)
            col += 1

        if on_edit is not None:
            edit_button = QPushButton("Source")
            edit_button.clicked.connect(lambda: on_edit(deck))
            grid.addWidget(edit_button, row_index, col)
            col += 1

        if on_duplicate is not None:
            duplicate_button = QPushButton("Duplicate")
            duplicate_button.clicked.connect(lambda: on_duplicate(deck))
            grid.addWidget(duplicate_button, row_index, col)
            col += 1

        if on_tags is not None:
            tags_button = QPushButton("Tags")
            tags_button.setToolTip(
                "Choose which group of the deck table this deck appears in "
                "(course, research, test, workdeck). Stored in the deck's "
                "own file as \\decktags{...}."
            )
            tags_button.clicked.connect(lambda: on_tags(deck))
            grid.addWidget(tags_button, row_index, col)
            col += 1

        if on_export_pptx is not None:
            export_pptx_button = QPushButton("Export PPTX")
            export_pptx_button.setToolTip(
                "Compile this deck (instructor version) and export it as a "
                ".pptx with one full-page image per PDF page -- lets "
                "PowerPoint's own recording tools be used with it."
            )
            export_pptx_button.clicked.connect(lambda: on_export_pptx(deck))
            grid.addWidget(export_pptx_button, row_index, col)
            col += 1

        if on_archive is not None:
            archive_button = QPushButton("Archive")
            archive_button.clicked.connect(lambda: on_archive(deck))
            grid.addWidget(archive_button, row_index, col)
            col += 1

    def clear_selection(self) -> None:
        """Unchecks every compile-option checkbox this row owns -- the
        three version checkboxes, "After-course, per chapter", and
        Presenter -- regardless of which are currently enabled/visible for
        this particular deck. Used by the table's own "Clear selection"
        button to reset every row in one click."""
        for checkbox in self.vars.values():
            checkbox.setChecked(False)
        self.chapter_var.setChecked(False)
        self.presenter_var.setChecked(False)

    def selected_versions(self) -> list[Optional[str]]:
        if not self.deck.supports_version:
            return [None] if self.vars["instructor"].isChecked() else []
        return [v for v in VERSIONS if self.vars[v].isChecked()]

    def build_jobs(self) -> list[CompileJob]:
        jobs: list[CompileJob] = [
            CompileJob(self.deck, version, None) for version in self.selected_versions()
        ]
        if self.chapter_var.isChecked() and self.deck.has_chapters:
            chapter_version = "after-course" if self.deck.supports_version else None
            for chapter in self.deck.chapters:
                jobs.append(CompileJob(self.deck, chapter_version, chapter))
        if self.presenter_var.isChecked():
            # Same "instructor, or whatever's hardcoded" choice
            # selected_versions() makes for the plain Instructor checkbox --
            # presenter mode always wants the fullest content (all \pause
            # reveals, every \note{}), never a restricted student version.
            presenter_version = "instructor" if self.deck.supports_version else None
            jobs.append(CompileJob(self.deck, presenter_version, None, presenter=True))
        return jobs

    def reset_status(self) -> None:
        self._running_keys.clear()
        for label in self.status_labels.values():
            label.setText("")
            label.setStyleSheet("")

    def set_status(self, key: str, status: str) -> None:
        """Same lifecycle as gui.py's own DeckRow.set_status: running
        (animated dots) / moving (static arrow) / pass (check) / fail
        (cross, sticky until the next reset_status())."""
        label = self.status_labels.get(key)
        if label is None:
            return
        if status == "fail":
            self._running_keys.discard(key)
            label.setText("✗")
            label.setStyleSheet(f"color: {self.theme.status_color('fail')}")
            return
        if label.text() == "✗":
            return  # sticky fail
        if status == "running":
            self._running_keys.add(key)
            label.setText(".")
            label.setStyleSheet(f"color: {self.theme.status_color('running')}")
        elif status == "moving":
            self._running_keys.discard(key)
            label.setText("→")
            label.setStyleSheet(f"color: {self.theme.status_color('moving')}")
        elif status == "pass":
            self._running_keys.discard(key)
            label.setText("✓")
            label.setStyleSheet(f"color: {self.theme.status_color('pass')}")

    def tick_spinner(self, frame: int) -> None:
        if not self._running_keys:
            return
        dots = "." * (frame % 3 + 1)
        for key in self._running_keys:
            self.status_labels[key].setText(dots)


class DeckTable(QWidget):
    """One tab's worth of deck rows -- the "Active decks"/"Archived decks"
    page content. Wrapped in a QScrollArea for horizontal overflow (a
    row's own content can exceed the window width), matching
    gui.py's own ScrollableFrame(horizontal=True, vertical=False) usage
    here."""

    def __init__(
        self,
        theme: ThemeManager,
        archivable: bool,
        on_open: Callable[[Deck], None],
        on_archive: Optional[Callable[[Deck], None]],
        on_edit: Optional[Callable[[Deck], None]],
        on_duplicate: Optional[Callable[[Deck], None]],
        on_export_pptx: Optional[Callable[[Deck], None]],
        on_compile_selected: Callable[[list[DeckRow]], None],
        on_stop_compilation: Callable[[], None],
        on_create_transcript: Callable[[list[DeckRow]], None],
        on_refresh: Callable[[], None],
        on_tags: Optional[Callable[[Deck], None]] = None,
        on_open_pdf: Optional[Callable[[Deck], None]] = None,
        on_course_link: Optional[Callable[[Deck], None]] = None,
    ) -> None:
        super().__init__()
        self.theme = theme
        self.archivable = archivable
        self.on_tags = on_tags
        self.on_open_pdf = on_open_pdf
        self.on_course_link = on_course_link
        # Which groups the user has collapsed, by group tag -- persisted
        # per table (app_settings.py) and kept across rebuild(), which
        # re-applies it without touching any row's checkboxes.
        self._collapsed_key = (
            f"collapsed_deck_groups_{'active' if archivable else 'archived'}")
        self._collapsed: set[str] = set(app_settings.get(self._collapsed_key, []))
        self._group_widgets: dict[str, list[QWidget]] = {}
        self._group_headers: dict[str, tuple[QPushButton, str, int]] = {}
        self.on_open = on_open
        self.on_archive = on_archive
        self.on_edit = on_edit
        self.on_duplicate = on_duplicate
        self.on_export_pptx = on_export_pptx
        self.on_compile_selected = on_compile_selected
        self.on_stop_compilation = on_stop_compilation
        self.on_create_transcript = on_create_transcript
        self.on_refresh = on_refresh

        self.rows: list[DeckRow] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer.addWidget(scroll)

        self.content = QWidget()
        self.content.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Minimum)
        scroll.setWidget(self.content)
        self.content_layout = QVBoxLayout(self.content)

        self.grid_container = QWidget()
        self.grid = QGridLayout(self.grid_container)
        self.content_layout.addWidget(self.grid_container)

        # This used to be a permanently-visible wrapped QLabel between the
        # deck grid and the button row -- taking up real vertical space on
        # every visit even though it's read once and rarely again. Moved
        # behind a "?" button (2026-09-16, direct instruction) next to
        # Stop creation: still one hover away (tooltip) or one click
        # away (QMessageBox, for anyone who doesn't hover), but out of the
        # way otherwise.
        help_text = (
            "Instructor/During-course/After-course each compile the whole deck "
            "as one PDF -- independent of \"After-course, per chapter\", which "
            "always compiles the after-course version split into one PDF per "
            "chapter (both can be checked together in the same run). "
            "Instructor-only decks have no \\deckversion override, so only "
            "\"Instructor\" is selectable there. \"After-course, per chapter\" "
            "is disabled for decks with no \\section{} chapters. \"Presenter\" "
            "compiles a separate <deck>-presenter.pdf with beamer's own "
            "dual-screen notes mode (\\note{} content on a facing page, for "
            "presenter software like pympress) -- always instructor-version "
            "content, independent of every other checkbox here."
        )

        # Create PDF/Stop creation exist on *both* tables --
        # archived decks are still compilable (an archived deck can still
        # have its own Instructor-only checkbox ticked), they just have no
        # Archive/Quick-compile buttons of their own. Only "Refresh decks"'s
        # alignment differs by table below.
        button_row = QHBoxLayout()
        self.compile_button = QPushButton("Create PDF")
        self._style_compile_button(active=True)
        self.compile_button.clicked.connect(lambda: self.on_compile_selected(self.rows))
        button_row.addWidget(self.compile_button)

        self.stop_button = QPushButton("Stop creation")
        self._style_stop_button(enabled=False)
        # Hidden rather than just disabled while no compile is running
        # (2026-09-17, direct instruction) -- a permanently-visible but
        # greyed-out Stop button sat in the row taking up space for a
        # command that's essentially never relevant outside an active
        # compile; set_compiling() below is the only other place this
        # gets toggled.
        self.stop_button.setVisible(False)
        self.stop_button.clicked.connect(self.on_stop_compilation)
        button_row.addWidget(self.stop_button)

        self.create_transcript_button = QPushButton("Create Transcript")
        self.create_transcript_button.setStyleSheet(
            "background-color: #0066cc; color: white; font-weight: bold; padding: 4px 12px;"
        )
        # Hidden rather than styled-down while a PDF compile is running
        # (2026-09-17, direct instruction, superseding an earlier muted-
        # but-still-clickable look) -- same setVisible() treatment as
        # Stop creation above, toggled from the same set_compiling() call.
        self.create_transcript_button.clicked.connect(
            lambda: self.on_create_transcript(self.rows)
        )
        button_row.addWidget(self.create_transcript_button)

        self.help_button = QPushButton("?")
        self.help_button.setFixedWidth(28)
        self.help_button.setToolTip(help_text)
        self.help_button.clicked.connect(
            lambda: QMessageBox.information(self, "Compile options", help_text)
        )
        button_row.addWidget(self.help_button)

        button_row.addStretch()
        clear_selection_button = QPushButton("Clear selection")
        clear_selection_button.setToolTip(
            "Unchecks every version/chapter/Presenter checkbox in this "
            "table, in one click."
        )
        clear_selection_button.clicked.connect(self._on_clear_selection)
        button_row.addWidget(clear_selection_button)

        refresh_button = QPushButton("Refresh decks")
        refresh_button.clicked.connect(self.on_refresh)
        button_row.addWidget(refresh_button)
        self.content_layout.addLayout(button_row)
        self.content_layout.addStretch()

    def _on_clear_selection(self) -> None:
        for row in self.rows:
            row.clear_selection()

    def _style_stop_button(self, enabled: bool) -> None:
        if enabled:
            self.stop_button.setEnabled(True)
            self.stop_button.setStyleSheet(
                "background-color: #cc3300; color: white; font-weight: bold; padding: 4px 12px;"
            )
        else:
            self.stop_button.setEnabled(False)
            self.stop_button.setStyleSheet(
                "background-color: #d9d9d9; color: #888888; font-weight: bold; padding: 4px 12px;"
            )

    def _style_compile_button(self, active: bool) -> None:
        """Create PDF's own look while a compile is already running
        (2026-09-17, direct instruction) -- same muted slate-blue/
        non-bold-gray-text scheme Create Transcript wore for its own
        short-lived "grayed out, still visible" state earlier today
        (superseded there by setVisible() once Stop creation existed to
        occupy that same "something's running" signal -- there is no
        equivalent swap-in for Create PDF itself, since it's the button
        that started the run, so it stays visible and disabled instead)."""
        if active:
            self.compile_button.setEnabled(True)
            self.compile_button.setStyleSheet(
                "background-color: #0066cc; color: white; font-weight: bold; padding: 4px 12px;"
            )
        else:
            self.compile_button.setEnabled(False)
            self.compile_button.setStyleSheet(
                "background-color: #3d668c; color: #999999; font-weight: normal; padding: 4px 12px;"
            )

    def set_compiling(self, compiling: bool) -> None:
        self._style_compile_button(active=not compiling)
        self.stop_button.setVisible(compiling)
        self._style_stop_button(enabled=compiling)
        # Create Transcript hidden for the same reason Stop creation is
        # shown -- while a PDF compile is running, Create PDF's own row of
        # per-version checkboxes is what's actually in use; hiding this
        # rather than styling it down (tried first, replaced same day per
        # direct instruction) keeps the row from offering an action that's
        # just visual noise until the compile finishes, same as Stop
        # creation's own reasoning above.
        self.create_transcript_button.setVisible(not compiling)

    def disable_stop_button(self) -> None:
        """Called right after Stop is clicked, before the batch itself has
        actually wound down (self.compiling stays True until it does) --
        just prevents a second click while the kill/skip is in flight.
        Separate from set_compiling(), which would also re-enable Compile
        prematurely."""
        self._style_stop_button(enabled=False)

    @staticmethod
    def _header_text(heading: str, count: int, collapsed: bool) -> str:
        return f"{'▸' if collapsed else '▾'}  {heading}  ({count})"

    def _group_header(self, tag: str, heading: str, count: int) -> QWidget:
        """A bold, clickable heading (click to collapse/expand the group)
        with a thin line under it. The line is its own 1px widget: a
        border-bottom set on a QLabel was checked and does not render under
        this app's global stylesheet."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 10, 0, 0)
        layout.setSpacing(2)
        button = QPushButton(self._header_text(heading, count, tag in self._collapsed))
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setToolTip("Click to collapse or expand this group.")
        button.setStyleSheet(
            "QPushButton {font-weight: bold; text-align: left; border: none; "
            "background: transparent; padding: 0;}"
        )
        button.clicked.connect(lambda _checked=False, t=tag: self._toggle_group(t))
        layout.addWidget(button)
        line = QFrame()
        line.setFixedHeight(1)
        line.setStyleSheet("background-color: #888888;")
        layout.addWidget(line)
        self._group_headers[tag] = (button, heading, count)
        return widget

    def _toggle_group(self, tag: str) -> None:
        if tag in self._collapsed:
            self._collapsed.discard(tag)
        else:
            self._collapsed.add(tag)
        app_settings.set(self._collapsed_key, sorted(self._collapsed))
        self._apply_collapsed(tag)

    def _apply_collapsed(self, tag: str) -> None:
        """Shows or hides one group's rows by hiding their top-level grid
        widgets only -- never rebuilding, so no checkbox or status is lost.
        Each cell's own children keep their individual visibility (e.g. a
        version checkbox a deck can't use stays hidden) since only the cell
        itself is toggled."""
        collapsed = tag in self._collapsed
        for widget in self._group_widgets.get(tag, []):
            widget.setVisible(not collapsed)
        header = self._group_headers.get(tag)
        if header is not None:
            button, heading, count = header
            button.setText(self._header_text(heading, count, collapsed))

    def rebuild(self, decks: list[Deck]) -> None:
        # Qt layouts have no single "clear everything" call -- pull every
        # item out (and delete the widget it owned) before rebuilding, or
        # the old rows would just stack up underneath the new ones.
        while self.grid.count():
            item = self.grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        header = [
            "Deck", "Instructor", "During-course", "After-course",
            "After-course, per chapter", "Presenter",
        ]
        if self.archivable:
            header.append("")  # Open pdf
        if self.on_course_link is not None:
            header.append("")  # Course link
        if self.archivable:
            header.append("")  # Source
            header.append("")  # Duplicate
            header.append("")  # Tags
            header.append("")  # Export PPTX
            header.append("")  # Archive
        for col, text in enumerate(header):
            label = QLabel(text)
            label.setStyleSheet("font-weight: bold;")
            self.grid.addWidget(label, 0, col)

        # Groups (2026-09-19, direct instruction), decided by each deck's
        # own \decktags{...} (Deck.group), never by its filename. Each group
        # keeps the scan's own filename order. A group with no decks in
        # this table shows no separator, except Research presentations on
        # the active table: it is deliberately shown while still empty, as
        # a reserved place for decks that don't exist yet.
        self._group_widgets = {}
        self._group_headers = {}
        self.rows = []
        grid_row = 1
        for tag, heading, show_when_empty in GROUPS:
            group = [d for d in decks if d.group == tag]
            if not group and not (show_when_empty and self.archivable):
                continue
            if heading is not None:
                self.grid.addWidget(
                    self._group_header(tag, heading, len(group)), grid_row, 0, 1, len(header))
                grid_row += 1
            first_row = grid_row
            for deck in group:
                self.rows.append(
                    DeckRow(
                        self.grid, grid_row, deck, self.theme,
                        on_open=self.on_open,
                        on_archive=self.on_archive if self.archivable else None,
                        on_edit=self.on_edit if self.archivable else None,
                        on_duplicate=self.on_duplicate if self.archivable else None,
                        on_export_pptx=self.on_export_pptx if self.archivable else None,
                        on_tags=self.on_tags if self.archivable else None,
                        on_open_pdf=self.on_open_pdf if self.archivable else None,
                        on_course_link=self.on_course_link,
                    )
                )
                grid_row += 1
            widgets: list[QWidget] = []
            for r in range(first_row, grid_row):
                for c in range(len(header)):
                    item = self.grid.itemAtPosition(r, c)
                    if item is not None and item.widget() is not None:
                        widgets.append(item.widget())
            self._group_widgets[tag] = widgets
            if tag in self._collapsed:
                self._apply_collapsed(tag)
