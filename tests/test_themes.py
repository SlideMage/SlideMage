# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Theme packages (themes.py, docs/THEME_PACKAGE.md, tools/make_theme_package.py): the theme.toml and package rules,
packing, installing from a file and removing, TEXINPUTS for compiles and previews, template discovery, and that
deck snapshots and Export LaTeX carry an installed theme's files. The fixture theme tests/fixtures/theme_package/
sample-theme has no institution content."""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from slidemage import compiler, deck_snapshot, project, slide_snapshot, themes
from slidemage.project import ProjectContext

REPO = Path(__file__).resolve().parents[1]
FIXTURE = REPO / "tests" / "fixtures" / "theme_package" / "sample-theme"
sys.path.insert(0, str(REPO / "tools"))
import make_theme_package  # noqa: E402

TOML = (FIXTURE / "theme.toml").read_text(encoding="utf-8")


@pytest.fixture
def theme_folder(tmp_path):
    folder = tmp_path / "src" / "sample-theme"
    shutil.copytree(FIXTURE, folder)
    return folder


@pytest.fixture
def package(theme_folder, tmp_path):
    return make_theme_package.pack(theme_folder, tmp_path / "dist")


def edit_toml(folder: Path, old: str, new: str) -> None:
    path = folder / "theme.toml"
    text = path.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new), encoding="utf-8")


def zip_of(path: Path, members: dict[str, bytes]) -> Path:
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return path


def fixture_members() -> dict[str, bytes]:
    return {p.relative_to(FIXTURE).as_posix(): p.read_bytes() for p in sorted(FIXTURE.rglob("*")) if p.is_file()}


# -- theme.toml

def test_the_fixture_manifest_reads_with_every_field():
    m = themes.parse_manifest(TOML)
    assert (m.id, m.name, m.version, m.requires_slidemage, m.layout) == (
        "sample-theme", "Sample Theme", "1.0.0", ">=10.16", "fira")
    assert m.template_file == "SlideMage_template_sample-theme.tex" and m.scheme_dir == "scheme_sample_theme"
    assert m.author and m.license and m.homepage.startswith("https://") and m.summary


@pytest.mark.parametrize("old, new, words", [
    ('id = "sample-theme"', 'id = "Sample"', "id (the template key)"),
    ('id = "sample-theme"', 'id = "x"', "id (the template key)"),
    ('version = "1.0.0"', 'version = "1.0"', "version must look like 1.2.3"),
    ('requires_slidemage = ">=10.16"', 'requires_slidemage = "10.16"', "requires_slidemage"),
    ('homepage = "https://slidemage.org/plugins/"', 'homepage = "slidemage.org"', "homepage"),
    ('layout = "fira"', 'layout = "Fira Sans"', "layout"),
    ('layout = "fira"\n', '', "layout is missing"),
    ('name = "Sample Theme"', 'name = "' + "x" * 41 + '"', "name must be 1 to 40"),
    ('layout = "fira"', 'layout = "fira"\napi_version = 1', "api_version belongs to plugin.toml"),
    ('layout = "fira"', 'layout = "fira"\nnetwork = []', "network belongs to plugin.toml"),
])
def test_a_bad_manifest_says_which_field(old, new, words):
    assert old in TOML
    with pytest.raises(themes.ThemeError, match="theme.toml") as e:
        themes.parse_manifest(TOML.replace(old, new))
    assert words in str(e.value)


def test_not_toml_at_all_is_a_theme_error():
    with pytest.raises(themes.ThemeError, match="not valid TOML"):
        themes.parse_manifest("id = ")


# -- the package rules

def test_the_fixture_theme_passes_every_check(theme_folder):
    assert themes.check_folder(theme_folder).id == "sample-theme"


@pytest.mark.parametrize("name, words", [
    ("notes.txt", "not part of a theme package"),
    ("beamerthemeSample.sty", "not part of a theme package"),
    ("tools/run.py", "folder that is not part of a theme package"),
    ("schemes/scheme_other/logo.pdf", "must be schemes/scheme_sample_theme/"),
    ("schemes/scheme_sample_theme/hyperref.sty", "TeX code besides its template"),
    ("schemes/scheme_sample_theme/extra.tex", "TeX code besides its template"),
    ("LICENSES/helper.lua", "TeX code besides its template"),
])
def test_files_that_are_not_the_themes_own_are_refused(theme_folder, name, words):
    path = theme_folder / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x", encoding="utf-8")
    with pytest.raises(themes.ThemeError, match=words):
        themes.check_folder(theme_folder)


@pytest.mark.parametrize("name", ["SlideMage_template_sample-theme.tex", "README.md", "CHANGELOG.md", "LICENSE"])
def test_a_required_file_missing_is_refused(theme_folder, name):
    (theme_folder / name).unlink()
    with pytest.raises(themes.ThemeError, match=f"has no {name}"):
        themes.check_folder(theme_folder)


def test_preview_and_licence_texts_and_an_own_layout_profile_are_allowed(theme_folder):
    (theme_folder / "preview.png").write_bytes(b"png")
    (theme_folder / "LICENSES").mkdir()
    (theme_folder / "LICENSES" / "LPPL-1.3c.txt").write_text("text", encoding="utf-8")
    edit_toml(theme_folder, 'layout = "fira"', 'layout = "house"')
    with pytest.raises(themes.ThemeError, match="neither SlideMage's"):
        themes.check_folder(theme_folder)
    (theme_folder / "SlideMage_layout_house.tex").write_text("% profile\n", encoding="utf-8")
    assert themes.check_folder(theme_folder).layout == "house"
    (theme_folder / "SlideMage_layout_other.tex").write_text("% profile\n", encoding="utf-8")
    with pytest.raises(themes.ThemeError, match="not part of a theme package"):     # only the one it names
        themes.check_folder(theme_folder)


def test_the_greyscale_template_and_its_profile_are_bundled():
    """v10.18.0: latex/ ships a second template and a third layout profile; a theme may not take the key, and a theme
    on that profile needs no profile file of its own."""
    assert "greyscale" in themes.bundled_keys()
    assert "lmroman" in themes.BUNDLED_PROFILES


def test_a_key_of_a_bundled_template_is_refused(theme_folder):
    assert "slidemage" in themes.bundled_keys()
    edit_toml(theme_folder, 'id = "sample-theme"', 'id = "slidemage"')
    (theme_folder / "SlideMage_template_sample-theme.tex").rename(theme_folder / "SlideMage_template_slidemage.tex")
    (theme_folder / "schemes" / "scheme_sample_theme").rename(theme_folder / "schemes" / "scheme_slidemage")
    with pytest.raises(themes.ThemeError, match="template SlideMage ships"):
        themes.check_folder(theme_folder)


def test_requires_slidemage_is_checked_against_the_running_version(theme_folder):
    assert themes.check_folder(theme_folder, "v10.16.0")
    with pytest.raises(themes.ThemeError, match=r"needs SlideMage >=10.16; this is v10.15.0"):
        themes.check_folder(theme_folder, "v10.15.0")


# -- tools/make_theme_package.py

def test_pack_writes_the_asset_and_a_sha256sum_file(package):
    assert package.name == "sample-theme-1.0.0.smtheme"
    sidecar = Path(str(package) + ".sha256").read_text(encoding="utf-8")
    assert sidecar == f"{hashlib.sha256(package.read_bytes()).hexdigest()}  sample-theme-1.0.0.smtheme\n"
    with zipfile.ZipFile(package) as zf:
        names = zf.namelist()
    assert names[0] == "theme.toml"
    assert sorted(names) == sorted(fixture_members())


def test_pack_is_reproducible_and_leaves_out_dot_files(theme_folder, tmp_path):
    first = make_theme_package.pack(theme_folder, tmp_path / "a").read_bytes()
    (theme_folder / ".git").mkdir()
    (theme_folder / ".git" / "HEAD").write_text("ref", encoding="utf-8")
    (theme_folder / ".gitignore").write_text("*.pdf", encoding="utf-8")
    second = make_theme_package.pack(theme_folder, tmp_path / "b").read_bytes()
    assert first == second


def test_pack_refuses_what_the_installer_would_refuse(theme_folder, tmp_path, capsys):
    (theme_folder / "README.md").unlink()
    out = tmp_path / "dist"
    assert make_theme_package.main([str(theme_folder), "--out", str(out)]) == 1
    assert "has no README.md" in capsys.readouterr().err
    assert not out.exists() or not any(out.iterdir())


def test_the_command_line_prints_the_asset(theme_folder, tmp_path):
    result = subprocess.run([sys.executable, str(REPO / "tools" / "make_theme_package.py"), str(theme_folder),
                             "--out", str(tmp_path / "dist"), "--app-version", "v10.16.0"],
                            capture_output=True, text=True, check=True)
    assert Path(result.stdout.strip()) == tmp_path / "dist" / "sample-theme-1.0.0.smtheme"


# -- install and remove

def test_install_unpacks_into_the_themes_folder(package):
    assert themes.peek(package).id == "sample-theme"
    manifest = themes.install_file(package)
    folder = themes.themes_dir() / "sample-theme"
    assert manifest.version == "1.0.0" and folder == project.config_dir() / "themes" / "sample-theme"
    assert (folder / "SlideMage_template_sample-theme.tex").is_file()
    assert (folder / "schemes" / "scheme_sample_theme" / "sample-logo.pdf").is_file()
    assert [t.key for t in themes.installed()] == ["sample-theme"] and themes.installed()[0].problem == ""
    assert themes.installed_dirs() == [folder]
    assert sorted(p.name for p in themes.themes_dir().iterdir()) == ["sample-theme"]      # no .staging/.old left


def test_install_replaces_an_installed_version(theme_folder, tmp_path):
    themes.install_file(make_theme_package.pack(theme_folder, tmp_path / "one"))
    edit_toml(theme_folder, 'version = "1.0.0"', 'version = "1.1.0"')
    (theme_folder / "schemes" / "scheme_sample_theme" / "sample-logo.pdf").rename(
        theme_folder / "schemes" / "scheme_sample_theme" / "new-logo.pdf")
    themes.install_file(make_theme_package.pack(theme_folder, tmp_path / "two"))
    folder = themes.themes_dir() / "sample-theme"
    assert themes.read_manifest(folder).version == "1.1.0"
    assert sorted(p.name for p in (folder / "schemes" / "scheme_sample_theme").iterdir()) == ["new-logo.pdf"]


def test_install_checks_the_sha256_it_is_given(package):
    with pytest.raises(themes.ThemeError, match="checksum"):
        themes.install_file(package, expected_sha256="0" * 64)
    assert themes.installed() == []
    themes.install_file(package, expected_sha256=hashlib.sha256(package.read_bytes()).hexdigest())


@pytest.mark.parametrize("member, words", [
    ("../outside.tex", "unsafe path"),
    ("/abs.png", "unsafe path"),
    ("C:/x.png", "unsafe path"),
    ("schemes/scheme_sample_theme/tool.exe", "compiled file"),
    ("extra.sty", "not part of a theme package"),
])
def test_an_archive_with_a_path_outside_the_package_or_foreign_files_installs_nothing(tmp_path, member, words):
    archive = zip_of(tmp_path / "bad.smtheme", {**fixture_members(), member: b"x"})
    with pytest.raises(themes.ThemeError, match=words):
        themes.install_file(archive)
    assert themes.installed() == [] and not (tmp_path / "outside.tex").exists()


def test_an_archive_without_theme_toml_or_not_a_zip_is_refused(tmp_path):
    members = fixture_members()
    del members["theme.toml"]
    with pytest.raises(themes.ThemeError, match="no theme.toml"):
        themes.install_file(zip_of(tmp_path / "a.smtheme", members))
    with pytest.raises(themes.ThemeError, match="no theme.toml"):
        themes.peek(tmp_path / "a.smtheme")
    (tmp_path / "b.smtheme").write_bytes(b"no zip")
    with pytest.raises(themes.ThemeError, match="not a valid zip"):
        themes.install_file(tmp_path / "b.smtheme")
    assert themes.installed() == []


def test_a_bundled_key_or_a_too_new_requirement_installs_nothing(theme_folder, tmp_path):
    archive = make_theme_package.pack(theme_folder, tmp_path / "dist")
    with pytest.raises(themes.ThemeError, match="needs SlideMage"):
        themes.install_file(archive, app_version="v10.15.0")
    members = fixture_members()
    members["theme.toml"] = TOML.replace('id = "sample-theme"', 'id = "slidemage"').encode()
    members["SlideMage_template_slidemage.tex"] = members.pop("SlideMage_template_sample-theme.tex")
    members = {k.replace("scheme_sample_theme", "scheme_slidemage"): v for k, v in members.items()}
    with pytest.raises(themes.ThemeError, match="template SlideMage ships"):
        themes.install_file(zip_of(tmp_path / "s.smtheme", members))
    assert themes.installed() == []


def test_remove_deletes_the_theme(package):
    themes.install_file(package)
    themes.remove("sample-theme")
    assert themes.installed() == [] and themes.installed_dirs() == []
    with pytest.raises(themes.ThemeError, match="not installed"):
        themes.remove("sample-theme")


def test_a_hand_broken_theme_folder_is_listed_with_its_problem_but_not_searched(package):
    themes.install_file(package)
    (themes.themes_dir() / "sample-theme" / "theme.toml").write_text("id = ", encoding="utf-8")
    (themes.themes_dir() / "other").mkdir()
    listed = {t.key: t for t in themes.installed()}
    assert listed["sample-theme"].manifest is None and "not valid TOML" in listed["sample-theme"].problem
    assert "other" in listed
    assert themes.installed_dirs() == [themes.themes_dir() / "sample-theme"]   # "other" has no template file


# -- compiles and previews: TEXINPUTS

def make_ctx(tmp_path: Path) -> ProjectContext:
    root = tmp_path / "proj"
    (root / "decks").mkdir(parents=True, exist_ok=True)
    return ProjectContext.at(root)


def test_no_theme_leaves_the_environment_as_it_was(tmp_path, monkeypatch):
    monkeypatch.delenv("TEXINPUTS", raising=False)
    assert themes.texinputs() is None
    assert "TEXINPUTS" not in compiler.build_env(make_ctx(tmp_path))


def test_installed_themes_go_on_texinputs_for_every_compile(package, tmp_path, monkeypatch):
    themes.install_file(package)
    folder = str(themes.themes_dir() / "sample-theme")
    monkeypatch.delenv("TEXINPUTS", raising=False)
    # the trailing separator keeps the TeX distribution's own search path; the .latexmkrc puts project and framework in front
    assert compiler.build_env(make_ctx(tmp_path))["TEXINPUTS"] == folder + os.pathsep
    monkeypatch.setenv("TEXINPUTS", "mine")
    assert compiler.build_env(make_ctx(tmp_path))["TEXINPUTS"] == folder + os.pathsep + "mine"


def test_a_snapshot_compile_gets_no_theme_folders(package, tmp_path, monkeypatch):
    themes.install_file(package)
    monkeypatch.delenv("TEXINPUTS", raising=False)
    ctx = make_ctx(tmp_path)
    monkeypatch.setattr(project, "is_snapshot", lambda root: True)
    assert "TEXINPUTS" not in compiler.build_env(ctx)
    assert slide_snapshot.template_dirs(ctx.root)[-1] != themes.themes_dir() / "sample-theme"


def test_preview_equivalence_accepts_exactly_the_theme_search_path(package, tmp_path, monkeypatch):
    from slidemage import preview_equivalence
    themes.install_file(package)
    monkeypatch.delenv("TEXINPUTS", raising=False)
    ctx = make_ctx(tmp_path)
    assert preview_equivalence._framework(ctx, {}) != "custom TEXINPUTS search path"
    monkeypatch.setenv("TEXINPUTS", "mine")
    assert preview_equivalence._framework(ctx, {}) == "custom TEXINPUTS search path"


# -- template discovery

def test_an_installed_theme_is_offered_like_a_project_template(package, tmp_path):
    ctx = make_ctx(tmp_path)
    assert "sample-theme" not in slide_snapshot.available_templates(ctx.root)
    themes.install_file(package)
    assert "sample-theme" in slide_snapshot.available_templates(ctx.root)
    assert slide_snapshot.preamble_file("sample-theme", ctx.root) == (
        themes.themes_dir() / "sample-theme" / "SlideMage_template_sample-theme.tex")
    assert slide_snapshot.template_label("sample-theme", ctx.root) == "Sample Theme"


def test_a_project_copy_of_the_same_key_wins(package, tmp_path):
    ctx = make_ctx(tmp_path)
    themes.install_file(package)
    own = ctx.root / "SlideMage_template_sample-theme.tex"
    own.write_text("% SlideMage template name: Frozen copy\n", encoding="utf-8")
    assert slide_snapshot.preamble_file("sample-theme", ctx.root) == own
    assert slide_snapshot.template_label("sample-theme", ctx.root) == "Frozen copy"
    assert slide_snapshot.available_templates(ctx.root).count("sample-theme") == 1


# -- what bundles a deck's template: deck snapshots and Export LaTeX

def test_a_snapshot_holds_an_installed_themes_files_in_its_project_root(package, tmp_path):
    themes.install_file(package)
    folder = themes.themes_dir() / "sample-theme"
    root = tmp_path / "proj"
    root.mkdir()
    inputs = [folder / "SlideMage_template_sample-theme.tex",
              folder / "schemes" / "scheme_sample_theme" / "sample-logo.pdf"]
    out = deck_snapshot._JobOutput(job_name="x", pdf=root / "x.pdf", inputs=inputs, log_text="", bib_sources=[])
    collected = deck_snapshot.collect_files([out], root, [], [], [])
    assert collected.project_files == {
        "SlideMage_template_sample-theme.tex": inputs[0].resolve(),
        "schemes/scheme_sample_theme/sample-logo.pdf": inputs[1].resolve()}
    assert collected.external == []


def test_export_latex_brings_an_installed_themes_template_and_scheme(package, tmp_path):
    from test_latex_export import HEAD, deck_of, make_project
    from slidemage import latex_export
    themes.install_file(package)
    ctx = make_project(tmp_path)
    (ctx.root / "decks" / "themed.tex").write_text(
        HEAD.format(template="sample-theme", calls="\\slide{zz1-EN-One}"), encoding="utf-8")
    dest = tmp_path / "out"
    dest.mkdir()
    result = latex_export.export_deck(ctx, deck_of(ctx, "themed"), dest)
    assert {"SlideMage_template_sample-theme.tex", "schemes/scheme_sample_theme/sample-logo.pdf",
            "SlideMage_layout_fira.tex", "SlideMage_base.tex"} <= set(result.files)
    assert "schemes/scheme_sample_theme/sample-logo.pdf" not in result.missing


@pytest.mark.skipif(os.environ.get("SLIDEMAGE_TEX_TESTS") != "1", reason="needs TeX (SLIDEMAGE_TEX_TESTS=1)")
def test_a_deck_compiles_with_an_installed_theme_and_its_scheme_logo(package, tmp_path):
    from test_latex_export import HEAD, make_project
    themes.install_file(package)
    ctx = make_project(tmp_path)
    (ctx.root / "decks" / "themed.tex").write_text(
        HEAD.format(template="sample-theme", calls="\\slide{zz1-EN-One}"), encoding="utf-8")
    env = dict(compiler.build_env(ctx), SLIDEMAGE_LATEX=str(REPO / "latex"))
    run = subprocess.run(["latexmk", "decks/themed.tex"], cwd=ctx.root, env=env, capture_output=True,
                         text=True, encoding="utf-8", errors="replace", timeout=600)
    assert (ctx.root / "decks" / "themed.pdf").is_file(), run.stdout[-3000:]
    fls = next((ctx.root / ".build").glob("themed.fls")).read_text(encoding="utf-8", errors="replace")
    assert "sample-logo.pdf" in fls and "themes" in fls.replace("\\", "/")
