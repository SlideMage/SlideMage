# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Translation calls follow their source's first call and inherit its placement options."""
from __future__ import annotations

import pytest
from agent_fakes import FakeWorkspace, call

from slidemage import compiler, preview_target, slide_ids, slide_snapshot
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
    monkeypatch.setattr(preview_target, "render_text", lambda *a, **k: root / "fake.pdf")
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


@pytest.mark.parametrize("tool, source, expected", [
    (add, r"\slide{abc-EN-Hello}", r"\slide{%s}"),
    (create, r"\conditionalslide[instructor,during-course]{abc-EN-Hello}",
     r"\conditionalslide[instructor,during-course]{%s}"),
    (add, r"\slidestep{abc-EN-Hello}[instructor]{2,3}", r"\slidestep{%s}[instructor]{2,3}"),
    (create, r"\omitslide{abc-EN-Hello}", r"\omitslide{%s}"),
    (add, r"\slideversion{abc-EN-Hello}{1-0-0}", r"\slide{%s}"),
], ids=["slide", "conditional", "overlay", "omit", "pinned-version"])
def test_translation_inherits_the_source_call_and_follows_its_first_occurrence(run, root, tool, source, expected):
    second = r"\slide{abd-EN-Second}"
    deck_of(root, "\n".join((source, second, source)) + "\n")
    out = tool(run)
    assert deck_calls(root) == [source, expected % german(root), second, source]
    assert "after abc in test" in out


@pytest.mark.parametrize("source, arguments, message", [
    ("\\slide{abc-EN-Hello}\n", {"after": "abd"}, "after abd in test"),
    ("", {}, "at the end of test"),
], ids=["explicit-after", "source-absent"])
def test_translation_uses_the_explicit_placement_or_appends(run, root, source, arguments, message):
    second = "\\slide{abd-EN-Second}\n"
    deck_of(root, source + second)
    assert message in create(run, **arguments)
    assert deck_calls(root) == (source + second).splitlines() + [f"\\slide{{{german(root)}}}"]


def test_a_new_slide_that_is_no_translation_still_goes_to_the_end(run, root):
    deck_of(root, "\\slide{abc-EN-Hello}\n\\slide{abd-EN-Second}\n")
    run("add_slide", slug="Other", title="Other")
    assert deck_calls(root)[:2] == ["\\slide{abc-EN-Hello}", "\\slide{abd-EN-Second}"] and len(deck_calls(root)) == 3


def test_insert_translation_uses_source_placement_and_call(run, root):
    deck_of(root, "\\conditionalslide[instructor]{abc-EN-Hello}\n\\slide{abd-EN-Second}\n")
    add(run, add_to_deck=False)
    run("insert_slide", slide=german(root))
    assert deck_calls(root) == ["\\conditionalslide[instructor]{abc-EN-Hello}",
                                f"\\conditionalslide[instructor]{{{german(root)}}}", "\\slide{abd-EN-Second}"]
