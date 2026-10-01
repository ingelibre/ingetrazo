# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Asistente IA — model with AI from INSIDE IngeTrazo, in the side tray's
«AI» tab (Ctrl+Shift+A brings it forward, even when hidden).

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
from PySide6.QtGui import QFontDatabase, QImageReader, QPalette
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core import ai, ai_recipes
from core.i18n import tr
from views.filedialogs import file_dialogs
from views.fold_section import FoldSection, narrow, wrapping_form

MAX_ROUNDS = 12

#: Reply budget per turn. 4096 was not enough for chatty coders (gemini
#: 2.5 flash got cut mid-```python and the loop ended with nothing drawn);
#: every provider we speak accepts 8192 output tokens.
MAX_TOKENS = 8192

#: Gemini 2.5 models bill their hidden "thinking" against the SAME
#: max_tokens — flash kept getting cut even at 8192 (seen live modeling a
#: fountain). Both 2.5 flash and pro accept 16384.
TOKENS_BY_PROVIDER = {"gemini": 16384}

#: The assistant's own voice and its one-block-per-reply contract; the
#: modelling reference itself is shared with the MCP door (core.ai_recipes),
#: so a new helper is taught once and both doors learn it.
SYSTEM_PROMPT = "\n".join((
    "Eres el asistente de modelado de IngeTrazo. " + ai_recipes.UNITS
    + " Conversas en español, breve y claro.",
    """
Para ACTUAR sobre el modelo incluye EXACTAMENTE UN bloque ```python por \
respuesta. Tras cada bloque recibirás su resultado (stdout/errores y, si \
está disponible, una captura del viewport) — revísalo e itera. Cuando el \
pedido esté terminado, responde SIN bloque de código con un resumen corto. \
SIN bloque no se ejecuta nada: nunca describas como hecho lo que no has \
ejecutado.""".strip(),
    ai_recipes.SCOPE,
    ai_recipes.RECIPES,
    ai_recipes.HOW_IT_RUNS.format(unit="bloque"),
    """El código de tus recetas viejas se resume como "[receta ya \
ejecutada]"; su efecto sigue en el modelo.

Si el usuario adjunta una FOTO de un objeto (una fuente, un mueble, una \
fachada): identifica sus partes y proporciones y recréalo por partes, cada \
una como grupo con nombre. Una foto NO trae medidas: usa las que el usuario \
dé y declara como supuesto toda dimensión que estimes de la imagen. Para \
piezas torneadas (platos, columnas, jarrones) usa revolve(). Compara tus \
capturas contra la foto e itera hasta que la silueta calce.""",
))


_BUILD_WORDS = ("dibuj", "crea", "haz", "hac", "modela", "constru", "añad",
                "agreg", "pon", "gener", "diseñ", "levant", "arma", "traza",
                "draw", "build", "make", "create", "add")


def _asks_to_build(prompt: str) -> bool:
    """Whether the user's message asks for something to be modelled (so a
    reply without code is a model that did not do its job)."""
    low = (prompt or "").lower()
    return any(w in low for w in _BUILD_WORDS)


class PromptEdit(QPlainTextEdit):
    """The prompt: several lines, Enter sends, Shift+Enter breaks a line.
    ``text``/``setText`` as the one-line field it replaces had."""
    submitted = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setTabChangesFocus(True)
        line = self.fontMetrics().lineSpacing()
        self.setMinimumHeight(2 * line + 12)

    def keyPressEvent(self, ev) -> None:
        if (ev.key() in (Qt.Key_Return, Qt.Key_Enter)
                and not ev.modifiers() & (Qt.ShiftModifier
                                          | Qt.ControlModifier)):
            self.submitted.emit()
            return
        super().keyPressEvent(ev)

    def text(self) -> str:
        return self.toPlainText()

    def setText(self, text: str) -> None:
        self.setPlainText(text)


