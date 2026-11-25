# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import pytest
from PySide6.QtGui import QMatrix4x4, QVector3D as V
from PySide6.QtWidgets import QApplication

from core.group import Group
from core.section import SectionPlane
from formats import clip
from tools.move import MoveTool
from tools.paste import PasteTool
from views.viewport import Viewport


@pytest.mark.parametrize("component", [False, True])
@pytest.mark.parametrize("operation", ["move", "clipboard"])
def test_copy_carries_scoped_planes_and_undo_removes_only_copies(
        monkeypatch, component, operation):
    app = QApplication.instance() or QApplication([])
    vp = Viewport(None)
    scene = vp.scene
    source = Group()
    source.mesh.add_edge(V(), V(0, 0, 3))
    if component:
        source.xform = QMatrix4x4()
    scene.groups.append(source)
    plane = SectionPlane(V(0, 0, 1), V(0, 0, 1), active=True)
    plane.owner_uid = source.uid
    plane.fill = {"pattern": "solid"}
    inactive = SectionPlane(V(0, 0, 2), V(0, 0, 1), hidden=True)
    inactive.owner_uid = source.uid
    root = SectionPlane(V(0, 0, 20), V(0, 0, 1), active=True)
    scene.section_planes.extend([plane, inactive, root])
    delta = V(4, 0, 2)

    if operation == "move":
        tool = MoveTool()
        tool._groups = [source]
        vp.history.execute(tool._make_copy_builder(scene)([delta]))
    else:
        monkeypatch.setattr(clip, "publish", lambda _: None)
        scene.select([source])
        assert vp.copy_selection()
        template = clip.decode(clip.encode(vp.clipboard))
        tool = PasteTool()
        tool._clip = template
        assert tool.stamp(vp, delta)

    copied = scene.groups[-1]
    first, second = scene.section_planes[3:]
    assert first.owner_uid == second.owner_uid == copied.uid != source.uid
    assert first.uid != plane.uid and second.uid != inactive.uid
    assert first.point == plane.point + delta
    assert second.point == inactive.point + delta
    assert first.active and not second.active and second.hidden
    assert first.fill == plane.fill and first.fill is not plane.fill
    assert vp.history.undo()
    assert scene.section_planes == [plane, inactive, root]
    assert scene.groups == [source]
    assert vp.history.redo()
    assert scene.section_planes == [plane, inactive, root, first, second]
    assert scene.groups == [source, copied]


def test_nested_scope_maps_to_the_new_child():
    from core.group import copy_group
    from core.section import copy_scoped_sections

    source, child = Group(), Group()
    source.adopt([child])
    clone = copy_group(source, V(4, 0, 2))
    plane = SectionPlane(V(0, 0, 1), V(0, 0, 1), active=True)
    plane.owner_uid = child.uid
    copied, = copy_scoped_sections([plane], source, clone, V(4, 0, 2))
    assert copied.owner_uid == clone.children[0].uid != child.uid
    assert copied.point == V(4, 0, 3)
