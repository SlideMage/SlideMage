# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Citation package validation, installation, releases and LaTeX integration."""
from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import urllib.error
import zipfile
from pathlib import Path

import pytest

from slidemage import (citation_sources, citations, compiler,
                       project, theme_sources, updater)
from slidemage.project import ProjectContext

REPO = Path(__file__).resolve().parents[1]
FIXTURE = REPO / "tests" / "fixtures" / "citation_package" / "sample-format"
ASSET = FIXTURE.with_name("sample-1.0.0.smcite")
sys.path.insert(0, str(REPO / "tools"))
import make_citation_package  # noqa: E402

BS = chr(92)
TOML = (FIXTURE / "citation.toml").read_text(encoding="utf-8")


@pytest.fixture
def folder(tmp_path):
    target = tmp_path / "src" / "sample-format"
    shutil.copytree(FIXTURE, target)
    return target


@pytest.fixture
def package(folder, tmp_path):
    return make_citation_package.pack(folder, tmp_path / "dist")


def manifest(key, value):
    return "\n".join(f'{key} = "{value}"' if line.startswith(f"{key} =") else line for line in TOML.split("\n"))

@pytest.mark.parametrize("key, value", [
    ("id", "A"), ("version", "1.0"), ("requires_slidemage", "new"), ("homepage", "ftp://x"),
])
def test_a_broken_manifest_is_refused(key, value):
    with pytest.raises(citations.CitationError, match=key):
        citations.parse_manifest(manifest(key, value))


def test_a_package_cannot_replace_a_bundled_format():
    parsed = citations.parse_manifest(manifest("id", "default"))
    with pytest.raises(citations.CitationError, match="ships"):
        citations.check_manifest(parsed)


@pytest.mark.parametrize("extra", ['api_version = 1', 'layout = "fira"'])
def test_plugin_and_theme_fields_are_refused(extra):
    with pytest.raises(citations.CitationError, match="does not belong"):
        citations.parse_manifest(TOML + extra + "\n")


def test_requires_slidemage_must_accept_this_slidemage(folder):
    (folder / "citation.toml").write_text(manifest("requires_slidemage", ">=1.99.0"), encoding="utf-8")
    with pytest.raises(citations.CitationError, match="needs SlideMage"):
        citations.check_folder(folder)

def test_extra_tex_files_must_carry_the_formats_prefix(folder):
    (folder / "SlideMage_citation_sample_extra.bbx").write_text("x", encoding="utf-8")
    citations.check_folder(folder)
    (folder / "authoryear.cbx").write_text("x", encoding="utf-8")
    with pytest.raises(citations.CitationError, match="not part of a citation package"):
        citations.check_folder(folder)


def test_folders_other_than_licenses_are_refused_and_licenses_may_not_hold_tex(folder):
    (folder / "schemes").mkdir()
    with pytest.raises(citations.CitationError, match="folder"):
        citations.check_folder(folder)
    (folder / "schemes").rmdir()
    (folder / "LICENSES").mkdir()
    (folder / "LICENSES" / "LPPL-1.3c.txt").write_text("text", encoding="utf-8")
    citations.check_folder(folder)
    (folder / "LICENSES" / "x.sty").write_text("x", encoding="utf-8")
    with pytest.raises(citations.CitationError, match="TeX code"):
        citations.check_folder(folder)


def test_hidden_files_are_skipped_only_when_asked(folder):
    (folder / ".git").mkdir()
    (folder / ".git" / "config").write_text("x", encoding="utf-8")
    (folder / ".gitignore").write_text("x", encoding="utf-8")
    with pytest.raises(citations.CitationError):
        citations.check_folder(folder)
    assert citations.check_folder(folder, skip_hidden=True).id == "sample"

def test_packing_is_reproducible_and_writes_the_checksum(folder, tmp_path):
    first = make_citation_package.pack(folder, tmp_path / "a")
    second = make_citation_package.pack(folder, tmp_path / "b")
    assert first.read_bytes() == second.read_bytes() and first.name == "sample-1.0.0.smcite"
    digest, name = Path(str(first) + ".sha256").read_text(encoding="utf-8").split()
    assert digest == hashlib.sha256(first.read_bytes()).hexdigest() and name == first.name


def test_the_tool_exits_1_with_the_reason_for_a_broken_folder(folder, tmp_path, capsys):
    (folder / "README.md").unlink()
    assert make_citation_package.main([str(folder), "--out", str(tmp_path / "dist")]) == 1
    assert "README.md" in capsys.readouterr().err


