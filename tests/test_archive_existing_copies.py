# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Archive collisions preserve both copies until the user chooses which to keep."""
from __future__ import annotations

import pytest

from slidemage import unused_content

OLD = "\\begin{gothamtable}[gap=12pt]{lll}\nrow\n\\end{gothamtable}\n"
NEW = "\\begin{SMTable}[gap=12pt]{lll}\nrow\n\\end{SMTable}\n"


def put(folder, name: str, text: str):
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_bytes(text.encode("utf-8"))
    return path


def test_archiving_over_existing_copies_never_loses_a_differing_one(ctx):
    archive = ctx.slides_dir / "archive"
    same = put(ctx.slides_dir, "s1-EN-X-v1-0-0.tex", NEW)
    older = put(ctx.slides_dir, "s2-EN-X-v1-0-0.tex", NEW)
    differs = put(ctx.slides_dir, "s3-EN-X-v1-0-0.tex", NEW)
    fresh = put(ctx.slides_dir, "s4-EN-X-v1-0-0.tex", NEW)
    put(archive, same.name, NEW)
    put(archive, older.name, OLD)
    put(archive, differs.name, OLD + "an edit of its own\n")
    for comment in ("%% Included in decks: old-deck\n" + NEW, NEW.replace("row", "row % a note")):
        put(archive, fresh.name, comment)
        assert unused_content.archive_copy_state(fresh, archive) == unused_content.COPY_OLDER
    (archive / fresh.name).unlink()
    media_archive = ctx.media_dir / "archive"
    same_media = put(ctx.media_dir, "a.png", "one")
    different_media = put(ctx.media_dir, "b.png", "one")
    put(media_archive, "a.png", "one")
    put(media_archive, "b.png", "another")
    log = []
    assert unused_content.archive_files(ctx, [same_media, different_media],
                                       [same, older, differs, fresh], log.append) == (1, 3)
    assert not same_media.exists()
    assert different_media.read_text() == "one" and (media_archive / "b.png").read_text() == "another"
    assert not same.exists() and not older.exists() and not fresh.exists()
    assert (archive / older.name).read_text(encoding="utf-8") == NEW   # the older archived text was replaced
    assert differs.read_text(encoding="utf-8") == NEW                  # left where it is ...
    assert (archive / differs.name).read_text(encoding="utf-8").endswith("an edit of its own\n")   # ... archive untouched
    assert any("Left s3-EN-X-v1-0-0.tex where it is" in line for line in log)
    assert any("identical copy" in line for line in log) and any("replaced the older copy" in line for line in log)


@pytest.mark.parametrize("folder, name, keep", [
    ("slides", "a-EN-X-v1-0-0.tex", unused_content.KEEP_FILE),
    ("media", "a.png", unused_content.KEEP_ARCHIVED),
])
def test_the_chosen_copy_stays_and_the_other_goes_to_the_recycle_bin(ctx, tmp_path, folder, name, keep):
    old = OLD + "edited\n"
    source = put(ctx.root / folder, name, NEW)
    archived = put(source.parent / "archive", source.name, old)
    expected, discarded = (NEW, old) if keep == unused_content.KEEP_FILE else (old, NEW)
    trash_path = tmp_path / "trash.tex"

    def trash(path):
        path.replace(trash_path)
        return True

    assert unused_content.settle_archived_copy(ctx, source, keep, lambda _: None, trash) is None
    assert not source.exists()
    assert archived.read_text() == expected and trash_path.read_text() == discarded


def test_nothing_changes_when_the_recycle_bin_refuses(ctx):
    archive = ctx.slides_dir / "archive"
    path = put(ctx.slides_dir, "a-EN-X-v1-0-0.tex", NEW)
    put(archive, path.name, OLD)
    for keep in (unused_content.KEEP_FILE, unused_content.KEEP_ARCHIVED):
        problem = unused_content.settle_archived_copy(ctx, path, keep, lambda _line: None, lambda _path: False)
        assert problem.startswith("Couldn't move slides/") and problem.endswith("nothing was changed")
        assert path.read_text(encoding="utf-8") == NEW and (archive / path.name).read_text(encoding="utf-8") == OLD
