# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Inside a group, the split of a kept instanced batch is kept with it.

With a group open, every instanced pass (faces, edges, outlines) split each
prototype's placements into the faded surroundings and the subject: four
tests per placement per pass, ~6-9 ms of every camera frame inside a group
of a plaza of 3 800 placements, while the batches themselves are kept as
long as the view keeps its placements. The split is now kept with the
batch (which placements are the surroundings, as bytes) while the
context, the placements and the scene stay the same:

* the same placements, the same fade, as working it out again;
* an orbit asks nothing again; another context, an edit, another rest
  mode or strength work it out again;
* the frames are the ones drawn with the split worked out afresh.

The frames need a GL context that renders; skipped where there is none."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtGui import QMatrix4x4, QVector3D as V  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication([])


def _box(mesh, x0, y0, z0, x1, y1, z1):
    p = [V(x0, y0, z0), V(x1, y0, z0), V(x1, y1, z0), V(x0, y1, z0),
         V(x0, y0, z1), V(x1, y0, z1), V(x1, y1, z1), V(x0, y1, z1)]
    for idx in ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5),
                (2, 3, 7, 6), (3, 0, 4, 7)):
        mesh.add_face([p[i] for i in idx])


def _copy(mesh, name, x, y):
    from core.group import Group
    g = Group(mesh, name=name)
    xf = QMatrix4x4()
    xf.translate(x, y, 0)
    g.xform = xf
    return g


@pytest.fixture
def win():
    from core.group import Group
    from core.mesh import Mesh
    from views.main_window import MainWindow
    w = MainWindow()
    w.resize(900, 650)
    w.show()
    for _ in range(10):
        _app.processEvents()
    vp = w.viewport
    if getattr(vp, "_gl", None) is None or not vp.isValid():
        w.close()
        pytest.skip("no OpenGL context on this platform")
    sc = vp.scene
    m = Mesh()
    _box(m, 0, 0, 0, 1, 1, 1.5)
    # Two containers holding copies of one component, and copies loose:
    # inside either container, its copies are the subject and every other
    # copy of the same prototype is the faded surroundings.
    for name, y in (("A", 0.0), ("B", 4.0)):
        c = Group(Mesh(), name=name)
        c.children = [_copy(m, f"{name}{k}", 2.0 * k, y) for k in range(3)]
        sc.groups.append(c)
    for k in range(3):
        sc.groups.append(_copy(m, f"loose{k}", 2.0 * k, -4.0))
    sc.version += 1
    vp._edit_rest_mode = "fade"
    vp.update()
    for _ in range(5):
        _app.processEvents()
    yield w
    w._saved_version = sc.version
    w._saved_content = getattr(sc, "content_version", None)
    w.close()


def _reference(vp, groups):
    """The split as worked out on every call before."""
    from views.viewport._support import EDIT_REST_FADE
    fuera = [g for g in groups if vp._draws_in_edit_context(g)]
    dentro = [g for g in groups if not vp._draws_in_edit_context(g)]
    if vp._edit_rest_mode == "hide":
        return [(dentro, 0.0)]
    if vp._edit_rest_mode != "fade":
        return [(groups, 0.0)]
    return [(fuera, float(getattr(vp, "_edit_rest_fade_strength",
                                  EDIT_REST_FADE))), (dentro, 0.0)]


def _batches(vp):
    from views.viewport._support import _InstanceBatch
    got = [v[2] for v in (getattr(vp, "_frame_instanced", None) or {}).values()]
    assert got and all(isinstance(b, _InstanceBatch) for b in got), \
        "the copies did not draw instanced"
    return got


def _fresh_frame(vp):
    """The frame with every split worked out afresh."""
    for v in (getattr(vp, "_frame_instanced", None) or {}).values():
        try:
            del v[2].split
        except AttributeError:
            pass
    vp._frame_cache = None
    return vp.grabFramebuffer()


def _enter(vp, name):
    while vp.scene.edit_group is not None:
        vp.end_group_edit()
    g = next(g for g in vp.scene.groups if g.name == name)
    vp.begin_group_edit(g)
    _app.processEvents()
    vp.grabFramebuffer()


def test_the_split_is_the_one_worked_out_and_kept_on_an_orbit(win):
    vp = win.viewport
    _enter(vp, "A")
    batches = _batches(vp)
    for b in batches:
        assert vp._instanced_batches(b) == _reference(vp, b)
    assert any(len(lotes) == 2 and lotes[0][0] and lotes[1][0]
               for lotes in (vp._instanced_batches(b) for b in batches)), \
        "no batch held both the subject and its surroundings"
    asked = []
    real = vp._draws_in_edit_context
    vp._draws_in_edit_context = lambda g: asked.append(g) or real(g)
    try:
        vp.camera.yaw += 0.03                 # an orbit: the view moves
        vp.grabFramebuffer()
        now = _batches(vp)
        assert len(now) == len(batches) and all(
            a is b for a, b in zip(now, batches)), \
            "the orbit did not keep the batches (the test needs it to)"
        for b in batches:
            vp._instanced_batches(b)
        placed = {id(g) for b in batches for g in b}
        again = [g for g in asked if id(g) in placed]
        assert not again, "a kept batch was split again"
    finally:
        del vp._draws_in_edit_context
    assert vp.grabFramebuffer() == _fresh_frame(vp)


@pytest.mark.parametrize("change", ["context", "edit", "mode", "strength"])
def test_a_change_works_the_split_out_again(win, change):
    vp = win.viewport
    _enter(vp, "A")
    for b in _batches(vp):
        vp._instanced_batches(b)              # kept
    old = _batches(vp)
    if change == "context":
        _enter(vp, "B")
    elif change == "edit":
        vp.scene.version += 1
    elif change == "mode":
        vp._edit_rest_mode = "hide"
    else:
        vp._edit_rest_fade_strength = 0.61
    for b in old + _batches(vp):              # the old batches too
        assert vp._instanced_batches(b) == _reference(vp, b), change
    kept = vp.grabFramebuffer()
    assert kept == _fresh_frame(vp), change
