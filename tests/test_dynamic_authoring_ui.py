# SPDX-License-Identifier: GPL-3.0-or-later
"""The author composes a formula by clicking the common attribute sheet."""
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QColor, QMatrix4x4, QPalette, QVector3D
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton

from core.dynamic import author as AU
from core.dynamic.apply import _merged, part_tree
from core.dynamic.evaluate import Evaluator
from core.group import Group
from core.i18n import tr
from views.dynamic_panel import AttributeOptionsDialog, AttributesDialog, ComponentOptionsPanel
from tests.test_dynamic_interaction import Viewport, data, door


@pytest.fixture
def editor():
    root, moving = door()
    root.ext['skp_dc_import']['definition_attributes'].update({
        'width': 100 / 2.54, '_width_units': 'CENTIMETERS'})
    moving.ext['skp_dc_import']['definition_attributes'].update({
        'derived': 0, '_derived_units': 'CENTIMETERS'})
    other = Group(name='Other')
    other.xform = QMatrix4x4()
    other.ext = data(_name='Other', _lengthunits='CENTIMETERS',
                     gap=20 / 2.54, _gap_units='CENTIMETERS')
    root.adopt([moving, other])
    viewport = Viewport(root)
    dialog = AttributesDialog(SimpleNamespace(viewport=viewport))
    dialog.show_root(root, (0,))
    dialog.show()
    QApplication.processEvents()
    yield dialog, viewport, root
    dialog.close()
    dialog.deleteLater()
    QApplication.processEvents()


def row(dialog, component, attribute):
    current = None
    for i in range(dialog.table.rowCount()):
        item = dialog.table.item(i, 0)
        if item is None:
            continue
        if item.data(Qt.UserRole + 2) == 'component':
            current = item.data(Qt.UserRole + 3)
        elif current == component and item.text() == AU.LABELS.get(attribute, attribute):
            return i
    raise AssertionError((component, attribute))


def click_attribute(dialog, component, attribute, column=0):
    i = row(dialog, component, attribute)
    item = dialog.table.item(i, column)
    dialog.table.scrollToItem(item)
    QApplication.processEvents()
    QTest.mouseClick(dialog.table.viewport(), Qt.LeftButton, Qt.NoModifier,
                     dialog.table.visualItemRect(item).center())


@pytest.mark.parametrize('section', [title for title, _items in AU.GROUPS])
def test_clicking_a_category_adds_all_members_to_the_selected_part_in_one_step(editor, section):
    dialog, viewport, original = editor
    label = tr({'Component Info': 'Component info', 'Form Design': 'Form design'}.get(section, section))
    action = next(a for a in dialog.add_btn.menu().actions() if a.text() == label)
    assert action.isEnabled() and not action.isSeparator()
    expected = {name for title, items in AU.GROUPS if title == section for name, _u in items}
    existing = set(AU.attribute_names(_merged(original.children[0])))
    action.trigger()
    assert expected <= set(AU.attribute_names(_merged(dialog.root.children[0])))
    assert not expected - existing <= set(AU.attribute_names(_merged(dialog.root)))
    assert len(viewport.history.undo_stack) == 1
    current = dialog.root
    action.trigger()                     # adding it again must not overwrite anything
    assert dialog.root is current
    assert len(viewport.history.undo_stack) == 1
    assert viewport.history.undo() and viewport.scene.groups[0] is original
    dialog._sync_root()
    assert dialog.root is original


def test_bulk_add_keeps_an_existing_formula(editor):
    dialog, viewport, original = editor
    original.children[0].ext['skp_dc_import']['definition_attributes'].update(
        {'x': 0, '_x_formula': '5'})
    dialog.show_root(original, (0,))
    next(a for a in dialog.add_btn.menu().actions() if a.text() == tr('Position')).trigger()
    assert _merged(dialog.root.children[0])['_x_formula'] == '5'
    assert {'x', 'y', 'z'} <= set(AU.attribute_names(_merged(dialog.root.children[0])))
    assert len(viewport.history.undo_stack) == 1


