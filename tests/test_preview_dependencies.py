# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
from pathlib import Path
import json
from types import SimpleNamespace

import pytest

from slidemage import compiler, preview_build, preview_cli
from slidemage.preview_metrics import PreviewMetrics, record_line, stage
from slidemage.project import ProjectContext
from conftest import EXAMPLE_PROJECT


@pytest.fixture(autouse=True)
def _no_precompiled_preamble(monkeypatch):
    # These tests fake latexmk, not the engine that would build a format.
    monkeypatch.setenv("SLIDEMAGE_PREVIEW_FORMAT", "0")


def test_cache_key_tracks_preamble_toolchain_environment_and_user_rc(
    tmp_path, monkeypatch
):
    executable = tmp_path / "lualatex"
    executable.write_text("engine v1")
    executable.chmod(0o755)
    monkeypatch.setattr(
        preview_build.shutil,
        "which",
        lambda name, **kw: str(executable) if name == "lualatex" else None,
    )
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


def test_recorded_inputs_include_bib_spaces_and_missing_files_but_exclude_outputs(
    tmp_path,
):
    decks, cache = tmp_path / "decks", tmp_path / ".build"
    decks.mkdir()
    cache.mkdir()
    fls, db = cache / "p.fls", cache / "p.fdb_latexmk"
    fls.write_text(
        f"PWD {decks}\nINPUT ../slides/a.tex\nINPUT ../media/with space.pdf\n"
        f"INPUT {cache}/p.aux\nINPUT _slidemage_preview-test.tex\n"
    )
    db.write_text('  "../references.bib" 123 10 "hash"\n')
    paths = preview_build.recorded_inputs(fls, db, project_root=tmp_path, cache=cache)
    assert paths == sorted(
        str(tmp_path / p)
        for p in ("slides/a.tex", "media/with space.pdf", "references.bib")
    )
    state = preview_cli.input_state(map(Path, paths))
    assert all(value is None for value in state.values())
    (tmp_path / "references.bib").write_text("new bibliography")
    assert preview_cli.input_state(map(Path, paths)) != state


def test_metrics_record_passes_and_nested_stages_without_global_leaks():
    with PreviewMetrics() as trace:
        with stage("latexmk"):
            record_line("Run number 1 of rule 'lualatex'")
            record_line("Latexmk: Getting log file")
            record_line("Run number 1 of rule 'biber example'")
            record_line("Run number 2 of rule 'lualatex'")
            record_line("Latexmk: Getting log file")
    data = trace.to_dict()
    assert [r["rule"] for r in data["rules"]] == [
        "lualatex",
        "biber example",
        "lualatex",
    ]
    assert (
        data["stages"]["latexmk"] >= 0 and data["seconds"] >= data["stages"]["latexmk"]
    )
    record_line("Run number 99 of rule 'lualatex'")
    assert trace.to_dict() == data


def test_generated_wrappers_never_enter_real_deck_headers(tmp_path, monkeypatch):
    from slidemage import deck_headers

    decks, slides = tmp_path / "decks", tmp_path / "slides"
    decks.mkdir()
    slides.mkdir()
    (decks / "course.tex").write_text(r"\slide{abc-EN-Test}")
    (decks / "_slidemage_preview-1.tex").write_text(r"\slide{abc-EN-Test}")
    (decks / "_snapshot_1.tex").write_text(r"\slide{abc-EN-Test}")
    slide = slides / "abc-EN-Test-current.tex"
    slide.write_text("%% Included in decks: _slidemage_preview-1\n%%\n\nBODY")
    ctx = ProjectContext.at(tmp_path)
    assert deck_headers.regenerate_headers(ctx) == (1, 1)
    assert slide.read_text() == "%% Included in decks: course\n%%\n\nBODY"


def test_watch_rebuilds_when_recorded_dependency_changes(tmp_path, monkeypatch):
    from slidemage import slide_preview

    source = tmp_path / "abc-EN-Test-current.tex"
    source.write_text("source unchanged")
    dependency = tmp_path / "graphics.pdf"
    dependency.write_bytes(b"original")
    pdf = tmp_path / "preview.pdf"
    pdf.write_bytes(b"pdf")
    pdf.with_suffix(".inputs.json").write_text(json.dumps([str(dependency)]))
    calls = []

    def render(*a, **kw):
        calls.append((a, kw))
        return pdf

    sleeps = []

    def sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) == 1:
            dependency.write_bytes(b"new graphic")
        else:
            raise KeyboardInterrupt

    monkeypatch.setattr(slide_preview, "render_slide_text_to_pdf", render)
    monkeypatch.setattr(preview_cli.time, "sleep", sleep)
    monkeypatch.setattr("sys.argv", ["preview", str(source), "--watch"])
    import pytest

    with pytest.raises(KeyboardInterrupt):
        preview_cli.main()
    assert len(calls) == 2 and calls[0][0] == calls[1][0]


