# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Themes from a (private) GitHub repository (theme_sources.py, docs/THEME_PACKAGE.md "From GitHub"), against a fake
GitHub API as the updater's tests do: the newest eligible release, the checks that pass one over, source.json, the
update check and its offers, and the failures that leave the installed theme alone. The fixture asset
tests/fixtures/theme_package/sample-theme-1.0.0.smtheme has no institution content."""
from __future__ import annotations

import hashlib
import io
import json
import shutil
import sys
import urllib.error
from pathlib import Path

import pytest

from slidemage import theme_sources, themes, updater

REPO = Path(__file__).resolve().parents[1]
FIXTURES = REPO / "tests" / "fixtures" / "theme_package"
FIXTURE = FIXTURES / "sample-theme"
ASSET = FIXTURES / "sample-theme-1.0.0.smtheme"
sys.path.insert(0, str(REPO / "tools"))
import make_theme_package  # noqa: E402

GH = "owner-org/slidemage-theme-sample"
API = f"https://api.github.com/repos/{GH}"


def build(tmp_path: Path, version: str, requires: str = ">=10.16", toml_version: str | None = None) -> bytes:
    """The bytes of sample-theme as `version` (its theme.toml saying `toml_version`, if given)."""
    folder = tmp_path / f"src-{version}-{toml_version}" / "sample-theme"
    shutil.copytree(FIXTURE, folder)
    path = folder / "theme.toml"
    text = path.read_text(encoding="utf-8")
    text = text.replace('version = "1.0.0"', f'version = "{toml_version or version}"')
    text = text.replace('requires_slidemage = ">=10.16"', f'requires_slidemage = "{requires}"')
    path.write_text(text, encoding="utf-8")
    asset = make_theme_package.pack(folder, folder.parent / "dist", app_version="99.0.0")
    return asset.read_bytes()


class FakeGitHub:
    """urlopen for api.github.com: a release list and asset downloads, or an HTTP error for everything."""

    def __init__(self) -> None:
        self.releases: list[dict] = []
        self.files: dict[str, bytes] = {}
        self.error: int | None = None
        self.offline = False
        self.requests: list = []
        self._next_id = 100

    def release(self, version: str, data: bytes | None, *, sha: str | None = None, draft=False, prerelease=False,
                body: str = "", name: str | None = None) -> None:
        self._next_id += 1
        rid = self._next_id
        name = name or f"sample-theme-{version}.smtheme"
        assets = []
        if data is not None:
            self.files[f"{API}/releases/assets/{rid}1"] = data
            assets.append({"name": name, "url": f"{API}/releases/assets/{rid}1", "size": len(data)})
            if sha != "missing":
                digest = sha or hashlib.sha256(data).hexdigest()
                self.files[f"{API}/releases/assets/{rid}2"] = f"{digest}  {name}\n".encode()
                assets.append({"name": name + ".sha256", "url": f"{API}/releases/assets/{rid}2", "size": 90})
        self.releases.append({"id": rid, "tag_name": f"v{version}", "draft": draft, "prerelease": prerelease,
                              "body": body, "html_url": f"https://github.com/{GH}/releases/tag/v{version}",
                              "assets": assets})

    def __call__(self, request, timeout=None):
        url = request.full_url
        self.requests.append(request)
        if self.offline:
            raise urllib.error.URLError("no network")
        if self.error:
            raise urllib.error.HTTPError(url, self.error, {404: "Not Found", 403: "Forbidden",
                                                           401: "Unauthorized"}[self.error], {}, None)
        if url == f"{API}/releases?per_page=100":
            return io.BytesIO(json.dumps(self.releases).encode())
        if url in self.files:
            assert request.get_header("Accept") == "application/octet-stream"
            return io.BytesIO(self.files[url])
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)


@pytest.fixture
def github(monkeypatch):
    fake = FakeGitHub()
    monkeypatch.setattr(theme_sources.urllib.request, "urlopen", fake)
    monkeypatch.setenv(updater.TOKEN_ENV_VAR, "github_pat_test")
    return fake


def install_newest(**kwargs):
    fetched, passed = theme_sources.newest_eligible(GH, **kwargs)
    assert fetched is not None, passed
    return theme_sources.install(fetched), passed


# -- the fixture asset

def test_the_fixture_asset_is_the_packed_fixture_folder_and_installs(tmp_path):
    assert make_theme_package.pack(FIXTURE, tmp_path).read_bytes() == ASSET.read_bytes()
    expected = (FIXTURES / "sample-theme-1.0.0.smtheme.sha256").read_text(encoding="utf-8").split()[0]
    assert hashlib.sha256(ASSET.read_bytes()).hexdigest() == expected
    assert themes.install_file(ASSET, expected_sha256=expected).id == "sample-theme"


# -- owner/name

@pytest.mark.parametrize("text", ["SlideMage/slidemage-theme-uni-graz", " SlideMage/slidemage-theme-uni-graz ",
                                  "https://github.com/SlideMage/slidemage-theme-uni-graz",
                                  "github.com/SlideMage/slidemage-theme-uni-graz.git",
                                  "https://github.com/SlideMage/slidemage-theme-uni-graz/"])
def test_a_repository_is_owner_slash_name_or_its_address(text):
    assert theme_sources.parse_repository(text) == "SlideMage/slidemage-theme-uni-graz"


@pytest.mark.parametrize("text", ["", "slidemage-theme", "a/b/c", "../x", "owner/na me", "-owner/x"])
def test_anything_else_is_refused(text):
    with pytest.raises(theme_sources.SourceError, match="owner/name"):
        theme_sources.parse_repository(text)


# -- the newest eligible release

def test_the_newest_published_release_with_both_files_is_installed_and_its_source_recorded(github):
    github.release("0.9.0", ASSET.read_bytes(), name="sample-theme-0.9.0.smtheme")
    github.release("1.0.0", ASSET.read_bytes())
    github.release("2.0.0", ASSET.read_bytes(), draft=True)
    github.release("1.5.0", ASSET.read_bytes(), prerelease=True)
    manifest, passed = install_newest()
    assert (manifest.id, manifest.version, passed) == ("sample-theme", "1.0.0", [])
    source = theme_sources.read_source("sample-theme")
    assert (source.repository, source.version, source.release_id) == (GH, "1.0.0", 102) and source.installed_at
    assert json.loads(theme_sources.source_path("sample-theme").read_text())["repository"] == GH
    assert all(r.get_header("Authorization") == "Bearer github_pat_test" for r in github.requests)
    assert not any("/releases/latest" in r.full_url for r in github.requests)
    assert not list(Path(theme_sources.tempfile.gettempdir()).glob("slidemage-theme-*/sample-theme-1.0.0.smtheme"))


def test_a_release_without_its_sha256_is_not_a_candidate(github):
    github.release("1.0.0", ASSET.read_bytes(), sha="missing")
    assert theme_sources.newest_eligible(GH) == (None, [])


def test_a_release_failing_a_check_is_passed_over_for_the_next_older_one(github, tmp_path):
    github.release("1.0.0", ASSET.read_bytes())
    github.release("1.1.0", build(tmp_path, "1.1.0", requires=">=99"))
    github.release("1.2.0", build(tmp_path, "1.2.0", toml_version="1.2.1"))
    github.release("1.3.0", build(tmp_path, "1.3.0"), sha="0" * 64)
    manifest, passed = install_newest()
    assert manifest.version == "1.0.0"
    assert [p.split(":")[0] for p in passed] == ["v1.3.0", "v1.2.0", "v1.1.0"]
    assert "does not match its .sha256" in passed[0]
    assert "says version 1.2.1" in passed[1]
    assert "needs SlideMage >=99" in passed[2]


def test_installing_from_a_file_drops_the_source_so_it_is_never_updated(github):
    github.release("1.0.0", ASSET.read_bytes())
    install_newest()
    themes.install_file(ASSET)
    assert theme_sources.read_source("sample-theme") is None and theme_sources.github_themes() == []


# -- failures

@pytest.mark.parametrize("code, token, words", [
    (404, True, "Contents: Read-only"),
    (404, False, updater.TOKEN_ENV_VAR),
    (403, True, "resource owner"),
    (401, True, "may have expired"),
    (403, False, "Add a GitHub token"),
])
def test_github_refusals_say_what_the_token_needs(github, monkeypatch, code, token, words):
    if not token:
        monkeypatch.delenv(updater.TOKEN_ENV_VAR)
    github.error = code
    with pytest.raises(theme_sources.SourceError, match=words.replace("(", r"\(")) as caught:
        theme_sources.newest_eligible(GH)
    if code != 404 and token:
        assert "owner-org" in str(caught.value) and "Contents: Read-only" in str(caught.value)


def test_no_network_is_a_source_error(github):
    github.offline = True
    with pytest.raises(theme_sources.SourceError, match="Couldn't reach GitHub"):
        theme_sources.newest_eligible(GH)


# -- updates

def test_the_update_check_offers_a_newer_release_and_installs_nothing_itself(github, tmp_path):
    github.release("1.0.0", ASSET.read_bytes())
    install_newest()
    assert theme_sources.check_updates() == ([], {})
    github.release("1.1.0", build(tmp_path, "1.1.0"), body="A new title bar.")
    offers, errors = theme_sources.check_updates()
    assert errors == {} and [(o.key, o.installed_version, o.fetched.release.version) for o in offers] == [
        ("sample-theme", "1.0.0", "1.1.0")]
    assert not offers[0].major and offers[0].fetched.release.body == "A new title bar."
    assert themes.installed()[0].manifest.version == "1.0.0"
    theme_sources.install(offers[0].fetched)
    assert themes.installed()[0].manifest.version == "1.1.0"
    assert theme_sources.read_source("sample-theme").version == "1.1.0"


def test_a_skipped_version_is_not_offered_again_but_a_later_one_is(github, tmp_path):
    github.release("1.0.0", ASSET.read_bytes())
    install_newest()
    github.release("1.1.0", build(tmp_path, "1.1.0"))
    theme_sources.skip_version("sample-theme", "1.1.0")
    assert theme_sources.check_updates() == ([], {})
    github.release("2.0.0", build(tmp_path, "2.0.0"))
    offers, _ = theme_sources.check_updates()
    assert offers[0].fetched.release.version == "2.0.0" and offers[0].major
    offers[0].fetched.discard()


def test_a_failed_check_is_recorded_and_leaves_the_installed_theme_working(github):
    github.release("1.0.0", ASSET.read_bytes())
    install_newest()
    github.error = 403
    offers, errors = theme_sources.check_updates()
    assert offers == [] and "GitHub refused the saved token" in errors["sample-theme"]
    assert "Contents: Read-only" in theme_sources.read_source("sample-theme").check_error
    assert themes.installed_dirs() == [themes.themes_dir() / "sample-theme"]
    github.error = None
    theme_sources.check_updates()
    source = theme_sources.read_source("sample-theme")
    assert source.check_error == "" and source.checked_at


def test_a_theme_installed_from_a_file_is_never_checked(github):
    themes.install_file(ASSET)
    assert theme_sources.check_updates() == ([], {}) and github.requests == []


def test_a_withdrawn_release_is_no_longer_offered(github, tmp_path):
    github.release("1.0.0", ASSET.read_bytes())
    install_newest()
    github.release("1.1.0", build(tmp_path, "1.1.0"))
    github.releases[-1]["prerelease"] = True
    assert theme_sources.check_updates() == ([], {})
