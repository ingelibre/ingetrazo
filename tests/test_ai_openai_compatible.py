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
