# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Replay Cocoa's accessibility callbacks in a disposable native process.

Offscreen and QAccessible events alone do not exercise the AX attribute
queries in the macOS crash report. Return to app.exec() between mutations
so Cocoa also drains the autorelease pools that release cached wrappers.
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import textwrap

import pytest


ROOT = Path(__file__).resolve().parents[1]

_NATIVE_REPLAY = textwrap.dedent("""\
    import ctypes
    import sys
    import traceback
    from types import SimpleNamespace

    from PySide6.QtCore import QStandardPaths, QTimer
    from PySide6.QtGui import QAccessible, QAccessibleTableModelChangeEvent
    from PySide6.QtWidgets import (QAbstractItemView, QApplication,
                                  QTableWidget, QTableWidgetItem,
                                  QTreeWidgetItem)
    from core.macos_accessibility import install_cocoa_accessibility_fix
    from views import outliner

    scenario = sys.argv[1]
    app = QApplication([])
    assert app.platformName() == "cocoa"
    app.setQuitOnLastWindowClosed(False)
    QStandardPaths.setTestModeEnabled(True)
    assert install_cocoa_accessibility_fix(app) is True
    QAccessible.setActive(True)

    # These are the same Objective-C attribute entry points AppKit invokes
    # for AX clients. No Accessibility permission or external process is
    # needed to call the native elements owned by this test's own window.
    objc = ctypes.CDLL("/usr/lib/libobjc.A.dylib")
    objc.objc_getClass.argtypes = [ctypes.c_char_p]
    objc.objc_getClass.restype = ctypes.c_void_p
    objc.sel_registerName.argtypes = [ctypes.c_char_p]
    objc.sel_registerName.restype = ctypes.c_void_p
    send = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p,
                            ctypes.c_void_p)(("objc_msgSend", objc))
    send_argument = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p,
                                     ctypes.c_void_p, ctypes.c_size_t)(
                                         ("objc_msgSend", objc))
    native_class = objc.objc_getClass(b"QMacAccessibilityElement")
    assert native_class

    def message(receiver, selector, *arguments):
        selector = objc.sel_registerName(selector.encode("ascii"))
        return (send_argument if arguments else send)(
            receiver, selector, *arguments)

    def count(array):
        return message(array, "count") or 0

    def native_element():
        iface = QAccessible.queryAccessibleInterface(view)
        return message(native_class, "elementWithId:",
                       QAccessible.uniqueId(iface))

    def inspect_native(element, depth=0):
        assert element
        # The reported libqcocoa+554036 callback is selectedChildren.
        message(element, "accessibilitySelectedChildren")
        message(element, "accessibilityTitle")
        if depth == 2:
            return
        for attribute in ("accessibilityChildren", "accessibilityRows",
                          "accessibilityColumns"):
            array = message(element, attribute)
            for index in range(min(count(array), 12)):
                inspect_native(message(array, "objectAtIndex:", index), depth + 1)

    def later(callback, delay=10):
        def guarded():
            try:
                callback()
            except Exception:
                traceback.print_exc()
                app.exit(1)
        QTimer.singleShot(delay, guarded)

    if scenario == "table":
        view = QTableWidget()
    else:
        view = getattr(outliner, scenario)(
            SimpleNamespace(current_sheet=lambda: None))
    view.setColumnCount(8)
    view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
    view.resize(1000, 500)
    view.show()
    roots = []
    completed = []
    generations = 12

    def rebuild(generation):
        view.clear()
        roots.clear()
        if scenario == "table":
            view.setRowCount(6)
            for row in range(6):
                for column in range(8):
                    view.setItem(row, column, QTableWidgetItem(
                        f"Cell {generation}-{row}-{column}"))
            view.setCurrentCell(0, 0)
            view.item(1, 1).setSelected(True)
        else:
            for row in range(6):
                item = QTreeWidgetItem([f"Group {generation}-{row}"] * 8)
                for child in range(4):
                    item.addChild(QTreeWidgetItem([f"Part {child}"] * 8))
                view.addTopLevelItem(item)
                roots.append(item)
            view.expandAll()
            view.setCurrentItem(roots[0].child(0))
            roots[0].setSelected(True)
        later(lambda: inspect_generation(generation))

    def inspect_generation(generation):
        iface = QAccessible.queryAccessibleInterface(view)
        assert iface.isValid()
        native = native_element()
        assert count(message(native, "accessibilityColumns")) == 8
        assert count(message(native, "accessibilitySelectedChildren")) > 0
        retained_cells = []
        if scenario == "table":
            # These rows remain in the model when the final row is removed.
            names = {f"Cell {generation}-{row}-{column}"
                     for row in range(2) for column in range(8)}
            for index in range(iface.childCount()):
                cell = iface.child(index)
                name = cell.text(QAccessible.Text.Name)
                if name in names:
                    retained_cells.append((QAccessible.uniqueId(cell), name))
            assert {name for _, name in retained_cells} == names
        inspect_native(native)
        if scenario == "table":
            # Native arrays expire while the view still owns real cells.
            # The earlier parent-placeholder-only fix deleted their IDs.
            view.setRowCount(5)
            later(lambda: inspect_retained_cells(generation, retained_cells))
        else:
            view.collapseAll()
            view.expandAll()
            later(lambda: reset_generation(generation))

    def inspect_retained_cells(generation, cells):
        for unique_id, name in cells:
            cell = QAccessible.accessibleInterface(unique_id)
            assert cell is not None, f"view-owned cell {unique_id} was deleted by Cocoa"
            assert cell.isValid()
            assert cell.text(QAccessible.Text.Name) == name
        assert view.currentItem().text() == f"Cell {generation}-0-0"
        assert count(message(native_element(), "accessibilitySelectedChildren")) == 2
        inspect_native(native_element())
        later(lambda: reset_generation(generation))

    def reset_generation(generation):
        event = QAccessibleTableModelChangeEvent(
            view, QAccessibleTableModelChangeEvent.ModelChangeType.ModelReset)
        QAccessible.updateAccessibility(event)
        completed.append(generation)
        later(clean_up if generation + 1 == generations
              else lambda: rebuild(generation + 1))

    def clean_up():
        view.clear()
        roots.clear()
        view.close()
        view.deleteLater()
        # Check success after Cocoa has also released the final arrays.
        later(finish, 50)

    def finish():
        assert completed == list(range(generations)), completed
        assert QAccessible.isActive()
        print("native accessibility replay completed: " + scenario, flush=True)
        app.exit(0)

    def start():
        message(int(view.winId()), "accessibilityFocusedUIElement")
        assert QAccessible.isActive()
        rebuild(0)

    def timed_out():
        print("native accessibility replay timed out", file=sys.stderr, flush=True)
        app.exit(2)

    later(start)
    QTimer.singleShot(30000, timed_out)
    sys.exit(app.exec())
""")


@pytest.mark.skipif(sys.platform != "darwin", reason="requires native Cocoa accessibility")
@pytest.mark.parametrize("scenario", ["_Tree", "_SheetsTree", "table"])
def test_native_accessibility_survives_view_mutations(scenario):
    env = dict(os.environ, QT_QPA_PLATFORM="cocoa")
    result = subprocess.run(
        [sys.executable, "-c", _NATIVE_REPLAY, scenario], cwd=ROOT, env=env,
        capture_output=True, text=True, timeout=45,
    )
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert f"native accessibility replay completed: {scenario}" in result.stdout, output
    assert "on invalid object" not in result.stderr, output
