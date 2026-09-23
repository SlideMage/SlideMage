from slidemage import slide_language, slide_rename, unused_content
from slidemage.qt_version_history_dialog import _license_text

STEP_SLIDE = "ZZH-EN-Deck-Version-Reveal-Steps"


def test_raw_reads_work_below_python_313():
    slide_language.cross_referenced_language("ZZJ-DE-German-Demo")
    assert "test-slides" in slide_rename.deck_names_referencing(STEP_SLIDE)


def test_license_found_outside_project():
    assert "Slidemaster" in _license_text()


def test_slidestep_slide_counts_as_used():
    unused = {p.name for p in unused_content.find_unused_slides()}
    assert f"{STEP_SLIDE}-current.tex" not in unused


def test_line_removal_takes_whole_calls_and_crlf():
    deck = (
        "\\slide{keep-EN-A}\r\n"
        "\\slideversion{gone-EN-B}{1-0-0}\r\n"
        "\t\\slidestep{gone-EN-B}[instructor]{1,2}  \r\n"
        "\\conditionalslide[after-course]{gone-EN-B}\n"
        "\\slide{gone-EN-B-longer}\r\n"
    )
    new, n = slide_rename._line_removal_pattern("gone-EN-B").subn("", deck)
    assert n == 3
    assert new == "\\slide{keep-EN-A}\r\n\\slide{gone-EN-B-longer}\r\n"
