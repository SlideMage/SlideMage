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


def _fake_deck(**overrides):
    from slidemage.deck_scan import Deck

    fields = dict(
        name="fake", path=None, archived=False, text="", supports_version=True,
        uses_biblatex=False, preamble_end=0, chapters=[], output_folders={}, tags=[],
    )
    fields.update(overrides)
    return Deck(**fields)


def test_wrapper_write_does_not_double_crlf(tmp_path):
    # Same bug slide_preview.py's own wrapper write already guards against:
    # writing CRLF content (deck_scan.py reads deck text with newline="",
    # so a real deck's preamble_text/chapter_text already carries literal
    # "\r\n") with the default newline translation doubles every "\r" into
    # "\r\r\n" on Windows. run_job() must write with newline="" too.
    from slidemage import compiler

    wrapper = tmp_path / "wrapper.tex"
    content = "line one\r\nline two\r\n"
    wrapper.write_text(content, encoding="utf-8", newline="")
    assert wrapper.read_bytes().decode("utf-8") == content


def test_deckoutputfolder_collision_falls_back_to_jobname(tmp_path):
    from slidemage.compiler import CompileJob, Chapter, _disambiguated_destinations

    deck = _fake_deck(
        name="course", chapters=[
            Chapter(order=1, title="A", slug="A", start=0, end=0),
            Chapter(order=2, title="B", slug="B", start=0, end=0),
        ],
        output_folders={"after-course": str(tmp_path / "Handout.pdf")},
    )
    jobs = [
        CompileJob(deck, "after-course", deck.chapters[0]),
        CompileJob(deck, "after-course", deck.chapters[1]),
    ]
    logged = []
    dests = _disambiguated_destinations(jobs, logged.append)
    resolved = {dests[id(job)] for job in jobs}
    assert len(resolved) == 2  # no longer collide
    assert all(stem == job.jobname for job, (_, stem) in zip(jobs, [dests[id(j)] for j in jobs]))
    assert any("shared by 2 jobs" in line for line in logged)


def test_deckoutputfolder_no_collision_keeps_literal_name(tmp_path):
    from slidemage.compiler import CompileJob, _disambiguated_destinations

    deck = _fake_deck(
        name="solo", supports_version=False,
        output_folders={None: str(tmp_path / "Handout.pdf")},
    )
    jobs = [CompileJob(deck, None, None)]
    logged = []
    dests = _disambiguated_destinations(jobs, logged.append)
    output_dir, stem = dests[id(jobs[0])]
    assert stem == "Handout"  # single job, no collision -- literal name kept
    assert not logged


def test_presenter_fallback_collision_is_disambiguated(tmp_path):
    from slidemage.compiler import CompileJob, _disambiguated_destinations

    deck = _fake_deck(
        name="course", supports_version=True,
        output_folders={"instructor": str(tmp_path / "Handout.pdf")},
    )
    ordinary = CompileJob(deck, "instructor", None)
    presenter = CompileJob(deck, "instructor", None, presenter=True)
    logged = []
    dests = _disambiguated_destinations([ordinary, presenter], logged.append)
    assert dests[id(ordinary)] != dests[id(presenter)]


def _fake_deck_with_text(text, **overrides):
    from slidemage.deck_scan import Deck

    doc_begin = text.find("\\begin{document}")
    fields = dict(
        name="fake", path=None, archived=False, text=text, supports_version=False,
        uses_biblatex=False,
        preamble_end=(doc_begin + len("\\begin{document}")) if doc_begin != -1 else None,
        chapters=[], output_folders={}, tags=[],
    )
    fields.update(overrides)
    return Deck(**fields)


def test_commented_out_section_is_not_a_chapter():
    from slidemage.deck_scan import _parse_chapters

    text = (
        "\\documentclass{beamer}\n\\begin{document}\n"
        "\\section{Intro}\n\\slide{aaa-EN-A}\n"
        "% \\section{Old stuff}\n\\slide{bbb-EN-B}\n\\end{document}\n"
    )
    chapters = _parse_chapters(text)
    assert [c.title for c in chapters] == ["Intro"]
    # The real chapter's own span still covers the commented line as
    # ordinary content -- offsets must stay into the *original* text.
    expected = text[text.index("\\section{Intro}"):text.index("\\end{document}")]
    assert text[chapters[0].start:chapters[0].end] == expected


def test_commented_out_slide_call_is_excluded_from_appendix():
    from slidemage import deck_editor

    text = (
        "\\documentclass{beamer}\n\\begin{document}\n"
        "\\slide{abc-EN-Old}\n% \\slide{xyz-EN-Old}\n\\end{document}\n"
    )
    deck = _fake_deck_with_text(text)
    calls = deck_editor.parse_slide_calls(deck)
    commented = {c.id_slug: deck_editor.is_commented_out(deck.text, c) for c in calls}
    assert commented == {"abc-EN-Old": False, "xyz-EN-Old": True}


