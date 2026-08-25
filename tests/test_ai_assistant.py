# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Asistente IA: provider layer (IngePresupuestos convention) and the
in-app agent loop with a scripted fake model."""
from __future__ import annotations

import json
import sys

from PySide6.QtWidgets import QApplication

if QApplication.instance() is None:
    QApplication(sys.argv[:1])

from core import ai  # noqa: E402


# ---- Provider layer ---------------------------------------------------------

def test_detect_provider_by_key_prefix():
    assert ai.detect_provider("gsk_xxx") == "groq"
    assert ai.detect_provider("sk-ant-xxx") == "anthropic"
    assert ai.detect_provider("AIzaXXX") == "gemini"
    assert ai.detect_provider("sk-or-xxx") == "openrouter"
    assert ai.detect_provider("sk-xxx") == "openai"
    assert ai.detect_provider("") == "ollama"


def test_build_request_shapes():
    msgs = [{"role": "user", "text": "hola"},
            {"role": "assistant", "text": "```python\nprint(1)\n```"},
            {"role": "user", "text": "resultado", "image_png_b64": "QUJD"}]

    url, headers, payload = ai.build_request(
        "anthropic", "claude-sonnet-5", "sk-ant-k", "SYS", msgs)
    assert "api.anthropic.com/v1/messages" in url
    assert headers["x-api-key"] == "sk-ant-k"
    body = json.loads(payload)
    assert body["system"] == "SYS"
    blocks = body["messages"][2]["content"]
    assert blocks[0]["type"] == "image"
    assert blocks[0]["source"]["data"] == "QUJD"

    url, headers, payload = ai.build_request(
        "groq", "llama-3.3-70b-versatile", "gsk_k", "SYS", msgs)
    assert "api.groq.com/openai/v1/chat/completions" in url
    assert headers["Authorization"] == "Bearer gsk_k"
    body = json.loads(payload)
    assert body["messages"][0] == {"role": "system", "content": "SYS"}
    img = body["messages"][3]["content"][0]
    assert img["image_url"]["url"].startswith("data:image/png;base64,")

    url, _h, _p = ai.build_request("ollama", "llama3.2", "", "SYS",
                                   [{"role": "user", "text": "x"}],
                                   ollama_url="http://localhost:11434")
    assert url == "http://localhost:11434/v1/chat/completions"


def test_parse_reply_and_extract_code():
    anth = json.dumps({"content": [{"type": "text", "text": "hola "},
                                   {"type": "text", "text": "mundo"}]})
    assert ai.parse_reply("anthropic", anth.encode()) == "hola mundo"
    oai = json.dumps({"choices": [{"message": {"content": "ok"}}]})
    assert ai.parse_reply("openai", oai.encode()) == "ok"

    text = "Voy a dibujar:\n```python\nmesh.add_edge(a, b)\n```\nlisto"
    assert ai.extract_code(text) == "mesh.add_edge(a, b)"
    assert ai.extract_code("sin código") is None


# ---- In-app agent loop ------------------------------------------------------

def test_assistant_loop_executes_recipes_transactionally(monkeypatch):
    from plugins.ai_assistant import AsistenteDialog
    from views.main_window import MainWindow

    replies = iter([
        "Dibujo la arista:\n```python\n"
        "mesh.add_edge(QVector3D(0,0,0), QVector3D(3,0,0))\n"
        "print('arista lista')\n```",
        "Listo: dibujé la arista de 3 m.",
    ])
    seen: list = []

    def fake_chat(provider, model, key, system, messages, **kw):
        seen.append([dict(m) for m in messages])
        return next(replies)

    monkeypatch.setattr(ai, "chat", fake_chat)

    win = MainWindow()
    try:
        vp = win.viewport
        dlg = AsistenteDialog(vp, parent=win)
        dlg._key.setText("sk-ant-test")
        dlg._shots.setChecked(False)           # offscreen has no GL anyway
        edges0 = len(vp.scene.mesh.edges)
        depth0 = len(vp.history.undo_stack)

        dlg._input.setText("dibuja una arista de 3 m")
        dlg._on_send()
        app = QApplication.instance()
        for _ in range(2000):
            app.processEvents()
            if not dlg._busy:
                break
        assert not dlg._busy

        assert len(vp.scene.mesh.edges) == edges0 + 1
        assert len(vp.history.undo_stack) == depth0 + 1   # ONE undo step
        # The model got the execution feedback on the second turn.
        assert any("arista lista" in m["text"]
                   for m in seen[1] if m["role"] == "user")
        # The transcript keeps user → assistant → feedback → assistant.
        roles = [m["role"] for m in dlg._convo]
        assert roles == ["user", "assistant", "user", "assistant"]
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


def test_user_agent_defeats_cloudflare_and_headers_carry_it():
    # Groq sits behind Cloudflare, which rejects urllib's default agent with
    # HTTP 403 error 1010 (the user's first real key hit it).
    for provider in ("groq", "anthropic", "openai"):
        _u, headers, _p = ai.build_request(
            provider, "m", "k", "SYS", [{"role": "user", "text": "x"}])
        assert headers["User-Agent"].startswith("IngeTrazo/")


def test_provider_selector_overrides_autodetect(monkeypatch):
    from plugins.ai_assistant import AsistenteDialog
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        dlg = AsistenteDialog(win.viewport, parent=win)
        dlg._provider.setCurrentIndex(0)             # Auto (QSettings persist
        dlg._key.setText("sk-ant-algo")              # between tests) → key wins
        assert dlg._effective_provider() == "anthropic"
        idx = dlg._provider.findData("groq")
        dlg._provider.setCurrentIndex(idx)           # explicit wins
        assert dlg._effective_provider() == "groq"
        assert "console.groq.com" in dlg._key_link.text()
        assert (dlg._model.lineEdit().placeholderText()
                == ai.DEFAULT_MODELS["groq"])

        # Probar conexión reports through the same reply channel.
        monkeypatch.setattr(ai, "probar_conexion",
                            lambda *a, **k: (True, "OK"))
        dlg._on_probar()
        app = QApplication.instance()
        for _ in range(2000):
            app.processEvents()
            if dlg._probar.isEnabled():
                break
        assert dlg._probar.isEnabled()
        assert "Connection OK" in dlg._chat.toPlainText()

        # "Models" fills the combo with what the key can actually use.
        monkeypatch.setattr(ai, "list_models",
                            lambda *a, **k: ["openai/gpt-oss-120b",
                                             "qwen/qwen3-32b"])
        dlg._model.setEditText("")
        dlg._on_modelos()
        for _ in range(2000):
            app.processEvents()
            if dlg._modelos.isEnabled():
                break
        assert dlg._modelos.isEnabled()
        assert [dlg._model.itemText(i) for i in range(dlg._model.count())] \
            == ["openai/gpt-oss-120b", "qwen/qwen3-32b"]
        dlg._model.hidePopup()
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


def test_list_models_filters_and_strips(monkeypatch):
    # Groq retired llama-3.3-70b-versatile (2026-06-17, free tiers) — the
    # picker offers the LIVE list, minus non-chat models, "models/" bare.
    calls = {}

    def fake_urlopen(url, headers, payload=None, timeout=180.0):
        calls["url"], calls["headers"] = url, headers
        return json.dumps({"data": [
            {"id": "models/gemini-2.5-flash"},
            {"id": "openai/gpt-oss-120b"},
            {"id": "whisper-large-v3"},
            {"id": "playai-tts"},
            {"id": "meta-llama/llama-guard-4-12b"},
            {"id": "text-embedding-004"},
        ]}).encode()

    monkeypatch.setattr(ai, "_urlopen", fake_urlopen)
    models = ai.list_models("groq", "gsk_k")
    assert models == ["gemini-2.5-flash", "openai/gpt-oss-120b"]
    assert calls["url"] == "https://api.groq.com/openai/v1/models"
    assert calls["headers"]["Authorization"] == "Bearer gsk_k"
    assert calls["headers"]["User-Agent"].startswith("IngeTrazo/")

    ai.list_models("anthropic", "sk-ant-k")
    assert "api.anthropic.com/v1/models" in calls["url"]
    assert calls["headers"]["x-api-key"] == "sk-ant-k"
