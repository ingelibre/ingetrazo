# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A key held twice works for nobody.

#313 (@RaphaelNunes10): on KDE and GNOME, Redo's factory keys came out as
«Ctrl+Shift+Z; Ctrl+Shift+Z» — the platform's Redo key plus the same key
spelled out — and Ctrl+Shift+Z did nothing. #323 (@tomlai-git): a
shortcuts file written from another program's keys gave Z to Zoom
Selection while the Zoom tool kept it, and neither responded."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from collections import defaultdict  # noqa: E402

from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtGui import QKeySequence  # noqa: E402

from core.i18n import tr  # noqa: E402
from tests.test_shortcuts_transfer import _keys, ventana  # noqa: E402,F401
from views import shortcuts as sc  # noqa: E402


def test_redo_answers_both_keys(ventana):  # noqa: F811
    assert _keys(ventana._redo_action) == ["Ctrl+Y", "Ctrl+Shift+Z"]


def test_no_factory_key_is_held_twice(ventana):  # noqa: F811
    owners = defaultdict(list)
    for act in sc.collect_actions(ventana):
        keys = _keys(act)
        assert len(keys) == len(set(keys)), (sc.action_key(act), keys)
        for k in keys:
            owners[k].append(sc.action_key(act))
    shared = {k: v for k, v in owners.items() if len(v) > 1}
    assert not shared, shared


def _zoom_selection(win):
    return next(a for a in sc.collect_actions(win)
                if sc._plain(a.text()) == sc._plain(tr("Zoom Selection")))


def test_a_file_giving_one_key_to_two_commands_leaves_it_working(
        ventana):  # noqa: F811
    zoom = ventana._nav_actions["zoom"]
    zsel = _zoom_selection(ventana)
    data = {"format": sc.EXPORT_FORMAT, "shortcuts": {
        sc.action_key(zoom): "Z",               # what the file kept
        sc.action_key(zsel): "Z",               # and what it added
    }}
    applied, skipped, clashes = sc.import_shortcuts(ventana, data)
    owners = [a for a in sc.collect_actions(ventana) if "Z" in _keys(a)]
    assert owners == [zoom], [sc.action_key(a) for a in owners]
    assert [(k, kept, dropped) for k, kept, dropped in clashes] == [
        ("Z", zoom, zsel)]


def test_a_key_saved_twice_on_one_command_is_loaded_once(
        ventana):  # noqa: F811
    redo = ventana._redo_action
    QSettings().setValue(f"shortcuts/{sc._store_key(sc.action_key(redo))}",
                         "Ctrl+Shift+Z; Ctrl+Shift+Z")
    sc.apply_user_shortcuts(ventana)
    assert _keys(redo) == ["Ctrl+Shift+Z"]
