"""fileio.py: complete-or-nothing writes and tolerant JSON reads."""
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
