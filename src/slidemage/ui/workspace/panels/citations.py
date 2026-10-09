"""Citations: the keys the focused slide cites, resolved against Slidemaster.bib.

A key the file has shows its author, year and title; a missing one is marked in the error color
and can be added: "Add to .bib…" opens the Source view's "Add reference to .bib" form with the
key filled in (the chat of step 10 will offer to draft the entry). Clicking a key shows its entry
in Slidemaster.bib."""
from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout

from .... import bibliography
from ....latex_lint import cited_keys
from ...kit import kit_qss as q
from ...kit.widgets import Button
from .base import Row, SidePanel, box, text


class Citations(SidePanel):
    key = "citations"
    title = "Citations"

    def suffix(self) -> str:
        return "from Slidemaster.bib"

    def meta(self) -> str:
        keys = cited_keys(self.slide_text())
        return str(len(keys)) if keys else ""

    def build(self, id_slug: str) -> None:
        keys = cited_keys(self.slide_text())
        entries = bibliography.load()
        frame, layout = box()
        if not keys:
            row = Row(layout)
            row.body.addWidget(text("No citations on this slide.", q.DETAILS_LABEL))
        for key in keys:
            row = Row(layout)
            known = key in entries
            if known:
                row.make_clickable(lambda k=key: self._show(k))
                row.setToolTip("Show this entry in Slidemaster.bib")
            row.body.addWidget(text(key, q.PANEL_MONO))
            if known:
                row.body.addWidget(text(bibliography.format_citation(key, entries, "full"), q.DETAILS_VALUE))
            else:
                row.body.addWidget(text("Not in Slidemaster.bib", q.PANEL_MISSING))
                add = Button("Add to .bib…", "primary", compact=True)
                add.clicked.connect(lambda _=False, k=key: self._add(k))
                line = QHBoxLayout()
                line.addStretch(1)
                line.addWidget(add)
                row.body.addLayout(line)
        self.body.addWidget(frame)
        self.body.addStretch(1)

    def _show(self, key: str) -> None:
        self.app.open_slide_editor(bibliography.DEFAULT_BIB, line=bibliography.entry_line(key))

    def _add(self, key: str) -> None:
        self.app.centre.source.add_reference(key)
        self.refresh()
