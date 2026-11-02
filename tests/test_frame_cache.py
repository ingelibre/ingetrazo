# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A pointer move over a still view reuses the model the last frame drew
(``Viewport._frame_cache_key``) and draws only the cursor's cues over it:
the dots of the face under the cursor, the edge under it. The frame must
come out the same, pixel for pixel, as one drawn whole — with the cue on
faces, on edges, on a selected face, over the axes and a guide, from
several views — and anything that changes what the model shows (a
selection, an edit, the style) must not bring back an old picture.

Needs a GL context that renders; skipped where the platform has none
(run with QT_QPA_PLATFORM=wayland or xcb)."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QMatrix4x4, QVector3D as V
from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])


def _box(mesh, x0, y0, z0, x1, y1, z1):
    p = [V(x0, y0, z0), V(x1, y0, z0), V(x1, y1, z0), V(x0, y1, z0),
         V(x0, y0, z1), V(x1, y0, z1), V(x1, y1, z1), V(x0, y1, z1)]
    for idx in ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5),
                (2, 3, 7, 6), (3, 0, 4, 7)):
        mesh.add_face([p[i] for i in idx])


@pytest.fixture
def win():
    from core.group import Group
    from core.guide import Guide
    from core.mesh import Mesh
    from views.main_window import MainWindow
    w = MainWindow()
    w.resize(1000, 700)
    w.show()
    for _ in range(10):
        _app.processEvents()
    vp = w.viewport
    if getattr(vp, "_gl", None) is None or not vp.isValid():
        w.close()
        pytest.skip("no OpenGL context on this platform")
    sc = vp.scene
    # A floor through the origin (the axes run over it), boxes, a copy.
    sc.mesh.add_face([V(-6, -6, 0), V(6, -6, 0), V(6, 6, 0), V(-6, 6, 0)])
    _box(sc.mesh, -4, -1, 0, -2, 1, 2)
    # Standing on the X axis: its bottom edge runs along the red axis.
    sc.mesh.add_face([V(2, 0, 0), V(4.5, 0, 0), V(4.5, 0, 1.5), V(2, 0, 1.5)])
    m = Mesh()
    _box(m, 0, 0, 0, 1.5, 1, 3)
    for k in range(3):
        g = Group(m, name=f"c{k}")
        xf = QMatrix4x4()
        xf.translate(1 + 1.8 * k, -3 + k, 0)
        g.xform = xf
        sc.groups.append(g)
    sc.guides.append(Guide(V(0, 2.5, 0), V(1, 0.3, 0)))
    sc.version += 1
    yield w, vp
    w._saved_version = sc.version
    w.close()


def _frame(vp, cache):
    import views.viewport as V_
    was, V_._FRAME_CACHE = V_._FRAME_CACHE, cache
    try:
        vp.update()
        _app.processEvents()
        return vp.grabFramebuffer()
    finally:
        V_._FRAME_CACHE = was


def _cues(vp):
    """Faces and edges to put the cursor on: loose, grouped, the floor
    under the axes."""
    sc = vp.scene
    out = [(f, None) for f in sc.mesh.faces[:5]]
    out += [(f, None) for f in sc.mesh.faces if _on_axis(f)]
    out += [(e, None) for e in list(sc.mesh.edges)[:6]]
    g = _copies(sc)[1]
    out += [(f, g) for f in g.mesh.faces[:3]]
    return out


def _copies(sc):
    return [g for g in sc.groups if g.name in ("c0", "c1", "c2")]


def _on_axis(face):
    ps = [v.position if hasattr(v, "position") else v
          for v in getattr(face, "vertices", ())]
    return bool(ps) and all(abs(p.y()) < 1e-6 for p in ps)


def _same(a, b):
    if a.size() != b.size():
        return False
    return a.convertToFormat(a.Format.Format_RGBA8888) == \
        b.convertToFormat(b.Format.Format_RGBA8888)


