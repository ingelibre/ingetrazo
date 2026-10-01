# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Issue #130: the MCP client can reach the bridge through a tunnel
(``INGETRAZO_AI_HOST``), while the bridge itself stays on loopback."""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _client(monkeypatch, **env):
    for k in ("INGETRAZO_AI_HOST", "INGETRAZO_AI_PORT"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    spec = importlib.util.spec_from_file_location(
        "_mcp_client_under_test", ROOT / "scripts" / "ingetrazo_mcp.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_by_default_it_connects_to_loopback(monkeypatch):
    mod = _client(monkeypatch)
    assert (mod.HOST, mod.PORT) == ("127.0.0.1", 4763)


def test_the_host_and_port_come_from_the_environment(monkeypatch):
    mod = _client(monkeypatch, INGETRAZO_AI_HOST="host.docker.internal",
                  INGETRAZO_AI_PORT="5000")
    assert (mod.HOST, mod.PORT) == ("host.docker.internal", 5000)


def test_an_unreachable_bridge_is_named_in_the_error(monkeypatch):
    mod = _client(monkeypatch, INGETRAZO_AI_HOST="203.0.113.9",
                  INGETRAZO_AI_PORT="9")

    def refuse(*_a, **_k):
        raise OSError("connection refused")

    monkeypatch.setattr(mod, "_bridge", refuse)
    out = mod._call("query_model", {})
    assert out["isError"] is True
    assert "203.0.113.9:9" in out["content"][0]["text"]


def test_the_bridge_still_binds_loopback_only():
    src = (ROOT / "plugins" / "ai_bridge.py").read_text(encoding="utf-8")
    assert 'srv.bind(("127.0.0.1", port))' in src
    assert "INGETRAZO_AI_HOST" not in src
