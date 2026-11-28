# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Verify HTTPS certificates through the operating system, not through Python's own default.

Python's default context on Windows reads only the roots already in the Windows certificate store. Windows fetches a
missing root on demand only for programs that use its own verification, which Python does not: when GitHub's chain
began to end at "Sectigo Public Server Authentication Root E46", every request failed with CERTIFICATE_VERIFY_FAILED
("unable to get issuer certificate") until something else made Windows fetch that root. `truststore` hands the
verification to the system (Windows CryptoAPI, macOS Security.framework, OpenSSL's store on Linux).

`inject()` is called once, first thing, by both entry points (cli.main, presenter_app.main). It patches `ssl`, so
every urllib / http.client request in the process uses it, plugins included (they run in-process). Nothing builds
its own SSLContext. Never raises: if truststore is missing or fails, Python's default stays and a warning is logged.
`certificate_message` turns a failed verification into a sentence for the UI."""
from __future__ import annotations

import logging
import ssl
import urllib.error
import urllib.parse
from typing import Optional

log = logging.getLogger("slidemage.tls_trust")
_injected = False


def inject() -> bool:
    """Make `ssl` verify through the operating system. True when it does (also on a repeated call); False, with a
    warning in the log, when truststore cannot be imported or injected. Never raises."""
    global _injected
    if _injected:
        return True
    try:
        import truststore

        truststore.inject_into_ssl()
    except Exception as exc:
        log.warning("HTTPS certificates are checked with Python's own list, not the system's: truststore failed "
                    "(%s: %s)", type(exc).__name__, exc)
        return False
    _injected = True
    return True


def injected() -> bool:
    """Whether inject() has made `ssl` use the operating system's certificate store."""
    return _injected


def _is_certificate_failure(exc: BaseException) -> bool:
    seen = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        if isinstance(exc, ssl.SSLCertVerificationError) or "CERTIFICATE_VERIFY_FAILED" in str(exc):
            return True
        reason = getattr(exc, "reason", None) if isinstance(exc, urllib.error.URLError) else None
        exc = reason if isinstance(reason, BaseException) else (exc.__cause__ or exc.__context__)
    return False


def certificate_message(exc: BaseException, url: str) -> Optional[str]:
    """A plain sentence when `exc` is a failed certificate check for `url`, else None. The technical error goes to
    the log, not to the person."""
    if not _is_certificate_failure(exc):
        return None
    host = urllib.parse.urlsplit(url).hostname or "the server"
    log.warning("certificate check failed for %s: %s", url, exc)
    return (f"The certificate of {host} could not be checked. If this keeps happening, a proxy or security "
            f"software may be intercepting HTTPS.")
