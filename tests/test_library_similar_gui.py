# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The Similar view's cluster cards and class counts, without a similarity scan."""
from types import SimpleNamespace

from slidemage.preview_requests import RenderService
from slidemage.project import ProjectContext
from slidemage.slide_similarity import Cluster
from slidemage.ui.kit.theme import ThemeManager
from slidemage.ui.kit.widgets import Card
from slidemage.ui.pages.library.page import LibraryPage
from slidemage.ui.workspace.state import WorkspaceState


def test_cluster_cards_and_counts(qapp, tmp_path):
    ctx = ProjectContext.at(tmp_path)
    ctx.slides_dir.mkdir()
    ctx.decks_dir.mkdir()
    for slide_id, body in (("aaa", "Value 10 and $x+1$"), ("bbb", "Value 20 and $x+2$")):
        (ctx.slides_dir / f"{slide_id}-EN-Demo-current.tex").write_text(
            "%% Included in decks: hidden\n\\begin{standardframe}{Demo}\n" + body + "\n\\end{standardframe}",
            encoding="utf-8")
    theme = ThemeManager(dark=False)
    renders = RenderService()
    app = SimpleNamespace(project=ctx, theme=theme, state=WorkspaceState(ctx),
                          centre=SimpleNamespace(preview=SimpleNamespace(_renders=renders)))
    page = LibraryPage(app)
    page.resize(1100, 850)
    page.show()
    view = page.similar_view
    clusters = [Cluster(kind, ["aaa", "bbb"], .62, str(index), sequence)
                for index, (kind, sequence) in enumerate([
                    ("exact", None), ("exact", None), ("same_words", None), ("similar", None),
                    ("similar", ctx.decks_dir / "build-up.tex")])]
    try:
        view.set_clusters(clusters)
        qapp.processEvents()
        cards = [card for card in view.findChildren(Card) if card.property("cluster_kind")]
        assert sum(card.isVisible() for card in cards) == 4
        assert [chip.text() for chip in view.chips.values()] == [
            "All · 4", "Exact copies · 2", "Same words · 1", "Similar text · 1"]
        assert page.similar_row.chip.text() == "4"
        assert view.sequence_toggle.text() == "Sequences in one deck (1)"
        assert not view.sequence_toggle.isChecked()
        view.chips["exact"].click()
        assert sum(card.isVisible() for card in cards) == 2
        # Restyling while the view is open must retain the cards and counts in both themes.
        theme.set_dark(True)
        assert view.chips["all"].text() == "All · 4"
    finally:
        page.shutdown()
        page.close()
        page.deleteLater()
        renders.close()
