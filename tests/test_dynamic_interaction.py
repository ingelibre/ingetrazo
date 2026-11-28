# SPDX-License-Identifier: GPL-3.0-or-later
"""Imported behavior survives, clicks choose the actual nested placement,
and previews never become saved or historical intermediate states."""
from types import SimpleNamespace as NS

import pytest
from PySide6.QtGui import QMatrix4x4, QVector3D
from PySide6.QtWidgets import QApplication

from core.group import Group
from core.scene import Scene
from core.history import History, InsertGroupCommand
from core.dynamic.apply import _merged, redraw_group
from core.dynamic.actions import ActionError, prepare
from core.dynamic.interaction import Interaction
from core.dynamic.options import options_of
from formats.igz import save_scene, load_into
from formats import skp, skp_openskp
from tools.interact import target_path
from tests.test_skp_nested_parts_866 import _box

_app = QApplication.instance() or QApplication([])
IDENTITY = [1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1]


def data(**attrs):
    return {'skp_dc_import': {'definition_attributes': attrs,
                              'instance_attributes': {}}}


def door(action='ANIMATE("rotation",0,1)'):
    root = Group(name='Door')
    root.xform = QMatrix4x4()
    root.ext = data(_name='Door', _lengthunits='CENTIMETERS')
    moving = Group(name='Opening')
    moving.xform = QMatrix4x4()
    moving.ext = data(_name='Opening', _lengthunits='CENTIMETERS', rotation=0,
                      _rotz_formula='-180-90*rotation', onclick=action,
                      _rotation_units='FLOAT')
    moving.mesh.add_face([QVector3D(0, 0, 0), QVector3D(.9, 0, 0),
                          QVector3D(.9, 0, 2), QVector3D(0, 0, 2)])
    root.adopt([moving])
    return root, moving


class Viewport:
    def __init__(self, root):
        self.scene = Scene()
        self.scene.groups = [root]
        self.scene.select([root])
        self.history = History(self.scene)

    def update(self):
        pass

    def notify_scene_changed(self):
        pass

    def flash_status(self, *args):
        pass


def test_click_cycles_the_existing_parameter_and_preserves_the_formula():
    root, moving = door()
    for expected in (1, 0, 1):
        plan = prepare(root, moving)
        root, ev = redraw_group(root, edits=plan.edits())
        moving = root.children[0]
        assert not ev.errors
        assert _merged(moving)['rotation'] == expected
        assert _merged(moving)['rotz'] == -180 - 90 * expected
        assert _merged(moving)['_rotz_formula'] == '-180-90*rotation'


@pytest.mark.parametrize('text', [
    'ANIMATE("rotation",0,1);GOTOSCENE("elsewhere")',
    '__import__("os")', 'SET("rotation",1);unknown()',
    'ANIMATECUSTOM("rotation",-1,0,100,0,1)',
    'ANIMATECUSTOM("rotation",1,0,101,0,1)',
    'ANIMATE("rotation",0,1/0)', 'SET("_onclick_formula",1)',
    'ANIMATE("rotation",0,1);' * 33,
])
def test_invalid_or_unsupported_actions_reject_the_whole_click(text):
    root, moving = door(text)
    before = repr(moving.ext)
    with pytest.raises(ActionError):
        prepare(root, moving)
    assert repr(moving.ext) == before


def test_set_one_state_and_action_arguments_see_earlier_changes():
    root, moving = door('SET("rotation",1);SET("other",rotation+1)')
    plan = prepare(root, moving)
    assert plan.edits()[id(moving)]['rotation'] == 1
    assert plan.edits()[id(moving)]['other'] == 2
    assert plan.duration == 0


def test_animation_states_use_the_components_length_units():
    root, moving = door('ANIMATECUSTOM("X",2,0,100,0,100)')
    plan = prepare(root, moving)
    change = plan.changes[0]
    assert change.end == pytest.approx(100 / 2.54)
    assert change.value(0) == 0
    assert 0 < change.value(1) < change.end
    assert change.value(2) == change.end


@pytest.mark.parametrize('attribute', ['rotation', 'Opening!rotation', '"rotation"'])
def test_action_attribute_can_be_a_quoted_name_or_an_unquoted_reference(attribute):
    root, moving = door('ANIMATESLOW(' + attribute + ',0,1)')
    plan = prepare(root, moving)
    assert plan.duration == 1
    assert plan.edits()[id(moving)]['rotation'] == 1


