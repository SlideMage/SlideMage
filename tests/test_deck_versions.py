"""Edits made outside the app get the "+", and a deck's changed slides are found (slide_versioning)."""
from slidemage import deck_scan
from slidemage import slide_versioning as sv
from slidemage.slide_source import read_slide_source

HEADER = "%% Included in decks: talk\n%%\n\n"
CURRENT = "abc-EN-Demo-current.tex"


def _project(tmp_path, current, frozen=None):
    slides = tmp_path / "slides"
    (slides / ".backups").mkdir(parents=True, exist_ok=True)
    (tmp_path / "decks").mkdir()
    (slides / CURRENT).write_text(current, encoding="utf-8")
    if frozen is not None:
        (slides / "abc-EN-Demo-v1-0-0.tex").write_text(frozen, encoding="utf-8")
    (tmp_path / "decks" / "talk.tex").write_text("\\documentclass{x}\n\\begin{document}\n\\slide{abc-EN-Demo}\n\\end{document}\n",
                                                 encoding="utf-8")
    return slides / CURRENT


def test_an_outside_edit_of_a_frozen_slide_gets_the_plus(ctx, tmp_path):
    current = _project(tmp_path, HEADER + "\\setSlideVersion{1-0-0}\nedited\n", HEADER + "\\setSlideVersion{1-0-0}\noriginal\n")
    assert sv.mark_external_edit(ctx, current)
    assert sv.parse_marker(read_slide_source(current)[0]) == ((1, 0, 0), True)
    assert not sv.mark_external_edit(ctx, current)           # already marked


def test_no_plus_when_unchanged_or_never_frozen(ctx, tmp_path):
    same = HEADER + "\\setSlideVersion{1-0-0}\nsame\n"
    current = _project(tmp_path, same, same)
    assert not sv.mark_external_edit(ctx, current)
    assert sv.parse_marker(read_slide_source(current)[0]) == ((1, 0, 0), False)
    (tmp_path / "slides" / "abc-EN-Demo-v1-0-0.tex").unlink()
    assert not sv.mark_external_edit(ctx, current)            # nothing to compare with


def test_changed_slides_lists_the_plus_slides_a_deck_calls(ctx, tmp_path):
    _project(tmp_path, HEADER + "\\setSlideVersion{1-0-0+}\nx\n")
    deck = next(d for d in deck_scan.scan_decks(ctx) if d.name == "talk")
    assert sv.changed_slides(ctx, deck, "en") == ["abc-EN-Demo"]
    (tmp_path / "slides" / CURRENT).write_text(HEADER + "\\setSlideVersion{1-0-0}\nx\n", encoding="utf-8")
    assert sv.changed_slides(ctx, deck, "en") == []