def test_local_package_can_be_previewed_installed_replaced_and_removed(package, tmp_path):
    assert citations.peek(package).name == "Sample Format" and citations.installed() == []
    with pytest.raises(citations.CitationError, match="checksum"):
        citations.install_file(package, expected_sha256="0" * 64)
    assert citations.installed() == []

    installed = citations.install_file(package)
    target = project.config_dir() / "citations" / "sample"
    tex_file = target / "SlideMage_citation_sample.tex"
    assert installed.id == "sample" and tex_file.is_file()
    assert citations.citation_dirs() == [target]
    assert citations.citation_of(tex_file) == target and citations.citation_of(tmp_path / "other.tex") is None
    assert citation_sources.read_source("sample") is None and citation_sources.github_citations() == []

    stale = target / "stale.txt"
    stale.write_text("x", encoding="utf-8")
    citations.install_file(package)
    assert not stale.exists() and tex_file.is_file()
    assert list(target.parent.iterdir()) == [target]
    with pytest.raises(citations.CitationError):
        citations.remove("../x")
    citations.remove("sample")
    assert not target.exists()


def test_a_bad_archive_installs_nothing(tmp_path):
    bad = tmp_path / "bad.smcite"
    bad.write_bytes(b"not a zip")
    with pytest.raises(citations.CitationError, match="zip"):
        citations.install_file(bad)
    with zipfile.ZipFile(tmp_path / "x.smcite", "w") as zf:
        zf.writestr("citation.toml", TOML)
        zf.writestr("../evil.tex", "x")
    with pytest.raises(citations.CitationError):
        citations.install_file(tmp_path / "x.smcite")
    assert citations.installed() == []


def test_a_folder_with_a_broken_manifest_is_listed_with_its_problem():
    broken = project.config_dir() / "citations" / "broken"
    broken.mkdir(parents=True)
    (broken / "citation.toml").write_text("id = ", encoding="utf-8")
    (item,) = citations.installed()
    assert item.manifest is None and "TOML" in item.problem and citations.citation_dirs() == []

def test_citation_texinputs_precedes_themes_and_is_excluded_from_snapshots(package, tmp_path, monkeypatch):
    citations.install_file(package)
    theme_dir = project.config_dir() / "themes" / "zzz"
    theme_dir.mkdir(parents=True)
    (theme_dir / "SlideMage_template_zzz.tex").write_text("x", encoding="utf-8")
    monkeypatch.setenv("TEXINPUTS", "mine")
    ctx = ProjectContext(root=tmp_path / "proj")
    cdir = str(project.config_dir() / "citations" / "sample")
    assert compiler.build_env(ctx)["TEXINPUTS"] == os.pathsep.join([cdir, str(theme_dir), "mine"])
    monkeypatch.delenv("TEXINPUTS")
    assert compiler.build_env(ctx)["TEXINPUTS"] == os.pathsep.join([cdir, str(theme_dir), ""])
    monkeypatch.setattr(project, "is_snapshot", lambda root: True)
    assert cdir not in compiler.build_env(ctx).get("TEXINPUTS", "")


# -- GitHub

GH = "owner-org/slidemage-citation-sample"
API = f"https://api.github.com/repos/{GH}"


class FakeGitHub:
    def __init__(self) -> None:
        self.releases: list[dict] = []
        self.files: dict[str, bytes] = {}
        self.error: int | None = None
        self._next_id = 100

    def release(self, version: str, data: bytes, *, name: str | None = None, draft=False) -> None:
        self._next_id += 1
        rid = self._next_id
        name = name or f"sample-{version}.smcite"
        self.files[f"{API}/releases/assets/{rid}1"] = data
        self.files[f"{API}/releases/assets/{rid}2"] = f"{hashlib.sha256(data).hexdigest()}  {name}\n".encode()
        self.releases.append({
            "id": rid, "tag_name": f"v{version}", "draft": draft, "prerelease": False, "body": f"notes {version}",
            "html_url": f"https://github.com/{GH}/releases/tag/v{version}",
            "assets": [{"name": name, "url": f"{API}/releases/assets/{rid}1", "size": len(data)},
                       {"name": name + ".sha256", "url": f"{API}/releases/assets/{rid}2", "size": 90}]})

    def __call__(self, request, timeout=None):
        url = request.full_url
        if self.error:
            raise urllib.error.HTTPError(url, self.error, "Not Found", {}, None)
        if url == f"{API}/releases?per_page=100":
            return io.BytesIO(json.dumps(self.releases).encode())
        if url in self.files:
            return io.BytesIO(self.files[url])
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)


@pytest.fixture
def github(monkeypatch):
    fake = FakeGitHub()
    monkeypatch.setattr(theme_sources.urllib.request, "urlopen", fake)
    monkeypatch.setenv(updater.TOKEN_ENV_VAR, "github_pat_test")
    return fake


def packed(folder: Path, tmp_path: Path, version: str) -> bytes:
    text = (folder / "citation.toml").read_text(encoding="utf-8").replace('version = "1.0.0"', f'version = "{version}"')
    (folder / "citation.toml").write_text(text, encoding="utf-8")
    return make_citation_package.pack(folder, tmp_path / f"dist-{version}").read_bytes()


def test_a_theme_asset_is_not_a_citation_release(github):
    github.release("1.0.0", ASSET.read_bytes(), name="sample-1.0.0.smtheme")
    assert citation_sources.newest_eligible(GH) == (None, [])
    assert citation_sources.list_releases(GH) == []


