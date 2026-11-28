# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Snapshot creation, isolated verification and opening a snapshot as a project."""
from __future__ import annotations

import json
import os
import re
import shutil
import threading
import time
import zipfile
from datetime import datetime
from pathlib import Path

import pytest

from conftest import write_test_file as write

from slidemage import bundled_copies, compat, compile_records, compiler, deck_scan, deck_snapshot, project, render_evidence, sm_rename
from slidemage.compat_types import Change, LAYOUT
from slidemage.deck_snapshot import SnapshotOptions
from slidemage.project import ProjectContext

WHEN = datetime(2026, 10, 7, 14, 12, 30)

DECK = r"""\documentclass{beamer}
\def\input@path{{../}}
\input{SlideMage_template_acme}
\deckoutputfolder{D:/Teaching/Somewhere}
\begin{document}
\slide{1aa-EN-One}
\end{document}
"""


@pytest.fixture
def tree(tmp_path, monkeypatch):
    """A sample project and framework with a recorded-compile substitute."""
    root = tmp_path / "Proj"
    framework = tmp_path / "SlideMage" / "latex"
    texroot = tmp_path / "texdist"
    write(root / "slide_ids.csv", '"id"\n"1aa"\n')
    write(root / ".latexmkrc", "$pdf_mode = 4;\n")
    write(root / "decks" / ".latexmkrc", "$pdf_mode = 4;\n")
    write(root / "decks" / "t-Deck.tex", DECK)
    write(root / "decks" / "t-Deck-extra.tex", DECK)
    write(root / "decks" / "t-Other.tex", DECK)
    write(root / "SlideMage_template_acme.tex", "graz\n")
    write(root / "SlideMage.bib", "@book{x, title={X}}\n")
    write(root / "SlideMage_layout_mine.tex", "% a project's own layout profile\n")
    write(root / "slides" / "1aa-EN-One-current.tex", "slide one\n")
    write(root / "slides" / "1bb-EN-Unused-current.tex", "not used\n")
    write(root / "media" / "used.png", b"png")
    write(root / "media" / "unused.png", b"png")
    write(root / "media" / "alt-text.csv", "image,short\nmedia/used.png,x\n")
    write(root / ".build" / "junk.aux", "aux")
    write(framework / "SlideMage_base.tex", "base\n")
    write(framework / "SlideMage_alt.lua", "-- lua\n")
    write(framework / "beamerthemeSlideMage.sty", "theme\n")
    write(texroot / "tex" / "latex" / "beamer" / "beamer.cls", "beamer\n")

    monkeypatch.setattr(deck_snapshot, "tex_roots", lambda: [texroot])
    monkeypatch.setattr(deck_snapshot, "command_output", lambda cmd, **kwargs: None)
    write(texroot / "fonts" / "opentype" / "public" / "fira" / "FiraSans-Light.otf", b"otf")
    monkeypatch.setattr(deck_snapshot, "pdf_font_names", lambda pdfs: ["FiraSans-Light"])
    monkeypatch.setattr(deck_snapshot, "locate_fonts", lambda names: {
        "FiraSans-Light": texroot / "fonts" / "opentype" / "public" / "fira" / "FiraSans-Light.otf"})
    calls: list[tuple[str, Path]] = []
    state = {"fail": set(), "leak": None}

    def fake_compile(cwd, wrapper, jobname, build_dir, env, log, cancel=None):
        assert wrapper.is_file(), "the wrapper exists while compiling"
        calls.append((jobname, cwd))
        if jobname in state["fail"]:
            raise deck_snapshot.SnapshotError(f"{jobname} did not compile")
        build_dir.mkdir(parents=True, exist_ok=True)
        pdf = write(build_dir / f"{jobname}.pdf", f"%PDF fake {jobname}".encode())
        fw = cwd.parent / "SlideMage" / "latex"
        deck_file = re.search(r"\\input\{([^}]+)\}", wrapper.read_text(encoding="utf-8")).group(1)
        inputs = [
            wrapper,
            cwd / "decks" / deck_file,
            cwd / "SlideMage_template_acme.tex",
            cwd / "SlideMage_layout_mine.tex",
            cwd / "slides" / "1aa-EN-One-current.tex",
            cwd / "media" / "used.png",
            fw / "SlideMage_base.tex",
            fw / "beamerthemeSlideMage.sty",
            texroot / "tex" / "latex" / "beamer" / "beamer.cls",
        ]
        if state["leak"] is not None:
            inputs.append(state["leak"])
        return deck_snapshot._JobOutput(
            job_name=jobname, pdf=pdf, inputs=inputs, log_text="Package: beamer 2025/06/02 v3.75\n",
            bib_sources=[cwd / "SlideMage.bib"])

    monkeypatch.setattr(deck_snapshot, "run_recorded_compile", fake_compile)
    decks = {d.name: d for d in deck_scan.scan_dir(root / "decks", archived=False)}
    def create(name="t-Deck", *, when=WHEN, log=print, **kwargs):
        return deck_snapshot.create_snapshot(decks[name], options(**kwargs), log, when=when,
                                             ctx=ProjectContext.at(root))

    return root, create, decks, calls, state


