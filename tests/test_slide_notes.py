"""The slide-source helpers behind the side panels: \\note calls and when a slide was last saved
(slide_source), a slide's translation partner and whether it is outdated (slide_language), the key
lookup of Slidemaster.bib, and storing one image's description for one slide (alt_images)."""
from __future__ import annotations

import os
from datetime import datetime

import pytest

from slidemage import alt_images, bibliography, slide_language, slide_source
from slidemage import slide_source as ss

FRAME = "\\begin{standardframe}{Demo}\n\tText\n\t\\note{First note}\n\\end{standardframe}\n"


# -- \note -------------------------------------------------------------------------------------

def test_note_calls_read_every_form_with_its_overlay_and_skip_comments():
    text = ("\\note{one \\textbf{two}}\n\\note<2>{second}\n\\note<3>[item]{third}\n% \\note{commented}\n"
            "\\noteworthy{x} \\\\note{escaped}\n")
    calls = ss.note_calls(text)
    assert [(c.overlay, c.content) for c in calls] == [
        ("", "one \\textbf{two}"), ("<2>", "second"), ("<3>[item]", "third")]
    assert text[calls[1].start:calls[1].end] == "\\note<2>{second}" == calls[1].text


def test_replace_note_keeps_the_overlay_and_everything_else():
    text = "A\n\\note<2>{old}\nB \\note{other}\n"
    assert ss.replace_note(text, 0, "new {braced}") == "A\n\\note<2>{new {braced}}\nB \\note{other}\n"


def test_remove_note_takes_its_line_when_it_stands_alone_only():
    assert ss.remove_note("A\n\t\\note{x}\nB\n", 0) == "A\nB\n"
    assert ss.remove_note("A \\note{x} B\n", 0) == "A  B\n"


def test_add_note_goes_before_the_frames_end_one_indent_deeper():
    assert ss.add_note(FRAME, "Second") == (
        "\\begin{standardframe}{Demo}\n\tText\n\t\\note{First note}\n\t\\note{Second}\n\\end{standardframe}\n")
    assert ss.add_note("\\begin{standardframe}{T}\n\t\\begin{x}\n\t\\end{x}\n\t\\end{standardframe}\n", "N").endswith(
        "\t\t\\note{N}\n\t\\end{standardframe}\n")
    assert ss.add_note("plain text\n", "N") == "plain text\n\\note{N}\n"
    notes = ss.note_calls(ss.add_note(FRAME, "Second"))
    assert [c.content for c in notes] == ["First note", "Second"]


# -- when a slide was last saved --------------------------------------------------------------------

@pytest.fixture
def slides(tmp_path, monkeypatch):
    folder = tmp_path / "slides"
    folder.mkdir()
    for module in (ss, slide_language):
        monkeypatch.setattr(module, "SLIDES_DIR", folder)
    monkeypatch.setattr(ss, "BACKUPS_DIR", folder / ".backups")
    return folder


def backup(slides, name, stamp):
    directory = slides / ".backups" / name
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{stamp}.tex").write_text("old", encoding="utf-8")


def test_last_saved_is_the_newest_backup_of_the_file(slides):
    path = slides / "abc-EN-Demo-current.tex"
    assert slide_source.last_saved(path) is None
    backup(slides, path.name, "20260101-100000")
    backup(slides, path.name, "20260301-090000-2")
    (slides / ".backups" / path.name / "notes.tex").write_text("x", encoding="utf-8")
    assert slide_source.last_saved(path) == datetime(2026, 3, 1, 9, 0, 0)


def test_a_real_save_makes_a_backup_that_last_saved_finds(slides):
    path = slides / "abc-EN-Demo-current.tex"
    path.write_text("one\n", encoding="utf-8")
    slide_source.save_slide_source(path, "two\n", "\n")
    assert abs((slide_source.last_saved(path) - datetime.now()).total_seconds()) < 5


# -- translation partners --------------------------------------------------------------------------

