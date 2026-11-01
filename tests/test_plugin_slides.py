# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Reading slides through the plugin host: deck_slides, slide_source, deck_output_folder, project_root and
open_slide. Pinned and current versions, a missing translation, hidden slides, the files a slide uses, and the calls that
need no window against the one that does."""
from __future__ import annotations

import dataclasses
import threading
from pathlib import Path

import pytest

from conftest import DECK_TEXT, SLIDE_TEXT, make_project, qapp as qapp
from slidemage import alt_images, deck_scan, plugin_api
from slidemage.plugins import host as host_module
from slidemage.plugins.host import PluginHost, deck_snapshot
from slidemage.plugins.manifest import read_manifest
from slidemage.project import ProjectContext

FIXTURES = Path(__file__).parent / "fixtures" / "plugins"
TRANSLATION = ("%% Translation of: abc-EN-Hello\r\n\r\n\\setSlideVersion{1-0-0}\r\n"
               "\\begin{standardframe}{Hallo}\r\n\tText\r\n\\end{standardframe}\r\n")


@pytest.fixture
def pctx(tmp_path, monkeypatch):
    monkeypatch.setattr(host_module.project, "config_dir", lambda: tmp_path / "config")
    return ProjectContext.at(make_project(monkeypatch, tmp_path / "project"))


@pytest.fixture
def host(pctx):
    return PluginHost(read_manifest(FIXTURES / "hello"), pctx)


def deck_of(pctx, text=DECK_TEXT):
    path = pctx.decks_dir / "test.tex"
    path.write_bytes(text.encode())
    return deck_snapshot(deck_scan.read_deck(path), pctx)


def write_slide(pctx, name, text):
    (pctx.slides_dir / name).write_bytes(text.encode())


# -- deck_slides ------------------------------------------------------------------------------------------------

def test_current_slides_in_deck_order(host, pctx):
    refs = host.deck_slides(deck_of(pctx), "instructor", "en")
    assert [(r.id, r.id_slug, r.language, r.version, r.pinned, r.title, r.position, r.hidden) for r in refs] == [
        ("abc", "abc-EN-Hello", "en", "1-0-0", False, "Hello", 1, False),
        ("abd", "abd-EN-Second", "en", "1-0-0", False, "Second", 2, False)]
    assert refs[0].path == pctx.slides_dir / "abc-EN-Hello-current.tex"


def test_a_pinned_version_names_its_frozen_file(host, pctx):
    write_slide(pctx, "abc-EN-Hello-v1-0-0.tex", SLIDE_TEXT.replace("Hello", "Hello old"))
    deck = deck_of(pctx, DECK_TEXT.replace("\\slide{abc-EN-Hello}", "\\slideversion{abc-EN-Hello}{1-0-0}"))
    first, second = host.deck_slides(deck, "instructor", "en")
    assert (first.pinned, first.version, first.title) == (True, "1-0-0", "Hello old")
    assert first.path == pctx.slides_dir / "abc-EN-Hello-v1-0-0.tex"
    assert (second.pinned, second.path.name) == (False, "abd-EN-Second-current.tex")
    assert "Hello old" in host.slide_source(first).text        # the pinned version, not the current file


def test_a_missing_translation_is_the_slide_in_its_own_language(host, pctx):
    write_slide(pctx, "abe-DE-Hallo-current.tex", TRANSLATION)
    deck = deck_of(pctx)
    english = host.deck_slides(deck, "instructor", "en")
    german = host.deck_slides(deck, "instructor", "de")
    assert [(r.id, r.language) for r in english] == [("abc", "en"), ("abd", "en")]
    # abc has a translation, abd has none: it stays English though German was asked for
    assert [(r.id, r.id_slug, r.language, r.title, r.position) for r in german] == [
        ("abe", "abe-DE-Hallo", "de", "Hallo", 1), ("abd", "abd-EN-Second", "en", "Second", 2)]
    assert german[0].path == pctx.slides_dir / "abe-DE-Hallo-current.tex"


def test_hidden_slides_are_listed_and_marked_per_view(host, pctx):
    deck = deck_of(pctx, DECK_TEXT.replace("\\slide{abd-EN-Second}", "\\omitslide{abd-EN-Second}"))
    hidden = {view: [r.hidden for r in host.deck_slides(deck, view, "en")]
              for view in ("instructor", "during-course", "after-course")}
    assert hidden == {"instructor": [False, False], "during-course": [False, True], "after-course": [False, True]}
    assert [r.position for r in host.deck_slides(deck, "after-course", "en")] == [1, 2]


def test_bad_view_or_language(host, pctx):
    deck = deck_of(pctx)
    with pytest.raises(ValueError, match="view"):
        host.deck_slides(deck, "presenter", "en")
    with pytest.raises(ValueError, match="language"):
        host.deck_slides(deck, "instructor", "fr")


def test_slide_reading_needs_no_window_and_runs_on_a_worker(host, pctx):
    deck, seen = deck_of(pctx), []

    def work():
        ref = host.deck_slides(deck, "instructor", "en")[0]
        seen.append((ref.id, host.slide_source(ref).text == SLIDE_TEXT, host.deck_output_folder(deck)))

    thread = threading.Thread(target=work)
    thread.start()
    thread.join()
    assert seen == [("abc", True, pctx.pdf_dir)]


# -- slide_source -----------------------------------------------------------------------------------------------

def store(pctx, **entries):
    alt_images.save_store(pctx, entries)


def test_source_lists_the_pictures_it_uses_and_describes_them(host, pctx):
    (pctx.media_dir).mkdir(exist_ok=True)
    (pctx.media_dir / "plot.png").write_bytes(b"png")
    (pctx.media_dir / "logo.png").write_bytes(b"logo")
    text = SLIDE_TEXT.replace("\\end{standardframe}", (
        "\\includegraphics{media/plot.png}\r\n\\includegraphics{media/missing.png}\r\n"
        "\\includegraphics[width=2cm]{media/plot.png}\r\n\\includegraphics{media/logo}\r\n\\end{standardframe}"))
    write_slide(pctx, "abc-EN-Hello-current.tex", text)
    store(pctx, **{
        "media/plot.png": alt_images.ImageEntry(
            "media/plot.png", short="A plot", long="A long plot", takeaway_default="Rising",
            short_de="Ein Plot", long_de="Ein langer Plot", takeaway_default_de="Steigend"),
        "media/logo.png": alt_images.ImageEntry("media/logo.png", role=alt_images.ROLE_DECORATIVE)})
    source = host.slide_source(host.deck_slides(deck_of(pctx), "instructor", "en")[0])
    assert source.text == text
    assert source.media == (pctx.media_dir / "logo.png", pctx.media_dir / "plot.png")      # by name, once, none missing
    assert source.descriptions == (
        plugin_api.MediaDescription("media/logo.png", True),
        plugin_api.MediaDescription("media/plot.png", False, "A plot", "A long plot", "Rising"))


def test_descriptions_follow_the_slides_language(host, pctx):
    (pctx.media_dir).mkdir(exist_ok=True)
    (pctx.media_dir / "plot.png").write_bytes(b"png")
    write_slide(pctx, "abe-DE-Hallo-current.tex", TRANSLATION.replace(
        "\\end{standardframe}", "\\includegraphics{media/plot.png}\r\n\\end{standardframe}"))
    store(pctx, **{"media/plot.png": alt_images.ImageEntry(
        "media/plot.png", short="A plot", short_de="Ein Plot", takeaway_default="Rising")})
    ref = host.deck_slides(deck_of(pctx), "instructor", "de")[0]
    (description,) = host.slide_source(ref).descriptions
    assert (description.short, description.takeaway) == ("Ein Plot", "")       # German, and nothing made up


def test_only_slide_files_of_the_project_are_read(host, pctx, tmp_path):
    outside = tmp_path / "secret.tex"
    outside.write_text("secret")
    for path in (outside, pctx.decks_dir / "test.tex", pctx.slides_dir / ".." / "decks" / "test.tex"):
        with pytest.raises(ValueError, match="not a slide file"):
            host.slide_source(plugin_api.SlideRef("x", "x-EN-y", path))


# -- deck_output_folder, project_root ---------------------------------------------------------------------------

def test_output_folder_follows_the_decks_line(host, pctx, tmp_path):
    assert host.project_root() == pctx.root
    assert host.deck_output_folder(deck_of(pctx)) == pctx.pdf_dir
    declared = DECK_TEXT.replace("\\begin{document}", (
        "\\deckoutputfolder{out/all}\r\n\\deckoutputfolder[after-course]{" + str(tmp_path / "web" / "Handout.pdf")
        + "}\r\n\\begin{document}"))
    deck = deck_of(pctx, declared)
    assert host.deck_output_folder(deck) == pctx.root / "out" / "all"
    assert host.deck_output_folder(deck, "during-course") == pctx.root / "out" / "all"
    assert host.deck_output_folder(deck, "after-course") == tmp_path / "web"        # a file name: its folder
    with pytest.raises(ValueError, match="view"):
        host.deck_output_folder(deck, "everyone")


# -- open_slide -------------------------------------------------------------------------------------------------

class RecordingUi:
    def __init__(self):
        self.shown = []

    def open_slide(self, path):
        self.shown.append(path)


def test_open_slide_needs_a_window(host, pctx):
    ref = host.deck_slides(deck_of(pctx), "instructor", "en")[0]
    with pytest.raises(RuntimeError, match="no window"):
        host.open_slide(ref)
    ui = RecordingUi()
    PluginHost(read_manifest(FIXTURES / "hello"), pctx, ui).open_slide(ref)
    assert ui.shown == [ref.path]
    with pytest.raises(ValueError, match="not a slide file"):
        PluginHost(read_manifest(FIXTURES / "hello"), pctx, ui).open_slide(plugin_api.SlideRef("x", "x", pctx.root))


# -- the types --------------------------------------------------------------------------------------------------

def test_multilingual_descriptions_keep_the_requested_language_and_change_with_its_store(host, pctx):
    pctx.media_dir.mkdir(exist_ok=True)
    (pctx.media_dir / "plot.png").write_bytes(b"plot")
    write_slide(pctx, "abc-mult-Hello-current.tex", SLIDE_TEXT.replace(
        "\\end{standardframe}", "\\includegraphics{media/plot.png}\n\\end{standardframe}"))
    deck = deck_of(pctx, DECK_TEXT.replace("abc-EN-Hello", "abc-mult-Hello"))
    entry = alt_images.ImageEntry("media/plot.png", short="English", short_de="Deutsch",
                                 long="Long", long_de="Lang", takeaway_default="Up", takeaway_default_de="Hoch")
    store(pctx, **{"media/plot.png": entry})
    en = host.deck_slides(deck, "instructor", "en")[0]
    de = host.deck_slides(deck, "instructor", "de")[0]
    assert (en.language, en.language_read, de.language, de.language_read) == ("mult", "en", "mult", "de")
    english, german = host.slide_source(en), host.slide_source(de)
    assert english.descriptions == (plugin_api.MediaDescription("media/plot.png", False, "English", "Long", "Up"),)
    assert german.descriptions == (plugin_api.MediaDescription("media/plot.png", False, "Deutsch", "Lang", "Hoch"),)
    # The descriptions consumed by F3's fingerprint change even though the multilingual source stays identical.
    store(pctx, **{"media/plot.png": dataclasses.replace(entry, short_de="Geändert")})
    assert host.slide_source(en) == english
    assert host.slide_source(de) != german
    assert host.slide_source(de).text == german.text