def options(*, verify=False, **kwargs):
    return SnapshotOptions(verify=verify, **kwargs)


def test_parse_fls_resolves_relative_paths_and_drops_duplicates(tmp_path):
    fls = write(tmp_path / "x.fls", "\n".join([
        f"PWD {tmp_path / 'proj' / 'decks'}",
        "INPUT ./deck.tex",
        "INPUT ../media/a.png",
        f"INPUT {tmp_path / 'proj' / 'media' / 'a.png'}",
        f"INPUT {tmp_path / 'proj' / 'decks' / '..' / '..' / 'fw' / 'base.tex'}",
        "OUTPUT deck.log",
    ]))
    inputs = deck_snapshot.parse_fls(fls)
    assert [p.name for p in inputs] == ["deck.tex", "a.png", "base.tex"]
    assert inputs[2] == Path(os.path.normpath(tmp_path / "fw" / "base.tex"))


def test_first_difference_names_the_line():
    assert deck_snapshot.first_difference("a\nb\nc", "a\nB\nc") == 'reference "b", now "B"'
    assert deck_snapshot.first_difference("a\nb", "a") == "reference has 2 lines, now 1"


@pytest.mark.skipif(os.name != "nt", reason="Windows paths compare case-insensitively")
def test_is_within_ignores_drive_letter_case():
    assert deck_snapshot.is_within(r"d:\Cloud\Proj\media\a.png", r"D:\Cloud\Proj")
    assert not deck_snapshot.is_within(r"D:\Cloud\Proj2\a.png", r"D:\Cloud\Proj")


def test_framework_relpath(tmp_path):
    root = tmp_path / "Proj"
    assert deck_snapshot.framework_relpath(root, tmp_path / "latex") == "latex"
    assert deck_snapshot.framework_relpath(root, tmp_path.parent / "elsewhere" / "latex") \
        == "SlideMage/latex"


# Cross-drive paths
REPO = Path(__file__).resolve().parents[1]
needs_tex = pytest.mark.skipif(not os.environ.get("SLIDEMAGE_TEX_TESTS") or not shutil.which("latexmk"),
                              reason="real LaTeX compile; set SLIDEMAGE_TEX_TESTS=1")


@pytest.fixture
def other_drive_dir(tmp_path):
    """A scratch folder on the repo's drive when pytest's temp folder is on another one, else skip."""
    if os.path.splitdrive(str(tmp_path.resolve()))[0].lower() == os.path.splitdrive(str(REPO))[0].lower():
        pytest.skip("temp folder and repo are on the same drive; no second drive to test with")
    import tempfile
    folder = Path(tempfile.mkdtemp(prefix="sm-other-drive-", dir=REPO))
    yield folder
    shutil.rmtree(folder, ignore_errors=True)


