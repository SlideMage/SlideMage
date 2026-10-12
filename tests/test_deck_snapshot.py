"""deck_snapshot: a deck's frozen, self-contained copy in <project>/snapshots/.

The LaTeX compile itself is faked here (run_recorded_compile): these tests
check what gets copied where, naming, old-snapshot handling, verification
logic and the one-deck-at-a-time loop. A real end-to-end run is in
test_real_snapshot_of_manual (opt-in, needs latexmk: SLIDEMAGE_TEX_TESTS=1)."""
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

from conftest import use_project, write_test_file as write

from slidemage import compiler, deck_scan, deck_snapshot, project, sm_rename
from slidemage.deck_snapshot import SnapshotOptions

WHEN = datetime(2026, 10, 7, 14, 12, 30)

DECK = r"""\documentclass{beamer}
\def\input@path{{../}}
\input{Slidemaster_preamble_uni-graz}
\deckoutputfolder{D:/Teaching/Somewhere}
\begin{document}
\slide{1aa-EN-One}
\end{document}
"""


@pytest.fixture
def tree(tmp_path, monkeypatch):
    """<tmp>/Proj (a project) next to <tmp>/SlideMage/latex (the framework),
    plus a fake TeX tree, with run_recorded_compile faked: it "reads" the
    deck, the template, one slide, one image, the framework, a TeX package
    and the bibliography, and writes a PDF whose bytes depend only on the
    job name."""
    root = tmp_path / "Proj"
    framework = tmp_path / "SlideMage" / "latex"
    texroot = tmp_path / "texdist"
    write(root / "slide_ids.csv", '"id"\n"1aa"\n')
    write(root / ".latexmkrc", "$pdf_mode = 4;\n")
    write(root / "decks" / ".latexmkrc", "$pdf_mode = 4;\n")
    write(root / "decks" / "t-Deck.tex", DECK)
    write(root / "decks" / "t-Deck-extra.tex", DECK)
    write(root / "decks" / "t-Other.tex", DECK)
    write(root / "Slidemaster_preamble_uni-graz.tex", "graz\n")
    write(root / "Slidemaster.bib", "@book{x, title={X}}\n")
    write(root / "slides" / "1aa-EN-One-current.tex", "slide one\n")
    write(root / "slides" / "1bb-EN-Unused-current.tex", "not used\n")
    write(root / "media" / "used.png", b"png")
    write(root / "media" / "unused.png", b"png")
    write(root / "media" / "alt-text.csv", "image,short\nmedia/used.png,x\n")
    write(root / ".build" / "junk.aux", "aux")
    write(framework / "Slidemaster_preamble_base.tex", "base\n")
    write(framework / "Slidemaster_alt.lua", "-- lua\n")
    write(framework / "beamerthemegotham.sty", "gotham\n")
    write(texroot / "tex" / "latex" / "beamer" / "beamer.cls", "beamer\n")

    use_project(monkeypatch, root)
    monkeypatch.setattr(deck_snapshot, "tex_roots", lambda: [texroot])
    monkeypatch.setattr(deck_snapshot, "_run_text", lambda cmd, cwd=None, any_exit_code=False: "")
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
        stamp = build_dir / f"{jobname}.timestamp"
        if not stamp.exists():
            write(stamp, "\\gdef\\SMCompileTimestampValue{2026-10-07 14:12}\n")
        fw = cwd.parent / "SlideMage" / "latex"
        deck_file = re.search(r"\\input\{([^}]+)\}", wrapper.read_text(encoding="utf-8")).group(1)
        inputs = [
            wrapper,
            cwd / "decks" / deck_file,
            cwd / "Slidemaster_preamble_uni-graz.tex",
            cwd / "slides" / "1aa-EN-One-current.tex",
            cwd / "media" / "used.png",
            fw / "Slidemaster_preamble_base.tex",
            fw / "beamerthemegotham.sty",
            texroot / "tex" / "latex" / "beamer" / "beamer.cls",
            stamp,
        ]
        if state["leak"] is not None:
            inputs.append(state["leak"])
        return deck_snapshot._JobOutput(
            job_name=jobname, pdf=pdf, inputs=inputs, log_text="Package: beamer 2025/06/02 v3.75\n",
            bib_sources=[cwd / "Slidemaster.bib"], timestamp=stamp.read_text(encoding="utf-8"))

    monkeypatch.setattr(deck_snapshot, "run_recorded_compile", fake_compile)
    decks = {d.name: d for d in deck_scan.scan_dir(root / "decks", archived=False)}
    return root, framework, decks, calls, state


