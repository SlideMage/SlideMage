"""Phase 7 of the PySide6 migration (see PYSIDE6_MIGRATION.md): the modal
"Add slide" dialog -- ports add_slide_dialog.py's AddSlideDialog onto Qt
widgets. deck_editor.py/slide_ids.py are reused completely unchanged.
"""
from __future__ import annotations

import re
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QCompleter,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from . import deck_editor, slide_ids, slide_language, slide_rename
from .deck_scan import Deck
from .ui.kit.theme import MUTED_LABEL

SLUG_RE = re.compile(r"^[A-Za-z0-9]+(-[A-Za-z0-9]+)*$")
VERSIONS = deck_editor.DEFAULT_CONDITIONS
VERSION_LABELS = {
    "instructor": "Instructor",
    "during-course": "During-course",
    "after-course": "After-course",
}


class AddSlideDialog(QDialog):
    def __init__(
        self, app, deck: Deck, insert_at: int, indent: str,
    ) -> None:
        super().__init__(app)
        self.app = app
        self.deck = deck
        self.insert_at = insert_at
        self.indent = indent
        self._selected_id_slug: Optional[str] = None
        self._duplicate_source_id_slug: Optional[str] = None
        self._listbox_items: list[str] = []
        self._all_slides = slide_ids.list_id_slugs()

        self.setWindowTitle("Add slide")
        self.setModal(True)
        self._build()

    # -- widgets ----------------------------------------------------------------

    def _build(self) -> None:
        layout = QVBoxLayout(self)

        mode_row = QHBoxLayout()
        self.existing_radio = QRadioButton("Use existing slide")
        self.new_radio = QRadioButton("Create new slide")
        self.duplicate_radio = QRadioButton("Duplicate existing slide")
        self.existing_radio.setChecked(True)
        mode_group = QButtonGroup(self)
        mode_group.addButton(self.existing_radio)
        mode_group.addButton(self.new_radio)
        mode_group.addButton(self.duplicate_radio)
        # All three connected (not just one, unlike a plain 2-way toggle
        # elsewhere in this codebase) -- with three buttons, a transition
        # between the two that *aren't* wired up would otherwise never
        # fire this handler at all. _on_mode_change() re-reads each
        # radio's own .isChecked() fresh regardless of which one's toggled
        # signal actually triggered it, so firing on every button's own
        # transition (twice per switch, harmless) is safe.
        self.existing_radio.toggled.connect(self._on_mode_change)
        self.new_radio.toggled.connect(self._on_mode_change)
        self.duplicate_radio.toggled.connect(self._on_mode_change)
        mode_row.addWidget(self.existing_radio)
        mode_row.addWidget(self.new_radio)
        mode_row.addWidget(self.duplicate_radio)
        mode_row.addStretch(1)
        layout.addLayout(mode_row)

        self.mode_stack = QStackedWidget()
        layout.addWidget(self.mode_stack, stretch=1)

        existing_page = QWidget()
        existing_layout = QVBoxLayout(existing_page)
        existing_layout.setContentsMargins(0, 0, 0, 0)
        existing_layout.addWidget(QLabel("Search:"))
        self.search_entry = QLineEdit()
        self.search_entry.textChanged.connect(self._refresh_listbox)
        existing_layout.addWidget(self.search_entry)
        self.listbox = QListWidget()
        self.listbox.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.listbox.itemSelectionChanged.connect(self._on_existing_selected)
        existing_layout.addWidget(self.listbox, stretch=1)
        self.mode_stack.addWidget(existing_page)

        new_page = QWidget()
        new_layout = QVBoxLayout(new_page)
        new_layout.setContentsMargins(0, 0, 0, 0)
        new_layout.addWidget(QLabel("Slug (e.g. MM-Theorem):"))
        self.slug_entry = QLineEdit()
        new_layout.addWidget(self.slug_entry)

        # Language (2026-08-24): always encoded into the new file's own
        # id-slug (slide_ids.create_slide_file), never left implicit --
        # unlike the ~665 pre-existing slides, a brand-new slide has no
        # "legacy, implicitly English" grace period to piggyback on.
        # "Multilingual" (not "Bilingual"): a third language later only
        # needs a new radio + keyword here and in
        # Slidemaster_preamble_base.tex's \\setSlideLanguageFromSlug, not a
        # renaming pass through this UI.
        language_row = QHBoxLayout()
        language_row.addWidget(QLabel("Language:"))
        self.language_en_radio = QRadioButton("EN")
        self.language_de_radio = QRadioButton("DE")
        self.language_mult_radio = QRadioButton("Multilingual")
        self.language_en_radio.setChecked(True)
        language_group = QButtonGroup(self)
        for rb in (self.language_en_radio, self.language_de_radio, self.language_mult_radio):
            language_group.addButton(rb)
            language_row.addWidget(rb)
        language_row.addStretch(1)
        new_layout.addLayout(language_row)

        # "Base on existing slide" -- required part of this dialog per
        # direct instruction (not a deferred nice-to-have): seeds the new
        # file from an existing slide's own current.tex body (a
        # translation starting point) instead of the blank template, and
        # writes both cross-reference header comments automatically
        # (create_slide_file's own "Translation of:" on this new file,
        # slide_ids.add_translation_backreference on the source).
        self.base_on_checkbox = QCheckBox("Base on existing slide (translation starting point):")
        self.base_on_checkbox.toggled.connect(lambda checked: self.base_on_combo.setEnabled(checked))
        new_layout.addWidget(self.base_on_checkbox)
        self.base_on_combo = QComboBox()
        self.base_on_combo.setEditable(True)
        self.base_on_combo.addItems(slide_ids.list_id_slugs())
        self.base_on_combo.setEnabled(False)
        completer = self.base_on_combo.completer()
        if completer is not None:
            completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
            completer.setFilterMode(Qt.MatchFlag.MatchContains)
        new_layout.addWidget(self.base_on_combo)

        new_layout.addStretch(1)
        self.mode_stack.addWidget(new_page)

        # "Duplicate existing slide" (2026-08-31, direct instruction) --
        # just the source picker lives here; the actual duplication (same
        # language, or another language with an optional auto-translate
        # pass) is entirely DuplicateSlideDialog's own job, launched as a
        # nested modal from _on_add() below once a source is chosen. This
        # mirrors that dialog's own pre-existing entry point from a slide's
        # source-editor tab -- reused rather than re-implemented, so this
        # button and that one can never drift apart on what "duplicate"
        # means.
        duplicate_page = QWidget()
        duplicate_layout = QVBoxLayout(duplicate_page)
        duplicate_layout.setContentsMargins(0, 0, 0, 0)
        duplicate_layout.addWidget(QLabel("Slide to duplicate:"))
        self.duplicate_search_entry = QLineEdit()
        self.duplicate_search_entry.textChanged.connect(self._refresh_duplicate_listbox)
        duplicate_layout.addWidget(self.duplicate_search_entry)
        self.duplicate_listbox = QListWidget()
        self.duplicate_listbox.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.duplicate_listbox.itemSelectionChanged.connect(self._on_duplicate_source_selected)
        duplicate_layout.addWidget(self.duplicate_listbox, stretch=1)
        self.mode_stack.addWidget(duplicate_page)

        variant_row = QHBoxLayout()
        variant_row.addWidget(QLabel("Load as:"))
        self.variant_combo = QComboBox()
        self.variant_combo.currentTextChanged.connect(lambda _: self._sync_condition_state())
        variant_row.addWidget(self.variant_combo)
        self.no_versions_label = QLabel("")
        self.no_versions_label.setObjectName(MUTED_LABEL)
        variant_row.addWidget(self.no_versions_label)
        variant_row.addStretch(1)
        layout.addLayout(variant_row)

        self.condition_row = QHBoxLayout()
        self.condition_row.addWidget(QLabel("Included in:"))
        self.condition_checks: dict[str, QCheckBox] = {}
        for version in VERSIONS:
            cb = QCheckBox(VERSION_LABELS[version])
            cb.setChecked(True)
            cb.setToolTip("Uncheck a version to use \\conditionalslide.")
            cb.toggled.connect(self._on_condition_toggled)
            self.condition_row.addWidget(cb)
            self.condition_checks[version] = cb
        self.condition_row.addWidget(QLabel("steps:"))
        self.steps_entry = QLineEdit(deck_editor.DEFAULT_STEPS)
        self.steps_entry.setFixedWidth(70)
        self.steps_entry.setToolTip(
            "\\slidestep only: reveal steps typeset (beamer overlay list, e.g. 1,2 or 2- or 1-2,4).")
        self.condition_row.addWidget(self.steps_entry)
        self.condition_row.addStretch(1)
        layout.addLayout(self.condition_row)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        add_button = QPushButton("Add")
        add_button.clicked.connect(self._on_add)
        button_row.addWidget(cancel_button)
        button_row.addWidget(add_button)
        layout.addLayout(button_row)

        self._on_mode_change()

    # -- mode/list handling -----------------------------------------------------

    def _on_mode_change(self) -> None:
        if self.existing_radio.isChecked():
            self.mode_stack.setCurrentIndex(0)
            self._refresh_listbox()
            self._on_existing_selected()
            # So the user can start typing a search term immediately,
            # without an extra click -- both on first open (this mode is
            # the default) and when switching back to it from another one.
            self.search_entry.setFocus()
        elif self.duplicate_radio.isChecked():
            self.mode_stack.setCurrentIndex(2)
            self._refresh_duplicate_listbox()
            self._on_duplicate_source_selected()
            # A duplicate is always a brand-new id -- no frozen versions of
            # its own yet, same reasoning as "Create new slide" below.
            self._refresh_variant_options([])
            self.duplicate_search_entry.setFocus()
        else:
            self.mode_stack.setCurrentIndex(1)
            self._selected_id_slug = None
            self._refresh_variant_options([])
            self.slug_entry.setFocus()

    def _populate_listbox(self, listbox: QListWidget, query: str) -> list[str]:
        """Shared between the "Use existing" and "Duplicate" pages' own
        pickers -- same source list, same language badge, same UserRole
        convention (the real id-slug never round-trips through the
        displayed, badge-suffixed text)."""
        query = query.strip().lower()
        listbox.clear()
        items = [s for s in self._all_slides if query in s.lower()]
        for id_slug in items:
            badge = slide_language.badge_for(id_slug)
            display = f"{id_slug} {badge.text()}" if badge.text() else id_slug
            item = QListWidgetItem(display)
            item.setData(Qt.ItemDataRole.UserRole, id_slug)
            if badge.both:
                font = item.font()
                font.setBold(True)
                item.setFont(font)
            listbox.addItem(item)
        return items

    def _refresh_listbox(self) -> None:
        self._listbox_items = self._populate_listbox(self.listbox, self.search_entry.text())

    def _on_existing_selected(self) -> None:
        selected = self.listbox.selectedItems()
        if not selected:
            self._selected_id_slug = None
            self._refresh_variant_options([])
            return
        self._selected_id_slug = selected[0].data(Qt.ItemDataRole.UserRole)
        self._refresh_variant_options(deck_editor.available_versions(self._selected_id_slug))

    def _refresh_duplicate_listbox(self) -> None:
        self._populate_listbox(self.duplicate_listbox, self.duplicate_search_entry.text())

    def _on_duplicate_source_selected(self) -> None:
        selected = self.duplicate_listbox.selectedItems()
        self._duplicate_source_id_slug = (
            selected[0].data(Qt.ItemDataRole.UserRole) if selected else None
        )

    # -- variant handling ---------------------------------------------------------

    def _refresh_variant_options(self, versions: list[str]) -> None:
        options = [f"\\{m} (current)" for m in deck_editor.BASE_MACROS]
        for v in versions:
            options.append(f"\\slideversion (v{v})")
            options.append(f"\\omitslideversion (v{v})")
        self.variant_combo.clear()
        self.variant_combo.addItems(options)
        if options:
            self.variant_combo.setCurrentIndex(0)
        self.no_versions_label.setText(
            "" if (versions or self.new_radio.isChecked() or self.duplicate_radio.isChecked())
            else "(no frozen versions available)"
        )
        self._sync_condition_state()

    def _current_macro_version(self) -> tuple[str, Optional[str]]:
        label = self.variant_combo.currentText()
        if not label:
            return "slide", None
        macro = label.split(" ", 1)[0][1:]
        if "(v" in label:
            return macro, label.split("(v", 1)[1].rstrip(")")
        return macro, None

    def _on_condition_toggled(self, checked: bool) -> None:
        if checked or self._current_macro_version()[0] != "slide":
            return
        index = self.variant_combo.findText("\\conditionalslide (current)")
        if index >= 0:
            self.variant_combo.setCurrentIndex(index)

    def _sync_condition_state(self) -> None:
        macro, _ = self._current_macro_version()
        enabled = macro == "slide" or macro in deck_editor.CONDITIONAL_MACROS
        for cb in self.condition_checks.values():
            if macro == "slide":
                cb.setChecked(True)
            cb.setEnabled(enabled)
        self.steps_entry.setEnabled(macro == "slidestep")

    # -- submit -------------------------------------------------------------------

    def _on_add(self) -> None:
        macro, version = self._current_macro_version()
        conditions = None
        steps = None
        if macro in deck_editor.CONDITIONAL_MACROS:
            conditions = [v for v in VERSIONS if self.condition_checks[v].isChecked()]
            if not conditions:
                QMessageBox.critical(
                    self, "Add slide", f"Pick at least one deck version for \\{macro}."
                )
                return
        if macro == "slidestep":
            try:
                steps = deck_editor.normalize_steps(self.steps_entry.text())
            except ValueError as exc:
                QMessageBox.critical(self, "Add slide", str(exc))
                return

        if self.existing_radio.isChecked():
            if self._selected_id_slug is None:
                QMessageBox.critical(self, "Add slide", "Pick an existing slide from the list.")
                return
            id_slug = self._selected_id_slug
            is_new_slide = False
        elif self.duplicate_radio.isChecked():
            if self._duplicate_source_id_slug is None:
                QMessageBox.critical(self, "Add slide", "Pick a slide to duplicate.")
                return
            source_path = slide_ids.SLIDES_DIR / f"{self._duplicate_source_id_slug}-current.tex"
            # The dialog does the actual duplication (same language, or
            # another language with an optional auto-translate pass) --
            # same entry point as the Details view's own "Duplicate
            # slide" button, just launched from here as a nested modal
            # instead. A cancel there (dialog.new_id_slug left None) backs
            # out of this whole "Add" click too, rather than falling
            # through to insert nothing.
            # Imported here, not at module level -- qt_duplicate_slide_dialog.py
            # itself imports SLUG_RE from this module, so a top-level
            # import in both directions is a circular import; deferring
            # this one until it's actually needed (well after both modules
            # have finished loading) breaks the cycle without having to
            # relocate SLUG_RE to a third module just for this.
            from .qt_duplicate_slide_dialog import DuplicateSlideDialog

            dialog = DuplicateSlideDialog(self, self._duplicate_source_id_slug, source_path)
            if dialog.exec() != QDialog.DialogCode.Accepted or dialog.new_id_slug is None:
                return
            id_slug = dialog.new_id_slug
            # A duplicate is a brand-new slide file too (2026-09-26, direct
            # instruction) -- opened in its source editor just like "Create
            # new slide" below.
            is_new_slide = True
        else:
            slug = self.slug_entry.text().strip()
            if not SLUG_RE.match(slug):
                QMessageBox.critical(
                    self,
                    "Add slide",
                    "Slug must be non-empty and hyphen-separated alphanumeric "
                    "words, e.g. MM-Theorem.",
                )
                return
            if self.language_de_radio.isChecked():
                language = "DE"
            elif self.language_mult_radio.isChecked():
                language = "mult"
            else:
                language = "EN"

            base_on_path = None
            cross_ref_id_slug = None
            if self.base_on_checkbox.isChecked():
                cross_ref_id_slug = self.base_on_combo.currentText().strip()
                base_on_path = slide_ids.SLIDES_DIR / f"{cross_ref_id_slug}-current.tex"
                if not cross_ref_id_slug or not base_on_path.exists():
                    QMessageBox.critical(
                        self, "Add slide",
                        "Pick a valid existing slide to base this on.",
                    )
                    return

            new_id = slide_ids.mint_slide_id()
            slide_ids.append_slide_id(new_id)
            try:
                slide_ids.create_slide_file(
                    new_id, slug, language,
                    base_on=base_on_path, cross_ref_id_slug=cross_ref_id_slug,
                )
            except FileExistsError as exc:
                QMessageBox.critical(self, "Add slide", str(exc))
                return
            id_slug = f"{new_id}-{language}-{slug}"
            if cross_ref_id_slug is not None:
                slide_ids.add_translation_backreference(base_on_path, language, id_slug)
                slide_rename.regenerate_translation_links()
            is_new_slide = True

        previous_text = self.deck.text
        try:
            deck_editor.insert_slide_call(
                self.deck.path, self.deck.text, self.insert_at, self.indent,
                macro, id_slug, version, conditions, steps,
            )
        except (deck_editor.StaleFileError, ValueError) as exc:
            QMessageBox.critical(self, "Add slide failed", str(exc))
            return

        self.accept()
        self.app.after_deck_edit(
            self.deck.path, f"Added \\{macro}{{{id_slug}}} to {self.deck.name}",
            previous_text=previous_text,
        )
        # "Create new slide" and "Duplicate existing slide" (2026-09-26,
        # direct instruction, extending the 2026-09-22 one: "let SlideMage
        # open its source view immediately so I can start editing it") --
        # both produce a new file; "Use existing slide" only references
        # content that already has an author behind it, nothing new to
        # jump into.
        if is_new_slide:
            self.app.open_slide_editor(
                slide_ids.SLIDES_DIR / f"{id_slug}-current.tex")
