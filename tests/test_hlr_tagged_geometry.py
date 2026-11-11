# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The line drawing by layer is made from the viewport's arrays, not from
a walk of the model.

Exporting the view of a 1 035-object plaza as SVG spent 12.8 of its 16 s
of hidden lines walking 85 000 faces in Python to learn their layers —
``collect_geometry(layers=True)`` — while the viewport already held every
triangle and edge as arrays, layers at hand in the pick index and the
chunks. ``Viewport.hlr_geometry(tags=True)`` hands those over with their
layers, and ``hlr_drawing`` takes them instead of walking: the same lines,
the same layers, on built meshes, on a lazy placement and on loose
geometry, with an edge's own layer inside an object kept."""
from __future__ import annotations

import os

import numpy as np
import pytest
from PySide6.QtGui import QVector3D as V

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from core import _native                                 # noqa: E402
from core import mesh as M                               # noqa: E402
from core.group import Group                             # noqa: E402
from core.hlr import hlr_drawing                         # noqa: E402
from core.layers import Layer                            # noqa: E402
from core.scene import Scene                             # noqa: E402
from formats import igz                                  # noqa: E402


def _app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _box(mesh, x0, y0, z0, s=1.0, layer=None):
    x1, y1, z1 = x0 + s, y0 + s, z0 + s
    faces = []
    for loop in (
            [(x0, y0, z0), (x0, y1, z0), (x1, y1, z0), (x1, y0, z0)],
            [(x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)],
            [(x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1)],
            [(x0, y1, z0), (x0, y1, z1), (x1, y1, z1), (x1, y1, z0)],
            [(x0, y0, z0), (x0, y0, z1), (x0, y1, z1), (x0, y1, z0)],
            [(x1, y0, z0), (x1, y1, z0), (x1, y1, z1), (x1, y0, z1)]):
        f = mesh.add_face([V(*p) for p in loop])
        if layer:
            f.attrs["layer"] = layer
        faces.append(f)
    return faces


def _scene(tmp_path, lazy: bool):
    """Layers everywhere a layer can be: a group on «Muros» with a face of
    its own on «Losa» and an edge of its own on «Barandas»; a second group
    with a soft edge between two faces; a loose face on «Mobiliario» and a
    loose edge on «Ejes»; a hidden edge. ``lazy``: saved and opened again
    so the groups come back as lazy placements."""
    scene = Scene()
    scene.layers[:] = [Layer("Layer0"), Layer("Muros"), Layer("Losa"),
                       Layer("Barandas"), Layer("Mobiliario"),
                       Layer("Ejes"), Layer("Techos")]
    m = M.Mesh()
    faces = _box(m, 0, 0, 0, 2.0)
    faces[1].attrs["layer"] = "Losa"                 # the top, its own
    top = faces[1]
    on_top = {id(v) for v in top.loop}
    e = next(ed for ed in m.edges
             if id(ed.v0) in on_top and id(ed.v1) in on_top)
    e.layer = "Barandas"                              # an edge of its own
    walls = Group(m, "muros")
    walls.layer = "Muros"
    scene.groups.append(walls)
    m2 = M.Mesh()
    a = m2.add_face([V(4, 0, 0), V(6, 0, 0), V(6, 2, 1), V(4, 2, 1)])
    b = m2.add_face([V(4, 2, 1), V(6, 2, 1), V(6, 4, 0), V(4, 4, 0)])
    shared = {id(v) for v in a.loop} & {id(v) for v in b.loop}
    ridge = next(ed for ed in m2.edges
                 if id(ed.v0) in shared and id(ed.v1) in shared)
    ridge.soft = True
    roof = Group(m2, "techo")
    roof.layer = "Techos"
    scene.groups.append(roof)
    lf = scene.loose_mesh.add_face([V(-3, 0, 0), V(-1, 0, 0), V(-1, 2, 0),
                                    V(-3, 2, 0)])
    lf.attrs["layer"] = "Mobiliario"
    le = scene.loose_mesh.add_edge(V(-3, 4, 0), V(3, 4, 0))
    le.layer = "Ejes"
    hid = scene.loose_mesh.add_edge(V(-3, 5, 0), V(3, 5, 0))
    hid.hidden = True
    scene.version += 1
    if not lazy:
        return scene
    path = tmp_path / "capas.igz"
    igz.save_scene(scene, path)
    opened = Scene()
    igz.load_into(opened, path)
    assert any(type(g.mesh) is M.DeferredMesh for g in opened.groups)
    return opened


def _canon(d):
    """The drawing as a set: each segment rounded, with its class and
    layer, both ends in either order."""
    out = []
    for seg, kind, tag in zip(d.segs, d.kinds, d.layers):
        a, b = tuple(np.round(seg[:2], 6)), tuple(np.round(seg[2:], 6))
        out.append((min(a, b), max(a, b), int(kind), tag))
    return sorted(out)


def _viewport(scene):
    from views.viewport import Viewport
    vp = Viewport(None)
    vp.scene = scene
    vp.resize(800, 600)
    vp.camera.set_aspect(800, 600)
    vp.camera.perspective = False
    vp.camera.set_view("iso")
    lo, hi = scene.bounds()
    vp.camera.fit_to(lo, hi, 1.2)
    vp.notify_scene_changed()
    return vp


