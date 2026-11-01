# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""An edit elsewhere does not rebuild the face-me figures (#1006).

After the clicks were fixed, drawing a rectangle, painting a face, opening
a group and pressing Esc still took ~4–5 s each on the villa: the figures'
cached draw data was keyed on the model's content version and on the
active mesh, so ANY edit — or entering/leaving any group — triangulated
the 18 vector-art figures again. Now only an edit of the figure itself
does. And the first click inside an opened group no longer builds every
not-yet-built group of the experimental engine to check the selection."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QMatrix4x4, QVector3D  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication([])

from core.group import Group  # noqa: E402
from core.mesh import DeferredMesh, Mesh  # noqa: E402


def V(x, y, z=0.0):
    return QVector3D(float(x), float(y), float(z))


def _window():
    from views.main_window import MainWindow
    return MainWindow()


def _close(win):
    win._saved_version = win.viewport.scene.version
    win.close()


def _figure(vp, placed=False):
    g = Group(Mesh(), name="Susan")
    g.billboard = "mesh"
    f = g.mesh.add_face([V(1, 2, 0), V(2, 2, 0), V(2, 2, 1.7), V(1, 2, 1.7)])
    f.attrs["color"] = (0.5, 0.5, 0.5)
    if placed:
        g.xform = QMatrix4x4()
        g.xform.translate(3, 0, 0)
    vp.scene.groups.append(g)
    return g


def _box_group(vp):
    m = Mesh()
    m.add_face([V(5, 0, 0), V(6, 0, 0), V(6, 1, 0), V(5, 1, 0)])
    g = Group(m, name="Box")
    vp.scene.groups.append(g)
    return g


def _counting(monkeypatch, vp):
    calls = []
    tris = vp._tris_of

    def counted(face):
        calls.append(face)
        return tris(face)
    monkeypatch.setattr(vp, "_tris_of", counted)
    return calls


def test_an_edit_elsewhere_keeps_the_figure(monkeypatch):
    win = _window()
    vp = win.viewport
    try:
        g = _figure(vp)
        box = _box_group(vp)
        vp.scene.version += 1
        calls = _counting(monkeypatch, vp)
        first = vp._faceme_base(g)
        assert first is not None and len(calls) == 1
        # a rectangle drawn on the ground, a face painted elsewhere
        loose = vp.scene.mesh.add_face(
            [V(0, 5, 0), V(1, 5, 0), V(1, 6, 0), V(0, 6, 0)])
        vp.scene.version += 1
        loose.attrs["color"] = (1.0, 0.0, 0.0)
        vp.scene.version += 1
        assert vp._faceme_base(g) is first
        # a group opened and closed again
        vp.scene.begin_group_edit(box)
        vp.scene.version += 1
        assert vp._faceme_base(g) is first
        vp.scene.end_group_edit()
        vp.scene.version += 1
        assert vp._faceme_base(g) is first
        # the experimental engine building the figure's mesh late bumps
        # its serial without changing it
        g.mesh._mut_serial += 7
        vp.scene.version += 1
        assert vp._faceme_base(g) is first
        assert len(calls) == 1, "an edit elsewhere triangulated the figure"
    finally:
        _close(win)


def test_an_edit_of_the_figure_rebuilds_it(monkeypatch):
    win = _window()
    vp = win.viewport
    try:
        g = _figure(vp)
        vp.scene.version += 1
        first = vp._faceme_base(g)
        # painted: the new colour is what gets drawn
        f = g.mesh.faces[0]
        f.attrs = dict(f.attrs, color=(0.1, 0.2, 0.3))
        vp.scene.version += 1
        painted = vp._faceme_base(g)
        assert painted is not first
        assert set(painted[1]) == {(0.1, 0.2, 0.3)}
        # reshaped: the anchor follows the vertex
        v = min(g.mesh.vertices, key=lambda v: (v.position.z(),
                                                v.position.x()))
        g.mesh.move_vertex(v, V(-1, 0, 0))
        vp.scene.version += 1
        moved = vp._faceme_base(g)
        assert moved is not painted
        assert abs(moved[2][0] - (painted[2][0] - 0.5)) < 1e-6
    finally:
        _close(win)


def test_the_extent_follows_the_figure_not_the_model(monkeypatch):
    win = _window()
    vp = win.viewport
    try:
        for placed in (False, True):
            g = _figure(vp, placed)
            vp.scene.version += 1
            walks = []
            mesh_of = vp._billboard_mesh
            monkeypatch.setattr(vp, "_billboard_mesh",
                                lambda grp: walks.append(grp) or mesh_of(grp))
            ext = vp._billboard_extent(g)
            assert ext is not None and len(walks) == 1
            vp.scene.mesh.add_face([V(0, 5, 0), V(1, 5, 0), V(1, 6, 0)])
            vp.scene.version += 1
            assert vp._billboard_extent(g) == ext
            assert len(walks) == 1, "an edit elsewhere walked the figure"
            for v in list(g.mesh.vertices):
                g.mesh.move_vertex(v, V(0, 0, 2))
            vp.scene.version += 1
            assert abs(vp._billboard_extent(g)[0].z() - ext[0].z() - 2) \
                < 1e-6
            monkeypatch.undo()
    finally:
        _close(win)


class _Stop(Exception):
    pass


def _stop_after_the_purge(vp):
    """The purge of dead hover/selection refs runs first in _sync_edges;
    stop there (the buffers need GL, and a lazy group without a source
    cannot be baked)."""
    def stop():
        raise _Stop
    vp._sync_content_key = stop


def test_a_selection_inside_a_group_leaves_unbuilt_groups_alone():
    win = _window()
    vp = win.viewport
    try:
        import pytest
        _stop_after_the_purge(vp)
        builds = []

        def build(mesh):
            builds.append(mesh)
            mesh.add_face([V(9, 0, 0), V(10, 0, 0), V(10, 1, 0)])
        lazy = Mesh()
        assert DeferredMesh.defer(lazy, build, 1)
        vp.scene.groups.append(Group(lazy, name="Lazy"))
        box = _box_group(vp)
        vp.scene.version += 1
        vp.scene.begin_group_edit(box)
        vp.scene.version += 1
        face = box.mesh.faces[0]
        vp.scene.select([face])
        with pytest.raises(_Stop):
            vp._sync_edges()
        assert face in vp.scene.selection, "a live selection was dropped"
        # a face of a group that is not open is not alive here
        stray = Mesh().add_face([V(0, 0, 0), V(1, 0, 0), V(1, 1, 0)])
        vp.scene.select([face, stray])
        with pytest.raises(_Stop):
            vp._sync_edges()
        assert face in vp.scene.selection
        assert stray not in vp.scene.selection
        assert not builds, "checking the selection built a lazy group"
        vp.scene.end_group_edit()
    finally:
        _close(win)
