"""Two projects side by side in one process: the modules that take a ProjectContext need no
module reload and no patched path globals."""
from __future__ import annotations

from slidemage import app_settings, deck_scan, housekeeping, unused_content
from slidemage.project import ProjectContext

DECK = "\\documentclass{beamer}\n\\begin{document}\n\\slide{aaa-EN-Used}\n\\end{document}\n"


def make(root, deck_name, slides):
    (root / "decks").mkdir(parents=True)
    (root / "slides").mkdir()
    (root / "pdf").mkdir()
    (root / "slide_ids.csv").write_text('"id"\n', encoding="utf-8")
    (root / "decks" / f"{deck_name}.tex").write_text(DECK, encoding="utf-8")
    for name in slides:
        (root / "slides" / f"{name}-current.tex").write_text("slide\n", encoding="utf-8")
    return ProjectContext.at(root)


def test_the_context_names_the_places_inside_one_project(tmp_path):
    ctx = ProjectContext.at(tmp_path)
    assert ctx.slides_dir == tmp_path / "slides" and ctx.archive_dir == tmp_path / "decks" / "archive"
    assert ctx.build_dir == tmp_path / ".build" and ctx.settings_dir == tmp_path / ".slidemage"
    assert ctx.slide_backups_dir == tmp_path / "slides" / ".backups"
    assert ProjectContext(tmp_path, tmp_path / "elsewhere").build_dir == tmp_path / "elsewhere"


def test_settings_decks_and_housekeeping_follow_the_context_they_are_given(tmp_path):
    one = make(tmp_path / "one", "first", ["aaa-EN-Used", "bbb-EN-Spare"])
    two = make(tmp_path / "two", "second", ["aaa-EN-Used"])
    (two.pdf_dir / "a.pdf").write_bytes(b"x")

    app_settings.set(one, "dark_mode", False)
    assert app_settings.get(one, "dark_mode") is False and app_settings.get(two, "dark_mode") is None
    assert (one.settings_dir / "app_settings.json").is_file() and not two.settings_dir.exists()

    assert [d.name for d in deck_scan.scan_decks(one)] == ["first"]
    assert [d.name for d in deck_scan.scan_decks(two)] == ["second"]

    assert [p.name for p in unused_content.find_unused_slides(one)] == ["bbb-EN-Spare-current.tex"]
    assert unused_content.find_unused_slides(two) == []
    assert housekeeping.pdf_files(one) == [] and [p.name for p in housekeeping.pdf_files(two)] == ["a.pdf"]