@pytest.mark.parametrize("view", ["iso", "top", "front"])
def test_a_pointer_move_draws_what_a_whole_frame_draws(win, view,
                                                      monkeypatch):
    w, vp = win
    reused = []
    real = type(vp)._frame_cache_restore
    monkeypatch.setattr(type(vp), "_frame_cache_restore",
                        lambda self, *a: reused.append(real(self, *a))
                        or reused[-1])
    vp.camera.set_view(view)
    vp.camera.fit_to(V(-7, -7, -1), V(7, 7, 4))
    first = vp.scene.mesh.faces[1]
    vp.scene.selection.add(first)           # a selected face keeps its dots
    vp.scene.bump_view()
    hits, bare, shown = 0, None, 0
    for ent, place in [(None, None)] + _cues(vp):
        vp._hover_entity, vp._hover_placement = ent, place
        whole = _frame(vp, False)
        _frame(vp, True)                    # keeps the model, or reuses it
        kept = vp._frame_cache
        got = _frame(vp, True)              # surely reused now
        assert vp._frame_cache == kept
        assert _same(got, whole), (view, type(ent).__name__)
        assert reused[-1], "the second frame was not reused"
        if bare is None:
            bare = whole
        shown += not _same(whole, bare)
        hits += 1
    assert hits > 10
    assert shown >= 3                   # the cues really show


def test_what_changes_the_model_is_not_drawn_from_the_old_frame(win):
    w, vp = win
    vp.camera.set_view("iso")
    vp.camera.fit_to(V(-7, -7, -1), V(7, 7, 4))
    face = vp.scene.mesh.faces[2]
    vp._hover_entity, vp._hover_placement = face, None
    _frame(vp, True)
    _frame(vp, True)
    sc = vp.scene

    def swap():                         # another face, the same count
        sc.selection.clear()
        sc.selection.add(sc.mesh.faces[4])
        sc.bump_view()

    def move():                         # a copy moves: nothing is counted
        g = _copies(sc)[0]
        xf = QMatrix4x4(g.xform)
        xf.translate(0, 1.5, 0)
        g.xform = xf
        sc.version += 1

    steps = [
        lambda: (sc.selection.add(sc.mesh.faces[3]), sc.bump_view()),
        swap,
        move,
        lambda: vp.scene.mesh.add_face([V(3, 3, 1), V(5, 3, 1), V(5, 5, 1),
                                        V(3, 5, 1)]) and None,
        lambda: setattr(vp.scene, "show_axes", False),
        lambda: setattr(vp.camera, "distance", vp.camera.distance * 0.8),
    ]
    for k, step in enumerate(steps):
        step()
        vp.scene.version += k == 3
        got = _frame(vp, True)
        assert _same(got, _frame(vp, False)), k


def test_off_the_frame_is_drawn_whole(win, monkeypatch):
    import views.viewport as V_
    w, vp = win
    monkeypatch.setattr(V_, "_FRAME_CACHE", False)
    calls = []
    real = type(vp)._paint_static
    monkeypatch.setattr(type(vp), "_paint_static",
                        lambda self, *a: (calls.append(a[-1]),
                                          real(self, *a))[1])
    vp._hover_entity = vp.scene.mesh.faces[0]
    vp.update()
    _app.processEvents()
    vp.grabFramebuffer()
    assert calls and all(c is vp.scene.mesh.faces[0] for c in calls)


def _fresh_depth(vp):
    """The depth the scene FBO holds now, read back afresh."""
    keep = vp._depth_snap, getattr(vp, "_depth_snap_of", None)
    vp.makeCurrent()
    try:
        vp._capture_depth(*vp._painted_view[1:])
        buf = vp._depth_snap[0].copy()
    finally:
        vp.doneCurrent()
        vp._depth_snap, vp._depth_snap_of = keep
    return buf


