# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Issue #831: work on a curved surface's facets.

With Camera ▸ Hidden Geometry on, a click on a cylinder's side selected the
whole side, and a line drawn over a facet seam welded into that soft edge
and stayed undrawn — «they do not stick». There was also no way to soften
or harden edges by hand. Now: one facet selects alone while hidden
geometry shows, a line over a soft seam hardens it, and edges soften or
harden from the right-click menu and the Eraser (Ctrl / Ctrl+Shift)."""
from __future__ import annotations

import math
import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QVector3D  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

if QApplication.instance() is None:
    QApplication([])

from core.history import (  # noqa: E402
    HardenEdgesAlongCommand,
    SoftenEdgesCommand,
    soft_edges_along,
)
from core.mesh import Mesh  # noqa: E402
from views.viewport import Viewport  # noqa: E402


def V(x, y, z=0.0):
    return QVector3D(float(x), float(y), float(z))


def _vp():
    vp = Viewport(None)
    vp.resize(1000, 600)
    vp.camera.set_aspect(1000, 600)
    vp.flash_status = lambda *a, **k: None
    vp.camera.set_view("top")
    vp.camera.target = V(1, 1, 0)
    vp.camera.distance = 8
    return vp


def _two_facets(vp):
    """A 2×2 square split by a SOFT diagonal: two facets of one smooth
    surface, as a cylinder's side is."""
    sc = vp.scene
    a, b, c, d = V(0, 0, 1), V(2, 0, 1), V(2, 2, 1), V(0, 2, 1)
    f1 = sc.mesh.add_face([a, b, c])
    f2 = sc.mesh.add_face([a, c, d])
    seam = sc.mesh.find_edge(sc.mesh.vertex_at(a), sc.mesh.vertex_at(c))
    seam.soft = True
    sc.version += 1
    return f1, f2, seam


def _cylinder_side(mesh, n=12, r=1.0, h=2.0):
    """The side of an ``n``-sided cylinder, its seams soft."""
    ring = [(r * math.cos(2 * math.pi * i / n),
             r * math.sin(2 * math.pi * i / n)) for i in range(n)]
    faces = []
    for i in range(n):
        (x0, y0), (x1, y1) = ring[i], ring[(i + 1) % n]
        faces.append(mesh.add_face([V(x0, y0, 0), V(x1, y1, 0),
                                    V(x1, y1, h), V(x0, y0, h)]))
    seams = []
    for x, y in ring:
        e = mesh.find_edge(mesh.vertex_at(V(x, y, 0)),
                           mesh.vertex_at(V(x, y, h)))
        e.soft = True
        seams.append(e)
    return faces, seams


# ---- 1. A facet selects alone while hidden geometry shows ----------------

def test_a_facet_selects_alone_with_hidden_geometry_on():
    from tools.select import SelectTool
    vp = _vp()
    f1, f2, _seam = _two_facets(vp)
    assert set(SelectTool._expand(vp, f1)) == {f1, f2}    # the whole surface
    vp.scene.show_hidden_geometry = True
    assert SelectTool._expand(vp, f1) == [f1]             # one facet
    vp.scene.show_hidden_geometry = False
    assert set(SelectTool._expand(vp, f2)) == {f1, f2}


def test_a_cylinder_facet_selects_alone():
    from tools.select import SelectTool
    vp = _vp()
    faces, _ = _cylinder_side(vp.scene.mesh)
    vp.scene.version += 1
    assert len(SelectTool._expand(vp, faces[3])) == len(faces)
    vp.scene.show_hidden_geometry = True
    assert SelectTool._expand(vp, faces[3]) == [faces[3]]


# ---- 2. The soften command ---------------------------------------------

