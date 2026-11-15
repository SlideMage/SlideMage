# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The Similar view's cluster cards and class counts, without a similarity scan."""
from pathlib import Path
from threading import get_ident
from types import SimpleNamespace

from slidemage.project import ProjectContext
from slidemage.slide_similarity import Cluster
from slidemage.ui.kit.theme import ThemeManager
from slidemage.ui.kit.widgets import Card
from slidemage.ui.pages.library import page as library_page
from slidemage.ui.pages.library.page import LibraryPage
from slidemage.ui.workspace.state import WorkspaceState


def test_cluster_cards_and_counts(qapp, tmp_path, monkeypatch):
    ctx = ProjectContext.at(tmp_path)
    ctx.slides_dir.mkdir()
    ctx.decks_dir.mkdir()
    for slide_id, body in (("aaa", "Value 10 and $x+1$"), ("bbb", "Value 20 and $x+2$")):
        (ctx.slides_dir / f"{slide_id}-EN-Demo-current.tex").write_text(
            "%% Included in decks: hidden\n\\begin{standardframe}{Demo}\n" + body + "\n\\end{standardframe}",
            encoding="utf-8")
    (ctx.root / "blocks").mkdir()
    (ctx.root / "blocks" / "linked.tex").write_text(r"\slide{bbb-EN-Demo}")
    (ctx.decks_dir / "course.tex").write_text(
        "\\documentclass{beamer}\n\\begin{document}\n% \\slide{aaa-EN-Demo}\n\\input{blocks/linked}\n\\end{document}")
    theme = ThemeManager(dark=False)
    app = SimpleNamespace(project=ctx, theme=theme, state=WorkspaceState(ctx),
                          background=SimpleNamespace(renderer=None))
    page = LibraryPage(app)
    page.similar_row.clicked.emit()  # Select explicitly; Library now opens on Pool or Suggestions.
    page.resize(1100, 850)
    page.show()
    view = page.similar_view
    clusters = [Cluster(kind, ["aaa", "bbb", "gone"], .62, str(index), sequence)
                for index, (kind, sequence) in enumerate([
                    ("exact", None), ("exact", None), ("same_words", None), ("similar", None),
                    ("similar", ctx.decks_dir / "build-up.tex")])]
    gui_thread = get_ident()
    read_text = Path.read_text

    def worker_read(path, *args, **kwargs):
        assert get_ident() != gui_thread
        if path.name.startswith("gone-"):
            raise OSError("slide disappeared")
        return read_text(path, *args, **kwargs)

    def scan(ctx, *, usage):
        assert get_ident() != gui_thread
        assert "aaa" not in usage
        assert [d.name for d in usage["bbb"]] == ["course", "linked"]
        return clusters

    (ctx.slides_dir / "gone-EN-Demo-current.tex").touch()
    monkeypatch.setattr(Path, "read_text", worker_read)
    monkeypatch.setattr(library_page, "find_clusters", scan)
    try:
        page.ensure_loaded()
        assert page._scan.wait(5000)
        qapp.processEvents()
        assert page.status.text() != "Finding similar slides…"
        assert not page.status.text().startswith("Could not"), page.status.text()
        cards = [card for card in view.findChildren(Card) if card.property("cluster_kind")]
        assert sum(card.isVisible() for card in cards) == 4
        assert [chip.text() for chip in view.chips.values()] == [
            "All · 4", "Exact copies · 2", "Same words · 1", "Similar text · 1"]
        assert page.similar_row.chip.text() == "4"
        assert all(c.ids == ["aaa", "bbb"] for c, _ in view._cards)
        assert not page.status.isVisible()
        assert view.sequence_toggle.text() == "Sequences in one deck (1)"
        assert not view.sequence_toggle.isChecked()
        view.chips["exact"].click()
        assert sum(card.isVisible() for card in cards) == 2
        # Restyling while the view is open must retain the cards and counts in both themes.
        theme.set_dark(True)
        assert view.chips["all"].text() == "All · 4"
        page._on_loaded(None, OSError("scan failed"))
        assert page.status.isVisible()
        assert page.status.text() == "Could not find similar slides: scan failed"
    finally:
        page.shutdown()
        page.close()
        page.deleteLater()
