# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
import json
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from slidemage import compiler, deck_headers, housekeeping, preview_build, preview_cli, project, slide_preview
from slidemage.preview_metrics import PreviewMetrics, record_line, stage
from slidemage.project import ProjectContext


@pytest.fixture(autouse=True)
def _no_precompiled_preamble(monkeypatch):
    monkeypatch.setenv("SLIDEMAGE_PREVIEW_FORMAT", "0")


def test_cache_key_tracks_preamble_toolchain_environment_and_user_rc(tmp_path, monkeypatch):
    executable = tmp_path / "lualatex"
    executable.write_text("engine v1")
    executable.chmod(0o755)
    monkeypatch.setattr(preview_build.shutil, "which", lambda name, **kw: str(executable) if name == "lualatex" else None)
    env = {"HOME": str(tmp_path), "PATH": str(tmp_path), "TEXMFVAR": "one"}
    body = r"\documentclass{beamer}\begin{document}BODY"

    def key(text=body, environment=env):
        return preview_build.configuration_key(text, "aaa", tmp_path, environment)

    initial = key()
    assert key(body.replace("BODY", "edit")) == initial
    assert key(body.replace("beamer", "article")) != initial
    assert key(environment={**env, "TEXMFVAR": "two"}) != initial
    (tmp_path / ".latexmkrc").write_text("different config")
    assert key() != initial
    rc_key = key()
    executable.write_text("engine v2 with changed bytes")
    assert key() != rc_key


def test_metrics_record_passes_and_nested_stages_without_global_leaks():
    with PreviewMetrics() as trace, stage("latexmk"):
        for line in ("Run number 1 of rule 'lualatex'", "Latexmk: Getting log file",
                     "Run number 1 of rule 'biber example'", "Run number 2 of rule 'lualatex'",
                     "Latexmk: Getting log file"):
            record_line(line)
    data = trace.to_dict()
    assert [r["rule"] for r in data["rules"]] == ["lualatex", "biber example", "lualatex"]
    assert data["seconds"] >= data["stages"]["latexmk"] >= 0
    record_line("Run number 99 of rule 'lualatex'")
    assert trace.to_dict() == data


def test_generated_wrappers_never_enter_real_deck_headers(tmp_path):
    decks, slides = tmp_path / "decks", tmp_path / "slides"
    decks.mkdir()
    slides.mkdir()
    for name in ("course.tex", "_slidemage_preview-1.tex", "_snapshot_1.tex"):
        (decks / name).write_text(r"\slide{abc-EN-Test}")
    slide = slides / "abc-EN-Test-current.tex"
    slide.write_text("%% Included in decks: _slidemage_preview-1\n%%\n\nBODY")
    ctx = ProjectContext.at(tmp_path)
    assert deck_headers.regenerate_headers(ctx) == (1, 1)
    assert slide.read_text() == "%% Included in decks: course\n%%\n\nBODY"


def test_watch_rebuilds_for_changed_graphics_and_missing_bibliography(tmp_path, monkeypatch):
    ctx = ProjectContext.at(tmp_path)
    ctx.decks_dir.mkdir()
    ctx.build_dir.mkdir()
    source = tmp_path / "abc-EN-Test-current.tex"
    graphic = tmp_path / "graphic with space.pdf"
    bibliography = tmp_path / "references.bib"
    source.write_text("source unchanged")
    graphic.write_bytes(b"original")
    fls, db = ctx.build_dir / "p.fls", ctx.build_dir / "p.fdb_latexmk"
    fls.write_text(f"PWD {ctx.decks_dir}\nINPUT {source}\nINPUT ../{graphic.name}\n"
                   f"INPUT {ctx.build_dir}/p.aux\nINPUT _slidemage_preview-test.tex\n")
    db.write_text('  "../references.bib" 123 10 "hash"\n  "Unresolved.bib" 0 -1 0 ""\n')
    paths = preview_build.recorded_inputs(fls, db, ctx=ctx, cache=ctx.build_dir)
    assert paths == sorted(map(str, (source, graphic, bibliography)))
    assert preview_cli.input_state(map(Path, paths))[bibliography] is None

    pdf = tmp_path / "preview.pdf"
    pdf.write_bytes(b"pdf")
    pdf.with_suffix(".inputs.json").write_text(json.dumps(paths))
    calls = []
    edits = iter((lambda: graphic.write_bytes(b"new graphic"),
                  lambda: bibliography.write_text("new bibliography")))

    def sleep(seconds):
        edit_dependency = next(edits, None)
        if edit_dependency is None:
            raise KeyboardInterrupt
        edit_dependency()

    monkeypatch.setattr(slide_preview, "render_slide_text_to_pdf", lambda *a, **kw: calls.append(a) or pdf)
    monkeypatch.setattr(preview_cli.time, "sleep", sleep)
    monkeypatch.setattr("sys.argv", ["preview", str(source), "--watch"])
    with pytest.raises(KeyboardInterrupt):
        preview_cli.main()
    assert len(calls) == 3 and calls[0] == calls[1] == calls[2]