def test_formula_can_pick_general_and_sibling_attributes_without_leaving_the_target(editor):
    dialog, viewport, original = editor
    click_attribute(dialog, 'Opening', 'derived')
    dialog.table.setFocus()
    QTest.keyClick(dialog.table, Qt.Key_Equal)
    assert dialog.formula_edit.text() == '='
    click_attribute(dialog, 'Door', 'width')
    QTest.keyClicks(dialog.formula_edit, '-')
    click_attribute(dialog, 'Other', 'gap')
    assert dialog.formula_edit.text() == '=parent!width-Other!gap'
    assert 'Opening' in dialog.edit_target.text()
    assert not viewport.history.undo_stack     # a draft is never partially applied
    assert _merged(original.children[0])['derived'] == 0
    QTest.keyClick(dialog.formula_edit, Qt.Key_Return)
    attrs = _merged(dialog.root.children[0])
    assert attrs['_derived_formula'] == 'parent!width-Other!gap'
    assert float(attrs['derived']) == pytest.approx(80 / 2.54)
    assert len(viewport.history.undo_stack) == 1
    assert viewport.history.undo() and viewport.scene.groups[0] is original
    dialog._sync_root()
    assert dialog.root is original
    assert '_derived_formula' not in _merged(dialog.root.children[0])


def test_tree_navigation_scrolls_the_reference_sheet_without_committing_a_draft(editor):
    dialog, viewport, _original = editor
    click_attribute(dialog, 'Opening', 'derived')
    dialog.formula_edit.setFocus()
    dialog.formula_edit.selectAll()
    QTest.keyClicks(dialog.formula_edit, '=IF(')
    dialog.tree.setCurrentItem(dialog.tree.topLevelItem(0))
    assert dialog.formula_edit.text() == '=IF('
    assert dialog.path == (0,)
    click_attribute(dialog, 'Door', 'width')
    assert dialog.formula_edit.text() == '=IF(parent!width'
    assert not viewport.history.undo_stack
    QTest.keyClick(dialog.formula_edit, Qt.Key_Escape)
    assert dialog.formula_edit.text() == '0 cm'
    assert not viewport.history.undo_stack


def test_bad_formula_stays_editable_and_escape_cancels_it(editor):
    dialog, viewport, _original = editor
    click_attribute(dialog, 'Opening', 'derived')
    dialog.formula_edit.setFocus()
    dialog.formula_edit.selectAll()
    QTest.keyClicks(dialog.formula_edit, '=IF(')
    QTest.keyClick(dialog.formula_edit, Qt.Key_Return)
    assert dialog.formula_edit.text() == '=IF('
    assert dialog.formula_apply.isEnabled()
    assert dialog.status.text()
    assert not viewport.history.undo_stack
    QTest.keyClick(dialog.formula_edit, Qt.Key_Escape)
    assert dialog.formula_edit.text() == '0 cm'


@pytest.mark.parametrize('target,source', [('lenz', 'z'), ('z', 'lenz')])
@pytest.mark.parametrize('names', [('A', 'B'), ('Composant n°1', 'Composant n°2'),
                                  ('Component #1', 'Component #2')])
def test_clicking_values_edits_in_the_cell_and_keeps_a_live_sibling_reference(editor, target, source, names):
    dialog, viewport, original = editor
    source_name, target_name = names
    a = original.children[0]
    _unused, b = door()
    a.name, b.name = names
    a.ext = data(_name=source_name, _lengthunits='CENTIMETERS', lenz=200 / 2.54, z=30 / 2.54)
    b.ext = data(_name=target_name, _lengthunits='CENTIMETERS', lenz=100 / 2.54, z=0)
    original.name = 'Composant n°3'
    original.ext['skp_dc_import']['definition_attributes']['_name'] = original.name
    a.xform.translate(0, 0, .3)
    b.xform.scale(1, 1, .5)
    original.adopt([a, b])
    dialog.show_root(original)

    click_attribute(dialog, target_name, target, column=1)
    cell = dialog.table.cellWidget(row(dialog, target_name, target), 1)
    assert cell is not None and cell.hasFocus()
    QTest.keyClicks(cell, '=')
    click_attribute(dialog, source_name, source, column=1)
    assert cell.text() == '=' + source_name + '!' + AU.LABELS[source]
    assert dialog._edit_target == ((1,), target)
    assert not viewport.history.undo_stack
    QTest.keyClick(cell, Qt.Key_Return)
    expected = (30 if source == 'z' else 200) / 2.54
    assert _merged(dialog.root.children[1])['_' + target + '_formula'] == source_name + '!' + AU.LABELS[source]
    assert float(_merged(dialog.root.children[1])[target]) == pytest.approx(expected)
    if target == 'z':
        assert dialog.root.children[1].xform.map(QVector3D()).z() == pytest.approx(2)
    assert len(viewport.history.undo_stack) == 1
    assert not {'z', 'lenz'} & set(_merged(dialog.root))

    # Changing A afterwards must update B, rather than having copied a number.
    click_attribute(dialog, source_name, source, column=1)
    cell = dialog._cell_editor
    QTest.keyClicks(cell, '75 cm')
    QTest.keyClick(cell, Qt.Key_Return)
    assert float(_merged(dialog.root.children[1])[target]) == pytest.approx(75 / 2.54)
    assert viewport.history.undo()
    dialog._sync_root()
    assert float(_merged(dialog.root.children[1])[target]) == pytest.approx(expected)


