# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Header refreshes preserve concurrent slide writes and each file's line endings."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

from slidemage import deck_headers, fileio, slide_source, slide_versioning
from slidemage.project import ProjectContext


@pytest.fixture
def project(tmp_path):
    ctx = ProjectContext.at(tmp_path)
    ctx.slides_dir.mkdir()
    ctx.decks_dir.mkdir()
    (ctx.decks_dir / "course.tex").write_text("\\slide{abc-EN-Title}\n")
    return ctx


@pytest.mark.parametrize("eol, header", [
    ("\r\n", "%% Included in decks: old\n%%\n\n"),
    ("\n", "%% Title\n\n"),
])
def test_regeneration_retries_with_the_new_slide_body(project, monkeypatch, eol, header):
    path = project.slides_dir / "abc-EN-Title-current.tex"
    original = (header + "old body\n").replace("\n", eol)
    newer = original.replace("old body", "Claude's newer body")
    path.write_bytes(original.encode())
    attempts = []
    prepared, saved = Event(), Event()

    def write(edits):
        attempts.append(edits[path][0])
        if len(attempts) == 1:
            prepared.set()
            assert saved.wait(5)
        fileio.write_texts(edits)

    monkeypatch.setattr(deck_headers, "write_texts", write)
    with ThreadPoolExecutor(1) as pool:
        worker = pool.submit(deck_headers.regenerate_headers, project)
        assert prepared.wait(5)
        try:
            slide_versioning.save_slide(project, path, newer, eol, original, backup=False)
        finally:
            saved.set()
        assert worker.result() == (1, 1)
    autosaved = slide_versioning.set_marker(newer.replace("\r\n", "\n"), (1, 0, 0), changed=True).replace("\n", eol)
    assert attempts == [original, autosaved]
    expected = autosaved.replace("old", "course") if "Included in decks" in autosaved else autosaved.replace(
        f"%% Title{eol}{eol}", f"%% Title{eol}{eol}%% Included in decks: course{eol}%%{eol}{eol}")
    assert path.read_bytes() == expected.encode()
    assert deck_headers.regenerate_headers(project) == (0, 1)
    assert len(attempts) == 2  # an unchanged header is never rewritten


def test_continuous_edits_exhaust_retries_without_overwriting_or_counting_a_change(project, monkeypatch):
    path = project.slides_dir / "abc-EN-Title-current.tex"
    header = "%% Included in decks: old\n%%\n\n"
    path.write_text(header + "body 0\n")
    attempts = []

    def write(edits):
        attempts.append(edits[path][0])
        path.write_text(header + f"body {len(attempts)}\n")
        fileio.write_texts(edits)

    monkeypatch.setattr(deck_headers, "write_texts", write)
    assert deck_headers.regenerate_headers(project) == (0, 1)
    assert len(attempts) == 3 and path.read_text() == header + "body 3\n"
    assert list(project.slides_dir.iterdir()) == [path]


def test_failed_header_replacement_keeps_the_whole_slide(project, monkeypatch):
    path = project.slides_dir / "abc-EN-Title-current.tex"
    original = b"%% Included in decks: old\r\n%%\r\n\r\nbody\r\n"
    path.write_bytes(original)
    monkeypatch.setattr(fileio.os, "replace", lambda *_args: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError, match="disk full"):
        deck_headers.regenerate_headers(project)
    assert path.read_bytes() == original and list(project.slides_dir.iterdir()) == [path]


@pytest.mark.parametrize("when", ["before", "during_write", "locked_retry"])
def test_expected_text_is_checked_before_atomic_replacement(tmp_path, monkeypatch, when):
    path = tmp_path / "slide.tex"
    path.write_bytes(b"old\r\n")
    newer = b"newer\r\n"
    if when == "before":
        path.write_bytes(newer)
    elif when == "during_write":
        real_fsync = fileio.os.fsync

        def fsync(fd):
            real_fsync(fd)
            path.write_bytes(newer)

        monkeypatch.setattr(fileio.os, "fsync", fsync)
    else:
        def replace(source, target):
            if path.read_bytes() == newer:
                pytest.fail("replacement retried with a stale body")
            path.write_bytes(newer)
            raise PermissionError("locked")

        monkeypatch.setattr(fileio.os, "replace", replace)
        monkeypatch.setattr(fileio.time, "sleep", lambda _s: None)
    with pytest.raises(slide_source.StaleFileError):
        fileio.atomic_write(path, "header\r\nold\r\n", expected_text="old\r\n")
    assert path.read_bytes() == newer and list(tmp_path.iterdir()) == [path]
