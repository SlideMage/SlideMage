# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""packaging/make_signing_key.py and packaging/sign_release.py, with throwaway keys made inside the test."""
import hashlib
import importlib.util
from pathlib import Path

import pytest

from slidemage import release_signing

PACKAGING = Path(__file__).resolve().parent.parent / "packaging"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, PACKAGING / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


make_signing_key = _load("make_signing_key")
sign_release = _load("sign_release")


def test_signing_requires_a_trusted_key_and_produces_a_verifiable_signature(tmp_path, monkeypatch, capsys):
    private, public = make_signing_key.make_key()
    text = make_signing_key.instructions(private, public)
    assert release_signing.SIGNING_KEY_SECRET in text and public in text and "release_signing.py" in text
    zip_path = tmp_path / "SlideMage-linux.zip"
    zip_path.write_bytes(b"zip bytes")
    secret = release_signing.SIGNING_KEY_SECRET
    signature_path = zip_path.with_suffix(".zip.sig")
    monkeypatch.delenv(secret, raising=False)
    assert sign_release.main([str(zip_path)]) == 1
    assert "is not set" in capsys.readouterr().out and not signature_path.exists()
    monkeypatch.setenv(secret, private)
    monkeypatch.setattr(release_signing, "TRUSTED_PUBLIC_KEYS", (release_signing.PLACEHOLDER,))
    assert sign_release.main([str(zip_path)]) == 1 and not signature_path.exists()
    monkeypatch.setattr(release_signing, "TRUSTED_PUBLIC_KEYS", (public,))
    assert sign_release.main([str(zip_path)]) == 0
    signature = signature_path.read_text()
    release_signing.verify_release("SlideMage-linux.zip", hashlib.sha256(b"zip bytes").hexdigest(), signature)
    with pytest.raises(release_signing.SignatureError):
        release_signing.verify_release("SlideMage-linux.zip", hashlib.sha256(b"other").hexdigest(), signature)


def test_a_malformed_secret_is_refused():
    with pytest.raises(SystemExit):
        sign_release.load_seed("not a key")