def test_escape_discards_an_inline_formula_without_changing_the_model(editor):
    dialog, viewport, _original = editor
    click_attribute(dialog, 'Opening', 'derived', column=1)
    cell = dialog._cell_editor
    QTest.keyClicks(cell, '=IF(')
    QTest.keyClick(cell, Qt.Key_Return)
    assert dialog._cell_editor is cell and cell.text() == '=IF('
    assert dialog.status.text()
    QTest.keyClick(cell, Qt.Key_Escape)
    assert dialog._cell_editor is None
    assert dialog.formula_edit.text() == '0 cm'
    assert not viewport.history.undo_stack


def test_clicking_another_value_commits_a_number_and_starts_the_next_cell(editor):
    dialog, viewport, _original = editor
    click_attribute(dialog, 'Opening', 'derived', column=1)
    QTest.keyClicks(dialog._cell_editor, '25 cm')
    click_attribute(dialog, 'Other', 'gap', column=1)
    assert float(_merged(dialog.root.children[0])['derived']) == pytest.approx(25 / 2.54)
    assert dialog._edit_target == ((1,), 'gap')
    assert dialog._cell_editor.hasFocus()
    assert dialog._cell_editor.text() == '20 cm'
    assert len(viewport.history.undo_stack) == 1


def test_typing_a_nested_component_size_stretches_its_contents(editor):
    dialog, viewport, original = editor
    part = original.children[0]
    _unused, child = door()
    part.mesh = Group().mesh
    part.adopt([child])
    part.ext = data(_name='Assembly', _lengthunits='CENTIMETERS', lenz=200 / 2.54)
    dialog.show_root(original)
    click_attribute(dialog, 'Assembly', 'lenz', column=1)
    QTest.keyClicks(dialog._cell_editor, '75 cm')
    QTest.keyClick(dialog._cell_editor, Qt.Key_Return)
    result = dialog.root.children[0]
    assert float(_merged(result)['lenz']) == pytest.approx(75 / 2.54)
    assert result.children[0].xform.map(QVector3D(0, 0, 2)).z() == pytest.approx(.75)
    assert not {'z', 'lenz'} & set(_merged(dialog.root))
    assert len(viewport.history.undo_stack) == 1


def test_formulas_can_reference_a_unique_part_in_another_branch(editor):
    dialog, _viewport, root = editor
    assembly = Group(name='Branch')
    assembly.xform = QMatrix4x4()
    leaf = Group(name='Unique leaf')
    leaf.xform = QMatrix4x4()
    leaf.ext = data(_name='Unique leaf', value=7)
    assembly.adopt([leaf])
    root.adopt([*root.children, assembly])
    root.children[0].ext['skp_dc_import']['definition_attributes']['_derived_formula'] = (
        'Unique leaf!value')
    tree = part_tree(root)
    assert Evaluator(tree).value(tree.children[0], 'derived') == pytest.approx(7 / 2.54)
    # A repeated display name cannot silently point at the wrong part.
    duplicate = Group(name='Unique leaf')
    duplicate.xform = QMatrix4x4()
    duplicate.ext = data(_name='Unique leaf', value=9)
    assembly.adopt([leaf, duplicate])
    tree = part_tree(root)
    assert Evaluator(tree).resolve(tree.children[0], 'Unique leaf') is None


def test_selection_inside_the_open_3d_component_follows_the_exact_placement(editor):
    dialog, viewport, original = editor
    original.children[1].mesh = original.children[0].mesh
    viewport.scene.begin_group_edit(original)
    viewport.scene.select([original.children[1]])
    dialog._sync_root()
    assert tuple(dialog.tree.currentItem().data(0, Qt.UserRole)) == (1,)
    assert dialog.path == (1,)
    assert dialog.root is original
    viewport.scene.select([original.children[0]])
    dialog._sync_root()
    assert tuple(dialog.tree.currentItem().data(0, Qt.UserRole)) == (0,)
    assert not viewport.history.undo_stack


