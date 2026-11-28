# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The agent's read-only slide and deck readability checks."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from test_agent_tools import LF, SLIDE, Box
from test_readability import body, footer, pdf_of, record_for, slide, title

from slidemage import preview_target
from slidemage.ai.tools import CLAUDE_CODE_PRE_APPROVED, TOOLS
from slidemage.ai.workspace import WorkspaceContext
from slidemage.deck_scan import scan_decks


@pytest.fixture
def box(root):
    return Box(root)


@pytest.fixture
def rendered(box, root, tmp_path, monkeypatch):
    """preview_target.render_text without LaTeX: records what it was asked and draws `draws[-1]`."""
    seen = SimpleNamespace(calls=[], draw=slide(pct=2.8))

    def render_text(target, text, view, language, **kwargs):
        seen.calls.append((target.bare_id, text, view, language))
        if seen.draw is None:
            raise RuntimeError("Render failed\n! Undefined control sequence.\nmore")
        return pdf_of(tmp_path, seen.draw, name=f"draft-{len(seen.calls)}.pdf")

    monkeypatch.setattr(preview_target, "render_text", render_text)
    return seen


def deck_record(box, root, *draws):
    deck = next(d for d in scan_decks(box.ws.project) if d.name == "test")
    pdf = pdf_of(root, *draws, name="test.pdf")
    record_for(box.ws.project, deck, pdf, [deck.path, root / "slides" / "abc-EN-Hello-current.tex"])


def test_the_tool_is_read_only_and_offered_to_claude_code_without_asking():
    assert any(t.spec.name == "check_readability" for t in TOOLS)
    assert [t.spec.name for t in CLAUDE_CODE_PRE_APPROVED].count("check_readability") == 1
    spec = next(t.spec for t in TOOLS if t.spec.name == "check_readability")
    assert set(spec.schema["properties"]) == {"slide", "deck"} and spec.schema["required"] == []


def test_the_open_buffer_with_unsaved_edits_is_what_is_measured_in_the_view_and_language_being_edited(box, rendered):
    box.ws._context = WorkspaceContext(deck=box.ws.context().deck, slide_id="abc", path=box.root / SLIDE,
                                       view="after-course", language="DE")
    box.ws.open(box.root / SLIDE, LF + "% unsaved\n", dirty=True)
    out = box.ok("check_readability")
    assert rendered.calls[0][1] == LF + "% unsaved\n" and rendered.calls[0][2:4] == ("after-course", "EN")      # (the slide is an EN file)
    assert "(editor (unsaved)) as after-course, EN:" in out
    assert "error · body text · 2.8 % of slide height, needs ≥ 3.3 · 3 lines" in out
    assert "enlarge to \\small or larger, or split the slide." in out


def test_an_explicit_slide_by_id_or_path_and_the_refusals(box, rendered):
    assert "abd-EN-Second-current.tex" in box.ok("check_readability", slide="abd")
    assert rendered.calls[-1][0] == "abd"
    assert "abc-EN-Hello-current.tex" in box.ok("check_readability", slide="slides/abc-EN-Hello-current.tex")
    assert "not a slide file" in box.error("check_readability", slide="SlideMage.bib")
    assert "not both" in box.error("check_readability", slide="abc", deck="test")
    rendered.draw = None
    for path in (box.root / SLIDE, box.root / "slides/abd-EN-Second-current.tex"):
        path.write_text(path.read_text() + "\n% edited\n")
    assert box.error("check_readability").endswith("! Undefined control sequence.")
    assert "did not compile, so it was not checked" in box.error("check_readability", slide="abd")


def test_a_clean_slide_says_there_is_nothing_to_report(box, rendered):
    rendered.draw = slide(pct=4.0)
    assert box.ok("check_readability").endswith("1 slide checked · 0 with errors · 0 with warnings. Nothing to report.")


def test_a_stale_deck_pdf_is_reported_and_never_compiled(box, root, rendered):
    out = box.ok("check_readability", deck="open")                                    # no compile on record
    assert "not current: test has not been compiled yet" in out and "Compile the deck first" in out
    deck_record(box, root, lambda page: (footer(page, "abc"), title(page), body(page, 2.8)),
                lambda page: (footer(page, "abd"), title(page), body(page, 4.0)))
    out = box.ok("check_readability", deck="open")
    assert out.startswith("test as instructor, EN: 2 slides checked · 1 with errors · 0 with warnings.")
    assert "abc (abc-EN-Hello-current.tex), page 1:" in out and "abd (" not in out        # only slides with findings
    slide_file = root / "slides" / "abc-EN-Hello-current.tex"
    slide_file.write_bytes(slide_file.read_bytes() + b"% edited\r\n")
    out = box.ok("check_readability", deck="open")
    assert "not current: abc-EN-Hello-current.tex changed since it was compiled" in out
    assert box.ws.compiled == [] and rendered.calls == []                                     # no compile, no render


def test_a_long_deck_answer_names_the_first_slides_with_findings_and_counts_the_rest(box, root):
    pages = [(lambda n: lambda page: (footer(page, f"a{n:02d}"), title(page), body(page, 2.8)))(n) for n in range(45)]
    deck_record(box, root, *pages)
    out = box.ok("check_readability", deck="open")
    assert "45 slides checked · 45 with errors" in out and "... and 5 more slides with findings." in out