def options(**kwargs) -> SnapshotOptions:
    kwargs.setdefault("verify", False)
    return SnapshotOptions(**kwargs)


# ---------------------------------------------------------------- parsing

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


def test_failed_biber_run_is_recognized_in_the_final_log():
    """A compile whose biber run failed (once seen: "No space left on device"
    while biber unpacked itself) still writes a PDF, citations as keys --
    never acceptable as a snapshot's reference."""
    log = ("Package biblatex Warning: Please (re)run Biber on the file:\n"
           "(biblatex)                slidemage-manual-during-course\n")
    assert deck_snapshot._BIBER_NEEDED_RE.search(log)
    assert not deck_snapshot._BIBER_NEEDED_RE.search("Package biblatex Info: ... \n")


def test_first_difference_names_the_line():
    assert deck_snapshot.first_difference("a\nb\nc", "a\nB\nc") == 'reference "b", now "B"'
    assert deck_snapshot.first_difference("a\nb", "a") == "reference has 2 lines, now 1"


@pytest.mark.skipif(os.name != "nt", reason="Windows paths compare case-insensitively")
def test_is_within_ignores_drive_letter_case():
    assert deck_snapshot.is_within(r"d:\uniCLOUD\Proj\media\a.png", r"D:\uniCLOUD\Proj")
    assert not deck_snapshot.is_within(r"D:\uniCLOUD\Proj2\a.png", r"D:\uniCLOUD\Proj")


def test_framework_relpath(tmp_path):
    root = tmp_path / "Proj"
    assert deck_snapshot.framework_relpath(root, tmp_path / "latex") == "latex"
    assert deck_snapshot.framework_relpath(root, tmp_path.parent / "elsewhere" / "latex") \
        == "SlideMage/latex"


# ---------------------------------------------------------------- creating

