# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
# ruff: noqa: F811 -- the fixtures of test_centre_gui are imported and used by name
"""The Preview's chip for a slide that needs the deck around it."""
from __future__ import annotations

from slidemage import deck_context
from test_centre_gui import FRAME, centre, deck, project, renders, wait_idle  # noqa: F401 -- fixtures


def chips(centre):
    layout = centre.preview._chips
    return [layout.itemAt(i).widget() for i in range(layout.count()) if layout.itemAt(i).widget() is not None]


def texts(centre):
    return [chip.text() for chip in chips(centre)]


def test_a_contents_slide_says_it_needs_the_deck_and_warns_after_a_render_without_it(centre, renders, project):
    (project / "aaa-EN-One-current.tex").write_text(FRAME % "Contents" + "\\tableofcontents\n", encoding="utf-8")
    centre.state.set_focused_slide("aaa")
    assert "Needs the deck around it" in texts(centre)
    centre.preview.render_now()
    wait_idle(centre)
    assert "Rendered without deck context: may differ from the full deck" in texts(centre)
    asked = []
    centre.preview.compile_requested.connect(asked.append)
    warning = next(chip for chip in chips(centre) if chip.text().startswith("Rendered without deck context"))
    warning.clicked.emit()
    assert asked == ["instructor"]
    assert "a table of contents" in warning.toolTip()


def test_the_chip_follows_how_the_page_was_made(centre, renders, project, monkeypatch):
    (project / "aaa-EN-One-current.tex").write_text(FRAME % "Contents" + "\\insertsection\n", encoding="utf-8")
    centre.state.set_focused_slide("aaa")
    for mode, text in ((deck_context.DECK, "In the deck's context"),
                       (deck_context.SKELETON, "Rendered without the deck: may differ from the full deck")):
        monkeypatch.setattr(deck_context, "mode_of", lambda pdf, mode=mode: mode)
        centre.preview.render_now()
        wait_idle(centre)
        assert text in texts(centre)


def test_an_ordinary_slide_has_no_such_chip(centre, renders):
    centre.state.set_focused_slide("aaa")
    centre.preview.render_now()
    wait_idle(centre)
    assert not any("deck" in text.lower() for text in texts(centre))
