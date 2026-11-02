# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Settings → Project → Languages (docs/plans/content-languages.md, 2.1): the project's main language, its
secondary languages in the order the language switch lists them, and the form of address translations use.

* The main language is where new slides and decks start and what the other languages fall back to. Changing it
  renames nothing and moves no text; the old main language stays in the project, as the first secondary one.
* Add language…: a language of the table (languages.py). Slides whose slug already starts with its code as a capital
  word ("x7k-IT-Governance") would be read as that language from now on, so they are listed first and tagged with
  their real language (slide_rename.tag_untagged), or the language is not added.
* Remove: a language that slides or decks still use is removed after a question with the counts; they stay as they
  are, but SlideMage no longer offers the language.

Every change is saved at once, into .slidemage/project.json (languages.set_project_languages).
"""
from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QAbstractItemView, QComboBox, QListWidget, QListWidgetItem, QMessageBox, QVBoxLayout

from ... import deck_scan, languages, slide_rename
from ...ai import translation_style
from ...deck_settings import read_settings
from ...project import ProjectContext
from ..kit.widgets import Button, Field, ModalSheet, SegmentedControl, Surface, caption, row

MULT = "mult"
SAVE_FIRST = ("The Source view holds edits of {name} that could not be saved (see the notice there). Resolve that "
              "first: the slide's file is renamed.")


def label(code: str) -> str:
    """"French (français)" for the pickers, "German (Deutsch)"; an unknown code is itself."""
    language = languages.get(code)
    return f"{language.english} ({language.native})" if language and language.native != language.english else languages.name(code)


def _count(n: int, noun: str) -> str:
    return f"{n} {noun}" if n == 1 else f"{n} {noun}s"


def slides_in(ctx: ProjectContext, code: str) -> int:
    """The slides whose file name says they are in `code` (the second segment of the id-slug, upper case)."""
    code = code.upper()
    suffix = "-current.tex"
    return sum(1 for path in ctx.slides_dir.glob(f"*{suffix}") if path.name.split("-", 2)[1:2] == [code])


def decks_in(decks: Sequence, code: str) -> int:
    """The decks whose \\decklanguage is `code`."""
    return sum(1 for deck in decks if read_settings(deck.text).language.lower() == code.lower())


class AddLanguageSheet(ModalSheet):
    """Add language…: a language of the table that the project does not have. After exec(), `code` is the choice."""

    def __init__(self, parent, taken: Sequence[str]) -> None:
        super().__init__("Add language", parent, width=420)
        body = Surface()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 0, 0)
        self.combo = QComboBox()
        self.combo.setAccessibleName("Language")
        for language in sorted(languages.TABLE, key=lambda language: language.english):
            if language.code not in taken:
                self.combo.addItem(label(language.code), language.code)
        layout.addWidget(Field("Language", self.combo))
        layout.addStretch(1)
        self.add_tab("", body)
        self.add_button("Cancel", role="reject")
        add = self.add_button("Add", kind="primary")
        add.setDefault(True)
        add.clicked.connect(self._on_ok)
        self.code = ""

    def _on_ok(self) -> None:
        self.code = self.combo.currentData() or ""
        if self.code:
            self.accept()


class UntaggedSlugsSheet(ModalSheet):
    """The slides that carry no language but would be read as `code` once it is added: what language is each in?
    After exec(), `chosen()` is {id-slug: "EN" | "mult" | ...}."""

    def __init__(self, parent, code: str, id_slugs: Sequence[str], choices: Sequence[str]) -> None:
        super().__init__(f"Slides named like {languages.name(code)}", parent, width=560)
        body = Surface()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(caption(
            f"{_count(len(id_slugs), 'slide')} without a language in the name start{'s' if len(id_slugs) == 1 else ''} "
            f"with {code.upper()}, which SlideMage would read as the language {languages.name(code)} once you add it. "
            "Choose each slide's own language: the slide is renamed to carry it (its files, its calls in the decks "
            "and its translation links follow)."))
        self.combos: dict[str, QComboBox] = {}
        for id_slug in id_slugs:
            combo = QComboBox()
            combo.setAccessibleName(f"Language of {id_slug}")
            for choice in choices:
                combo.addItem(label(choice) if choice != MULT else "Multilingual", choice.upper() if choice != MULT else MULT)
            self.combos[id_slug] = combo
            layout.addWidget(Field(id_slug, combo))
        self.add_tab("", body, scroll=True)
        self.add_button("Cancel", role="reject")
        ok = self.add_button(f"Rename them and add {languages.name(code)}", kind="primary")
        ok.setDefault(True)
        ok.clicked.connect(self.accept)

    def chosen(self) -> dict[str, str]:
        return {id_slug: combo.currentData() for id_slug, combo in self.combos.items()}


class LanguagesSection(Surface):
    """The Languages part of Settings' Project tab. `app` is the window: its project, its decks, its Source view
    (`centre`) and `refresh_open_deck_editors`; a window without them shows no deck counts and rescans nothing."""

    changed = Signal()        # the languages were saved

    def __init__(self, app) -> None:
        super().__init__()
        self.app = app
        self.project = app.project
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.main = QComboBox()
        self.main.setAccessibleName("Main language")
        self.main.activated.connect(self._on_main)
        layout.addWidget(Field("Main language", self.main))
        layout.addWidget(caption(
            "Where new slides and decks start, and what the others fall back to. Changing it renames nothing and "
            "moves no text."))
        self.list = QListWidget()
        self.list.setAccessibleName("Secondary languages")
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list.setMinimumHeight(110)
        self.list.itemSelectionChanged.connect(self._sync_buttons)
        layout.addWidget(Field("Secondary languages (in the order the language switch lists them)", self.list))
        self.add_button = Button("Add language…", compact=True)
        self.remove_button = Button("Remove", compact=True)
        self.up_button = Button("Move up", compact=True)
        self.down_button = Button("Move down", compact=True)
        for button, slot in ((self.add_button, self.add_language), (self.remove_button, self.remove_language),
                             (self.up_button, lambda: self.move(-1)), (self.down_button, lambda: self.move(1))):
            button.clicked.connect(lambda _checked=False, slot=slot: slot())
        layout.addWidget(row(self.add_button, self.remove_button, self.up_button, self.down_button, stretch=3))
        layout.addWidget(caption("The languages are stored with the project (.slidemage/project.json), so everyone "
                                 "who opens it sees the same ones."))

        self.address = SegmentedControl(tuple((a, a) for a in translation_style.ADDRESSES),
                                        current=translation_style.de_address(self.project))
        self.address.changed.connect(lambda value: translation_style.set_de_address(self.project, value))
        layout.addWidget(Field("German address in Claude Code translations (this project)", self.address))
        self.fill()

    # -- what the page shows -------------------------------------------------------------------------------------

    def current(self) -> languages.Languages:
        return languages.project_languages(self.project)

    def fill(self, select: str | None = None) -> None:
        select = select if select is not None else self.selected()
        own = self.current()
        self.main.clear()
        choices = [language.code for language in languages.TABLE]
        for code in (own.main, *own.secondary):
            if code not in choices:
                choices.append(code)             # a code the table does not have, written by hand
        for code in sorted(choices, key=languages.name):
            self.main.addItem(label(code), code)
        self.main.setCurrentIndex(self.main.findData(own.main))
        self.list.clear()
        for code in own.secondary:
            item = QListWidgetItem(f"{label(code)}  ·  {code.upper()}")
            item.setData(Qt.ItemDataRole.UserRole, code)
            self.list.addItem(item)
            if code == select:
                self.list.setCurrentItem(item)
        self._sync_buttons()

    def selected(self) -> str | None:
        item = self.list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item is not None and item.isSelected() else None

    def _sync_buttons(self) -> None:
        secondary = self.current().secondary
        index = secondary.index(self.selected()) if self.selected() in secondary else -1
        self.remove_button.setEnabled(index >= 0)
        self.up_button.setEnabled(index > 0)
        self.down_button.setEnabled(0 <= index < len(secondary) - 1)

    def decks(self) -> list:
        return list(getattr(self.app, "decks", None) or deck_scan.scan_decks(self.project))

    # -- saving --------------------------------------------------------------------------------------------------

    def commit(self, main: str, secondary: Sequence[str], summary: str, select: str | None = None) -> bool:
        try:
            languages.set_project_languages(self.project, main, secondary)
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, "Languages", f"Couldn't save the languages: {exc}")
            return False
        self.fill(select)
        log = getattr(self.app, "log", None)
        if log is not None:
            log(summary)
        self.changed.emit()
        return True

    # -- the buttons ---------------------------------------------------------------------------------------------

    def _on_main(self, index: int) -> None:
        code = self.main.itemData(index)
        own = self.current()
        if code == own.main:
            return
        secondary = [own.main, *(c for c in own.secondary if c != code)]
        if not self.commit(code, secondary, f"Main language of the project: {languages.name(code)}", own.main):
            self.fill()

    def add_language(self, code: str | None = None) -> bool:
        """Add `code` (asked for when None) as the last secondary language. False when nothing was added."""
        own = self.current()
        if code is None:
            sheet = AddLanguageSheet(self, own.lower)
            if not sheet.exec() or not sheet.code:
                return False
            code = sheet.code
        if not self._tag_untagged(code, own):
            return False
        return self.commit(own.main, [*own.secondary, code], f"Added the language {languages.name(code)}", code)

    def _tag_untagged(self, code: str, own: languages.Languages) -> bool:
        """Tag the slides that the new language's code would take for its own. False when the user cancels or a
        slide cannot be renamed; the language is then not added."""
        id_slugs = slide_rename.untagged_slugs_matching(self.project, code)
        if not id_slugs:
            return True
        sheet = UntaggedSlugsSheet(self, code, id_slugs, [*own.lower, MULT])
        if not sheet.exec():
            return False
        centre = getattr(self.app, "centre", None)
        chosen = sheet.chosen()
        for id_slug in id_slugs:
            path = self.project.slides_dir / f"{id_slug}-current.tex"
            if centre is not None and centre.unsaved(path):
                QMessageBox.warning(self, "Add language", SAVE_FIRST.format(name=path.name))
                return False
        for id_slug, language in chosen.items():
            try:
                new = slide_rename.tag_untagged(self.project, id_slug, language)
            except (FileNotFoundError, FileExistsError, ValueError) as exc:
                QMessageBox.critical(self, "Add language", f"{id_slug} could not be renamed: {exc}")
                return False
            log = getattr(self.app, "log", None)
            if log is not None:
                log(f"Gave {id_slug} the language {language}: {new}")
        refresh = getattr(self.app, "refresh_open_deck_editors", None)
        if refresh is not None:
            refresh()
        return True

    def remove_language(self, confirm: bool = True) -> bool:
        """Remove the selected secondary language, after asking when slides or decks still use it."""
        code = self.selected()
        own = self.current()
        if code not in own.secondary:
            return False
        slides, decks = slides_in(self.project, code), decks_in(self.decks(), code)
        if confirm and (slides or decks):
            used = " and ".join([*([_count(slides, "slide")] if slides else []), *([_count(decks, "deck")] if decks else [])])
            name = languages.name(code)
            answer = QMessageBox.question(
                self, "Remove language",
                f"{used} {'is' if slides + decks == 1 else 'are'} in {name}; they stay as they are, but SlideMage "
                f"no longer offers {name}. Remove it?")
            if answer != QMessageBox.StandardButton.Yes:
                return False
        return self.commit(own.main, [c for c in own.secondary if c != code],
                           f"Removed the language {languages.name(code)}")

    def move(self, delta: int) -> None:
        own = self.current()
        code = self.selected()
        if code not in own.secondary:
            return
        secondary = list(own.secondary)
        index = secondary.index(code)
        other = index + delta
        if not 0 <= other < len(secondary):
            return
        secondary[index], secondary[other] = secondary[other], secondary[index]
        self.commit(own.main, secondary, f"Moved the language {languages.name(code)} {'up' if delta < 0 else 'down'}",
                    code)
