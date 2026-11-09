# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Picking the same library or bundled component again places a copy of it.

Each pick read the file again and added a new, independent piece: four of
the same 12 600-face cabinet were 50 400 faces in the model and its 2 s
read came back every time (Marco, 18-10). The copies share the definition,
as in SketchUp."""
from __future__ import annotations

import numpy as np
import pytest
from PySide6.QtGui import QVector3D
from PySide6.QtWidgets import QApplication


def V(x, y, z=0.0):
    return QVector3D(float(x), float(y), float(z))


def _window():
    QApplication.instance() or QApplication([])
    from views.main_window import MainWindow
    return MainWindow()


def _close(win):
    win._saved_version = win.viewport.scene.version
    win.close()


def _pick_and_place(win, pick, at):
    pick()
    tool = win.viewport.active_tool
    tool.place_at(win.viewport, at)
    return win.viewport.scene.groups[-1]


def _counting(win, monkeypatch, name):
    reads = []
    real = getattr(win, name)

    def counted(*args):
        reads.append(args)
        return real(*args)
    monkeypatch.setattr(win, name, counted)
    return reads


def _base_center(group):
    from core.group import placement_points
    import numpy as np
    pts = np.asarray(placement_points(group), dtype=float).reshape(-1, 3)
    lo, hi = pts.min(axis=0), pts.max(axis=0)
    return ((lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, lo[2])


def test_a_second_pick_is_a_copy_of_the_same_component(monkeypatch):
    win = _window()
    try:
        reads = _counting(win, monkeypatch, "_build_bundled_component")
        pick = lambda: win._on_insert_component("banco", "Banco")
        a = _pick_and_place(win, pick, V(0, 0))
        b = _pick_and_place(win, pick, V(5, 3))
        c = _pick_and_place(win, pick, V(-4, 8))
        assert len(reads) == 1                       # the file, read once
        assert a.is_component() and b.is_component() and c.is_component()
        assert a.mesh is b.mesh is c.mesh            # one definition
        # Each copy stands where it was placed, base on the ground.
        for g, (x, y) in ((a, (0, 0)), (b, (5, 3)), (c, (-4, 8))):
            cx, cy, cz = _base_center(g)
            assert abs(cx - x) < 1e-3 and abs(cy - y) < 1e-3
            assert abs(cz) < 1e-3
    finally:
        _close(win)


def test_a_copy_starts_fresh_from_how_the_other_was_left(monkeypatch):
    win = _window()
    try:
        pick = lambda: win._on_insert_component("banco", "Banco")
        a = _pick_and_place(win, pick, V(0, 0))
        a.material = {"color": [1.0, 0.0, 0.0]}
        a.layer = "Mobiliario"
        a.locked = True
        b = _pick_and_place(win, pick, V(5, 0))
        assert b.mesh is a.mesh
        assert b.material is None and b.layer is None and not b.locked
        assert b.uid != a.uid
    finally:
        _close(win)


def test_with_no_copy_left_the_file_is_read_again(monkeypatch):
    win = _window()
    try:
        reads = _counting(win, monkeypatch, "_build_bundled_component")
        pick = lambda: win._on_insert_component("banco", "Banco")
        a = _pick_and_place(win, pick, V(0, 0))
        win.viewport.history.undo()                 # the only copy, gone
        assert a not in win.viewport.scene.groups
        b = _pick_and_place(win, pick, V(1, 0))
        assert len(reads) == 2
        assert b.mesh is not a.mesh
        # A copy made unique is not the definition any more either.
        b.make_unique()
        c = _pick_and_place(win, pick, V(2, 0))
        assert len(reads) == 3 and c.mesh is not b.mesh
    finally:
        _close(win)


def test_editing_inside_one_copy_reaches_the_others(monkeypatch):
    win = _window()
    try:
        pick = lambda: win._on_insert_component("banco", "Banco")
        a = _pick_and_place(win, pick, V(0, 0))
        b = _pick_and_place(win, pick, V(5, 0))
        n = len(a.mesh.faces)
        scene = win.viewport.scene
        scene.begin_group_edit(a)
        face = scene.mesh.faces[0]
        scene.mesh.remove_face(face)
        scene.end_group_edit()
        assert b.mesh is a.mesh and len(b.mesh.faces) == n - 1
    finally:
        _close(win)


@pytest.mark.parametrize("multipart", [False, True], ids=["mesh", "parts"])
def test_library_models_are_shared_too_and_save_once(tmp_path, monkeypatch, multipart):
    from core import library
    from core.group import placement_points
    from core.resize import ResizeCommand
    from formats import igz
    from core.scene import Scene
    obj = tmp_path / "caja.obj"
    content = (
        "v 0 0 0\nv 1 0 0\nv 1 1 0\nv 0 1 0\n"
        "v 0 0 1\nv 1 0 1\nv 1 1 1\nv 0 1 1\n"
        "f 1 4 3 2\nf 5 6 7 8\nf 1 2 6 5\nf 2 3 7 6\nf 3 4 8 7\nf 4 1 5 8\n")
    if multipart:
        content = content.replace("f 1 4 3 2", "g base\nf 1 4 3 2")
        content = content.replace("f 2 3 7 6", "g sides\nf 2 3 7 6")
    obj.write_text(content)
    monkeypatch.setattr(library, "model_file", lambda entry: obj)
    monkeypatch.setattr(library, "model_matrix", lambda entry, path: None)
    win = _window()
    try:
        reads = _counting(win, monkeypatch, "_build_library_component")
        entry = {"id": "prueba-1", "nombre": "Caja", "obj": "caja.obj"}
        pick = lambda: win.insert_library_component(entry)
        copies = [_pick_and_place(win, pick, V(3 * i, 0)) for i in range(4)]
        assert len(reads) == 1
        assert all(g.mesh is copies[0].mesh for g in copies)
        assert all(g.source == obj.name for g in copies)
        assert bool(copies[0].children) == multipart

        def points():
            return [np.asarray(placement_points(g), dtype=float).reshape(-1, 3)
                    for g in copies]

        before = points()
        win.viewport.history.execute(ResizeCommand(win.viewport.scene, 2.0))
        after = points()
        # Library picks still share their definition and keep their real size;
        # only each placement's origin follows the model's resize.
        for g, old, new in zip(copies, before, after):
            np.testing.assert_allclose(np.ptp(new, axis=0), np.ptp(old, axis=0))
            origin = np.array(g.xform.map(V(0, 0)).toTuple())
            np.testing.assert_allclose(new - old, np.broadcast_to(origin / 2, old.shape))
        assert win.viewport.history.undo()
        for old, restored in zip(before, points()):
            np.testing.assert_allclose(restored, old)
        assert win.viewport.history.redo()
        for new, restored in zip(after, points()):
            np.testing.assert_allclose(restored, new)
        path = tmp_path / "m.igz"
        igz.save_scene(win.viewport.scene, path)
        back = Scene()
        igz.load_into(back, path)
        loaded = [g for g in back.groups if g.name == "Caja"]
        assert len(loaded) == 4
        assert len({id(g.mesh) for g in loaded}) == 1   # one definition
        assert all(g.source == obj.name for g in loaded)
    finally:
        _close(win)
