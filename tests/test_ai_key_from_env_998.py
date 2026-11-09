# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""#998: a user who keeps ``ANTHROPIC_API_KEY`` (and the other providers'
keys) in the environment does not have to paste it again. With the field
empty, a provider picked by name falls back to its usual variable, says so
under the field, and never copies it into the settings."""
from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

if QApplication.instance() is None:
    QApplication(sys.argv[:1])

from core import ai  # noqa: E402
from plugins.ai_assistant import AsistenteDialog, env_key_note  # noqa: E402


@pytest.fixture
def clean_env(monkeypatch):
    """No provider variable from the machine running the tests leaks in."""
    for names in ai.ENV_KEYS.values():
        for var in names:
            monkeypatch.delenv(var, raising=False)
    return monkeypatch


def test_env_key_reads_the_providers_usual_variable():
    env = {"ANTHROPIC_API_KEY": " sk-ant-env \n", "OPENAI_API_KEY": "   "}
    assert ai.env_key("anthropic", env) == ("ANTHROPIC_API_KEY", "sk-ant-env")
    assert ai.env_key("openai", env) is None            # blanks are unset
    assert ai.env_key("ollama", env) is None            # local: no key
    assert ai.env_key("gemini", {"GOOGLE_API_KEY": "AIzaG"}) \
        == ("GOOGLE_API_KEY", "AIzaG")
    assert ai.env_key("gemini", {"GOOGLE_API_KEY": "AIzaG",
                                 "GEMINI_API_KEY": "AIzaM"}) \
        == ("GEMINI_API_KEY", "AIzaM")                  # first one wins
    # Every hosted provider has its variable; the local one has none.
    assert set(ai.ENV_KEYS) == set(ai.PROVIDERS) - {"ollama"}


def test_note_under_the_field():
    env = {"ANTHROPIC_API_KEY": "sk-ant-env"}
    assert "ANTHROPIC_API_KEY" in env_key_note("anthropic", "", env)
    assert env_key_note("anthropic", "sk-ant-typed", env) == ""
    assert env_key_note("groq", "", env) == ""
    # On Auto an empty field is the local server: the note only points at
    # the provider to pick.
    note = env_key_note("auto", "", env)
    assert "ANTHROPIC_API_KEY" in note
    assert ai.PROVIDER_INFO["anthropic"][0] in note
    assert env_key_note("auto", "", {}) == ""


def test_placeholder_says_what_an_empty_field_means():
    """«empty = local AI» showed with Anthropic picked, where an empty
    field is the environment's key or no key at all."""
    from plugins.ai_assistant import key_placeholder
    local = key_placeholder("auto", {})
    assert "Ollama" in local
    assert key_placeholder("ollama", {}) == local
    env = {"ANTHROPIC_API_KEY": "sk-ant-env"}
    assert "ANTHROPIC_API_KEY" in key_placeholder("anthropic", env)
    named = key_placeholder("anthropic", {})
    assert "Ollama" not in named
    assert ai.PROVIDER_INFO["anthropic"][0] in named


def test_wrapped_key_link_keeps_its_second_line():
    """In the tray, the Korean key link wrapped to two lines and the second
    was cut in half: the dock lays the section out with a one-line hint.
    The label's hint now asks for every line it wraps to — a hint, not a
    minimum, so it never makes a short window grow."""
    from views.fold_section import WrapLabel
    label = WrapLabel("")
    assert label.wordWrap()
    label.show()                     # a hidden widget defers its resizes
    label.resize(120, 10)
    label.setText("Anthropic (Claude) — https://console.anthropic.com/"
                  "settings/keys 에서 키를 받으세요")
    QApplication.processEvents()
    need = label.heightForWidth(label.width())
    assert need > label.fontMetrics().lineSpacing() + 4       # wraps
    assert label.sizeHint().height() >= need
    assert label.minimumHeight() == 0
    label.resize(2000, label.height())       # wider: it asks for less
    QApplication.processEvents()
    assert label.sizeHint().height() < need
    label.close()


