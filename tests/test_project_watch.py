# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The polling scan for project changes made by external tools."""
from __future__ import annotations

import os

from slidemage.ai import project_watch


def make(root, *names, text="x"):
    for name in names:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)


def rel(root, paths):
    return sorted(p.relative_to(root).as_posix() for p in paths)


def test_the_scan_sees_project_text_and_ignores_generated_wrappers(tmp_path):
    from slidemage.deck_scan import scan_dir

    make(tmp_path, "decks/real.tex", text=r"\documentclass{beamer}")
    make(tmp_path, "_notes.md", "slides/live-current.tex", "SlideMage.bib", "sub/pdf/ok.tex",
         "media/pic.png", ".build/x.tex", ".slidemage/app_settings.json", "decks/.hidden/x.tex",
         "pdf/out.tex", ".gitignore.txt", "slides/.backups/old.tex")
    before = project_watch.scan(tmp_path)
    assert rel(tmp_path, before) == ["SlideMage.bib", "_notes.md", "decks/real.tex",
                                    "slides/live-current.tex", "sub/pdf/ok.tex"]
    wrappers = ("decks/_slidemage_preview-abc.tex", "decks/archive/_slidemage_preview-def.tex",
                "_slidemage_preview-ghi.tex", "decks/_compile-wrapper.tex")
    make(tmp_path, *wrappers, text=r"\documentclass{beamer}")
    assert not project_watch.diff(before, project_watch.scan(tmp_path))
    assert [d.name for d in scan_dir(tmp_path / "decks", False)] == ["real"]
    assert scan_dir(tmp_path / "decks/archive", True) == []
    for name in wrappers:
        (tmp_path / name).write_text("modified wrapper")
    assert project_watch.scan(tmp_path) == before
    for name in wrappers:
        (tmp_path / name).unlink()
    assert not project_watch.diff(before, project_watch.scan(tmp_path))


def test_diff_names_added_removed_and_modified_files(tmp_path):
    make(tmp_path, "a.tex", "b.tex", "c.tex")
    before = project_watch.scan(tmp_path)
    assert not project_watch.diff(before, project_watch.scan(tmp_path))
    stamp = (tmp_path / "b.tex").stat().st_mtime_ns
    (tmp_path / "b.tex").write_text("y")
    os.utime(tmp_path / "b.tex", ns=(stamp + 5_000_000_000, stamp + 5_000_000_000))
    (tmp_path / "c.tex").unlink()
    make(tmp_path, "d.tex")
    changes = project_watch.diff(before, project_watch.scan(tmp_path))
    assert rel(tmp_path, changes.modified) == ["b.tex"] and rel(tmp_path, changes.removed) == ["c.tex"]
    assert rel(tmp_path, changes.added) == ["d.tex"] and changes
