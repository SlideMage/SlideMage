from __future__ import annotations

import io
import threading
from pathlib import Path


def _configure_compiler(monkeypatch, tmp_path):
    from slidemage import compiler
    from slidemage.deck_scan import Deck

    project_root = tmp_path / "project"
    deck_dir = project_root / "decks"
    deck_dir.mkdir(parents=True)
    deck_path = deck_dir / "demo.tex"
    deck_path.write_text("\\documentclass{beamer}\n", encoding="utf-8")
    build_dir = project_root / ".build"
    build_dir.mkdir()
    pdf_dir = project_root / "pdf"
    deck = Deck(
        name="demo",
        path=deck_path,
        archived=False,
        text="",
        supports_version=True,
        uses_biblatex=False,
        preamble_end=0,
        chapters=[],
        output_folders={},
        tags=[],
    )
    monkeypatch.setattr(compiler, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(compiler, "BUILD_DIR", build_dir)
    monkeypatch.setattr(compiler, "PDF_DIR", pdf_dir)
    monkeypatch.setattr(compiler, "_build_env", lambda: {})
    return compiler, deck, build_dir, pdf_dir, deck_path


def _fake_latexmk(monkeypatch, outputs, commands):
    from slidemage import compiler

    class FakeProcess:
        def __init__(self, command, **_kwargs):
            self.command = list(command)
            commands.append(self.command)
            self.stdout = io.StringIO("")
            self.output = outputs.pop(0)

        def wait(self):
            output_dir = Path(next(
                item.split("=", 1)[1] for item in self.command
                if item.startswith("-outdir=")
            ))
            jobname = next(
                item.split("=", 1)[1] for item in self.command
                if item.startswith("-jobname=")
            )
            output_dir.mkdir(parents=True, exist_ok=True)
            (output_dir / f"{jobname}.pdf").write_bytes(self.output)
            (output_dir / f"{jobname}.log").write_text(
                "No errors found.\n", encoding="utf-8"
            )
            return 0

    monkeypatch.setattr(compiler.subprocess, "Popen", FakeProcess)


def test_run_job_uses_only_its_fresh_configured_pdf(tmp_path, monkeypatch):
    from slidemage.compiler import CompileJob

    compiler, deck, build_dir, pdf_dir, deck_path = _configure_compiler(
        monkeypatch, tmp_path
    )
    job = CompileJob(deck, "after-course", None)
    stale_deck_pdf = deck_path.parent / f"{job.jobname}.pdf"
    stale_build_pdf = build_dir / f"{job.jobname}.pdf"
    stale_deck_pdf.write_bytes(b"OLD_DECK_PDF")
    stale_build_pdf.write_bytes(b"OLD_BUILD_PDF")
    commands = []
    _fake_latexmk(monkeypatch, [b"NEW_PDF"], commands)
    relocated = threading.Event()
    outcome = {}

    def on_relocated(ok, path):
        outcome.update(ok=ok, path=path)
        relocated.set()

    assert compiler.run_job(job, lambda _line: None, on_relocated=on_relocated)
    assert relocated.wait(5)

    expected_pdf = pdf_dir / f"{job.jobname}.pdf"
    assert outcome == {"ok": True, "path": expected_pdf}
    assert expected_pdf.read_bytes() == b"NEW_PDF"
    assert stale_deck_pdf.read_bytes() == b"OLD_DECK_PDF"
    assert stale_build_pdf.read_bytes() == b"OLD_BUILD_PDF"
    aux_dir = next(
        Path(item.split("=", 1)[1]) for item in commands[0]
        if item.startswith("-auxdir=")
    )
    out_dir = next(
        Path(item.split("=", 1)[1]) for item in commands[0]
        if item.startswith("-outdir=")
    )
    assert aux_dir == out_dir
    assert aux_dir.parent == build_dir
    assert aux_dir != build_dir


def test_delayed_old_relocation_cannot_replace_newer_compile(tmp_path, monkeypatch):
    from slidemage.compiler import CompileJob

    compiler, deck, build_dir, pdf_dir, deck_path = _configure_compiler(
        monkeypatch, tmp_path
    )
    job = CompileJob(deck, "after-course", None)
    commands = []
    _fake_latexmk(monkeypatch, [b"OLD_PDF", b"NEW_PDF"], commands)

    old_copy_started = threading.Event()
    release_old_copy = threading.Event()
    old_callback_done = threading.Event()
    new_callback_done = threading.Event()
    old_outcome = {}
    new_outcome = {}
    source_snapshots = {}
    real_relocate = compiler._relocate_pdf

    def delay_old_relocation(source, destination, destination_key, generation):
        source_snapshots[source] = source.read_bytes()
        if source_snapshots[source] == b"OLD_PDF":
            old_copy_started.set()
            if not release_old_copy.wait(5):
                raise AssertionError("test did not release old PDF relocation")
        return real_relocate(source, destination, destination_key, generation)

    monkeypatch.setattr(compiler, "_relocate_pdf", delay_old_relocation)

    def old_callback(ok, path):
        old_outcome.update(ok=ok, path=path)
        old_callback_done.set()

    def new_callback(ok, path):
        new_outcome.update(ok=ok, path=path)
        new_callback_done.set()

    assert compiler.run_job(job, lambda _line: None, on_relocated=old_callback)
    assert old_copy_started.wait(5)
    old_out_dir = next(
        Path(item.split("=", 1)[1]) for item in commands[0]
        if item.startswith("-outdir=")
    )
    old_source = old_out_dir / f"{job.jobname}.pdf"
    assert old_source.read_bytes() == b"OLD_PDF"
    assert old_out_dir not in compiler.removable_build_entries()

    assert compiler.run_job(job, lambda _line: None, on_relocated=new_callback)
    assert new_callback_done.wait(5)
    new_out_dir = next(
        Path(item.split("=", 1)[1]) for item in commands[1]
        if item.startswith("-outdir=")
    )
    new_source = new_out_dir / f"{job.jobname}.pdf"
    assert old_out_dir != new_out_dir
    assert source_snapshots[old_source] == b"OLD_PDF"
    assert source_snapshots[new_source] == b"NEW_PDF"

    release_old_copy.set()
    assert old_callback_done.wait(5)

    expected_pdf = pdf_dir / f"{job.jobname}.pdf"
    assert expected_pdf.read_bytes() == b"NEW_PDF"
    assert old_outcome == {"ok": False, "path": expected_pdf}
    assert new_outcome == {"ok": True, "path": expected_pdf}
    assert not list(deck_path.parent.glob(f"_slidemage_{job.jobname}_*.tex"))
