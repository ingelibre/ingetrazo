# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Asistente IA: provider layer (IngePresupuestos convention) and the
in-app agent loop with a scripted fake model."""
from __future__ import annotations

import json
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

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


def test_build_request_generic_image_mime():
    # User photos ride as JPEG via image_b64+image_mime; the legacy
    # image_png_b64 screenshot shorthand keeps working (previous test).
    msgs = [{"role": "user", "text": "recrea esto",
             "image_b64": "REVG", "image_mime": "image/jpeg"}]

    _u, _h, payload = ai.build_request(
        "anthropic", "claude-sonnet-5", "sk-ant-k", "SYS", msgs)
    block = json.loads(payload)["messages"][0]["content"][0]
    assert block["type"] == "image"
    assert block["source"]["media_type"] == "image/jpeg"
    assert block["source"]["data"] == "REVG"

    _u, _h, payload = ai.build_request(
        "openai", "gpt-4o", "sk-k", "SYS", msgs)
    img = json.loads(payload)["messages"][1]["content"][0]
    assert img["image_url"]["url"].startswith("data:image/jpeg;base64,REVG")


def test_parse_reply_and_extract_code():
    anth = json.dumps({"content": [{"type": "text", "text": "hola "},
                                   {"type": "text", "text": "mundo"}]})
    assert ai.parse_reply("anthropic", anth.encode()) == "hola mundo"
    oai = json.dumps({"choices": [{"message": {"content": "ok"}}]})
    assert ai.parse_reply("openai", oai.encode()) == "ok"

    text = "Voy a dibujar:\n```python\nmesh.add_edge(a, b)\n```\nlisto"
    assert ai.extract_code(text) == "mesh.add_edge(a, b)"
    assert ai.extract_code("sin código") is None


def test_compact_messages_stubs_old_recipes_keeps_recent():
    # Past recipes are dead weight (their effect is in the document): all
    # but the last 2 collapse to a stub, prose and feedback stay whole.
    def turn(i):
        return [{"role": "assistant",
                 "text": f"Paso {i}:\n```python\nprint({i})\n```\nsigo"},
                {"role": "user", "text": f"Resultado {i}"}]

    convo = [{"role": "user", "text": "modela la fuente"}]
    for i in range(4):
        convo += turn(i)
    convo.append({"role": "assistant", "text": "Listo, sin código."})

    slim = ai.compact_messages(convo)
    stubbed = [m for m in slim if ai.CODE_STUB in m["text"]]
    assert len(stubbed) == 2                       # turns 0 and 1
    assert "Paso 0:" in stubbed[0]["text"]         # prose kept
    assert "sigo" in stubbed[0]["text"]
    assert "print(0)" not in stubbed[0]["text"]    # code gone
    assert "print(2)" in slim[5]["text"]           # last two stay whole
    assert "print(3)" in slim[7]["text"]
    assert slim[2]["text"] == "Resultado 0"        # feedback untouched
    assert slim[-1]["text"] == "Listo, sin código."
    assert "print(0)" in convo[1]["text"]          # stored convo untouched


def test_strip_thoughts_removes_leaked_monologue():
    # Gemma leaks its chain of thought into the visible text (seen live);
    # resending it every turn is pure token burn.
    assert ai.strip_thoughts("<thought>hmm</thought>Listo.") == "Listo."
    assert ai.strip_thoughts("plan…</thought>La fuente está.") \
        == "La fuente está."                       # opener lost upstream
    assert ai.strip_thoughts("<thinking>a\nb") == ""   # unclosed: all gone
    assert ai.strip_thoughts("sin nada") == "sin nada"
    code = "ok\n```python\nprint(1)\n```"
    assert ai.strip_thoughts(code) == code


def test_recipe_helpers_build_correct_solids():
    # revolve/extrude are the one-line builders recipes should reach for:
    # a closed, outward-oriented, soft-edged group per call.
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        vp = win.viewport
        scope: dict = {"__name__": "__ai__"}
        r = ai.run_transactional(vp, (
            "g1 = revolve([(0.5, 0.0), (0.5, 1.0)], name='Cil',"
            " color=(1, 0, 0, 1))\n"
            "g2 = revolve([(0.6, 0.0), (0.7, 0.2), (0.6, 0.4), (0.4, 0.4),"
            " (0.4, 0.0)], closed=True, name='Aro')\n"
            "g3 = revolve([(0.4, 0.0), (0.5, 0.3), (0.5, 0.5)],"
            " scallop=(0.1, 8), name='Festón')\n"
            "g4 = extrude([(0, 0), (1, 0), (1, 1), (0, 1)], 0.0, 0.5,"
            " name='Caja', color=(0, 1, 0, 1))\n"
            "print(len(g1.mesh.faces), len(g4.mesh.faces))"), scope)
        assert r["error"] is None and r["changed"]
        names = [g.name for g in vp.scene.groups[-4:]]
        assert names == ["Cil", "Aro", "Festón", "Caja"]
        cil, aro, feston, caja = vp.scene.groups[-4:]
        assert len(cil.mesh.faces) == 32 + 2       # sides + two caps
        assert len(caja.mesh.faces) == 6
        assert all(f.attrs.get("color") == (1, 0, 0, 1)
                   for f in cil.mesh.faces)
        # Every solid is watertight and the curved sides came out soft.
        from core.orient import is_closed
        for g in (cil, aro, feston, caja):
            assert is_closed(g.mesh)
        assert any(e.soft for e in cil.mesh.edges)
        # The scallop carves INTO the stone: nominal radius is the max.
        import math as m
        rmax = max(m.hypot(v.position.x(), v.position.y())
                   for v in feston.mesh.vertices)
        assert abs(rmax - 0.5) < 1e-5
        # ONE undo step for the whole recipe.
        assert vp.history.undo_stack
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


def test_supports_vision_by_provider_or_model():
    assert ai.supports_vision("anthropic", "claude-sonnet-5")
    assert ai.supports_vision("gemini", "gemini-2.5-flash")
    # Groq's DEFAULT model is text-only, but its free Llama 4 sees images.
    assert not ai.supports_vision("groq", "openai/gpt-oss-120b")
    assert ai.supports_vision(
        "groq", "meta-llama/llama-4-scout-17b-16e-instruct")
    assert ai.supports_vision("ollama", "llava:13b")
    assert ai.supports_vision("ollama", "qwen2.5-vl-7b")
    assert not ai.supports_vision("ollama", "llama3.2")
    assert not ai.supports_vision("groq", "llama-3.3-70b-versatile")


def test_slim_messages_keeps_photo_and_latest_screenshot_only():
    convo = [
        {"role": "user", "text": "recrea esto",
         "image_b64": "FOTO", "image_mime": "image/jpeg"},
        {"role": "assistant", "text": "```python\n...\n```"},
        {"role": "user", "text": "resultado 1", "image_png_b64": "SHOT1"},
        {"role": "assistant", "text": "```python\n...\n```"},
        {"role": "user", "text": "resultado 2", "image_png_b64": "SHOT2"},
    ]
    slim = ai.slim_messages(convo)
    assert slim[0]["image_b64"] == "FOTO"          # the reference stays
    assert "image_png_b64" not in slim[2]          # stale screenshot gone
    assert slim[4]["image_png_b64"] == "SHOT2"     # the latest stays
    assert slim[2]["text"] == "resultado 1"        # text untouched
    assert convo[2]["image_png_b64"] == "SHOT1"    # stored convo untouched

    # A text-only model gets NO image content at all (Groq rejects content
    # arrays with HTTP 400, and the poisoned convo made every retry fail).
    blind = ai.slim_messages(convo, vision=False)
    assert all(not any(k.startswith("image") for k in m) for m in blind)
    assert [m["text"] for m in blind] == [m["text"] for m in convo]
    assert convo[0]["image_b64"] == "FOTO"         # still stored


def test_truncated_code_detects_a_cut_reply():
    # A reply chopped by max_tokens opens the fence and never closes it
    # (seen live with gemini-2.5-flash) — that is NOT "no code".
    cut = "Empiezo:\n```python\nimport math\nm = Mesh()"
    assert ai.extract_code(cut) is None
    assert ai.truncated_code(cut)
    assert not ai.truncated_code("sin código")
    assert not ai.truncated_code("```python\nprint(1)\n```\nlisto")

    # The assistant asks for MORE room than the layer's default.
    _u, _h, payload = ai.build_request(
        "gemini", "gemini-2.5-flash", "AIzaK", "SYS",
        [{"role": "user", "text": "x"}], max_tokens=8192)
    assert json.loads(payload)["max_tokens"] == 8192


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


def test_photo_attaches_to_next_message_only(monkeypatch, tmp_path):
    # The attached photo rides the NEXT user message as scaled JPEG and is
    # cleared afterwards — execution feedback turns must not re-send it.
    from PySide6.QtGui import QImage
    from plugins.ai_assistant import AsistenteDialog
    from views.main_window import MainWindow

    photo = tmp_path / "fuente.jpg"
    big = QImage(3000, 1500, QImage.Format_RGB32)
    big.fill(0xFF808080)
    assert big.save(str(photo), "JPEG")

    replies = iter([
        "Empiezo:\n```python\nprint('viendo la foto')\n```",
        "Listo.",
    ])
    seen: list = []

    def fake_chat(provider, model, key, system, messages, **kw):
        seen.append([dict(m) for m in messages])
        return next(replies)

    monkeypatch.setattr(ai, "chat", fake_chat)

    win = MainWindow()
    try:
        dlg = AsistenteDialog(win.viewport, parent=win)
        dlg._provider.setCurrentIndex(0)   # Auto: the sk-ant key → vision
        dlg._key.setText("sk-ant-test")
        dlg._shots.setChecked(False)
        assert not dlg._foto_chip.isVisibleTo(dlg)     # nothing attached yet

        dlg._attach_photo(str(photo))
        assert dlg._foto is not None
        b64, mime, name = dlg._foto
        assert mime == "image/jpeg" and name == "fuente.jpg"
        assert dlg._foto_chip.isVisibleTo(dlg)

        # The upload is scaled down to the cap, aspect kept.
        import base64 as b64mod
        sent = QImage.fromData(b64mod.b64decode(b64), "JPEG")
        assert max(sent.width(), sent.height()) == dlg.FOTO_MAX_EDGE
        assert sent.width() == 1280 and sent.height() == 640

        dlg._input.setText("recrea la fuente; taza de 4 m")
        dlg._on_send()
        app = QApplication.instance()
        for _ in range(2000):
            app.processEvents()
            if not dlg._busy:
                break
        assert not dlg._busy

        first_user = seen[0][0]
        assert first_user["image_b64"] == b64
        assert first_user["image_mime"] == "image/jpeg"
        assert dlg._foto is None                       # cleared after send
        assert not dlg._foto_chip.isVisibleTo(dlg)
        # The feedback turn carries no photo (and no screenshot: shots off).
        feedback = seen[1][2]
        assert feedback["role"] == "user"
        assert "image_b64" not in feedback
        assert "image_png_b64" not in feedback
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


def test_cut_reply_gets_a_retry_not_a_silent_stop(monkeypatch):
    # Live failure (gemini-2.5-flash): reply cut mid-```python → the loop
    # used to end silently with nothing drawn. Now it tells the model and
    # asks for a shorter complete block, and the retry still executes.
    from plugins.ai_assistant import TOKENS_BY_PROVIDER, AsistenteDialog
    from views.main_window import MainWindow

    replies = iter([
        "Empiezo con el pedestal:\n```python\nimport math\nm = Mesh()",
        "Más corto:\n```python\n"
        "mesh.add_edge(QVector3D(0,0,0), QVector3D(1,0,0))\n```",
        "Listo.",
    ])
    seen: list = []
    budgets: list = []

    def fake_chat(provider, model, key, system, messages, **kw):
        seen.append([dict(m) for m in messages])
        budgets.append(kw.get("max_tokens"))
        return next(replies)

    monkeypatch.setattr(ai, "chat", fake_chat)

    win = MainWindow()
    try:
        vp = win.viewport
        dlg = AsistenteDialog(vp, parent=win)
        dlg._provider.setCurrentIndex(0)   # Auto: the AIza key → gemini
        dlg._key.setText("AIzaTest")
        dlg._shots.setChecked(False)
        edges0 = len(vp.scene.mesh.edges)

        dlg._input.setText("modela la fuente de la foto")
        dlg._on_send()
        app = QApplication.instance()
        for _ in range(2000):
            app.processEvents()
            if not dlg._busy:
                break
        assert not dlg._busy

        # The retry request went out, the shorter block ran, the loop ended
        # on the closing summary — and every turn asked for Gemini's budget
        # (its hidden thinking bills against the same max_tokens).
        assert any("se cortó a mitad del bloque" in m["text"]
                   for m in seen[1] if m["role"] == "user")
        assert len(vp.scene.mesh.edges) == edges0 + 1
        assert budgets == [TOKENS_BY_PROVIDER["gemini"]] * 3
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


def test_step_limit_announces_instead_of_silent_stop(monkeypatch):
    # Second live failure mode: the model was still sending recipes when
    # MAX_ROUNDS ran out and the loop just went quiet. Now it says so and
    # points at "continue" (the convo survives, so continuing works).
    import plugins.ai_assistant as pa
    from views.main_window import MainWindow

    monkeypatch.setattr(pa, "MAX_ROUNDS", 1)
    replies = iter([
        "Paso 1:\n```python\nprint('a')\n```",
        "Paso 2:\n```python\n"
        "mesh.add_edge(QVector3D(0,0,0), QVector3D(1,0,0))\n```",
    ])
    monkeypatch.setattr(ai, "chat",
                        lambda *a, **k: next(replies))

    win = MainWindow()
    try:
        vp = win.viewport
        dlg = pa.AsistenteDialog(vp, parent=win)
        dlg._provider.setCurrentIndex(0)   # Auto: the AIza key → gemini
        dlg._key.setText("AIzaTest")
        dlg._shots.setChecked(False)
        edges0 = len(vp.scene.mesh.edges)

        dlg._input.setText("haz dos pasos")
        dlg._on_send()
        app = QApplication.instance()
        for _ in range(2000):
            app.processEvents()
            if not dlg._busy:
                break
        assert not dlg._busy

        # The second recipe was NOT executed (limit hit) and the chat says
        # why instead of ending silently.
        assert len(vp.scene.mesh.edges) == edges0
        assert "Step limit reached" in dlg._chat.toPlainText()
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


def test_encode_photo_rejects_garbage(tmp_path):
    from plugins.ai_assistant import AsistenteDialog
    from views.main_window import MainWindow
    bad = tmp_path / "no-es-imagen.jpg"
    bad.write_bytes(b"not an image at all")
    win = MainWindow()
    try:
        dlg = AsistenteDialog(win.viewport, parent=win)
        assert dlg._encode_photo(str(bad)) is None
        dlg._attach_photo(str(bad))                    # reports, no crash
        assert dlg._foto is None
        assert "Could not read the image." in dlg._chat.toPlainText()
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


def test_chat_colors_follow_theme():
    from PySide6.QtGui import QColor, QPalette
    from plugins.ai_assistant import AsistenteDialog
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        dlg = AsistenteDialog(win.viewport, parent=win)
        light = QPalette()
        light.setColor(QPalette.ColorRole.Base, QColor("#ffffff"))
        dlg.setPalette(light)
        assert dlg._chat_colors()["ai"] == "#1a202c"
        dark = QPalette()
        dark.setColor(QPalette.ColorRole.Base, QColor("#252525"))
        dlg.setPalette(dark)
        assert dlg._chat_colors()["ai"] == "#e8eaed"   # readable on dark
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


def test_each_provider_remembers_its_own_key_and_model(monkeypatch, tmp_path):
    # Pasting the Gemini key must not erase the Groq one: switching
    # providers when tokens run out has to be two clicks (user report).
    from PySide6.QtCore import QSettings
    from plugins.ai_assistant import AsistenteDialog
    from views.main_window import MainWindow
    ini = str(tmp_path / "cfg.ini")
    monkeypatch.setattr(
        AsistenteDialog, "_settings",
        lambda self: QSettings(ini, QSettings.Format.IniFormat))
    win = MainWindow()
    try:
        dlg = AsistenteDialog(win.viewport, parent=win)
        dlg._provider.setCurrentIndex(dlg._provider.findData("groq"))
        dlg._key.setText("gsk_AAA")
        dlg._model.setEditText("openai/gpt-oss-120b")

        dlg._provider.setCurrentIndex(dlg._provider.findData("gemini"))
        assert dlg._key.text() == ""                 # gemini slot is empty
        dlg._key.setText("AIzaBBB")

        dlg._provider.setCurrentIndex(dlg._provider.findData("groq"))
        assert dlg._key.text() == "gsk_AAA"          # restored
        assert dlg._model.currentText() == "openai/gpt-oss-120b"

        dlg._provider.setCurrentIndex(dlg._provider.findData("gemini"))
        assert dlg._key.text() == "AIzaBBB"          # gemini kept its own

        # A fresh dialog on the same settings restores the last provider.
        dlg._save_settings()
        dlg2 = AsistenteDialog(win.viewport, parent=win)
        assert dlg2._provider.currentData() == "gemini"
        assert dlg2._key.text() == "AIzaBBB"
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()
