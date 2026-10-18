r"""Slides that need the rest of the deck: finding them, and the deck's sections and agenda records around them."""
from __future__ import annotations

import pytest

from slidemage import deck_context, deck_scan, partial_compile, preview_target, slide_preview


@pytest.mark.parametrize("text, expected", [
    ("\\tableofcontents[hideallsubsections]", ("contents",)),
    ("\\SMDeckAgenda \\tableofcontents", ("contents",)),
    ("\\SMChapterAgenda[0.8\\linewidth]", ("contents",)),
    ("\\begin{sectionframe}{A}{B}\\end{sectionframe}", ("section",)),
    ("Section: \\insertsection, \\insertsectionhead", ("section",)),
    ("\\insertframenumber of \\inserttotalframenumber", ("numbers",)),
    ("see slide \\ref{x} and \\hyperlink{abc}{there}", ("references",)),
    ("\\tableofcontents \\insertsection \\insertpagenumber \\pageref{x}",
     ("contents", "section", "numbers", "references")),
    ("\\begin{standardframe}{Plain}\n\\pause\\only<2>{x}\\cite{key}\n\\end{standardframe}", ()),
    ("% \\tableofcontents is commented out\nplain", ()),
    ("\\begin{verbatim}\\tableofcontents\\end{verbatim}", ()),
    ("\\insertsectionnumberish", ()),
])
def test_reasons_come_from_the_slides_own_text(text, expected):
    assert deck_context.reasons(text) == expected


def test_reasons_of_a_file_are_remembered_until_it_changes(tmp_path):
    path = tmp_path / "a.tex"
    path.write_text("\\tableofcontents", encoding="utf-8")
    assert deck_context.reasons_for_file(path) == ("contents",)
    path.write_text("nothing", encoding="utf-8")
    import os
    os.utime(path, ns=(1, path.stat().st_mtime_ns + 5_000_000_000))
    assert deck_context.reasons_for_file(path) == ()
    assert deck_context.reasons_for_file(tmp_path / "missing.tex") == ()
    assert "section" in deck_context.describe(("contents", "section"))


@pytest.mark.parametrize("text, title", [
    ("\\begin{standardframe}{Hello World}\nx\n\\end{standardframe}", "Hello World"),
    ("\\begin{standardframe}[t]{With option}\nx", "With option"),
    ("\\begin{sideimageframe}[c]{Side title}{media/pic.png}", "Side title"),
    ("\\begin{frame}<2->[t]{Raw}", "Raw"),
    ("\\begin{frame}\n\\frametitle{Late title}\n", "Late title"),
    ("\\SMAgendaTitle{For the agenda}\n\\begin{quoteframe}{Not this}", "For the agenda"),
    ("\\begin{standardframe}{Real}\n\\SMAgendaTitle{Too late}", "Real"),
    ("\\begin{standardframe}{A \\textbf{bold} {nested} title}\n", "A \\textbf{bold} {nested} title"),
    ("\\begin{standardframe}{}\nno title\n", None),
    ("% \\begin{standardframe}{Commented}\n\\begin{standardframe}{Real one}", "Real one"),
    ("just text", None),
])
def test_frame_title(text, title):
    assert deck_context.frame_title(text) == title


def test_a_title_made_of_a_macro_the_slide_defines_is_recognised():
    text = "\\newcommand{\\mytitle}{X}\n\\begin{standardframe}{\\mytitle}\n"
    assert deck_context._defines_macros_of("\\mytitle", text)
    assert not deck_context._defines_macros_of("\\textbf{x}", text)


def test_titles_of_the_last_compile_come_from_its_aux(tmp_path):
    (tmp_path / "course-instructor.aux").write_text(
        "\\relax\n\\SMAgendaEntryTitle{1AA}{First \\textbf {title}}\n\\SMAgendaEntryTitle{1bb}{Second}\n"
        "\\SMAgendaEntryTitle{1aa}{ignored: first one wins}\n", encoding="utf-8")
    assert deck_context.aux_titles(tmp_path, "course-instructor") == {"1aa": "First \\textbf {title}", "1bb": "Second"}
    assert deck_context.aux_titles(tmp_path, "none") == {}


DECK = ("\\documentclass{beamer}\n\\begin{document}\n"
        "\\slide{1aa-EN-Intro}\n"
        "\\section{Alpha}\n"
        "\\slide{1bb-EN-Contents}\n"
        "% \\section{Commented out}\n"
        "\\slide{1cc-EN-Third}\n"
        "\\conditionalslide[instructor]{1dd-EN-Instructor-only}\n"
        "\\subsection[Short]{Sub one}\n"
        "\\section*{Starred}\n"
        "\\slide{1ee-EN-Fifth}\n"
        "\\end{document}\n")


