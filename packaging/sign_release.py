# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Sign release zips (.github/workflows/release.yml): writes "<zip>.sig" next to each zip given on the command line.

The private key is read from the environment variable SLIDEMAGE_RELEASE_SIGNING_KEY (the repository secret: the
32-byte key as base64). It fails, and the release job with it, when the variable is empty, so no unsigned release goes
out. What is signed is described in src/slidemage/release_signing.py.

    python packaging/sign_release.py out/SlideMage-windows.zip out/SlideMage-windows-folder.zip
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from slidemage import ed25519, release_signing  # noqa: E402


def load_seed(text: str) -> bytes:
    try:
        seed = base64.b64decode("".join(text.split()), validate=True)
    except (binascii.Error, ValueError):
        seed = b""
    if len(seed) != 32:
        raise SystemExit("The signing key is not a base64-encoded 32-byte key.")
    return seed


def sign_file(seed: bytes, zip_path: Path) -> Path:
    digest = hashlib.sha256()
    with open(zip_path, "rb") as source:
        while chunk := source.read(1 << 20):
            digest.update(chunk)
    signature = ed25519.sign(seed, release_signing.signed_message(zip_path.name, digest.hexdigest()))
    target = zip_path.with_name(zip_path.name + release_signing.SIGNATURE_SUFFIX)
    target.write_text(release_signing.encode_signature(signature), encoding="ascii", newline="\n")
    return target


def main(argv: list[str]) -> int:
    key = os.environ.get(release_signing.SIGNING_KEY_SECRET, "").strip()
    if not key:
        print(f"::error::{release_signing.SIGNING_KEY_SECRET} is not set: add the repository secret "
              "(packaging/make_signing_key.py explains how). No unsigned release goes out.")
        return 1
    if not argv:
        print("No zip given.")
        return 1
    seed = load_seed(key)
    if ed25519.public_key(seed).hex() not in {k.lower() for k in release_signing.TRUSTED_PUBLIC_KEYS}:
        print("::error::The signing key's public key is not in release_signing.TRUSTED_PUBLIC_KEYS: "
              "a release signed with it would be refused by every installation.")
        return 1
    for name in argv:
        path = Path(name)
        if not path.is_file():
            print(f"::error::{path} does not exist.")
            return 1
        print(f"signed {path} -> {sign_file(seed, path).name}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