def test_snapshot_copies_what_the_deck_uses_at_the_same_paths(tree):
    root, framework, decks, calls, _ = tree
    result = deck_snapshot.create_snapshot(decks["t-Deck"], options(), print, when=WHEN,
                                           project_root=root)
    assert result.ok, result.error
    snap = result.path
    assert snap == root / "snapshots" / "t-Deck_2026-10-07_14-12"
    proj = snap / "Proj"
    for rel in ("decks/t-Deck.tex", "Slidemaster_preamble_uni-graz.tex",
                "slides/1aa-EN-One-current.tex", "media/used.png", "Slidemaster.bib",
                ".latexmkrc", "decks/.latexmkrc", "slide_ids.csv", "media/alt-text.csv"):
        assert (proj / rel).is_file(), rel
    for rel in ("slides/1bb-EN-Unused-current.tex", "media/unused.png", ".build/junk.aux",
                "decks/t-Other.tex"):
        assert not (proj / rel).exists(), rel
    # the framework, whole, where the project's .latexmkrc looks for it
    assert (snap / "SlideMage" / "latex" / "Slidemaster_alt.lua").is_file()
    # TeX distribution files are recorded, not copied
    assert not list(snap.rglob("beamer.cls"))
    manifest = json.loads((snap / "snapshot.json").read_text(encoding="utf-8"))
    assert [f["path"].endswith("beamer.cls") for f in manifest["tex"]["files"]] == [True]
    assert manifest["deck_name"] == "t-Deck"
    assert manifest["framework_dir"] == "SlideMage/latex"
    # one wrapper, one seeded footer stamp and one reference PDF per job
    jobnames = [j["jobname"] for j in manifest["jobs"]]
    assert jobnames == ["t-Deck", "t-Deck-presenter"]
    for job in manifest["jobs"]:
        assert (proj / job["wrapper"]).is_file()
        assert (proj / ".build" / job["jobname"] / f"{job['jobname']}.timestamp").is_file()
        assert (snap / "reference-pdf" / f"{job['jobname']}.pdf").is_file()
        assert job["timestamp"] == "2026-10-07 14:12"
    assert (proj / "decks" / "_snapshot_t-Deck-presenter.tex").read_text(encoding="utf-8") \
        .startswith("\\def\\SMPresenterModeOverride{1}")
    # the project's own deck folder holds no leftover wrapper
    assert not list((root / "decks").glob("_snapshot_*"))
    # every file is hashed in the manifest
    listed = {f["path"] for f in manifest["files"]}
    on_disk = {p.relative_to(snap).as_posix() for p in snap.rglob("*") if p.is_file()}
    assert listed == on_disk - {"snapshot.json"}
    # marked as a read-only snapshot for SlideMage
    pj = json.loads((proj / ".slidemage" / "project.json").read_text(encoding="utf-8"))
    assert pj["snapshot"]["deck_name"] == "t-Deck" and pj["snapshot"]["read_only"]
    assert (snap / "render.bat").read_bytes().count(b"\r\n") > 5
    assert "SOURCE_DATE_EPOCH=" in (snap / "render.sh").read_text(encoding="utf-8")
    assert "snapshots/" in (root / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert not list((root / "snapshots").glob(".partial-*"))


def test_latex_package_files_are_copied_on_request(tree):
    root, _, decks, _, _ = tree
    result = deck_snapshot.create_snapshot(decks["t-Deck"], options(), print, when=WHEN,
                                           project_root=root)
    assert not (result.path / "texmf").exists()
    manifest = deck_snapshot.read_manifest(result.path)
    # recorded either way: the fonts the PDFs embed, with their files
    assert [f["name"] for f in manifest["tex"]["fonts"]] == ["FiraSans-Light"]
    assert manifest["tex"]["fonts"][0]["path"] == "fonts/opentype/public/fira/FiraSans-Light.otf"
    result = deck_snapshot.create_snapshot(decks["t-Deck"], options(texmf=True), print,
                                           when=WHEN, project_root=root)
    texmf = result.path / "texmf"
    assert (texmf / "tex" / "latex" / "beamer" / "beamer.cls").is_file()
    assert (texmf / "fonts" / "opentype" / "public" / "fira" / "FiraSans-Light.otf").is_file()
    assert (texmf / "README.txt").is_file()
    assert result.counts["texmf"] == 2


def test_each_version_keeps_the_previews_its_compile_read(tmp_path):
    """The instructor compile reads the previews from before its own refresh,
    the versions compiled after it the refreshed ones: one snapshot holds both."""
    root, target = tmp_path / "Proj", tmp_path / "snap" / "Proj"
    preview = write(root / ".previews" / "slide_previews" / "1aa-304-171.png", b"refreshed")
    kept = write(tmp_path / "kept" / "0-1aa-304-171.png", b"as the instructor compile read it")

    def out(copies):
        return deck_snapshot._JobOutput("j", Path("x.pdf"), [preview], "", [], None,
                                        copies=copies)

    assert deck_snapshot.copy_job_previews(
        out({deck_snapshot._norm(preview): kept}), "t-instructor", root, target) == 1
    assert deck_snapshot.copy_job_previews(out({}), "t-after-course", root, target) == 1
    base = target / ".previews"
    assert (base / "t-instructor" / "slide_previews" / "1aa-304-171.png").read_bytes() \
        == b"as the instructor compile read it"
    assert (base / "t-after-course" / "slide_previews" / "1aa-304-171.png").read_bytes() \
        == b"refreshed"
    wrapper = f"\\includegraphics{{{root.as_posix()}/.previews/slide_previews/1aa-304-171.png}}"
    assert deck_snapshot.relative_wrapper(wrapper, root, "t-instructor") == (
        "\\includegraphics{.previews/t-instructor/slide_previews/1aa-304-171.png}")

    text = (f"\\includegraphics[width=1cm]{{{root.as_posix()}/.previews/slide_previews/x.png}}\n"
            "\\input{t-Deck.tex}\n")
    assert deck_snapshot.relative_wrapper(text, root) == (
        "\\includegraphics[width=1cm]{.previews/slide_previews/x.png}\n\\input{t-Deck.tex}\n")


def test_root_of_prefers_the_deepest_root(tmp_path):
    outer, inner = tmp_path / "texlive" / "2026", tmp_path / "texlive" / "2026" / "texmf-dist"
    path = inner / "tex" / "latex" / "x.sty"
    assert deck_snapshot.root_of(path, [outer, inner]) == inner
    assert deck_snapshot.root_of(tmp_path / "elsewhere", [outer, inner]) is None


def record_compile(root: Path, texroot: Path, jobname: str, started: float) -> Path:
    """What compiler.py records after compiling `jobname` of t-Deck: the same
    inputs the fake compile reads, the PDF published to pdf/."""
    from slidemage import compile_records

    fw = root.parent / "SlideMage" / "latex"
    inv = root / ".build" / f"{jobname}-x"
    write(inv / f"{jobname}.fls", "\n".join(f"INPUT {p}" for p in (
        root / "decks" / "t-Deck.tex", root / "Slidemaster_preamble_uni-graz.tex",
        root / "slides" / "1aa-EN-One-current.tex", root / "media" / "used.png",
        fw / "Slidemaster_preamble_base.tex", fw / "beamerthemegotham.sty",
        texroot / "tex" / "latex" / "beamer" / "beamer.cls")) + "\n")
    write(inv / f"{jobname}.log", "Package: beamer 2025/06/02 v3.75\n")
    write(inv / f"{jobname}.timestamp", "\\gdef\\SMCompileTimestampValue{2026-10-06 08:00}\n")
    write(inv / f"{jobname}.blg", f"Found BibTeX data source '{root / 'Slidemaster.bib'}'\n")
    pdf = write(root / "pdf" / f"{jobname}.pdf", f"%PDF fake {jobname}".encode())
    assert compile_records.write_record(root / ".build", jobname, inv, root / "decks" / "_w.tex",
                                        compiler.wrapper_text(compiler.CompileJob(
                                            next(d for d in deck_scan.scan_dir(root / "decks", False)
                                                 if d.name == "t-Deck"),
                                            None, None)), pdf, started)
    return pdf


def test_unchanged_version_is_reused_changed_one_compiled(tree, monkeypatch):
    from slidemage import compile_records

    root, _, decks, calls, _ = tree
    monkeypatch.setattr(compile_records, "engine_version", lambda: "LuaHBTeX 1.22.0")
    texroot = deck_snapshot.tex_roots()[0]
    started = time.time() + 1
    pdf = record_compile(root, texroot, "t-Deck", started)
    lines: list[str] = []
    result = deck_snapshot.create_snapshot(decks["t-Deck"], options(verify=True), lines.append,
                                           when=WHEN, project_root=root)
    assert result.ok, result.error
    # t-Deck reused (only its verification render), the presenter compiled
    assert [c[0] for c in calls] == ["t-Deck-presenter", "t-Deck", "t-Deck-presenter"], [
        line for line in lines if "is compiled" in line]
    assert result.counts["reused"] == 1
    manifest = deck_snapshot.read_manifest(result.path)
    job = manifest["jobs"][0]
    assert job["reused_compile"] and job["source_date_epoch"] == int(started)
    assert job["timestamp"] == "2026-10-06 08:00"
    assert manifest["jobs"][1]["reused_compile"] == ""
    assert (result.path / "reference-pdf" / "t-Deck.pdf").read_bytes() == pdf.read_bytes()
    assert f"{int(started)}" in (result.path / "render.bat").read_text(encoding="utf-8")
    # a slide edit makes it compile again
    calls.clear()
    write(root / "slides" / "1aa-EN-One-current.tex", "slide one, edited\n")
    result = deck_snapshot.create_snapshot(decks["t-Deck"], options(), lines.append,
                                           when=WHEN, project_root=root)
    assert result.ok and [c[0] for c in calls] == ["t-Deck", "t-Deck-presenter"]
    # and --recompile ignores the record
    record_compile(root, texroot, "t-Deck", time.time() + 1)
    calls.clear()
    deck_snapshot.create_snapshot(decks["t-Deck"], options(reuse=False), print, when=WHEN,
                                  project_root=root)
    assert [c[0] for c in calls] == ["t-Deck", "t-Deck-presenter"]


def test_snapshot_of_versioned_deck_compiles_every_version(tree):
    root, _, decks, calls, _ = tree
    deck = decks["t-Deck"]
    deck.supports_version = True
    result = deck_snapshot.create_snapshot(deck, options(), print, when=WHEN, project_root=root)
    assert result.ok, result.error
    assert [c[0] for c in calls] == ["t-Deck-instructor", "t-Deck-during-course",
                                     "t-Deck-after-course", "t-Deck-instructor-presenter"]


def test_zip_snapshot_has_the_folder_tree_and_is_deterministic(tree, tmp_path):
    root, _, decks, _, _ = tree
    result = deck_snapshot.create_snapshot(decks["t-Deck"], options(zip=True), print,
                                           when=WHEN, project_root=root)
    assert result.ok, result.error
    assert result.path == root / "snapshots" / "t-Deck_2026-10-07_14-12.zip"
    with zipfile.ZipFile(result.path) as zf:
        names = zf.namelist()
    assert names[0] == "t-Deck_2026-10-07_14-12/snapshot.json"
    assert all(n.startswith("t-Deck_2026-10-07_14-12/") for n in names)
    assert deck_snapshot.read_manifest(result.path)["deck_name"] == "t-Deck"
    # writing the same tree twice gives the same bytes
    with zipfile.ZipFile(result.path) as zf:
        zf.extractall(tmp_path / "x")
    a, b = tmp_path / "a.zip", tmp_path / "b.zip"
    src = tmp_path / "x" / "t-Deck_2026-10-07_14-12"
    deck_snapshot.write_zip(src, a, "t", WHEN)
    deck_snapshot.write_zip(src, b, "t", WHEN)
    assert a.read_bytes() == b.read_bytes()


def test_failed_compile_leaves_nothing_behind(tree):
    root, _, decks, _, state = tree
    state["fail"].add("t-Deck-presenter")
    result = deck_snapshot.create_snapshot(decks["t-Deck"], options(), print, when=WHEN,
                                           project_root=root)
    assert not result.ok and "did not compile" in result.error
    assert not [p for p in (root / "snapshots").iterdir()]
    assert not list((root / "decks").glob("_snapshot_*"))
    assert not (root / ".gitignore").exists()


def test_file_outside_project_is_a_warning(tree, tmp_path):
    root, _, decks, _, state = tree
    state["leak"] = write(tmp_path / "elsewhere" / "logo.pdf", b"x")
    result = deck_snapshot.create_snapshot(decks["t-Deck"], options(), print, when=WHEN,
                                           project_root=root)
    assert result.ok
    assert any("outside the project" in w for w in result.warnings)


# ---------------------------------------------------------------- verifying

def test_verify_renders_from_the_snapshot_and_passes(tree):
    root, _, decks, calls, _ = tree
    result = deck_snapshot.create_snapshot(decks["t-Deck"], options(verify=True), print,
                                           when=WHEN, project_root=root)
    assert result.ok, result.error
    snap_project = result.path / "Proj"
    # two reference compiles in the project, two renders from the snapshot
    assert [c[1] for c in calls] == [root, root, ] + [
        root / "snapshots" / ".partial-t-Deck_2026-10-07_14-12" / "Proj"] * 2
    assert snap_project.is_dir()


def test_verify_fails_when_the_snapshot_reads_the_project(tree):
    root, _, decks, calls, state = tree
    original = deck_snapshot.run_recorded_compile

    def leaky(cwd, wrapper, jobname, build_dir, env, log, cancel=None):
        out = original(cwd, wrapper, jobname, build_dir, env, log, cancel)
        if cwd != root:   # the verification render reads a project file
            out.inputs.append(root / "media" / "unused.png")
        return out

    deck_snapshot.run_recorded_compile = leaky
    try:
        result = deck_snapshot.create_snapshot(decks["t-Deck"], options(verify=True), print,
                                               when=WHEN, project_root=root)
    finally:
        deck_snapshot.run_recorded_compile = original
    assert not result.ok and "outside the snapshot" in result.error
    assert not list((root / "snapshots").iterdir())


def test_verify_detects_changed_files(tree):
    root, _, decks, _, _ = tree
    result = deck_snapshot.create_snapshot(decks["t-Deck"], options(), print, when=WHEN,
                                           project_root=root)
    write(result.path / "Proj" / "slides" / "1aa-EN-One-current.tex", "edited\n")
    (result.path / "Proj" / "media" / "used.png").unlink()
    report = deck_snapshot.verify_snapshot(result.path, print)
    assert not report.ok
    assert set(report.problems) == {"changed: Proj/slides/1aa-EN-One-current.tex",
                                    "missing: Proj/media/used.png"}


# ---------------------------------------------------------------- several decks

def test_decks_one_by_one_a_failure_does_not_stop_the_rest(tree):
    root, _, decks, calls, state = tree
    state["fail"].add("t-Deck-extra")
    results = deck_snapshot.snapshot_decks(
        [decks["t-Deck"], decks["t-Deck-extra"], decks["t-Other"]], options(), print,
        project_root=root)
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
        cancel=cancel, progress=progress, project_root=root)
    assert results[0].ok
    assert not results[1].ok
    assert results[2].skipped
    assert not list((root / "snapshots").glob(".partial-*"))


