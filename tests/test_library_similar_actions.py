# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Approved exact-copy actions, using real project files offscreen."""
import json
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QCheckBox, QDialog, QLabel, QMessageBox

from slidemage import fileio, project, slide_similarity, slide_usage
from slidemage.project import ProjectContext
from slidemage.ui.kit.theme import ThemeManager
from slidemage.ui.kit.widgets import Button, ModalSheet
from slidemage.ui.pages.library.similar import SimilarView, prepare_clusters


@pytest.fixture
def copies(tmp_path, monkeypatch):
    monkeypatch.setattr(project, "config_dir", lambda: tmp_path / "config")
    monkeypatch.setattr(project, "cache_dir", lambda: tmp_path / "cache")
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
    forgotten = []
    app = SimpleNamespace(project=ctx, theme=ThemeManager(dark=False),
                          state=SimpleNamespace(language="EN"), background=SimpleNamespace(renderer=None),
                          slide_list=SimpleNamespace(forgotten=forgotten, forget_undo=lambda paths: forgotten.append(set(paths))),
                          refresh_open_deck_editors=lambda: None, after_deck_edit=lambda *args: None)
    view = SimilarView(app)
    usage = slide_usage.decks_by(slide_usage.deck_calls(ctx), "id")
    view.set_clusters(prepare_clusters(ctx, slide_similarity.find_clusters(ctx, usage=usage), usage, {}, None, "EN"))
    yield ctx, view
    if view._work is not None:
        view._work.stop(wait_ms=5000)
    view.deleteLater()


def test_archive_unused_copy(qapp, copies, monkeypatch):
    ctx, view = copies
    approvals, refreshes = [], []
    view.changed.connect(lambda: refreshes.append(True))
    monkeypatch.setattr(QMessageBox, "question", lambda *args: approvals.append(args[2]) or QMessageBox.Yes)
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: pytest.fail(args[2]))
    button = next(b for b in view.findChildren(Button) if b.text() == "Archive the unused copy")
    button.click()
    assert view._work.wait(5000)
    qapp.processEvents()
    assert len(approvals) == 1 and refreshes == [True]
    assert (ctx.slides_dir / "archive" / "bbb-EN-Demo-current.tex").is_file()
    assert not (ctx.slides_dir / "bbb-EN-Demo-current.tex").exists()
    assert slide_similarity.find_clusters(ctx) == []
    (ctx.slides_dir / "bbb-EN-Demo-current.tex").write_bytes(
        (ctx.slides_dir / "aaa-EN-Demo-current.tex").read_bytes())
    (ctx.decks_dir / "keep.tex").unlink()
    view.set_clusters(prepare_clusters(ctx, slide_similarity.find_clusters(ctx), {}, {}, None, "EN"))
    assert not [b for b in view._cards[0][1].findChildren(Button) if b.text() == "Archive the unused copy"]


def test_replace_unpinned_calls_and_refuse_translation(qapp, copies, monkeypatch):
    ctx, view = copies
    deck = ctx.decks_dir / "replace.tex"
    deck.write_text("\\documentclass{beamer}\n\\slide{bbb-EN-Demo}\n\\slideversion{bbb-EN-Demo}{1-0-0}\n"
                    "\\omitslideversion{bbb-EN-Demo}{1-0-0}\n% \\slide{bbb-EN-Demo}\n"
                    "\\begin{verbatim}\n\\slide{bbb-EN-Demo}\n\\end{verbatim}\n")
    block = ctx.blocks_dir / "topic.tex"
    block.write_text("\\conditionalslide[instructor]{bbb-EN-Demo}\n"
                     "\\slidestep{bbb-EN-Demo}[instructor]{1,2}\n")
    skipped = ctx.decks_dir / "skip.tex"
    skipped.write_text("\\omitslide{bbb-EN-Demo}\n")
    snapshots = {p: p.read_text() for p in (deck, block, skipped)}
    usage = slide_usage.decks_by(slide_usage.deck_calls(ctx), "id")
    view.set_clusters(prepare_clusters(ctx, slide_similarity.find_clusters(ctx, usage=usage), usage, {}, None, "EN"))
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
    assert view.app.slide_list.forgotten == [{deck, block}]
    # A translation added after the approval must refuse the next replacement, through the UI.
    translation = ctx.slides_dir / "ccc-DE-Demo-current.tex"
    translation.write_text("%% Translation of: bbb-EN-Demo\nEine Übersetzung.")
    view._replace("aaa", "bbb")
    assert view._work.wait(5000)
    qapp.processEvents()
    assert len(approvals) == 1
    assert "translation" in warnings[-1]


@pytest.mark.parametrize("trigger, reason", [
    ("translation", "translation.*DE"),
    ("alt-text summary", "alt-text"),
    ("alt-text takeaway", "alt-text"),
    ("plugin data", "plugin data"),
])
def test_replacement_refuses_translations_and_unregistered_data(qapp, copies, trigger, reason):
    ctx, _view = copies
    deck, block, skipped = ctx.decks_dir / "replace.tex", ctx.blocks_dir / "topic.tex", ctx.decks_dir / "skip.tex"
    deck.write_text("\\slide{bbb-EN-Demo}\n")
    block.write_text("\\slidestep{bbb-EN-Demo}[instructor]{1,2}\n")
    skipped.write_text("\\omitslide{bbb-EN-Demo}\n")
    before = {p: p.read_bytes() for p in (deck, block, skipped)}
    files = slide_similarity.replacement_files(ctx, "aaa", "bbb")
    # ID-bearing core metadata is not plugin data.
    (ctx.settings_dir / "library.json").write_text(json.dumps({"topics": {"bbb": ["Demo"]}}))
    alt = ctx.media_dir / "alt-text.json"
    alt.parent.mkdir()
    plugin = ctx.settings_dir / "exam-forge" / "questions.json"
    plugin.parent.mkdir()
    path, data = {
        "translation": (ctx.slides_dir / "ccc-DE-Demo-current.tex", "%% Translation of: bbb-EN-Demo\nEine Übersetzung."),
        "alt-text summary": (alt, {"images": {}, "slides": {"bbb": {"summary": "A slide description"}}}),
        "alt-text takeaway": (alt, {"images": {"media/a.png": {"used_on": {"bbb": {"takeaway": {"en": "Detail"}}}}}}),
        "plugin data": (plugin, {"sources": [{"slide_id": "bbb"}]}),
    }[trigger]
    if isinstance(data, str):
        path.write_text(data, encoding="utf-8")
    else:
        path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match=reason):
        slide_similarity.replace_exact_copy(ctx, "aaa", "bbb", files)
    assert {p: p.read_bytes() for p in before} == before


def test_replacement_restores_prior_writes(qapp, copies, monkeypatch):
    ctx, _view = copies
    block = ctx.blocks_dir / "Topic.tex"
    deck = ctx.decks_dir / "replace.tex"
    for path in (block, deck):
        path.write_text("\\slide{bbb-EN-Demo}\n")
    snapshots = {p: p.read_bytes() for p in (block, deck)}
    files = slide_similarity.replacement_files(ctx, "aaa", "bbb")
    write = fileio.write_text_exact

    def fail_deck(path, *args, **kwargs):
        if path == deck:
            raise OSError("disk full")
        return write(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(fileio, "write_text_exact", fail_deck)
        with pytest.raises(OSError, match="Restored all files"):
            slide_similarity.replace_exact_copy(ctx, "aaa", "bbb", files)
    assert {p: p.read_bytes() for p in snapshots} == snapshots
