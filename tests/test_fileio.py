# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""fileio.py: complete-or-nothing writes and tolerant JSON reads."""
import errno
import hashlib
import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Event

import pytest

from slidemage.fileio import (
    PartialWriteError, StaleFileError, atomic_write, read_json, read_text_exact,
    sha256_file, write_json, write_text_exact, write_texts, writer_stamp,
)


def test_sha256_file_hashes_all_bytes_and_reports_a_missing_file(tmp_path):
    path = tmp_path / "file.bin"
    with pytest.raises(FileNotFoundError):
        sha256_file(path)
    data = bytes(range(256)) * 8193
    path.write_bytes(data)
    assert sha256_file(path) == hashlib.sha256(data).hexdigest()


def test_json_io_preserves_unicode_and_tolerates_unusable_files(tmp_path):
    path = tmp_path / "s.json"
    assert read_json(path) == {} and read_json(path, list) == []
    for raw in (b"{broken", b"\xff\xfe", b"[1]"):
        path.write_bytes(raw)
        assert read_json(path) == {}
    assert read_json(path, list) == [1]
    write_json(path, {"b": "ä", "a": 1})
    assert path.read_text(encoding="utf-8") == '{\n  "a": 1,\n  "b": "ä"\n}\n'
    write_json(path, {"b": "ä", "a": 1}, indent=None, sort_keys=False, ensure_ascii=True)
    assert path.read_text(encoding="utf-8") == '{"b": "\\u00e4", "a": 1}\n'


def test_a_locked_file_is_retried_then_written_and_a_permanent_lock_leaves_the_old_text(tmp_path, monkeypatch):
    target = tmp_path / "nested" / "file.txt"
    atomic_write(target, b"old\r\n")
    assert target.read_bytes() == b"old\r\n"
    real_replace, calls = os.replace, []
    monkeypatch.setattr("time.sleep", lambda _s: None)

    def locked_twice(source, destination):
        calls.append(source)
        if len(calls) <= 2:
            raise PermissionError("held by a scanner")
        real_replace(source, destination)

    monkeypatch.setattr("os.replace", locked_twice)
    atomic_write(target, "new")
    assert target.read_text() == "new" and len(calls) == 3
    for error in (PermissionError("still held"), OSError(errno.ENOSPC, "disk full")):
        def failed_replace(source, destination):
            raise error

        monkeypatch.setattr(os, "replace", failed_replace)
        with pytest.raises(type(error), match=error.strerror or str(error)):
            atomic_write(target, "newer")
        assert target.read_text() == "new" and list(target.parent.iterdir()) == [target]


def test_write_text_exact_failing_midway_leaves_the_old_deck(tmp_path, monkeypatch):
    path = tmp_path / "deck.tex"
    path.write_bytes(b"old text\r\n")
    fdopen = os.fdopen

    @contextmanager
    def open_partial(fd, *args, **kwargs):
        with fdopen(fd, *args, **kwargs) as handle:
            write = handle.write

            def partial_write(data):
                write(data[:3])
                handle.flush()
                raise OSError("disk full")

            monkeypatch.setattr(handle, "write", partial_write)
            yield handle

    monkeypatch.setattr(os, "fdopen", open_partial)
    with pytest.raises(OSError, match="disk full"):
        write_text_exact(path, "new text that is longer\r\n")
    assert path.read_bytes() == b"old text\r\n" and list(tmp_path.iterdir()) == [path]


def test_exact_text_preserves_crlf_and_permissions_and_refuses_stale_writes(tmp_path):
    path = tmp_path / "deck.tex"
    path.write_bytes(b"changed\r\n")
    path.chmod(0o640)
    with pytest.raises(StaleFileError):
        write_text_exact(path, "new", expected_text="was\r\n")
    assert read_text_exact(path) == "changed\r\n" and list(tmp_path.iterdir()) == [path]
    write_text_exact(path, "new\r\nä\n", expected_text="changed\r\n")
    assert path.read_bytes() == "new\r\nä\n".encode()
    if os.name != "nt":
        assert path.stat().st_mode & 0o777 == 0o640
    assert list(tmp_path.iterdir()) == [path]


def test_write_text_exact_writes_through_a_symlink(tmp_path):
    target = tmp_path / "real.tex"
    target.write_bytes(b"a")
    link = tmp_path / "link.tex"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("no symlinks here")
    write_text_exact(link, "b")
    assert link.is_symlink() and target.read_bytes() == b"b"


def test_exclusive_create_without_hard_links_still_never_overwrites(tmp_path, monkeypatch):
    def no_links(staged, target):
        raise OSError(errno.ENOTSUP, "hard links are not supported")

    monkeypatch.setattr(os, "link", no_links)
    target = tmp_path / "new.tex"
    atomic_write(target, "text\n", exclusive=True)
    assert target.read_bytes() == b"text\n" and [p.name for p in tmp_path.iterdir()] == ["new.tex"]
    with pytest.raises(FileExistsError):
        atomic_write(target, "other", exclusive=True)
    assert target.read_bytes() == b"text\n"


def test_missing_expected_file_is_stale(tmp_path):
    path = tmp_path / "deleted"
    with pytest.raises(StaleFileError):
        write_texts({path: ("loaded", "edited")})
    assert not path.exists()


@pytest.mark.parametrize("outside_edit", [False, True])
def test_rollback_preserves_prerequisites_at_first_conflict(tmp_path, monkeypatch, outside_edit):
    slide, deck, last, registry = (tmp_path / name for name in ("slide", "deck", "last", "registry"))
    link = os.link

    def publish(staged, target):
        if target == registry:
            assert staged.parent == target.parent and staged.read_bytes() == b"after"
            registry.write_bytes(b"outside registry")
            if outside_edit:
                deck.write_bytes(b"outside edit")
        link(staged, target)

    monkeypatch.setattr(os, "link", publish)
    stamp = writer_stamp()
    with pytest.raises(PartialWriteError) as error:
        write_texts({slide: (None, "new slide"), deck: (None, "calls slide"),
                     last: (None, "later"), registry: (None, "after")}, expected_stamp=stamp)
    assert error.value.written == (slide, deck, last)
    assert error.value.restored == ((last,) if outside_edit else (last, deck, slide))
    assert not last.exists() and registry.read_bytes() == b"outside registry"
    if outside_edit:
        assert slide.read_bytes() == b"new slide" and deck.read_bytes() == b"outside edit"
        assert writer_stamp() != stamp
    else:
        assert not deck.exists() and not slide.exists()


def test_competing_writers_only_commit_one_snapshot(tmp_path, monkeypatch):
    deck = tmp_path / "deck"
    deck.write_bytes(b"before")
    publishing, competing, second_replaced = Event(), Event(), Event()
    replace = os.replace

    def publish(staged, path):
        if staged.read_bytes() == b"one":
            publishing.set()
            assert competing.wait(5)
            second_replaced.wait(0.2)  # without serialization both writers can enter os.replace
        else:
            second_replaced.set()
        replace(staged, path)

    def compete():
        competing.set()
        write_texts({deck: ("before", "two")})

    stamp = writer_stamp()
    monkeypatch.setattr(os, "replace", publish)
    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(write_texts, {deck: ("before", "one")})
        assert publishing.wait(5)
        second = pool.submit(compete)
        first.result()
        with pytest.raises(StaleFileError):
            second.result()
    assert not second_replaced.is_set() and deck.read_bytes() == b"one"
    with pytest.raises(StaleFileError):
        write_texts({}, expected_stamp=stamp)