@pytest.fixture(params=["built", "lazy"])
def lazy(request, monkeypatch):
    if request.param == "lazy":
        if _native.available() is None or _native.qt_hypot() is None:
            pytest.skip("native module or hypot unknown")
        monkeypatch.setattr(igz, "_LARGE_DOCUMENT", 0)
        monkeypatch.setattr(_native, "wanted", lambda: True)
        monkeypatch.setattr(_native, "native", _native.available())
    return request.param == "lazy"


def test_the_arrays_draw_the_lines_the_walk_draws_with_their_layers(
        tmp_path, lazy):
    _app()
    scene = _scene(tmp_path, lazy)
    vp = _viewport(scene)
    geometry = vp.hlr_geometry(tags=True)
    assert len(geometry) == 7
    tris, hard, soft, soft_n, ttags, htags, stags = geometry
    assert len(ttags) == len(tris) and len(htags) == len(hard)
    assert len(stags) == len(soft) and len(soft)       # the ridge
    walked = hlr_drawing(scene, vp.camera, layers=True)
    arrays = hlr_drawing(scene, vp.camera, layers=True, geometry=geometry)
    assert _canon(arrays) == _canon(walked)
    tags = {t for *_rest, t in _canon(arrays)}
    # Every layer a line can carry is there: the object's, the edge's own
    # inside the object, the loose edge's. (A face's own layer inks its
    # section cut, not its edges: see the cut below.)
    assert {"Muros", "Barandas", "Techos", "Ejes"} <= tags
    assert "Losa" not in tags and "Mobiliario" not in tags
    # The ridge is a profile on the roof's layer, and the hidden edge is
    # nowhere.
    assert any(k == 1 and t == "Techos" for _a, _b, k, t in _canon(arrays))
    assert not any(a[1] == 5.0 and b[1] == 5.0 for a, b, _k, _t in
                   _canon(arrays))
    vp.close()


def test_with_a_section_cut_too(tmp_path, lazy):
    from core.history import History, PlaceSectionPlaneCommand
    from core.section import SectionPlane
    _app()
    scene = _scene(tmp_path, lazy)
    vp = _viewport(scene)
    hist = History(scene)
    hist.execute(PlaceSectionPlaneCommand(
        SectionPlane(V(1, 1, 1.0), V(0, 0, 1))))
    geometry = vp.hlr_geometry(tags=True)
    walked = hlr_drawing(scene, vp.camera, layers=True)
    arrays = hlr_drawing(scene, vp.camera, layers=True, geometry=geometry)
    assert _canon(arrays) == _canon(walked)
    assert sorted(arrays.loop_layers) == sorted(walked.loop_layers)
    cut = {t for _a, _b, k, t in _canon(arrays) if k == 2}
    assert cut == {"Muros"}        # the plane crosses the walls' object
    vp.close()


def test_the_exports_hand_the_arrays_over(tmp_path, monkeypatch):
    """The SVG and DXF exports of a view with layers no longer walk."""
    from core import hlr as H
    from views import main_window as mw
    from views.main_window import MainWindow
    _app()
    win = MainWindow()
    try:
        scene = _scene(tmp_path, False)
        win.viewport.scene.layers[:] = scene.layers
        win.viewport.scene.groups[:] = scene.groups
        for f in list(scene.loose_mesh.faces):
            win.viewport.scene.loose_mesh.add_face(
                [V(v) for v in f.vertices]).attrs.update(f.attrs)
        win.viewport.scene.version += 1
        win.viewport.notify_scene_changed()
        walked = []
        real = H.collect_geometry
        monkeypatch.setattr(H, "collect_geometry",
                            lambda *a, **k: (walked.append(1), real(*a, **k))[1])
        groups = win._view_line_groups()
        assert groups and walked == []
        monkeypatch.setattr(mw.file_dialogs, "getSaveFileName",
                            lambda *a, **k: (str(tmp_path / "v.dxf"), ""))
        win._on_export_view_dxf()
        assert (tmp_path / "v.dxf").exists() and walked == []
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


def test_a_hidden_face_inside_an_object_hides_nothing():
    """A face hidden inside a component is not drawn in the view and hides
    nothing there; the walk of the model took it as an occluder (and drew
    its edges), so a sheet by layer showed less than the screen under a
    hidden roof. From the arrays, as on the screen: the box under the
    hidden top keeps its edges."""
    _app()
    scene = Scene()
    m = M.Mesh()
    roof = m.add_face([V(0, 0, 2), V(2, 0, 2), V(2, 2, 2), V(0, 2, 2)])
    roof.attrs["hidden"] = True                       # a hidden roof
    scene.groups.append(Group(m, "a"))
    m2 = M.Mesh()
    _box(m2, 0.5, 0.5, 0.0, 1.0)                      # a box under it
    scene.groups.append(Group(m2, "b"))
    scene.version += 1
    vp = _viewport(scene)
    vp.camera.set_view("top")
    lo, hi = scene.bounds()
    vp.camera.fit_to(lo, hi, 1.2)
    arrays = hlr_drawing(scene, vp.camera, layers=True,
                         geometry=vp.hlr_geometry(tags=True))
    walked = hlr_drawing(scene, vp.camera, layers=True)
    # Seen from above through the hidden roof: the box's top edges (z = 1).
    def at_top(d):
        return int(np.sum(np.all(np.abs(d.world[:, :, 2] - 1.0) < 1e-6,
                                 axis=1)))
    assert at_top(arrays) >= 4
    # The walk hid them behind the hidden face: the two differ there.
    assert at_top(walked) == 0
    assert _canon(arrays) != _canon(walked)
    vp.close()