def test_a_render_proxy_selects_its_part_and_opens_the_collapsed_block(editor):
    dialog, viewport, root = editor
    QTest.mouseClick(dialog._block_buttons[(1,)], Qt.LeftButton)
    assert dialog.table.isRowHidden(row(dialog, 'Other', 'gap'))
    proxy = Group(root.children[1].mesh)
    viewport._placement_proxies = {id(root.children[1]): proxy}
    viewport.scene.select([proxy])
    dialog._sync_root()
    assert tuple(dialog.tree.currentItem().data(0, Qt.UserRole)) == (1,)
    assert not dialog.table.isRowHidden(row(dialog, 'Other', 'gap'))


def test_3d_selection_marks_the_source_without_losing_the_pending_formula(editor):
    dialog, viewport, root = editor
    click_attribute(dialog, 'Opening', 'derived', column=1)
    cell = dialog._cell_editor
    QTest.keyClicks(cell, '=IF(')
    viewport.scene.select([root.children[1]])
    dialog._sync_root()
    assert tuple(dialog.tree.currentItem().data(0, Qt.UserRole)) == (1,)
    assert dialog._cell_editor is cell and cell.text() == '=IF('
    assert dialog._edit_target == ((0,), 'derived')
    assert not viewport.history.undo_stack


def test_attribute_colors_follow_the_active_styles_axes_without_resetting_a_draft(editor):
    from core.modeling_style import modeling_color
    from core.style import Style
    dialog, viewport, root = editor
    attrs = root.children[0].ext['skp_dc_import']['definition_attributes']
    attrs.update({name: 0 for name in ('x', 'y', 'z', 'lenx', 'leny', 'lenz')})
    dialog.show_root(root)
    for name in ('x', 'y', 'z', 'lenx', 'leny', 'lenz'):
        assert dialog.table.item(row(dialog, 'Opening', name), 0).foreground().color() == (
            QColor.fromRgbF(*modeling_color(viewport.scene.display_style, 'axis_' + name[-1])))
    click_attribute(dialog, 'Opening', 'derived', column=1)
    cell = dialog._cell_editor
    QTest.keyClicks(cell, '=')
    viewport.scene.display_style = Style(modeling_colors={'axis_x': (.1, .8, .9),
                                                          'axis_y': (.8, .2, .7),
                                                          'axis_z': (.9, .7, .1)})
    dialog._sync_root()
    assert dialog._cell_editor is cell and cell.text() == '='
    assert dialog.table.item(row(dialog, 'Opening', 'lenx'), 0).foreground().color() == (
        QColor.fromRgbF(.1, .8, .9))


def test_component_blocks_have_categories_and_collapse_independently(editor):
    dialog, _viewport, root = editor
    root.children[0].ext['skp_dc_import']['definition_attributes'].update(
        {'x': 0, 'y': 0, 'z': 0, 'lenz': 100 / 2.54})
    dialog.show_root(root)
    first, last = dialog._block_rows[(0,)]
    labels = [dialog.table.item(r, 0).text() for r in range(first, last + 1)
              if dialog.table.item(r, 0) is not None
              and dialog.table.item(r, 0).data(Qt.UserRole + 2) == 'category']
    assert tr('Position') in labels and tr('Size') in labels
    QTest.mouseClick(dialog._block_buttons[(0,)], Qt.LeftButton)
    assert all(dialog.table.isRowHidden(r) for r in range(first + 1, last + 1))
    assert not dialog.table.isRowHidden(row(dialog, 'Other', 'gap'))
    QTest.mouseClick(dialog._block_buttons[(0,)], Qt.LeftButton)
    assert all(not dialog.table.isRowHidden(r) for r in range(first, last + 1))


def test_sidebar_handle_does_not_become_a_splitter_pane_or_squeeze_the_sheet(editor):
    dialog, _viewport, _root = editor
    dialog.resize(980, 800)
    QApplication.processEvents()
    assert dialog._sheet_split.count() == 2
    assert dialog.table.height() > 400
    for _ in range(2):
        QTest.mouseClick(dialog.tree_toggle, Qt.LeftButton)
        QApplication.processEvents()
        assert dialog.table.height() > 400
        center = dialog.tree_toggle.geometry().center()
        assert abs(center.y() - dialog._sheet_split.geometry().center().y()) < 3
    assert not dialog.tree.isHidden()


