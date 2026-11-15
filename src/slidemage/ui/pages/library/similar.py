# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Advisory clusters, their usage and source differences."""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, replace
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QButtonGroup, QGridLayout, QHBoxLayout, QScrollArea, QVBoxLayout

from .... import (alt_blocks, deck_context, languages, library_data, preview_target, render_key,
                  render_lookup, slide_language)
from ....slide_similarity import Cluster, normalise, uncomment
from ...kit.flow import FlowLayout
from ...kit.tokens import RADIUS_LG, SPACE
from ...kit.widgets import Button, Card, Chip, Surface, ToggleChip, caption, text_label


CLASSES = {"all": "All", "exact": "Exact copies", "same_words": "Same words", "similar": "Similar text"}
WORD_RE = re.compile(r"\$\$.*?\$\$|\$[^$]*\$|\\\(.*?\\\)|\\\[.*?\\\]|media/[^\s{}\\]+|"
                     r"\\[A-Za-z@]+\*?|\d+(?:[.,:/–-]\d+)*|[^\W_]+|[=<>+\-*/^_]", re.DOTALL)


@dataclass
class Member:
    id: str
    title: str
    usage: str
    png: Path | None


@dataclass
class PreparedCluster:
    cluster: Cluster
    members: list[Member]
    diffs: list[list[tuple[str, str, bool]]]


def prepare_clusters(ctx, clusters, usage, resolver, language):
    """Read sources and renders and compute diffs on the scan worker, before building widgets."""
    codes = languages.project_languages(ctx).codes
    library = library_data.read(ctx)
    ids = library_data.group_ids(ctx)
    pool = {i for i, original in ids.items() if original in library.pool}
    prepared = []
    for cluster in sorted(clusters, key=lambda c: (not pool.intersection(c.ids),
                                                 list(CLASSES).index(c.kind), -len(c.ids))):
        members = frozenset(ids[i] for i in cluster.ids if i in ids)
        if (members, cluster.fingerprint) in library.different_on_purpose:
            continue
        members, sources = [], []
        for slide_id in cluster.ids:
            path = slide_language.current_path_for_bare_id(ctx, slide_id)
            if path is None:
                continue
            try:
                source = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            slug = path.name[:-len(slide_language.CURRENT_SUFFIX)]
            decks = usage.get(slide_id, [])
            png = None
            if resolver is not None:
                try:
                    own = slide_language.own_language(slug, codes)
                    preamble = decks[-1].preamble_text if decks else None
                    target = preview_target.PreviewTarget(ctx, "slide", slug, None, None, None, None, preamble)
                    unit = render_key.unit_for(target, "instructor", own if own in codes else language)
                    record = render_lookup.instructor_reference(dict(resolver=resolver, unit=unit), strict=True)
                    if record is not None:
                        png = resolver.store.thumbnail_path(record)
                except Exception:  # The Library also works when the render store is unavailable.
                    pass
            members.append(Member(slide_id, alt_blocks.plain_title(deck_context.frame_title(source) or slug),
                                  ", ".join(deck.name for deck in decks), png))
            sources.append(source)
        if len(members) < 2:
            continue
        diffs = []
        if cluster.kind != "exact":
            for source in sources[1:]:
                changes = []
                if cluster.kind == "same_words":
                    for line in difflib.unified_diff(uncomment(sources[0]).splitlines(),
                                                     uncomment(source).splitlines(), lineterm=""):
                        changes.append((line, "delete" if line.startswith("-") else
                                        "insert" if line.startswith("+") else "equal", False))
                else:
                    words = [[w for w in WORD_RE.findall(normalise(text))
                              if not w.startswith("\\") or w.startswith((r"\(", r"\["))]
                             for text in (sources[0], source)]
                    for operation, a, b, c, d in difflib.SequenceMatcher(None, *words, autojunk=False).get_opcodes():
                        groups = [("equal", words[0][a:b])] if operation == "equal" else []
                        if operation in ("delete", "replace"):
                            groups.append(("delete", words[0][a:b]))
                        if operation in ("insert", "replace"):
                            groups.append(("insert", words[1][c:d]))
                        for role, tokens in groups:
                            for word in tokens:
                                changes.append((word, role, any(ch.isdigit() for ch in word)
                                                or word.startswith(("$", r"\(", r"\["))
                                                or word in "=<>+-*/^_"))
                diffs.append(changes)
        prepared.append(PreparedCluster(replace(cluster, ids=[m.id for m in members]), members, diffs))
    return prepared


