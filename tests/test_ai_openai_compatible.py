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


def test_opencode_go_routes_each_model_family_to_its_wire_format():
    """PR #516: on Go, Claude/Qwen/MiniMax answer on /messages and GPT/Grok
    on /responses; the plain chat ones stay on /chat/completions."""
    import json
    msgs = [{"role": "user", "text": "hola"},
            {"role": "assistant", "text": "ok"},
            {"role": "user", "text": "más"}]
    url, headers, payload = ai.build_request(
        "opencode", "claude-sonnet-5", "oc_sk_k", "SYS", msgs,
        session_id="conv-1")
    assert url == "https://opencode.ai/zen/go/v1/messages"
    assert headers["x-api-key"] == "oc_sk_k"
    assert headers["x-opencode-session"] == "conv-1"
    body = json.loads(payload)
    assert body["system"] == "SYS" and len(body["messages"]) == 3

    url, headers, payload = ai.build_request(
        "opencode", "gpt-5.5", "oc_sk_k", "SYS", msgs, session_id="conv-1")
    assert url == "https://opencode.ai/zen/go/v1/responses"
    assert headers["x-opencode-session"] == "conv-1"
    body = json.loads(payload)
    assert body["instructions"] == "SYS"
    assert [c["content"][0]["type"] for c in body["input"]] == [
        "input_text", "output_text", "input_text"]

    url, _h, _p = ai.build_request("opencode", "kimi-k2.6", "oc_sk_k", "s",
                                   msgs)
    assert url.endswith("/chat/completions")
    # Elsewhere a "gpt" or "claude" id keeps its provider's own shape.
    assert ai.wire_style("openrouter", "claude-sonnet-5") == "openai"
    assert ai.wire_style("openai", "gpt-5") == "openai"


def test_a_responses_reply_is_read():
    raw = (b'{"output": [{"type": "reasoning"}, {"type": "message",'
           b' "content": [{"type": "output_text", "text": "hola "},'
           b' {"type": "output_text", "text": "mundo"}]}]}')
    assert ai.parse_reply("opencode", raw, style="responses") == "hola mundo"
    assert ai.parse_reply("opencode", b'{"output_text": "ok"}',
                          style="responses") == "ok"


def test_opencode_go_vision_families():
    assert ai.supports_vision("opencode", "claude-sonnet-5")
    assert ai.supports_vision("opencode", "gemini-3-pro")
    assert not ai.supports_vision("opencode", "kimi-k2.6")
    assert not ai.supports_vision("groq", "qwen3-32b")
