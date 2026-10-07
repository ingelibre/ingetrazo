"""Object locks survive storage and protect edits without preventing unlock."""
import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QMatrix4x4, QVector3D
from PySide6.QtWidgets import QApplication
from core.group import Group, copy_group
from core.history import (CompoundCommand, DeleteGroupCommand, ExplodeGroupCommand,
                          FlipGroupsCommand, History, MoveGroupCommand,
                          RotateGroupCommand, ScaleGroupCommand, SetLockedCommand)
from core.scene import Scene
from formats.igz import load_into, save_scene

_app = QApplication.instance() or QApplication([])


def group_for(scene, component=False):
    group = Group(name="Protected")
    group.mesh.add_face([QVector3D(), QVector3D(1, 0, 0), QVector3D(0, 1, 0)])
    if component:
        group.xform = QMatrix4x4()
    scene.groups.append(group)
    return group


@pytest.mark.parametrize("component", [False, True])
@pytest.mark.parametrize("make_command", [
    lambda g: MoveGroupCommand(g, QVector3D(2, 0, 0)),
    lambda g: RotateGroupCommand(g, QVector3D(), QVector3D(0, 0, 1), 45),
    lambda g: ScaleGroupCommand(g, QVector3D(), QVector3D(2, 2, 2)),
    lambda g: FlipGroupsCommand([g], QVector3D(), QVector3D(1, 0, 0)),
    lambda g: DeleteGroupCommand(g),
    lambda g: ExplodeGroupCommand(g),
])
def test_locked_groups_and_components_reject_edits(component, make_command):
    scene = Scene()
    group = group_for(scene, component)
    group.locked = True
    scene.select([group])
    before = [QVector3D(v.position) for v in group.mesh.vertices]
    transform = QMatrix4x4(group.xform) if component else None
    history = History(scene)
    version = scene.version
    history.execute(make_command(group))
    assert group in scene.groups and scene.selection == {group}
    assert [v.position for v in group.mesh.vertices] == before
    assert group.xform == transform
    assert scene.version == version and not history.undo_stack
    assert history.last_error == "Object is locked"


def test_batch_rejection_is_atomic_and_unlock_allows_editing():
    scene = Scene()
    first, protected = group_for(scene), group_for(scene)
    protected.locked = True
    history = History(scene)
    before = [QVector3D(v.position) for v in first.mesh.vertices]
    history.execute(CompoundCommand([
        MoveGroupCommand(first, QVector3D(2, 0, 0)), DeleteGroupCommand(protected)]))
    assert [v.position for v in first.mesh.vertices] == before
    assert protected in scene.groups and not history.undo_stack
    scene.begin_group_edit(protected)
    assert scene.edit_group is None
    history.execute(SetLockedCommand([first, protected], False))
    assert history.undo() and protected.locked and not first.locked
    assert history.redo() and not protected.locked
    history.execute(MoveGroupCommand(protected, QVector3D(2, 0, 0)))
    assert history.last_error is None and len(history.undo_stack) == 2
    assert history.undo()


def test_locks_survive_copy_and_nested_file_roundtrip(tmp_path):
    scene = Scene()
    parent = group_for(scene, True)
    child = Group(name="Child")
    parent.adopt([child])
    parent.locked = child.locked = True
    copied = copy_group(parent)
    assert copied.locked and copied.children[0].locked
    path = tmp_path / "locked.igz"
    save_scene(scene, path)
    reopened = Scene()
    load_into(reopened, path)
    assert reopened.groups[0].locked and reopened.groups[0].children[0].locked


def test_transform_targets_skip_locked_objects():
    from tools.move import gather_targets
    scene = Scene()
    locked, movable = group_for(scene), group_for(scene)
    locked.locked = True
    scene.select([locked, movable])
    context = SimpleNamespace(viewport=SimpleNamespace(scene=scene))
    groups, positions = gather_targets(context)
    assert groups == [movable] and not positions


def test_scale_box_excludes_locked_objects():
    from tools.scale import ScaleTool
    scene = Scene()
    group = group_for(scene)
    scene.select([group])
    viewport = SimpleNamespace(scene=scene)
    tool = ScaleTool()
    assert tool._selection_bounds(viewport)[0] is not None
    group.locked = True
    assert tool._selection_bounds(viewport) == (None, None)
