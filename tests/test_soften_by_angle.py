# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Edit ▸ Soften Edges… (#347): soften the selection's edges by the angle
their faces fold, with a slider, live and as one undo step.

Right-click ▸ Soften went edge by edge; a faceted import (a cylinder of 48
sides, a terrain) needed every seam by hand. Now one angle softens the
gentle folds and hardens the sharp ones."""
from __future__ import annotations

import math
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtGui import QVector3D  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

if QApplication.instance() is None:
    QApplication([])

from core.history import (  # noqa: E402
    edge_fold_degrees,
    soften_by_angle,
    soften_by_angle_command,
)
from core.mesh import Mesh  # noqa: E402


def V(x, y, z=0.0):
    return QVector3D(float(x), float(y), float(z))


def _cylinder_side(mesh, n=12, r=1.0, h=2.0, x0=0.0):
    """The side of an ``n``-sided cylinder, its seams HARD (as an import
    leaves them): adjacent facets fold 360/n degrees."""
    ring = [(x0 + r * math.cos(2 * math.pi * i / n),
             r * math.sin(2 * math.pi * i / n)) for i in range(n)]
    faces = []
    for i in range(n):
        (xa, ya), (xb, yb) = ring[i], ring[(i + 1) % n]
        faces.append(mesh.add_face([V(xa, ya, 0), V(xb, yb, 0),
                                    V(xb, yb, h), V(xa, ya, h)]))
    seams = [mesh.find_edge(mesh.vertex_at(V(x, y, 0)),
                            mesh.vertex_at(V(x, y, h))) for x, y in ring]
    for e in seams:
        e.soft = False
    return faces, seams


def _fold(mesh, degrees):
    """A flat square and a second one rising from its x=2 side by
    ``degrees``: the edge between them folds exactly that much."""
    t = math.radians(degrees)
    dx, dz = 2 * math.cos(t), 2 * math.sin(t)
    f1 = mesh.add_face([V(0, 0), V(2, 0), V(2, 2), V(0, 2)])
    f2 = mesh.add_face([V(2, 0), V(2 + dx, 0, dz), V(2 + dx, 2, dz),
                        V(2, 2)])
    e = mesh.find_edge(mesh.vertex_at(V(2, 0)), mesh.vertex_at(V(2, 2)))
    return f1, f2, e


# ---- 1. The fold of an edge ---------------------------------------------

@pytest.mark.parametrize("deg", [5.0, 30.0, 90.0, 135.0])
def test_fold_reads_the_angle_between_the_faces(deg):
    m = Mesh()
    _f1, _f2, e = _fold(m, deg)
    assert edge_fold_degrees(e) == pytest.approx(deg, abs=1e-3)


def test_fold_of_a_cylinder_seam_is_its_step():
    m = Mesh()
    _faces, seams = _cylinder_side(m, n=12)
    for e in seams:
        assert edge_fold_degrees(e) == pytest.approx(30.0, abs=1e-3)


def test_fold_ignores_a_face_turned_the_other_way():
    """A reversed face (or an import whose winding disagrees) must not turn
    a gentle 10° fold into a sharp 170° one."""
    m = Mesh()
    _f1, f2, e = _fold(m, 10.0)
    f2.loop.reverse()
    assert edge_fold_degrees(e) == pytest.approx(10.0, abs=1e-3)


def test_fold_is_none_off_two_faces():
    m = Mesh()
    loose = m.add_edge(V(5, 0), V(6, 0))
    f = m.add_face([V(0, 0), V(1, 0), V(1, 1)])
    border = m.find_edge(m.vertex_at(V(0, 0)), m.vertex_at(V(1, 0)))
    assert f is not None
    assert edge_fold_degrees(loose) is None
    assert edge_fold_degrees(border) is None


# ---- 2. What an angle softens and hardens ----------------------------------

def test_angle_softens_gentle_folds_and_hardens_sharp_ones():
    m = Mesh()
    _faces, seams = _cylinder_side(m, n=12)          # 30° seams
    _a, _b, sharp = _fold(m, 90.0)
    sharp.soft = True                                 # wrongly soft
    soften, harden = soften_by_angle(seams + [sharp], 40.0)
    assert set(soften) == set(seams)
    assert harden == [sharp]
    # Below the step: the seams stay hard, nothing to soften.
    soften, harden = soften_by_angle(seams, 20.0)
    assert soften == [] and harden == []


def test_the_angle_itself_is_included():
    m = Mesh()
    _faces, seams = _cylinder_side(m, n=12)
    soften, _harden = soften_by_angle(seams, 30.0)
    assert set(soften) == set(seams)


def test_coplanar_edges_only_with_the_option():
    m = Mesh()
    f1 = m.add_face([V(0, 0), V(2, 0), V(2, 2)])
    f2 = m.add_face([V(0, 0), V(2, 2), V(0, 2)])
    assert f1 is not None and f2 is not None
    diag = m.find_edge(m.vertex_at(V(0, 0)), m.vertex_at(V(2, 2)))
    assert edge_fold_degrees(diag) == pytest.approx(0.0, abs=1e-6)
    assert soften_by_angle([diag], 45.0) == ([], [])
    assert soften_by_angle([diag], 45.0, coplanar=True) == ([diag], [])
    # Already soft and the option off: left as it is, never hardened.
    diag.soft = True
    assert soften_by_angle([diag], 45.0) == ([], [])


def test_loose_lines_and_borders_are_never_touched():
    m = Mesh()
    loose = m.add_edge(V(5, 0), V(6, 0))
    loose.soft = True
    assert soften_by_angle([loose], 0.0) == ([], [])
    assert soften_by_angle([loose], 180.0) == ([], [])


def test_command_is_one_undo_step_and_none_when_nothing_changes():
    from views.viewport import Viewport
    vp = Viewport(None)
    _faces, seams = _cylinder_side(vp.scene.mesh, n=12)
    _a, _b, sharp = _fold(vp.scene.mesh, 90.0)
    sharp.soft = True
    assert soften_by_angle_command(seams, 10.0) is None
    vp.history.execute(soften_by_angle_command(seams + [sharp], 40.0))
    assert all(e.soft for e in seams) and not sharp.soft
    vp.history.undo()
    assert not any(e.soft for e in seams) and sharp.soft


# ---- 3. The window -------------------------------------------------------

@pytest.fixture
def win():
    from views.main_window import MainWindow
    from views.soften_dialog import DEFAULT_DEGREES, SoftenEdgesPanel
    SoftenEdgesPanel._last = DEFAULT_DEGREES
    SoftenEdgesPanel._last_coplanar = False
    w = MainWindow()
    yield w
    dlg = getattr(w, "_soften_dialog", None)
    if dlg is not None:
        dlg.close()
    w._saved_version = w.viewport.scene.version   # no save prompt
    w.close()


def test_slider_moves_are_one_undo_step(win):
    vp = win.viewport
    faces, seams = _cylinder_side(vp.scene.mesh, n=12)
    vp.scene.version += 1
    vp.scene.select(faces)
    before = len(vp.history.undo_stack)
    win.show_soften_dialog()
    dlg = win._soften_dialog
    assert len(vp.history.undo_stack) == before      # opening changes nothing
    dlg.slider.setValue(40)
    assert all(e.soft for e in seams)
    dlg.slider.setValue(10)
    assert not any(e.soft for e in seams)
    dlg.box.setValue(35.0)
    assert all(e.soft for e in seams)
    assert len(vp.history.undo_stack) == before + 1  # however many moves
    vp.history.undo()
    assert not any(e.soft for e in seams)
    assert len(vp.history.undo_stack) == before


def test_a_move_that_changes_nothing_leaves_redo_empty(win):
    """Moving back to an angle that leaves the edges as they were must not
    leave the previous move waiting in Redo."""
    vp = win.viewport
    faces, seams = _cylinder_side(vp.scene.mesh, n=12)
    vp.scene.version += 1
    vp.scene.select(faces)
    win.show_soften_dialog()
    dlg = win._soften_dialog
    dlg.slider.setValue(40)
    assert all(e.soft for e in seams)
    dlg.slider.setValue(10)                          # back to all hard
    assert not any(e.soft for e in seams)
    assert not vp.history.redo_stack
    assert not vp.history.redo()
    assert not any(e.soft for e in seams)


def test_a_new_selection_starts_a_new_step(win):
    vp = win.viewport
    faces1, seams1 = _cylinder_side(vp.scene.mesh, n=12)
    faces2, seams2 = _cylinder_side(vp.scene.mesh, n=12, x0=5.0)
    vp.scene.version += 1
    vp.scene.select(faces1)
    before = len(vp.history.undo_stack)
    win.show_soften_dialog()
    dlg = win._soften_dialog
    dlg.slider.setValue(40)
    vp.scene.select(faces2)
    dlg.slider.setValue(45)
    assert all(e.soft for e in seams1 + seams2)
    assert len(vp.history.undo_stack) == before + 2
    vp.history.undo()                                # the second only
    assert all(e.soft for e in seams1)
    assert not any(e.soft for e in seams2)


def test_status_counts_the_soft_edges(win):
    vp = win.viewport
    faces, _seams = _cylinder_side(vp.scene.mesh, n=12)
    vp.scene.version += 1
    win.show_soften_dialog()
    dlg = win._soften_dialog
    assert dlg.status.text() == "Select edges or faces first."
    vp.scene.select(faces)
    dlg.refresh()
    assert dlg.status.text() == "0 of 12 edges soft"
    dlg.slider.setValue(40)
    assert dlg.status.text().startswith("12 of 12 edges soft")


def test_coplanar_box_softens_flat_seams(win):
    vp = win.viewport
    m = vp.scene.mesh
    f1 = m.add_face([V(0, 0), V(2, 0), V(2, 2)])
    f2 = m.add_face([V(0, 0), V(2, 2), V(0, 2)])
    diag = m.find_edge(m.vertex_at(V(0, 0)), m.vertex_at(V(2, 2)))
    vp.scene.version += 1
    vp.scene.select([f1, f2])
    win.show_soften_dialog()
    dlg = win._soften_dialog
    dlg.slider.setValue(30)
    assert not diag.soft
    dlg.coplanar.setChecked(True)
    assert diag.soft


# ---- 4. Where it is offered ----------------------------------------------

def test_edit_menu_has_soften_edges(win):
    texts = []
    for top in win.menuBar().actions():
        menu = top.menu()
        if menu is not None:
            texts += [a.text() for a in menu.actions()]
    assert "Soften Edges…" in texts


def test_right_click_offers_soften_edges_between_faces(win, monkeypatch):
    from PySide6.QtCore import QPoint
    from PySide6.QtWidgets import QMenu
    import views.main_window as mw

    opened: list = []

    class _NoModal(QMenu):
        def exec(self, *args, **kwargs):        # noqa: A003 - Qt's name
            opened.append(self)

    def entries(sel):
        opened.clear()
        monkeypatch.setattr(mw, "QMenu", _NoModal)
        win.viewport.scene.select(list(sel))
        win.show_viewport_context_menu(QPoint(0, 0))
        return [a.text() for a in opened[0].actions()]

    vp = win.viewport
    faces, _seams = _cylinder_side(vp.scene.mesh, n=12)
    loose = vp.scene.mesh.add_edge(V(5, 0), V(6, 0))
    vp.scene.version += 1
    assert "Soften Edges…" in entries(faces)
    assert "Soften Edges…" not in entries([loose])


# ---- 5. The selection goes so the result shows -------------------------

def test_a_move_deselects_and_keeps_working_on_the_edges(win):
    """The selection's colour hid the result: the first move takes the
    edges and clears the selection; the next moves still act on them."""
    vp = win.viewport
    faces, seams = _cylinder_side(vp.scene.mesh, n=12)
    vp.scene.version += 1
    vp.scene.select(faces)
    win.show_soften_dialog()
    dlg = win._soften_dialog
    before = len(vp.history.undo_stack)
    dlg.slider.setValue(40)
    assert not vp.scene.selection
    assert all(e.soft for e in seams)
    dlg.slider.setValue(10)                          # nothing selected now
    assert not any(e.soft for e in seams)
    dlg.slider.setValue(35)
    assert all(e.soft for e in seams)
    assert len(vp.history.undo_stack) == before + 1
    assert "Deselected" in dlg.status.text()


def test_closing_the_window_lets_go_of_the_edges(win):
    vp = win.viewport
    faces, seams = _cylinder_side(vp.scene.mesh, n=12)
    vp.scene.version += 1
    vp.scene.select(faces)
    win.show_soften_dialog()
    dlg = win._soften_dialog
    dlg.slider.setValue(40)
    dlg.close()
    win.show_soften_dialog()
    assert dlg.status.text() == "Select edges or faces first."
    dlg.slider.setValue(10)                          # acts on nothing
    assert all(e.soft for e in seams)


# ---- 6. Properties ▸ Soften Edges, under Entity info -----------------------

def _soften_section(win):
    return win.tray.soften.parentWidget()


def test_properties_section_sits_under_entity_info(win):
    stack = win.tray.entity_info.parentWidget().parentWidget()
    order = [stack._layout.itemAt(i).widget()._content
             for i in range(stack._layout.count())]
    assert order.index(win.tray.soften) ==         order.index(win.tray.entity_info) + 1


def test_properties_section_is_always_there(win):
    """The section stays in the palette whatever is selected: it says what
    it acts on, or asks for edges or faces."""
    vp = win.viewport
    faces, seams = _cylinder_side(vp.scene.mesh, n=12)
    loose = vp.scene.mesh.add_edge(V(5, 0), V(6, 0))
    vp.scene.version += 1
    win.tray.on_scene_changed()
    status = win.tray.soften.status
    assert not _soften_section(win).isHidden()       # nothing selected
    assert status.text() == "Select edges or faces first."
    vp.scene.select([loose])
    win.tray.on_scene_changed()
    assert not _soften_section(win).isHidden()       # a loose line: no fold
    assert status.text() == "Select edges or faces first."
    vp.scene.select(faces)
    win.tray.on_scene_changed()
    assert not _soften_section(win).isHidden()
    assert status.text() == "0 of 12 edges soft"


def test_properties_section_softens_and_stays_after_deselecting(win):
    vp = win.viewport
    faces, seams = _cylinder_side(vp.scene.mesh, n=12)
    vp.scene.version += 1
    vp.scene.select(faces)
    win.tray.on_scene_changed()
    panel = win.tray.soften
    before = len(vp.history.undo_stack)
    panel.slider.setValue(40)
    win.tray.on_scene_changed()
    assert not vp.scene.selection
    assert all(e.soft for e in seams)
    assert not _soften_section(win).isHidden()       # still there to tune
    panel.slider.setValue(10)                        # back as it was
    assert not any(e.soft for e in seams)
    assert len(vp.history.undo_stack) == before
    panel.slider.setValue(35)
    assert all(e.soft for e in seams)
    assert len(vp.history.undo_stack) == before + 1
    loose = vp.scene.mesh.add_edge(V(5, 0), V(6, 0))
    vp.scene.select([loose])                         # something else
    win.tray.on_scene_changed()
    assert not _soften_section(win).isHidden()
    assert panel.status.text() == "Select edges or faces first."
    panel.slider.setValue(5)                         # the cylinder let go
    assert all(e.soft for e in seams)


# ---- 7. A new section keeps the order the user dragged ---------------------

def test_new_section_goes_after_the_one_before_it():
    from views.tray import _merge_section_order
    default = ["Info", "Soften", "Materials", "Parts"]
    assert _merge_section_order(["Parts", "Info", "Materials"], default)         == ["Parts", "Info", "Soften", "Materials"]
    assert _merge_section_order(["Materials", "Parts"], default)         == ["Info", "Soften", "Materials", "Parts"]


def test_order_saved_without_the_new_section_is_kept():
    from PySide6.QtCore import QSettings
    from views.tray import _older_section_order
    s = QSettings()
    s.setValue("tray/section_order/Alpha|Beta", ["Beta", "Alpha"])
    s.sync()
    try:
        assert _older_section_order(["Alpha", "Beta", "Gamma"]) ==             ["Beta", "Alpha"]
        assert _older_section_order(["Alpha", "Gamma"]) == []
    finally:
        s.remove("tray/section_order/Alpha|Beta")
