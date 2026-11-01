# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Issue #198: the macOS package's Python looked for its CA bundle at the
build machine's path, and the AI assistant failed with
CERTIFICATE_VERIFY_FAILED. core.tls points OpenSSL at a bundle that exists,
and leaves a working setup — and verification — alone."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from core import tls


def _paths(cafile=None, capath=None, openssl_cafile=None, openssl_capath=None):
    return SimpleNamespace(cafile=cafile, capath=capath,
                           openssl_cafile=openssl_cafile,
                           openssl_capath=openssl_capath)


MAC_FRAMEWORK = _paths(
    openssl_cafile="/Library/Frameworks/Python.framework/Versions/3.12/etc/"
                   "openssl/cert.pem",
    openssl_capath="/Library/Frameworks/Python.framework/Versions/3.12/etc/"
                   "openssl/certs")


def test_the_mac_package_gets_the_system_bundle(tmp_path, monkeypatch):
    monkeypatch.setattr(tls, "_certifi", lambda: None)
    system = tmp_path / "cert.pem"
    system.write_text("-----BEGIN CERTIFICATE-----\n")
    env: dict = {}
    got = tls.ensure_ca_bundle(MAC_FRAMEWORK, [str(tmp_path / "nope"),
                                               str(system)],
                               environ=env, platform="darwin")
    assert got == str(system) and env["SSL_CERT_FILE"] == str(system)


def test_certifi_wins_when_it_is_bundled(tmp_path, monkeypatch):
    bundled = tmp_path / "cacert.pem"
    bundled.write_text("x")
    monkeypatch.setattr(tls, "_certifi", lambda: str(bundled))
    env: dict = {}
    assert tls.ensure_ca_bundle(MAC_FRAMEWORK, ["/etc/ssl/cert.pem"],
                                environ=env, platform="darwin") == str(bundled)


def test_a_working_setup_is_left_alone(tmp_path, monkeypatch):
    monkeypatch.setattr(tls, "_certifi", lambda: None)
    ok = tmp_path / "ok.pem"
    ok.write_text("x")
    env: dict = {}
    assert tls.ensure_ca_bundle(_paths(openssl_cafile=str(ok)),
                                ["/etc/ssl/cert.pem"], environ=env,
                                platform="linux") is None
    assert "SSL_CERT_FILE" not in env
    # …and so is a bundle the user already chose.
    env = {"SSL_CERT_FILE": str(ok)}
    assert tls.ensure_ca_bundle(MAC_FRAMEWORK, [], environ=env,
                                platform="darwin") is None
    assert env["SSL_CERT_FILE"] == str(ok)


def test_windows_reads_its_own_store(monkeypatch):
    env: dict = {}
    assert tls.ensure_ca_bundle(MAC_FRAMEWORK, ["/etc/ssl/cert.pem"],
                                environ=env, platform="win32") is None
    assert env == {}


def test_nothing_found_changes_nothing(monkeypatch, tmp_path):
    monkeypatch.setattr(tls, "_certifi", lambda: None)
    env: dict = {}
    assert tls.ensure_ca_bundle(MAC_FRAMEWORK, [str(tmp_path / "none")],
                                environ=env, platform="darwin") is None
    assert env == {}


def test_the_bundle_it_sets_is_what_ssl_then_uses(tmp_path, monkeypatch):
    # SSL_CERT_FILE is read by every NEW context: the fix reaches urllib's
    # connections without touching verification.
    import ssl
    real = ssl.get_default_verify_paths()
    monkeypatch.setenv("SSL_CERT_FILE", real.openssl_cafile or "/nonexistent")
    assert ssl.get_default_verify_paths().cafile in (real.openssl_cafile, None)
    ctx = ssl.create_default_context()
    assert ctx.verify_mode == ssl.CERT_REQUIRED and ctx.check_hostname


def test_a_bundle_variable_pointing_nowhere_is_replaced(tmp_path, monkeypatch):
    monkeypatch.setattr(tls, "_certifi", lambda: None)
    ok = tmp_path / "ok.pem"
    ok.write_text("x")
    env = {"SSL_CERT_FILE": str(tmp_path / "gone.pem")}
    got = tls.ensure_ca_bundle(_paths(openssl_cafile=str(ok)), [str(ok)],
                               environ=env, platform="linux")
    assert got == str(ok) and env["SSL_CERT_FILE"] == str(ok)


def test_the_ai_requests_carry_a_verifying_context(monkeypatch):
    import ssl
    import urllib.request
    from core import ai
    seen = {}

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b"{}"

    def fake(req, timeout=None, context=None):
        seen["context"] = context
        return _Resp()

    monkeypatch.setattr(urllib.request, "urlopen", fake)
    ai._urlopen("https://example.invalid/", {})
    ctx = seen["context"]
    assert isinstance(ctx, ssl.SSLContext)
    assert ctx.verify_mode == ssl.CERT_REQUIRED and ctx.check_hostname


# Issue #783: on a fresh Windows the store lacks the root that signs
# raw.githubusercontent.com (Windows fetches it on demand only for programs
# that ask its own verifier), so Python's store-reading context failed.
# truststore hands verification to that verifier.

def _fake_truststore(monkeypatch):
    import ssl
    import sys
    import types

    class SSLContext(ssl.SSLContext):
        pass

    module = types.ModuleType("truststore")
    module.SSLContext = SSLContext          # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "truststore", module)
    return SSLContext


def test_windows_verifies_through_the_system_verifier(monkeypatch):
    import ssl
    cls = _fake_truststore(monkeypatch)
    ctx = tls.https_context(platform="win32")
    assert isinstance(ctx, cls)
    assert ctx.verify_mode == ssl.CERT_REQUIRED and ctx.check_hostname


def test_other_systems_keep_the_bundle_context(monkeypatch):
    import ssl
    cls = _fake_truststore(monkeypatch)
    ctx = tls.https_context(platform="linux")
    assert not isinstance(ctx, cls)
    assert ctx.verify_mode == ssl.CERT_REQUIRED


def test_windows_without_truststore_still_verifies(monkeypatch):
    import ssl
    import sys
    monkeypatch.setitem(sys.modules, "truststore", None)    # import fails
    ctx = tls.https_context(platform="win32")
    assert ctx.verify_mode == ssl.CERT_REQUIRED and ctx.check_hostname


def test_every_python_https_call_uses_the_context():
    import re
    from pathlib import Path
    root = Path(tls.__file__).resolve().parent
    for name in ("extension_manager.py", "library.py", "ai.py"):
        text = (root / name).read_text(encoding="utf-8")
        calls = re.findall(r"request\.urlopen\((?:[^()]|\([^()]*\))*\)", text)
        assert calls and all("context=" in c for c in calls), name


def test_the_windows_build_ships_truststore():
    """The Windows build installs its packages by hand, not from
    requirements.txt: without truststore there, the frozen app falls back
    to Python's own store and #783 comes back without a word."""
    root = Path(__file__).resolve().parent.parent
    workflow = (root / ".github/workflows/build-windows.yml").read_text()
    spec = (root / "ingetrazo.spec").read_text()
    assert "truststore" in workflow
    assert "'truststore'" in spec
