"""Navigation for readers: \\SMChapterAgenda in transcripts, \\deckappendixtoc."""
from pathlib import Path

from conftest import write_test_file as _write
from slidemage import alt_images, deck_scan, transcript
from slidemage.project import ProjectContext


def test_transcript_lists_the_chapter_slides_on_the_agenda(tmp_path: Path, monkeypatch):
    project = tmp_path / "project"
    slides = project / "slides"
    ctx = ProjectContext.at(tmp_path / "project")
    monkeypatch.setattr(alt_images, "load_store", lambda _ctx: {})
    monkeypatch.setattr(alt_images, "load_slide_notes", lambda _ctx: {})
    _write(slides / "1aa-EN-Contents-current.tex",
           "\\begin{standardframe}{Contents}\\SMDeckAgenda\\end{standardframe}")
    _write(slides / "1ab-EN-Chapter-One-current.tex",
           "\\begin{sectionframe}{Chapter one}\\SMChapterAgenda[0.6\\linewidth]\\end{sectionframe}")
    _write(slides / "1ac-EN-First-current.tex", "\\begin{standardframe}{First slide}x\\end{standardframe}")
    _write(slides / "1ad-EN-Quote-Demo-current.tex",
           "\\SMAgendaTitle{A quote}\n\\quoteframe{Quoted.}{Someone}")
    _write(slides / "1af-EN-Steps-current.tex", "\\begin{standardframe}{Steps}y\\end{standardframe}")
    _write(slides / "1ag-EN-Later-current.tex", "\\begin{standardframe}{Later chapter}z\\end{standardframe}")
    deck = project / "decks" / "deck.tex"
    _write(deck, "\\documentclass{beamer}\n\\begin{document}\n"
                 "\\slide{1aa-EN-Contents}\n"
                 "\\section{Chapter one}\n\\slide{1ab-EN-Chapter-One}\n\\slide{1ac-EN-First}\n"
                 "\\slide{1ad-EN-Quote-Demo}\n"
                 "\\slidestep{1af-EN-Steps}[instructor]{1}\n"
                 "\\slidestep{1af-EN-Steps}[during-course,after-course]{1}\n"
                 "\\slidestep{1af-EN-Steps}[during-course,after-course]{1}\n"
                 "\\section{Chapter two}\n\\slide{1ag-EN-Later}\n"
                 "\\end{document}\n")

    resolved = transcript.resolve_deck(ctx, deck, "during-course")
    assert [(s.slide_id, s.chapter) for s in resolved] == [
        ("1aa", 0), ("1ab", 1), ("1ac", 1), ("1ad", 1), ("1af", 1), ("1af", 1), ("1ag", 2)]

    result = transcript.generate(ctx, deck, "during-course")
    agenda = next(s for s in result.slides if s.slide_id == "1ab")
    assert agenda.body == ("**This chapter's slides:**\n\n- First slide (slide 3)\n"
                           "- A quote (slide 4)\n- Steps (slide 5)")
    quote = next(s for s in result.slides if s.slide_id == "1ad")
    assert quote.title == "A quote" and "A quote" not in quote.body
    contents = next(s for s in result.slides if s.slide_id == "1aa")
    assert "SMDeckAgenda" not in contents.body and "\x02" not in contents.body


def test_single_slide_transcript_drops_the_agenda_placeholder(ctx, monkeypatch):
    monkeypatch.setattr(alt_images, "load_store", lambda _ctx: {})
    monkeypatch.setattr(alt_images, "load_slide_notes", lambda _ctx: {})
    result = transcript.generate_single_slide(
        ctx, "\\begin{sectionframe}{Chapter}\\SMChapterAgenda\\end{sectionframe}", "1ab",
        "during-course", "en")
    assert "\x02" not in result.markdown


def test_transcript_lists_the_subsections_on_a_subsection_agenda(tmp_path: Path, monkeypatch):
    project = tmp_path / "project"
    slides = project / "slides"
    ctx = ProjectContext.at(tmp_path / "project")
    monkeypatch.setattr(alt_images, "load_store", lambda _ctx: {})
    monkeypatch.setattr(alt_images, "load_slide_notes", lambda _ctx: {})
    _write(slides / "1ab-EN-Chapter-One-current.tex",
           "\\begin{sectionframe}{Chapter one}\\SMSubsectionAgenda[\\dimexpr\\linewidth-1cm\\relax]"
           "\\end{sectionframe}")
    for sid, title in (("1ac", "Alpha one"), ("1ad", "Alpha two"), ("1ae", "Beta one"),
                       ("1af", "Gamma one"), ("1ag", "Elsewhere")):
        _write(slides / f"{sid}-EN-{title.replace(' ', '-')}-current.tex",
               f"\\begin{{standardframe}}{{{title}}}x\\end{{standardframe}}")
    deck = project / "decks" / "deck.tex"
    _write(deck, "\\documentclass{beamer}\n\\begin{document}\n"
                 "\\section{Chapter one}\n\\slide{1ab-EN-Chapter-One}\n"
                 "\\subsection{Alpha \\& more}\n\\slide{1ac-EN-Alpha-one}\n\\slide{1ad-EN-Alpha-two}\n"
                 "\\subsection{Beta}\n"
                 "\\conditionalslide[instructor]{1ae-EN-Beta-one}\n"        # not in during-course
                 "\\subsection{Gamma}\n\\slide{1af-EN-Gamma-one}\n"
                 "\\section{Chapter two}\n\\subsection{Delta}\n\\slide{1ag-EN-Elsewhere}\n"
                 "\\end{document}\n")

    resolved = transcript.resolve_deck(ctx, deck, "during-course")
    assert [(s.slide_id, s.chapter, s.subsection) for s in resolved] == [
        ("1ab", 1, 0), ("1ac", 1, 1), ("1ad", 1, 1), ("1ae", 1, 2), ("1af", 1, 3), ("1ag", 2, 1)]

    result = transcript.generate(ctx, deck, "during-course")
    agenda = next(s for s in result.slides if s.slide_id == "1ab")
    # Beta has no slide in this version, so it is not listed (as in the PDF);
    # each subsection carries the number of its first slide
    assert agenda.body == ("**This chapter's sections:**\n\n- Alpha & more (slide 2)\n"
                           "- Gamma (slide 5)")
    instructor = transcript.resolve_deck(ctx, deck, "instructor")
    assert [s.subsection for s in instructor] == [0, 1, 1, 2, 3, 1]
    assert "\x02" not in agenda.body


def test_single_slide_transcript_drops_the_subsection_agenda_placeholder(ctx, monkeypatch):
    monkeypatch.setattr(alt_images, "load_store", lambda _ctx: {})
    monkeypatch.setattr(alt_images, "load_slide_notes", lambda _ctx: {})
    result = transcript.generate_single_slide(
        ctx, "\\begin{sectionframe}{Chapter}\\SMSubsectionAgenda\\end{sectionframe}", "1ab",
        "during-course", "en")
    assert "\x02" not in result.markdown and "SMSubsectionAgenda" not in result.markdown


def test_deckappendixtoc_is_read_from_the_live_preamble():
    assert deck_scan.parse_appendix_toc("\\deckappendixtoc\n\\begin{document}\n")
    assert not deck_scan.parse_appendix_toc("% \\deckappendixtoc\n\\begin{document}\n")
    assert not deck_scan.parse_appendix_toc("\\begin{document}\n\\deckappendixtoc\n")
