# SPDX-License-Identifier: GPL-3.0-or-later
"""A section placed while editing a group must leave a neighbouring group visible."""
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QMatrix4x4, QVector3D as V
import pytest
from PySide6.QtWidgets import QApplication

from core.group import Group
from core.scene import Scene
from core.section import active_scoped_cut
from formats.igz import load_into, save_scene
from tools.base import ToolContext
from tools.section import SectionPlaneTool
from views.viewport import Viewport


@pytest.mark.parametrize("component", [False, True])
def test_section_plane_placed_in_a_group_leaves_its_neighbour_visible(monkeypatch, tmp_path, component):
    app = QApplication.instance() or QApplication([])
    vp = Viewport(None)
    monkeypatch.setattr(vp, "flash_status", lambda *_: None)
    scene = vp.scene
    owner, neighbour = Group(name="Cut me"), Group(name="Leave me whole")
    for group, x in ((owner, 0), (neighbour, 4)):
        group.mesh.add_face([V(x - 1, -1, 3), V(x + 1, -1, 3),
                             V(x + 1, 1, 3), V(x - 1, 1, 3)])
    if component:
        owner.xform = QMatrix4x4()
        neighbour.mesh = owner.mesh
        neighbour.xform = QMatrix4x4()
        neighbour.xform.translate(4, 0, 0)
        assert owner.is_component() and neighbour.is_component()
    scene.groups.extend((owner, neighbour))
    scene.begin_group_edit(owner)
    tool = SectionPlaneTool()
    tool.on_click(ToolContext(vp, V(0, 0, 1.5), QPointF(), Qt.NoModifier, None))
    scene.end_group_edit()

    vp.resize(900, 680)
    vp.camera.set_view("top")
    vp.camera.fit_box(*scene.bounds())
    owner_px = vp._world_to_pixel(V(0, 0, 3))
    neighbour_px = vp._world_to_pixel(V(4, 0, 3))
    scene.show_section_cuts = False
    assert vp.pick_face_any(*owner_px)[1] is owner
    assert vp.pick_face_any(*neighbour_px)[1] is neighbour
    scene.show_section_cuts = True
    assert vp.pick_face_any(*owner_px) == (None, None)
    assert vp.pick_face_any(*neighbour_px)[1] is neighbour
    assert vp._occluded_many([V(0, 0, 1), V(4, 0, 1)]) == [False, True]

    vp._frame_scoped_cut = active_scoped_cut(scene)
    owner_chunk = vp._group_chunk(owner)
    neighbour_chunk = vp._group_chunk(neighbour)
    assert owner_chunk["vcol"] and owner_chunk["edges"]
    assert not vp._scoped_draw_chunk(owner, owner_chunk)["vcol"]
    assert not vp._scoped_draw_chunk(owner, owner_chunk, edges_only=True)["edges"]
    assert vp._scoped_draw_chunk(neighbour, neighbour_chunk) is neighbour_chunk

    target = tmp_path / "section.igz"
    save_scene(scene, target)
    reopened = Scene()
    load_into(reopened, target)
    loaded_owner, loaded_neighbour = reopened.groups
    cut = active_scoped_cut(reopened)
    assert cut.hidden(V(0, 0, 3), loaded_owner)
    assert not cut.hidden(V(4, 0, 3), loaded_neighbour)
    assert "active" not in reopened.active_section().to_dict()

    from core.history import MoveGroupCommand, RotateGroupCommand, ScaleGroupCommand
    vp.history.execute(MoveGroupCommand(owner, V(0, 0, 2)))
    assert scene.active_section().point.z() == 3.5
    assert vp.history.undo()
    assert scene.active_section().point.z() == 1.5
    vp.history.execute(RotateGroupCommand(owner, V(), V(0, 1, 0), 90))
    assert (scene.active_section().normal - V(1, 0, 0)).length() < 1e-5
    assert vp.history.undo()
    vp.history.execute(ScaleGroupCommand(owner, V(), 2.0))
    assert abs(scene.active_section().point.z() - 3.0) < 1e-5
    assert vp.history.undo()
    assert abs(scene.active_section().point.z() - 1.5) < 1e-5


