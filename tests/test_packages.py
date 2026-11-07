# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The shared store must preserve the previous package when publishing a checked update fails."""
from pathlib import Path
import zipfile

import pytest

from slidemage import citations, packages, themes
from slidemage.plugins import installer


FIXTURES = Path(__file__).parent / "fixtures"


def fail_replace(monkeypatch, call):
    replace = installer.os.replace
    calls = []

    def replace_or_fail(source, target):
        calls.append((source, target))
        if len(calls) == call:
            raise OSError("swap failed")
        return replace(source, target)

    monkeypatch.setattr(installer.os, "replace", replace_or_fail)
    return calls


def test_swap_restores_the_old_folder_when_the_second_replace_fails(tmp_path, monkeypatch):
    staging, final, old = (tmp_path / name for name in ("staging", "final", ".old/backup"))
    staging.mkdir()
    final.mkdir()
    (staging / "new").write_bytes(b"new")
    (final / "original").write_bytes(b"old")
    calls = fail_replace(monkeypatch, 2)

    with pytest.raises(OSError, match="swap failed"):
        installer.swap_into_place(staging, final, old)

    assert calls == [(final, old), (staging, final), (old, final)]
    assert (final / "original").read_bytes() == b"old"
    assert not (final / "new").exists() and not old.exists()
    assert (staging / "new").read_bytes() == b"new"


@pytest.mark.parametrize("module, fixture", [(themes, "theme_package/sample-theme"),
                                             (citations, "citation_package/sample-format")])
@pytest.mark.parametrize("failed_call", [1, 2])
def test_failed_package_update_keeps_the_installed_files_and_cleans_staging(
        module, fixture, failed_call, tmp_path, monkeypatch):
    kind = module.KIND
    source = FIXTURES / fixture
    archive = tmp_path / ("package" + kind.suffix)

    def pack(version):
        with zipfile.ZipFile(archive, "w") as zf:
            for path in source.rglob("*"):
                if path.is_file():
                    data = path.read_bytes()
                    if path.name == kind.manifest_name:
                        data = data.replace(b'"1.0.0"', f'"{version}"'.encode())
                    zf.writestr(path.relative_to(source).as_posix(), data)

    pack("1.0.0")
    manifest = module.install_file(archive)
    final = kind.folder() / manifest.id
    before = {p.relative_to(final): p.read_bytes() for p in final.rglob("*") if p.is_file()}
    pack("1.1.0")
    calls = fail_replace(monkeypatch, failed_call)

    with pytest.raises(kind.error) as caught:
        module.install_file(archive)

    assert str(caught.value) == f"The {kind.name} could not be put in place (is a compile using it?): swap failed"
    assert len(calls) == (3 if failed_call == 2 else 1)
    assert {p.relative_to(final): p.read_bytes() for p in final.rglob("*") if p.is_file()} == before
    assert module.read_manifest(final).version == "1.0.0"
    assert sorted(p.name for p in kind.folder().iterdir()) == [manifest.id]
    installed = module.installed()[0]
    assert isinstance(installed, packages.InstalledPackage) and installed.manifest == manifest


def test_github_sources_with_the_same_key_stay_separate_between_kinds():
    from slidemage import citation_sources, theme_sources

    key = "shared-key"
    for module, sources, fixture, repository in [
        (themes, theme_sources, "theme_package/sample-theme", "owner/theme"),
        (citations, citation_sources, "citation_package/sample-format", "owner/citation"),
    ]:
        kind = module.KIND
        folder = kind.folder() / key
        folder.mkdir(parents=True)
        text = (FIXTURES / fixture / kind.manifest_name).read_text(encoding="utf-8")
        manifest = module.parse_manifest(text)
        (folder / kind.manifest_name).write_text(text.replace(f'id = "{manifest.id}"', f'id = "{key}"'),
                                                encoding="utf-8")
        assert sources.read_source(key) is None
        sources.write_source(key, sources.Source(repository, "1.0.0", 1, "installed"))
        assert sources.source_path(key) == folder / "source.json"

    theme_sources.record_check(key, "no access")
    citation_sources.skip_version(key, "2.0.0")
    theme = theme_sources.read_source(key)
    citation = citation_sources.read_source(key)
    assert (theme.repository, theme.check_error, theme.skipped_version) == ("owner/theme", "no access", "")
    assert (citation.repository, citation.check_error, citation.skipped_version) == ("owner/citation", "", "2.0.0")
    assert theme.checked_at and not citation.checked_at
    assert theme_sources.github_themes()[0][0].manifest.id == key
    assert citation_sources.github_citations()[0][0].manifest.id == key
    themes.remove(key)
    assert theme_sources.github_themes() == []
    assert citation_sources.read_source(key) == citation