class SimilarView(Surface):
    count_changed = Signal(int)

    def __init__(self, app) -> None:
        super().__init__()
        self.app = app
        self._dismissed = set()
        self._cards = []
        self._diff_labels = []
        self._kind = "all"
        body = QVBoxLayout(self)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(SPACE.xl)
        body.addWidget(text_label("Similar slides", "title"))
        body.addWidget(caption("Compared by text within one language. Translations, title slides and section slides "
                               "are left out. SlideMage only advises: nothing is merged."))
        filters = FlowLayout()
        self.chips = {}
        group = QButtonGroup(self)
        group.setExclusive(True)
        for kind, title in CLASSES.items():
            chip = ToggleChip(f"{title} · 0")
            group.addButton(chip)
            chip.setChecked(kind == "all")
            chip.clicked.connect(lambda _checked=False, k=kind: self._filter(k))
            filters.addWidget(chip)
            self.chips[kind] = chip
        body.addLayout(filters)
        self.status = caption("Finding similar slides…")
        body.addWidget(self.status)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        content = Surface()
        self.cards = QVBoxLayout(content)
        self.cards.setContentsMargins(0, 0, 0, 0)
        self.cards.setSpacing(SPACE.xl)
        self.cards.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll.setWidget(content)
        body.addWidget(scroll, 1)
        remove_listener = app.theme.add_listener(self._style_diffs)
        self.destroyed.connect(lambda: remove_listener())

    def set_clusters(self, clusters) -> None:
        self._dismissed.clear()  # Persisted dismissals were filtered on the scan worker.
        self._cards.clear()
        self._diff_labels.clear()
        while (item := self.cards.takeAt(0)) is not None:
            item.widget().hide()
            item.widget().deleteLater()
        self.sequences = Card()
        self.sequence_toggle = Button("Sequences in one deck (0)", "ghost")
        self.sequence_toggle.setCheckable(True)
        self.sequences.layout().addWidget(self.sequence_toggle)
        sequence_body = Surface()
        sequence_layout = QVBoxLayout(sequence_body)
        sequence_layout.setContentsMargins(0, 0, 0, 0)
        self.sequences.layout().addWidget(sequence_body)
        sequence_body.hide()
        self.sequence_toggle.toggled.connect(sequence_body.setVisible)
        for prepared in clusters:
            cluster = prepared.cluster
            card = Card()
            card.setProperty("cluster_kind", cluster.kind)
            head = QHBoxLayout()
            head.addWidget(Chip("Sequence" if cluster.sequence_deck else
                                {"exact": "Exact copy", "same_words": "Same words", "similar": "Similar text"}[cluster.kind],
                                "ok" if cluster.sequence_deck else "warning" if cluster.kind == "exact" else "neutral"))
            title = text_label(prepared.members[0].title, "heading")
            title.setTextFormat(Qt.TextFormat.PlainText)
            title.setWordWrap(True)
            head.addWidget(title, 1)
            if cluster.kind == "similar":
                head.addWidget(caption(f"overlap {cluster.overlap:.0%}"))
            card.layout().addLayout(head)
            members = QGridLayout()
            for index, data in enumerate(prepared.members):
                member = Surface()
                column = QVBoxLayout(member)
                column.setContentsMargins(0, 0, 0, 0)
                picture = text_label("No render yet", "secondary")
                picture.setFixedSize(256, 144)
                picture.setAlignment(Qt.AlignmentFlag.AlignCenter)
                column.addWidget(picture)
                if data.png is not None:
                    pixmap = QPixmap(str(data.png))
                    if not pixmap.isNull():
                        picture.setPixmap(pixmap.scaled(picture.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                                       Qt.TransformationMode.SmoothTransformation))
                column.addWidget(text_label(data.id, "mono"))
                usage = caption(data.usage or "in no deck", "" if data.usage else "warning")
                usage.setTextFormat(Qt.TextFormat.PlainText)
                column.addWidget(usage)
                members.addWidget(member, index // 2, index % 2, Qt.AlignmentFlag.AlignTop)
            card.layout().addLayout(members)
            if cluster.sequence_deck:
                card.layout().addWidget(caption(f"{len(cluster.ids)} slides in {cluster.sequence_deck.stem}"))
            if cluster.kind == "exact":
                card.layout().addWidget(caption("The sources are identical once comments, %% lines and version metadata are removed."))
            else:
                for index, changes in enumerate(prepared.diffs, 1):
                    card.layout().addWidget(caption(f"{cluster.ids[0]} → {cluster.ids[index]}"))
                    diff = Card()
                    layout = diff.layout()
                    if cluster.kind == "similar":
                        layout = FlowLayout(spacing=SPACE.xs)
                        diff.layout().addLayout(layout)
                    for text, role, outlined in changes:
                        label = text_label(text, "mono")
                        label.setTextFormat(Qt.TextFormat.PlainText)
                        label.setWordWrap(True)
                        if cluster.kind == "similar":
                            label.setMaximumWidth(480)
                            font = label.font()
                            font.setStrikeOut(role == "delete")
                            label.setFont(font)
                        layout.addWidget(label)
                        self._diff_labels.append((label, role, outlined))
                    card.layout().addWidget(diff)
                if cluster.kind == "similar":
                    card.layout().addWidget(caption("Removed words are struck through; added words are green. "
                                                   "Numbers and formulas are outlined."))
            actions = QHBoxLayout()
            actions.addStretch(1)
            dismiss = Button("Different on purpose")
            dismiss.clicked.connect(lambda _checked=False, cluster=cluster: self._dismiss(cluster))
            actions.addWidget(dismiss)
            open_both = Button("Open both")
            open_both.clicked.connect(lambda _checked=False, ids=cluster.ids: self._open(ids))
            actions.addWidget(open_both)
            card.layout().addLayout(actions)
            self._cards.append((cluster, card))
            (sequence_layout if cluster.sequence_deck else self.cards).addWidget(card)
        self.cards.addWidget(self.sequences)
        self._style_diffs()
        self._filter(self._kind)

    def _style_diffs(self) -> None:
        t = self.app.theme.tokens
        for chip in self.chips.values():
            chip.setStyleSheet(f"QPushButton {{ border-radius: {RADIUS_LG}px; }} "
                              f"QPushButton:checked {{ background: {t.inverse}; color: {t.on_inverse}; }}")
        for label, role, outlined in self._diff_labels:
            foreground, background = (t.error_fg, t.error_bg) if role == "delete" else (
                (t.ok_fg, t.ok_bg) if role == "insert" else (t.text, t.bg))
            label.setStyleSheet(f"color: {foreground}; background: {background}; padding: 1px; "
                               f"border: 1px solid {t.warning if outlined else background};")

    def _filter(self, kind: str) -> None:
        self._kind = kind
        counts = dict.fromkeys(CLASSES, 0)
        sequences = 0
        for cluster, card in self._cards:
            active = cluster.fingerprint not in self._dismissed
            if cluster.sequence_deck:
                sequences += active
                card.setVisible(active)
            else:
                counts[cluster.kind] += active
                counts["all"] += active
                card.setVisible(active and kind in ("all", cluster.kind))
        for key, chip in self.chips.items():
            chip.setText(f"{CLASSES[key]} · {counts[key]}")
        self.sequence_toggle.setText(f"Sequences in one deck ({sequences})")
        self.sequences.setVisible(bool(sequences))
        self.status.setText("No similar slide groups." if not counts["all"] else "")
        self.status.setVisible(not counts["all"])
        self.count_changed.emit(counts["all"])

    def _dismiss(self, cluster: Cluster) -> None:
        ctx = self.app.project
        library = library_data.read(ctx)
        ids = library_data.group_ids(ctx)
        library.different_on_purpose.add((frozenset(ids[i] for i in cluster.ids if i in ids),
                                         cluster.fingerprint))
        library_data.write(ctx, library)
        self._dismissed.add(cluster.fingerprint)
        self._filter(self._kind)

    def _open(self, ids) -> None:
        for slide_id in ids:
            path = slide_language.current_path_for_bare_id(self.app.project, slide_id)
            if path is not None:
                self.app.open_slide_editor(path, tab=True)