def test_click_on_a_shared_nested_part_finds_its_own_ancestor():
    root, moving = door()
    child = Group(name='Handle')
    child.xform = QMatrix4x4()
    moving.adopt([child])
    vp = Viewport(root)
    proxy = Group(child.mesh)
    vp._placement_proxies = {id(child): proxy}
    assert target_path(vp, proxy) == (root, moving)
    # The same mesh in another instance must not select the first one.
    other, other_moving = door()
    other_moving.mesh = moving.mesh
    vp.scene.groups.append(other)
    assert target_path(vp, other_moving) == (other, other_moving)
    moving.locked = True
    assert target_path(vp, proxy) is None


def test_animation_is_one_step_with_exact_undo_and_redo():
    root, moving = door()
    vp = Viewport(root)
    interaction = Interaction(vp, root, moving)
    interaction.start()
    interaction.tick(.25)
    assert not vp.history.undo_stack
    assert 0 < _merged(vp.scene.groups[0].children[0])['rotation'] < 1
    interaction.finish()
    final = vp.scene.groups[0]
    assert len(vp.history.undo_stack) == 1
    assert _merged(final.children[0])['rotation'] == 1
    assert vp.history.undo() and vp.scene.groups[0] is root
    assert vp.history.redo() and vp.scene.groups[0] is final


def test_escape_restores_the_original_tree_without_an_undo_step():
    root, moving = door()
    vp = Viewport(root)
    before = vp.scene.version
    interaction = Interaction(vp, root, moving)
    interaction.start()
    interaction.tick(.2)
    interaction.cancel()
    assert vp.scene.groups[0] is root
    assert root in vp.scene.selection
    assert not vp.history.undo_stack
    assert vp.scene.version == before
    assert not hasattr(vp.scene, '_finish_dynamic_preview')


def test_undo_during_animation_first_settles_then_undoes_the_click():
    root, moving = door()
    vp = Viewport(root)
    interaction = Interaction(vp, root, moving)
    interaction.start()
    interaction.tick(.2)
    assert vp.history.undo()
    assert vp.scene.groups[0] is root
    assert not interaction.running
    assert vp.history.redo()
    assert _merged(vp.scene.groups[0].children[0])['rotation'] == 1


def test_another_command_settles_the_animation_before_it_runs():
    root, moving = door()
    vp = Viewport(root)
    interaction = Interaction(vp, root, moving)
    interaction.start()
    interaction.tick(.2)
    vp.history.execute(InsertGroupCommand(Group(name='Other')))
    assert len(vp.history.undo_stack) == 2
    assert not interaction.running
    assert _merged(vp.scene.groups[0].children[0])['rotation'] == 1


def test_saving_during_animation_writes_the_final_state(tmp_path):
    root, moving = door()
    vp = Viewport(root)
    interaction = Interaction(vp, root, moving)
    interaction.start()
    interaction.tick(.2)
    path = tmp_path / 'door.igz'
    save_scene(vp.scene, path)
    scene = Scene()
    load_into(scene, path)
    attrs = _merged(scene.groups[0].children[0])
    assert attrs['rotation'] == 1
    assert attrs['onclick'] == 'ANIMATE("rotation",0,1)'
    assert not interaction.running


def imported_model():
    board = _box(2, 'Board', 30, 1, 80)
    board.attribute_dictionaries = {'dynamic_attributes': {
        '_lengthunits': 'INCHES', '_lenx_formula': 'Parent!width'}}
    root = NS(id=0, name='ROOT_MODEL', vertices={}, edges={}, faces={},
              instances=[NS(ref_idx=2, matrix=IDENTITY, hidden=True,
                            attribute_dictionaries={'dynamic_attributes': {'width': 40}}),
                         NS(ref_idx=2, matrix=IDENTITY,
                            attribute_dictionaries={'dynamic_attributes': {'width': 50}})])
    return NS(root=root, definitions={2: board}, attribute_dictionaries={},
              version='{23.0}', styles=[], pages=[], dimensions=[])


