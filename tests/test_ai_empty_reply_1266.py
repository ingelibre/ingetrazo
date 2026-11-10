# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""#1266: with Anthropic, the AI Assistant hit «HTTP 400 … text content
blocks must be non-empty» and kept hitting it. A reply with nothing to read
(empty, or only a <thinking> block) was kept in the convo as an empty
assistant turn, and every later request carried it as an empty text block
— «continue» too. An empty reply is no longer kept, and no empty text block
goes to Anthropic, so a convo that already holds one works again."""
from __future__ import annotations

import json
import os
import sys
import threading

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

if QApplication.instance() is None:
    QApplication(sys.argv[:1])

from core import ai  # noqa: E402


def _anthropic_messages(convo):
    _url, _headers, body = ai.build_request(
        "anthropic", "claude-sonnet-5", "sk-ant-test", "sys", convo)
    return json.loads(body)["messages"]


def _texts(msg):
    return [b["text"] for b in msg["content"] if b["type"] == "text"]


@pytest.mark.parametrize("empty", ["", "   \n"])
def test_an_empty_turn_never_goes_as_an_empty_text_block(empty):
    msgs = _anthropic_messages([
        {"role": "user", "text": "make a slab"},
        {"role": "assistant", "text": empty},
        {"role": "user", "text": "continue"},
    ])
    assert [m["role"] for m in msgs] == ["user", "assistant", "user"]
    for m in msgs:
        assert m["content"], m
        assert all(t.strip() for t in _texts(m)), m
    assert _texts(msgs[1]) == [ai.EMPTY_TURN]


def test_a_photo_without_words_goes_alone():
    msgs = _anthropic_messages([
        {"role": "user", "text": "", "image_b64": "iVBORw0KGgo=",
         "image_mime": "image/png"},
    ])
    assert [b["type"] for b in msgs[0]["content"]] == ["image"]


def test_turns_with_text_go_as_before():
    msgs = _anthropic_messages([
        {"role": "user", "text": "make a slab"},
        {"role": "assistant", "text": "```python\npass\n```"},
    ])
    assert [_texts(m) for m in msgs] == [["make a slab"],
                                         ["```python\npass\n```"]]


@pytest.fixture
def panel(monkeypatch):
    """The AI panel with a turn on the way that never answers by itself."""
    from plugins.ai_assistant import AsistenteDialog
    from views.main_window import MainWindow
    gate = threading.Event()

    def slow_chat(*a, **k):
        gate.wait(10)
        return "late"

    monkeypatch.setattr(ai, "chat", slow_chat)
    win = MainWindow()
    try:
        dlg = AsistenteDialog(win.viewport, parent=win)
        dlg._provider.setCurrentIndex(dlg._provider.findData("anthropic"))
        dlg._key.setText("sk-ant-test")
        dlg._input.setText("make a slab")
        dlg._on_send()
        assert dlg._busy
        yield dlg
        # Stopped, the turn's late reply is dropped: let through, it would
        # ask again in the NEXT test, with that test's fake chat.
        dlg._on_stop()
    finally:
        gate.set()
        win._saved_version = win.viewport.scene.version
        win.close()


@pytest.mark.parametrize("reply", ["", "  ", "<thinking>a slab…</thinking>"])
def test_an_empty_reply_is_said_and_not_kept(panel, reply):
    before = list(panel._convo)
    panel._on_reply({"ok": True, "text": reply, "gen": panel._gen})
    assert panel._convo == before                  # no empty assistant turn
    assert not panel._busy                         # the request is over
    assert "empty reply" in panel._chat.toPlainText()
    assert all((m.get("text") or "").strip() for m in panel._convo)


def test_a_reply_with_words_is_kept_as_before(panel):
    panel._on_reply({"ok": True, "text": "Which height?", "gen": panel._gen})
    assert panel._convo[-1] == {"role": "assistant", "text": "Which height?"}
