"""The poll that notices files Claude Code changed (ai/project_watch.py): what it looks at and what it
reports."""
from __future__ import annotations

import os

import pytest

from slidemage.ai import project_watch


def make(root, *names):
    for name in names:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x")


def rel(root, paths):
    return sorted(p.relative_to(root).as_posix() for p in paths)


def test_only_text_files_of_the_project_are_seen(tmp_path):
    make(tmp_path, "slides/a-current.tex", "decks/d.tex", "Slidemaster.bib", "notes.md", "media/pic.png",
         ".build/x.tex", ".slidemage/app_settings.json", "decks/.hidden/x.tex", "pdf/out.tex", ".gitignore.txt",
         "slides/.backups/old.tex", "sub/pdf/ok.tex")
    seen = rel(tmp_path, project_watch.scan(tmp_path))
    assert seen == ["Slidemaster.bib", "decks/d.tex", "notes.md", "slides/a-current.tex", "sub/pdf/ok.tex"]


@pytest.mark.parametrize("replacement", ["longer text", "y"])
def test_diff_names_added_removed_and_modified_files(tmp_path, replacement):
    make(tmp_path, "a.tex", "b.tex", "c.tex")
    before = project_watch.scan(tmp_path)
    assert not project_watch.diff(before, project_watch.scan(tmp_path))
    stamp = (tmp_path / "b.tex").stat().st_mtime_ns
    (tmp_path / "b.tex").write_text(replacement)
    os.utime(tmp_path / "b.tex", ns=(stamp + 5_000_000_000, stamp + 5_000_000_000))
    (tmp_path / "c.tex").unlink()
    make(tmp_path, "d.tex")
    changes = project_watch.diff(before, project_watch.scan(tmp_path))
    assert rel(tmp_path, changes.modified) == ["b.tex"] and rel(tmp_path, changes.removed) == ["c.tex"]
    assert rel(tmp_path, changes.added) == ["d.tex"] and changes
