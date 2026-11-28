# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Slide operations include topic blocks, even when no deck links to the block."""
import pytest

from slidemage import slide_rename, unused_content
from slidemage.project import ProjectContext

DECK = "\\documentclass{beamer}\n\\begin{document}\n\\slideblock{Literaturrecherche}\n\\end{document}\n"


CALLS = [
    r"\slide{abc-EN-Title}",
    r"\slideversion{abc-EN-Title}{1-0-0}",
    r"\omitslide{abc-EN-Title}",
    r"\omitslideversion{abc-EN-Title}{1-0-0}",
    r"\slidefinal{abc-EN-Title}",
    r"\conditionalslide[instructor]{abc-EN-Title}",
    r"\slidestep{abc-EN-Title}[instructor]{1-2}",
]


@pytest.fixture
def project(tmp_path):
    ctx = ProjectContext.at(tmp_path)
    ctx.slide_ids_csv.write_text('"id"\n"abc"\n')
    ctx.slides_dir.mkdir()
    ctx.archive_dir.mkdir(parents=True)
    ctx.blocks_dir.mkdir()
    for suffix in ("current", "v1-0-0"):
        (ctx.slides_dir / f"abc-EN-Title-{suffix}.tex").write_text("\\setSlideVersion{1-0-0}\nTitle\n")
    (ctx.slides_dir / "zzz-EN-Spare-current.tex").write_text("Spare\n")
    (ctx.blocks_dir / "colors.tex").write_text("\\definecolor{accent}{RGB}{1,2,3}\n")
    return ctx


@pytest.mark.parametrize("operation, call, eol", [
    *[("slug", call, "\n") for call in CALLS[1:]], ("slug", CALLS[0], "\r\n"),
    ("language", CALLS[0], "\n"), ("id", CALLS[6], "\n"), ("delete", CALLS[6], "\n"),
])
def test_slide_operations_update_calls_written_only_in_a_block(project, operation, call, eol):
    block = project.blocks_dir / "Literaturrecherche.tex"
    block.write_bytes(("% Topic\n" + call + "\n").replace("\n", eol).encode())
    decks = [project.decks_dir / "course.tex", project.archive_dir / "old.tex"]
    for deck in decks:
        deck.write_text(DECK)
    assert slide_rename.count_references(project, "abc-EN-Title") == 1
    assert slide_rename.deck_names_referencing(project, "abc-EN-Title") == [block.stem]

    if operation == "delete":
        assert slide_rename.delete_slide_id(project, "abc-EN-Title") == {
            "files_removed": 2, "deck_references_removed": 1}
        expected = "% Topic\n"
        assert not list(project.slides_dir.glob("abc-*.tex"))
    else:
        if operation == "slug":
            renamed = slide_rename.rename_slide_slug(project, "abc-EN-Title", "Renamed")
        elif operation == "language":
            renamed = slide_rename.set_slide_language(project, "abc-EN-Title", "DE")
        else:
            renamed = slide_rename.rename_slide_id(project, "abc", "xyz")["abc-EN-Title"]
        expected = "% Topic\n" + call.replace("abc-EN-Title", renamed) + "\n"
        current = project.slides_dir / f"{renamed}-current.tex"
        assert "%% Included in decks: course, old" in current.read_text()
        assert "\\setSlideVersion{1-0-0}\n" in current.read_text()
        assert (project.slides_dir / f"{renamed}-v1-0-0.tex").is_file()
    assert block.read_bytes() == expected.replace("\n", eol).encode()
    assert all(deck.read_text() == DECK for deck in decks)


@pytest.mark.parametrize("call, block_name", [
    (CALLS[0], "Literaturrecherche"), *[(call, "_topic") for call in CALLS[1:]],
])
def test_slide_called_only_in_a_detached_block_is_used(project, call, block_name):
    (project.blocks_dir / f"{block_name}.tex").write_text(call + "\n")
    (project.blocks_dir / "comments.tex").write_text("% \\slide{zzz-EN-Spare}\n")
    (project.blocks_dir / "verbatim.tex").write_text("\\begin{verbatim}\n\\slide{zzz-EN-Spare}\n\\end{verbatim}\n")
    expected_unused = {"zzz-EN-Spare-current.tex"}
    if "slideversion" in call:
        expected_unused.add("abc-EN-Title-current.tex")
    else:
        expected_unused.add("abc-EN-Title-v1-0-0.tex")
    assert {p.name for p in unused_content.find_unused_slides(project)} == expected_unused
