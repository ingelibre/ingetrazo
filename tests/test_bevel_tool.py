# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Fillet 3D bevels: a Ctrl tap walks how the size is read (radius →
distance → width → depth), «0.3p» in the value box shapes the profile,
and one segment is a flat chamfer — one undo step, as before. It bevels
corners (vertices) too. A panel in the corner of the view holds every
setting, box corners included, and follows the keys."""
from __future__ import annotations

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent, QVector3D
from PySide6.QtWidgets import QApplication

from core.orient import is_closed, signed_volume
from tools.base import ToolContext
from tools.fillet import FilletTool
from tests.test_fillet import box, edge_at


@pytest.fixture(scope="module")
def viewport():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    elif not isinstance(app, QApplication):
        pytest.skip("another Qt application flavour is already running")
    from views.viewport import Viewport
    vp = Viewport(None)
    vp.resize(1000, 700)
    vp.camera.set_aspect(1000, 700)
    vp.flash_status = lambda *a, **k: None
    return vp


@pytest.fixture(autouse=True)
def plain_fillet():
    """The tool's settings are class-wide: every test starts from the
    plain fillet and leaves it so."""
    saved = (FilletTool.radius, FilletTool.segments, FilletTool.profile,
             FilletTool.measure, FilletTool.corners, FilletTool.affect,
             FilletTool.shape)
    FilletTool.radius, FilletTool.segments = 0.1, 8
    FilletTool.profile, FilletTool.measure = 0.5, "radius"
    FilletTool.corners, FilletTool.affect = "round", "edges"
    FilletTool.shape = None
    yield
    (FilletTool.radius, FilletTool.segments, FilletTool.profile,
     FilletTool.measure, FilletTool.corners, FilletTool.affect,
     FilletTool.shape) = saved


def _box_scene(vp):
    vp.scene.mesh.clear()
    vp.history.undo_stack.clear()
    vp.history.redo_stack.clear()
    for f in box().faces:
        vp.scene.mesh.add_face(f.vertices)
    vp.scene.version += 1
    return vp.scene.mesh


def _ctx(vp, world):
    return ToolContext(viewport=vp, world=QVector3D(*world), screen=QPointF(0, 0),
                       modifiers=Qt.NoModifier, snap=None)


def _tap_ctrl(vp, tool, alone=True):
    assert tool.on_key(vp, Qt.Key_Control, Qt.ControlModifier)
    vp._ctrl_alone = alone
    return tool.on_key_release(vp, Qt.Key_Control)


def _type(vp, text):
    for ch in text:
        ev = QKeyEvent(QEvent.KeyPress, 0, Qt.NoModifier, ch)
        assert vp._handle_value_key(ev), ch
    ev = QKeyEvent(QEvent.KeyPress, Qt.Key_Return, Qt.NoModifier)
    return vp._handle_value_key(ev)


def test_a_ctrl_tap_walks_the_measures(viewport):
    _box_scene(viewport)
    tool = FilletTool()
    viewport.set_active_tool(tool)
    assert tool.vcb_caption() == "Radius"
    seen = []
    for _ in range(4):
        assert _tap_ctrl(viewport, tool)
        seen.append(FilletTool.measure)
    assert seen == ["offset", "width", "depth", "radius"]
    FilletTool.measure = "width"
    assert tool.vcb_caption() == "Width"
    assert "Width" in tool.status_clause()


def test_ctrl_inside_a_shortcut_leaves_the_measure(viewport):
    _box_scene(viewport)
    tool = FilletTool()
    viewport.set_active_tool(tool)
    assert not _tap_ctrl(viewport, tool, alone=False)      # Ctrl+Z, say
    assert FilletTool.measure == "radius"


def test_the_preview_follows_the_measure(viewport):
    mesh = _box_scene(viewport)
    tool = FilletTool()
    viewport.set_active_tool(tool)
    viewport._hover_edge = edge_at(mesh, (0, 0, 1), (2, 0, 1))
    tool.on_hover(_ctx(viewport, (1, 0, 1)))
    FilletTool.segments = 1
    tool._replan()
    # Radius 0.1 at 90°: the chamfer runs 0.1 back on each face …
    ys = sorted(q.y() for q in tool.preview_faces()[0].vertices)
    assert ys[-1] == pytest.approx(0.1, abs=1e-6)
    # … read as width, 0.1 is the chord, so 0.1/√2 on each face.
    FilletTool.measure = "width"
    tool._replan()
    ys = sorted(q.y() for q in tool.preview_faces()[0].vertices)
    assert ys[-1] == pytest.approx(0.1 / 2 ** 0.5, abs=1e-6)
    assert tool.value_label()[0].startswith("Width 0.100")


def test_a_typed_profile_shapes_the_bevel(viewport):
    mesh = _box_scene(viewport)
    tool = FilletTool()
    viewport.set_active_tool(tool)
    viewport.scene.select([edge_at(mesh, (0, 0, 1), (2, 0, 1))])
    tool.on_activate(viewport)
    _type(viewport, "4s")
    assert FilletTool.segments == 4
    _type(viewport, "0,3p")                   # the comma is a decimal mark
    assert FilletTool.profile == pytest.approx(0.3)
    assert "0.30" in tool.value_label()[0]
    depth = len(viewport.history.undo_stack)
    _type(viewport, "0.2")
    assert len(viewport.history.undo_stack) == depth + 1
    assert len(mesh.faces) == 6 + 4 and is_closed(mesh)
    viewport.history.undo()
    assert len(mesh.faces) == 6 and abs(signed_volume(mesh)) == pytest.approx(2.0)


def test_a_profile_outside_zero_one_only_speaks(viewport):
    _box_scene(viewport)
    said = []
    viewport.flash_status = lambda text, *a, **k: said.append(text)
    tool = FilletTool()
    viewport.set_active_tool(tool)
    assert not tool.on_profile_value(viewport, 1.5)
    assert not tool.on_profile_value(viewport, 0.0)
    assert FilletTool.profile == 0.5
    assert any("profile" in s for s in said)
    viewport.flash_status = lambda *a, **k: None


def test_a_typed_chamfer_by_depth(viewport):
    mesh = _box_scene(viewport)
    tool = FilletTool()
    viewport.set_active_tool(tool)
    viewport.scene.select([edge_at(mesh, (0, 0, 1), (2, 0, 1))])
    tool.on_activate(viewport)
    FilletTool.measure = "depth"
    assert tool.on_segments_value(viewport, 1)
    assert tool.on_value(viewport, 0.2 / 2 ** 0.5)       # t = 0.2 on each face
    assert len(mesh.faces) == 7 and is_closed(mesh)
    assert abs(signed_volume(mesh)) == pytest.approx(2.0 - 0.02 * 2.0, abs=1e-6)


def test_the_value_box_reads_a_profile_suffix():
    from views.viewport import Viewport
    assert Viewport._parse_value_buffer("0.3p") == ("profile", 0.3)
    assert Viewport._parse_value_buffer("0,75p") == ("profile", 0.75)
    assert Viewport._parse_value_buffer("p") is None


def test_p_stays_push_pull_for_other_tools(viewport):
    from tools.line import LineTool
    viewport.set_active_tool(LineTool())
    viewport._set_value_buffer("")
    assert viewport._handle_value_key(QKeyEvent(QEvent.KeyPress, 0, Qt.NoModifier, "2"))
    assert not viewport._handle_value_key(QKeyEvent(QEvent.KeyPress, 0, Qt.NoModifier, "p"))
    viewport._set_value_buffer("")


# ---- The panel -----------------------------------------------------------------

def _panel(vp):
    return vp._bevel_panel


def test_the_panel_shows_with_the_tool_and_goes_with_it(viewport):
    from tools.line import LineTool
    _box_scene(viewport)
    viewport.set_active_tool(FilletTool())
    panel = _panel(viewport)
    assert not panel.isHidden()
    assert panel.parent() is viewport
    assert panel.x() == 12 and panel.geometry().bottom() <= viewport.height()
    viewport.set_active_tool(LineTool())
    assert panel.isHidden()


def test_panel_edits_reach_the_tool_and_the_preview(viewport):
    mesh = _box_scene(viewport)
    tool = FilletTool()
    viewport.set_active_tool(tool)
    viewport.scene.select(list(mesh.edges))
    tool.on_activate(viewport)
    panel = _panel(viewport)
    panel.segments.setValue(3)
    assert FilletTool.segments == 3
    panel.profile.setValue(0.7)
    assert FilletTool.profile == pytest.approx(0.7)
    panel.measure.setCurrentIndex(panel.measure.findData("width"))
    panel._measure_picked(panel.measure.currentIndex())
    assert FilletTool.measure == "width"
    panel.corners.setCurrentIndex(panel.corners.findData("cut"))
    panel._corners_picked(panel.corners.currentIndex())
    assert FilletTool.corners == "cut"
    panel.amount.setText("0.15")
    panel._amount_typed()
    assert FilletTool.radius == pytest.approx(0.15)
    assert len(mesh.faces) == 6                       # nothing applied yet
    # Live preview: 12 strips of 3 plus 8 corners capped by 3 flat faces.
    assert len(tool.preview_faces()) == 12 * 3 + 8 * 3
    depth = len(viewport.history.undo_stack)
    panel.apply.click()
    assert len(viewport.history.undo_stack) == depth + 1
    assert len(mesh.faces) == 6 + 12 * 3 + 8 * 3 and is_closed(mesh)
    viewport.history.undo()
    assert len(mesh.faces) == 6


def test_the_panel_follows_the_keys(viewport):
    _box_scene(viewport)
    tool = FilletTool()
    viewport.set_active_tool(tool)
    panel = _panel(viewport)
    _tap_ctrl(viewport, tool)
    assert panel.measure.currentData() == "offset"
    _type(viewport, "5s")
    assert panel.segments.value() == 5
    _type(viewport, "0,4p")
    assert panel.profile.value() == pytest.approx(0.4)
    _type(viewport, "0.3")                            # no edge: only remembered
    assert panel.amount.text().startswith("0.30")


def test_a_bad_amount_in_the_panel_is_ignored(viewport):
    _box_scene(viewport)
    viewport.set_active_tool(FilletTool())
    panel = _panel(viewport)
    for text in ("abc", "-1", "0"):
        panel.amount.setText(text)
        panel._amount_typed()
        assert FilletTool.radius == pytest.approx(0.1)
    assert panel.amount.text().startswith("0.10")


def test_apply_with_nothing_picked_only_speaks(viewport):
    _box_scene(viewport)
    said = []
    viewport.flash_status = lambda text, *a, **k: said.append(text)
    tool = FilletTool()
    viewport.set_active_tool(tool)
    viewport._hover_edge = None
    tool.hover_edge = None
    depth = len(viewport.history.undo_stack)
    _panel(viewport).apply.click()
    assert len(viewport.history.undo_stack) == depth
    assert any("Click an edge" in s for s in said)
    viewport.flash_status = lambda *a, **k: None


def test_a_click_on_the_panel_does_not_reach_the_model(viewport):
    mesh = _box_scene(viewport)
    tool = FilletTool()
    viewport.set_active_tool(tool)
    viewport._hover_edge = edge_at(mesh, (0, 0, 1), (2, 0, 1))
    panel = _panel(viewport)
    pos = QPointF(2, 2)
    for kind in (QEvent.MouseButtonPress, QEvent.MouseButtonRelease):
        ev = QMouseEvent(kind, pos, panel.mapToGlobal(QPoint(2, 2)),
                         Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
        QApplication.sendEvent(panel, ev)
    assert not tool.sizing and not tool.edges
    assert len(mesh.faces) == 6


# ---- Corners (vertices) ---------------------------------------------------------

def test_hovering_near_an_end_picks_that_corner(viewport):
    mesh = _box_scene(viewport)
    FilletTool.affect = "vertices"
    tool = FilletTool()
    viewport.set_active_tool(tool)
    viewport._hover_edge = edge_at(mesh, (0, 0, 1), (2, 0, 1))
    tool.on_hover(_ctx(viewport, (1.8, 0, 1)))
    assert tool.hover_vertex is mesh.vertex_at(QVector3D(2, 0, 1))
    assert tool.vcb_caption() == "Distance"
    assert "Vertices" in tool.status_clause()
    assert len(tool.preview_faces()) == 8 * 8          # the round cap
    tool.on_click(_ctx(viewport, (1.8, 0, 1)))
    assert tool.sizing and tool.edges == [tool.hover_vertex]
    tool.on_hover(_ctx(viewport, (1.75, 0, 1)))       # 0.25 from the corner
    assert FilletTool.radius == pytest.approx(0.25)
    assert tool.value_label()[0].startswith("Distance 0.250")
    depth = len(viewport.history.undo_stack)
    tool.on_click(_ctx(viewport, (1.75, 0, 1)))
    assert len(viewport.history.undo_stack) == depth + 1
    assert len(mesh.faces) == 6 + 64 and is_closed(mesh)
    viewport.history.undo()
    assert len(mesh.faces) == 6 and len(mesh.edges) == 12


def test_a_selected_box_bevels_its_eight_corners(viewport):
    mesh = _box_scene(viewport)
    FilletTool.affect = "vertices"
    viewport.scene.select(list(mesh.faces) + list(mesh.edges))
    tool = FilletTool()
    viewport.set_active_tool(tool)
    assert len(tool.edges) == 8
    assert tool.on_segments_value(viewport, 1)
    assert tool.on_value(viewport, 0.1)
    assert len(mesh.faces) == 6 + 8 and is_closed(mesh)
    assert abs(signed_volume(mesh)) == pytest.approx(2.0 - 8 * 0.1 ** 3 / 6, abs=1e-6)


def test_ctrl_leaves_the_measure_while_bevelling_corners(viewport):
    _box_scene(viewport)
    FilletTool.affect = "vertices"
    tool = FilletTool()
    viewport.set_active_tool(tool)
    assert _tap_ctrl(viewport, tool)
    assert FilletTool.measure == "radius"


def test_the_panel_switches_to_corners_and_carries_the_pick(viewport):
    mesh = _box_scene(viewport)
    tool = FilletTool()
    viewport.set_active_tool(tool)
    viewport.scene.select([edge_at(mesh, (0, 0, 1), (2, 0, 1))])
    tool.on_activate(viewport)
    panel = _panel(viewport)
    assert panel.measure.isEnabled() and panel.corners.isEnabled()
    panel.affect.setCurrentIndex(panel.affect.findData("vertices"))
    panel._affect_picked(panel.affect.currentIndex())
    assert FilletTool.affect == "vertices"
    assert {tuple((v.position.x(), v.position.y(), v.position.z()))
            for v in tool.edges} == {(0.0, 0.0, 1.0), (2.0, 0.0, 1.0)}
    assert not panel.measure.isEnabled() and not panel.corners.isEnabled()
    panel.affect.setCurrentIndex(panel.affect.findData("edges"))
    panel._affect_picked(panel.affect.currentIndex())
    assert FilletTool.affect == "edges" and not tool.edges
    assert panel.measure.isEnabled()


def test_a_refused_corner_only_speaks(viewport):
    mesh = _box_scene(viewport)
    said = []
    viewport.flash_status = lambda text, *a, **k: said.append(text)
    FilletTool.affect = "vertices"
    tool = FilletTool()
    viewport.set_active_tool(tool)
    viewport._hover_edge = edge_at(mesh, (0, 0, 1), (2, 0, 1))
    tool.on_hover(_ctx(viewport, (0.1, 0, 1)))
    tool.on_click(_ctx(viewport, (0.1, 0, 1)))
    assert tool.on_value(viewport, 1.5)               # longer than the edges
    assert len(mesh.faces) == 6
    assert any("too large" in s for s in said)
    viewport.flash_status = lambda *a, **k: None


def test_the_profile_shape_picks_round_flat_or_custom(viewport):
    mesh = _box_scene(viewport)
    tool = FilletTool()
    viewport.set_active_tool(tool)
    panel = _panel(viewport)
    assert panel.shape.currentData() == "round" and not panel.profile.isEnabled()
    panel.shape.setCurrentIndex(panel.shape.findData("flat"))
    panel._shape_picked(panel.shape.currentIndex())
    assert FilletTool.profile == pytest.approx(0.25)
    assert not panel.profile.isEnabled()
    panel.shape.setCurrentIndex(panel.shape.findData("custom"))
    panel._shape_picked(panel.shape.currentIndex())
    assert panel.profile.isEnabled() and FilletTool.profile == pytest.approx(0.25)
    panel.profile.setValue(0.7)
    assert FilletTool.profile == pytest.approx(0.7)
    panel.shape.setCurrentIndex(panel.shape.findData("round"))
    panel._shape_picked(panel.shape.currentIndex())
    assert FilletTool.profile == pytest.approx(0.5) and not panel.profile.isEnabled()
    _type(viewport, "0,3p")                           # a typed number is custom
    assert panel.shape.currentData() == "custom"


def test_a_flat_profile_with_and_without_the_corner_fill(viewport):
    for corners, per_corner in (("round", 9), ("cut", 3)):
        mesh = _box_scene(viewport)
        tool = FilletTool()
        viewport.set_active_tool(tool)
        viewport.scene.select(list(mesh.edges))
        tool.on_activate(viewport)
        panel = _panel(viewport)
        panel.shape.setCurrentIndex(panel.shape.findData("flat"))
        panel._shape_picked(panel.shape.currentIndex())
        panel.segments.setValue(3)
        panel.corners.setCurrentIndex(panel.corners.findData(corners))
        panel._corners_picked(panel.corners.currentIndex())
        panel.amount.setText("0.1")
        panel._amount_typed()
        panel.apply.click()
        assert len(mesh.faces) == 6 + 12 * 3 + 8 * per_corner and is_closed(mesh)


def _pick_shape(panel, key):
    panel.shape.setCurrentIndex(panel.shape.findData(key))
    panel._shape_picked(panel.shape.currentIndex())


def test_a_drawn_profile_from_the_panel(viewport):
    mesh = _box_scene(viewport)
    tool = FilletTool()
    viewport.set_active_tool(tool)
    viewport.scene.select([edge_at(mesh, (0, 0, 1), (2, 0, 1))])
    tool.on_activate(viewport)
    panel = _panel(viewport)
    for key in ("steps", "supports", "cornice", "crown"):
        assert panel.shape.findData(key) >= 0
    _pick_shape(panel, "steps")
    assert FilletTool.shape == "steps"
    assert not panel.profile.isEnabled() and panel.corners.isEnabled()
    assert not panel.editor.isHidden()                # the outline, editable
    panel.segments.setValue(6)
    assert len(tool.preview_faces()) == 6               # one strip per step
    assert "Steps" in tool.value_label()[0]
    panel.amount.setText("0.2")
    panel._amount_typed()
    panel.apply.click()
    assert len(mesh.faces) == 6 + 6 and is_closed(mesh)
    assert abs(signed_volume(mesh)) == pytest.approx(2.0 - (1 - 1 / 3) * 0.04 * 2, abs=1e-6)


def test_a_typed_profile_or_round_leaves_the_drawn_one(viewport):
    _box_scene(viewport)
    tool = FilletTool()
    viewport.set_active_tool(tool)
    panel = _panel(viewport)
    _pick_shape(panel, "cornice")
    assert FilletTool.shape == "cornice"
    _type(viewport, "0,3p")
    assert FilletTool.shape is None and panel.shape.currentData() == "custom"
    _pick_shape(panel, "crown")
    _pick_shape(panel, "round")
    assert FilletTool.shape is None and FilletTool.profile == pytest.approx(0.5)
    assert panel.corners.isEnabled()


def test_drawn_profiles_are_for_edges_only(viewport):
    _box_scene(viewport)
    tool = FilletTool()
    viewport.set_active_tool(tool)
    panel = _panel(viewport)
    _pick_shape(panel, "steps")
    tool.set_affect(viewport, "vertices")
    assert FilletTool.shape is None                     # switching lets it go
    said = []
    viewport.flash_status = lambda text, *a, **k: said.append(text)
    _pick_shape(panel, "crown")
    assert FilletTool.shape is None
    assert any("edges only" in s for s in said)
    viewport.flash_status = lambda *a, **k: None


def test_the_editor_draws_the_profile_the_tool_uses(viewport):
    mesh = _box_scene(viewport)
    tool = FilletTool()
    viewport.set_active_tool(tool)
    viewport.scene.select(list(mesh.edges))
    tool.on_activate(viewport)
    panel = _panel(viewport)
    assert panel.editor.isHidden()                    # round: nothing to draw
    _pick_shape(panel, "cornice")
    assert not panel.editor.isHidden()
    assert len(panel.editor.points) == 13             # the cornice's own points
    # Moving one point makes the outline the user's own.
    ed = panel.editor
    x, y, _s = ed.points[6]
    start = ed.to_screen(x, y)
    end = ed.to_screen(x - 0.1, y + 0.05)
    for kind, pos, btn in ((QEvent.MouseButtonPress, start, Qt.LeftButton),
                           (QEvent.MouseMove, end, Qt.NoButton),
                           (QEvent.MouseButtonRelease, end, Qt.LeftButton)):
        QApplication.sendEvent(ed, QMouseEvent(kind, pos, ed.mapToGlobal(pos.toPoint()),
                                               btn, btn, Qt.NoModifier))
    assert isinstance(FilletTool.shape, tuple)
    assert FilletTool.shape[6][0] == pytest.approx(x - 0.1, abs=0.01)
    assert panel.shape.currentData() == "drawn"
    depth = len(viewport.history.undo_stack)
    panel.amount.setText("0.15")
    panel._amount_typed()
    panel.apply.click()
    assert len(viewport.history.undo_stack) == depth + 1
    assert is_closed(mesh) and all(len(e.faces) == 2 for e in mesh.edges)


def test_choosing_drawn_starts_from_the_current_outline(viewport):
    _box_scene(viewport)
    tool = FilletTool()
    viewport.set_active_tool(tool)
    panel = _panel(viewport)
    _pick_shape(panel, "steps")
    _pick_shape(panel, "drawn")
    assert isinstance(FilletTool.shape, tuple)
    assert all(not sm for _x, _y, sm in FilletTool.shape)   # steps are corners
    assert not panel.editor.isHidden()


# ---- The profile editor on its own -------------------------------------------

def _click(ed, x, y, kind=QEvent.MouseButtonPress, button=Qt.LeftButton):
    pos = ed.to_screen(x, y)
    ev = QMouseEvent(kind, pos, ed.mapToGlobal(pos.toPoint()), button, button,
                     Qt.NoModifier)
    QApplication.sendEvent(ed, ev)


def test_editor_adds_toggles_and_removes_points(viewport):
    from views.bevel_profile_editor import ProfileEditor
    ed = ProfileEditor()
    got = []
    ed.edited.connect(got.append)
    ed.set_points([(1.0, 0.0, False), (0.0, 1.0, False)], 8)
    _click(ed, 0.6, 0.6, QEvent.MouseButtonDblClick)        # add
    assert len(ed.points) == 3 and ed.points[1][2] is True
    assert ed.points[1][:2] == pytest.approx((0.6, 0.6), abs=0.01)
    _click(ed, 0.6, 0.6, QEvent.MouseButtonDblClick)        # smooth → corner
    assert ed.points[1][2] is False
    _click(ed, 0.6, 0.6, button=Qt.RightButton)             # remove
    assert len(ed.points) == 2
    assert len(got) == 3 and all(p[0] == (1.0, 0.0, False) for p in got)


def test_editor_keeps_the_ends_on_their_faces(viewport):
    from views.bevel_profile_editor import ProfileEditor
    ed = ProfileEditor()
    ed.set_points([(1.0, 0.0, False), (0.5, 0.5, True), (0.0, 1.0, False)], 8)
    _click(ed, 1.0, 0.0, button=Qt.RightButton)             # an end: stays
    _click(ed, 1.0, 0.0)                                    # no drag either
    _click(ed, 0.7, 0.2, QEvent.MouseMove, Qt.NoButton)
    _click(ed, 0.7, 0.2, QEvent.MouseButtonRelease)
    assert ed.points[0] == (1.0, 0.0, False) and len(ed.points) == 3
    # A dragged point stays inside the square.
    _click(ed, 0.5, 0.5)
    pos = ed.to_screen(1.5, -0.5)
    QApplication.sendEvent(ed, QMouseEvent(QEvent.MouseMove, pos, ed.mapToGlobal(pos.toPoint()),
                                           Qt.NoButton, Qt.LeftButton, Qt.NoModifier))
    _click(ed, 1.0, 0.0, QEvent.MouseButtonRelease)
    assert ed.points[1][:2] == pytest.approx((1.0, 0.0))


def test_double_click_adds_corner_points_too(viewport):
    from views.bevel_profile_editor import ProfileEditor
    ed = ProfileEditor()
    ed.set_points([(1.0, 0.0, False), (0.0, 1.0, False)], 8)
    ed.new_smooth = False                                   # «Corner point»
    _click(ed, 0.6, 0.6, QEvent.MouseButtonDblClick)
    assert ed.points[1][2] is False
    # Shift adds the other kind.
    pos = ed.to_screen(0.3, 0.8)
    QApplication.sendEvent(ed, QMouseEvent(QEvent.MouseButtonDblClick, pos,
                                           ed.mapToGlobal(pos.toPoint()), Qt.LeftButton,
                                           Qt.LeftButton, Qt.ShiftModifier))
    assert [p[2] for p in ed.points] == [False, False, True, False]


def test_the_panel_picks_the_kind_of_new_points(viewport):
    _box_scene(viewport)
    tool = FilletTool()
    viewport.set_active_tool(tool)
    panel = _panel(viewport)
    assert panel.point_kind.isHidden()
    _pick_shape(panel, "drawn")
    assert not panel.point_kind.isHidden() and panel.smooth_point.isChecked()
    panel.corner_point.click()
    assert panel.editor.new_smooth is False and not panel.smooth_point.isChecked()
    before = len(FilletTool.shape)
    _click(panel.editor, 0.85, 0.85, QEvent.MouseButtonDblClick)
    assert len(FilletTool.shape) == before + 1
    assert any(not sm for x, y, sm in FilletTool.shape[1:-1])
    panel.smooth_point.click()
    assert panel.editor.new_smooth is True
