# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Custom 1:N scales typed in the composer live in the document."""
from __future__ import annotations


def _items(combo) -> list:
    return [combo.itemText(i) for i in range(combo.count())]


def test_custom_scale_joins_the_document_and_its_frames(tmp_path):
    from core.scene import Scene
    from formats import igz as igz_format
    from views.composer import ComposerWindow
    from views.main_window import MainWindow

    win = MainWindow()
    comp = None
    try:
        scene = win.viewport.scene
        comp = ComposerWindow(win)
        assert "1:75" not in _items(comp.scale_combo)

        comp.scale_combo.setCurrentText("1:75")
        comp._on_scale_committed()                   # Enter in the box
        assert scene.custom_scales == [75.0]
        assert "1:75" in _items(comp.scale_combo)
        assert comp.scale_combo.currentText() == "1:75"
        comp._on_scale_committed()                   # no duplicates
        comp.scale_combo.setCurrentText("1:100")
        comp._on_scale_committed()                   # presets are not stored
        assert scene.custom_scales == [75.0]

        # It travels with the document…
        path = tmp_path / "escalas.igz"
        igz_format.save_scene(scene, path)
        fresh = Scene()
        igz_format.load_into(fresh, path)
        assert fresh.custom_scales == [75.0]
        # …and a composer over that document offers it on any frame.
        scene.custom_scales = list(fresh.custom_scales)
        comp._reload_scale_options()
        assert "1:75" in _items(comp.scale_combo)
        # A new document starts clean.
        scene.clear()
        assert scene.custom_scales == []
    finally:
        if comp is not None:
            comp.close()
        win._saved_version = win.viewport.scene.version
        win.close()
