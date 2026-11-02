# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Language: the focused slide's translation group, one row per language of the project.

The facts are slide_language's (the id-slug's language segment and the "Translation of" /
"<LANG> translation" header comments); "outdated" is slide_language.translation_group()'s, which
says exactly what it measures. Each language the slide has no translation in has its Translate to <language>,
which runs the assistant's Translate task on the slide: its task card shows the proposed slide, and creates it on
Apply. A translation has Make this the original (slide_rename.make_original). Set language moved here from the
Details view."""
from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QMessageBox

from .... import languages, slide_language, slide_rename
from ....deck_outline import slide_file_title
from ...kit import kit_qss as q
from ...ai_models import cloud_label
from ...kit.widgets import Button, PopoverMenu
from ..details_view import SAVE_FIRST
from .base import Row, SidePanel, box, text

LABELS = {"mult": "Multilingual"}      # a language code is its own label


class Language(SidePanel):
    key = "language"
    title = "Language"
    translate_buttons: dict[str, Button] = {}   # language -> its Translate to <language>, which sends the slide's text

    def meta(self) -> str:
        slide = self.id_slug()
        own = slide_language.own_language(slide, self._codes()) if slide else None
        if own is None:
            return ""
        links = slide_language.translation_group(self.app.project, slide)
        if not links:
            return f"{own} only" if own != slide_language.MULT else own
        return f"{own} · {' '.join(link.language or '?' for link in links)}" + (" outdated" if any(link.outdated for link in links) else "")

    def _codes(self) -> tuple[str, ...]:
        return languages.project_languages(self.app.project).codes

    def build(self, id_slug: str) -> None:
        self.translate_buttons = {}
        own = slide_language.own_language(id_slug, self._codes())
        path = self.slide_path()
        listed = own not in (None, slide_language.MULT)
        links = slide_language.translation_group(self.app.project, id_slug, path) if listed and path is not None else []
        frame, layout = box()
        self._add_language(layout, own or "?", id_slug, path, self._own_caption(own, links))
        for link in links:
            self._add_language(layout, link.language or "?", link.partner, link.path, self._partner_caption(link),
                               open_it=True)
        have = {link.language for link in links}
        for code in (code for code in self._codes() if listed and code != own and code not in have):
            self._add_missing(layout, code)
        self.body.addWidget(frame)
        if listed and any(link.is_translation for link in links):
            self._add_make_original(id_slug)
        self._add_set_language(id_slug, own)
        self.body.addStretch(1)

    def _add_missing(self, layout, code: str) -> None:
        row = Row(layout)
        line = QHBoxLayout()
        line.addWidget(text(code, q.PANEL_MONO))
        line.addWidget(text("No translation yet", q.DETAILS_LABEL), 1)
        translate = self.translate_buttons[code] = Button(
            cloud_label(self.app.project, self._translate_text(code)), "primary", compact=True)
        translate.setToolTip("Translate this slide with the model chosen in AI setup (the ▾ of the AI switch): "
                             "the assistant shows the proposed slide, and creates it linked to this one when you apply it.")
        translate.clicked.connect(lambda: self.actions.translate(code))
        line.addWidget(translate)
        row.body.addLayout(line)

    @staticmethod
    def _translate_text(code: str) -> str:
        return f"Translate to {languages.name(code)}"

    def refresh_route(self) -> None:
        for code, button in self.translate_buttons.items():
            button.setText(cloud_label(self.app.project, self._translate_text(code)))

    @staticmethod
    def _own_caption(own, links) -> str:
        if own is None:
            return "This slide has no language in its name."
        if own == "mult":
            return "The same in every language (\\multilingualtext)."
        if not links:
            return "No translation linked."
        original = next((link for link in links if link.is_translation), None)
        return f"A translation of {original.partner}." if original else "The original."

    @staticmethod
    def _partner_caption(link) -> str:
        if link.outdated:
            return "Translation outdated: the original was saved after the translation was written."
        return "Translation up to date."

    def _add_language(self, layout, language: str, id_slug: str, path, caption: str, open_it: bool = False) -> None:
        row = Row(layout)
        line = QHBoxLayout()
        line.addWidget(text(language, q.PANEL_MONO))
        line.addWidget(text(slide_file_title(self.app.project, path, id_slug) if path else id_slug, q.DETAILS_VALUE), 1)
        if open_it:
            open_button = Button("Open", "secondary", compact=True)
            open_button.clicked.connect(lambda: self.app.open_slide_editor(path))
            line.addWidget(open_button)
        row.body.addLayout(line)
        row.add_text(caption, q.PANEL_CAPTION)

    def _saved(self, title: str) -> bool:
        """Whether the slide's file may be moved: not while the Source view holds
        edits of it that could not be saved."""
        path = self.slide_path()
        if path is not None and self.actions.is_dirty(path):
            QMessageBox.warning(self, title, SAVE_FIRST)
            return False
        return True

    # -- Make this the original ---------------------------------------------------------------

    def _add_make_original(self, id_slug: str) -> None:
        line = QHBoxLayout()
        line.addWidget(text("Writing in this language from now on?", q.DETAILS_LABEL), 1)
        button = Button("Make this the original", "secondary", compact=True)
        button.setToolTip("The other languages become translations of this slide; right afterwards none is outdated.")
        button.clicked.connect(lambda: self._make_original(id_slug))
        line.addWidget(button)
        self.body.addLayout(line)

    def _make_original(self, id_slug: str) -> None:
        links = slide_language.translation_group(self.app.project, id_slug)
        if any(self.actions.is_dirty(path) for path in (self.slide_path(), *(link.path for link in links)) if path):
            QMessageBox.warning(self, "Make this the original", SAVE_FIRST)
            return
        try:
            slide_rename.make_original(self.app.project, id_slug)
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self, "Make this the original failed", str(exc))
            return
        self.app.log(f"Made {id_slug} the original of its translations")
        self.app.refresh_open_deck_editors()

    # -- Set language ----------------------------------------------------------------------

    def _add_set_language(self, id_slug: str, own) -> None:
        line = QHBoxLayout()
        line.addWidget(text("Language of this slide", q.DETAILS_LABEL), 1)
        button = Button(f"{LABELS.get(own, 'untagged')} ▾", "secondary", compact=True)
        button.setToolTip("Rename the slide to the language and rewrite every deck reference to match.")
        button.clicked.connect(lambda: self._open_menu(button, id_slug, own))
        line.addWidget(button)
        self.body.addLayout(line)

    def _open_menu(self, anchor, id_slug: str, own) -> None:
        menu = PopoverMenu(self, min_width=180)
        for code in (*self._codes(), slide_language.MULT):
            menu.add_item(code, LABELS.get(code, code), icon="check" if code == own else "")
        menu.triggered.connect(lambda code: self._set_language(id_slug, code))
        menu.closed.connect(menu.deleteLater)
        menu.popup_below(anchor)

    def _set_language(self, old: str, language: str) -> None:
        if slide_language.own_language(old, self._codes()) == language or not self._saved("Set language"):
            return
        n_refs = slide_rename.count_references(self.app.project, old)
        confirm = QMessageBox.question(
            self, "Set language",
            f"This will rename {slide_language.current_name(old)} (and any frozen versions of it) to language "
            f"{language}, and rewrite {n_refs} deck reference(s) to match. Continue?")
        if confirm != QMessageBox.StandardButton.Yes:
            return
        try:
            new = slide_rename.set_slide_language(self.app.project, old, language)
        except (FileNotFoundError, FileExistsError, ValueError) as exc:
            QMessageBox.critical(self, "Set language failed", str(exc))
            return
        self.app.log(f"Set language of {old} -> {new} ({n_refs} deck reference(s) updated)")
        self.app.refresh_open_deck_editors()