def test_cleanup_and_new_reservation_are_atomic_in_both_orders(tmp_path, monkeypatch):
    ctx = ProjectContext.at(tmp_path)
    monkeypatch.setattr(compiler.project, "is_snapshot", lambda root: False)
    cache = ctx.build_dir / "preview-cache" / "race"
    wrapper = tmp_path / "decks" / "_slidemage_preview-race.tex"
    cache.mkdir(parents=True)
    wrapper.parent.mkdir()
    wrapper.write_text("wrapper")
    artifact = cache / "preview.pdf"
    artifact.write_bytes(b"old")
    found = housekeeping.TempFiles([cache.parent], [wrapper], [])
    deleting, release_delete, attempting, reserved = [threading.Event() for _ in range(4)]
    original_remove = housekeeping.shutil.rmtree
    errors = []

    def remove(path, **kwargs):
        deleting.set()
        if not release_delete.wait(3):
            errors.append("cleanup barrier timed out")
        original_remove(path, **kwargs)

    def build():
        attempting.set()
        with preview_build.active_build(cache, wrapper):
            reserved.set()
            cache.mkdir(parents=True, exist_ok=True)
            artifact.write_bytes(b"new")

    # Recheck a reservation made after collection of the deletion candidates.
    with preview_build.active_build(cache, wrapper):
        assert compiler.removable_build_entries(ctx) == []
        housekeeping.remove_temp_files(ctx, found)
        assert artifact.read_bytes() == b"old" and wrapper.exists()

    monkeypatch.setattr(housekeeping.shutil, "rmtree", remove)
    cleaner = threading.Thread(target=housekeeping.remove_temp_files, args=(ctx, found))
    worker = threading.Thread(target=build)
    cleaner.start()
    try:
        assert deleting.wait(1)
        acquired = preview_build._ACTIVE_LOCK.acquire(blocking=False)
        if acquired:
            preview_build._ACTIVE_LOCK.release()
        assert not acquired
        worker.start()
        assert attempting.wait(1) and not reserved.is_set()
    finally:
        release_delete.set()
        cleaner.join(3)
        if worker.ident is not None:
            worker.join(3)
    assert not errors and not cleaner.is_alive() and not worker.is_alive()
    assert artifact.read_bytes() == b"new"


def test_housekeeping_and_pruning_skip_another_process_active_build(tmp_path):
    ctx = ProjectContext.at(tmp_path)
    build = tmp_path / ".build"
    cache = build / "preview-cache" / "external"
    cache.mkdir(parents=True)
    artifact = cache / "p.pdf"
    artifact.write_bytes(b"pdf")
    wrapper = tmp_path / "decks" / "_slidemage_preview-external.tex"
    wrapper.parent.mkdir()
    wrapper.write_text("wrapper")
    lock = cache / "build.lock"
    lock.touch()
    old = time.time() - (preview_build.UNUSED_DAYS + 1) * 86400
    os.utime(lock, (old, old))
    os.utime(wrapper, (old, old))
    code = (
        "import sys; from pathlib import Path; from slidemage import project; from slidemage.preview_build import active_build; "
            "project.cache_dir = lambda: Path(sys.argv[3]); "      # the test's cache folder, where the maintenance lock is
        "ctx=active_build(Path(sys.argv[1]),Path(sys.argv[2])); "
        "ctx.__enter__(); print('reserved',flush=True); sys.stdin.readline(); ctx.__exit__(None,None,None)"
    )
    child = subprocess.Popen([sys.executable, "-c", code, str(cache), str(wrapper), str(project.cache_dir())],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    ready = queue.Queue()
    threading.Thread(target=lambda: ready.put(child.stdout.readline()), daemon=True).start()
    try:
        assert ready.get(timeout=5).strip() == "reserved"
        found = housekeeping.TempFiles([build / "preview-cache"], [wrapper], [])
        housekeeping.remove_temp_files(ctx, found)
        preview_build.prune_unused(tmp_path, build)
        assert artifact.exists() and wrapper.exists()
        child.communicate("release\n", timeout=5)
        assert child.returncode == 0
        housekeeping.remove_temp_files(ctx, found)
        assert not artifact.exists() and not wrapper.exists()
        assert preview_build.maintenance_lock(tmp_path).exists()
    finally:
        if child.poll() is None:
            child.kill()
            child.communicate(timeout=3)


def test_cache_reserved_before_first_directory_mutation(tmp_path, monkeypatch):
    original = Path.mkdir
    observed = []

    def mkdir(path, *args, **kwargs):
        if path.parent.name == "preview-cache":
            observed.append(preview_build.is_active(path))
        return original(path, *args, **kwargs)

    def run(command, *, jobname, outdir, **kwargs):
        pdf = outdir / f"{jobname}.pdf"
        pdf.write_bytes(b"pdf")
        return compiler.Build(0, pdf, outdir / f"{jobname}.log", "Success", False)

    monkeypatch.setattr(Path, "mkdir", mkdir)
    monkeypatch.setattr(compiler, "run_latexmk", run)
    preview_build.compile_cached(r'\begin{document}Text', 'abc', lambda _: None,
                                 ctx=ProjectContext.at(tmp_path), env={})
    assert observed and all(observed)