def test_folding_and_unfolding_repaints_the_whole_frame_without_scrolling(editor):
    dialog, _viewport, _root = editor

    class PaintRegions(QObject):
        def __init__(self):
            super().__init__()
            self.regions = []

        def eventFilter(self, obj, event):
            if event.type() == QEvent.Paint:
                self.regions.append(event.region().boundingRect())
            return False

    observer = PaintRegions()
    outline = dialog.table._outline
    outline.installEventFilter(observer)
    try:
        for _ in range(4):
            observer.regions.clear()
            dialog._toggle_block((0,))
            QTest.qWait(30)
            assert any(region.contains(outline.rect()) for region in observer.regions)
    finally:
        outline.removeEventFilter(observer)


def test_each_blocks_add_attribute_menu_targets_that_block(editor):
    dialog, viewport, _root = editor
    button = dialog._block_add_buttons[2]  # Other; the selected part is Opening
    dialog.table.scrollToItem(dialog.table.item(dialog._section_rows[(1,)], 0))
    QApplication.processEvents()
    QTest.mouseClick(button, Qt.LeftButton)
    menu = QApplication.activePopupWidget()
    assert menu is not None
    next(action for action in menu.actions() if action.text() == tr('Position')).trigger()
    menu.close()
    assert {'x', 'y', 'z'} <= set(AU.attribute_names(_merged(dialog.root.children[1])))
    assert 'x' not in _merged(dialog.root.children[0])
    assert len(viewport.history.undo_stack) == 1


def test_row_options_icon_opens_and_edits_the_clicked_parts_attribute(editor, monkeypatch):
    from PySide6.QtWidgets import QDialog
    dialog, viewport, _root = editor
    captured = []

    def configure(options):
        captured.append(options.label.text())
        options.label.setText('Clearance')
        options.units.setCurrentIndex(options.units.findData('MILLIMETERS'))
        return QDialog.Accepted

    monkeypatch.setattr(AttributeOptionsDialog, 'exec', configure)
    button = dialog._attribute_option_buttons[((1,), 'gap')]
    assert not button.icon().isNull()
    dialog.table.scrollToItem(dialog.table.item(row(dialog, 'Other', 'gap'), 2))
    QApplication.processEvents()
    QTest.mouseClick(button, Qt.LeftButton)
    assert captured == ['gap']
    assert _merged(dialog.root.children[1])['_gap_formlabel'] == 'Clearance'
    assert _merged(dialog.root.children[1])['_gap_units'] == 'MILLIMETERS'
    assert '_gap_formlabel' not in _merged(dialog.root.children[0])
    assert len(viewport.history.undo_stack) == 1


def select_function(dialog, name):
    index = next(i for i in range(dialog.function_combo.count())
                 if dialog.function_combo.itemData(i) is not None
                 and dialog.function_combo.itemData(i)[0] == name)
    dialog.function_combo.setCurrentIndex(index)
    return index


def test_insert_function_can_pick_an_attribute_and_apply_the_complete_formula(editor):
    dialog, viewport, _root = editor
    assert not hasattr(dialog, 'opt_btn')
    click_attribute(dialog, 'Opening', 'derived', column=1)
    select_function(dialog, 'ABS')
    QTest.mouseClick(dialog.insert_function_btn, Qt.LeftButton)
    cell = dialog._cell_editor
    assert cell.text() == '=ABS()' and cell.cursorPosition() == 5
    click_attribute(dialog, 'Door', 'width', column=1)
    assert cell.text() == '=ABS(parent!width)'
    assert not viewport.history.undo_stack
    QTest.keyClick(cell, Qt.Key_Return)
    assert _merged(dialog.root.children[0])['_derived_formula'] == 'ABS(parent!width)'
    assert float(_merged(dialog.root.children[0])['derived']) == pytest.approx(100 / 2.54)
    assert len(viewport.history.undo_stack) == 1


def test_insert_uses_the_cursor_selection_without_committing_an_incomplete_draft(editor):
    dialog, viewport, _root = editor
    click_attribute(dialog, 'Opening', 'derived', column=1)
    cell = dialog._cell_editor
    QTest.keyClicks(cell, '=10+2')
    cell.setSelection(4, 1)
    select_function(dialog, 'SQRT')
    QTest.mouseClick(dialog.insert_function_btn, Qt.LeftButton)
    QTest.keyClicks(cell, '9')
    assert cell.text() == '=10+SQRT(9)'
    assert not viewport.history.undo_stack
    QTest.keyClick(cell, Qt.Key_Return)
    assert float(_merged(dialog.root.children[0])['derived']) == pytest.approx(13 / 2.54)