def _panel(monkeypatch, tmp_path):
    from views.main_window import MainWindow
    ini = str(tmp_path / "cfg.ini")
    monkeypatch.setattr(
        AsistenteDialog, "_settings",
        lambda self: QSettings(ini, QSettings.Format.IniFormat))
    win = MainWindow()
    return win, AsistenteDialog(win.viewport, parent=win), ini


def test_named_provider_uses_the_environment_key(clean_env, tmp_path):
    clean_env.setenv("ANTHROPIC_API_KEY", "sk-ant-from-env")
    win, dlg, ini = _panel(clean_env, tmp_path)
    try:
        dlg._provider.setCurrentIndex(dlg._provider.findData("anthropic"))
        dlg._key.setText("")
        # The note shares the key link's label: no row more in the tab.
        assert "ANTHROPIC_API_KEY" in dlg._key_link.text()
        assert "console.anthropic.com" in dlg._key_link.text()
        assert "ANTHROPIC_API_KEY" in dlg._key.placeholderText()
        provider, _model, key, _url = dlg._config()
        assert (provider, key) == ("anthropic", "sk-ant-from-env")

        # Test connection goes out with it instead of «needs an API key».
        seen = {}

        def fake_probe(provider, model, key, url):
            seen["call"] = (provider, key)
            return True, "OK"

        clean_env.setattr(ai, "probar_conexion", fake_probe)
        dlg._on_probar()
        app = QApplication.instance()
        for _ in range(2000):
            app.processEvents()
            if dlg._probar.isEnabled():
                break
        assert seen["call"] == ("anthropic", "sk-ant-from-env")
        assert "Connection OK" in dlg._chat.toPlainText()
        assert "needs an API key" not in dlg._chat.toPlainText()

        # Never copied into the settings.
        st = QSettings(ini, QSettings.Format.IniFormat)
        assert not st.value("ia/api_key")
        assert st.value("ia/claves/anthropic") is None

        # A typed key wins over the environment and drops the note.
        dlg._key.setText("sk-ant-typed")
        assert "ANTHROPIC_API_KEY" not in dlg._key_link.text()
        assert dlg._config()[2] == "sk-ant-typed"
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


def test_auto_with_an_empty_field_stays_local(clean_env, tmp_path):
    """An ``OPENAI_API_KEY`` exported for another program must not send
    the chat of someone running Ollama to the cloud."""
    clean_env.setenv("OPENAI_API_KEY", "sk-env")
    win, dlg, _ini = _panel(clean_env, tmp_path)
    try:
        dlg._provider.setCurrentIndex(dlg._provider.findData("auto"))
        dlg._key.setText("")
        provider, _model, key, _url = dlg._config()
        assert (provider, key) == ("ollama", "")
        assert "Ollama" in dlg._key.placeholderText()
        assert "OPENAI_API_KEY" in dlg._key_link.text()
        assert "OpenAI" in dlg._key_link.text()
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


def test_missing_key_hint_names_the_variable(clean_env):
    hint = AsistenteDialog._missing_key_hint(None, "anthropic", "")
    assert "ANTHROPIC_API_KEY" in hint
    assert "GEMINI_API_KEY" in AsistenteDialog._missing_key_hint(
        None, "gemini", "")


def test_preferences_shows_the_same_note(clean_env, tmp_path):
    import views.preferences_dialog as prefs_mod
    path = tmp_path / "prefs.ini"
    clean_env.setattr(prefs_mod, "QSettings",
                      lambda: QSettings(str(path), QSettings.IniFormat))
    clean_env.setenv("GROQ_API_KEY", "gsk_env")

    class _Win(QWidget):
        def __init__(self):
            super().__init__()

            class _VP:
                edit_rest_mode = "fade"

                def set_edit_rest_mode(self, mode):
                    self.edit_rest_mode = mode

            self.viewport = _VP()
            self._rest_actions = {}

    win = _Win()
    dlg = prefs_mod.PreferencesDialog(win)
    dlg._provider.setCurrentIndex(dlg._provider.findData("groq"))
    dlg._api_key.setText("")
    assert "GROQ_API_KEY" in dlg._key_env.text()
    assert not dlg._key_env.isHidden()
    dlg._api_key.setText("gsk_typed")
    assert dlg._key_env.isHidden()
