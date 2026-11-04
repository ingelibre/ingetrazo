# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The style window must not fall back to English in localized sessions."""
from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from core import i18n

ROOT = Path(__file__).resolve().parents[1]


def _style_strings():
    tree = ast.parse((ROOT / "views" / "tray.py").read_text(encoding="utf-8"))
    panel = next(node for node in tree.body
                 if isinstance(node, ast.ClassDef) and node.name == "StylesPanel")
    strings = {node.args[0].value for node in ast.walk(panel)
               if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
               and node.func.id == "tr" and node.args
               and isinstance(node.args[0], ast.Constant)}
    for node in ast.walk(panel):
        if not isinstance(node, ast.Tuple):
            continue
        try:
            values = ast.literal_eval(node)
        except (ValueError, TypeError):
            continue
        if len(values) == 3 and isinstance(values[1], str) and values[1].startswith(("cap_", "endpoint_")):
            strings.add(values[2])
    for name, column in (("_MODES", 1), ("_CATEGORIES", 0)):
        assignment = next(node for node in panel.body if isinstance(node, ast.Assign)
                          and any(isinstance(t, ast.Name) and t.id == name for t in node.targets))
        strings.update(row[column] for row in ast.literal_eval(assignment.value))
    strings.update(("Styles", "Built-in styles", "My styles", "All same", "By material", "By axis"))
    from core.style import BUILTIN_STYLES
    strings.update(style.name for style in BUILTIN_STYLES)
    watermark_tree = ast.parse((ROOT / "views" / "watermarks_panel.py").read_text(encoding="utf-8"))
    strings.update(node.args[0].value for node in ast.walk(watermark_tree)
                   if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                   and node.func.id == "tr" and node.args
                   and isinstance(node.args[0], ast.Constant))
    return strings


@pytest.mark.parametrize("language", sorted(i18n.LANGUAGE_NAMES))
def test_every_style_string_is_present_in_the_selected_language(language):
    old = i18n.current_language()
    try:
        i18n.set_language(language)
        strings = _style_strings()
        if language == "en":
            assert all(i18n.tr(text) == text for text in strings)
        else:
            catalog = json.loads((ROOT / "i18n" / (language + ".json")).read_text(encoding="utf-8"))
            assert not (strings - catalog.keys())
            assert all(isinstance(catalog[text], str) and catalog[text].strip() for text in strings)
            assert all(i18n.tr(text) == catalog[text] for text in strings)
    finally:
        i18n.set_language(old)


def test_french_editor_uses_translated_labels_and_shape_descriptions(tmp_path, monkeypatch):
    from PySide6.QtCore import QSettings
    from core import style as library
    from core.scene import Scene
    from views.tray import StylesPanel

    monkeypatch.setattr(library, "_settings", lambda: QSettings(
        str(tmp_path / "styles.ini"), QSettings.IniFormat))

    class Window:
        class viewport:
            scene = Scene()

    old = i18n.current_language()
    panel = None
    try:
        i18n.set_language("fr")
        panel = StylesPanel(Window())
        assert panel._depth_cue.text() == "Profondeur"
        assert panel._endpoints.text() == "Extrémités"
        assert panel._extensions.text() == "Prolongements"
        assert panel._dashes.text() == "Ligne du calque"
        assert panel._edge_color_mode.itemText(0) == "Toutes identiques"
        assert panel._profile_caps.button(1).toolTip() == "Ronde, à ras"
        assert panel._endpoint_types.button(1).toolTip() == "Point rond"
        assert "Calques" in panel._dashes.toolTip()
    finally:
        if panel is not None:
            panel.close()
        i18n.set_language(old)
