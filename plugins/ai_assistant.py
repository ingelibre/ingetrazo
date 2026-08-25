# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Asistente IA — model with AI from INSIDE IngeTrazo (Ctrl+Shift+A).

The user types what they want; the model answers in Spanish and acts by
emitting ONE ```python recipe per turn, which runs through the shared
transactional executor (core.ai): one undo step per action, whole-rollback
on error, the hermeticity guard validating every solid. After each action
the assistant receives the result — and, for vision-capable providers, a
live viewport screenshot, so it SEES what it built and iterates.

Providers follow the IngePresupuestos convention the user already knows:
paste ONE API key and the provider is detected by its prefix (gsk_ → Groq,
sk-ant- → Anthropic, AIza → Gemini, sk-or- → OpenRouter, sk- → OpenAI), or
leave it empty for a local Ollama. Model name and Ollama URL are editable;
everything persists in QSettings. Network calls run on a worker thread —
the recipes always execute on the Qt main thread.
"""
from __future__ import annotations

import base64
import threading

from PySide6.QtCore import QBuffer, QIODevice, QSettings, Qt, Signal
from PySide6.QtGui import QFontDatabase, QPalette
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

from core import ai
from core.i18n import tr
from tools.base import Tool

MAX_ROUNDS = 8

SYSTEM_PROMPT = """Eres el asistente de modelado de IngeTrazo, un modelador \
3D libre estilo SketchUp (Z-up, unidades en METROS). Conversas en español, \
breve y claro.

Para ACTUAR sobre el modelo incluye EXACTAMENTE UN bloque ```python por \
respuesta. Tras cada bloque recibirás su resultado (stdout/errores y, si \
está disponible, una captura del viewport) — revísalo e itera. Cuando el \
pedido esté terminado, responde SIN bloque de código con un resumen corto.