def test_action_functions_are_restricted_to_onclick_and_unsupported_entries_are_disabled(editor):
    dialog, _viewport, _root = editor
    click_attribute(dialog, 'Opening', 'derived', column=1)
    select_function(dialog, 'ANIMATE')
    assert not dialog.insert_function_btn.isEnabled()
    index = select_function(dialog, 'FACEAREA')
    assert not dialog.function_combo.model().item(index).isEnabled()
    assert not dialog.insert_function_btn.isEnabled()
    click_attribute(dialog, 'Opening', 'onclick', column=1)
    cell = dialog._cell_editor
    cell.deselect()
    cell.setCursorPosition(len(cell.text()))
    select_function(dialog, 'REDRAW')
    QTest.mouseClick(dialog.insert_function_btn, Qt.LeftButton)
    assert cell.text() == 'ANIMATE("rotation",0,1);REDRAW()'
    QTest.keyClick(cell, Qt.Key_Return)
    assert _merged(dialog.root.children[0])['onclick'].endswith(';REDRAW()')
    assert '_onclick_formula' not in _merged(dialog.root.children[0])


def test_the_global_unit_switch_converts_values_and_keeps_formulas_and_geometry(editor):
    dialog, viewport, root = editor
    click_attribute(dialog, 'Opening', 'derived', column=1)
    QTest.keyClicks(dialog._cell_editor, '=parent!width/2')
    QTest.keyClick(dialog._cell_editor, Qt.Key_Return)
    current = dialog.root
    initial_transform = QMatrix4x4(current.children[0].xform)
    steps = len(viewport.history.undo_stack)
    QTest.mouseClick(dialog.display_units_btn, Qt.LeftButton)
    assert dialog.table.item(row(dialog, 'Door', 'width'), 1).text() == '39.3701 in'
    assert dialog.table.item(row(dialog, 'Opening', 'derived'), 1).text() == '=parent!width/2'
    assert dialog.table.item(row(dialog, 'Opening', 'derived'), 2).text() == '19.685 in'
    assert dialog.root is current and current.children[0].xform == initial_transform
    assert _merged(current.children[0])['_lengthunits'] == 'CENTIMETERS'
    assert len(viewport.history.undo_stack) == steps
    QTest.mouseClick(dialog.display_units_btn, Qt.LeftButton)
    assert dialog.table.item(row(dialog, 'Door', 'width'), 1).text() == '100 cm'


def test_display_selector_preserves_mixed_imported_units_and_all_component_data(editor):
    import copy
    dialog, viewport, root = editor
    root.ext['skp_dc_import']['definition_attributes']['_width_units'] = 'MILLIMETERS'
    root.children[0].ext['skp_dc_import']['definition_attributes'].update({
        '_lengthunits': 'INCHES', '_derived_units': 'INCHES',
        '_derived_formula': 'parent!width/2'})
    dialog.show_root(root)
    groups = [root, *root.children]
    before = [(copy.deepcopy(g.ext), QMatrix4x4(g.xform)) for g in groups]
    version = viewport.scene.version
    assert dialog.table.item(row(dialog, 'Door', 'width'), 1).text() == '1000 mm'
    assert dialog.table.item(row(dialog, 'Opening', 'derived'), 2).text() == '19.685 in'
    for unit, expected_width, expected_result in (
            ('METERS', '1 m', '0.5 m'), ('CENTIMETERS', '100 cm', '50 cm'),
            ('INCHES', '39.3701 in', '19.685 in'), (None, '1000 mm', '19.685 in')):
        dialog.display_unit_combo.setCurrentIndex(dialog.display_unit_combo.findData(unit))
        assert dialog.table.item(row(dialog, 'Door', 'width'), 1).text() == expected_width
        assert dialog.table.item(row(dialog, 'Opening', 'derived'), 2).text() == expected_result
        assert dialog.root is root and viewport.scene.version == version
        assert all(g.ext == ext and g.xform == matrix for g, (ext, matrix) in zip(groups, before))
        assert not viewport.history.undo_stack


