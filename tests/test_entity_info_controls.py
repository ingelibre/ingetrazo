"""Selection facts and the visibility control use the same model/history."""
import os
from types import SimpleNamespace
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QVector3D
from PySide6.QtWidgets import QApplication

from core.history import History
from core.scene import Scene
from views.tray import EntityInfoPanel

_app = QApplication.instance() or QApplication([])


def panel_for(scene):
    viewport = SimpleNamespace(scene=scene, history=History(scene), update=lambda: None)
    window = SimpleNamespace(viewport=viewport)
    return EntityInfoPanel(window), viewport


def test_face_fields_clear_when_selection_clears():
    scene = Scene()
    face = scene.mesh.add_face([QVector3D(0, 0, 0), QVector3D(2, 0, 0),
                               QVector3D(2, 2, 0), QVector3D(0, 2, 0)])
    scene.select([face])
    panel, _ = panel_for(scene)
    assert panel._label.text() == "Face"
    assert panel._facts[0][1].text() == "4.000 m²"
    assert panel._visible.isEnabled() and panel._visible.isChecked()
    scene.clear_selection()
    panel.refresh()
    assert all(value.text() == "" for _, value in panel._facts)
    assert not panel._visible.isEnabled()
    panel.close()


def test_hide_mixed_selection_is_one_undo_step():
    scene = Scene()
    face = scene.mesh.add_face([QVector3D(0, 0, 0), QVector3D(1, 0, 0),
                               QVector3D(1, 1, 0)])
    edge = next(iter(scene.mesh.edges))
    scene.select([face, edge])
    panel, viewport = panel_for(scene)
    panel._visible.click()
    assert face.attrs.get("hidden") and edge.hidden
    assert not scene.selection
    assert viewport.history.undo()
    assert not face.attrs.get("hidden") and not edge.hidden
    panel.close()


def test_lock_button_sets_mixed_images_to_one_state():
    from core.image_plane import ImagePlane
    scene = Scene()
    images = [ImagePlane("plan.png", QVector3D(), QVector3D(1, 0, 0),
                         QVector3D(0, 1, 0), locked=locked)
              for locked in (False, True)]
    scene.image_planes.extend(images)
    scene.selection.update(images)
    panel, _ = panel_for(scene)
    from core import history
    if not hasattr(history, "SetLockedCommand"):
        assert not panel._locked.isEnabled()
        panel.close()
        return
    assert panel._locked.isEnabled() and not panel._locked.isChecked()
    version = scene.version
    panel._locked.click()
    assert all(image.locked for image in images)
    assert scene.version > version
    panel.refresh()
    assert panel._locked.isChecked() and panel._locked.toolTip() == "Unlock"
    panel._locked.click()
    assert not any(image.locked for image in images)
    scene.clear_selection()
    panel.refresh()
    assert not panel._locked.isEnabled() and not panel._locked.isChecked()
    panel.close()


def test_panel_lock_is_undoable_and_selection_stays_available():
    from core import history as history_module
    from core.group import Group
    from core.history import History
    if not hasattr(history_module, "SetLockedCommand"):
        pytest.skip("Group-lock integration requires the companion lock PR")
    scene = Scene()
    group = Group(name="Protected")
    scene.groups.append(group)
    scene.select([group])
    history = History(scene)
    window = SimpleNamespace(viewport=SimpleNamespace(
        scene=scene, history=history, update=lambda: None))
    panel = EntityInfoPanel(window)
    assert panel._locked.isEnabled()
    panel._locked.click()
    assert group.locked and scene.selection == {group}
    assert scene.entity_selectable(group) and scene.entity_visible(group)
    assert history.undo() and not group.locked
    assert history.redo() and group.locked
    panel.refresh()
    assert panel._locked.isChecked() and panel._locked.toolTip() == "Unlock"
    panel._locked.click()
    assert not group.locked
    panel.close()
