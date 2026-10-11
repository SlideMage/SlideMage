"""Navigation for readers: \\SMChapterAgenda in transcripts, \\deckappendixtoc."""
from pathlib import Path

from conftest import write_test_file as _write
from slidemage import alt_images, deck_scan, transcript


def test_transcript_lists_the_chapter_slides_on_the_agenda(tmp_path: Path, monkeypatch):
    project = tmp_path / "project"
    slides = project / "slides"
    monkeypatch.setattr(transcript, "PROJECT_ROOT", project)
    monkeypatch.setattr(transcript, "SLIDES_DIR", slides)
    monkeypatch.setattr(alt_images, "load_store", lambda: {})
    monkeypatch.setattr(alt_images, "load_slide_notes", lambda: {})
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

    resolved = transcript.resolve_deck(deck, "during-course")
    assert [(s.slide_id, s.chapter) for s in resolved] == [
        ("1aa", 0), ("1ab", 1), ("1ac", 1), ("1ad", 1), ("1af", 1), ("1af", 1), ("1ag", 2)]

    result = transcript.generate(deck, "during-course")
    agenda = next(s for s in result.slides if s.slide_id == "1ab")
    assert agenda.body == ("**This chapter's slides:**\n\n- First slide (slide 3)\n"
                           "- A quote (slide 4)\n- Steps (slide 5)")
    quote = next(s for s in result.slides if s.slide_id == "1ad")
    assert quote.title == "A quote" and "A quote" not in quote.body
    contents = next(s for s in result.slides if s.slide_id == "1aa")
    assert "SMDeckAgenda" not in contents.body and "\x02" not in contents.body


def test_single_slide_transcript_drops_the_agenda_placeholder(monkeypatch):
    monkeypatch.setattr(alt_images, "load_store", lambda: {})
    monkeypatch.setattr(alt_images, "load_slide_notes", lambda: {})
    result = transcript.generate_single_slide(
        "\\begin{sectionframe}{Chapter}\\SMChapterAgenda\\end{sectionframe}", "1ab",
        "during-course", "en")
    assert "\x02" not in result.markdown


def test_deckappendixtoc_is_read_from_the_live_preamble():
    assert deck_scan.parse_appendix_toc("\\deckappendixtoc\n\\begin{document}\n")
    assert not deck_scan.parse_appendix_toc("% \\deckappendixtoc\n\\begin{document}\n")
    assert not deck_scan.parse_appendix_toc("\\begin{document}\n\\deckappendixtoc\n")