@pytest.fixture
def deck(ctx):
    ctx.decks_dir.mkdir(parents=True, exist_ok=True)
    ctx.slides_dir.mkdir(parents=True, exist_ok=True)
    (ctx.decks_dir / "course.tex").write_text(DECK, encoding="utf-8", newline="")
    frames = {
        "1aa-EN-Intro": "\\begin{standardframe}{Introduction}\nx\\end{standardframe}\n",
        "1bb-EN-Contents": "\\begin{standardframe}{Contents}\n\\tableofcontents\n\\end{standardframe}\n",
        "1cc-EN-Third": "\\newcommand{\\t}{Made}\n\\begin{standardframe}{\\t}\n\\end{standardframe}\n",
        "1dd-EN-Instructor-only": "\\begin{standardframe}{Answers}\n\\end{standardframe}\n",
        "1ee-EN-Fifth": "\\begin{quoteframe}{A quote}\n\\end{quoteframe}\n",
    }
    for slug, text in frames.items():
        (ctx.slides_dir / f"{slug}-current.tex").write_text(text, encoding="utf-8")
    return deck_scan.scan_dir(ctx.decks_dir, False)[0]


def test_the_skeleton_has_every_section_and_a_record_for_every_other_slide_of_the_view(ctx, deck):
    sk = deck_context.skeleton(ctx, deck, 2, "1bb-EN-Contents", "during-course", "EN", {"1cc": "Fallback title"})
    assert sk.before == ("\\setSlideID{1aa-EN-Intro}\\SMAgendaTitle{Introduction}\n"
                         "\\section{Alpha}\n")
    assert sk.after == ("\\setSlideID{1cc-EN-Third}\\SMAgendaTitle{Fallback title}\n"       # title from a macro: the aux's
                        "\\subsection[Short]{Sub one}\n"
                        "\\section*{Starred}\n"
                        "\\setSlideID{1ee-EN-Fifth}\\SMAgendaTitle{A quote}\n"
                        + deck_context.FLUSH_FRAME)
    assert "Commented" not in sk.before + sk.after
    assert "Answers" not in sk.after and "1dd" not in sk.after                              # not in during-course
    instructor = deck_context.skeleton(ctx, deck, 2, "1bb-EN-Contents", "instructor", "EN")
    assert "\\setSlideID{1dd-EN-Instructor-only}\\SMAgendaTitle{Answers}" in instructor.after
    assert "SMAgendaTitle" not in instructor.after.split("1cc-EN-Third}")[1].split("\n")[0]   # no fallback, no title


def test_a_slide_that_is_last_has_nothing_after_it_and_a_changed_deck_gives_no_skeleton(ctx, deck):
    last = deck_context.skeleton(ctx, deck, 5, "1ee-EN-Fifth", "instructor", "EN")
    assert last.after == "" and last.before.count("\\section") == 2
    assert deck_context.skeleton(ctx, deck, 5, "1aa-EN-Intro", "instructor", "EN") is None
    assert deck_context.skeleton(ctx, deck, 9, "1ee-EN-Fifth", "instructor", "EN") is None


def test_a_target_of_a_slide_that_needs_the_deck_says_so_and_keeps_renders_of_other_decks_apart(ctx, deck):
    target = preview_target.for_call(ctx, deck, deck_scan_call(ctx, deck, "1bb"), 2)
    assert target.needs_context == ("contents",) and target.deck is deck
    plain = preview_target.for_call(ctx, deck, deck_scan_call(ctx, deck, "1aa"), 1)
    assert plain.needs_context == () and plain.deck is None and plain.key[-1] == ""
    assert target.key[-1] == target.deck_hash != ""


def deck_scan_call(ctx, deck, slide_id):
    from slidemage import deck_editor
    return next(c for c in deck_editor.parse_slide_calls(deck) if c.id == slide_id)


def test_the_render_uses_the_deck_when_it_can_and_the_skeleton_when_it_cannot(ctx, deck, monkeypatch, tmp_path):
    target = preview_target.for_call(ctx, deck, deck_scan_call(ctx, deck, "1bb"), 2)
    seen = []
    pdf = tmp_path / "in-deck.pdf"
    monkeypatch.setattr(deck_context, "render_in_deck", lambda *a, **k: seen.append(("deck", k)) or pdf)
    monkeypatch.setattr(slide_preview, "render_slide_to_pdf", lambda *a, **k: seen.append(("plain", k)) or tmp_path / "p.pdf")
    assert preview_target.render(target, "instructor", "EN", log=print) == pdf
    assert seen[0][0] == "deck" and seen[0][1]["language"] == "EN" and len(seen) == 1
    monkeypatch.setattr(deck_context, "render_in_deck", lambda *a, **k: None)
    preview_target.render(target, "instructor", "EN", log=print)
    kwargs = seen[-1][1]
    assert seen[-1][0] == "plain" and kwargs["context_before"].startswith("\\setSlideID{1aa-EN-Intro}")
    assert kwargs["context_after"].endswith(deck_context.FLUSH_FRAME)


