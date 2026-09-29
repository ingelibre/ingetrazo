import pytest
from types import SimpleNamespace
from PySide6.QtGui import QMatrix4x4, QVector3D
from PySide6.QtWidgets import QWidget, QDialog
from core.group import Group
from core.scene import Scene
from core.history import History
from core.assembly_animation import KEY, joint, solve, packed, matrix
from formats import igz


def test_hinge_anchor_and_child_attachment_follow_parent():
    body, wing, pin = Group(), Group(), Group()
    rules = [joint(wing, body, 'hinge', (1, 0, 0), (0, 0, 1), 0, 90),
             joint(pin, wing, 'fixed', (0, 0, 0), (0, 0, 1), 0, 0)]
    poses = solve([body, wing, pin], rules, 1)
    for part in [wing, pin]:
        assert (poses[part.uid].map(QVector3D(1, 0, 0))-QVector3D(1, 0, 0)).length() < 1e-6
        assert (poses[part.uid].map(QVector3D(2, 0, 0))-QVector3D(1, 1, 0)).length() < 1e-6


def test_slide_hard_stops_and_scale_preserved():
    pin = Group()
    pin.xform = QMatrix4x4(); pin.xform.scale(.001)
    rules = [joint(pin, None, 'slide', (0, 0, 0), (1, 0, 0), 0, 100)]
    for progress, x in [(-4, 0), (.5, .05), (8, .1)]:
        pose = solve([pin], rules, progress)[pin.uid]
        assert pose.map(QVector3D()).x() == pytest.approx(x)
        assert pose.mapVector(QVector3D(1, 0, 0)).length() == pytest.approx(.001)


def test_matrix_roundtrip_and_parent_translated():
    parent, child = Group(), Group()
    parent.xform = QMatrix4x4(); parent.xform.translate(1, 2, 3)
    parent.xform.rotate(40, 0, 0, 1)
    rule = joint(child, parent, 'fixed', (0, 0, 0), (0, 0, 1), 0, 0)
    assert packed(matrix(packed(parent.xform))) == packed(parent.xform)
    parent.xform.translate(0, 0, 4)
    assert solve([parent, child], [rule], 1)[child.uid].map(QVector3D()).z() == pytest.approx(4)


def test_cycles_missing_parts_and_duplicate_parents_rejected():
    a, b = Group(), Group()
    ab = joint(a, b, 'fixed', (0, 0, 0), (0, 0, 1), 0, 0)
    ba = joint(b, a, 'fixed', (0, 0, 0), (0, 0, 1), 0, 0)
    for groups, rules in [([a,b], [ab, ba]), ([a], [ab]), ([a,b], [ab, ab])]:
        with pytest.raises(ValueError):
            solve(groups, rules, .5)


def test_dialog_cancel_commit_undo_and_saved_joints(tmp_path):
    from plugins.assembly_animation import AssemblyDialog
    scene = Scene(); pin = Group(name='Pin'); scene.groups.append(pin)
    window = QWidget(); history = History(scene)
    vp = SimpleNamespace(window=lambda: window, scene=scene, history=history,
                         notify_scene_changed=lambda: None)
    dialog = AssemblyDialog(vp)
    dialog.kind.setCurrentIndex(2)
    dialog.axis.setText('1, 0, 0')
    dialog.end.setValue(100)
    dialog.add_joint(); dialog.slider.setValue(500)
    assert pin.xform.map(QVector3D()).x() == pytest.approx(.05)
    dialog.reject()
    assert pin.xform is None and KEY not in scene.plugin_data
    dialog = AssemblyDialog(vp)
    dialog.kind.setCurrentIndex(2); dialog.axis.setText('1, 0, 0')
    dialog.end.setValue(100); dialog.add_joint(); dialog.slider.setValue(1000)
    dialog.accept()
    assert not pin.component
    assert scene.plugin_data[KEY]
    history.undo(); assert pin.xform is None and KEY not in scene.plugin_data
    history.redo(); assert pin.xform.map(QVector3D()).x() == pytest.approx(.1)
    path = tmp_path / 'assembly.igz'; igz.save_scene(scene, path)
    loaded = Scene(); igz.load_into(loaded, path)
    assert loaded.plugin_data[KEY] == scene.plugin_data[KEY]
    poses = solve(loaded.groups, loaded.plugin_data[KEY], .5)
    assert poses[pin.uid].map(QVector3D()).x() == pytest.approx(.05)


def test_selected_edge_sets_travel():
    from plugins.assembly_animation import AssemblyDialog
    scene = Scene(); scene.groups.append(Group())
    edge = scene.mesh.add_edge(QVector3D(0, 0, 0), QVector3D(.1, 0, 0))
    scene.selection.add(edge)
    window = QWidget()
    vp = SimpleNamespace(window=lambda: window, scene=scene, history=History(scene),
                         notify_scene_changed=lambda: None)
    dialog = AssemblyDialog(vp); dialog.kind.setCurrentIndex(2)
    dialog.use_edge()
    assert dialog.end.value() == pytest.approx(100)
    assert dialog.axis.text() == '0.1, 0, 0'
    dialog.reject()
