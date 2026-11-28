# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""The pure-Python Ed25519 against the test vectors of RFC 8032, section 7.1."""
import pytest

from slidemage import ed25519

VECTORS = [
    ("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60",
     "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a",
     "",
     "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b"),
    ("4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb",
     "3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c",
     "72",
     "92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da085ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00"),
]


@pytest.mark.parametrize("secret, public, message, signature", VECTORS)
def test_rfc8032_vectors(secret, public, message, signature):
    seed, pub, msg, sig = (bytes.fromhex(x) for x in (secret, public, message, signature))
    assert ed25519.public_key(seed) == pub
    assert ed25519.sign(seed, msg) == sig
    assert ed25519.verify(pub, msg, sig)


def test_verify_rejects_tampering_and_malformed_input():
    secret, public, message, signature = (bytes.fromhex(x) for x in VECTORS[1])
    assert not ed25519.verify(public, message + b"x", signature)
    assert not ed25519.verify(public, message, bytes([signature[0] ^ 1]) + signature[1:])
    assert not ed25519.verify(public, message, signature[:-1])
    assert not ed25519.verify(public[:-1], message, signature)
    assert not ed25519.verify(bytes.fromhex(VECTORS[0][1]), message, signature)      # another key
    big_s = signature[:32] + (2**253).to_bytes(32, "little")                          # s >= group order
    assert not ed25519.verify(public, message, big_s)
    assert not ed25519.verify(b"\xff" * 32, message, signature)                       # not a point
