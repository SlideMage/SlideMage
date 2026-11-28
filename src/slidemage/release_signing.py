# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Signed releases (docs/plans/update-install-safety.md, A7 / U2): every release zip has a second asset,
"<zip name>.sig", made in .github/workflows/release.yml by packaging/sign_release.py with a private key that only
the repository's secret SLIDEMAGE_RELEASE_SIGNING_KEY holds. The app checks it against the public keys below before
it installs anything, so a release made through a hijacked GitHub account (which has no key) is refused.

What is signed (SIGNED_MESSAGE): the asset's name and the SHA-256 of the zip, not the zip itself, so the check
needs no second pass over a 300 MB file and the signature of one asset cannot be put next to another. The ".sig"
file holds the 64-byte signature as one line of base64.

Key rotation (README, "Releases and updates"): TRUSTED_PUBLIC_KEYS is a list, and a release is accepted when any
key in it verifies. To change the key, release a version that lists old and new key, signed with the OLD key; once
users have it, sign with the new key, and one release later drop the old one.
"""
from __future__ import annotations

import base64
import binascii

from . import ed25519

SIGNATURE_SUFFIX = ".sig"
SIGNING_KEY_SECRET = "SLIDEMAGE_RELEASE_SIGNING_KEY"
PLACEHOLDER = "PLACEHOLDER-run-packaging-make_signing_key.py-and-paste-the-public-key-here"

# Public keys (64 hex characters each) whose signatures are accepted. Newest last. The placeholder is not a key:
# while nothing else is listed, no release verifies and no update installs (the message points to the release page).
TRUSTED_PUBLIC_KEYS: tuple[str, ...] = (
    "3346c1d7aad53ae10b6a8835bb81489b2f133dbd58e8d2bb2eb8379c0bba1d90",   # 2026-11-24, packaging/make_signing_key.py
)


class SignatureError(Exception):
    pass


def signed_message(asset_name: str, sha256_hex: str) -> bytes:
    """The bytes that are signed for the asset `asset_name` whose zip has SHA-256 `sha256_hex`."""
    return f"SlideMage release v1\n{asset_name}\n{sha256_hex.lower()}\n".encode("utf-8")


def encode_signature(signature: bytes) -> str:
    return base64.b64encode(signature).decode("ascii") + "\n"


def parse_keys(keys: tuple[str, ...] | list[str]) -> list[bytes]:
    """The usable keys among `keys`: 64 hex characters each. Anything else (the placeholder) is skipped."""
    usable = []
    for key in keys:
        try:
            raw = bytes.fromhex(key.strip())
        except ValueError:
            continue
        if len(raw) == 32:
            usable.append(raw)
    return usable


def verify_release(asset_name: str, sha256_hex: str, signature_text: bytes | str,
                   keys: tuple[str, ...] | list[str] | None = None) -> None:
    """Raise SignatureError unless `signature_text` (the content of "<asset_name>.sig") is a valid signature of this
    asset under one of `keys` (TRUSTED_PUBLIC_KEYS by default)."""
    usable = parse_keys(TRUSTED_PUBLIC_KEYS if keys is None else keys)
    if not usable:
        raise SignatureError("this SlideMage has no release signing key built in yet")
    if isinstance(signature_text, bytes):
        signature_text = signature_text.decode("ascii", "replace")
    try:
        signature = base64.b64decode("".join(signature_text.split()), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise SignatureError("the signature file is not valid") from exc
    if len(signature) != 64:
        raise SignatureError("the signature file is not valid")
    message = signed_message(asset_name, sha256_hex)
    if not any(ed25519.verify(key, message, signature) for key in usable):
        raise SignatureError("the signature does not match any trusted key")
