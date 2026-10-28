# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""fileio.py: complete-or-nothing writes and tolerant JSON reads."""
import os
import pytest

from slidemage.fileio import atomic_write, read_json, read_text_exact, write_json, write_text_exact


def test_atomic_write_creates_folders_and_leaves_no_temporary_file(tmp_path):
    target = tmp_path / "a" / "b" / "file.txt"
    atomic_write(target, "text\n")
    atomic_write(target, b"bytes\r\n")
    assert target.read_bytes() == b"bytes\r\n"
    assert [p.name for p in target.parent.iterdir()] == ["file.txt"]


def test_a_failed_write_keeps_the_old_file_and_cleans_up(tmp_path, monkeypatch):
    target = tmp_path / "file.txt"
    atomic_write(target, "old")
    monkeypatch.setattr("os.replace", lambda *_args: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError):
        atomic_write(target, "new")
    assert target.read_text() == "old" and [p.name for p in tmp_path.iterdir()] == ["file.txt"]


def test_read_json_gives_an_empty_value_for_anything_unusable(tmp_path):
    path = tmp_path / "s.json"
    assert read_json(path) == {} and read_json(path, list) == []             # missing
    path.write_text("{broken", encoding="utf-8")
    assert read_json(path) == {}                                             # not JSON
    path.write_bytes(b"\xff\xfe")
    assert read_json(path) == {}                                             # not UTF-8
    path.write_text("[1]", encoding="utf-8")
    assert read_json(path) == {} and read_json(path, list) == [1]            # wrong kind


def test_write_json_is_sorted_and_keeps_unicode_unless_told_otherwise(tmp_path):
    path = tmp_path / "s.json"
    write_json(path, {"b": "ä", "a": 1})
    assert path.read_text(encoding="utf-8") == '{\n  "a": 1,\n  "b": "ä"\n}\n'
    write_json(path, {"b": "ä", "a": 1}, indent=None, sort_keys=False, ensure_ascii=True)
    assert path.read_text(encoding="utf-8") == '{"b": "\\u00e4", "a": 1}\n'


def test_exact_text_keeps_crlf(tmp_path):
    path = tmp_path / "t.tex"
    write_text_exact(path, "a\r\nb\n")
    assert path.read_bytes() == b"a\r\nb\n" and read_text_exact(path) == "a\r\nb\n"


def test_a_locked_file_is_retried_then_written_and_a_permanent_lock_leaves_the_old_text(tmp_path, monkeypatch):
    target = tmp_path / "file.txt"
    atomic_write(target, "old")
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
    monkeypatch.setattr("os.replace", lambda *_args: (_ for _ in ()).throw(PermissionError("still held")))
    with pytest.raises(PermissionError):
        atomic_write(target, "newer")
    assert target.read_text() == "new" and [p.name for p in tmp_path.iterdir()] == ["file.txt"]


def test_write_text_exact_replaces_the_file_whole_and_keeps_its_mode(tmp_path, monkeypatch):
    path = tmp_path / "deck.tex"
    path.write_bytes(b"old\r\ntext\r\n")
    path.chmod(0o640)
    write_text_exact(path, "new\r\nä\n")
    assert path.read_bytes() == "new\r\nä\n".encode() and path.stat().st_mode & 0o777 == 0o640
    assert [p.name for p in tmp_path.iterdir()] == ["deck.tex"]


def test_write_text_exact_failing_midway_leaves_the_old_deck(tmp_path, monkeypatch):
    path = tmp_path / "deck.tex"
    path.write_bytes(b"old text\r\n")
    real = os.fdopen

    class Partial:
        def __init__(self, handle):
            self.handle = handle

        def __enter__(self):
            return self

        def write(self, data):
            self.handle.write(data[:3])
            self.handle.flush()
            raise OSError("disk full")

        def __getattr__(self, name):
            return getattr(self.handle, name)

        def __exit__(self, *args):
            self.handle.close()

    monkeypatch.setattr(os, "fdopen", lambda fd, mode="r", *a, **kw: Partial(real(fd, mode, *a, **kw)))
    with pytest.raises(OSError):
        write_text_exact(path, "new text that is longer\r\n")
    assert path.read_bytes() == b"old text\r\n" and [p.name for p in tmp_path.iterdir()] == ["deck.tex"]


def test_write_text_exact_checks_the_expected_text_at_the_commit(tmp_path):
    from slidemage.fileio import StaleFileError
    path = tmp_path / "deck.tex"
    path.write_bytes(b"changed\r\n")
    with pytest.raises(StaleFileError):
        write_text_exact(path, "new", expected_text="was\r\n")
    assert path.read_bytes() == b"changed\r\n" and [p.name for p in tmp_path.iterdir()] == ["deck.tex"]
    write_text_exact(path, "new", expected_text="changed\r\n")
    assert path.read_bytes() == b"new"


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