def test_old_snapshots_found_by_manifest_and_deleted_only_after_success(tree, monkeypatch):
    root, _, decks, _, state = tree
    earlier = datetime(2026, 9, 30, 10, 5)
    for name, form in (("t-Deck", False), ("t-Deck", True), ("t-Deck-extra", False)):
        deck_snapshot.create_snapshot(decks[name], options(zip=form), print, when=earlier,
                                      project_root=root)
    old = deck_snapshot.find_snapshots(["t-Deck"], root=root)
    # t-Deck-extra's snapshot starts with "t-Deck_"? no -- and it is never t-Deck's
    assert [(s.deck_name, s.is_zip) for s in old] in (
        [("t-Deck", False), ("t-Deck", True)], [("t-Deck", True), ("t-Deck", False)])
    trashed: list[Path] = []

    def fake_trash(path: Path) -> bool:
        trashed.append(path)
        shutil.rmtree(path) if path.is_dir() else path.unlink()
        return True

    monkeypatch.setattr(deck_snapshot, "move_to_trash", fake_trash)
    # a failed new snapshot deletes nothing
    state["fail"].add("t-Deck-presenter")
    results = deck_snapshot.snapshot_decks([decks["t-Deck"]], options(), print,
                                           delete_old=old, project_root=root)
    assert not results[0].ok and trashed == []
    # a successful one deletes exactly the listed old ones
    state["fail"].clear()
    results = deck_snapshot.snapshot_decks([decks["t-Deck"]], options(), print,
                                           delete_old=old, project_root=root)
    assert results[0].ok
    assert sorted(trashed) == sorted(s.path for s in old)
    remaining = deck_snapshot.find_snapshots(root=root)
    assert sorted(s.deck_name for s in remaining) == ["t-Deck", "t-Deck-extra"]