def test_files_of_another_drive_are_not_project_files(tmp_path, other_drive_dir):
    root = tmp_path / "Proj"
    write(root / "decks" / "a.tex", "x")
    outside = write(other_drive_dir / "elsewhere.bib", "y")
    assert deck_snapshot.framework_relpath(root, other_drive_dir / "latex") == "SlideMage/latex"
    relative = deck_snapshot._rel(outside, root)
    assert deck_snapshot._is_outside(relative) and not relative.startswith("..")
    assert not deck_snapshot._is_outside(deck_snapshot._rel(root / "decks" / "a.tex", root))
    out = deck_snapshot._JobOutput(job_name="a", pdf=root / "a.pdf", inputs=[root / "decks" / "a.tex"],
                                   log_text="", bib_sources=[outside])
    collected = deck_snapshot.collect_files([out], root, [], [], [])
    assert "decks/a.tex" in collected.project_files
    assert any("elsewhere.bib" in w for w in collected.warnings)       # outside the project, not a crash


def copy_manual(tmp_path, framework):
    shutil.copytree(REPO / "latex", framework)
    return shutil.copytree(REPO / "example", tmp_path / "example",
                           ignore=shutil.ignore_patterns("pdf", ".build", ".previews", "snapshots"))


@needs_tex
def test_real_snapshot_with_the_framework_on_another_drive(tmp_path, other_drive_dir, monkeypatch):
    root = copy_manual(tmp_path, other_drive_dir / "latex")
    monkeypatch.setenv("SLIDEMAGE_LATEX", str(other_drive_dir / "latex"))
    deck = next(d for d in deck_scan.scan_dir(root / "decks", False) if d.name == "slidemage-manual")
    deck.supports_version = False
    result = deck_snapshot.create_snapshot(deck, SnapshotOptions(presenter=False), print,
                                           ctx=ProjectContext.at(root))
    assert result.ok, result.error
    assert any(result.path.rglob("SlideMage_base.tex"))        # the framework came along, under SlideMage/latex