def test_the_depth_kept_over_pointer_moves_is_the_frames(win, monkeypatch):
    """A pointer move over the kept model keeps the depth read back the
    move before, when nothing drawn over the model writes depth: it must
    be the depth a read now gives, value for value — over faces, edges
    (whose highlight writes depth) and nothing."""
    import numpy as np
    w, vp = win
    reads = []
    real = type(vp)._capture_depth
    monkeypatch.setattr(type(vp), "_capture_depth",
                        lambda self, *a: (reads.append(1),
                                          real(self, *a))[1])
    vp.camera.set_view("iso")
    vp.camera.fit_to(V(-7, -7, -1), V(7, 7, 4))
    cx, cy = vp.width() / 2.0, vp.height() / 2.0
    kept = 0
    steps = [(None, None)] + _cues(vp)
    for k, (ent, place) in enumerate(steps * 2):
        if k == len(steps):             # a copy moves: the depth is new
            g = _copies(vp.scene)[0]
            xf = QMatrix4x4(g.xform)
            xf.translate(0.0, 0.0, 1.5)
            g.xform = xf
            vp.scene.version += 1
        vp._hover_entity, vp._hover_placement = ent, place
        _frame(vp, True)
        n = len(reads)
        assert vp._depth_world_at(cx, cy) is not None
        kept += len(reads) == n
        assert np.array_equal(vp._depth_snap[0], _fresh_depth(vp)), \
            type(ent).__name__
    assert kept > 10


def test_a_preview_that_writes_depth_reads_it_again(win, monkeypatch):
    w, vp = win
    reads = []
    real = type(vp)._capture_depth
    monkeypatch.setattr(type(vp), "_capture_depth",
                        lambda self, *a: (reads.append(1),
                                          real(self, *a))[1])
    vp.camera.set_view("iso")
    vp.camera.fit_to(V(-7, -7, -1), V(7, 7, 4))

    w._activate_tool("pushpull")        # its solid preview is depth tested
    assert vp.active_tool.wireframe_depth_tested
    vp._hover_entity, vp._hover_placement = vp.scene.mesh.faces[0], None
    for k in range(4):
        _frame(vp, True)
        n = len(reads)
        vp._depth_world_at(vp.width() / 2.0, vp.height() / 2.0)
        assert len(reads) == n + 1, k


# ---- Issue #944: the kept picture is stored once the view settles ---------

def test_frame_cache_track_reports_a_settled_view():
    # No GL needed: the settle decision itself, driven frame by frame.
    from views.viewport import Viewport
    vp = Viewport.__new__(Viewport)
    assert vp._frame_cache_track((1.0, 0.0)) is False    # first frame
    assert vp._frame_cache_track((1.0, 0.0)) is True     # same view again
    assert vp._frame_cache_track((0.0, 1.0)) is False    # camera moved
    assert vp._frame_cache_track((0.0, 2.0)) is False    # still moving
    assert vp._frame_cache_track((0.0, 2.0)) is True     # settled


def _one_paint(vp):
    """Exactly one paint per camera step, as an orbit gets: ``_frame``
    paints twice (the update, then the grab), and the second one already
    sees a settled view."""
    import views.viewport as V_
    was, V_._FRAME_CACHE = V_._FRAME_CACHE, True
    try:
        return vp.grabFramebuffer()
    finally:
        V_._FRAME_CACHE = was


def test_the_picture_is_kept_once_the_view_settles(win, monkeypatch):
    w, vp = win
    stores = []
    real = type(vp)._frame_cache_store
    monkeypatch.setattr(type(vp), "_frame_cache_store",
                        lambda self, *a: (stores.append(1),
                                          real(self, *a))[1])
    vp.camera.set_view("iso")
    vp.camera.fit_to(V(-7, -7, -1), V(7, 7, 4))
    _frame(vp, True)                    # this view's first frame
    kept = len(stores)
    for view in ("top", "front", "iso", "top"):
        vp.camera.set_view(view)        # an orbit: every frame moves
        _one_paint(vp)
    assert len(stores) == kept, "a moving view stored pictures it never reuses"
    for _ in range(3):                  # the view stands still now
        _one_paint(vp)
    assert len(stores) == kept + 1, "the settled frame did not keep the picture"
    assert vp._frame_cache is not None
