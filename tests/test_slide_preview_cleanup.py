"""A render that succeeded must not die on a build file that is locked for a moment.

direct report 2026-10-11: compiling single slides several times in a row left the status bar
showing a render as running forever. The log ended with latexmk's last line, .build/ kept the
files of those jobs (.fls and others), and no PASS/FAIL line appeared: the cleanup after the
compile raised PermissionError (a locked file in the cloud-synced folder), which the render
thread did not catch.
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from slidemage import slide_preview


class _FakeProc:
    def __init__(self, cmd, build_dir: Path):
        jobname = next(a for a in cmd if a.startswith("-jobname=")).split("=", 1)[1]
        for suffix, text in ((".pdf", "%PDF-1.5 fake"), (".log", "no problems"),
                             (".fls", "x"), (".aux", "x"), (".synctex.gz", "x")):
            (build_dir / f"{jobname}{suffix}").write_text(text, encoding="utf-8")
        self.stdout = iter(["Latexmk: All targets are up-to-date\n"])

    def wait(self):
        return 0


@pytest.fixture
def project(monkeypatch, tmp_path):
    build = tmp_path / ".build"
    build.mkdir()
    (tmp_path / "decks").mkdir()
    monkeypatch.setattr(slide_preview, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(slide_preview, "DECKS_DIR", tmp_path / "decks")
    monkeypatch.setattr(slide_preview, "BUILD_DIR", build)
    monkeypatch.setattr(slide_preview, "_build_env", lambda: {})
    monkeypatch.setattr(slide_preview, "_LOCK_RETRY_DELAY", 0)
    # renders (and the sweep after them) must never touch the real temp directory
    fake_temp = tmp_path / "temp"
    fake_temp.mkdir()
    monkeypatch.setattr(slide_preview.tempfile, "tempdir", str(fake_temp))
    monkeypatch.setattr(
        slide_preview.slide_snapshot, "capture_single_slide", lambda *a, **k: None)
    monkeypatch.setattr(
        slide_preview.subprocess, "Popen",
        lambda cmd, **kw: _FakeProc(cmd, build))
    return build


def test_locked_build_file_does_not_fail_a_finished_render(monkeypatch, project):
    real_unlink = Path.unlink

    def locked_unlink(self, *args, **kwargs):
        if self.suffix == ".fls":
            raise PermissionError(32, "The process cannot access the file")
        return real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", locked_unlink)
    lines: list[str] = []

    pdf = slide_preview._compile_and_extract("x", "abc-EN-Test", lines.append)

    assert pdf.exists() and pdf.read_text(encoding="utf-8").startswith("%PDF")
    assert any(line.startswith("==== PASS: render of abc-EN-Test") for line in lines)
    assert any("could not be deleted" in line for line in lines)
    # everything that could be deleted was
    assert {p.suffix for p in project.iterdir()} == {".fls"}


def test_stale_preview_leftovers_are_swept_by_the_next_render(project):
    old = project / "preview-old-deadbeef.fls"
    old.write_text("x", encoding="utf-8")
    long_ago = time.time() - 2 * slide_preview._STALE_PREVIEW_AGE
    import os
    os.utime(old, (long_ago, long_ago))
    young = project / "preview-young-cafebabe.fls"
    young.write_text("x", encoding="utf-8")

    slide_preview._compile_and_extract("x", "abc-EN-Test", lambda line: None)

    assert not old.exists()
    assert young.exists()


def test_renders_older_than_24_hours_are_deleted(tmp_path):
    import os

    day = 24 * 3600

    def make(name: str, age: float, extra_dir: bool = False) -> Path:
        folder = tmp_path / name
        folder.mkdir()
        pdf = folder / "abc.pdf"
        pdf.write_text("%PDF", encoding="utf-8")
        if extra_dir:
            (folder / "sub").mkdir()
        then = time.time() - age
        os.utime(pdf, (then, then))
        os.utime(folder, (then, then))
        return folder

    old = make("slidemage_preview_old", day + 60)
    young = make("slidemage_preview_young", day - 3600)
    foreign = make("something_else", 10 * day)
    odd = make("slidemage_preview_odd", 10 * day, extra_dir=True)

    removed = slide_preview.sweep_old_renders(temp_dir=tmp_path)

    assert removed == 1
    assert not old.exists()
    assert young.exists() and foreign.exists() and odd.exists()