def test_an_unsaved_buffer_gets_the_skeleton_only_when_it_needs_the_deck(ctx, deck, monkeypatch):
    target = preview_target.for_call(ctx, deck, deck_scan_call(ctx, deck, "1bb"), 2)
    seen = []
    monkeypatch.setattr(slide_preview, "render_slide_text_to_pdf", lambda *a, **k: seen.append(k))
    preview_target.render_text(target, "\\tableofcontents", "instructor", "EN", log=print)
    preview_target.render_text(target, "plain text", "instructor", "EN", log=print)
    preview_target.render_text(target, "\\tableofcontents", "instructor", "EN", log=print,
                               mode="region")
    assert "context_before" in seen[0] and "context_before" not in seen[1] and "context_before" not in seen[2]


def test_the_page_compile_of_a_slide_becomes_its_own_pdf(ctx, deck, monkeypatch, tmp_path):
    out = tmp_path / "out"
    out.mkdir()

    class Output:
        pdf = out / "pages.pdf"
        build_dir = out

    def written(src, pages, target):
        target.write_bytes(b"%PDF fake")
        written.pages = pages
        return target

    monkeypatch.setattr(partial_compile, "frames_for_slides", lambda *a: [2])
    monkeypatch.setattr(partial_compile, "plan", lambda ctx_, job, frames: type("P", (), {"extra_lines": ""})())
    monkeypatch.setattr(partial_compile, "run", lambda plan, log, cancel: Output)
    monkeypatch.setattr(partial_compile, "new_pages_of", lambda plan, output: [[3, 4]])
    monkeypatch.setattr(partial_compile, "write_pages", written)
    pdf = deck_context.render_in_deck(ctx, deck, "instructor", "1bb", "1bb-EN-Contents", print, all_steps=True)
    assert pdf is not None and written.pages == [3, 4] and deck_context.mode_of(pdf) == deck_context.DECK
    assert not out.exists()                                                  # the page compile's folder is gone


@pytest.mark.parametrize("failure", ["no frames", "refused", "no pages"])
def test_without_a_usable_compile_there_is_no_deck_render(ctx, deck, monkeypatch, failure, tmp_path):
    logged = []
    monkeypatch.setattr(partial_compile, "frames_for_slides",
                        lambda *a: [] if failure == "no frames" else (_ for _ in ()).throw(partial_compile.PartialError("old")))
    if failure == "no pages":
        monkeypatch.setattr(partial_compile, "frames_for_slides", lambda *a: [2])
        monkeypatch.setattr(partial_compile, "plan", lambda *a: type("P", (), {"extra_lines": ""})())
        monkeypatch.setattr(partial_compile, "run", lambda *a: type("O", (), {"pdf": tmp_path / "x.pdf", "build_dir": tmp_path})())
        monkeypatch.setattr(partial_compile, "new_pages_of", lambda *a: [[]])
    assert deck_context.render_in_deck(ctx, deck, "instructor", "1bb", "1bb-EN-Contents", logged.append) is None
    assert failure != "refused" or any("old" in line for line in logged)


def test_the_flush_frame_page_comes_off(tmp_path):
    import pymupdf

    path = tmp_path / "two.pdf"
    doc = pymupdf.open()
    for text in ("slide", "flush"):
        doc.new_page().insert_text((20, 40), text)
    doc.save(path)
    doc.close()
    deck_context.drop_last_page(path)
    with pymupdf.open(path) as doc:
        assert len(doc) == 1 and "slide" in doc[0].get_text()
    deck_context.drop_last_page(path)                                        # one page: nothing to take off
    with pymupdf.open(path) as doc:
        assert len(doc) == 1


@pytest.mark.parametrize("mode, snapshot", [(deck_context.DECK, True), (deck_context.SKELETON, False), (None, False)])
def test_only_a_render_in_the_deck_may_refresh_the_snapshot_of_a_slide_that_needs_it(ctx, deck, monkeypatch, tmp_path,
                                                                                   mode, snapshot):
    from slidemage import preview_requests, slide_snapshot

    target = preview_target.for_call(ctx, deck, deck_scan_call(ctx, deck, "1bb"), 2)
    pdf = tmp_path / "r.pdf"
    pdf.write_bytes(b"%PDF")
    deck_context.remember_mode(pdf, mode) if mode else None
    monkeypatch.setattr(preview_target, "render", lambda *a, **k: pdf)
    asked = []
    monkeypatch.setattr(slide_snapshot, "prepare_preview_images",
                        lambda path, snapshots, widths: asked.append(snapshots) or ((b"a", b"b"), ()))
    saved = target.source_path.read_text(encoding="utf-8")    # a saved request renders the file as it is on disk
    request = preview_requests.RenderService().request(target, saved, "instructor", "EN", print, saved=True)
    request.wait()
    assert asked == [snapshot]
