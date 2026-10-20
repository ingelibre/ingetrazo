# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The segment count of a circle, arc or polygon, changed after it is
drawn (Entity Info). The «24s» of the tools only reached the shape just
drawn; any other had to be erased and drawn again."""
from __future__ import annotations

import math
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import QPointF, Qt  # noqa: E402
from PySide6.QtGui import QVector3D as V  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from core.curve_segments import ResegmentCurveCommand, read_curve  # noqa: E402
from tools.base import ToolContext  # noqa: E402
from tools.circle import CircleTool, PolygonTool  # noqa: E402
from tools.rectangle import RectangleTool  # noqa: E402

_app = QApplication.instance() or QApplication([])


@pytest.fixture
def viewport():
    from views.viewport import Viewport
    vp = Viewport(None)
    vp.resize(1000, 700)
    vp.camera.set_aspect(1000, 700)
    vp.flash_status = lambda *a, **k: None
    return vp


def _draw(vp, tool, *points):
    tool.on_activate(vp)
    for p in points:
        tool.on_click(ToolContext(viewport=vp, world=p, screen=QPointF(0, 0),
                                  modifiers=Qt.NoModifier, snap=None))


def _curve_edge(mesh):
    return next(e for e in mesh.edges if e.curve is not None)


def _loops(mesh):
    return sorted((len(f.vertices), sorted(len(h) for h in f.holes))
                  for f in mesh.faces)


def _arc_with_chord(mesh, n=4, r=2.0):
    """A half disc: an arc of ``n`` segments closed by its diameter."""
    pts = [V(r * math.cos(math.pi * k / n), r * math.sin(math.pi * k / n), 0)
           for k in range(n + 1)]
    face = mesh.add_face(pts)
    mesh.tag_curve(pts, closed=False)
    return face, pts


@pytest.mark.parametrize("cls,before,after", [(CircleTool, 24, 8),
                                               (CircleTool, 24, 48),
                                               (PolygonTool, 6, 8)])
def test_a_shape_takes_a_new_count_in_place(viewport, cls, before, after):
    _draw(viewport, cls(), V(1, 1, 0), V(3, 1, 0))
    mesh = viewport.scene.mesh
    shape = read_curve(mesh, _curve_edge(mesh))
    assert shape.closed and shape.flat and shape.segments == before
    steps = len(viewport.history.undo_stack)
    viewport.history.execute(ResegmentCurveCommand(_curve_edge(mesh), after))
    assert len(viewport.history.undo_stack) == steps + 1
    assert _loops(mesh) == [(after, [])]
    radii = {round((v.position - V(1, 1, 0)).length(), 6)
             for v in mesh.vertices}
    assert radii == {2.0}
    assert len({e.curve for e in mesh.edges}) == 1     # still one curve
    assert len(viewport.scene.selection) == after      # and it stays picked
    viewport.history.undo()
    assert _loops(mesh) == [(before, [])]
    viewport.history.redo()
    assert _loops(mesh) == [(after, [])]


def test_the_hole_it_cut_follows_and_paint_stays(viewport):
    _draw(viewport, RectangleTool(), V(0, 0, 0), V(10, 10, 0))
    _draw(viewport, CircleTool(), V(5, 5, 0), V(7, 5, 0))
    mesh = viewport.scene.mesh
    for f in mesh.faces:
        f.attrs["color"] = (0.1, 0.2, 0.3) if len(f.vertices) == 4 \
            else (0.9, 0.8, 0.7)
    viewport.history.execute(ResegmentCurveCommand(_curve_edge(mesh), 12))
    assert _loops(mesh) == [(4, [12]), (12, [])]
    colors = {len(f.vertices): f.attrs.get("color") for f in mesh.faces}
    assert colors == {4: (0.1, 0.2, 0.3), 12: (0.9, 0.8, 0.7)}
    viewport.history.undo()
    assert _loops(mesh) == [(4, [24]), (24, [])]


def test_an_arc_keeps_its_ends_and_its_face(viewport):
    mesh = viewport.scene.mesh
    face, pts = _arc_with_chord(mesh)
    face.attrs["color"] = (0.5, 0.5, 0.5)
    edge = _curve_edge(mesh)
    shape = read_curve(mesh, edge)
    assert not shape.closed and shape.segments == 4
    assert shape.sweep == pytest.approx(math.pi)
    viewport.history.execute(ResegmentCurveCommand(edge, 10))
    assert _loops(mesh) == [(11, [])]
    assert mesh.vertex_at(pts[0]) is not None
    assert mesh.vertex_at(pts[-1]) is not None
    assert sum(1 for e in mesh.edges if e.curve is not None) == 10
    assert mesh.faces[0].attrs["color"] == (0.5, 0.5, 0.5)
    assert mesh.faces[0].area() == pytest.approx(
        0.5 * 10 * 4.0 * math.sin(math.pi / 10))


def test_an_uneven_stroke_is_not_a_curve_to_rebuild(viewport):
    mesh = viewport.scene.mesh
    pts = [V(0, 0, 0), V(1, 0.2, 0), V(1.5, 1, 0), V(3, 1.1, 0)]
    for a, b in zip(pts, pts[1:]):
        mesh.add_edge(a, b)
    mesh.tag_curve(pts, closed=False)
    assert read_curve(mesh, _curve_edge(mesh)) is None


def test_a_pushed_cylinder_is_left_alone(viewport):
    _draw(viewport, CircleTool(), V(0, 0, 0), V(2, 0, 0))
    mesh = viewport.scene.mesh
    ring = [v.position for v in mesh.faces[0].loop]
    for a, b in zip(ring, ring[1:] + ring[:1]):
        mesh.add_face([a, b, b + V(0, 0, 3), a + V(0, 0, 3)])
    edge = _curve_edge(mesh)
    shape = read_curve(mesh, edge)
    assert shape is not None and not shape.flat
    faces = len(mesh.faces)
    steps = len(viewport.history.undo_stack)
    viewport.history.execute(ResegmentCurveCommand(edge, 8))
    assert len(viewport.history.undo_stack) == steps     # rejected
    assert len(mesh.faces) == faces


# ---- The field in Entity Info ---------------------------------------------
@pytest.fixture
def window():
    from views.main_window import MainWindow
    w = MainWindow()
    w.show()
    yield w
    w._saved_version = w.viewport.scene.version   # no "save?" modal
    w.close()


def _panel(window):
    from views.tray import EntityInfoPanel
    return window.findChild(EntityInfoPanel)


def test_the_field_shows_for_one_curve_and_rebuilds_it(window):
    vp = window.viewport
    _draw(vp, PolygonTool(), V(0, 0, 0), V(2, 0, 0))
    mesh = vp.scene.mesh
    panel = _panel(window)
    cid = _curve_edge(mesh).curve
    vp.scene.selection.update(e for e in mesh.edges if e.curve == cid)
    panel.refresh()
    assert panel._seg_box.isVisible() and panel._seg_box.isEnabled()
    assert panel._seg_caption.text() == "Sides:"
    assert panel._seg_box.value() == 6
    assert not panel._name_edit.isVisible()
    panel._seg_box.setValue(9)
    assert _loops(mesh) == [(9, [])]
    assert panel._seg_box.value() == 9
    vp.history.undo()
    panel.refresh()
    assert panel._seg_box.value() == 6


def test_the_field_hides_for_a_plain_edge_or_a_face(window):
    vp = window.viewport
    _draw(vp, RectangleTool(), V(0, 0, 0), V(4, 4, 0))
    mesh = vp.scene.mesh
    panel = _panel(window)
    vp.scene.selection.add(mesh.edges[0])
    panel.refresh()
    assert not panel._seg_box.isVisible()
    vp.scene.selection.clear()
    vp.scene.selection.add(mesh.faces[0])
    panel.refresh()
    assert not panel._seg_box.isVisible()


def test_an_arc_reads_segments(window):
    vp = window.viewport
    _arc_with_chord(vp.scene.mesh, n=5)
    mesh = vp.scene.mesh
    panel = _panel(window)
    cid = _curve_edge(mesh).curve
    vp.scene.selection.update(e for e in mesh.edges if e.curve == cid)
    panel.refresh()
    assert panel._seg_caption.text() == "Segments:"
    assert panel._seg_box.value() == 5
    assert panel._seg_box.minimum() == 2


def test_a_curve_is_described_by_its_shape(window):
    vp = window.viewport
    _draw(vp, CircleTool(), V(0, 0, 0), V(2, 0, 0))
    mesh = vp.scene.mesh
    panel = _panel(window)
    cid = _curve_edge(mesh).curve
    text = panel._describe([e for e in mesh.edges if e.curve == cid])
    assert text.startswith("<b>Circle</b>")
    assert "Radius" in text and "Diameter" in text and "Perimeter" in text
    vp.history.execute(ResegmentCurveCommand(_curve_edge(mesh), 6))
    text = panel._describe([e for e in mesh.edges if e.curve == cid])
    assert text.startswith("<b>Polygon</b>") and "Side" in text


def test_labels_are_muted_and_values_left_alone():
    from views.tray import EntityInfoPanel
    out = EntityInfoPanel._styled("<b>Face</b><br>Area: 1 m²<br>Material: —")
    assert out.startswith("<b>Face</b><br><span style=")
    assert "Area:</span> 1 m²" in out and "Material:</span> —" in out


def test_a_painted_face_shows_a_swatch_and_its_code():
    from views.tray import EntityInfoPanel

    class _Face:
        attrs = {"color": (0.85, 0.45, 0.2)}
    text = EntityInfoPanel._material_of(_Face())
    assert "#D97333" in text and "■" in text


@pytest.mark.parametrize("offset,r", [(1000.0, 0.05), (10000.0, 0.5),
                                      (100000.0, 2.0)])
def test_a_small_circle_far_from_the_origin_is_still_read(offset, r):
    """Positions are single precision: the centre is worked out from the
    first vertex, and the rounding of far coordinates is allowed for."""
    from core.mesh import Mesh
    mesh = Mesh()
    c = V(offset, offset, 0)
    pts = [c + V(math.cos(2 * math.pi * k / 24),
                 math.sin(2 * math.pi * k / 24), 0) * r for k in range(24)]
    mesh.add_face(pts)
    mesh.tag_curve(pts, closed=True)
    shape = read_curve(mesh, _curve_edge(mesh))
    assert shape is not None and shape.radius == pytest.approx(r, rel=1e-2)