def test_snapshot_copies_and_verifies_the_decks_dependencies(tree):
    root, create, decks, calls, _ = tree
    decks["t-Deck"].supports_version = True
    result = create(verify=True)
    assert result.ok, result.error
    snap = result.path
    assert snap == root / "snapshots" / "t-Deck_2026-10-07_14-12"
    proj = snap / "Proj"
    partial = snap.with_name(f".partial-{snap.name}") / "Proj"
    jobnames = [f"t-Deck-{suffix}" for suffix in (
        "instructor", "during-course", "after-course", "instructor-presenter",
    )]
    assert calls == [(name, cwd) for cwd in (root, partial) for name in jobnames]
    for rel in ("decks/t-Deck.tex", "SlideMage_template_acme.tex", "SlideMage_layout_mine.tex",
                "slides/1aa-EN-One-current.tex", "media/used.png", "SlideMage.bib",
                ".latexmkrc", "decks/.latexmkrc", "slide_ids.csv", "media/alt-text.csv"):
        assert (proj / rel).is_file(), rel
    for rel in ("slides/1bb-EN-Unused-current.tex", "media/unused.png", ".build/junk.aux",
                "decks/t-Other.tex"):
        assert not (proj / rel).exists(), rel
    # the framework, whole, where the project's .latexmkrc looks for it
    assert (snap / "SlideMage" / "latex" / "SlideMage_alt.lua").is_file()
    # TeX distribution files are recorded, not copied
    assert not list(snap.rglob("beamer.cls"))
    manifest = deck_snapshot.read_manifest(snap)
    assert [f["path"].endswith("beamer.cls") for f in manifest["tex"]["files"]] == [True]
    assert manifest["deck_name"] == "t-Deck" and manifest["framework_dir"] == "SlideMage/latex"
    (font,) = manifest["tex"]["fonts"]
    assert font["name"] == "FiraSans-Light"
    assert font["path"] == "fonts/opentype/public/fira/FiraSans-Light.otf"
    assert not (snap / "texmf").exists()
    # one wrapper and one reference PDF per job
    assert [job["jobname"] for job in manifest["jobs"]] == jobnames
    for job in manifest["jobs"]:
        assert (proj / job["wrapper"]).is_file()
        assert (snap / "reference-pdf" / f"{job['jobname']}.pdf").is_file()
    presenter = proj / manifest["jobs"][-1]["wrapper"]
    assert presenter.read_text(encoding="utf-8").splitlines()[:2] == [
        r"\def\deckversionoverride{instructor}", r"\def\SMPresenterModeOverride{1}",
    ]
    # the project's own deck folder holds no leftover wrapper
    assert not list((root / "decks").glob("_snapshot_*"))
    # every file is hashed in the manifest
    listed = {f["path"] for f in manifest["files"]}
    on_disk = {p.relative_to(snap).as_posix() for p in snap.rglob("*") if p.is_file()}
    assert listed == on_disk - {"snapshot.json"}
    # marked as a read-only snapshot for SlideMage
    pj = json.loads((proj / ".slidemage" / "project.json").read_text(encoding="utf-8"))
    assert pj["snapshot"]["deck_name"] == "t-Deck" and pj["snapshot"]["read_only"]
    bat = (snap / "render.bat").read_bytes()
    assert b"\r\n" in bat and b"\n" not in bat.replace(b"\r\n", b"")
    assert "SOURCE_DATE_EPOCH=" in (snap / "render.sh").read_text(encoding="utf-8")
    assert "snapshots/" in (root / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert not list((root / "snapshots").glob(".partial-*"))

    write(proj / "slides" / "1aa-EN-One-current.tex", "edited\n")
    (proj / "media" / "used.png").unlink()
    report = deck_snapshot.verify_snapshot(ProjectContext.at(root), snap, print)
    assert not report.ok
    assert set(report.problems) == {"changed: Proj/slides/1aa-EN-One-current.tex", "missing: Proj/media/used.png"}


def test_optional_latex_packages_are_copied_and_external_files_warn(tree, tmp_path):
    _, create, _, _, state = tree
    state["leak"] = write(tmp_path / "elsewhere" / "logo.pdf", b"x")
    result = create(texmf=True)
    assert result.ok, result.error
    assert any("outside the project" in warning for warning in result.warnings)
    texmf = result.path / "texmf"
    assert (texmf / "tex" / "latex" / "beamer" / "beamer.cls").is_file()
    assert (texmf / "fonts" / "opentype" / "public" / "fira" / "FiraSans-Light.otf").is_file()
    assert (texmf / "README.txt").is_file() and result.counts["texmf"] == 2


def test_each_version_keeps_the_previews_its_compile_read(tmp_path):
    """Preserve instructor previews as read before later compiles refresh them."""
    root, target = tmp_path / "Proj", tmp_path / "snap" / "Proj"
    preview = write(root / ".build" / "appendix-thumbs" / "slidemage" / "1aa-304-171.png", b"refreshed")
    kept = write(tmp_path / "kept" / "0-1aa-304-171.png", b"as the instructor compile read it")

    def out(copies):
        return deck_snapshot._JobOutput("j", Path("x.pdf"), [preview], "", [], None,
                                        copies=copies)

    assert deck_snapshot.copy_job_previews(
        out({deck_snapshot._norm(preview): kept}), "t-instructor", root, target) == 1
    assert deck_snapshot.copy_job_previews(out({}), "t-after-course", root, target) == 1
    base = target / ".build" / "appendix-thumbs"
    assert (base / "t-instructor" / "slidemage" / "1aa-304-171.png").read_bytes() \
        == b"as the instructor compile read it"
    assert (base / "t-after-course" / "slidemage" / "1aa-304-171.png").read_bytes() \
        == b"refreshed"
    wrapper = f"\\includegraphics{{{root.as_posix()}/.build/appendix-thumbs/slidemage/1aa-304-171.png}}"
    assert deck_snapshot.relative_wrapper(wrapper, root, "t-instructor") == (
        "\\includegraphics{.build/appendix-thumbs/t-instructor/slidemage/1aa-304-171.png}")

    text = (f"\\includegraphics[width=1cm]{{{root.as_posix()}/.build/appendix-thumbs/slidemage/x.png}}\n"
            "\\input{t-Deck.tex}\n")
    assert deck_snapshot.relative_wrapper(text, root) == (
        "\\includegraphics[width=1cm]{.build/appendix-thumbs/slidemage/x.png}\n\\input{t-Deck.tex}\n")


def record_compile(ctx, deck, texroot: Path, started: float) -> Path:
    root, jobname = ctx.root, deck.name
    fw = root.parent / "SlideMage" / "latex"
    inv = root / ".build" / f"{jobname}-x"
    write(inv / f"{jobname}.fls", "\n".join(f"INPUT {p}" for p in (
        root / "decks" / "t-Deck.tex", root / "SlideMage_template_acme.tex",
        root / "slides" / "1aa-EN-One-current.tex", root / "media" / "used.png",
        fw / "SlideMage_base.tex", fw / "beamerthemeSlideMage.sty",
        texroot / "tex" / "latex" / "beamer" / "beamer.cls")) + "\n")
    write(inv / f"{jobname}.log", "Package: beamer 2025/06/02 v3.75\n")
    write(inv / f"{jobname}.blg", f"Found BibTeX data source '{root / 'SlideMage.bib'}'\n")
    pdf = write(root / "pdf" / f"{jobname}.pdf", f"%PDF fake {jobname}".encode())
    env = compiler.build_env(ctx)
    wrapper = compiler.wrapper_text(ctx, compiler.CompileJob(deck, None, None))
    assert compile_records.write_record(
        ctx, jobname, inv, root / "decks" / "_w.tex", wrapper, pdf, started,
        render_evidence.search_inventory(root, env),
        render_evidence.digest(render_evidence.configuration_state(root, env)),
    )
    return pdf


def test_unchanged_version_is_reused_changed_one_compiled(tree, monkeypatch):
    root, create, decks, calls, _ = tree
    ctx, deck = ProjectContext.at(root), decks["t-Deck"]
    monkeypatch.setattr(compile_records, "engine_version", lambda: "LuaHBTeX 1.22.0")
    texroot = deck_snapshot.tex_roots()[0]
    started = time.time() + 1
    pdf = record_compile(ctx, deck, texroot, started)
    lines: list[str] = []
    result = create(verify=True, log=lines.append)
    assert result.ok, result.error
    # t-Deck reused (only its verification render), the presenter compiled
    assert [c[0] for c in calls] == ["t-Deck-presenter", "t-Deck", "t-Deck-presenter"], [
        line for line in lines if "is compiled" in line]
    assert result.counts["reused"] == 1
    manifest = deck_snapshot.read_manifest(result.path)
    job = manifest["jobs"][0]
    assert job["reused_compile"] and job["source_date_epoch"] == int(started)
    assert manifest["jobs"][1]["reused_compile"] == ""
    assert (result.path / "reference-pdf" / "t-Deck.pdf").read_bytes() == pdf.read_bytes()
    assert f"{int(started)}" in (result.path / "render.bat").read_text(encoding="utf-8")
    # a slide edit makes it compile again
    calls.clear()
    write(root / "slides" / "1aa-EN-One-current.tex", "slide one, edited\n")
    result = create(log=lines.append)
    assert result.ok and [c[0] for c in calls] == ["t-Deck", "t-Deck-presenter"]
    # and --recompile ignores the record
    record_compile(ctx, deck, texroot, time.time() + 1)
    calls.clear()
    assert create(reuse=False).ok
    assert [c[0] for c in calls] == ["t-Deck", "t-Deck-presenter"]


def test_failed_compile_leaves_nothing_behind(tree):
    root, create, _, _, state = tree
    state["fail"].add("t-Deck-presenter")
    result = create()
    assert not result.ok and "did not compile" in result.error
    assert not [p for p in (root / "snapshots").iterdir()]
    assert not list((root / "decks").glob("_snapshot_*"))
    assert not (root / ".gitignore").exists()



def test_verify_fails_when_the_snapshot_reads_the_project(tree, monkeypatch):
    root, create, _, _, _ = tree
    original = deck_snapshot.run_recorded_compile

    def leaky(cwd, wrapper, jobname, build_dir, env, log, cancel=None):
        out = original(cwd, wrapper, jobname, build_dir, env, log, cancel)
        if cwd != root:   # the verification render reads a project file
            out.inputs.append(root / "media" / "unused.png")
        return out

    monkeypatch.setattr(deck_snapshot, "run_recorded_compile", leaky)
    result = create(verify=True)
    assert not result.ok and "outside the snapshot" in result.error
    assert not list((root / "snapshots").iterdir())


def test_decks_one_by_one_a_failure_does_not_stop_the_rest(tree):
    root, _, decks, _, state = tree
    state["fail"].add("t-Deck-extra")
    results = deck_snapshot.snapshot_decks(
        [decks["t-Deck"], decks["t-Deck-extra"], decks["t-Other"]], options(), print,
        ctx=ProjectContext.at(root))
    assert [r.ok for r in results] == [True, False, True]
    assert {p.name.rsplit("_", 2)[0] for p in (root / "snapshots").iterdir()
            if not p.name.startswith(".")} == {"t-Deck", "t-Other"}
    assert not list((root / "snapshots").glob(".partial-*"))


def test_cancel_skips_the_remaining_decks(tree):
    root, _, decks, _, _ = tree
    cancel = compiler.CancelToken()

    def progress(i, n, name, text):
        if name == "t-Deck-extra":
            cancel._event.set()

    results = deck_snapshot.snapshot_decks(
        [decks["t-Deck"], decks["t-Deck-extra"], decks["t-Other"]], options(), print,
        cancel=cancel, progress=progress, ctx=ProjectContext.at(root))
    assert results[0].ok
    assert not results[1].ok
    assert results[2].skipped
    assert not list((root / "snapshots").glob(".partial-*"))


def test_old_snapshots_found_by_manifest_and_deleted_only_after_success(tree, monkeypatch):
    root, create, decks, _, state = tree
    earlier = datetime(2026, 9, 30, 10, 5)
    for name, form in (("t-Deck", False), ("t-Deck", True), ("t-Deck-extra", False)):
        assert create(name, zip=form, when=earlier).ok
    old = deck_snapshot.find_snapshots(["t-Deck"], root=root)
    assert sorted((s.deck_name, s.is_zip) for s in old) == [("t-Deck", False), ("t-Deck", True)]
    trashed: list[Path] = []
    ctx = ProjectContext.at(root)

    def fake_trash(path: Path) -> bool:
        trashed.append(path)
        shutil.rmtree(path) if path.is_dir() else path.unlink()
        return True

    monkeypatch.setattr(deck_snapshot, "move_to_trash", fake_trash)
    # a failed new snapshot deletes nothing
    state["fail"].add("t-Deck-presenter")
    results = deck_snapshot.snapshot_decks([decks["t-Deck"]], options(), print,
                                           delete_old=old, ctx=ctx)
    assert not results[0].ok and trashed == []
    # a successful one deletes exactly the listed old ones
    state["fail"].clear()
    results = deck_snapshot.snapshot_decks([decks["t-Deck"]], options(), print,
                                           delete_old=old, ctx=ctx)
    assert results[0].ok
    assert sorted(trashed) == sorted(s.path for s in old)
    remaining = deck_snapshot.find_snapshots(root=root)
    assert sorted(s.deck_name for s in remaining) == ["t-Deck", "t-Deck-extra"]


def test_folder_and_deterministic_zip_snapshots_coexist(tree, tmp_path):
    root, create, _, _, _ = tree
    results = [create(zip=form) for form in (False, True, False, True)]
    assert all(r.ok for r in results), [r.error for r in results]
    folder, zipped, second, second_zip = (r.path for r in results)
    name = "t-Deck_2026-10-07_14-12"
    assert [p.name for p in (folder, zipped, second, second_zip)] == [
        name, f"{name}.zip", f"{name}_2", f"{name}_2.zip",
    ]
    assert len(deck_snapshot.find_snapshots(["t-Deck"], root=root)) == 4
    with zipfile.ZipFile(zipped) as archive:
        names = archive.namelist()
    assert names[0] == f"{name}/snapshot.json" and all(n.startswith(f"{name}/") for n in names)
    assert deck_snapshot.read_manifest(zipped)["deck_name"] == "t-Deck"
    a, b = tmp_path / "a.zip", tmp_path / "b.zip"
    for path in (a, b):
        deck_snapshot.write_zip(folder, path, "t", WHEN)
    assert a.read_bytes() == b.read_bytes()

def test_gitignore_line_added_once(tmp_path):
    write(tmp_path / ".gitignore", "pdf/*.pdf\r\n")
    assert deck_snapshot.ensure_gitignored(tmp_path)
    assert not deck_snapshot.ensure_gitignored(tmp_path)
    text = (tmp_path / ".gitignore").read_bytes().decode("utf-8")
    assert text.count("snapshots/") == 1 and "\r\nsnapshots/\r\n" in text
    assert "\n" not in text.replace("\r\n", "")


def test_project_scans_never_look_inside_snapshots(tmp_path):
    """Project-wide rename globs must skip the frozen deck and slide sources."""
    snap = tmp_path / "snapshots" / "t-X_2026-10-07_14-12" / "Proj"
    for rel in ("slides/1aa-EN-One-current.tex", "decks/t-X.tex", "decks/archive/t-Y.tex",
                "x.tex", "README.md", ".slidemage/project.json"):
        write(snap / rel, "x")
    for pattern in sm_rename.PROJECT_GLOBS:
        assert not list(tmp_path.glob(pattern)), pattern

def test_opened_snapshot_compiles_in_place_and_refuses_updates(tree):
    root, create, _, _, _ = tree
    result = create()
    assert result.ok, result.error
    opened = result.path / "Proj"
    assert project.is_snapshot(opened) and not project.is_snapshot(root)
    assert project.snapshot_info(opened)["deck_name"] == project.snapshot_manifest(opened)["deck_name"] == "t-Deck"

    env = {"TEXINPUTS": "D:/elsewhere", "SLIDEMAGE_LATEX": "D:/live/latex", "PATH": "x"}
    adjusted = project.snapshot_compile_env(opened, env)
    framework = result.path / "SlideMage" / "latex"
    assert "TEXINPUTS" not in adjusted and Path(adjusted["SLIDEMAGE_LATEX"]) == framework
    assert adjusted["SOURCE_DATE_EPOCH"] == str(int(WHEN.timestamp()))
    assert adjusted["FORCE_SOURCE_DATE"] == "1" and adjusted["PATH"] == "x"
    assert project.snapshot_compile_env(root, env) is env

    ctx = ProjectContext.at(opened)
    (deck,) = deck_scan.scan_dir(ctx.decks_dir, False)
    assert deck.output_folders
    assert compiler.resolve_output_location(ctx, compiler.CompileJob(deck, None, None)) == (opened / "pdf", "t-Deck")
    (opened / ".build" / "t-Deck-abc123").mkdir(parents=True)
    assert [p.name for p in compiler.removable_build_entries(ctx)] == ["t-Deck-abc123"]

    deck_file = ctx.decks_dir / "t-Deck.tex"
    before = deck_file.read_bytes()
    change = Change(id="test", since="v1.0.0", severity=LAYOUT, title="t", description="d",
                    fix="f", migrate=lambda root: {"decks/t-Deck.tex": b"migrated"})
    update = compat.run_update(opened, [compat.Pending(change)])
    assert update.errors and not update.changed and deck_file.read_bytes() == before
    assert bundled_copies.plan_updates(opened, latex_source=framework, example_source=None) == []


# Real compiles (opt-in)

@needs_tex
def test_real_snapshot_of_manual(tmp_path):
    root = copy_manual(tmp_path, tmp_path / "latex")
    deck = next(d for d in deck_scan.scan_dir(root / "decks", False)
                if d.name == "slidemage-manual")
    deck.supports_version = False
    result = deck_snapshot.create_snapshot(deck, SnapshotOptions(presenter=False), print,
                                           ctx=ProjectContext.at(root))
    assert result.ok, result.error


@needs_tex
@pytest.mark.parametrize("pinned", [False, True], ids=["current", "pinned"])
def test_real_omitslide_is_instructor_only(tmp_path, monkeypatch, pinned):
    import pymupdf

    root = copy_manual(tmp_path, tmp_path / "latex")
    monkeypatch.setenv("SLIDEMAGE_LATEX", str(tmp_path / "latex"))
    monkeypatch.setenv("SLIDEMAGE_PROJECT", str(root))
    ctx = ProjectContext.at(root)
    omit = (r"\omitslideversion{1an-EN-Slide-Versions}{1-0-0}" if pinned
            else r"\omitslide{1an-EN-Slide-Versions}")
    write(root / "decks" / "omit-test.tex", r"""\documentclass[aspectratio=169]{beamer}
\makeatletter\def\input@path{{../}}\makeatother
\input{SlideMage_template_slidemage}
\newcommand{\FooterText}{Omission test}
\ifdefined\deckversionoverride\deckversion[\deckversionoverride]\fi
\typeout{SM TEST deck version: \SMDeckVersion}
\begin{document}
\slide{1jv-EN-Anatomy-of-a-Project}
""" + omit + r"""
\slide{1kp-EN-Deck-Housekeeping}
\end{document}
""")
    deck = next(d for d in deck_scan.scan_dir(root / "decks", False) if d.name == "omit-test")
    jobs = [compiler.CompileJob(deck, None, None), *compiler.build_jobs(deck, "all"),
            *compiler.build_jobs(deck, "presenter")]
    for job in jobs:
        lines, outcome = [], []
        relocated = threading.Event()

        def finished(ok, path):
            outcome.append((ok, path))
            relocated.set()

        assert compiler.run_job(ctx, job, lines.append, on_relocated=finished), "\n".join(lines)
        assert relocated.wait(30), "\n".join(lines)
        assert outcome[0][0], "\n".join(lines)
        assert f"SM TEST deck version: {job.version or 'instructor'}" in lines
        expected = [("1jv", 1), ("1an", 2), ("1kp", 3)]
        if job.version in ("during-course", "after-course"):
            expected = [("1jv", 1), ("1kp", 3)]
        with pymupdf.open(outcome[0][1]) as pdf:
            assert pdf.page_count == len(expected)
            footers = [re.search(r"\(slide id:\s*(\S+)[^)]*\)\s*(\d+)", page.get_text())
                       for page in pdf]
            assert all(footers)
            frames = [(m.group(1), int(m.group(2))) for m in footers]
            assert frames == expected
            if len(expected) == 3:
                assert "omitted from student deck" in pdf[1].get_text()
            print(f"{job.jobname}: {pdf.page_count} pages, slides {frames}")


def test_failed_biber_run_is_recognized_in_the_final_log():
    """Biber failures can leave a PDF with citation keys instead of references."""
    log = ("Package biblatex Warning: Please (re)run Biber on the file:\n"
           "(biblatex)                slidemage-manual-during-course\n")
    assert deck_snapshot._BIBER_NEEDED_RE.search(log)
    assert not deck_snapshot._BIBER_NEEDED_RE.search("Package biblatex Info: ... \n")
