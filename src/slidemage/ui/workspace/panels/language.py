"""Language: the focused slide's language, its translation partner and whether that is outdated.

The facts are slide_language's (the id-slug's language segment and the "Translation of" /
"<LANG> translation" header comments); "outdated" is slide_language.translation_link()'s, which
says exactly what it measures. Translate… opens the Add slide sheet on a translation into the
other language, with the machine translation ticked where it is possible (EN to DE). Set language
moved here from the Details view."""
from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QMessageBox

from .... import slide_language, slide_rename
from ....deck_outline import slide_file_title
from ...kit import kit_qss as q
from ...kit.widgets import Button, PopoverMenu
from ..details_view import SAVE_FIRST
from .base import Row, SidePanel, box, text

# The language menu: label -> the code slide_rename.set_slide_language() takes.
LANGUAGE_CHOICES = (("EN", "EN"), ("DE", "DE"), ("Multilingual", "mult"))
LABELS = {code: label for label, code in LANGUAGE_CHOICES}
OTHER = {"EN": "DE", "DE": "EN"}


class Language(SidePanel):
    key = "language"
    title = "Language"

    def meta(self) -> str:
        slide = self.id_slug()
        own = slide_language.own_language(slide) if slide else None
        if own is None:
            return ""
        link = slide_language.translation_link(slide)
        if link is None:
            return f"{own} only" if own in OTHER else own
        return f"{own} · {link.language or '?'}" + (" outdated" if link.outdated else "")

    def build(self, id_slug: str) -> None:
        own = slide_language.own_language(id_slug)
        path = self.slide_path()
        link = slide_language.translation_link(id_slug, path) if own in OTHER and path is not None else None
        frame, layout = box()
        self._add_language(layout, own or "?", id_slug, path, self._own_caption(own, link))
        if link is not None:
            self._add_language(layout, link.language or "?", link.partner, link.path, self._partner_caption(link),
                               open_it=True)
        elif own in OTHER:
            row = Row(layout)
            line = QHBoxLayout()
            line.addWidget(text(OTHER[own], q.PANEL_MONO))
            line.addWidget(text("No translation yet", q.DETAILS_LABEL), 1)
            translate = Button(f"Translate to {OTHER[own]}…", "primary", compact=True)
            translate.setToolTip("Create the translation as a new slide linked to this one, with the text "
                                 "translated by the model chosen under Settings -> AI models (EN to DE).")
            translate.clicked.connect(lambda: self._translate(id_slug, OTHER[own]))
            line.addWidget(translate)
            row.body.addLayout(line)
        self.body.addWidget(frame)
        self._add_set_language(id_slug, own)
        self.body.addStretch(1)

    @staticmethod
    def _own_caption(own, link) -> str:
        if own is None:
            return "This slide has no language in its name."
        if own == "mult":
            return "The same in every language (\\multilingualtext)."
        if link is None:
            return "No translation linked."
        return f"A translation of {link.partner}." if link.is_translation else "The original."

    @staticmethod
    def _partner_caption(link) -> str:
        if link.outdated:
            return "Translation outdated: the original was saved after the translation was written."
        return "Translation up to date."

    def _add_language(self, layout, language: str, id_slug: str, path, caption: str, open_it: bool = False) -> None:
        row = Row(layout)
        line = QHBoxLayout()
        line.addWidget(text(language, q.PANEL_MONO))
        line.addWidget(text(slide_file_title(path, id_slug) if path else id_slug, q.DETAILS_VALUE), 1)
        if open_it:
            open_button = Button("Open", "secondary", compact=True)
            open_button.clicked.connect(lambda: self.app.open_slide_editor(path))
            line.addWidget(open_button)
        row.body.addLayout(line)
        row.body.addWidget(text(caption, q.PANEL_CAPTION))

    # -- Translate -----------------------------------------------------------------------

    def _saved(self, title: str) -> bool:
        """Whether the slide's file may be moved: not while the Source view holds
        unsaved edits of it."""
        path = self.slide_path()
        if path is not None and self.app.centre.is_dirty(path):
            QMessageBox.warning(self, title, SAVE_FIRST)
            return False
        return True

    def _translate(self, id_slug: str, target: str) -> None:
        self.app.slide_list.add_slide("translate", id_slug, target)

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
        for label, code in LANGUAGE_CHOICES:
            menu.add_item(code, label, icon="check" if code == own else "")
        menu.triggered.connect(lambda code: self._set_language(id_slug, code))
        menu.closed.connect(menu.deleteLater)
        menu.popup_below(anchor)

    def _set_language(self, old: str, language: str) -> None:
        if slide_language.own_language(old) == language or not self._saved("Set language"):
            return
        n_refs = slide_rename.count_references(old)
        confirm = QMessageBox.question(
            self, "Set language",
            f"This will rename {old}-current.tex (and any frozen versions of it) to language "
            f"{language}, and rewrite {n_refs} deck reference(s) to match. Continue?")
        if confirm != QMessageBox.StandardButton.Yes:
            return
        try:
            new = slide_rename.set_slide_language(old, language)
        except (FileNotFoundError, FileExistsError, ValueError) as exc:
            QMessageBox.critical(self, "Set language failed", str(exc))
            return
        self.app.log(f"Set language of {old} -> {new} ({n_refs} deck reference(s) updated)")
        self.app.refresh_open_deck_editors()
