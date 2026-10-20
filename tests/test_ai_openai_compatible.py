# SPDX-License-Identifier: GPL-3.0-or-later
"""The «Local / OpenAI-compatible» provider reaches hosted services too
(#650).

Ollama and LM Studio are given as host:port and serve under /v1; a hosted
OpenAI-compatible service (OpenCode Go/Zen, vLLM, LiteLLM...) is given
with its version already, and became .../v1/v1. Its key travels as the
usual Bearer token."""
from __future__ import annotations

from core import ai


def _url(base):
    url, headers, _ = ai.build_request("ollama", "m", "sk-1", "s",
                                       [{"role": "user", "text": "hi"}],
                                       ollama_url=base)
    return url, headers


def test_a_local_server_gets_v1():
    assert _url("http://localhost:11434")[0] == \
        "http://localhost:11434/v1/chat/completions"
    assert _url("http://localhost:1234/")[0] == \
        "http://localhost:1234/v1/chat/completions"


def test_a_hosted_url_with_its_version_is_kept():
    url, headers = _url("https://opencode.ai/zen/v1")
    assert url == "https://opencode.ai/zen/v1/chat/completions"
    assert headers["Authorization"] == "Bearer sk-1"


def test_the_label_says_any_openai_compatible_service():
    assert "OpenAI-compatible" in ai.PROVIDER_INFO["ollama"][0]


def test_opencode_go_is_a_named_provider():
    """An ``oc_sk_`` key picks the provider on its own and talks to the
    GO catalog's chat/completions endpoint (/zen/go/v1 — not plain Zen,
    which is a different service) with a Bearer token. Go requires a
    stable x-opencode-session header on every request."""
    assert ai.detect_provider("oc_sk_k") == "opencode"
    url, headers, _ = ai.build_request(
        "opencode", "kimi-k2.6", "oc_sk_k", "s",
        [{"role": "user", "text": "hi"}])
    assert url == "https://opencode.ai/zen/go/v1/chat/completions"
    assert headers["Authorization"] == "Bearer oc_sk_k"
    assert headers["x-opencode-session"]

    url, headers, _ = ai.build_request(
        "opencode", "kimi-k2.6", "oc_sk_k", "s",
        [{"role": "user", "text": "hi"}], session_id="conv-1")
    assert headers["x-opencode-session"] == "conv-1"
