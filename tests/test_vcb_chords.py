# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Issue #185 (Alejandro Limón): with a value being typed, Alt+1 (a view
shortcut) was swallowed by the value box and appended a «1»; each retry
added another, a 35-digit number reached the Tape and Scale, overflowed
the geometry's float32 coordinates to inf, and NaN followed."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import QEvent, Qt  # noqa: E402
from PySide6.QtGui import QKeyEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication([])


@pytest.fixture
def vp():
    from views.main_window import MainWindow
    w = MainWindow()
    w._activate_tool("line")
    yield w.viewport
    w._saved_version = w.viewport.scene.version   # no "save?" modal
    w.close()


def _override(vp, key, text, mods=Qt.NoModifier):
    ev = QKeyEvent(QEvent.ShortcutOverride, key, mods, text)
    vp.event(ev)
    return ev.isAccepted()


def test_a_digit_continues_the_value_but_alt_digit_stays_a_shortcut(vp):
    vp._set_value_buffer("12")
    assert _override(vp, Qt.Key_1, "1") is True            # typing
    assert _override(vp, Qt.Key_1, "1", Qt.AltModifier) is False
    assert _override(vp, Qt.Key_2, "2", Qt.ControlModifier) is False
    assert _override(vp, Qt.Key_F, "f", Qt.AltModifier) is False


def test_alt_digit_never_lands_in_the_buffer(vp):
    vp._set_value_buffer("12")
    vp.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_1, Qt.AltModifier, "1"))
    assert vp._value_buffer == "12"
    vp.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_3, Qt.NoModifier, "3"))
    assert vp._value_buffer == "123"


def test_altgr_still_types(vp):
    # AltGr arrives as Ctrl+Alt on Windows and types characters.
    vp._set_value_buffer("12")
    both = Qt.ControlModifier | Qt.AltModifier
    assert _override(vp, Qt.Key_1, "1", both) is True


def test_an_absurd_number_is_refused(vp):
    from views.viewport import _parse_number
    assert _parse_number("111111111111111111111112111") is None   # ~1e26
    assert _parse_number("8900000") == 8900000.0         # a UTM northing
    # Typed and committed, it never reaches the tool.
    vp._set_value_buffer("111111111111111111111112111")
    assert vp._parse_value_buffer(vp._value_buffer) is None


def test_a_document_with_a_nan_corner_opens_without_it(tmp_path):
    """The other half of #185: a file saved with one NaN corner and a NaN
    guide could not be opened at all. Now the rest opens."""
    import json
    import math
    import zipfile
    from pathlib import Path
    from core.scene import Scene
    from formats import igz
    good = Scene()
    V3 = __import__("PySide6.QtGui", fromlist=["QVector3D"]).QVector3D
    good.mesh.add_face([V3(0, 0, 0), V3(1, 0, 0), V3(1, 1, 0), V3(0, 1, 0)])
    good.mesh.add_face([V3(3, 0, 0), V3(4, 0, 0), V3(4, 1, 0)])
    path = tmp_path / "reja.igz"
    igz.save_scene(good, path)
    # Damage it the way it happened: one corner and one guide become NaN.
    # (A document without images is plain JSON; with them, a zip.)
    raw = path.read_bytes()
    packed = raw[:2] == b"PK"
    if packed:
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
            blobs = {n: z.read(n) for n in names}
        doc_name = next(n for n in names if n.endswith(".json"))
        raw = blobs[doc_name]
    data = json.loads(raw)
    scene_block = data.get("scene", data)
    scene_block["faces"][1]["vertices"][0][0] = float("nan")
    scene_block.setdefault("guides", []).append(
        {"point": [float("nan")] * 3, "direction": None, "origin": None})
    raw = json.dumps(data).encode()
    if packed:
        blobs[doc_name] = raw
        with zipfile.ZipFile(path, "w") as z:
            for n in names:
                z.writestr(n, blobs[n])
    else:
        path.write_bytes(raw)
    s = Scene()
    igz.load_into(s, Path(path))
    assert len(s.mesh.faces) == 1                      # the sound face
    assert all(math.isfinite(c) for v in s.mesh.vertices
               for c in (v.position.x(), v.position.y(), v.position.z()))
    assert not s.guides
    assert s.load_repairs >= 2