def test_housekeeping_rechecks_jobs_that_started_after_counting(tmp_path, monkeypatch):
    from slidemage import housekeeping, compiler

    build = tmp_path / ".build"
    cache = build / "preview-cache" / "test"
    cache.mkdir(parents=True)
    artifact = cache / "p.pdf"
    artifact.write_bytes(b"pdf")
    decks = tmp_path / "decks"
    decks.mkdir()
    wrapper = decks / "_slidemage_preview-test.tex"
    wrapper.write_text("source")
    ctx = ProjectContext.at(tmp_path)
    monkeypatch.setattr(compiler.project, "is_snapshot", lambda root: False)
    found = housekeeping.TempFiles([build / "preview-cache"], [wrapper], [])
    with preview_build.active_build(cache, wrapper):
        assert compiler.removable_build_entries(ctx) == []
        housekeeping.remove_temp_files(ctx, found)
        assert artifact.exists() and wrapper.exists()
    housekeeping.remove_temp_files(ctx, found)
    assert not artifact.exists() and not wrapper.exists()


def test_cleanup_and_new_reservation_are_atomic_in_both_orders(tmp_path, monkeypatch):
    import threading
    from slidemage import housekeeping
    cache = tmp_path / ".build" / "preview-cache" / "race"
    wrapper = tmp_path / "decks" / "_slidemage_preview-race.tex"
    cache.mkdir(parents=True)
    wrapper.parent.mkdir()
    wrapper.write_text("wrapper")
    artifact = cache / "preview.pdf"
    artifact.write_bytes(b"old")
    found = housekeeping.TempFiles([cache], [wrapper], [])
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

    monkeypatch.setattr(housekeeping.shutil, "rmtree", remove)
    cleaner = threading.Thread(target=housekeeping.remove_temp_files, args=(EXAMPLE_PROJECT, found))
    cleaner.start()
    assert deleting.wait(1)
    # While deletion owns the guard a reservation cannot enter its mutation phase.
    assert not preview_build._ACTIVE_LOCK.acquire(blocking=False)
    worker = threading.Thread(target=build)
    worker.start()
    assert attempting.wait(1) and not reserved.is_set()
    release_delete.set()
    cleaner.join(3)
    worker.join(3)
    assert not errors and not cleaner.is_alive() and not worker.is_alive()
    assert artifact.read_bytes() == b"new"
    # Reverse ordering: an established reservation prevents removal altogether.
    with preview_build.active_build(cache, wrapper):
        housekeeping.remove_temp_files(EXAMPLE_PROJECT, found)
        assert artifact.read_bytes() == b"new"


def test_housekeeping_and_pruning_skip_another_process_active_build(tmp_path, monkeypatch):
    import os
    import subprocess
    import sys
    import threading
    import queue
    import time
    from slidemage import housekeeping
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
        "import sys; from pathlib import Path; from slidemage.preview_build import active_build; "
        "ctx=active_build(Path(sys.argv[1]),Path(sys.argv[2])); "
        "ctx.__enter__(); print('reserved',flush=True); sys.stdin.readline(); ctx.__exit__(None,None,None)"
    )
    child = subprocess.Popen([sys.executable, "-c", code, str(cache), str(wrapper)],
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

    def popen(cmd, **kwargs):
        cache = Path(next(c.split('=', 1)[1] for c in cmd if c.startswith('-outdir=')))
        job = next(c.split('=', 1)[1] for c in cmd if c.startswith('-jobname='))
        (cache / (job + '.pdf')).write_bytes(b'pdf')
        (cache / (job + '.log')).write_text('Success')
        return SimpleNamespace(stdout=iter([]), wait=lambda: 0, returncode=0)

    monkeypatch.setattr(Path, "mkdir", mkdir)
    monkeypatch.setattr(compiler.subprocess, "Popen", popen)
    output = preview_build.compile_cached(r'\begin{document}Text', 'abc', lambda _: None,
        ctx=ProjectContext.at(tmp_path), env={})
    assert observed and all(observed)
    import shutil
    shutil.rmtree(output.parent)