def test_several_snapshots_and_forms_coexist(tree):
    root, _, decks, _, _ = tree
    for form in (False, True, False, True):
        assert deck_snapshot.create_snapshot(decks["t-Deck"], options(zip=form), print,
                                             when=WHEN, project_root=root).ok
    names = sorted(p.name for p in (root / "snapshots").iterdir())
    assert names == ["t-Deck_2026-10-07_14-12", "t-Deck_2026-10-07_14-12.zip",
                     "t-Deck_2026-10-07_14-12_2", "t-Deck_2026-10-07_14-12_2.zip"]
    assert len(deck_snapshot.find_snapshots(["t-Deck"], root=root)) == 4


# ---------------------------------------------------------------- project integration

def test_gitignore_line_added_once(tmp_path):
    write(tmp_path / ".gitignore", "pdf/*.pdf\r\n")
    assert deck_snapshot.ensure_gitignored(tmp_path)
    assert not deck_snapshot.ensure_gitignored(tmp_path)
    text = (tmp_path / ".gitignore").read_bytes().decode("utf-8")
    assert text.count("snapshots/") == 1 and "\r\nsnapshots/\r\n" in text
    assert "\n" not in text.replace("\r\n", "")


def test_project_scans_never_look_inside_snapshots(tmp_path):
    """sm_rename's project-wide globs and deck_scan's deck folders never
    reach into snapshots/, where a snapshot keeps its own copies of decks,
    slides and slide_ids.csv."""
    snap = tmp_path / "snapshots" / "t-X_2026-10-07_14-12" / "Proj"
    for rel in ("slides/1aa-EN-One-current.tex", "decks/t-X.tex", "decks/archive/t-Y.tex",
                "x.tex", "README.md", ".slidemage/project.json"):
        write(snap / rel, "x")
    for pattern in sm_rename.PROJECT_GLOBS:
        assert not list(tmp_path.glob(pattern)), pattern


