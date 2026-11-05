# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The persistent style editor is translated in every shipped language."""
from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from core import i18n
from core.style import BUILTIN_STYLES

ROOT = Path(__file__).resolve().parents[1]


def _editor_strings():
    tree = ast.parse((ROOT / "views/tray.py").read_text(encoding="utf-8"))
    panel = next(node for node in tree.body
                 if isinstance(node, ast.ClassDef) and node.name == "StylesPanel")
    strings = {node.args[0].value for node in ast.walk(panel)
               if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
               and node.func.id == "tr" and node.args
               and isinstance(node.args[0], ast.Constant)}
    for name, column in (("_MODES", 1), ("_CATEGORIES", 0)):
        assignment = next(node for node in panel.body if isinstance(node, ast.Assign)
                          and any(isinstance(t, ast.Name) and t.id == name for t in node.targets))
        strings.update(row[column] for row in ast.literal_eval(assignment.value))
    strings.update(style.name for style in BUILTIN_STYLES)
    return strings


@pytest.mark.parametrize("language", sorted(i18n.LANGUAGE_NAMES))
def test_styles_window_has_translations_in_every_shipped_language(language):
    original = i18n.current_language()
    try:
        i18n.set_language(language)
        strings = _editor_strings()
        if language == "en":
            assert all(i18n.tr(text) == text for text in strings)
        else:
            catalog = json.loads((ROOT / "i18n" / f"{language}.json").read_text(encoding="utf-8"))
            assert not (strings - catalog.keys())
            assert all(isinstance(catalog[text], str) and catalog[text].strip() for text in strings)
            assert all(i18n.tr(text) == catalog[text] for text in strings)
    finally:
        i18n.set_language(original)
