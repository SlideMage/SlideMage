# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""GitHub theme release selection, installation and updates."""
from __future__ import annotations

import hashlib
import io
import json
import shutil
import sys
import urllib.error
from pathlib import Path

import pytest

from conftest import zip_members
from slidemage import theme_sources, themes, updater

REPO = Path(__file__).resolve().parents[1]
FIXTURES = REPO / "tests" / "fixtures" / "theme_package"
FIXTURE = FIXTURES / "sample-theme"
ASSET = FIXTURES / "sample-theme-1.0.0.smtheme"
sys.path.insert(0, str(REPO / "tools"))
import make_theme_package  # noqa: E402

GH = "owner-org/slidemage-theme-sample"
API = f"https://api.github.com/repos/{GH}"


def build(tmp_path: Path, version: str, requires: str = ">=0.10.16", toml_version: str | None = None) -> bytes:
    folder = tmp_path / f"src-{version}-{toml_version}" / "sample-theme"
    shutil.copytree(FIXTURE, folder)
    path = folder / "theme.toml"
    text = path.read_text(encoding="utf-8")
    text = text.replace('version = "1.0.0"', f'version = "{toml_version or version}"')
    text = text.replace('requires_slidemage = ">=0.10.16"', f'requires_slidemage = "{requires}"')
    path.write_text(text, encoding="utf-8")
    return make_theme_package.pack(folder, folder.parent / "dist", app_version="1.999.0").read_bytes()


class FakeGitHub:
    """urlopen for api.github.com: a release list and asset downloads, or an HTTP error for everything."""

    def __init__(self) -> None:
        self.releases: list[dict] = []
        self.files: dict[str, bytes] = {}
        self.error: int | None = None
        self.offline = False
        self.requests: list = []

    def release(self, version, data=None, *, sha=None, draft=False, prerelease=False, body=""):
        data = ASSET.read_bytes() if data is None else data
        rid = 101 + len(self.releases)
        name = f"sample-theme-{version}.smtheme"
        url = f"{API}/releases/assets/{rid}1"
        digest_url = f"{API}/releases/assets/{rid}2"
        self.files[url] = data
        assets = [{"name": name, "url": url, "size": len(data)}]
        if sha != "missing":
            digest = sha or hashlib.sha256(data).hexdigest()
            self.files[digest_url] = f"{digest}  {name}\n".encode()
            assets.append({"name": name + ".sha256", "url": digest_url, "size": 90})
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


def install_newest():
    fetched, passed = theme_sources.newest_eligible(GH)
    assert fetched is not None, passed
    return theme_sources.install(fetched), passed


@pytest.mark.parametrize("text", [" SlideMage/slidemage-theme-uni-graz ",
                                  "github.com/SlideMage/slidemage-theme-uni-graz.git"])
def test_a_repository_is_owner_slash_name_or_its_address(text):
    assert theme_sources.parse_repository(text) == "SlideMage/slidemage-theme-uni-graz"


@pytest.mark.parametrize("text", ["slidemage-theme", "../x"])
def test_anything_else_is_refused(text):
    with pytest.raises(theme_sources.SourceError, match="owner/name"):
        theme_sources.parse_repository(text)


def test_a_release_without_its_sha256_is_not_a_candidate(github):
    github.release("1.0.0", sha="missing")
    assert theme_sources.newest_eligible(GH) == (None, [])


def test_a_release_failing_a_check_is_passed_over_for_the_next_older_one(github, tmp_path):
    # Normalize CRLF in the packed fixture comparison.
    assert zip_members(make_theme_package.pack(FIXTURE, tmp_path)) == zip_members(ASSET)
    data = ASSET.read_bytes()
    assert hashlib.sha256(data).hexdigest() == ASSET.with_suffix(".smtheme.sha256").read_text().split()[0]
    github.release("1.0.0", data)
    github.release("2.0.0", data, draft=True)
    github.release("2.1.0", data, prerelease=True)
    github.release("1.1.0", build(tmp_path, "1.1.0", requires=">=1.99"))
    github.release("1.2.0", build(tmp_path, "1.2.0", toml_version="1.2.1"))
    github.release("1.3.0", build(tmp_path, "1.3.0"), sha="0" * 64)
    manifest, passed = install_newest()
    assert (manifest.id, manifest.version) == ("sample-theme", "1.0.0")
    source = theme_sources.read_source(manifest.id)
    assert (source.repository, source.version, source.release_id) == (GH, "1.0.0", 101) and source.installed_at
    assert all(r.get_header("Authorization") == "Bearer github_pat_test" for r in github.requests)
    assert not list(Path(theme_sources.tempfile.gettempdir()).glob("slidemage-theme-*/sample-theme-1.0.0.smtheme"))
    assert [p.split(":")[0] for p in passed] == ["v1.3.0", "v1.2.0", "v1.1.0"]
    assert "does not match its .sha256" in passed[0]
    assert "says version 1.2.1" in passed[1]
    assert "needs SlideMage >=1.99" in passed[2]


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
    with pytest.raises(theme_sources.SourceError, match=words) as caught:
        theme_sources.newest_eligible(GH)
    if code != 404 and token:
        assert "owner-org" in str(caught.value) and "Contents: Read-only" in str(caught.value)


def test_updates_ignore_skipped_and_withdrawn_releases(github, tmp_path):
    github.release("1.0.0")
    install_newest()
    assert theme_sources.check_updates() == ([], {})
    github.release("1.1.0", build(tmp_path, "1.1.0"))
    offers, errors = theme_sources.check_updates()
    offer, = offers
    assert not errors and (offer.installed_version, offer.fetched.release.version) == ("1.0.0", "1.1.0")
    assert themes.installed()[0].manifest.version == "1.0.0"
    offer.fetched.discard()
    theme_sources.skip_version("sample-theme", "1.1.0")
    assert theme_sources.check_updates() == ([], {})
    github.release("2.0.0", build(tmp_path, "2.0.0"))
    offers, _ = theme_sources.check_updates()
    assert offers[0].fetched.release.version == "2.0.0" and offers[0].major
    offers[0].fetched.discard()
    github.releases[-1]["prerelease"] = True
    assert theme_sources.check_updates() == ([], {})


def test_check_failure_preserves_the_install_and_file_reinstall_disables_checks(github):
    github.release("1.0.0")
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
    themes.install_file(ASSET)
    github.requests.clear()
    assert theme_sources.read_source("sample-theme") is None
    assert theme_sources.check_updates() == ([], {}) and github.requests == []
