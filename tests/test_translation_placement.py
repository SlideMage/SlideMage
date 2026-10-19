# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Where the call of a new translation goes in the deck: directly after the first call of its source, called the
way the source is, wherever a translation is made (slide_add.translation_call; the Add slide sheet, the task card
and the batch are in test_add_slide_gui.py and test_claude_tasks_gui.py)."""
from __future__ import annotations

import pytest
from agent_fakes import FakeWorkspace, call

from slidemage import compiler, deck_editor, preview_target, slide_add, slide_ids, slide_snapshot
from slidemage.ai.agent_types import EDIT_AUTO
from slidemage.ai.tools import build_toolbox
from slidemage.ai.workspace import WorkspaceContext
from slidemage.deck_scan import scan_decks
from slidemage.project import ProjectContext

HEAD = "\\documentclass{beamer}\r\n\\begin{document}\r\n\\section{Intro}\r\n"


def deck_of(root, calls: str):
    (root / "decks" / "test.tex").write_bytes((HEAD + calls.replace("\n", "\r\n") + "\\end{document}\r\n").encode())
    return next(d for d in scan_decks(ProjectContext.at(root)) if d.name == "test")


def deck_calls(root) -> list[str]:
    text = (root / "decks" / "test.tex").read_text().replace("\r\n", "\n")
    return [line for line in text.split("\n") if line.startswith("\\")][3:-1]


@pytest.fixture
def run(root, monkeypatch):
    """The tool `name` of a toolbox on the open deck; slides are not rendered."""
    monkeypatch.setattr(preview_target, "render_text", lambda *a, **k: root / "fake.pdf")
    monkeypatch.setattr(slide_snapshot, "page_png", lambda pdf, width: b"\x89PNG")
    # The render service reads the rendered PDF's images (prepare_preview_images) for saved and draft renders alike.
    monkeypatch.setattr(slide_snapshot, "prepare_preview_images", lambda pdf, snapshots, widths: ((b"\x89PNG", b"\x89PNG"), ()))
    (root / "fake.pdf").write_bytes(b"%PDF-1.4")

    def run(name, **arguments):
        deck = next(d for d in scan_decks(ProjectContext.at(root)) if d.name == "test")
        workspace = FakeWorkspace(root, WorkspaceContext(deck=deck))
        box = build_toolbox(workspace, lambda event: None, compiler.CancelToken(), EDIT_AUTO)
        result = box.execute(call(name, **arguments))
        assert not result.is_error, result.text
        return result.text

    run.root = root
    return run


def german(root) -> str:
    return next((root / "slides").glob("*-DE-Hallo-current.tex")).name.removesuffix("-current.tex")


def add(run, **arguments):
    return run("add_slide", slug="Hallo", title="Hallo", language="DE", translation_of="abc", **arguments)


def create(run, **arguments):
    body = slide_ids.slide_body(run.root / "slides" / "abc-EN-Hello-current.tex").replace("\r\n", "\n").replace("Hello", "Hallo")
    return run("create_slide", slug="Hallo", title="Hallo", language="DE", translation_of="abc", deck="test",
               body=body, **arguments)


@pytest.mark.parametrize("tool", [add, create], ids=["add_slide", "create_slide"])
class TestTools:
    def test_goes_directly_after_the_source_not_to_the_end(self, run, root, tool):
        deck_of(root, "\\slide{abc-EN-Hello}\n\\slide{abd-EN-Second}\n")
        out = tool(run)
        assert deck_calls(root) == ["\\slide{abc-EN-Hello}", f"\\slide{{{german(root)}}}", "\\slide{abd-EN-Second}"]
        assert "after abc in test" in out

    def test_a_source_called_several_times_gets_one_call_after_the_first(self, run, root, tool):
        deck_of(root, "\\slide{abc-EN-Hello}\n\\slide{abd-EN-Second}\n\\slide{abc-EN-Hello}\n")
        tool(run)
        assert deck_calls(root) == ["\\slide{abc-EN-Hello}", f"\\slide{{{german(root)}}}", "\\slide{abd-EN-Second}",
                                    "\\slide{abc-EN-Hello}"]

    def test_an_explicit_after_wins(self, run, root, tool):
        deck_of(root, "\\slide{abc-EN-Hello}\n\\slide{abd-EN-Second}\n")
        out = tool(run, after="abd")
        assert deck_calls(root) == ["\\slide{abc-EN-Hello}", "\\slide{abd-EN-Second}", f"\\slide{{{german(root)}}}"]
        assert "after abd in test" in out

    def test_a_source_that_is_not_in_the_deck_goes_to_the_end_as_before(self, run, root, tool):
        deck_of(root, "\\slide{abd-EN-Second}\n")
        out = tool(run)
        assert deck_calls(root) == ["\\slide{abd-EN-Second}", f"\\slide{{{german(root)}}}"]
        assert "at the end of test" in out

    @pytest.mark.parametrize("source_call, expected", [
        ("\\conditionalslide[instructor,during-course]{abc-EN-Hello}", "\\conditionalslide[instructor,during-course]{%s}"),
        ("\\slidestep{abc-EN-Hello}[instructor]{2,3}", "\\slidestep{%s}[instructor]{2,3}"),
        ("\\omitslide{abc-EN-Hello}", "\\omitslide{%s}"),
        ("\\slideversion{abc-EN-Hello}{1-0-0}", "\\slide{%s}"),
    ], ids=["conditional", "overlay", "omit", "pinned-version"])
    def test_the_call_is_made_the_way_deck_language_resolves_the_source(self, run, root, tool, source_call, expected):
        deck_of(root, source_call + "\n\\slide{abd-EN-Second}\n")
        tool(run)
        assert deck_calls(root) == [source_call, expected % german(root), "\\slide{abd-EN-Second}"]


def test_a_new_slide_that_is_no_translation_still_goes_to_the_end(run, root):
    deck_of(root, "\\slide{abc-EN-Hello}\n\\slide{abd-EN-Second}\n")
    run("add_slide", slug="Other", title="Other")
    assert deck_calls(root)[:2] == ["\\slide{abc-EN-Hello}", "\\slide{abd-EN-Second}"] and len(deck_calls(root)) == 3


def test_the_shared_placement_function(root):
    deck = deck_of(root, "\\slide{abd-EN-Second}\n\\conditionalslide[instructor]{abc-EN-Hello}\n\\slide{abc-EN-Hello}\n")
    first = slide_add.translation_call(deck, "abc-EN-Hello")
    assert (first.macro, first.line_start) == ("conditionalslide", deck_editor.parse_slide_calls(deck)[1].line_start)
    assert slide_add.translation_spec(first) == slide_add.CallSpec("conditionalslide", None, ["instructor"], None)
    assert slide_add.translation_call(deck, "abe-EN-Missing") is None
    assert slide_add.translation_call(deck, "abc-DE-Hallo").id == "abc"        # by the bare id, whichever language