def test_cut_chords_leave_out_the_neighbour(monkeypatch):
    app = QApplication.instance() or QApplication([])
    vp = Viewport(None)
    monkeypatch.setattr(vp, "flash_status", lambda *_: None)
    scene = vp.scene
    owner, neighbour = Group(), Group()
    for group, x in ((owner, 0), (neighbour, 4)):
        group.mesh.add_face([V(x - 1, 0, 0), V(x + 1, 0, 0),
                             V(x + 1, 0, 3), V(x - 1, 0, 3)])
    scene.groups.extend([owner, neighbour])
    scene.begin_group_edit(owner)
    SectionPlaneTool().on_click(ToolContext(vp, V(0, 0, 1.5), QPointF(),
                                           Qt.NoModifier, None))
    scene.end_group_edit()
    segments = vp._section_cut_segments(scene.active_section())
    assert segments is not None
    assert (abs(segments[..., 0]) <= 1).all()
    assert (segments[..., 2] == 1.5).all()
    assert max(p.x() for p in vp.section_plane_frame(scene.active_section())) < 2.0


def test_scoped_edge_inference_stops_at_plane(monkeypatch):
    app = QApplication.instance() or QApplication([])
    vp = Viewport(None)
    monkeypatch.setattr(vp, "flash_status", lambda *_: None)
    scene = vp.scene
    owner, neighbour = Group(), Group()
    owner.mesh.add_edge(V(0, 0, 0), V(0, 0, 3))
    neighbour.mesh.add_edge(V(4, 0, 0), V(4, 0, 3))
    scene.groups.extend([owner, neighbour])
    scene.begin_group_edit(owner)
    SectionPlaneTool().on_click(ToolContext(vp, V(0, 0, 1.5), QPointF(),
                                           Qt.NoModifier, None))
    scene.end_group_edit()

    vp.resize(900, 680)
    vp.camera.set_view("front")
    vp.camera.fit_box(*scene.bounds())

    def top_for(group, x):
        pos = vp._world_to_pixel(V(x, 0, 2))
        snap_scene = vp._snap_scene(*pos)
        edge, = [e for e in snap_scene.edges if getattr(e, "group", None) is group]
        return max(edge.a.z(), edge.b.z())

    assert top_for(owner, 0) == 1.5
    assert top_for(neighbour, 4) == 3.0


def test_multiple_component_cuts_toggle_and_round_trip(monkeypatch, tmp_path):
    app = QApplication.instance() or QApplication([])
    vp = Viewport(None)
    monkeypatch.setattr(vp, "flash_status", lambda *_: None)
    scene = vp.scene
    original = Group()
    original.mesh.add_edge(V(0, 0, 0), V(0, 0, 3))
    original.xform = QMatrix4x4()
    copies = [original]
    for x in (4, 8):
        copy = Group(mesh=original.mesh)
        copy.xform = QMatrix4x4()
        copy.xform.translate(x, 0, 0)
        copies.append(copy)
    scene.groups.extend(copies)

    originals = []
    for owner, x, height in ((original, 0, 1.5), (copies[1], 4, 2.25)):
        scene.begin_group_edit(owner)
        SectionPlaneTool().on_click(ToolContext(vp, V(x, 0, height), QPointF(),
                                               Qt.NoModifier, None))
        scene.end_group_edit()
        originals.append(scene.section_planes[-1])

    first, second = originals
    assert scene.active_sections() == [first, second]
    cut = active_scoped_cut(scene)
    assert cut.hidden(V(0, 0, 2), original)
    assert not cut.hidden(V(4, 0, 2), copies[1])
    assert cut.hidden(V(4, 0, 2.5), copies[1])
    assert not cut.hidden(V(8, 0, 3), copies[2])

    from core.history import SetActiveSectionCommand
    vp.history.execute(SetActiveSectionCommand(first, False))
    assert scene.active_sections() == [second]
    assert vp.history.undo()
    assert scene.active_sections() == [first, second]

    target = tmp_path / "multiple-sections.igz"
    save_scene(scene, target)
    reopened = Scene()
    load_into(reopened, target)
    assert [plane.owner_uid for plane in reopened.active_sections()] == [
        reopened.groups[0].uid, reopened.groups[1].uid,
    ]


def test_more_than_seven_active_planes_clip_the_same_placement():
    from core.section import SectionPlane

    scene = Scene()
    group = Group()
    scene.groups.append(group)
    for offset in range(10):
        plane = SectionPlane(V(0, 0, 10 - offset), V(0, 0, 1), active=True)
        plane.owner_uid = group.uid
        scene.section_planes.append(plane)
    cut = active_scoped_cut(scene)
    assert len(cut.cuts) == 10
    assert cut.clip_segment(V(), V(0, 0, 10), group) == (V(), V(0, 0, 1))
