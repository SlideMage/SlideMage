# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""HTTPS certificates are verified through the operating system (tls_trust.py): injected at both entry points, a
failure falls back and is logged, and a failed certificate check reads as a sentence."""
from __future__ import annotations

import logging
import ssl
import sys
import urllib.error

import pytest

from slidemage import cli, presenter_app, tls_trust, updater
from slidemage.plugins import catalogue, installer

CERTIFICATE_ERROR = ("<urlopen error [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: unable to get "
                     "issuer certificate (_ssl.c:1010)>")


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    monkeypatch.setattr(tls_trust, "_injected", False)


def certificate_failure() -> urllib.error.URLError:
    return urllib.error.URLError(ssl.SSLCertVerificationError(
        1, "[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: unable to get issuer certificate"))


def count_injections(monkeypatch) -> list:
    import truststore

    calls = []
    monkeypatch.setattr(truststore, "inject_into_ssl", lambda: calls.append(1))
    return calls


def test_inject_calls_truststore_once(monkeypatch):
    calls = count_injections(monkeypatch)
    assert tls_trust.inject() and tls_trust.inject()
    assert tls_trust.injected() and calls == [1]


def test_a_failing_injection_falls_back_and_logs(monkeypatch, caplog):
    import truststore

    def boom():
        raise OSError("no store")
    monkeypatch.setattr(truststore, "inject_into_ssl", boom)
    with caplog.at_level(logging.WARNING, logger="slidemage.tls_trust"):
        assert tls_trust.inject() is False
    assert not tls_trust.injected()
    assert "truststore failed" in caplog.text and "no store" in caplog.text


def test_a_missing_truststore_falls_back_and_logs(monkeypatch, caplog):
    monkeypatch.setitem(sys.modules, "truststore", None)      # import raises ImportError
    with caplog.at_level(logging.WARNING, logger="slidemage.tls_trust"):
        assert tls_trust.inject() is False
    assert "truststore failed" in caplog.text and "ModuleNotFoundError" in caplog.text


def test_the_app_injects_at_startup(monkeypatch):
    calls = []
    monkeypatch.setattr(tls_trust, "inject", lambda: calls.append("inject"))
    monkeypatch.setattr(cli.diagnostics, "setup", lambda *a, **k: calls.append("setup"))
    monkeypatch.setattr(cli.splash, "release_topmost", lambda: None)
    monkeypatch.setattr(cli.splash, "close", lambda: None)
    with pytest.raises(SystemExit):
        cli.main(["--plugin"])          # a path that stops before any window
    assert calls[:2] == ["setup", "inject"]


def test_the_presenter_injects_at_startup(monkeypatch):
    calls = []
    monkeypatch.setattr(tls_trust, "inject", lambda: calls.append("inject"))
    assert presenter_app.main([presenter_app.SELF_TEST_FLAG]) == 1      # not injected: the self-test says so
    assert calls == ["inject"]


def test_the_presenter_self_test_needs_the_injection(monkeypatch):
    monkeypatch.setattr(tls_trust, "inject", lambda: True)
    assert presenter_app.main([presenter_app.SELF_TEST_FLAG]) == 1
    monkeypatch.setattr(tls_trust, "_injected", True)
    assert presenter_app.main([presenter_app.SELF_TEST_FLAG]) == 0


def test_a_certificate_failure_reads_as_a_sentence(caplog):
    with caplog.at_level(logging.WARNING, logger="slidemage.tls_trust"):
        said = tls_trust.certificate_message(certificate_failure(), "https://api.github.com/repos/x/y/releases")
    assert said == ("The certificate of api.github.com could not be checked. If this keeps happening, a proxy or "
                    "security software may be intercepting HTTPS.")
    assert "CERTIFICATE_VERIFY_FAILED" not in said and "CERTIFICATE_VERIFY_FAILED" in caplog.text


def test_other_errors_are_not_certificate_failures():
    assert tls_trust.certificate_message(urllib.error.URLError("no network"), "https://github.com/") is None
    assert tls_trust.certificate_message(OSError("timed out"), "https://github.com/") is None
    assert tls_trust.certificate_message(urllib.error.URLError(CERTIFICATE_ERROR), "https://github.com/")


class Raises:
    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        raise certificate_failure()

    def __exit__(self, *a):
        return False


def test_every_network_path_shows_the_readable_message(monkeypatch, tmp_path):
    from slidemage import package_sources

    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: Raises())
    said = "could not be checked"
    with pytest.raises(updater.UpdateError, match=said) as caught:
        updater._get_json("https://api.github.com/x", 1)
    assert "CERTIFICATE_VERIFY_FAILED" not in str(caught.value)
    release = updater.Release(tag="v1", page_url="https://github.com/x", asset_url="https://api.github.com/a", asset_size=1)
    with pytest.raises(updater.UpdateError, match=said):
        updater.download(release, tmp_path / "z", lambda done, total: True)
    with pytest.raises(package_sources.SourceError, match=said):
        package_sources._get_json("https://api.github.com/x", "o/r", 1)
    with pytest.raises(package_sources.SourceError, match=said):
        package_sources._download("https://api.github.com/x", tmp_path / "f", "o/r", 10, 1)
    with pytest.raises(catalogue.CatalogueError, match="slidemage.org"):
        catalogue.fetch()
    with pytest.raises(installer.InstallError, match="objects.githubusercontent.com"):
        installer.download("https://objects.githubusercontent.com/f", tmp_path / "g")
