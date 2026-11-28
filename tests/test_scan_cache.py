# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Regression tests for repeated full-project scans after a deck save."""
from __future__ import annotations

import os
import time

import pytest

from slidemage import app_settings, deck_headers, fileio, slide_language
from slidemage.project import ProjectContext

CODES = ("EN", "DE")
OLD = time.time() - 3600          # a stamp well outside the 2 s in which a file is always read again


@pytest.fixture(autouse=True)
def fresh_caches():
    slide_language.clear_cache()
    app_settings.clear_cache()
    yield
    slide_language.clear_cache()
    app_settings.clear_cache()


def write(path, text, when=OLD):
    path.write_text(text, encoding="utf-8")
    os.utime(path, (when, when))


@pytest.fixture
def slides(tmp_path, monkeypatch):
    folder = tmp_path / "slides"
    folder.mkdir()
    write(folder / "aaa-EN-One-current.tex", "body\n")       # the translation's link alone makes the group
    write(folder / "ddd-DE-Eins-current.tex", "%% Translation of: aaa-EN-One\nbody\n")
    write(folder / "bbb-EN-Two-current.tex", "body\n")
    reads = []
    real = slide_language._header
    monkeypatch.setattr(slide_language, "_header", lambda path: reads.append(path.name) or real(path))
    return folder, reads


def group(folder, slug="aaa-EN-One"):
    return slide_language.TranslationLinks(folder, CODES).group(slug)


def test_a_second_scan_reads_no_file_and_reuses_the_groups(slides, monkeypatch):
    folder, reads = slides
    first = group(folder)
    assert first.members == {"EN": "aaa-EN-One", "DE": "ddd-DE-Eins"} and len(reads) == 3
    reads.clear()
    monkeypatch.setattr(slide_language.TranslationLinks, "_scan", lambda self: pytest.fail("scanned again"))
    assert group(folder) == first and reads == []


def test_a_same_size_rewrite_inside_one_mtime_step_is_read_again_while_it_is_recent(slides):
    """Windows moves a file's mtime only every 15 ms or so: a file changed in the last 2 s is never served from the cache."""
    folder, reads = slides
    now = time.time()
    path = folder / "ddd-DE-Eins-current.tex"
    write(path, "%% Translation of: aaa-EN-One\nbody\n", now)
    assert group(folder).members == {"EN": "aaa-EN-One", "DE": "ddd-DE-Eins"}
    write(path, "%% Translation of: bbb-EN-Two\nbody\n", now)            # same size, same stamp
    assert group(folder).members == {"EN": "aaa-EN-One"}
    assert reads.count("ddd-DE-Eins-current.tex") == 2


def test_a_link_added_to_one_file_shows_at_once_while_files_are_recent(slides):
    """The links of settled files come from the cache; a recent file, even another one, makes the scan run again."""
    folder, reads = slides
    group(folder)
    now = time.time()
    write(folder / "eee-DE-Zwei-current.tex", "body\n", now)                       # recent: no cached groups
    assert group(folder, "bbb-EN-Two").members == {"EN": "bbb-EN-Two"}
    reads.clear()
    write(folder / "bbb-EN-Two-current.tex", "%% DE translation: eee-DE-Zwei\nbody\n", OLD + 60)
    assert group(folder, "bbb-EN-Two").members == {"EN": "bbb-EN-Two", "DE": "eee-DE-Zwei"}
    assert "bbb-EN-Two-current.tex" in reads and "aaa-EN-One-current.tex" not in reads
    (folder / "ddd-DE-Eins-current.tex").unlink()
    assert group(folder).members == {"EN": "aaa-EN-One"}


def test_header_sync_scans_the_slides_once_for_all_decks_and_languages(tmp_path, monkeypatch):
    ctx = ProjectContext.at(tmp_path)
    ctx.slides_dir.mkdir()
    ctx.decks_dir.mkdir()
    for name in ("one", "two", "three"):
        (ctx.decks_dir / f"{name}.tex").write_text("\\slide{abc-EN-Title}\n")
    write(ctx.slides_dir / "abc-EN-Title-current.tex", "%% Title\n\nbody\n")
    scans = []

    class Counting(slide_language.TranslationLinks):
        def __init__(self, *args, **kwargs):
            scans.append(1)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(slide_language, "TranslationLinks", Counting)
    id_to_decks, _paths = deck_headers._deck_membership(ctx)
    assert id_to_decks["abc"] == {"one", "two", "three"}
    assert len(scans) == 1


def test_settings_are_parsed_once_while_the_files_are_unchanged(tmp_path, monkeypatch):
    ctx = ProjectContext.at(tmp_path)
    ctx.settings_dir.mkdir(parents=True)
    store = ctx.settings_dir / "app_settings.json"
    write(store, '{"last_deck": "course"}')
    write(app_settings.machine_store_path(), "{}")
    reads = []
    real = fileio.read_json
    monkeypatch.setattr(fileio, "read_json", lambda path, *a: reads.append(path) or real(path, *a))
    assert app_settings.get(ctx, "last_deck") == "course"
    reads.clear()
    assert app_settings.get(ctx, "last_deck") == "course" and reads == []
    app_settings.load(ctx)["last_deck"] = "changed by a caller"           # a copy: the cache keeps its own
    assert app_settings.get(ctx, "last_deck") == "course"
    write(store, '{"last_deck": "other"}', OLD + 60)                      # changed outside the app (a sync client)
    assert app_settings.get(ctx, "last_deck") == "other"
    app_settings.set(ctx, "last_deck", "third")                          # written now: read again while recent
    assert app_settings.get(ctx, "last_deck") == "third"