# ---------------------------------------------------------------- a snapshot opened as a project

@pytest.fixture
def opened_snapshot(tree):
    root, _, decks, _, _ = tree
    result = deck_snapshot.create_snapshot(decks["t-Deck"], options(), print, when=WHEN,
                                           project_root=root)
    assert result.ok
    return result.path / "Proj"


def test_snapshot_project_is_recognized_and_uses_its_own_framework_and_dates(opened_snapshot, tree):
    root = tree[0]
    assert project.is_snapshot(opened_snapshot)
    assert not project.is_snapshot(root)
    assert project.snapshot_info(opened_snapshot)["deck_name"] == "t-Deck"
    assert project.snapshot_manifest(opened_snapshot)["deck_name"] == "t-Deck"

    env = {"TEXINPUTS": "D:/elsewhere", "SLIDEMASTER_LATEX": "D:/live/latex", "PATH": "x"}
    adjusted = project.snapshot_compile_env(opened_snapshot, env)
    assert "TEXINPUTS" not in adjusted
    assert Path(adjusted["SLIDEMASTER_LATEX"]) == opened_snapshot.parent / "SlideMage" / "latex"
    assert adjusted["SOURCE_DATE_EPOCH"] == str(int(WHEN.timestamp()))
    assert adjusted["FORCE_SOURCE_DATE"] == "1" and adjusted["PATH"] == "x"
    # an ordinary project's environment is left alone
    assert project.snapshot_compile_env(opened_snapshot.parent.parent.parent, env) is env