def test_soften_and_harden_undo_exactly():
    vp = _vp()
    _f1, _f2, seam = _two_facets(vp)
    hard = vp.scene.mesh.find_edge(vp.scene.mesh.vertex_at(V(0, 0, 1)),
                                   vp.scene.mesh.vertex_at(V(2, 0, 1)))
    assert not hard.soft
    v0 = vp.scene.version
    cmd = SoftenEdgesCommand([seam, hard], soft=False)
    vp.history.execute(cmd)
    assert not seam.soft and not hard.soft
    assert vp.scene.version > v0
    vp.history.undo()
    assert seam.soft and not hard.soft                    # each its own flag
    vp.history.redo()
    assert not seam.soft
    vp.history.execute(SoftenEdgesCommand([hard], soft=True))
    assert hard.soft
    vp.history.undo()
    assert not hard.soft


def test_hardening_a_seam_splits_the_surface():
    """The flag is what joins the facets: hard, each one is its own face
    for the next click, with hidden geometry off too."""
    from tools.select import SelectTool
    vp = _vp()
    f1, f2, seam = _two_facets(vp)
    vp.history.execute(SoftenEdgesCommand([seam], soft=False))
    assert SelectTool._expand(vp, f1) == [f1]
    vp.history.undo()
    assert set(SelectTool._expand(vp, f1)) == {f1, f2}


def test_soften_flags_the_meshes_for_a_rebuild():
    vp = _vp()
    _f1, _f2, seam = _two_facets(vp)
    m = vp.scene.mesh
    m._chunk_dirty = False
    serial = getattr(m, "_mut_serial", 0)
    vp.history.execute(SoftenEdgesCommand([seam], soft=False))
    assert m._chunk_dirty and m._mut_serial > serial


# ---- 3. A line drawn over a soft seam hardens it -------------------------

def test_soft_edges_along_walks_a_chain():
    m = Mesh()
    e1 = m.add_edge(V(0, 0, 0), V(1, 0, 0))
    e2 = m.add_edge(V(1, 0, 0), V(3, 0, 0))
    off = m.add_edge(V(1, 0, 0), V(1, 1, 0))              # not on the line
    e1.soft = e2.soft = off.soft = True
    found = soft_edges_along(m, V(0, 0, 0), V(3, 0, 0))
    assert set(found) == {e1, e2}
    assert soft_edges_along(m, V(0, 0, 0), V(1, 0, 0)) == [e1]
    assert soft_edges_along(m, V(5, 5, 0), V(6, 5, 0)) == []


def test_a_line_over_a_soft_seam_hardens_it():
    from tools.line import LineTool
    vp = _vp()
    vp.scene.show_hidden_geometry = True
    _f1, _f2, seam = _two_facets(vp)
    cmd = LineTool()._commit_edge(vp, V(0, 0, 1), V(2, 2, 1))
    vp.history.execute(cmd)
    m = vp.scene.mesh
    edge = m.find_edge(m.vertex_at(V(0, 0, 1)), m.vertex_at(V(2, 2, 1)))
    assert edge is not None and not edge.soft            # it sticks: drawn
    vp.history.undo()
    edge = m.find_edge(m.vertex_at(V(0, 0, 1)), m.vertex_at(V(2, 2, 1)))
    assert edge is not None and edge.soft                # undo: soft again
    vp.history.redo()
    edge = m.find_edge(m.vertex_at(V(0, 0, 1)), m.vertex_at(V(2, 2, 1)))
    assert not edge.soft


def test_a_line_over_a_cylinder_seam_hardens_only_that_seam():
    from tools.line import LineTool
    vp = _vp()
    vp.scene.show_hidden_geometry = True
    _faces, seams = _cylinder_side(vp.scene.mesh)
    vp.scene.version += 1
    a = QVector3D(seams[2].a)
    b = QVector3D(seams[2].b)
    vp.history.execute(LineTool()._commit_edge(vp, a, b))
    m = vp.scene.mesh
    drawn = m.find_edge(m.vertex_at(a), m.vertex_at(b))
    assert not drawn.soft
    others = [e for e in m.edges
              if e is not drawn and abs(e.a.z() - e.b.z()) > 1.0]
    assert others and all(e.soft for e in others)


def test_harden_along_does_nothing_off_the_seams():
    vp = _vp()
    _f1, _f2, seam = _two_facets(vp)
    cmd = HardenEdgesAlongCommand(V(0, 0, 1), V(2, 0, 1))  # a hard border
    cmd.do(vp.scene)
    assert cmd.edges == [] and seam.soft
    cmd.undo(vp.scene)
    assert seam.soft


