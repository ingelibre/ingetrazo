# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""«Vista previa de impresión» no hacía nada — Fase 10 (Rafael, 30:20).

    «No sé qué hace este icono de aquí que dice "Mira la lámina que se
    imprime". Pero yo pulso y no veo nada… creo que es un previo de
    impresión, pero no hace nada. Igual no lo tenéis implementado.»

It was implemented, and it works — everywhere except the package he runs.
The Flatpak manifest trims PySide6 down to the modules the program uses,
and **QtPrintSupport was on the trim list**. The button's import lives
inside the slot, so in that build it raised where nobody could see it and
the click did nothing at all, while PDF export — QPdfWriter, which is in
QtGui — kept working perfectly for him. Two nets, then: the module stays
in the package, and if it ever goes missing again the program says so.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# The repository root: ``app/`` on Marco's disk, ``ingetrazo/`` on the CI
# runner — never assume the folder above it holds an ``app`` (it does not
# there, and the v0.4.7 gate fell on exactly that).
MANIFEST = (Path(__file__).resolve().parents[1]
            / "packaging/flatpak/com.ingetrazo.IngeTrazo.yml")


def _trimmed_modules() -> set[str]:
    """The Qt module stems the Flatpak recipe deletes from PySide6."""
    text = MANIFEST.read_text(encoding="utf-8")
    m = re.search(r"for stem in ([^;]+); do", text)
    assert m, "the Flatpak recipe lost its PySide6 trim loop"
    return set(m.group(1).split())


def test_the_flatpak_keeps_the_printing_module():
    """The one that broke it. QtPdf may stay trimmed — that is the PDF
    VIEWER, which the program does not use; writing PDFs is QtGui."""
    trimmed = _trimmed_modules()
    assert "PrintSupport" not in trimmed
    assert "Pdf" in trimmed                       # still not needed
    assert "WebEngine" in trimmed                 # the loop still trims


def test_the_program_can_say_whether_it_has_printing():
    from views.composer import ComposerWindow
    assert ComposerWindow.print_support() is not None   # here it does


def test_without_the_module_the_button_explains_itself(monkeypatch):
    """What it must never do again is nothing at all."""
    from PySide6.QtWidgets import QMessageBox
    from views.composer import ComposerWindow
    from views.main_window import MainWindow
    monkeypatch.setattr(ComposerWindow, "render_frame", lambda self, f: None)
    win = MainWindow()
    comp = None
    try:
        comp = ComposerWindow(win)
        said = []
        monkeypatch.setattr(QMessageBox, "information",
                            staticmethod(lambda *a, **k: said.append(a[2])))
        opened = []
        monkeypatch.setattr(ComposerWindow, "_printer_for_sheet",
                            lambda self: opened.append(1))

        monkeypatch.setattr(ComposerWindow, "print_support",
                            staticmethod(lambda: None))
        comp._on_print_preview()
        assert said and "Export PDF" in said[0]     # and where to go instead
        assert not opened                           # no half-open dialog
    finally:
        if comp is not None:
            comp.close()
        win._saved_version = win.viewport.scene.version
        win.close()