def test_snapshot_compiler_mode(opened_snapshot, monkeypatch, tmp_path):
    """Inside a snapshot: PDFs stay in the snapshot's pdf/ (its
    \\deckoutputfolder belongs to the original project), and a compile's
    build folder gets the seeded footer timestamp."""
    use_project(monkeypatch, opened_snapshot)
    deck = deck_scan.scan_dir(opened_snapshot / "decks", False)[0]
    assert deck.output_folders  # D:/Teaching/Somewhere
    job = compiler.CompileJob(deck, None, None)
    assert compiler.resolve_output_location(job) == (opened_snapshot / "pdf", "t-Deck")
    build = tmp_path / "b"
    build.mkdir()
    compiler._seed_snapshot_timestamp("t-Deck", build)
    assert "2026-10-07 14:12" in (build / "t-Deck.timestamp").read_text(encoding="utf-8")
    # "Remove temp files" leaves the seeds alone, other build output goes
    (opened_snapshot / ".build" / "t-Deck-abc123").mkdir()
    removable = [p.name for p in compiler.removable_build_entries()]
    assert removable == ["t-Deck-abc123"]


def test_snapshot_is_never_migrated_or_updated(opened_snapshot):
    from slidemage import bundled_copies, compat
    from slidemage.compat_types import Change, LAYOUT

    deck_file = opened_snapshot / "decks" / "t-Deck.tex"
    before = deck_file.read_bytes()
    change = Change(id="test", since="v1.0.0", severity=LAYOUT, title="t", description="d",
                    fix="f", migrate=lambda root: {"decks/t-Deck.tex": b"migrated"})
    result = compat.run_update(opened_snapshot, [compat.Pending(change)])
    assert result.errors and not result.changed
    assert deck_file.read_bytes() == before
    bundle = opened_snapshot.parent / "SlideMage" / "latex"
    assert bundled_copies.plan_updates(opened_snapshot, latex_source=bundle,
                                       example_source=None) == []


