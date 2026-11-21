# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The alt-text archive sheet of the Images page: what deleted and archived slides and images left behind.

Two tabs, one list each: the images whose descriptions were archived and the slides whose own data was (takeaway
overrides, reviewed marks, summary). Search looks at names, slide ids and the texts. Each entry can hold several
snapshots (the archive only grows); the picker chooses which one is shown and acted on. An image's snapshot can be
restored (text that is there now is kept unless the person says otherwise, and then it joins the archive first),
copied onto another image, or deleted for good, which is the only way anything leaves the archive.
"""
from __future__ import annotations

import json
from typing import Callable, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QInputDialog,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..kit.tokens import SPACE
from ... import alt_archive, alt_images
from ...project import ProjectContext
from ..kit import kit_qss as q
from ..kit.widgets import Button, ModalSheet, Page, caption

LANGUAGE_NAMES = {"en": "English", "de": "German"}


def describe_image_snapshot(image: str, snapshot: dict) -> str:
    """What one archived image entry holds, as text for a person to read before restoring it."""
    entry = alt_images.entry_from_dict(image, snapshot.get("entry") or {})
    lines = [f"{image}", f"Archived {snapshot.get('archived', '?')}: {snapshot.get('reason', '?')}"]
    if snapshot.get("slides"):
        lines.append("Used on slides: " + ", ".join(snapshot["slides"]))
    lines.append(f"Role: {entry.role}" + (f" · drafted by {entry.drafted_by}" if entry.drafted_by else ""))
    if entry.hint:
        lines.append(f"Hint: {entry.hint}")
    for code, text in entry.texts.items():
        if text.is_blank:
            continue
        lines += ["", f"{LANGUAGE_NAMES.get(code, code.upper())} ({text.status})"]
        for label, value in (("Short", text.short), ("Long", text.long), ("Takeaway", text.takeaway_default),
                             ("Source", text.source)):
            if value:
                lines.append(f"{label}: {value}")
    return "\n".join(lines)


def describe_slide_snapshot(bare_id: str, snapshot: dict) -> str:
    """What one archived slide record holds."""
    lines = [f"{snapshot.get('name') or bare_id}", f"Archived {snapshot.get('archived', '?')}: {snapshot.get('reason', '?')}"]
    if snapshot.get("summary"):
        lines += ["", f"Summary: {snapshot['summary']}"]
    for image, use in (snapshot.get("uses") or {}).items():
        lines += ["", image]
        for code, text in sorted((use.get("takeaway") or {}).items()):
            lines.append(f"  Takeaway ({code}): {text}")
        if use.get("reviewed"):
            lines.append(f"  Reviewed {use['reviewed']}")
    return "\n".join(lines)


def _matches(needle: str, key: str, snapshots: list[dict]) -> bool:
    """Whether the search text is in the key or anywhere in its snapshots (names, slide ids, texts)."""
    needle = needle.strip().lower()
    return not needle or needle in key.lower() or needle in json.dumps(snapshots, ensure_ascii=False).lower()


class _Pane(QWidget):
    """One tab: search, the list, the picker of snapshots, the text of the chosen one and the buttons."""

    def __init__(self, noun: str, describe: Callable[[str, dict], str], label: Callable[[str, list[dict]], str]) -> None:
        super().__init__()
        self._describe, self._label = describe, label
        self.data: dict[str, list[dict]] = {}
        self.marked: set[str] = set()      # the keys that can be restored right now: listed first, marked
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACE.md)
        self.search = QLineEdit()
        self.search.setPlaceholderText(f"Search {noun}s by name, slide or text")
        self.search.textChanged.connect(self.fill)
        layout.addWidget(self.search)
        self.list = QListWidget()
        self.list.setObjectName(q.IMAGE_LIST)
        self.list.setMinimumHeight(180)
        self.list.currentItemChanged.connect(lambda *_: self._show_versions())
        layout.addWidget(self.list, 1)
        self.versions = QComboBox()
        self.versions.currentIndexChanged.connect(lambda _i: self._show_text())
        layout.addWidget(self.versions)
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setMinimumHeight(180)
        layout.addWidget(self.text, 1)
        self.buttons = QHBoxLayout()
        self.buttons.setSpacing(SPACE.sm)
        layout.addLayout(self.buttons)
        self.empty = caption("")
        layout.addWidget(self.empty)

    @property
    def key(self) -> Optional[str]:
        item = self.list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item is not None else None

    @property
    def index(self) -> int:
        """The snapshot chosen in the picker (an index into the key's list, newest last)."""
        return max(self.versions.currentIndex(), 0) if self.versions.count() else -1

    def set_data(self, data: dict[str, list[dict]], marked: set[str] = frozenset(), keep: Optional[str] = None) -> None:
        self.data, self.marked = data, set(marked)
        self.fill(keep=keep)

    def fill(self, *_args, keep: Optional[str] = None) -> None:
        keep = keep or self.key
        self.list.blockSignals(True)
        self.list.clear()
        keys = sorted((k for k, snaps in self.data.items() if _matches(self.search.text(), k, snaps)),
                      key=lambda k: (k not in self.marked, k))
        for key in keys:
            snaps = self.data[key]
            item = QListWidgetItem(("↩ " if key in self.marked else "") + self._label(key, snaps))
            item.setData(Qt.ItemDataRole.UserRole, key)
            self.list.addItem(item)
        row = next((i for i, key in enumerate(keys) if key == keep), 0 if keys else -1)
        self.list.setCurrentRow(row)
        self.list.blockSignals(False)
        self.empty.setText("" if keys else ("Nothing here matches the search." if self.data else "Nothing archived yet."))
        self._show_versions()

    def _show_versions(self) -> None:
        self.versions.blockSignals(True)
        self.versions.clear()
        snaps = self.data.get(self.key or "", [])
        for number, snap in enumerate(snaps, 1):
            self.versions.addItem(f"Version {number} of {len(snaps)} · {snap.get('archived', '?')} · "
                                  f"{snap.get('reason', '?')}")
        self.versions.setCurrentIndex(len(snaps) - 1)
        self.versions.blockSignals(False)
        self.versions.setVisible(len(snaps) > 1)
        self._show_text()

    def _show_text(self) -> None:
        key = self.key
        snaps = self.data.get(key or "", [])
        self.text.setPlainText(self._describe(key, snaps[self.index]) if key and snaps else "")
        for i in range(self.buttons.count()):
            widget = self.buttons.itemAt(i).widget()
            if widget is not None:
                widget.setEnabled(bool(snaps))


class AltArchiveSheet(ModalSheet):
    """Browse the archive and restore, copy or delete from it. `changed` says whether the store or the archive was
    touched, so the page reads them again when the sheet closes."""

    def __init__(self, parent: QWidget, project: ProjectContext, restorable: set[str] = frozenset(),
                 restorable_slides: set[str] = frozenset()) -> None:
        super().__init__("Alt-text archive", parent, width=760)
        self.project = project
        self.changed = False
        self._restorable_slides = set(restorable_slides)
        self._marked = set(restorable)

        self.images = _Pane("image", describe_image_snapshot, self._image_label)
        self.restore_image_button = Button("Restore", "primary", compact=True)
        self.restore_image_button.setToolTip("Put this description back for the image. Text the image has now is "
                                             "kept unless you choose otherwise.")
        self.restore_image_button.clicked.connect(self._restore_image)
        self.copy_button = Button("Copy onto another image…", "secondary", compact=True)
        self.copy_button.setToolTip("Use this description for another image (a replacement, say). The copy counts "
                                    "as unreviewed: it describes a different picture.")
        self.copy_button.clicked.connect(self._copy_image)
        self.delete_image_button = Button("Delete this version…", "ghost", compact=True)
        self.delete_image_button.clicked.connect(lambda: self._delete(self.images, alt_archive.purge_image))
        for button in (self.restore_image_button, self.copy_button, self.delete_image_button):
            self.images.buttons.addWidget(button)
        self.images.buttons.addStretch(1)

        self.slides = _Pane("slide", describe_slide_snapshot, self._slide_label)
        self.restore_slide_button = Button("Restore", "primary", compact=True)
        self.restore_slide_button.setToolTip("Put this slide's takeaway texts, reviewed marks and summary back. "
                                             "What the slide has now is kept.")
        self.restore_slide_button.clicked.connect(self._restore_slide)
        self.delete_slide_button = Button("Delete this version…", "ghost", compact=True)
        self.delete_slide_button.clicked.connect(lambda: self._delete(self.slides, alt_archive.purge_slide))
        for button in (self.restore_slide_button, self.delete_slide_button):
            self.slides.buttons.addWidget(button)
        self.slides.buttons.addStretch(1)

        page = Page()
        page.body.addWidget(caption(
            "What deleted and archived slides and images left behind, kept in media/archive/alt-text-archive.json. "
            "Entries marked ↩ can be restored now: the image is in the project again and has no description. "
            "Nothing leaves the archive except what you delete here."))
        page.body.addWidget(self.images, 1)
        self.add_tab("Images", page)
        slide_page = Page()
        slide_page.body.addWidget(self.slides, 1)
        self.add_tab("Slides", slide_page)
        self.add_button("Close", role="accept")
        self.setMinimumHeight(640)
        self._reload()

    # -- data ------------------------------------------------------------------------------------------------

    @staticmethod
    def _image_label(image: str, snaps: list[dict]) -> str:
        entry = alt_images.entry_from_dict(image, snaps[-1].get("entry") or {})
        short = entry.text_for("en").short
        return f"{image} · {snaps[-1].get('reason', '')} {snaps[-1].get('archived', '')}" + (f" · {short}" if short else "")

    @staticmethod
    def _slide_label(bare_id: str, snaps: list[dict]) -> str:
        return f"{snaps[-1].get('name') or bare_id} · {snaps[-1].get('reason', '')} {snaps[-1].get('archived', '')}"

    def _reload(self) -> None:
        data = alt_archive.load(self.project)
        self.images.set_data(data["images"], self._marked)
        self.slides.set_data(data["slides"], self._restorable_slides)

    def _writable(self) -> bool:
        try:
            alt_images.check_writable(self.project)
            alt_archive.load(self.project)
        except alt_images.NewerStoreError as exc:
            QMessageBox.warning(self, "Alt-text archive", str(exc))
            return False
        return True

    # -- actions ---------------------------------------------------------------------------------------------

    def _restore_image(self) -> None:
        image, index = self.images.key, self.images.index
        if image is None or not self._writable():
            return
        outcome = alt_archive.restore_image(self.project, image, index)
        if outcome == "kept":
            if QMessageBox.question(
                    self, "Restore description",
                    f"{image} has a description already. Replace it with the archived one? The description it has now "
                    "moves to the archive, so neither is lost.") != QMessageBox.StandardButton.Yes:
                return
            outcome = alt_archive.restore_image(self.project, image, index, overwrite=True)
        if outcome == "restored":
            self.changed = True
            self._marked.discard(image)
            self._reload()

    def _copy_image(self) -> None:
        image, index = self.images.key, self.images.index
        if image is None or not self._writable():
            return
        entries = alt_images.load_store(self.project)
        free = sorted(name for name, entry in entries.items() if name != image and alt_archive.blank(entry))
        if not free:
            QMessageBox.information(self, "Copy description",
                                    "No other image is without a description: a copy never overwrites one.")
            return
        target, accepted = QInputDialog.getItem(self, "Copy description", f"Use the description of {image} for:", free, 0,
                                                False)
        if not accepted or not target:
            return
        if alt_archive.copy_image_text(self.project, image, target, index) == "copied":
            self.changed = True
            QMessageBox.information(self, "Copy description", f"Copied onto {target}. It counts as unreviewed: check "
                                    "it against the new picture.")
            self._reload()

    def _restore_slide(self) -> None:
        bare_id, index = self.slides.key, self.slides.index
        if bare_id is None or not self._writable():
            return
        result = alt_archive.restore_slide(self.project, bare_id, index)
        if result.uses or result.summary:
            self.changed = True
            self._restorable_slides.discard(bare_id)
        notes = []
        if result.missing:
            notes.append("These images have no description in the project, restore them first: "
                         + ", ".join(sorted(set(result.missing))) + ".")
        if not (result.uses or result.summary):
            notes.insert(0, "Nothing came back: the slide has its own data for these already.")
        if notes:
            QMessageBox.information(self, "Restore slide data", "\n".join(notes))
        self._reload()

    def _delete(self, pane: _Pane, purge: Callable[..., int]) -> None:
        key, index = pane.key, pane.index
        if key is None or not self._writable():
            return
        if QMessageBox.question(
                self, "Delete from the archive",
                f"Delete this version of {key} from the archive for good? This cannot be undone (the project's git "
                "history may still hold it).") != QMessageBox.StandardButton.Yes:
            return
        if purge(self.project, key, index):
            self.changed = True
            self._marked.discard(key)
            self._reload()
