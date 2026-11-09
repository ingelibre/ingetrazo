# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""#1266: Anthropic answers HTTP 400 «text content blocks must be
non-empty» to an empty text block. A reply that came back empty, or that
was nothing but <thinking>, is stored as an empty assistant turn and
resent with every later request — so every turn after it failed."""
from __future__ import annotations

import json

from core import ai


def _blocks(messages):
    _url, _headers, payload = ai.build_request(
        "anthropic", "claude-sonnet-5", "sk-ant-k", "SYS", messages)
    return json.loads(payload)["messages"]


def _assert_no_empty_text(sent):
    for m in sent:
        assert m["content"], m                     # no empty content list
        for b in m["content"]:
            if b["type"] == "text":
                assert b["text"].strip(), m


def test_an_empty_reply_in_the_convo_sends_no_empty_text():
    reply = ai.strip_thoughts("<thinking>planning the slab</thinking>")
    assert reply == ""
    sent = _blocks([{"role": "user", "text": "make a slab"},
                    {"role": "assistant", "text": reply},
                    {"role": "user", "text": "continue"}])
    _assert_no_empty_text(sent)
    # The roles still alternate: the empty turn is kept, not dropped.
    assert [m["role"] for m in sent] == ["user", "assistant", "user"]


def test_whitespace_only_text_counts_as_empty():
    sent = _blocks([{"role": "user", "text": "hi"},
                    {"role": "assistant", "text": "  \n"},
                    {"role": "user", "text": "go on"}])
    _assert_no_empty_text(sent)


def test_an_image_without_text_goes_alone():
    sent = _blocks([{"role": "user", "text": "", "image_png_b64": "QUJD"}])
    _assert_no_empty_text(sent)
    assert [b["type"] for b in sent[0]["content"]] == ["image"]


def test_normal_turns_are_unchanged():
    sent = _blocks([{"role": "user", "text": "hola"},
                    {"role": "assistant", "text": "listo"}])
    assert sent[0]["content"] == [{"type": "text", "text": "hola"}]
    assert sent[1]["content"] == [{"type": "text", "text": "listo"}]