def test_progress_follows_snapshot_compiles():
    from slidemage import compile_progress

    progress = compile_progress.BatchProgress()
    spec = compile_progress.JobSpec(3, 2)
    keys = [deck_snapshot.progress_key("t-Deck"), deck_snapshot.progress_key("t-Deck", True)]
    progress.reset({k: spec for k in keys})
    progress.feed(f"==== Compiling t-Deck -> {keys[0]} ====")
    progress.feed("Run number 1 of rule 'lualatex'")
    assert progress.active
    progress.feed(f"==== Finished: {keys[0]} ====")
    assert not progress.active and progress.fraction == 0.5
    progress.feed(f"==== Compiling t-Deck -> {keys[1]} ====")
    assert progress.feed(f"==== Finished: {keys[1]} ====")[2] is True   # batch finished


# ---------------------------------------------------------------- real compile (opt-in)

@pytest.mark.skipif(not os.environ.get("SLIDEMAGE_TEX_TESTS") or not shutil.which("latexmk"),
                    reason="real LaTeX compile; set SLIDEMAGE_TEX_TESTS=1")
def test_real_snapshot_of_manual(tmp_path, monkeypatch):
    repo = Path(__file__).resolve().parents[1]
    shutil.copytree(repo / "latex", tmp_path / "latex")
    shutil.copytree(repo / "example", tmp_path / "example",
                    ignore=shutil.ignore_patterns("pdf", ".build", ".previews", "snapshots"))
    root = tmp_path / "example"
    use_project(monkeypatch, root)
    deck = next(d for d in deck_scan.scan_dir(root / "decks", False)
                if d.name == "slidemage-manual")
    deck.supports_version = False
    result = deck_snapshot.create_snapshot(deck, SnapshotOptions(presenter=False), print,
                                           project_root=root)
    assert result.ok, result.error


@pytest.mark.skipif(not os.environ.get("SLIDEMAGE_TEX_TESTS") or not shutil.which("latexmk"),
                    reason="real LaTeX compile; set SLIDEMAGE_TEX_TESTS=1")
@pytest.mark.parametrize("pinned", [False, True], ids=["current", "pinned"])
def test_real_omitslide_is_instructor_only(tmp_path, monkeypatch, pinned):
    import pymupdf

    repo = Path(__file__).resolve().parents[1]
    shutil.copytree(repo / "latex", tmp_path / "latex")
    shutil.copytree(repo / "example", tmp_path / "example",
                    ignore=shutil.ignore_patterns("pdf", ".build", ".previews", "snapshots"))
    root = tmp_path / "example"
    monkeypatch.setenv("SLIDEMASTER_LATEX", str(tmp_path / "latex"))
    monkeypatch.setenv("SLIDEMASTER_PROJECT", str(root))
    use_project(monkeypatch, root)
    omit = (r"\omitslideversion{1an-EN-Slide-Versions}{1-0-0}" if pinned
            else r"\omitslide{1an-EN-Slide-Versions}")
    write(root / "decks" / "omit-test.tex", r"""\documentclass[aspectratio=169]{beamer}
\usetheme{gotham}
\makeatletter\def\input@path{{../}}\makeatother
\input{Slidemaster_preamble_slidemage}
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
        job.footer_timestamp = False
        lines, outcome = [], []
        relocated = threading.Event()

        def finished(ok, path):
            outcome.append((ok, path))
            relocated.set()

        assert compiler.run_job(job, lines.append, on_relocated=finished), "\n".join(lines)
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
