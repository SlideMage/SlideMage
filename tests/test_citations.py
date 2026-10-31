# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Citation format packages (citations.py, citation_sources.py, docs/CITATION_PACKAGE.md,
tools/make_citation_package.py): the citation.toml and package rules, packing, installing from a file and removing,
TEXINPUTS order for compiles and previews, GitHub releases and update offers (against a fake GitHub API), the
compatibility entry, and \\SMCitationFormat chosen by a deck in a compiled throwaway project. The fixture package
tests/fixtures/citation_package/sample-format has no institution content."""
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

from slidemage import (citation_sources, citations, compat, compat_citation_format, compiler, preview_equivalence,
                       project, theme_sources, updater)
from slidemage.project import ProjectContext

REPO = Path(__file__).resolve().parents[1]
FIXTURES = REPO / "tests" / "fixtures" / "citation_package"
FIXTURE = FIXTURES / "sample-format"
ASSET = FIXTURES / "sample-1.0.0.smcite"
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


def manifest(**changes) -> str:
    text = TOML
    for key, value in changes.items():
        text = "\n".join(f'{key} = "{value}"' if line.startswith(f"{key} =") else line for line in text.split("\n"))
    return text


# -- the manifest

def test_the_fixture_manifest_parses():
    m = citations.parse_manifest(TOML)
    assert (m.id, m.version, m.format_file) == ("sample", "1.0.0", "SlideMage_citation_sample.tex")


@pytest.mark.parametrize("changes, message", [
    ({"id": "A"}, "id"), ({"id": "default"}, None), ({"version": "1.0"}, "version"),
    ({"requires_slidemage": "new"}, "requires_slidemage"), ({"homepage": "ftp://x"}, "homepage"),
])
def test_a_broken_manifest_is_refused(changes, message):
    if message is None:                          # a valid manifest, refused for the key it takes
        parsed = citations.parse_manifest(manifest(**changes))
        with pytest.raises(citations.CitationError, match="ships"):
            citations.check_manifest(parsed)
        return
    with pytest.raises(citations.CitationError, match=message):
        citations.parse_manifest(manifest(**changes))


@pytest.mark.parametrize("extra", ['api_version = 1', 'needs = []', 'network = []', 'layout = "fira"'])
def test_plugin_and_theme_fields_are_refused(extra):
    with pytest.raises(citations.CitationError, match="does not belong"):
        citations.parse_manifest(TOML + extra + "\n")


def test_requires_slidemage_must_accept_this_slidemage(folder):
    (folder / "citation.toml").write_text(manifest(requires_slidemage=">=99.0.0"), encoding="utf-8")
    with pytest.raises(citations.CitationError, match="needs SlideMage"):
        citations.check_folder(folder)


# -- the package rules

def test_the_fixture_folder_passes(folder):
    assert citations.check_folder(folder).id == "sample"


def test_extra_tex_files_must_carry_the_formats_prefix(folder):
    (folder / "SlideMage_citation_sample_extra.bbx").write_text("x", encoding="utf-8")
    citations.check_folder(folder)
    (folder / "authoryear.cbx").write_text("x", encoding="utf-8")
    with pytest.raises(citations.CitationError, match="not part of a citation package"):
        citations.check_folder(folder)


@pytest.mark.parametrize("name", ["foo.sty", "SlideMage_citation_other.tex", "SlideMage_citation_sample_.tex",
                                  "x.dll", "SlideMage_citation_sample_x.sty"])
def test_other_files_are_refused(folder, name):
    (folder / name).write_text("x", encoding="utf-8")
    with pytest.raises(citations.CitationError):
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


@pytest.mark.parametrize("missing", ["README.md", "CHANGELOG.md", "LICENSE", "SlideMage_citation_sample.tex"])
def test_required_files_must_be_there(folder, missing):
    (folder / missing).unlink()
    with pytest.raises(citations.CitationError, match="has no"):
        citations.check_folder(folder)


def test_hidden_files_are_skipped_only_when_asked(folder):
    (folder / ".git").mkdir()
    (folder / ".git" / "config").write_text("x", encoding="utf-8")
    (folder / ".gitignore").write_text("x", encoding="utf-8")
    with pytest.raises(citations.CitationError):
        citations.check_folder(folder)
    assert citations.check_folder(folder, skip_hidden=True).id == "sample"


# -- packing and installing

def test_the_fixture_asset_is_the_packed_fixture_folder(tmp_path):
    assert make_citation_package.pack(FIXTURE, tmp_path).read_bytes() == ASSET.read_bytes()
    expected = (FIXTURES / "sample-1.0.0.smcite.sha256").read_text(encoding="utf-8").split()[0]
    assert hashlib.sha256(ASSET.read_bytes()).hexdigest() == expected


def test_packing_is_reproducible_and_writes_the_checksum(folder, tmp_path):
    first = make_citation_package.pack(folder, tmp_path / "a")
    second = make_citation_package.pack(folder, tmp_path / "b")
    assert first.read_bytes() == second.read_bytes() and first.name == "sample-1.0.0.smcite"
    digest, name = Path(str(first) + ".sha256").read_text(encoding="utf-8").split()
    assert digest == hashlib.sha256(first.read_bytes()).hexdigest() and name == first.name
    with zipfile.ZipFile(first) as zf:
        assert zf.namelist()[0] == "citation.toml"


def test_the_tool_exits_1_with_the_reason_for_a_broken_folder(folder, tmp_path, capsys):
    (folder / "README.md").unlink()
    assert make_citation_package.main([str(folder), "--out", str(tmp_path / "dist")]) == 1
    assert "README.md" in capsys.readouterr().err


def test_install_file_unpacks_into_the_config_folder_and_replaces(package):
    m = citations.install_file(package)
    target = project.config_dir() / "citations" / "sample"
    assert m.id == "sample" and (target / "SlideMage_citation_sample.tex").is_file()
    assert [c.key for c in citations.installed()] == ["sample"] and citations.citation_dirs() == [target]
    (target / "stale.txt").write_text("x", encoding="utf-8")
    citations.install_file(package)
    assert not (target / "stale.txt").exists()
    assert not (project.config_dir() / "citations" / ".staging").exists()


def test_a_wrong_checksum_installs_nothing(package):
    with pytest.raises(citations.CitationError, match="checksum"):
        citations.install_file(package, expected_sha256="0" * 64)
    assert citations.installed() == []


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


def test_peek_reads_the_manifest_without_installing(package):
    assert citations.peek(package).name == "Sample Format" and citations.installed() == []


def test_remove_deletes_the_folder(package):
    citations.install_file(package)
    citations.remove("sample")
    assert citations.installed() == [] and citations.citation_dirs() == []
    with pytest.raises(citations.CitationError, match="not installed"):
        citations.remove("sample")
    with pytest.raises(citations.CitationError):
        citations.remove("../x")


def test_a_folder_with_a_broken_manifest_is_listed_with_its_problem(tmp_path):
    broken = project.config_dir() / "citations" / "broken"
    broken.mkdir(parents=True)
    (broken / "citation.toml").write_text("id = ", encoding="utf-8")
    (item,) = citations.installed()
    assert item.manifest is None and "TOML" in item.problem and citations.citation_dirs() == []


# -- TEXINPUTS and who wins

def test_no_package_leaves_the_environment_as_it_was(monkeypatch):
    monkeypatch.delenv("TEXINPUTS", raising=False)
    assert citations.texinputs() is None


def test_installed_formats_go_on_texinputs_in_front_of_the_themes_for_every_compile(package, tmp_path, monkeypatch):
    from slidemage import themes
    citations.install_file(package)
    theme_dir = project.config_dir() / "themes" / "zzz"
    theme_dir.mkdir(parents=True)
    (theme_dir / "SlideMage_template_zzz.tex").write_text("x", encoding="utf-8")
    monkeypatch.setenv("TEXINPUTS", "mine")
    ctx = ProjectContext(root=tmp_path / "proj")
    env = compiler.build_env(ctx)
    cdir = str(project.config_dir() / "citations" / "sample")
    assert env["TEXINPUTS"] == os.pathsep.join([cdir, str(theme_dir), "mine"])
    assert themes.installed_dirs() == [theme_dir]
    monkeypatch.delenv("TEXINPUTS")
    assert compiler.build_env(ctx)["TEXINPUTS"] == os.pathsep.join([cdir, str(theme_dir), ""])


def test_a_snapshot_compile_gets_no_citation_folders(package, tmp_path, monkeypatch):
    citations.install_file(package)
    monkeypatch.delenv("TEXINPUTS", raising=False)
    monkeypatch.setattr(project, "is_snapshot", lambda root: True)
    assert "sample" not in compiler.build_env(ProjectContext(root=tmp_path / "proj")).get("TEXINPUTS", "")


def test_preview_equivalence_accepts_exactly_the_installed_search_path(package, tmp_path, monkeypatch):
    citations.install_file(package)
    monkeypatch.delenv("TEXINPUTS", raising=False)
    ctx = ProjectContext(root=tmp_path / "proj")
    (ctx.root).mkdir()
    assert preview_equivalence._framework(ctx, {}) != "custom TEXINPUTS search path"
    monkeypatch.setenv("TEXINPUTS", "mine")
    assert preview_equivalence._framework(ctx, {}) == "custom TEXINPUTS search path"


def test_citation_of_finds_the_folder_a_file_lies_in(package, tmp_path):
    citations.install_file(package)
    target = project.config_dir() / "citations" / "sample"
    assert citations.citation_of(target / "SlideMage_citation_sample.tex") == target
    assert citations.citation_of(tmp_path / "other.tex") is None


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


def test_the_newest_eligible_release_is_installed_and_its_source_recorded(github):
    github.release("0.9.0", ASSET.read_bytes(), name="sample-0.9.0.smcite")      # its toml says 1.0.0: passed over
    github.release("1.0.0", ASSET.read_bytes())
    github.release("2.0.0", ASSET.read_bytes(), draft=True)
    fetched, passed = citation_sources.newest_eligible(GH)
    assert fetched is not None and passed == []
    manifest = citation_sources.install(fetched)
    assert (manifest.id, manifest.version) == ("sample", "1.0.0")
    source = citation_sources.read_source("sample")
    assert source.repository == GH and source.version == "1.0.0"
    assert not fetched.archive.parent.exists()
    assert [g[1].repository for g in citation_sources.github_citations()] == [GH]


def test_a_theme_asset_is_not_a_citation_release(github):
    github.release("1.0.0", ASSET.read_bytes(), name="sample-1.0.0.smtheme")
    assert citation_sources.newest_eligible(GH) == (None, [])
    assert citation_sources.list_releases(GH) == []


def test_a_release_whose_download_does_not_match_is_passed_over(github):
    github.release("1.0.0", ASSET.read_bytes())
    github.files[f"{API}/releases/assets/1012"] = ("0" * 64 + "  sample-1.0.0.smcite\n").encode()
    fetched, passed = citation_sources.newest_eligible(GH)
    assert fetched is None and "does not match" in passed[0]


def test_updates_are_offered_only_for_newer_releases_and_skipping_is_remembered(github, folder, tmp_path):
    github.release("1.0.0", ASSET.read_bytes())
    fetched, _ = citation_sources.newest_eligible(GH)
    citation_sources.install(fetched)
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
    citations_dir_listing = [p.name for p in (project.config_dir() / "citations").iterdir()]
    assert citations_dir_listing == ["sample"]
    assert citation_sources.install(citation_sources.newest_eligible(GH)[0]).version == "1.1.0"


def test_a_failed_check_is_recorded_and_leaves_the_installed_format_alone(github):
    github.release("1.0.0", ASSET.read_bytes())
    citation_sources.install(citation_sources.newest_eligible(GH)[0])
    github.error = 404
    offers, errors = citation_sources.check_updates()
    assert offers == [] and "No published release" in errors["sample"]
    assert "No published release" in citation_sources.read_source("sample").check_error
    assert [c.key for c in citations.installed()] == ["sample"]


def test_a_format_installed_from_a_file_has_no_source_and_is_never_checked(package):
    citations.install_file(package)
    assert citation_sources.read_source("sample") is None and citation_sources.github_citations() == []


# -- the compatibility entry

def _root(tmp_path, template: str):
    (tmp_path / "SlideMage_template_acme.tex").write_bytes(template.encode())
    return tmp_path


LEGACY = BS + "input{SlideMage_bibliography_default}"


def test_the_compat_entry_removes_the_line_and_its_introducing_comment_keeping_line_endings(tmp_path):
    root = _root(tmp_path, BS + "input{SlideMage_base}\r\n\r\n% The house citation format.\r\n" + LEGACY + "\r\nmore\r\n")
    assert [f.line for f in compat_citation_format.detect(root)] == [4]
    plan = compat_citation_format.migrate(root)
    assert plan[Path("SlideMage_template_acme.tex")].decode() == BS + "input{SlideMage_base}\r\n\r\nmore\r\n"
    (root / "SlideMage_template_acme.tex").write_bytes(plan[Path("SlideMage_template_acme.tex")])
    assert compat_citation_format.detect(root) == [] and compat_citation_format.migrate(root) == {}


def test_a_comment_that_is_not_about_the_format_stays(tmp_path):
    root = _root(tmp_path, "% colors below\n" + LEGACY + "\n")
    plan = compat_citation_format.migrate(root)
    assert plan[Path("SlideMage_template_acme.tex")].decode() == "% colors below\n"
    root = _root(tmp_path, "% one\n% bibliography\n" + LEGACY + "\n")
    assert compat_citation_format.migrate(root)[Path("SlideMage_template_acme.tex")].decode() == "% one\n% bibliography\n"


@pytest.mark.parametrize("text", [
    BS + "renewcommand{" + BS + "SMCitationFormat}{apa}\n" + LEGACY + "\n",          # another format chosen
    LEGACY + "\n" + BS + "renewcommand{" + BS + "SMBibliographyStyle}{x}\n",         # customised after the default
    "% " + LEGACY + "\n", "no line at all\n",
])
def test_the_compat_entry_leaves_a_template_that_is_not_plain_default_alone(tmp_path, text):
    root = _root(tmp_path, text)
    assert compat_citation_format.detect(root) == [] and compat_citation_format.migrate(root) == {}


def test_the_compat_entry_is_registered_and_not_breaking():
    change = next(c for c in compat.CHANGES if c.id == compat_citation_format.CHANGE_ID)
    assert change.since == "v0.13.0" and "SMCitationFormat" in change.description and "SMCitationFormat" in change.fix


# -- \SMCitationFormat chosen by a deck, compiled

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


DECK = (BS + "documentclass[aspectratio=169]{beamer}\n" + BS + "input{SlideMage_template_greyscale}\n"
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
def test_the_default_is_loaded_for_a_plain_deck_and_a_legacy_input_changes_nothing(tmp_path):
    plain = _compile(tmp_path, DECK % "", [])
    assert "SM-CITATION-SAMPLE" not in plain and not compiler.FATAL_ERROR_RE.search(plain), plain[-1500:]
    assert "SlideMage_citation_default.tex" in plain
    legacy = _compile(tmp_path, DECK % (BS + "input{SlideMage_bibliography_default}\n"), [])
    assert not compiler.FATAL_ERROR_RE.search(legacy), legacy[-1500:]
    assert "SlideMage_bibliography_default.tex" in legacy


@needs_tex
def test_a_missing_format_is_an_error_naming_the_key(tmp_path):
    log = _compile(tmp_path, DECK % (BS + "renewcommand{" + BS + "SMCitationFormat}{nowhere}\n"), [])
    assert 'The citation format "nowhere" is not available' in log


@needs_tex
def test_a_decks_own_redefinition_still_wins_over_the_templates_format(tmp_path):
    log = _compile(tmp_path, DECK % (BS + "renewcommand{" + BS + "SMBibliographyStyle}{" + BS
                                       + "typeout{SM-DECK-STYLE}}\n"), [])
    assert "SM-DECK-STYLE" in log and not compiler.FATAL_ERROR_RE.search(log), log[-1500:]
