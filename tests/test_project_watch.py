"""The poll that notices files Claude Code changed (ai/project_watch.py): what it looks at and what it
reports."""
from __future__ import annotations

import os

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


def test_diff_names_added_removed_and_modified_files(tmp_path):
    make(tmp_path, "a.tex", "b.tex", "c.tex")
    before = project_watch.scan(tmp_path)
    assert not project_watch.diff(before, project_watch.scan(tmp_path))
    (tmp_path / "b.tex").write_text("longer text")
    (tmp_path / "c.tex").unlink()
    make(tmp_path, "d.tex")
    changes = project_watch.diff(before, project_watch.scan(tmp_path))
    assert rel(tmp_path, changes.modified) == ["b.tex"] and rel(tmp_path, changes.removed) == ["c.tex"]
    assert rel(tmp_path, changes.added) == ["d.tex"] and changes


def test_a_rewrite_with_the_same_size_is_seen_by_its_time(tmp_path):
    make(tmp_path, "a.tex")
    before = project_watch.scan(tmp_path)
    stamp = (tmp_path / "a.tex").stat().st_mtime_ns
    (tmp_path / "a.tex").write_text("y")
    os.utime(tmp_path / "a.tex", ns=(stamp + 5_000_000_000, stamp + 5_000_000_000))
    assert rel(tmp_path, project_watch.diff(before, project_watch.scan(tmp_path)).modified) == ["a.tex"]


def test_a_folder_that_vanishes_or_is_missing_is_no_error(tmp_path):
    assert project_watch.scan(tmp_path / "missing") == {}
