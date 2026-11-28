# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Fixes A3, A5, A6 and A8 of docs/Code_Review_2026-11-24-v1.0.md."""
from __future__ import annotations

import json
import subprocess
import sys
import threading
import time

import pytest

from slidemage import bibliography, compiler, deck_headers, fileio, library_data, processes, slide_rename, sm_rename
from slidemage.project import ProjectContext


@pytest.fixture
def library_project(tmp_path):
    ctx = ProjectContext.at(tmp_path)
    ctx.slides_dir.mkdir()
    (ctx.root / "slide_ids.csv").write_text('"id"\n', encoding="utf-8")
    for slide_id in ("abc", "def"):
        (ctx.slides_dir / f"{slide_id}-EN-Demo-current.tex").write_text("Demo", encoding="utf-8")
    ctx.settings_dir.mkdir()
    return ctx


def test_a_damaged_conflict_copy_is_left_out_and_kept(library_project, caplog):
    ctx = library_project
    (ctx.settings_dir / "library.json").write_text(json.dumps(
        {"pool": ["abc", 7], "topics": {"abc": ["T", None]}, "not_reusable": "def",
         "different_on_purpose": [{"ids": ["abc", "def"]}, {"ids": ["abc", "def"], "fingerprint": "f"}]}),
        encoding="utf-8")
    copy = ctx.settings_dir / "library (conflict 2026-11-24).json"
    copy.write_text('{"pool": ["def"', encoding="utf-8")
    data = library_data.read(ctx)
    assert data.pool == {"abc"} and data.topics == {"abc": {"T"}} and data.not_reusable == set()
    assert data.different_on_purpose == {(frozenset({"abc", "def"}), "f")}
    assert "Library data left out" in caplog.text
    library_data.update(ctx, lambda data: data.pool.add("def"))
    assert copy.read_text(encoding="utf-8") == '{"pool": ["def"'


def test_a_damaged_library_reads_empty_and_blocks_updates_rename_and_delete(library_project, monkeypatch):
    ctx = library_project
    path = ctx.settings_dir / "library.json"
    path.write_text("<<<<<<< HEAD\n{}\n", encoding="utf-8")
    assert library_data.read(ctx) == library_data.LibraryData()             # the Library page still opens
    with pytest.raises(fileio.UnreadableFileError):
        library_data.update(ctx, lambda data: data.pool.add("abc"))
    assert path.read_text(encoding="utf-8") == "<<<<<<< HEAD\n{}\n"
    monkeypatch.setattr(deck_headers, "regenerate_headers", lambda _ctx: None)
    before = sorted(p.name for p in ctx.slides_dir.iterdir())
    with pytest.raises(fileio.UnreadableFileError):
        slide_rename.rename_slide_id(ctx, "abc", "xyz")
    with pytest.raises(fileio.UnreadableFileError):
        slide_rename.delete_slide_id(ctx, "abc-EN-Demo")
    assert sorted(p.name for p in ctx.slides_dir.iterdir()) == before


def test_moves_and_deletes_work_when_git_cannot_run(tmp_path, monkeypatch):
    (tmp_path / ".git").mkdir()
    source = tmp_path / "a.tex"
    source.write_text("x", encoding="utf-8")
    real_run = subprocess.run

    def no_git(cmd, *args, **kwargs):
        if cmd[0] == "git":
            raise FileNotFoundError(2, "The system cannot find the file specified", "git")
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", no_git)
    assert processes.is_git_tracked(source, tmp_path) is False
    processes.move_file(source, tmp_path / "b.tex", tmp_path)
    assert (tmp_path / "b.tex").read_text(encoding="utf-8") == "x" and not source.exists()
    processes.delete_file(tmp_path / "b.tex", tmp_path)
    assert not (tmp_path / "b.tex").exists()


def test_a_hanging_git_counts_as_untracked(tmp_path, monkeypatch):
    def hangs(cmd, *args, **kwargs):
        raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout"))

    monkeypatch.setattr(subprocess, "run", hangs)
    assert processes.is_git_tracked(tmp_path / "a.tex", tmp_path) is False


BIB = "% my references\r\n\r\n@book{zeta,\r\n  title = {Z},\r\n}\r\n\r\n@book{alpha,\r\n  title = {A},\r\n}\r\n"


@pytest.fixture
def bib(tmp_path):
    path = tmp_path / "refs.bib"
    path.write_bytes(BIB.encode("utf-8"))
    return path


def test_sorting_a_bib_keeps_its_crlf(bib):
    assert bibliography.sort_entries(bib) is True
    text = bib.read_bytes().decode("utf-8")
    assert "\n" not in text.replace("\r\n", "")                              # no bare LF crept in
    assert text.index("@book{alpha") < text.index("@book{zeta")
    assert text.startswith("% my references\r\n\r\n")
    assert bibliography.sort_entries(bib) is False                          # already sorted: not written


def test_adding_a_bib_entry_writes_once_sorted_and_keeps_crlf(bib, monkeypatch):
    writes = []
    real = fileio.atomic_write
    monkeypatch.setattr(fileio, "atomic_write", lambda *a, **k: (writes.append(a[0]), real(*a, **k))[1])
    bibliography.add_entry("article", "middle", {"title": "M"}, bib)
    text = bib.read_bytes().decode("utf-8")
    assert len(writes) == 1
    assert "\n" not in text.replace("\r\n", "")
    assert text.index("@book{alpha") < text.index("@article{middle") < text.index("@book{zeta")
    assert set(bibliography.load(bib)) == {"alpha", "middle", "zeta"}


def test_adding_to_a_new_bib(tmp_path):
    path = tmp_path / "new.bib"
    bibliography.add_entry("book", "k", {"title": "T"}, path)
    assert "@book{k" in path.read_text(encoding="utf-8")


def test_sm_rename_refuses_a_file_changed_meanwhile(tmp_path, monkeypatch):
    path = tmp_path / "s.tex"
    path.write_bytes(b"x\r\n")
    monkeypatch.setattr(sm_rename, "rename_text", lambda text, counts=None: text + "renamed")
    real_exact = fileio.read_text_exact

    def changed_meanwhile(p):
        p.write_bytes(b"edited elsewhere\r\n")
        return real_exact(p)

    monkeypatch.setattr(fileio, "read_text_exact", changed_meanwhile)
    with pytest.raises(fileio.StaleFileError):
        sm_rename.rename_file(path)
    assert path.read_bytes() == b"edited elsewhere\r\n"


def test_stopping_one_job_ends_even_when_the_kill_misses(tmp_path, monkeypatch):
    monkeypatch.setattr(compiler, "STOP_GRACE_SECONDS", 0.5)
    monkeypatch.setattr(compiler.CancelToken, "_kill", staticmethod(lambda proc: None))   # the kill misses
    token = compiler.CancelToken()
    launched = []
    real_set = token._set_process
    token._set_process = lambda proc: (launched.append(proc), real_set(proc))[1]
    started = []
    threading.Thread(target=lambda: (time.sleep(1.0), started.append(True), token.stop_current()),
                     daemon=True).start()
    begun = time.monotonic()
    try:
        code = compiler.run_streamed([sys.executable, "-c", "import time; time.sleep(60)"], cwd=tmp_path,
                                     env=None, log=lambda _line: None, cancel=token)
    finally:
        for proc in launched:
            proc.kill()
    assert started and time.monotonic() - begun < 15
    assert code == -1 and not token.is_set()           # only the job was stopped, not the run
    assert token.job_stopped() is True