class AsistentePanel(QWidget):
    """The assistant as the «AI» tab of the side tray: the connection
    settings fold away, the chat takes the rest of the height."""
    _reply = Signal(object)     # object, not dict: queued dicts get COPIED

    def __init__(self, viewport, parent=None) -> None:
        super().__init__(parent)
        self._viewport = viewport
        self._scope: dict = {"__name__": "__ai__"}
        self._convo: list[dict] = []
        self._busy = False
        self._round = 0
        self._nudged = False
        self._last_prompt = ""
        self._foto: tuple[str, str, str] | None = None  # (b64, mime, name)
        self._reply.connect(self._on_reply, Qt.QueuedConnection)
        self._build_ui()
        self._load_settings()

    # ---- UI -----------------------------------------------------------------
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 0)

        conn = FoldSection(tr("AI Assistant — connection"),
                           "ia/open_connection")
        self._connection = conn
        form = wrapping_form(conn.body)
        self._provider = QComboBox()
        self._provider.addItem(tr("Auto (by key prefix)"), "auto")
        for prov in ai.PROVIDERS:
            self._provider.addItem(ai.PROVIDER_INFO[prov][0], prov)
        self._provider.currentIndexChanged.connect(self._on_provider_changed)
        form.addRow(tr("Provider:"), self._provider)

        self._key = QLineEdit()
        self._key.setEchoMode(QLineEdit.Password)
        self._key.setPlaceholderText(tr("empty = local AI (Ollama, LM Studio)"))
        self._key.textChanged.connect(self._on_key_changed)
        self._key.editingFinished.connect(self._save_settings)
        form.addRow(tr("API key:"), self._key)

        self._key_link = QLabel("")
        self._key_link.setOpenExternalLinks(True)
        self._key_link.setWordWrap(True)
        form.addRow(self._key_link)

        self._model = QComboBox()
        self._model.setEditable(True)
        self._model.setInsertPolicy(QComboBox.NoInsert)
        self._model.lineEdit().setPlaceholderText(
            tr("model (default per provider)"))
        self._model.lineEdit().editingFinished.connect(self._save_settings)
        form.addRow(tr("Model:"), self._model)

        buttons = QHBoxLayout()
        self._modelos = QPushButton(tr("Models"))
        self._modelos.setToolTip(
            tr("List the models your key can use"))
        self._modelos.clicked.connect(self._on_modelos)
        buttons.addWidget(self._modelos)
        self._probar = QPushButton(tr("Test connection"))
        self._probar.clicked.connect(self._on_probar)
        buttons.addWidget(self._probar)
        form.addRow(buttons)

        self._ollama = QLineEdit("http://localhost:11434")
        self._ollama.setToolTip(tr("Local AI server — Ollama: http://localhost:11434, LM Studio: http://localhost:1234 (key left empty)"))
        self._ollama.editingFinished.connect(self._save_settings)
        self._ollama_label = QLabel(tr("Server:"))
        form.addRow(self._ollama_label, self._ollama)

        self._shots = QCheckBox(tr("Send viewport screenshots to the model"))
        self._shots.setChecked(True)
        self._shots.toggled.connect(lambda _on: self._save_settings())
        form.addRow(self._shots)
        narrow(self._provider, self._model, self._key, self._ollama,
               self._shots, self._modelos, self._probar)
        layout.addWidget(conn)

        self._chat = QTextEdit()
        self._chat.setReadOnly(True)
        self._chat.setFont(
            QFontDatabase.systemFont(QFontDatabase.FixedFont))
        self._chat.setMinimumHeight(80)

        # The prompt under the chat, with a handle between them to give it
        # more room (Marco: «ese espacio es muy pequeño para un prompt»).
        bottom = QWidget()
        bl = QVBoxLayout(bottom)
        bl.setContentsMargins(0, 0, 0, 0)
        chip_row = QHBoxLayout()
        self._foto_chip = QLabel("")
        chip_row.addWidget(self._foto_chip, 1)
        narrow(self._foto_chip)
        self._foto_quitar = QPushButton("✕")
        self._foto_quitar.setFixedWidth(28)
        self._foto_quitar.setToolTip(tr("Remove the photo"))
        self._foto_quitar.clicked.connect(self._clear_foto)
        chip_row.addWidget(self._foto_quitar)
        bl.addLayout(chip_row)

        self._input = PromptEdit()
        self._input.setPlaceholderText(
            tr("e.g. draw a 6×4 m house with a gable roof")
            + "\n" + tr("Enter sends · Shift+Enter: new line"))
        self._input.submitted.connect(self._on_send)
        bl.addWidget(self._input, 1)

        split = QSplitter(Qt.Vertical)
        split.setChildrenCollapsible(False)
        split.addWidget(self._chat)
        split.addWidget(bottom)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 1)
        line = self._input.fontMetrics().lineSpacing()
        split.setSizes([400, 6 * line + 16])
        layout.addWidget(split, 1)

        row3 = QHBoxLayout()
        self._adjuntar = QPushButton(tr("Photo…"))
        self._adjuntar.setToolTip(tr(
            "Attach a photo — the model recreates what it shows "
            "(give it the real measurements)"))
        self._adjuntar.clicked.connect(self._on_foto)
        row3.addWidget(self._adjuntar)
        row3.addStretch()
        self._send = QPushButton(tr("Send"))
        self._send.clicked.connect(self._on_send)
        row3.addWidget(self._send)
        layout.addLayout(row3)
        self._clear_foto()

    def focus_input(self) -> None:
        self._input.setFocus(Qt.ShortcutFocusReason)

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
        self._loading = True
        try:
            self._read_settings()
        finally:
            self._loading = False

    def _read_settings(self) -> None:
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
        if getattr(self, "_loading", False):
            return
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
        self._ollama_label.setVisible(provider == "ollama")

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

    def _missing_key_hint(self, provider: str, key: str) -> str | None:
        """The plain-words message for a hosted provider with no key, or
        None when there is nothing to say. Rafael picked «Groq (gratis)»,
        left the key empty and Test connection answered with Groq's raw
        ``HTTP 401 {"error":{"message":"Invalid API Key"…`` (Revisión 3,
        2026-09-20). A missing key is known BEFORE any network round trip,
        and the fix is one sentence, not a JSON blob."""
        if key or provider == "ollama":
            return None
        label, url = ai.PROVIDER_INFO[provider]
        return tr(
            "{name} needs an API key — the quota is free, the key is not "
            "optional. Create one at {url} (the link under the key field "
            "opens it) and paste it in the \"API key\" field — it is saved "
            "in your user profile, never in the document.", name=label,
            url=url)

    @staticmethod
    def _bad_key_hint(provider: str, err: str) -> str | None:
        """A rejected key (HTTP 401/403, or the providers' own wording),
        translated into what to check."""
        low = (err or "").lower()
        if not ("401" in low or "403" in low or "invalid api key" in low
                or "invalid_api_key" in low or "incorrect api key" in low
                or "invalid x-api-key" in low or "api key not valid" in low
                or "authentication" in low):
            return None
        label, url = ai.PROVIDER_INFO.get(provider, ("", ""))
        prefixes = {"groq": "gsk_", "anthropic": "sk-ant-", "gemini": "AIza",
                    "openrouter": "sk-or-", "openai": "sk-"}
        pre = prefixes.get(provider)
        tail = (tr(" A {name} key starts with «{prefix}».", name=label,
                   prefix=pre) if pre else "")
        return tr(
            "{name} rejected the key. Check it was pasted whole, with no "
            "spaces, and that it belongs to this provider — or create a new "
            "one at {url}.", name=label, url=url) + tail

    def _on_probar(self) -> None:
        if self._busy:
            return
        self._save_settings()
        provider, model, key, ollama = self._config()
        hint = self._missing_key_hint(provider, key)
        if hint is not None:
            self._append(hint, "err")
            return
        self._append(tr("Testing {name} ({model})…",
                        name=ai.PROVIDER_INFO[provider][0], model=model),
                     "muted")
        self._probar.setEnabled(False)

        def worker() -> None:
            ok, msg = ai.probar_conexion(provider, model, key, ollama)
            self._reply.emit({"probar": True, "ok": ok, "msg": msg})

        threading.Thread(target=worker, daemon=True).start()

    # ---- Photo attachment ---------------------------------------------------
    #: Longest edge a photo is scaled down to before upload. Enough detail
    #: to read shapes; the convo is resent EVERY turn, so size compounds.
    FOTO_MAX_EDGE = 1280

    def _on_foto(self) -> None:
        path, _f = file_dialogs.getOpenFileName(
            self, tr("Attach a photo"), "",
            tr("Images (*.png *.jpg *.jpeg *.bmp *.tif *.tiff *.webp)"
               ";;All files (*)"))
        if path:
            self._attach_photo(path)

    def _attach_photo(self, path: str) -> None:
        encoded = self._encode_photo(path)
        if encoded is None:
            self._append(tr("Could not read the image."), "err")
            return
        name = path.rsplit("/", 1)[-1]
        self._foto = (*encoded, name)
        self._foto_chip.setText("📷 " + name)
        self._foto_chip.setVisible(True)
        self._foto_quitar.setVisible(True)
        self._append(tr(
            "Photo attached: {name} — it goes with your next message. "
            "Include the real measurements: a photo has none.", name=name),
            "muted")

    def _encode_photo(self, path: str) -> tuple[str, str] | None:
        """(base64, mime) of the photo, EXIF-rotated and scaled down to
        FOTO_MAX_EDGE, re-encoded as JPEG (a photo as PNG is ~10× the
        bytes, and the payload rides on every later turn)."""
        reader = QImageReader(path)
        reader.setAutoTransform(True)      # phone photos carry EXIF rotation
        image = reader.read()
        if image.isNull():
            return None
        if max(image.width(), image.height()) > self.FOTO_MAX_EDGE:
            if image.width() >= image.height():
                image = image.scaledToWidth(
                    self.FOTO_MAX_EDGE, Qt.SmoothTransformation)
            else:
                image = image.scaledToHeight(
                    self.FOTO_MAX_EDGE, Qt.SmoothTransformation)
        buf = QBuffer()
        buf.open(QIODevice.WriteOnly)
        image.save(buf, "JPEG", 85)
        return base64.b64encode(bytes(buf.data())).decode(), "image/jpeg"

    def _clear_foto(self) -> None:
        self._foto = None
        self._foto_chip.setVisible(False)
        self._foto_quitar.setVisible(False)

    # ---- Chat loop ----------------------------------------------------------
    def _on_send(self) -> None:
        if self._busy:
            return
        prompt = self._input.text().strip()
        if not prompt:
            return
        provider, _model, key, _ollama = self._config()
        hint = self._missing_key_hint(provider, key)
        if hint is not None:
            self._append(hint, "err")     # the prompt stays in the box
            return
        self._input.clear()
        self._save_settings()
        self._append(f"Tú: {prompt}", "user")
        message: dict = {"role": "user", "text": prompt}
        if self._foto is not None:
            b64, mime, name = self._foto
            message["image_b64"] = b64
            message["image_mime"] = mime
            self._append(f"[📷 {name}]", "user")
            provider, model = self._config()[:2]
            if not ai.supports_vision(provider, model):
                self._append(tr(
                    "Heads-up: {model} has no vision, so the photo will "
                    "NOT be sent — it is kept, and flows again when you "
                    "switch to a vision model (Anthropic, OpenAI, Gemini, "
                    "OpenRouter).", model=model), "muted")
            self._clear_foto()
        self._convo.append(message)
        self._round = 0
        self._nudged = False
        self._last_prompt = prompt
        self._next_turn()

    def _next_turn(self) -> None:
        self._busy = True
        self._send.setEnabled(False)
        self._append(tr("thinking…"), "muted")
        provider, model, key, ollama = self._config()
        convo = ai.compact_messages(ai.slim_messages(
            self._convo, vision=ai.supports_vision(provider, model)))

        budget = TOKENS_BY_PROVIDER.get(provider, MAX_TOKENS)

        def on_retry(n, total, wait, reason) -> None:
            # A busy provider (Gemini's 503 «high demand»): say so and
            # wait, instead of ending the recipe at the walls.
            self._reply.emit({"retry": True, "n": n, "total": total,
                              "wait": wait, "reason": reason})

        def worker() -> None:
            try:
                text = ai.chat(provider, model, key, SYSTEM_PROMPT, convo,
                               ollama_url=ollama, max_tokens=budget,
                               on_retry=on_retry)
                self._reply.emit({"ok": True, "text": text})
            except Exception as exc:  # noqa: BLE001 — shown in the chat
                self._reply.emit({"ok": False, "error": str(exc)})

        threading.Thread(target=worker, daemon=True).start()

    def _on_reply(self, msg: dict) -> None:
        if msg.get("retry"):
            reason = str(msg.get("reason", ""))
            short = reason.split(":", 1)[0]
            self._append(tr(
                "The provider is busy ({why}) — retry {n} of {total} in {wait} s…",
                why=short, n=msg.get("n"), total=msg.get("total"),
                wait=int(msg.get("wait", 0))), "muted")
            return
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
                bad = self._bad_key_hint(self._effective_provider(),
                                         str(msg.get("msg")))
                if bad is not None:
                    self._append(bad, "err")
                if "model_not_found" in str(msg.get("msg")):
                    self._append(tr(
                        'That model no longer exists for your key — press '
                        '"Models" to list the available ones.'), "err")
            return
        if not msg.get("ok"):
            self._append(tr("Error: {err}", err=msg.get("error")), "err")
            self._finish()
            return
        text = ai.strip_thoughts(msg["text"])
        self._convo.append({"role": "assistant", "text": text})
        self._append(f"IA: {text}", "ai")
        code = ai.extract_code(text)
        if code is None and ai.truncated_code(text):
            # Cut by max_tokens mid-recipe: half a block must neither run
            # nor end the loop silently — ask for a smaller, complete one.
            if self._round < MAX_ROUNDS:
                self._round += 1
                self._append(tr("The reply was cut off mid-code — asking "
                                "for a shorter, complete block."), "muted")
                self._convo.append({"role": "user", "text":
                    "Tu respuesta se cortó a mitad del bloque ```python "
                    "(límite de tokens). NO continúes donde quedaste: "
                    "reenvía UN bloque completo y más corto, avanzando "
                    "solo la primera parte del trabajo; el resto irá en "
                    "turnos siguientes."})
                self._next_turn()
                return
            self._append(tr('The reply was cut off and the step limit is '
                            'used up — type "continue" to keep going.'),
                         "err")
            self._finish()
            return
        if code is not None and self._round >= MAX_ROUNDS:
            # A recipe arrived but the budget for ONE request is spent:
            # never swallow it silently — the convo survives, so any new
            # message (e.g. "continúa") picks up exactly here.
            self._append(tr('Step limit reached for one request '
                            '({n}) — type "continue" to keep going.',
                            n=MAX_ROUNDS), "muted")
            self._finish()
            return
        if code is None:
            if self._round == 0 and not self._nudged and _asks_to_build(
                    self._last_prompt) and "?" not in text[-80:]:
                # A model that narrates a build it never sent (Groq's
                # compound answered «se añadió una cumbrera…» with no
                # block, Marco 2026-09-15): one push, then let it be.
                self._nudged = True
                self._append(tr("No code came back — asking for the recipe."),
                             "muted")
                self._convo.append({"role": "user", "text":
                    "No incluiste ningún bloque ```python: NADA se ejecutó "
                    "y el modelo no cambió. Escribe ahora la receta completa "
                    "en UN bloque ```python (sin describirla antes)."})
                self._next_turn()
                return
            self._finish()
            return
        self._round += 1
        result = ai.run_transactional(self._viewport, code, self._scope)
        summary = []
        if result["stdout"]:
            out = result["stdout"].rstrip()
            if len(out) > 1500:      # a print-happy recipe rides EVERY turn
                out = out[:700] + "\n… (recortado) …\n" + out[-700:]
            summary.append(out)
        if result["error"]:
            summary.append("ERROR (todo revertido): " + str(result["error"]))
            if result["stderr"]:
                summary.append(result["stderr"].rstrip()[-800:])
        summary.append(f"(cambió el modelo: {result['changed']})")
        feedback = "Resultado de la ejecución:\n" + "\n".join(summary)
        self._append(feedback, "muted")
        provider, model = self._config()[:2]
        shot = None
        # Only shoot when the model CHANGED: after an error or an
        # inspect-only block the previous screenshot is still accurate
        # (slim_messages keeps the latest one in the convo).
        if (self._shots.isChecked() and result["changed"]
                and ai.supports_vision(provider, model)):
            shot = self._screenshot_b64()
        self._convo.append({"role": "user", "text": feedback,
                            **({"image_png_b64": shot} if shot else {})})
        self._next_turn()

    def _finish(self) -> None:
        self._busy = False
        self._send.setEnabled(True)

    def _screenshot_b64(self) -> str | None:
        try:
            # 640 px JPEG: the model reads a screenshot fine at that size
            # and it costs a quarter of the 768 px PNG it used to be —
            # the screenshot is the fattest thing in every turn.
            image = self._viewport.render_image(640, 427)
            buf = QBuffer()
            buf.open(QIODevice.WriteOnly)
            image.save(buf, "JPEG", 72)
            return base64.b64encode(bytes(buf.data())).decode()
        except Exception:  # noqa: BLE001 — vision is best-effort
            return None


def _esc(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))


#: The tests and older code name it by its dialog-era name.
AsistenteDialog = AsistentePanel


def setup(app) -> None:
    """The «AI» tab of the side tray (shared with the MCP bridge) and
    Extensions ▸ AI Assistant (Ctrl+Shift+A), which brings the tab
    forward — shown again if it was hidden — with the cursor in the input."""
    panel = AsistentePanel(app.viewport)
    dock = app.add_panel(tr("AI"), panel, panel="ai", stretch=1)
    app.window._ai_assistant = panel

    def summon() -> None:
        app.show_panel(dock)
        panel.focus_input()

    app.add_menu_action(tr("AI Assistant"), summon, "Ctrl+Shift+A", tr(
        "Open a chat with an AI that can read and change the model."))
