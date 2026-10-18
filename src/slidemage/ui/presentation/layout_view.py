"""A layout profile turned into widgets (plan 4.10): nested splitters, with the info strip a fixed-height bar."""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QBoxLayout, QHBoxLayout, QSplitter, QVBoxLayout, QWidget

from ...presentation.layout import Leaf, Node, Profile

STRIP_HEIGHT = 46


def build_layout(profile: Profile, factory: Callable[[str], QWidget]) -> QWidget:
    """`factory(name)` makes the widget of one element."""
    return _build(profile.tree, factory)


def _strip(leaf: Leaf, factory: Callable[[str], QWidget]) -> QWidget:
    strip = QWidget()
    strip.setFixedHeight(STRIP_HEIGHT)
    row = QHBoxLayout(strip)
    row.setContentsMargins(8, 2, 8, 2)
    for position, name in enumerate(leaf.elements):
        if position:
            row.addStretch(1)
        row.addWidget(factory(name))
    return strip


def _build(node: Node, factory: Callable[[str], QWidget]) -> QWidget:
    if isinstance(node, Leaf):
        return _strip(node, factory) if node.is_strip else factory(node.elements[0])
    strips = [isinstance(child, Leaf) and child.is_strip for child in (node.a, node.b)]
    first, second = _build(node.a, factory), _build(node.b, factory)
    if any(strips):
        box = QWidget()
        layout = QVBoxLayout(box) if node.orient == "v" else QHBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        add(layout, first, 0 if strips[0] else 1)
        add(layout, second, 0 if strips[1] else 1)
        return box
    splitter = QSplitter(Qt.Orientation.Horizontal if node.orient == "h" else Qt.Orientation.Vertical)
    splitter.setChildrenCollapsible(False)
    splitter.addWidget(first)
    splitter.addWidget(second)
    splitter.setSizes([int(node.ratio * 10000), int((1 - node.ratio) * 10000)])
    return splitter


def add(layout: QBoxLayout, widget: QWidget, stretch: int) -> None:
    layout.addWidget(widget, stretch)
