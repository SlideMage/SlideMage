# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Make the Ed25519 key pair that signs SlideMage releases, on this computer, and say what to do with it.

    python packaging/make_signing_key.py

Prints the PRIVATE key once (base64) and the PUBLIC key (64 hex characters). Nothing is written to a file. The
private key belongs only in the repository secret SLIDEMAGE_RELEASE_SIGNING_KEY and, as a backup, in a password
manager: whoever has it can make updates that every SlideMage installation accepts. Do not paste it into a chat, an
issue or a file in the repository.
"""
from __future__ import annotations

import base64
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from slidemage import ed25519, release_signing  # noqa: E402


def make_key() -> tuple[str, str]:
    """(private key as base64, public key as hex)."""
    seed = os.urandom(32)
    return base64.b64encode(seed).decode("ascii"), ed25519.public_key(seed).hex()


def instructions(private_b64: str, public_hex: str) -> str:
    return f"""\
New SlideMage release signing key.

PRIVATE key (secret, shown only now):
    {private_b64}

PUBLIC key:
    {public_hex}

Steps:
 1. Add the private key as a repository secret: GitHub -> SlideMage/SlideMage -> Settings -> Secrets and variables ->
    Actions -> New repository secret. Name: {release_signing.SIGNING_KEY_SECRET}   Value: the PRIVATE key above.
    (Or: gh secret set {release_signing.SIGNING_KEY_SECRET} --repo SlideMage/SlideMage, then paste it.)
 2. Keep a copy of the private key in your password manager. Then clear this terminal.
 3. Put the PUBLIC key into the app: in src/slidemage/release_signing.py replace the placeholder in
    TRUSTED_PUBLIC_KEYS with
        "{public_hex}",
    Commit it with a change fragment and release it as usual. That release is the first one the check can verify.
 4. The release workflow signs every zip with the secret and fails when it is missing.

Changing the key later (rotation) is described in the README, "Releases and updates".
"""


def main() -> int:
    private_b64, public_hex = make_key()
    print(instructions(private_b64, public_hex))
    return 0


if __name__ == "__main__":
    sys.exit(main())