En el scope del bloque tienes: scene, mesh, selection, groups, layers, \
viewport, QVector3D, Mesh, Group, Edge, Face, bim.
Recetario:
- Cara: f = mesh.add_face([QVector3D(x,y,z), ...])  (lazo antihorario visto \
desde afuera; los sólidos se construyen cara a cara, cerrados)
- Color: f.attrs["color"] = (r, g, b, 1.0)  (0..1)
- Arista: mesh.add_edge(QVector3D(...), QVector3D(...))
- Grupo: m = Mesh(); m.add_face([...]); g = Group(m, name="..."); \
groups.append(g)
- Cámara: viewport.camera.target/distance/yaw/pitch; viewport.update()
- print(...) para reportar datos.
Cada bloque es UN paso de undo y se revierte ENTERO si lanza una excepción. \
Construye por pasos pequeños y verifica con las capturas."""


class AsistenteDialog(QDialog):
    _reply = Signal(object)     # object, not dict: queued dicts get COPIED

    def __init__(self, viewport, parent=None) -> None:
        super().__init__(parent or viewport.window())
        self._viewport = viewport
        self._scope: dict = {"__name__": "__ai__"}
        self._convo: list[dict] = []
        self._busy = False
        self._round = 0
        self._reply.connect(self._on_reply, Qt.QueuedConnection)

        self.setWindowTitle(tr("AI Assistant") + " — IngeTrazo")
        self.setMinimumSize(560, 520)
        self.resize(640, 620)
        self._build_ui()
        self._load_settings()

    # ---- UI -----------------------------------------------------------------
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        row0 = QHBoxLayout()
        row0.addWidget(QLabel(tr("Provider:")))
        self._provider = QComboBox()
        self._provider.addItem(tr("Auto (by key prefix)"), "auto")
        for prov in ai.PROVIDERS:
            self._provider.addItem(ai.PROVIDER_INFO[prov][0], prov)
        self._provider.currentIndexChanged.connect(self._on_provider_changed)
        row0.addWidget(self._provider, 1)
        self._model = QComboBox()
        self._model.setEditable(True)
        self._model.setInsertPolicy(QComboBox.NoInsert)
        self._model.lineEdit().setPlaceholderText(
            tr("model (default per provider)"))
        row0.addWidget(self._model, 1)
        self._modelos = QPushButton(tr("Models"))
        self._modelos.setToolTip(
            tr("List the models your key can use"))
        self._modelos.clicked.connect(self._on_modelos)
        row0.addWidget(self._modelos)
        self._probar = QPushButton(tr("Test connection"))
        self._probar.clicked.connect(self._on_probar)
        row0.addWidget(self._probar)
        layout.addLayout(row0)

        row = QHBoxLayout()
        row.addWidget(QLabel(tr("API key:")))
        self._key = QLineEdit()
        self._key.setEchoMode(QLineEdit.Password)
        self._key.setPlaceholderText(tr("empty = local Ollama"))
        self._key.textChanged.connect(self._on_key_changed)
        row.addWidget(self._key, 1)
        layout.addLayout(row)

        self._key_link = QLabel("")
        self._key_link.setOpenExternalLinks(True)
        layout.addWidget(self._key_link)

        row2 = QHBoxLayout()
        self._shots = QCheckBox(tr("Send viewport screenshots to the model"))
        self._shots.setChecked(True)
        row2.addWidget(self._shots)
        row2.addStretch()
        self._ollama = QLineEdit("http://localhost:11434")
        self._ollama.setMaximumWidth(220)
        self._ollama.setToolTip(tr("Ollama URL (key left empty)"))
        row2.addWidget(self._ollama)
        layout.addLayout(row2)

        self._chat = QTextEdit()
        self._chat.setReadOnly(True)
        self._chat.setFont(
            QFontDatabase.systemFont(QFontDatabase.FixedFont))
        layout.addWidget(self._chat, 1)

        row3 = QHBoxLayout()
        self._input = QLineEdit()
        self._input.setPlaceholderText(
            tr("e.g. draw a 6×4 m house with a gable roof"))
        self._input.returnPressed.connect(self._on_send)
        row3.addWidget(self._input, 1)
        self._send = QPushButton(tr("Send"))
        self._send.clicked.connect(self._on_send)
        row3.addWidget(self._send)
        layout.addLayout(row3)

    def _chat_colors(self) -> dict:
        """Text colors that read on the CURRENT theme — hardcoded
        light-theme grays vanish on a dark chat background (user report)."""
        dark = self.palette().color(QPalette.ColorRole.Base).lightness() < 128
        if dark:
            return {"user": "#7ab7ff", "ai": "#e8eaed", "muted": "#9aa5b1",
                    "ok": "#7ce0a3", "err": "#ff8f8f"}
        return {"user": "#2b6cb0", "ai": "#1a202c", "muted": "#718096",
                "ok": "#2f855a", "err": "#c53030"}

    def _append(self, text: str, role: str) -> None:
        color = self._chat_colors()[role]
        self._chat.append(f'<pre style="color:{color}; white-space:pre-wrap; '
                          f'margin:2px">{_esc(text)}</pre>')
        self._chat.verticalScrollBar().setValue(
            self._chat.verticalScrollBar().maximum())

    # ---- Settings -----------------------------------------------------------
    def _settings(self) -> QSettings:
        return QSettings()

    def _load_settings(self) -> None:
        st = self._settings()
        self._key.setText(str(st.value("ia/api_key", "") or ""))
        self._model.setEditText(str(st.value("ia/modelo", "") or ""))
        self._ollama.setText(str(st.value("ia/ollama_url",
                                          "http://localhost:11434") or ""))
        self._shots.setChecked(str(st.value("ia/capturas", "1")) != "0")
        stored = str(st.value("ia/proveedor", "auto") or "auto")
        idx = self._provider.findData(stored)
        if idx >= 0:
            self._provider.setCurrentIndex(idx)
        self._on_key_changed()

    def _save_settings(self) -> None:
        st = self._settings()
        st.setValue("ia/api_key", self._key.text())
        st.setValue("ia/modelo", self._model.currentText().strip())
        st.setValue("ia/ollama_url", self._ollama.text().strip())
        st.setValue("ia/capturas", "1" if self._shots.isChecked() else "0")
        st.setValue("ia/proveedor", self._provider.currentData())
        self._stash_credentials(st, self._provider.currentData())

    def _stash_credentials(self, st: QSettings, slot) -> None:
        """Remember the current key/model under the provider they belong
        to (detected by prefix when the combo is on Auto). Empty fields
        never clobber a stored value."""
        key = self._key.text().strip()
        provider = (slot if slot not in (None, "auto")
                    else ai.detect_provider(key))
        if provider == "ollama":
            return
        if key:
            st.setValue(f"ia/claves/{provider}", self._key.text())
        model = self._model.currentText().strip()
        if model:
            st.setValue(f"ia/modelos/{provider}", model)

    def _on_provider_changed(self) -> None:
        """EACH provider keeps its own key and model: pasting the Gemini
        key must not erase the Groq one (user report) — running out of
        tokens on one plan and switching has to be two clicks."""
        st = self._settings()
        self._stash_credentials(st, getattr(self, "_prov_slot", None))
        cur = self._provider.currentData()
        self._prov_slot = cur
        if cur and cur != "auto":
            self._key.setText(str(st.value(f"ia/claves/{cur}", "") or ""))
            self._model.clear()      # the fetched model list is per provider
            self._model.setEditText(
                str(st.value(f"ia/modelos/{cur}", "") or ""))
        self._on_key_changed()

    def _effective_provider(self) -> str:
        chosen = self._provider.currentData()
        if chosen and chosen != "auto":
            return chosen
        return ai.detect_provider(self._key.text().strip())

    def _on_key_changed(self) -> None:
        provider = self._effective_provider()
        label, url = ai.PROVIDER_INFO[provider]
        if provider == "ollama":
            self._key_link.setText(tr(
                "Local models — install from <a href='{url}'>{url}</a>",
                url=url))
        else:
            self._key_link.setText(tr(
                "{name} — get your key at <a href='{url}'>{url}</a>",
                name=label, url=url))
        self._model.lineEdit().setPlaceholderText(
            ai.DEFAULT_MODELS[provider])
        self._ollama.setVisible(provider == "ollama")

    def _config(self) -> tuple[str, str, str, str]:
        key = self._key.text().strip()
        provider = self._effective_provider()
        model = (self._model.currentText().strip()
                 or ai.DEFAULT_MODELS[provider])
        return provider, model, key, self._ollama.text().strip()

    def _on_modelos(self) -> None:
        if self._busy:
            return
        self._save_settings()
        provider, _model, key, ollama = self._config()
        self._append(tr("Fetching the model list from {name}…",
                        name=ai.PROVIDER_INFO[provider][0]), "muted")
        self._modelos.setEnabled(False)

        def worker() -> None:
            try:
                models = ai.list_models(provider, key, ollama)
                self._reply.emit({"modelos": True, "ok": True,
                                  "models": models})
            except Exception as exc:  # noqa: BLE001 — shown in the chat
                self._reply.emit({"modelos": True, "ok": False,
                                  "msg": str(exc)})

        threading.Thread(target=worker, daemon=True).start()

    def _on_probar(self) -> None:
        if self._busy:
            return
        self._save_settings()
        provider, model, key, ollama = self._config()
        self._append(tr("Testing {name} ({model})…",
                        name=ai.PROVIDER_INFO[provider][0], model=model),
                     "muted")
        self._probar.setEnabled(False)

        def worker() -> None:
            ok, msg = ai.probar_conexion(provider, model, key, ollama)
            self._reply.emit({"probar": True, "ok": ok, "msg": msg})

        threading.Thread(target=worker, daemon=True).start()

    # ---- Chat loop ----------------------------------------------------------
    def _on_send(self) -> None:
        if self._busy:
            return
        prompt = self._input.text().strip()
        if not prompt:
            return
        self._input.clear()
        self._save_settings()
        self._append(f"Tú: {prompt}", "user")
        self._convo.append({"role": "user", "text": prompt})
        self._round = 0
        self._next_turn()

    def _next_turn(self) -> None:
        self._busy = True
        self._send.setEnabled(False)
        self._append(tr("thinking…"), "muted")
        provider, model, key, ollama = self._config()
        convo = list(self._convo)

        def worker() -> None:
            try:
                text = ai.chat(provider, model, key, SYSTEM_PROMPT, convo,
                               ollama_url=ollama)
                self._reply.emit({"ok": True, "text": text})
            except Exception as exc:  # noqa: BLE001 — shown in the chat
                self._reply.emit({"ok": False, "error": str(exc)})

        threading.Thread(target=worker, daemon=True).start()

    def _on_reply(self, msg: dict) -> None:
        if msg.get("modelos"):
            self._modelos.setEnabled(True)
            if msg.get("ok"):
                models = msg.get("models") or []
                current = self._model.currentText()
                self._model.clear()
                self._model.addItems(models)
                self._model.setEditText(current)
                self._append(tr(
                    "{n} models available to your key — pick one from "
                    "the list.", n=len(models)), "ok")
                self._model.showPopup()
            else:
                self._append(tr("Could not list models: {err}",
                                err=msg.get("msg")), "err")
            return
        if msg.get("probar"):
            self._probar.setEnabled(True)
            if msg.get("ok"):
                self._append(tr("Connection OK — the model answered."),
                             "ok")
            else:
                self._append(tr("Connection failed: {err}",
                                err=msg.get("msg")), "err")
                if "model_not_found" in str(msg.get("msg")):
                    self._append(tr(
                        'That model no longer exists for your key — press '
                        '"Models" to list the available ones.'), "err")
            return
        if not msg.get("ok"):
            self._append(tr("Error: {err}", err=msg.get("error")), "err")
            self._finish()
            return
        text = msg["text"]
        self._convo.append({"role": "assistant", "text": text})
        self._append(f"IA: {text}", "ai")
        code = ai.extract_code(text)
        if code is None or self._round >= MAX_ROUNDS:
            self._finish()
            return
        self._round += 1
        result = ai.run_transactional(self._viewport, code, self._scope)
        summary = []
        if result["stdout"]:
            summary.append(result["stdout"].rstrip())
        if result["error"]:
            summary.append("ERROR (todo revertido): " + str(result["error"]))
            if result["stderr"]:
                summary.append(result["stderr"].rstrip()[-800:])
        summary.append(f"(cambió el modelo: {result['changed']})")
        feedback = "Resultado de la ejecución:\n" + "\n".join(summary)
        self._append(feedback, "muted")
        provider = self._config()[0]
        shot = None
        if self._shots.isChecked() and provider in ai.VISION:
            shot = self._screenshot_b64()
        self._convo.append({"role": "user", "text": feedback,
                            **({"image_png_b64": shot} if shot else {})})
        self._next_turn()

    def _finish(self) -> None:
        self._busy = False
        self._send.setEnabled(True)

    def _screenshot_b64(self) -> str | None:
        try:
            image = self._viewport.render_image(768, 512)
            buf = QBuffer()
            buf.open(QIODevice.WriteOnly)
            image.save(buf, "PNG")
            return base64.b64encode(bytes(buf.data())).decode()
        except Exception:  # noqa: BLE001 — vision is best-effort
            return None


def _esc(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))


class AIAssistantTool(Tool):
    """Extensions-menu entry that opens (or raises) the assistant."""
    name = "AI Assistant"
    shortcut = "Ctrl+Shift+A"
    uses_snap = False

    def on_activate(self, viewport) -> None:
        window = viewport.window()
        dialog = getattr(window, "_ai_assistant", None)
        if dialog is None or not dialog.isVisible():
            dialog = AsistenteDialog(viewport, parent=window)
            window._ai_assistant = dialog
            dialog.show()
        else:
            dialog.raise_()
            dialog.activateWindow()

    def on_deactivate(self, viewport) -> None:
        pass