def pair(slides):
    en, de = slides / "abc-EN-Demo-current.tex", slides / "abd-DE-Demo-current.tex"
    en.write_text("%% DE translation: abd-DE-Demo\n" + FRAME, encoding="utf-8")
    de.write_text("%% Translation of: abc-EN-Demo\n" + FRAME, encoding="utf-8")
    old = datetime(2026, 1, 1).timestamp()
    os.utime(en, (old, old))
    os.utime(de, (old, old))
    return en, de


def test_translation_link_names_the_partner_from_either_side(slides):
    en, de = pair(slides)
    link = slide_language.translation_link("abc-EN-Demo")
    assert (link.partner, link.language, link.path, link.is_translation, link.outdated) == (
        "abd-DE-Demo", "DE", de, False, False)
    link = slide_language.translation_link("abd-DE-Demo")
    assert (link.partner, link.language, link.path, link.is_translation) == ("abc-EN-Demo", "EN", en, True)
    (slides / "xyz-EN-Alone-current.tex").write_text(FRAME, encoding="utf-8")
    assert slide_language.translation_link("xyz-EN-Alone") is None
    de.unlink()
    assert slide_language.translation_link("abc-EN-Demo") is None      # the partner's file is gone


def test_a_translation_is_outdated_when_the_original_was_saved_after_it_was_written(slides):
    en, de = pair(slides)
    backup(slides, en.name, "20260301-090000")                          # the original was saved in March
    assert slide_language.translation_link("abd-DE-Demo").outdated      # the translation's file dates from January
    assert slide_language.translation_link("abc-EN-Demo").outdated      # seen from the original, too
    backup(slides, de.name, "20260401-090000")                          # the translation saved in April
    assert not slide_language.translation_link("abd-DE-Demo").outdated
    later = datetime(2026, 5, 1).timestamp()
    os.utime(en, (later, later))                                        # a header sync touching the original's mtime
    assert not slide_language.translation_link("abd-DE-Demo").outdated  # is not a save


# -- Slidemaster.bib ---------------------------------------------------------------------------------

def test_entry_line_finds_the_entry_of_a_key(tmp_path):
    bib = tmp_path / "x.bib"
    bib.write_text("% header\n\n@article{smith2020,\n\ttitle = {A},\n}\n\n@book{doe2021,\n}\n", encoding="utf-8")
    assert bibliography.entry_line("smith2020", bib) == 3 and bibliography.entry_line("doe2021", bib) == 7
    assert bibliography.entry_line("smith20", bib) is None and bibliography.entry_line("a", tmp_path / "no.bib") is None


# -- one image on one slide -----------------------------------------------------------------------------

@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(alt_images, "STORE_PATH", tmp_path / "alt-text.json")
    monkeypatch.setattr(alt_images, "_COMPILE_CSV_PATH", tmp_path / "alt-text.csv")
    slide = tmp_path / "abc-EN-Demo-current.tex"
    slide.write_text(FRAME, encoding="utf-8")
    return slide


def test_save_slide_image_stores_text_and_reviews_this_slides_use_only(store):
    alt_images.save_slide_image("media/a.png", "abc", store, role="informative", short="S", long="L", reviewed=True)
    entry = alt_images.load_store()["media/a.png"]
    assert (entry.role, entry.short, entry.long, entry.status) == ("informative", "S", "L", "reviewed")
    use = entry.used_on["abc"]
    assert use.reviewed and use.stored_hash == alt_images.slide_context_hash(store)
    assert alt_images.slide_use_state(entry, "abc", alt_images.slide_context_hash(store)) == alt_images.STATE_REVIEWED

    alt_images.save_slide_image("media/a.png", "xyz", store, role="informative", short="S", long="L", reviewed=False)
    entry = alt_images.load_store()["media/a.png"]
    assert entry.used_on["xyz"].reviewed == "" and entry.used_on["abc"].reviewed       # the other slide stays reviewed
    alt_images.save_slide_image("media/a.png", "abc", store, role="decorative", short="", long="", reviewed=False)
    entry = alt_images.load_store()["media/a.png"]
    assert entry.is_decorative and entry.used_on["abc"].reviewed == "" and entry.status == "reviewed"
