# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The Deck settings sheet (UI_REDESIGN_PLAN.md, step 9): the deck-wide settings that live in the
deck's own file -- template, language, footer text, the PDF shown by "Open pdf", where the PDFs
go, the appendix TOC (deck_settings.py reads and writes them) -- and the tabs of the loaded plugins.

Save closes the sheet with `action == "save"`; `result_settings()` is then the edited, checked
settings (a bad value shows under the form instead). The caller writes them.

The Maintenance rows of General run a window command (`action == "command:<id>"`, see `COMMAND`): the
sheet is modal, so it closes first, asks about unsaved changes before, and the caller runs the command
through the command registry, which also says whether its button is enabled.
"""
from __future__ import annotations

import logging
from dataclasses import replace
from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QVBoxLayout, QWidget)

from ... import deck_settings, languages, project
from ...deck_editor import VIEWS
from ...deck_scan import OPEN_PDF_CHOICES, Deck
from ...deck_settings import DeckSettings
from ...plugins import session
from ...plugins.host import deck_snapshot
from ..plugin_ui import DIRTY_SHEET_MESSAGE, HOST_UI
from ..ai_models import add_route_badge
from ..kit.tokens import SPACE
from ..kit.widgets import Button, Field, ModalSheet, Page, Surface, action_row, caption, columns, set_property

GENERAL, OUTPUT = range(2)
SAVE, COMMAND = "save", "command:"
MAINTENANCE = (       # (command id, name, what it does, button)
    ("create_snapshot", "Deck snapshot", "A dated, self-contained copy of the deck that compiles as it does today.",
     "Create snapshot…"),
    ("rerender_deck_previews", "Previews", "Render every slide preview of this deck again.", "Rerender all"),
    ("update_deck_versions", "Slide versions", "Raise the version of every slide changed since its last version.",
     "Update changed…"),
)
log = logging.getLogger(__name__)
OUTPUT_LABELS = {
    None: "All outputs",
    "instructor": "Instructor",
    "presenter": "Presenter",
    "during-course": "During-course",
    "after-course": "After-course",
    "transcript": "Transcript",
}


class DeckSettingsSheet(ModalSheet):
    def __init__(self, parent, deck: Deck, templates: list[tuple[str, str]], *, tab: int | str = GENERAL) -> None:
        """Edits a copy of the deck's settings. `templates` is [(key, label)] of the templates the
        project can find; the deck's current one is added if it is not there. `tab` is the one to
        open on: its index, or the title of a tab (a plugin's; an unknown title opens General). The tabs of the
        loaded plugins follow SlideMage's own."""
        super().__init__(f"Deck settings — {deck.name}", parent, width=700)
        add_route_badge(self, parent)
        self.deck = deck
        self._project_root = project.find_upward(deck.path.parent) or deck.path.parent
        self.original = deck_settings.read_settings(deck.text)
        self.settings = self.original
        self.action = ""
        self.add_tab("General", self._build_general(templates))
        self.add_tab("PDF output", self._build_output())
        self.plugin_tabs: dict[int, tuple] = {}      # tab index -> (the plugin's DeckSettingsTab, its page)
        self.tab_titles = ["General", "PDF output"]
        for plugin in session.active():
            for plugin_tab in plugin.contributions.deck_settings_tabs:
                self._add_plugin_tab(plugin, plugin_tab)

        self.note = caption("")
        self.add_footer_note(self.note)
        self.add_button("Cancel", role="reject")
        self.save_button = self.add_button("Save", kind="primary")
        self.save_button.clicked.connect(self._on_save)
        self.plugin_button = self.add_button("", kind="primary")     # the footer action of the shown plugin tab
        self.plugin_button.clicked.connect(self._on_plugin_action)

        self._initial = self._values()
        self.template_combo.currentIndexChanged.connect(self._sync_mode_combo)
        for widget in (self.template_combo, self.language_combo, self.open_pdf_combo):
            widget.currentIndexChanged.connect(self._sync_footer)
        for widget in (self.footer_edit, *self.output_edits.values()):
            widget.textChanged.connect(self._sync_footer)
        self.mode_combo.currentIndexChanged.connect(self._sync_footer)
        self.appendix_check.toggled.connect(self._sync_footer)
        for view in self.view_combos:
            self.view_combos[view].currentIndexChanged.connect(self._sync_footer)
            self.view_mode[view].currentIndexChanged.connect(self._sync_footer)
        for check in self.footer_checks.values():
            check.toggled.connect(self._sync_footer)
        for _tab, page in self.plugin_tabs.values():
            if hasattr(page, "changed"):
                page.changed.connect(self._sync_footer)
        self.tab_changed.connect(lambda _index: self._sync_footer())
        HOST_UI.register_sheet(self)
        if isinstance(tab, str):
            tab = self.tab_titles.index(tab) if tab in self.tab_titles else GENERAL
        self.set_current_tab(tab)
        self._sync_footer()

    # -- building --------------------------------------------------------------------------

    def _add_plugin_tab(self, plugin, plugin_tab) -> None:
        """A plugin's tab; when its build() raises, the tab says so instead (the sheet still opens)."""
        try:
            page = plugin_tab.build(deck_snapshot(self.deck))
        except Exception as exc:
            log.exception("deck settings tab %r of %s failed", plugin_tab.title, plugin.id)
            page = Page()
            page.body.addWidget(caption(f"{plugin.manifest.name} could not build this tab: {exc}", "error"))
            page.body.addStretch(1)
            plugin_tab = replace(plugin_tab, footer_action=None)
        index = self.add_tab(plugin_tab.title, page, scroll=True)
        self.tab_titles.append(plugin_tab.title)
        self.plugin_tabs[index] = (plugin_tab, page)

    def refresh_from_deck(self, deck: Deck) -> None:
        """A plugin edited the deck's file (the sheet had no unsaved changes then): take the rescanned deck and read
        the form again from its text, so a later Save is checked against, and computed from, the file as it is."""
        self.deck = deck
        self.original = self.settings = deck_settings.read_settings(deck.text)
        settings = self.original
        self.template_combo.setCurrentIndex(max(self.template_combo.findData(settings.template), 0))
        self.language_combo.setCurrentIndex(max(self.language_combo.findData(settings.language), 0))
        self.footer_edit.setText(settings.footer_text)
        self.appendix_check.setChecked(settings.appendix_toc)
        self.open_pdf_combo.setCurrentIndex(max(0, self.open_pdf_combo.findData(settings.open_pdf)))
        for key, edit in self.output_edits.items():
            edit.setText(settings.output_folders.get(key, ""))
        for key, check in self.footer_checks.items():
            check.setChecked(key not in settings.footer_hide)
        self._fill_mode_combo(deck_settings.settings_mode(self._template_modes(), settings.mode))
        self._view_modes = {view: mode for view, (_key, mode) in settings.view_themes.items()}
        for view, combo in self.view_combos.items():
            chosen = settings.view_themes.get(view, ("", ""))[0]
            combo.setCurrentIndex(max(combo.findData(chosen), 0))
            self._fill_view_mode(view, self._view_modes.get(view, ""))
        self._initial = self._values()
        self._sync_footer()

    def _build_general(self, templates: list[tuple[str, str]]) -> Page:
        page = Page()
        layout = page.body
        layout.addWidget(caption("These settings are written into the deck's own file, so they stay with the deck."))
        settings = self.original

        self.template_combo = QComboBox()
        entries = list(templates)
        if settings.template and settings.template not in {key for key, _ in entries}:
            entries.append((settings.template, f"{settings.template} (not found in this project)"))
        for key, label in entries:
            self.template_combo.addItem(label, key)
        self.template_combo.setCurrentIndex(max(self.template_combo.findData(settings.template), 0))
        self.template_combo.setToolTip(
            "The institution template: colors, logo, title bar and footer. "
            "SlideMage_template_<name>.tex, loaded by the deck's \\input line.")
        self.language_combo = QComboBox()
        codes = list(languages.project_languages(project.ProjectContext.at(self._project_root)).lower)
        if settings.language not in codes:            # the deck's own, should it be another
            codes.append(settings.language)
        for code in codes:
            self.language_combo.addItem(languages.name(code), code)
        self.language_combo.setCurrentIndex(self.language_combo.findData(settings.language))
        self.language_combo.setToolTip(
            "The deck's language (\\decklanguage): hyphenation, automatic texts, "
            "the language of its transcript and of \\multilingualtext.")
        layout.addWidget(columns(Field("Template", self.template_combo), Field("Language", self.language_combo)))

        self.mode_combo = QComboBox()
        self.mode_combo.setToolTip(
            "The colour mode of this deck's slides and PDFs, for example a dark background. "
            "Available when the selected template declares more than one mode.")
        self._fill_mode_combo(deck_settings.settings_mode(self._template_modes(), settings.mode))
        layout.addWidget(Field("Colours", self.mode_combo))
        layout.addWidget(caption("A template declares its colour modes (light, dark, grey ...); a mode changes colours only."))
        self._build_view_themes(layout, entries)

        self.footer_edit = QLineEdit(settings.footer_text)
        self.footer_edit.setPlaceholderText("Shown at the left of the footer, e.g. course | name | term")
        self.footer_edit.setToolTip("The deck's \\FooterText.")
        layout.addWidget(Field("Footer text", self.footer_edit))

        self.footer_checks: dict[str, QCheckBox] = {}
        shown = QWidget()
        shown_row = QHBoxLayout(shown)
        shown_row.setContentsMargins(0, 0, 0, 0)
        for key, label, tip in (
                ("text", "Footer text (left)", "The deck's \\FooterText at the left of the footer."),
                ("id", "Slide id (right)", "\"slide id: abc | v1.0.0\" at the right of the footer."),
                ("deck", "Deck version (right)", "\"instructor deck\", \"student course deck\" ... at the right.")):
            check = QCheckBox(label)
            check.setToolTip(tip)
            check.setChecked(key not in settings.footer_hide)
            self.footer_checks[key] = check
            shown_row.addWidget(check)
        shown_row.addStretch(1)
        layout.addWidget(Field("Footer shows", shown))

        self.appendix_check = QCheckBox("Always add the slide-preview appendix (\\deckappendixtoc)")
        self.appendix_check.setChecked(settings.appendix_toc)
        layout.addWidget(self.appendix_check)

        commands = getattr(self.parent(), "commands", None)
        group = Surface()
        rows = QVBoxLayout(group)
        rows.setContentsMargins(0, 0, 0, 0)
        rows.setSpacing(SPACE.lg)
        self.maintenance_buttons: dict[str, Button] = {}
        for command_id, title, note, label in MAINTENANCE:
            button = Button(label, compact=True)
            button.setEnabled(commands is not None and commands[command_id].enabled(self.parent()))
            button.clicked.connect(lambda _checked=False, cid=command_id: self._on_command(cid))
            self.maintenance_buttons[command_id] = button
            rows.addWidget(action_row(title, note, button))
        layout.addWidget(Field("Maintenance", group))
        layout.addStretch(1)
        return page

    def _build_output(self) -> Page:
        page = Page()
        layout = page.body
        settings = self.original
        self.open_pdf_combo = QComboBox()
        for key in OPEN_PDF_CHOICES:
            self.open_pdf_combo.addItem(OUTPUT_LABELS[key], key)
        self.open_pdf_combo.setCurrentIndex(max(0, self.open_pdf_combo.findData(settings.open_pdf)))
        layout.addWidget(Field("Open pdf opens", self.open_pdf_combo))
        layout.addWidget(caption(
            "The PDF \"Open latest PDF\" opens -- unless a newer PDF of the deck comes from a later "
            "compile run; then it asks."))

        grid_box = Surface()
        grid = QGridLayout(grid_box)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setColumnStretch(1, 1)
        self.output_edits: dict[str | None, QLineEdit] = {}
        for index, key in enumerate(deck_settings.OUTPUT_KEYS):
            edit = QLineEdit(settings.output_folders.get(key, ""))
            edit.setCursorPosition(0)       # long paths show from their start
            edit.setPlaceholderText("(the project's pdf folder)" if key is None else "(as for all outputs)")
            browse = Button("Browse…", compact=True)
            browse.clicked.connect(lambda _checked=False, k=key: self._browse(k))
            grid.addWidget(QLabel(f"{OUTPUT_LABELS[key]}"), index, 0)
            grid.addWidget(edit, index, 1)
            grid.addWidget(browse, index, 2)
            self.output_edits[key] = edit
        layout.addWidget(Field("Where the PDFs go", grid_box))
        layout.addWidget(caption(
            "A folder, or a file name ending in .pdf. An output with no entry of its own goes where "
            "\"All outputs\" says."))
        layout.addStretch(1)
        return page

    # -- the form --------------------------------------------------------------------------

    def _values(self) -> tuple:
        return (self.template_combo.currentData(), self.language_combo.currentData(), self.footer_edit.text(),
                tuple(edit.text() for edit in self.output_edits.values()),
                self.appendix_check.isChecked(), self.open_pdf_combo.currentData(), self._footer_hide(),
                self._mode_settings(),
                tuple(sorted(self._view_theme_entries().items())))

    def dirty(self) -> bool:
        return self._values() != self._initial

    def _read(self) -> DeckSettings:
        return deck_settings.from_form(
            self.original,
            template=self.template_combo.currentData() or "",
            language=self.language_combo.currentData() or "en",
            footer_text=self.footer_edit.text(),
            output_folders={key: edit.text() for key, edit in self.output_edits.items()},
            appendix_toc=self.appendix_check.isChecked(),
            open_pdf=self.open_pdf_combo.currentData() or "instructor",
            footer_hide=self._footer_hide(),
            mode=self._mode_settings(),
            view_themes=self._view_theme_entries() if self.deck.supports_version else None)

    def _build_view_themes(self, layout, entries: list[tuple[str, str]]) -> None:
        """"Theme per view": a theme and colour mode for each view, so one deck is dark for projection and light for
        print. A view left at "Same as the deck" has no entry. Decks without views skip it."""
        self.view_combos: dict[str, QComboBox] = {}
        self.view_mode: dict[str, QComboBox] = {}
        self._view_modes = {view: mode for view, (_key, mode) in self.original.view_themes.items()}
        if not self.deck.supports_version:
            return
        grid_box = QWidget()
        grid = QGridLayout(grid_box)
        grid.setContentsMargins(0, 0, 0, 0)
        for row, view in enumerate(VIEWS):
            combo = QComboBox()
            combo.addItem("Same as the deck", "")
            known = {key for key, _ in entries}
            chosen = self.original.view_themes.get(view, ("", ""))[0]
            for key, label in entries + ([(chosen, f"{chosen} (not found in this project)")] if chosen and chosen not in known else []):
                combo.addItem(label, key)
            combo.setCurrentIndex(max(combo.findData(chosen), 0))
            mode = QComboBox()
            grid.addWidget(QLabel(view.replace("-", " ").capitalize()), row, 0)
            grid.addWidget(combo, row, 1)
            grid.addWidget(mode, row, 2)
            self.view_combos[view], self.view_mode[view] = combo, mode
            self._fill_view_mode(view, self._view_modes.get(view, ""))
            combo.currentIndexChanged.connect(lambda _i, v=view: self._fill_view_mode(v, self._view_mode_choice(v)))
        layout.addWidget(Field("Theme per view", grid_box))
        layout.addWidget(caption(
            "A view can use another theme than the deck's, for example a dark one for the instructor view and a light "
            "one for the handouts. Written as a comment line the app reads; compiling the deck outside SlideMage uses "
            "the deck's own template."))

    def _view_mode_choice(self, view: str) -> str:
        """The mode a view's drop-down shows now ("" for the theme's base mode)."""
        combo = self.view_mode[view]
        return (combo.currentData() or "") if combo.isEnabled() else self._view_modes.get(view, "")

    def _fill_view_mode(self, view: str, chosen: str) -> None:
        """The modes of the theme a view uses, the base mode first (data ""); a mode the theme does not declare stays
        listed, so saving does not drop it silently."""
        key = self.view_combos[view].currentData() or ""
        modes = deck_settings.template_modes(self._project_root, key) if key else []
        combo = self.view_mode[view]
        combo.blockSignals(True)
        combo.clear()
        for position, (mode_id, label) in enumerate(modes):
            combo.addItem(label, "" if position == 0 else mode_id)
        if chosen and combo.findData(chosen) < 0 and modes:
            combo.addItem(f"{chosen} (not in this theme)", chosen)
        combo.setCurrentIndex(max(combo.findData(chosen), 0))
        combo.setEnabled(len(modes) > 1)
        combo.blockSignals(False)

    def _view_theme_entries(self) -> dict[str, tuple[str, str]]:
        entries = {}
        for view, combo in getattr(self, "view_combos", {}).items():
            key = combo.currentData() or ""
            if not key:
                continue
            mode_combo = self.view_mode[view]
            entries[view] = (key, (mode_combo.currentData() or "") if mode_combo.isEnabled() else "")
        return entries

    def _template_modes(self) -> list[tuple[str, str]]:
        return deck_settings.template_modes(self._project_root, self.template_combo.currentData() or "")

    def _fill_mode_combo(self, chosen: str) -> None:
        """The modes of the deck's template, the base mode first. A mode the template does not declare stays listed (the
        deck says it), so saving does not drop it silently; with fewer than two modes the drop-down is off."""
        modes = self._template_modes()
        combo = self.mode_combo
        combo.blockSignals(True)
        combo.clear()
        for mode_id, label in modes:
            combo.addItem(label, mode_id)
        if chosen and combo.findData(chosen) < 0 and modes:
            combo.addItem(f"{chosen} (not in this template)", chosen)
        combo.setCurrentIndex(max(combo.findData(chosen), 0))
        combo.setEnabled(len(modes) > 1)
        combo.blockSignals(False)

    def _sync_mode_combo(self) -> None:
        """The template changed: its modes replace the list; the mode stays when the new template has it."""
        self._fill_mode_combo(self.mode_combo.currentData() or "")

    def _mode_settings(self) -> str:
        """The mode setting the drop-down stands for; "" when the template offers no choice."""
        if not self.mode_combo.isEnabled():
            return ""
        return deck_settings.mode_to_settings(self._template_modes(), self.mode_combo.currentData() or "")

    def _footer_hide(self) -> tuple[str, ...]:
        return tuple(key for key, check in self.footer_checks.items() if not check.isChecked())

    def result_settings(self) -> DeckSettings:
        return self.settings

    def _say(self, text: str, tone: str = "") -> None:
        self.note.setText(text)
        set_property(self.note, "tone", tone)

    def _sync_footer(self) -> None:
        dirty = self.dirty()
        plugin_tab, page = self.plugin_tabs.get(self.current_tab(), (None, None))
        action = plugin_tab.footer_action if plugin_tab is not None else None
        self.plugin_button.setVisible(action is not None)
        if action is not None:
            self.plugin_button.setText(action.label)
            try:
                self.plugin_button.setEnabled(not dirty and bool(action.enabled(page)))
            except Exception:
                log.exception("enabled() of the footer action %r raised; counted as False", action.label)
                self.plugin_button.setEnabled(False)
        self.save_button.setVisible(action is None)
        self._say(DIRTY_SHEET_MESSAGE if action is not None and dirty else "")

    def _browse(self, key: str | None) -> None:
        edit = self.output_edits[key]
        start = edit.text().strip()
        if start.lower().endswith(".pdf"):
            start = str(Path(start).parent)
        chosen = QFileDialog.getExistingDirectory(self, f"Folder for: {OUTPUT_LABELS[key]}", start)
        if chosen:
            edit.setText(chosen.replace("\\", "/"))

    def _on_save(self) -> None:
        try:
            self.settings = self._read()
        except ValueError as exc:
            self._say(str(exc), "error")
            return
        self.action = SAVE
        self.accept()

    def _on_command(self, command_id: str) -> None:
        if self.dirty() and QMessageBox.question(
                self, "Unsaved changes", "You have unsaved changes to the deck settings. Discard them and continue?",
                QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel) != QMessageBox.StandardButton.Discard:
            return
        self.action = COMMAND + command_id
        self.accept()

    def _on_plugin_action(self) -> None:
        plugin_tab, page = self.plugin_tabs[self.current_tab()]
        try:
            plugin_tab.footer_action.run(page)
        except Exception as exc:        # a plugin's bug is a line in the sheet, not a crash
            log.exception("footer action %r failed", plugin_tab.footer_action.label)
            self._say(f"{plugin_tab.footer_action.label} failed: {exc}", "error")
        else:
            self._sync_footer()

    def done(self, result: int) -> None:
        HOST_UI.unregister_sheet(self)
        super().done(result)