def test_reload_decks_remaps_job_status_without_crashing():
    """qt_gui.py's _job_status_map used to keep DeckRow objects a later
    reload_decks() (deck edit/archive/tag/duplicate, none of which check
    self.compiling) deletes the widgets of -- the next status update then
    raised RuntimeError inside _log(). Headless GUI test: build the main
    window against the example project, start a fake batch, reload, and
    confirm the status map only points at live rows."""
    import os

    from PySide6.QtWidgets import QApplication

    from slidemage import qt_gui

    app = QApplication.instance() or QApplication([])
    window = qt_gui.SlideMageWindow(qt_gui.ThemeManager())
    row = window.active_rows[0]
    window._job_status_map = {"fake-jobname": (row, "instructor")}
    window.reload_decks()
    for jobname, (mapped_row, key) in window._job_status_map.items():
        assert mapped_row in (*window.active_rows, *window.archived_rows)
        mapped_row.set_status(key, "running")  # must not raise
    window.close()


def test_save_slide_source_detects_stale_disk_content(tmp_path):
    from slidemage import slide_source

    slide_path = tmp_path / "abc-EN-Test-current.tex"
    slide_path.write_text("original\n", encoding="utf-8", newline="")

    # Another writer (a citation dialog, header regeneration, ...) changes
    # the file after this "tab" read it.
    loaded_text, eol = slide_source.read_slide_source(slide_path)
    slide_path.write_text("changed elsewhere\n", encoding="utf-8", newline="")

    import pytest

    with pytest.raises(slide_source.StaleFileError):
        slide_source.save_slide_source(
            slide_path, "my edit\n", eol, expected_text=loaded_text
        )
    # Nothing was overwritten or backed up.
    assert slide_path.read_text(encoding="utf-8") == "changed elsewhere\n"
    assert not (tmp_path / ".backups").exists()


def test_save_slide_source_without_expected_text_still_overwrites(tmp_path):
    from slidemage import slide_source

    slide_path = tmp_path / "abc-EN-Test-current.tex"
    slide_path.write_text("original\n", encoding="utf-8", newline="")
    slide_source.save_slide_source(slide_path, "new content\n", "\n")
    assert slide_path.read_text(encoding="utf-8") == "new content\n"


def test_stale_translation_is_not_written_as_in_sync(monkeypatch, tmp_path):
    """A batch translation whose English text has since been edited must
    not be saved with a translated_from_hash that makes translation_state()
    call it 'in sync' -- see alt_draft.apply_one_translation's own comment
    for the full scenario (a long-running 'Translate all' batch snapshots
    its queue once up front)."""
    from slidemage import alt_draft, alt_images

    monkeypatch.setattr(alt_images, "STORE_PATH", tmp_path / "alt-text.json")
    monkeypatch.setattr(alt_images, "_COMPILE_CSV_PATH", tmp_path / "alt-text.csv")

    entry = alt_images.ImageEntry(image="media/x.png", short="s1", long="original english", takeaway_default="t1")
    original_hash = alt_images.en_text_hash(entry)
    alt_images.save_store({"media/x.png": entry})

    # The batch translates from a queue snapshot taken before this edit.
    stale_result = alt_draft.TranslationResult(
        short_de="s1-de", long_de="translated from the OLD text",
        takeaway_de="t1-de", model="test", source_hash=original_hash,
    )

    # ... then, while that translation was in flight, the user edits the
    # English text (e.g. via the review tab, on the GUI thread).
    def edit_english(entries):
        entries["media/x.png"].long = "edited english"
        return True

    alt_images.update_store(edit_english)

    written = alt_draft.apply_one_translation("media/x.png", stale_result, "test")
    assert written is False

    current = alt_images.load_store()["media/x.png"]
    assert current.long_de == ""  # stale translation was NOT written
    assert current.translated_from_hash == ""


def test_fresh_translation_is_written_normally(monkeypatch, tmp_path):
    from slidemage import alt_draft, alt_images

    monkeypatch.setattr(alt_images, "STORE_PATH", tmp_path / "alt-text.json")
    monkeypatch.setattr(alt_images, "_COMPILE_CSV_PATH", tmp_path / "alt-text.csv")

    entry = alt_images.ImageEntry(image="media/x.png", short="s1", long="english text", takeaway_default="t1")
    current_hash = alt_images.en_text_hash(entry)
    alt_images.save_store({"media/x.png": entry})

    result = alt_draft.TranslationResult(
        short_de="s1-de", long_de="translated text",
        takeaway_de="t1-de", model="test", source_hash=current_hash,
    )
    written = alt_draft.apply_one_translation("media/x.png", result, "test")
    assert written is True

    current = alt_images.load_store()["media/x.png"]
    assert current.long_de == "translated text"
    assert current.translated_from_hash == current_hash