# ---- 4. The Eraser: Ctrl softens, Ctrl+Shift hardens ---------------------

class _Ctx:
    def __init__(self, vp, px, modifiers):
        from PySide6.QtCore import QPointF
        self.viewport = vp
        self.screen = QPointF(*px)
        self.modifiers = modifiers


def test_eraser_ctrl_shift_hardens_an_undrawn_seam():
    from PySide6.QtCore import Qt
    from tools.eraser import EraserTool
    vp = _vp()
    _f1, _f2, seam = _two_facets(vp)                     # hidden geometry off
    px = vp._world_to_pixel(V(1, 1, 1))
    tool = EraserTool()
    tool.on_click(_Ctx(vp, px, Qt.ControlModifier | Qt.ShiftModifier))
    assert seam in tool.marked                           # reaches the seam
    tool.on_release(vp)
    assert not seam.soft
    assert len(vp.scene.faces) == 2                      # nothing erased
    vp.history.undo()
    assert seam.soft


def test_eraser_ctrl_softens_and_erases_nothing():
    from PySide6.QtCore import Qt
    from tools.eraser import EraserTool
    vp = _vp()
    _f1, _f2, seam = _two_facets(vp)
    seam.soft = False
    vp.scene.version += 1
    px = vp._world_to_pixel(V(1, 1, 1))
    tool = EraserTool()
    tool.on_click(_Ctx(vp, px, Qt.ControlModifier))
    tool.on_release(vp)
    assert seam.soft
    assert len(vp.scene.faces) == 2
    assert seam in vp.scene.mesh.edges


def test_eraser_plain_and_shift_keep_their_meaning():
    from PySide6.QtCore import Qt
    from tools.eraser import EraserTool
    vp = _vp()
    tool = EraserTool()
    tool.on_click(_Ctx(vp, (5, 5), Qt.ShiftModifier))
    assert tool._hide and tool._soften is None
    tool.on_cancel(vp)
    tool.on_click(_Ctx(vp, (5, 5), Qt.NoModifier))
    assert not tool._hide and tool._soften is None


# ---- 5. Right-click ▸ Soften / Harden -----------------------------------

def test_soften_targets_take_edges_and_inner_edges_of_faces():
    from views.main_window import MainWindow
    vp = _vp()
    faces, seams = _cylinder_side(vp.scene.mesh)
    fake = SimpleNamespace(viewport=vp)
    # The whole side selected: its 12 seams, none of its rim edges.
    got = MainWindow._soften_targets(fake, faces)
    assert set(got) == set(seams)
    # Two neighbouring facets: only the seam they share.
    got = MainWindow._soften_targets(fake, faces[:2])
    assert got == [seams[1]]
    # A selected edge counts on its own.
    m = vp.scene.mesh
    p1 = V(math.cos(2 * math.pi / 12), math.sin(2 * math.pi / 12), 0)
    rim = m.find_edge(m.vertex_at(V(1, 0, 0)), m.vertex_at(p1))
    assert rim is not None and not rim.soft
    assert MainWindow._soften_targets(fake, [rim]) == [rim]


# ---- 6. Styles ▸ Hidden geometry: the same switch as the Camera menu -----

def test_styles_box_and_camera_menu_are_one_switch():
    from views.main_window import MainWindow
    app = QApplication.instance()
    win = MainWindow()
    win.show()
    app.processEvents()
    try:
        box = win.styles_panel._hidden_geo
        sc = win.viewport.scene
        assert not box.isChecked() and not sc.show_hidden_geometry
        box.setChecked(True)                       # Styles → scene + menu
        assert sc.show_hidden_geometry
        assert win._act_hidden_geometry.isChecked()
        win._act_hidden_geometry.setChecked(False)  # menu → Styles
        assert not box.isChecked() and not sc.show_hidden_geometry
        sc.show_hidden_geometry = True             # a load / scene recall
        win._sync_section_menu()
        assert box.isChecked() and win._act_hidden_geometry.isChecked()
    finally:
        win._saved_version = win.viewport.scene.version   # no save prompt
        win.close()


