# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Slide operations include topic blocks, even when no deck links to the block."""
import pytest

from slidemage import slide_rename, unused_content
from slidemage.project import ProjectContext


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
    (ctx.blocks_dir / "colours.tex").write_text("\\definecolor{accent}{RGB}{1,2,3}\n")
    return ctx


@pytest.mark.parametrize("eol", ["\n", "\r\n"])
@pytest.mark.parametrize("operation, call", [
    *[("slug", call) for call in CALLS],
    *[(operation, call) for operation in ("language", "id", "delete") for call in (CALLS[0], CALLS[6])],
])
def test_slide_operations_update_calls_written_only_in_a_block(project, operation, call, eol):
    block = project.blocks_dir / "Literaturrecherche.tex"
    block.write_bytes(("% Topic\n" + call + "\n").replace("\n", eol).encode())
    body = "\\documentclass{beamer}\n\\begin{document}\n\\slideblock{Literaturrecherche}\n\\end{document}\n"
    for path in (project.decks_dir / "course.tex", project.archive_dir / "old.tex"):
        path.write_text(body)
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
    assert (project.decks_dir / "course.tex").read_text() == body
    assert (project.archive_dir / "old.tex").read_text() == body


@pytest.mark.parametrize("call", CALLS)
@pytest.mark.parametrize("block_name", ["Literaturrecherche", "_topic"])
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
