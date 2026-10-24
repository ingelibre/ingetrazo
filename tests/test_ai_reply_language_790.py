# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The assistant answers in the user's language (#790).

The system prompt said «Conversas en español», so an English user got
Spanish replies even after asking for English. It now tells the model to
reply in the language the user writes in, falling back to the
interface's."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication([])


def test_the_prompt_no_longer_pins_spanish():
    from plugins.ai_assistant import system_prompt
    text = system_prompt("en")
    assert "Conversas en español" not in text
    assert "idioma en que escribe el usuario" in text
    assert "English" in text


def test_the_fallback_follows_the_interface_language():
    from plugins.ai_assistant import system_prompt
    assert "Deutsch" in system_prompt("de")
    assert "español" in system_prompt("es")
    assert "English" in system_prompt("xx")       # unknown → English