@pytest.mark.parametrize('attribute,expected', [('lenz', '2 m'), ('width', '1 m')])
def test_choosing_meters_in_attribute_options_shows_suffix_in_both_windows(editor, attribute, expected):
    dialog, viewport, root = editor
    attrs = root.ext['skp_dc_import']['definition_attributes']
    attrs.update({'lenz': 200 / 2.54, '_lenz_access': 'TEXTBOX', '_width_access': 'TEXTBOX'})
    dialog.show_root(root)
    options = AttributeOptionsDialog(dialog, attribute, _merged(root))
    options.units.setCurrentIndex(options.units.findData('METERS'))
    dialog._select_attribute((), attribute)
    assert dialog._commit(options.changes(attribute), '')
    options.close()
    item_row = row(dialog, 'Door', attribute)
    assert dialog.table.item(item_row, 1).text() == expected
    assert dialog.table.item(item_row, 2).text() == expected
    click_attribute(dialog, 'Door', attribute, column=1)
    assert dialog._cell_editor.text() == expected
    panel = ComponentOptionsPanel(SimpleNamespace(viewport=viewport))
    panel.refresh()
    assert next(w for opt, w, _initial in panel.rows if opt.name == attribute).text() == expected
    assert _merged(dialog.root)['_lengthunits'] == 'CENTIMETERS'
    panel.close()


def test_new_custom_attribute_keeps_unit_visible_when_empty_or_typing(editor, monkeypatch):
    from PySide6.QtWidgets import QDialog
    dialog, viewport, _root = editor
    dialog._select_attribute(())
    dialog.add_attribute('ferqgrb')

    def choose_centimeters(options):
        options.access.setCurrentIndex(options.access.findData('TEXTBOX'))
        options.units.setCurrentIndex(options.units.findData('CENTIMETERS'))
        return QDialog.Accepted

    monkeypatch.setattr(AttributeOptionsDialog, 'exec', choose_centimeters)
    dialog.edit_options()
    item_row = row(dialog, 'Door', 'ferqgrb')
    assert dialog.table.item(item_row, 1).data(Qt.UserRole + 4) == 'cm'
    click_attribute(dialog, 'Door', 'ferqgrb', column=1)
    cell = dialog._cell_editor
    assert cell.text() == '' and cell.unit_label.text() == 'cm'
    assert not cell.unit_label.isHidden()
    panel = ComponentOptionsPanel(SimpleNamespace(viewport=viewport))
    panel.refresh()
    field = next(w for opt, w, _initial in panel.rows if opt.name == 'ferqgrb')
    assert field.text() == '' and not field.unit_label.isHidden()
    field.setText('1532')
    assert not field.unit_label.isHidden() and field.unit_label.text() == 'cm'
    assert panel.collect()[0]['ferqgrb'] == pytest.approx(1532 / 2.54)
    QTest.keyClicks(cell, '1532')
    assert not cell.unit_label.isHidden()
    QTest.keyClick(cell, Qt.Key_Return)
    assert dialog.table.item(row(dialog, 'Door', 'ferqgrb'), 1).text() == '1532 cm'
    panel.refresh()
    field = next(w for opt, w, _initial in panel.rows if opt.name == 'ferqgrb')
    assert field.text() == '1532 cm' and field.unit_label.isHidden()
    panel.close()


def test_per_block_units_parse_typed_inches_and_keep_cross_component_references(editor):
    dialog, viewport, _root = editor
    QTest.mouseClick(dialog._unit_buttons[(1,)], Qt.LeftButton)
    assert dialog.table.item(row(dialog, 'Other', 'gap'), 1).text() == '7.874 in'
    assert dialog.table.item(row(dialog, 'Door', 'width'), 1).text() == '100 cm'
    click_attribute(dialog, 'Opening', 'derived', column=1)
    QTest.keyClicks(dialog._cell_editor, '=')
    assert not dialog.display_units_btn.isEnabled()
    click_attribute(dialog, 'Other', 'gap', column=1)
    assert dialog._cell_editor.text() == '=Other!gap'
    QTest.keyClick(dialog._cell_editor, Qt.Key_Return)
    assert dialog.table.item(row(dialog, 'Opening', 'derived'), 2).text() == '20 cm'
    click_attribute(dialog, 'Other', 'gap', column=1)
    QTest.keyClicks(dialog._cell_editor, '10')
    QTest.keyClick(dialog._cell_editor, Qt.Key_Return)
    assert float(_merged(dialog.root.children[1])['gap']) == pytest.approx(10)
    assert _merged(dialog.root.children[1])['_lengthunits'] == 'CENTIMETERS'
    assert dialog.table.item(row(dialog, 'Opening', 'derived'), 2).text() == '25.4 cm'
    assert len(viewport.history.undo_stack) == 2