# ---- 7. Make Visible: an invisible line (soft or hidden) draws again ------

def test_make_visible_hardens_soft_and_unhides_hidden_lines():
    from core.history import edge_is_invisible, make_edges_visible_command
    vp = _vp()
    _f1, _f2, seam = _two_facets(vp)
    line = vp.scene.mesh.add_edge(V(3, 0, 0), V(5, 0, 0))
    line.hidden = True
    plain = vp.scene.mesh.add_edge(V(3, 1, 0), V(5, 1, 0))
    vp.scene.version += 1
    assert edge_is_invisible(seam) and edge_is_invisible(line)
    assert not edge_is_invisible(plain)
    assert make_edges_visible_command([plain]) is None
    vp.history.execute(make_edges_visible_command([seam, line, plain]))
    assert not seam.soft and not line.hidden
    vp.history.undo()                                  # one step
    assert seam.soft and line.hidden


def test_right_click_make_visible_and_hide_round_trip():
    """The right-click entries on a selected invisible line: Make Visible
    draws it, Hide puts it back among the hidden geometry."""
    from views.main_window import MainWindow
    app = QApplication.instance()
    win = MainWindow()
    win.show()
    app.processEvents()
    try:
        vp = win.viewport
        _f1, _f2, seam = _two_facets(vp)
        line = vp.scene.mesh.add_edge(V(3, 0, 0), V(5, 0, 0))
        line.hidden = True
        vp.scene.version += 1
        vp.scene.select([seam, line])
        win._on_make_visible()
        assert not seam.soft and not line.hidden
        vp.scene.select([line])
        win._on_hide()
        assert line.hidden                             # hidden geometry again
        vp.history.undo()
        vp.history.undo()
        assert seam.soft and line.hidden
    finally:
        win._saved_version = win.viewport.scene.version   # no save prompt
        win.close()


def test_eraser_ctrl_shift_brings_back_a_hidden_line():
    from PySide6.QtCore import Qt
    from tools.eraser import EraserTool
    vp = _vp()
    vp.scene.show_hidden_geometry = True               # seen dotted
    line = vp.scene.mesh.add_edge(V(0, 1, 0), V(2, 1, 0))
    line.hidden = True
    vp.scene.version += 1
    px = vp._world_to_pixel(V(1, 1, 0))
    tool = EraserTool()
    tool.on_click(_Ctx(vp, px, Qt.ControlModifier | Qt.ShiftModifier))
    tool.on_release(vp)
    assert not line.hidden and line in vp.scene.mesh.edges


def test_right_click_menu_offers_make_visible_hide_and_soften(monkeypatch):
    from PySide6.QtCore import QPoint
    from PySide6.QtWidgets import QMenu
    import views.main_window as mw

    opened: list = []

    class _NoModal(QMenu):
        def exec(self, *args, **kwargs):        # noqa: A003 - Qt's name
            opened.append(self)

    def entries(win, sel):
        opened.clear()
        monkeypatch.setattr(mw, "QMenu", _NoModal)
        win.viewport.scene.select(list(sel))
        win.show_viewport_context_menu(QPoint(0, 0))
        return [a.text() for a in opened[0].actions()]

    win = mw.MainWindow()
    try:
        vp = win.viewport
        _f1, _f2, seam = _two_facets(vp)
        line = vp.scene.mesh.add_edge(V(3, 0, 0), V(5, 0, 0))
        line.hidden = True
        plain = vp.scene.mesh.add_edge(V(3, 1, 0), V(5, 1, 0))
        vp.scene.version += 1
        got = entries(win, [seam])                    # an invisible seam
        assert "Make Visible" in got and "Hide" in got
        assert "Soften" not in got
        got = entries(win, [line])                    # a hidden line
        assert "Make Visible" in got
        assert "Unhide" not in got                    # one entry, not two
        got = entries(win, [plain])                   # a visible line
        assert "Make Visible" not in got
        assert "Hide" in got and "Soften" in got
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()
