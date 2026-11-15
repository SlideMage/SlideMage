# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Approved exact-copy actions, using real project files offscreen."""
import json
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QCheckBox, QDialog, QLabel, QMessageBox

from slidemage import slide_similarity
from slidemage.project import ProjectContext
from slidemage.ui.kit.theme import ThemeManager
from slidemage.ui.kit.widgets import Button, ModalSheet
from slidemage.ui.pages.library.similar import SimilarView, prepare_clusters


@pytest.fixture
def copies(tmp_path):
    ctx = ProjectContext.at(tmp_path)
    for folder in (ctx.slides_dir, ctx.decks_dir, ctx.blocks_dir, ctx.settings_dir):
        folder.mkdir()
    (ctx.settings_dir / "project.json").write_text(json.dumps({
        "languages": {"main": "en", "secondary": ["de"]}}))
    for slide_id in ("aaa", "bbb"):
        (ctx.slides_dir / f"{slide_id}-EN-Demo-current.tex").write_text(
            r"\begin{standardframe}{Demo} An exact copy with distinctive words.\end{standardframe}")
    (ctx.decks_dir / "keep.tex").write_text("\\documentclass{beamer}\n\\begin{document}\n"
                                             "\\slide{aaa-EN-Demo}\n\\end{document}\n")
    app = SimpleNamespace(project=ctx, theme=ThemeManager(dark=False),
                          state=SimpleNamespace(language="EN"), background=SimpleNamespace(renderer=None),
                          slide_list=SimpleNamespace(_undo={}, _undo_order=[]),
                          refresh_open_deck_editors=lambda: None)
    view = SimilarView(app)
    usage = slide_similarity.usage_index(ctx)
    view.set_clusters(prepare_clusters(ctx, slide_similarity.find_clusters(ctx, usage=usage), usage, None, "EN"))
    yield ctx, view
    if view._work is not None:
        view._work.stop(wait_ms=5000)
    view.deleteLater()


def test_archive_unused_copy(qapp, copies, monkeypatch):
    ctx, view = copies
    approvals = []
    monkeypatch.setattr(QMessageBox, "question", lambda *args: approvals.append(args[2]) or QMessageBox.Yes)
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: pytest.fail(args[2]))
    button = next(b for b in view.findChildren(Button) if b.text() == "Archive the unused copy")
    button.click()
    assert view._work.wait(5000)
    qapp.processEvents()
    assert len(approvals) == 1
    assert (ctx.slides_dir / "archive" / "bbb-EN-Demo-current.tex").is_file()
    assert not (ctx.slides_dir / "bbb-EN-Demo-current.tex").exists()
    assert slide_similarity.find_clusters(ctx) == []
    assert view._cards == []
    assert view.chips["all"].text() == "All · 0"


def test_replace_unpinned_calls_and_refuse_translation(qapp, copies, monkeypatch):
    ctx, view = copies
    deck = ctx.decks_dir / "replace.tex"
    deck.write_text("\\slide{bbb-EN-Demo}\n\\slideversion{bbb-EN-Demo}{1-0-0}\n"
                    "\\omitslideversion{bbb-EN-Demo}{1-0-0}\n% \\slide{bbb-EN-Demo}\n"
                    "\\begin{verbatim}\n\\slide{bbb-EN-Demo}\n\\end{verbatim}\n")
    block = ctx.blocks_dir / "topic.tex"
    block.write_text("\\conditionalslide[instructor]{bbb-EN-Demo}\n"
                     "\\slidestep{bbb-EN-Demo}[instructor]{1,2}\n")
    skipped = ctx.decks_dir / "skip.tex"
    skipped.write_text("\\omitslide{bbb-EN-Demo}\n")
    snapshots = {p: p.read_text() for p in (deck, block, skipped)}
    view.app.slide_list._undo = {p: [snapshots[p]] for p in snapshots}
    view.app.slide_list._undo_order = [(None, p) for p in snapshots]
    usage = slide_similarity.usage_index(ctx)
    view.set_clusters(prepare_clusters(ctx, slide_similarity.find_clusters(ctx, usage=usage), usage, None, "EN"))
    approvals, warnings = [], []

    def approve(sheet):
        checks = sheet.findChildren(QCheckBox)
        assert {c.text() for c in checks} == {"decks/replace.tex", "decks/skip.tex", "blocks/topic.tex"}
        assert all(c.isChecked() for c in checks)
        assert any("cannot be undone" in label.text() for label in sheet.findChildren(QLabel))
        next(c for c in checks if c.text() == "decks/skip.tex").setChecked(False)
        approvals.append(sheet)
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(ModalSheet, "exec", approve)
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args[2]))
    next(b for b in view.findChildren(Button) if b.text() == "Use this one instead").click()
    assert view._work.wait(5000)
    qapp.processEvents()  # Present the one approval, then start the write.
    assert view._work.wait(5000)
    qapp.processEvents()
    assert len(approvals) == 1 and warnings == []
    assert deck.read_text() == snapshots[deck].replace("\\slide{bbb-EN-Demo}", "\\slide{aaa-EN-Demo}", 1)
    assert block.read_text() == snapshots[block].replace("bbb-EN-Demo", "aaa-EN-Demo")
    assert skipped.read_text() == snapshots[skipped]
    assert view.app.slide_list._undo == {skipped: [snapshots[skipped]]}
    assert view.app.slide_list._undo_order == [(None, skipped)]
    # Adding a translation after the approval snapshot must also prevent every write.
    files = slide_similarity.replacement_files(ctx, "aaa", "bbb")
    translation = ctx.slides_dir / "ccc-DE-Demo-current.tex"
    translation.write_text("%% Translation of: bbb-EN-Demo\nEine Übersetzung.")
    before = {p: p.read_bytes() for p in (deck, block, skipped)}
    with pytest.raises(ValueError, match="translation.*DE"):
        slide_similarity.replace_exact_copy(ctx, "aaa", "bbb", files)
    assert {p: p.read_bytes() for p in before} == before
    # The view reports the refusal without asking for a second approval.
    view._replace("aaa", "bbb")
    assert view._work.wait(5000)
    qapp.processEvents()
    assert len(approvals) == 1
    assert "translation" in warnings[-1]
    translation.unlink()
    # ID-bearing core metadata is not plugin data. Unknown plugin formats are refused.
    (ctx.settings_dir / "library.json").write_text(json.dumps({"topics": {"bbb": ["Demo"]}}))
    plugin = ctx.settings_dir / "exam-forge" / "questions.json"
    plugin.parent.mkdir()
    alt = ctx.media_dir / "alt-text.json"
    alt.parent.mkdir()
    for path, data, reason in (
            (alt, {"images": {}, "slides": {"bbb": {"summary": "A slide description"}}}, "alt-text"),
            (alt, {"images": {"media/a.png": {"used_on": {"bbb": {"takeaway": {"en": "Detail"}}}}}}, "alt-text"),
            (plugin, {"sources": [{"slide_id": "bbb"}]}, "plugin data")):
        path.write_text(json.dumps(data))
        with pytest.raises(ValueError, match=reason):
            slide_similarity.replace_exact_copy(ctx, "aaa", "bbb", files)
        assert {p: p.read_bytes() for p in before} == before
        path.unlink()
