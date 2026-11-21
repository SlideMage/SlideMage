# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Archiving a file whose name archive/ holds already: identical copies are removed from their folder, an archived
text that differs only in SM names and comments is replaced, anything else is left where it is and said so."""
from __future__ import annotations

from slidemage import unused_content

OLD = "\\begin{gothamtable}[gap=12pt]{lll}\nrow\n\\end{gothamtable}\n"
NEW = "\\begin{SMTable}[gap=12pt]{lll}\nrow\n\\end{SMTable}\n"


def put(folder, name: str, text: str):
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_bytes(text.encode("utf-8"))
    return path


def test_the_state_of_the_copy_in_archive_tells_the_three_cases_apart(ctx):
    archive = ctx.slides_dir / "archive"
    source = put(ctx.slides_dir, "a-EN-X-v1-0-0.tex", NEW)
    assert unused_content.archive_copy_state(source, archive) is None
    put(archive, source.name, NEW)
    assert unused_content.archive_copy_state(source, archive) == unused_content.COPY_SAME
    put(archive, source.name, OLD)
    assert unused_content.archive_copy_state(source, archive) == unused_content.COPY_OLDER
    put(archive, source.name, "%% Included in decks: old-deck\n" + NEW)           # only a comment differs
    assert unused_content.archive_copy_state(source, archive) == unused_content.COPY_OLDER
    put(archive, source.name, NEW.replace("row", "row % a note"))                  # a trailing comment, not code
    assert unused_content.archive_copy_state(source, archive) == unused_content.COPY_OLDER
    put(archive, source.name, NEW.replace("row", "row \\par"))                     # code differs
    assert unused_content.archive_copy_state(source, archive) == unused_content.COPY_DIFFERS
    put(archive, source.name, OLD + "an edit of its own\n")
    assert unused_content.archive_copy_state(source, archive) == unused_content.COPY_DIFFERS


def test_archiving_over_existing_copies_never_loses_a_differing_one(ctx):
    archive = ctx.slides_dir / "archive"
    same = put(ctx.slides_dir, "s1-EN-X-v1-0-0.tex", NEW)
    older = put(ctx.slides_dir, "s2-EN-X-v1-0-0.tex", NEW)
    differs = put(ctx.slides_dir, "s3-EN-X-v1-0-0.tex", NEW)
    fresh = put(ctx.slides_dir, "s4-EN-X-v1-0-0.tex", NEW)
    put(archive, same.name, NEW)
    put(archive, older.name, OLD)
    put(archive, differs.name, OLD + "an edit of its own\n")
    log: list[str] = []
    moved = unused_content.archive_files(ctx, [], [same, older, differs, fresh], log.append)
    assert moved == (0, 3)                                           # the differing one is not counted
    assert not same.exists() and not older.exists() and not fresh.exists()
    assert (archive / older.name).read_text(encoding="utf-8") == NEW   # the older archived text was replaced
    assert differs.read_text(encoding="utf-8") == NEW                  # left where it is ...
    assert (archive / differs.name).read_text(encoding="utf-8").endswith("an edit of its own\n")   # ... archive untouched
    assert any("Left s3-EN-X-v1-0-0.tex where it is" in line for line in log)
    assert any("identical copy" in line for line in log) and any("replaced the older copy" in line for line in log)


def test_media_with_an_identical_copy_is_removed_and_a_different_one_stays(ctx):
    archive = ctx.media_dir / "archive"
    same = put(ctx.media_dir, "a.png", "one")
    other = put(ctx.media_dir, "b.png", "one")
    put(archive, "a.png", "one")
    put(archive, "b.png", "another")
    assert unused_content.archive_files(ctx, [same, other], [], lambda _line: None) == (1, 0)
    assert not same.exists() and other.read_text() == "one" and (archive / "b.png").read_text() == "another"
