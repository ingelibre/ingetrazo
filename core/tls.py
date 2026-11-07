# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Certificates for Python's own HTTPS (``urllib``, the AI assistant).

A packaged Python looks for its CA bundle where the machine that BUILT it
kept one: the macOS package (python.org's framework build under
PyInstaller) asks for ``/Library/Frameworks/Python.framework/…/cert.pem``,
which no user's Mac has, so every HTTPS call failed with
``CERTIFICATE_VERIFY_FAILED`` before the server was even asked (issue
#198). Qt's network stack (map tiles, terrain, the model library) uses the
system's own store and never had the problem.

:func:`ensure_ca_bundle` leaves a working setup alone; otherwise it points
OpenSSL at ``certifi``'s bundle when present, else at the system's own file
(``/etc/ssl/cert.pem`` on macOS, the usual Linux ones), through
``SSL_CERT_FILE`` — which every new ``ssl`` context reads. Verification is
never turned off. Windows has no bundle to point at: :func:`https_context`
verifies there through ``truststore``, the Windows verifier (issue #783).
"""
from __future__ import annotations

import os
import ssl
import sys
from pathlib import Path

#: The system's CA bundle, where each family keeps it.
SYSTEM_BUNDLES = (
    "/etc/ssl/cert.pem",                                  # macOS, Alpine, BSD
    "/etc/ssl/certs/ca-certificates.crt",                 # Debian, Ubuntu, Arch
    "/etc/pki/tls/certs/ca-bundle.crt",                   # Fedora, RHEL
    "/etc/ssl/ca-bundle.pem",                             # openSUSE
    "/etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem",  # Fedora (newer)
)

_done = False


def _has_certs(paths) -> bool:
    """Whether OpenSSL's default locations hold anything."""
    for f in (paths.cafile, paths.openssl_cafile):
        if f and Path(f).is_file():
            return True
    for d in (paths.capath, paths.openssl_capath):
        if d and Path(d).is_dir() and any(Path(d).iterdir()):
            return True
    return False


def _certifi() -> str | None:
    try:
        import certifi
    except ImportError:
        return None
    where = certifi.where()
    return where if Path(where).is_file() else None


def ensure_ca_bundle(paths=None, candidates=SYSTEM_BUNDLES,
                     environ=None, platform: str | None = None) -> str | None:
    """Make sure HTTPS from Python can verify servers. Returns the bundle it
    pointed ``SSL_CERT_FILE`` at, or None when nothing needed doing."""
    environ = os.environ if environ is None else environ
    platform = platform or sys.platform
    if platform.startswith("win"):
        return None
    chosen = environ.get("SSL_CERT_FILE")
    if chosen and Path(chosen).is_file():
        return None                      # the user (or a launcher) chose one
    # A SSL_CERT_FILE that points nowhere is what OpenSSL reads, working
    # defaults or not: replace it.
    if not chosen and _has_certs(paths or ssl.get_default_verify_paths()):
        return None
    for bundle in (_certifi(), *candidates):
        if bundle and Path(bundle).is_file():
            environ["SSL_CERT_FILE"] = bundle
            return bundle
    return None


def https_context(platform: str | None = None) -> ssl.SSLContext:
    """A verifying context for ``urlopen(context=…)``. Every Python HTTPS call
    of the app goes through it.

    On Windows, verification goes to the system verifier through
    ``truststore``: Windows fetches a missing root certificate on demand for
    programs that ask it, whereas Python's own store reading only sees the
    roots already installed, which fails on a fresh installation (#783).
    Elsewhere, and without ``truststore``, the context is loaded from the
    bundle :func:`ensure_ca_bundle` chose when there is one. Passing it
    explicitly does not depend on OpenSSL reading ``SSL_CERT_FILE`` again —
    it caches the default path once a connection has been tried."""
    platform = platform or sys.platform
    if platform.startswith("win"):
        try:
            import truststore
        except ImportError:
            pass
        else:
            return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ensure_once()
    bundle = os.environ.get("SSL_CERT_FILE")
    if bundle and Path(bundle).is_file():
        return ssl.create_default_context(cafile=bundle)
    return ssl.create_default_context()


def ensure_once() -> None:
    """:func:`ensure_ca_bundle` the first time only (cheap to call before
    every request)."""
    global _done
    if not _done:
        _done = True
        try:
            ensure_ca_bundle()
        except OSError:
            pass
