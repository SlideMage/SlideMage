# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""A fake GitHub release with a signed zip, for the update tests. The keys are throwaway ones made here from fixed
seeds; the real signing key is never in the repository."""
from __future__ import annotations

import hashlib
import io
import zipfile

from slidemage import ed25519, release_signing, updater

SEED = bytes(range(32))
OTHER_SEED = bytes(range(100, 132))
PUBLIC_HEX = ed25519.public_key(SEED).hex()
OTHER_PUBLIC_HEX = ed25519.public_key(OTHER_SEED).hex()
ASSET_URL = "https://api.example.invalid/asset"
SIG_URL = "https://api.example.invalid/sig"


def zip_bytes(files: dict[str, bytes | str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def sign(data: bytes, asset_name: str, seed: bytes = SEED) -> str:
    message = release_signing.signed_message(asset_name, hashlib.sha256(data).hexdigest())
    return release_signing.encode_signature(ed25519.sign(seed, message))


def make_release(data: bytes, asset_name: str = "SlideMage-windows.zip", **overrides) -> updater.Release:
    fields = dict(
        tag="v99.0.0", page_url="https://example.invalid/releases/v99.0.0", asset_url=ASSET_URL, asset_size=len(data),
        body="", asset_name=asset_name, asset_digest="sha256:" + hashlib.sha256(data).hexdigest(), signature_url=SIG_URL,
    )
    fields.update(overrides)
    return updater.Release(**fields)


class Response(io.BytesIO):
    def __init__(self, data: bytes, content_length: int | None = None):
        super().__init__(data)
        self.headers = {"Content-Length": str(len(data) if content_length is None else content_length)}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def serve(monkeypatch, body: bytes, signature: str | None, content_length: int | None = None) -> list[str]:
    """Make updater's urlopen answer the asset url with `body` and the signature url with `signature`. Returns the
    list of urls requested."""
    requested: list[str] = []

    def fake_urlopen(request, **_kw):
        requested.append(request.full_url)
        if request.full_url == SIG_URL and signature is not None:
            return Response(signature.encode())
        if request.full_url == ASSET_URL:
            return Response(body, content_length)
        raise AssertionError(f"unexpected request {request.full_url}")

    monkeypatch.setattr(updater.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(release_signing, "TRUSTED_PUBLIC_KEYS", (PUBLIC_HEX,))
    return requested