def test_import_keeps_definition_and_instance_data_and_hidden_parts():
    scene = Scene()
    payload = skp_openskp._adapt(imported_model(), 'test')
    skp.apply_payload(scene, payload)
    first, second = scene.groups
    assert first.mesh is second.mesh
    assert first.hidden and not second.hidden
    assert _merged(first)['width'] == 40
    assert _merged(second)['width'] == 50
    assert _merged(first)['_lenx_formula'] == 'Parent!width'
    # Placement dictionaries must not alias each other or the reusable payload.
    first.ext['skp_dc_import']['definition_attributes']['custom'] = 1
    assert 'custom' not in _merged(second)


def test_a_component_saved_as_its_own_skp_keeps_its_parent():
    model = imported_model()
    model.attribute_dictionaries = {'dynamic_attributes': {
        '_name': 'Cabinet', 'width': 45, '_width_access': 'TEXTBOX',
        '_width_units': 'INCHES'}}
    scene = Scene()
    skp.apply_payload(scene, skp_openskp._adapt(model, 'cabinet'))
    [root] = scene.groups
    assert root.name == 'Cabinet' and len(root.children) == 2
    assert len(options_of(_merged(root))) == 1


def test_toolbar_opens_user_options_and_the_attribute_editor(monkeypatch):
    from PySide6.QtWidgets import QDialog
    from PySide6.QtCore import Qt
    from views.main_window import MainWindow

    show = QDialog.show
    def hidden_show(dialog):
        dialog.setAttribute(Qt.WA_DontShowOnScreen, True)
        show(dialog)
    monkeypatch.setattr(QDialog, 'show', hidden_show)
    window = MainWindow(defer_extensions=True)
    root, moving = door()
    root.ext['skp_dc_import']['definition_attributes'].update({
        'width': 90 / 2.54, '_width_access': 'TEXTBOX', '_width_units': 'CENTIMETERS'})
    scene = window.viewport.scene
    scene.clear()
    scene.groups = [root]
    window.viewport.notify_scene_changed()
    scene.select([root])
    try:
        assert len(window.toolbars['dynamic_components'].actions()) == 3
        from views.icons import tool_icon
        from views import theme
        from PySide6.QtGui import QColor
        actions = window.toolbars['dynamic_components'].actions()
        def pixels(icon):
            image = icon.pixmap(24, 24).toImage()
            return bytes(image.constBits())
        assert pixels(actions[1].icon()) == pixels(tool_icon('panel_properties'))
        assert pixels(actions[2].icon()) == pixels(tool_icon('panel_options'))
        before = [pixels(action.icon()) for action in actions]
        monkeypatch.setattr(theme, 'accent_color', lambda *args: QColor(180, 40, 210))
        window._refresh_toolbar_icons()
        assert root in scene.selection, 'selection lost during icon refresh'
        assert all(pixels(action.icon()) != old for action, old in zip(actions, before))
        export_menu = next(action.menu() for action in window.menuBar().actions()
                           if action.menu() and any(a.menu() and a.menu().title() == 'Export'
                                                   for a in action.menu().actions()))
        export_menu = next(a.menu() for a in export_menu.actions()
                           if a.menu() and a.menu().title() == 'Export')
        assert all('SKP' not in action.text().upper() for action in export_menu.actions())
        assert root in scene.selection, 'selection lost during export menu inspection'
        window._show_dynamic_options()
        panel = window._dynamic_options_dialog.panel
        assert len(panel.rows) == 1
        from PySide6.QtCore import QEvent
        monkeypatch.setattr(theme, 'accent_color', lambda *args: QColor(30, 160, 90))
        QApplication.sendEvent(panel, QEvent(QEvent.StyleChange))
        assert pixels(panel.interact_btn.icon()) == pixels(tool_icon('interact'))
        panel.rows[0][1].setText('100 cm')
        assert root in scene.selection, 'selection lost while showing options'
        panel.apply_btn.click()
        assert _merged(scene.groups[0])['width'] == pytest.approx(100 / 2.54)
        assert scene.groups[0] in scene.selection, (window.viewport.history.last_error, panel.status.text())
        panel.open_attributes()
        assert panel._attributes is not None
    finally:
        if panel._attributes is not None:
            panel._attributes.close()
        window._dynamic_options_dialog.close()
        window._saved_version = scene.version
        window.close()