def test_a_release_whose_download_does_not_match_is_passed_over(github):
    github.release("1.0.0", ASSET.read_bytes())
    github.files[f"{API}/releases/assets/1012"] = ("0" * 64 + "  sample-1.0.0.smcite\n").encode()
    fetched, passed = citation_sources.newest_eligible(GH)
    assert fetched is None and "does not match" in passed[0]


def test_github_install_tracks_its_source_and_offers_only_newer_unskipped_releases(github, folder, tmp_path):
    github.release("1.0.0", ASSET.read_bytes())
    github.release("2.0.0", ASSET.read_bytes(), draft=True)
    fetched, passed = citation_sources.newest_eligible(GH)
    assert not passed and citation_sources.install(fetched).version == "1.0.0"
    source = citation_sources.read_source("sample")
    assert (source.repository, source.version) == (GH, "1.0.0")
    assert not fetched.archive.parent.exists()
    offers, errors = citation_sources.check_updates()
    assert offers == [] and errors == {}
    github.release("1.1.0", packed(folder, tmp_path, "1.1.0"))
    offers, errors = citation_sources.check_updates()
    assert errors == {} and [(o.key, o.installed_version, o.fetched.release.version) for o in offers] == \
        [("sample", "1.0.0", "1.1.0")]
    citation_sources.skip_version("sample", "1.1.0")
    offers[0].fetched.discard()
    assert citation_sources.check_updates()[0] == []
    assert citation_sources.read_source("sample").checked_at
    assert [p.name for p in (project.config_dir() / "citations").iterdir()] == ["sample"]
    assert citation_sources.install(citation_sources.newest_eligible(GH)[0]).version == "1.1.0"
    github.error = 404
    offers, errors = citation_sources.check_updates()
    source = citation_sources.read_source("sample")
    assert not offers and "No published release" in errors["sample"]
    assert source.check_error == errors["sample"]
    assert citations.installed()[0].manifest.version == "1.1.0"

# Real deck compiles

needs_tex = pytest.mark.skipif(shutil.which("lualatex") is None, reason="needs a TeX installation")


def _compile(tmp_path: Path, deck: str, extra_texinputs: list[Path]) -> str:
    work = tmp_path / "work"
    work.mkdir(exist_ok=True)
    (work / "SlideMage.bib").write_text("", encoding="utf-8")
    (work / "deck.tex").write_text(deck, encoding="utf-8")
    env = {**os.environ, "TEXINPUTS": os.pathsep.join([str(REPO / "latex"), *map(str, extra_texinputs), ""])}
    subprocess.run(["lualatex", "-interaction=nonstopmode", "deck.tex"], cwd=work, env=env, capture_output=True,
                   timeout=600)
    return (work / "deck.log").read_text(encoding="utf-8", errors="replace")


DECK = (BS + "documentclass[aspectratio=169]{beamer}\n" + BS + "input{SlideMage_template_grayscale}\n"
        + "%s" + BS + "SMUseBibliography\n" + BS + "newcommand{" + BS + "FooterText}{x}\n" + BS + "begin{document}\n" + BS + "begin{frame}x" + BS + "end{frame}\n"
        + BS + "end{document}\n")


@needs_tex
def test_a_deck_chooses_an_installed_format_which_is_loaded_and_applied_once(package, tmp_path):
    citations.install_file(package)
    log = _compile(tmp_path, DECK % (BS + "renewcommand{" + BS + "SMCitationFormat}{sample}\n"),
                   citations.citation_dirs())
    assert log.count("SM-CITATION-SAMPLE-LOADED") == 1 and log.count("SM-CITATION-SAMPLE-APPLIED") == 1
    assert not compiler.FATAL_ERROR_RE.search(log), log[-1500:]


@needs_tex
def test_a_missing_format_is_an_error_naming_the_key(tmp_path):
    log = _compile(tmp_path, DECK % (BS + "renewcommand{" + BS + "SMCitationFormat}{nowhere}\n"), [])
    assert 'The citation format "nowhere" is not available' in log


@needs_tex
def test_a_decks_own_redefinition_still_wins_over_the_templates_format(tmp_path):
    log = _compile(tmp_path, DECK % (BS + "renewcommand{" + BS + "SMBibliographyStyle}{" + BS
                                       + "typeout{SM-DECK-STYLE}}\n"), [])
    assert "SM-DECK-STYLE" in log and not compiler.FATAL_ERROR_RE.search(log), log[-1500:]


@pytest.mark.parametrize("name", ["SlideMage_citation_default.tex", "SlideMage_base.tex"])
def test_a_package_may_not_ship_a_file_named_like_a_framework_file(folder, name):
    (folder / name).write_text("% mine\n", encoding="utf-8")
    with pytest.raises(citations.CitationError, match="named like one of SlideMage's own framework files"):
        citations.check_folder(folder)
