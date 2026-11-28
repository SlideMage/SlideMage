# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Ed25519 (RFC 8032, pure signatures) in plain Python, so the updater can check a release's signature without a
new dependency (SlideMage declares only PySide6).

Written after the RFC's reference code and tested against its test vectors (tests/test_ed25519.py). It is not
constant-time and meant for what it is used for here: verifying a 64-byte signature over a short message with a
public key built into the app, and signing in the release workflow and the key script, where timing leaks do not
matter. Do not use it for anything else.
"""
from __future__ import annotations

import hashlib

_P = 2**255 - 19
_Q = 2**252 + 27742317777372353535851937790883648493       # order of the base point
_D = -121665 * pow(121666, _P - 2, _P) % _P
_I = pow(2, (_P - 1) // 4, _P)                              # sqrt(-1)


def _inv(x: int) -> int:
    return pow(x, _P - 2, _P)


def _recover_x(y: int, sign: int) -> int | None:
    if y >= _P:
        return None
    x2 = (y * y - 1) * _inv(_D * y * y + 1) % _P
    if x2 == 0:
        return None if sign else 0
    x = pow(x2, (_P + 3) // 8, _P)
    if (x * x - x2) % _P != 0:
        x = x * _I % _P
    if (x * x - x2) % _P != 0:
        return None
    if (x & 1) != sign:
        x = _P - x
    return x


_GY = 4 * _inv(5) % _P
_GX = _recover_x(_GY, 0)
_G = (_GX, _GY, 1, _GX * _GY % _P)                          # extended coordinates (X, Y, Z, T)


def _add(p, q):
    a = (p[1] - p[0]) * (q[1] - q[0]) % _P
    b = (p[1] + p[0]) * (q[1] + q[0]) % _P
    c = 2 * p[3] * q[3] * _D % _P
    d = 2 * p[2] * q[2] % _P
    e, f, g, h = b - a, d - c, d + c, b + a
    return (e * f % _P, g * h % _P, f * g % _P, e * h % _P)


def _mul(s: int, p):
    q = (0, 1, 1, 0)
    while s > 0:
        if s & 1:
            q = _add(q, p)
        p = _add(p, p)
        s >>= 1
    return q


def _equal(p, q) -> bool:
    return (p[0] * q[2] - q[0] * p[2]) % _P == 0 and (p[1] * q[2] - q[1] * p[2]) % _P == 0


def _compress(p) -> bytes:
    zi = _inv(p[2])
    x, y = p[0] * zi % _P, p[1] * zi % _P
    return int.to_bytes(y | ((x & 1) << 255), 32, "little")


def _decompress(data: bytes):
    if len(data) != 32:
        return None
    y = int.from_bytes(data, "little")
    sign = y >> 255
    y &= (1 << 255) - 1
    x = _recover_x(y, sign)
    if x is None:
        return None
    return (x, y, 1, x * y % _P)


def _sha512_int(*parts: bytes) -> int:
    return int.from_bytes(hashlib.sha512(b"".join(parts)).digest(), "little")


def _expand(seed: bytes) -> tuple[int, bytes]:
    digest = hashlib.sha512(seed).digest()
    a = int.from_bytes(digest[:32], "little")
    a &= (1 << 254) - 8
    a |= 1 << 254
    return a, digest[32:]


def public_key(seed: bytes) -> bytes:
    """The 32-byte public key of the 32-byte private `seed`."""
    if len(seed) != 32:
        raise ValueError("An Ed25519 private key is 32 bytes.")
    return _compress(_mul(_expand(seed)[0], _G))


def sign(seed: bytes, message: bytes) -> bytes:
    """The 64-byte signature of `message` under the private `seed`."""
    a, prefix = _expand(seed)
    public = _compress(_mul(a, _G))
    r = _sha512_int(prefix, message) % _Q
    big_r = _compress(_mul(r, _G))
    h = _sha512_int(big_r, public, message) % _Q
    return big_r + int.to_bytes((r + h * a) % _Q, 32, "little")


def verify(public: bytes, message: bytes, signature: bytes) -> bool:
    """True when `signature` is a valid Ed25519 signature of `message` under the 32-byte `public` key. Never raises
    for malformed input: a wrong length, a point off the curve or a non-canonical scalar is just False."""
    if len(public) != 32 or len(signature) != 64:
        return False
    point_a = _decompress(public)
    point_r = _decompress(signature[:32])
    if point_a is None or point_r is None:
        return False
    s = int.from_bytes(signature[32:], "little")
    if s >= _Q:
        return False
    h = _sha512_int(signature[:32], public, message) % _Q
    return _equal(_mul(s, _G), _add(point_r, _mul(h, point_a)))