def test_attribute_selection_uses_model_style_color_even_when_the_window_is_inactive(editor):
    dialog, viewport, _root = editor
    click_attribute(dialog, 'Opening', 'derived', column=1)
    cell = dialog._cell_editor
    QTest.keyClicks(cell, '=')
    viewport.scene.display_style.modeling_colors['selected'] = (.1, .7, .6)
    dialog._sync_root()
    for widget in (dialog.tree, dialog.table, dialog.formula_edit):
        for state in (QPalette.Active, QPalette.Inactive):
            assert widget.palette().color(state, QPalette.Highlight) == QColor.fromRgbF(.1, .7, .6)
    assert dialog._cell_editor is cell and cell.text() == '='
    assert not viewport.history.undo_stack


def test_attribute_window_follows_another_component_and_recovers_its_selection_color(editor):
    dialog, viewport, original = editor
    other, _child = door()
    other.name = 'Another component'
    viewport.scene.groups.append(other)
    viewport.scene.select([other])
    dialog._sync_root()
    assert dialog.root is other
    # A theme refresh can replace child widget palettes without changing the model style.
    blue = QPalette(dialog.table.palette())
    blue.setColor(QPalette.Highlight, QColor('blue'))
    dialog.table.setPalette(blue)
    dialog.tree.setPalette(blue)
    dialog._sync_root()
    expected = QColor.fromRgbF(.95, .45, .16)
    assert dialog.table.palette().color(QPalette.Highlight) == expected
    assert dialog.tree.palette().color(QPalette.Highlight) == expected
    viewport.scene.select([original])
    dialog._sync_root()
    assert dialog.root is original
    assert not viewport.history.undo_stack


def test_options_banner_has_a_component_picture_and_metadata_with_dense_single_line_rows():
    root, _moving = door()
    attrs = root.ext['skp_dc_import']['definition_attributes']
    attrs.update({'name': '<b>AP Door</b>', 'itemcode': '<i>AP-123</i>',
                  'summary': '<b>Settings</b>', 'description': 'A <i>dynamic</i> door',
                  '_itemcode_access': 'TEXTBOX'})
    for i in range(20):
        attrs.update({f'p{i}': i, f'_p{i}_access': 'TEXTBOX',
                      f'_p{i}_formlabel': 'Long parameter label on one line ' + str(i)})
    viewport = Viewport(root)
    panel = ComponentOptionsPanel(SimpleNamespace(viewport=viewport))
    panel.resize(560, 500)
    panel.show_group(root, True)
    panel.show()
    QApplication.processEvents()
    try:
        assert panel.title.text() == '<b>AP Door</b>' and panel.itemcode.text() == '<i>AP-123</i>'
        assert panel.description.text() == 'A <i>dynamic</i> door'
        assert panel.description.y() > panel.summary.y()
        assert panel.summary.font().bold()
        assert panel.summary.font().pointSizeF() > panel.description.font().pointSizeF()
        image = panel.preview.pixmap().toImage()
        assert not image.isNull()
        assert any(image.pixelColor(x, y).alpha() for x in range(image.width())
                   for y in range(image.height()))
        assert len(panel.rows) == 20 and all(opt.name != 'itemcode' for opt, _w, _initial in panel.rows)
        labels = [panel.form.labelForField(w) for _opt, w, _initial in panel.rows]
        assert all(not label.wordWrap() for label in labels)
        first, second = panel.rows[0][1], panel.rows[1][1]
        assert second.y() - first.y() <= first.height() + 4
        assert panel.scroll.verticalScrollBar().maximum() > 0
        left, right = panel.apply_btn.geometry().left(), panel.interact_btn.geometry().right()
        assert abs((left + right) / 2 - panel.width() / 2) < 2
        assert panel.banner.palette().color(panel.banner.backgroundRole()) != (
            panel.form_host.palette().color(panel.form_host.backgroundRole()))
        assert not viewport.history.undo_stack
        panel.show_group(None)
        assert panel.preview.isHidden() and panel.itemcode.isHidden()
    finally:
        panel.close()


def test_options_uses_the_interact_icon_instead_of_an_attributes_button():
    root, _moving = door()
    viewport = Viewport(root)
    called = []
    viewport.setFocus = lambda: called.append('focus')
    window = SimpleNamespace(viewport=viewport,
                             _activate_tool=lambda key: called.append(key),
                             activateWindow=lambda: None)
    panel = ComponentOptionsPanel(window)
    panel.show()
    QApplication.processEvents()
    panel.refresh()
    assert not panel.interact_btn.icon().isNull()
    assert all(button.text() != tr('Attributes…')
               for button in panel.findChildren(QPushButton))
    panel.interact_btn.click()
    assert called == ['interact', 'focus']
    assert panel.interact_btn.y() == panel.revert_btn.y()
    assert panel.interact_btn.x() > panel.revert_btn.x()
    panel.close()
