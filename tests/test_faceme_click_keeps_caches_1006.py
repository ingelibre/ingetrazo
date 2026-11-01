# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A click does not rebuild the face-me figures (#1006, @blenderarc).

Selecting anything in the villa took ~5 s: every selection bumps the
scene's version, and the face-me figures — vector-art people from an
imported file, faces with thousands of holes — were triangulated again
on the next frame, and their extents walked again for every pick. Both
now wait for a change of the model itself."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QMatrix4x4, QVector3D  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication([])

from core.group import Group  # noqa: E402
from core.mesh import Mesh  # noqa: E402


def V(x, y, z=0.0):
    return QVector3D(float(x), float(y), float(z))


def _figure(vp, placed=False):
    g = Group(Mesh(), name="Susan")
    g.billboard = "mesh"
    f = g.mesh.add_face([V(1, 2, 0), V(2, 2, 0), V(2, 2, 1.7), V(1, 2, 1.7)])
    f.attrs["color"] = (0.5, 0.5, 0.5)
    if placed:
        g.xform = QMatrix4x4()
        g.xform.translate(3, 0, 0)
    vp.scene.groups.append(g)
    vp.scene.version += 1
    return g


def _counting(monkeypatch, vp):
    calls = []
    tris = vp._tris_of

    def counted(face):
        calls.append(face)
        return tris(face)
    monkeypatch.setattr(vp, "_tris_of", counted)
    return calls


def _window():
    from views.main_window import MainWindow
    return MainWindow()


def test_a_selection_keeps_the_figure_triangulated(monkeypatch):
    win = _window()
    vp = win.viewport
    try:
        g = _figure(vp)
        calls = _counting(monkeypatch, vp)
        first = vp._faceme_base(g)
        assert first is not None and len(calls) == 1
        vp.scene.select([g])               # a click: view-only bump
        vp.scene.clear_selection()
        assert vp._faceme_base(g) is first
        assert len(calls) == 1, "a click triangulated the figure again"
        # an edit of the figure does rebuild it
        f = g.mesh.faces[0]
        f.attrs = dict(f.attrs, color=(0.1, 0.1, 0.1))
        vp.scene.version += 1
        assert vp._faceme_base(g) is not first
        assert len(calls) == 2
    finally:
        win._saved_version = vp.scene.version
        win.close()


def test_a_selection_keeps_the_figure_extent(monkeypatch):
    win = _window()
    vp = win.viewport
    try:
        for placed in (False, True):
            g = _figure(vp, placed)
            walks = []
            mesh_of = vp._billboard_mesh
            monkeypatch.setattr(vp, "_billboard_mesh",
                                lambda grp: walks.append(grp) or mesh_of(grp))
            quad = vp._billboard_quad(g)
            assert quad is not None and len(walks) == 1
            vp.scene.select([g])
            vp.scene.clear_selection()
            again = vp._billboard_quad(g)
            assert len(walks) == 1, "a click walked the figure again"
            assert [(c - d).length() for c, d in zip(quad[0], again[0])] \
                == [0.0] * 4
            # moved: the extent follows
            if placed:
                x0 = vp._billboard_extent(g)[0].x()
                g.xform.translate(1, 0, 0)
                vp._billboard_quad(g)
                assert len(walks) == 2
                assert abs(vp._billboard_extent(g)[0].x() - x0 - 1.0) < 1e-6
            monkeypatch.undo()
    finally:
        win._saved_version = vp.scene.version
        win.close()


def test_a_box_over_a_figure_builds_the_camera_once(monkeypatch):
    """The box walks a figure's vertices one by one (it cannot use the
    chunks of a face-me): each one rebuilt the camera matrices — 1.6 s of
    a 3 s box on the villa. Same pixels, same pick."""
    import math
    from tools.select import SelectTool
    win = _window()
    vp = win.viewport
    try:
        vp.resize(1000, 600)
        vp.camera.set_aspect(1000, 600)
        vp.camera.set_view("front")
        vp.camera.target = V(1.5, 2, 0.8)
        vp.camera.distance = 8
        g = Group(Mesh(), name="Susan")
        g.billboard = "mesh"
        ring = [V(1.5 + 0.5 * math.cos(2 * math.pi * k / 200), 2,
                  0.85 + 0.85 * math.sin(2 * math.pi * k / 200))
                for k in range(200)]
        g.mesh.add_face(ring)
        vp.scene.groups.append(g)
        vp.scene.version += 1
        builds = []
        view = vp.camera.view_matrix
        monkeypatch.setattr(vp.camera, "view_matrix",
                            lambda: builds.append(1) or view())
        SelectTool().on_box_select(vp, (0, 0, 1000, 600), crossing=False)
        assert g in vp.scene.selection
        assert len(builds) < 20, f"{len(builds)} camera builds for one box"
    finally:
        win._saved_version = vp.scene.version
        win.close()


def test_big_figure_faces_go_to_the_native_earcut_with_the_same_triangles():
    """A figure's face with many holes is triangulated by the engine's
    earcut (the villa's 18 took ~40 s in Python, 0.7 s natively) — the
    same triangles, corner for corner. Without the Rust engine nothing is
    seeded and the Python earcut does it as before."""
    import core._native as _native
    win = _window()
    vp = win.viewport
    try:
        outer = [V(0, 2, 0), V(4, 2, 0), V(4, 2, 4), V(0, 2, 4)]
        holes = []
        for i in range(4):
            for j in range(4):
                x, z = 0.3 + i * 0.95, 0.3 + j * 0.95
                holes.append([V(x, 2, z), V(x, 2, z + 0.5),
                              V(x + 0.5, 2, z + 0.5), V(x + 0.5, 2, z)])
        g = Group(Mesh(), name="Susan")
        g.billboard = "mesh"
        f = g.mesh.add_face(outer, holes)
        f.attrs["color"] = (0.2, 0.2, 0.2)
        vp.scene.groups.append(g)
        vp.scene.version += 1
        vp._tri_memo = None
        vp._seed_tris_native([f])
        seeded = (vp._tri_memo or (None, {}))[1].get(id(f))
        if _native.native is None or _native.qt_hypot() is None:
            assert seeded is None
            return
        assert seeded is not None and seeded[0] is f
        python = f.triangulate(vp._normal_of(f))

        def corners(tris):
            return [tuple((p.x(), p.y(), p.z()) for p in t) for t in tris]
        assert corners(seeded[1]) == corners(python)
        assert vp._tris_of(f) is seeded[1]
    finally:
        win._saved_version = vp.scene.version
        win.close()
