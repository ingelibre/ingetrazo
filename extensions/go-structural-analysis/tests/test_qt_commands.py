import copy
import pytest
pytest.importorskip('PySide6')
from PySide6.QtCore import Qt,QPoint
from PySide6.QtGui import QContextMenuEvent
from PySide6.QtWidgets import QApplication,QMessageBox
from test_qt_v02 import panel,qtapp,run_background
from go_structural_analysis.model3d import cantilever3d

def actions(menu): return {a.data():a for a in menu.actions() if a.data()}

def test_search_keywords_empty_and_route(panel,qtapp):
    panel.put(cantilever3d()); before=copy.deepcopy(panel.model()); calls=[]; panel.open_combinations=lambda:calls.append('combination')
    panel.ribbon.buttons['search'].click(); dialog=panel.commands.dialog
    dialog.search.setText('ชุดรวมแรง'); assert dialog.list.topLevelItemCount()==1
    assert dialog.list.currentItem().data(0,Qt.ItemDataRole.UserRole)=='combinations'
    dialog.search.returnPressed.emit(); assert calls==['combination'] and not dialog.isVisible() and panel.model()==before
    panel.commands.show_search(); dialog.search.setText('no-such-command'); assert dialog.list.topLevelItemCount()==0 and not dialog.execute_button.isEnabled()
    dialog.search.setText('node coordinate'); assert dialog.list.topLevelItemCount()==1; dialog.close()

def test_current_export_guard_and_busy_recheck(panel,qtapp):
    panel.put(cantilever3d()); panel.commands.show_search(); dialog=panel.commands.dialog; dialog.search.setText('csv')
    assert not dialog.execute_button.isEnabled() and 'Current' in dialog.notice.text()
    calls=[]; panel.open_combinations=lambda:calls.append('combination'); dialog.search.setText('combinations')
    panel.job='Running'; dialog.activate(); assert not calls and 'Solver' in dialog.notice.text()
    assert not panel.commands.execute('combinations')
    panel.ribbon.refresh(); assert not panel.ribbon.buttons['combinations'].isEnabled() and not panel.ribbon.buttons['run'].isEnabled()
    panel.job=None; panel.redraw(); dialog.refresh(); assert dialog.execute_button.isEnabled(); dialog.close()

def test_selection_and_context_route(panel):
    panel.put(cantilever3d()); assert not panel.ribbon.buttons['edit_selected'].isEnabled()
    panel.select_entity('node:N1'); assert panel.ribbon.buttons['edit_selected'].isEnabled()
    calls=[]; panel.edit_selected=lambda:calls.append(panel.selected_entity)
    menu=panel.commands.make_context_menu('node:N2'); assert 'inspector' not in actions(menu)
    actions(menu)['edit_selected'].trigger(); assert calls==['node:N2']; menu.close()
    panel.select_entity('node:Missing'); panel.ribbon.refresh(); assert not panel.ribbon.buttons['edit_selected'].isEnabled()

def test_member_context_inspector_preserves_inputs(panel):
    panel.put(cantilever3d()); before=copy.deepcopy(panel.model()); mid=before['members'][0]['id']; menu=panel.commands.make_context_menu(mid)
    actions(menu)['inspector'].trigger()
    assert panel.tabs.currentIndex()==2 and panel.inspector.member.currentText()==mid and panel.model()==before; menu.close()

def test_context_action_keeps_original_target(panel):
    panel.put(cantilever3d()); calls=[]; panel.edit_selected=lambda:calls.append(panel.selected_entity)
    menu=panel.commands.make_context_menu('node:N1'); panel.select_entity('node:N2'); actions(menu)['edit_selected'].trigger()
    assert calls==['node:N1']
    d=copy.deepcopy(panel.model()); d['nodes'][0]['id']='Renamed'; d['members'][0]['i']='Renamed'; panel.put(d)
    actions(menu)['edit_selected'].trigger(); assert calls==['node:N1'] and 'เลือกใหม่' in panel.status.text(); menu.close()

def test_delete_confirmation_cancel_and_cascade(panel,monkeypatch):
    panel.put(cantilever3d()); before=copy.deepcopy(panel.model()); captured=[]
    def cancel(*args): captured.append(args[2]); return QMessageBox.StandardButton.No
    monkeypatch.setattr(QMessageBox,'question',cancel)
    menu=panel.commands.make_context_menu('node:N2'); actions(menu)['delete_selected'].trigger()
    assert panel.model()==before and 'Member 1' in captured[0] and 'Node' in captured[0]
    monkeypatch.setattr(QMessageBox,'question',lambda *args:QMessageBox.StandardButton.Yes)
    actions(menu)['delete_selected'].trigger(); assert panel.model() is None and panel.selected_entity is None; menu.close()

def test_tree_filter_preserved_on_refresh(panel):
    panel.put(cantilever3d()); before=copy.deepcopy(panel.model()); panel.tree_search.setText('nodes N2')
    nodes=panel.model_tree.topLevelItem(0); members=panel.model_tree.topLevelItem(1)
    assert nodes.child(0).isHidden() and not nodes.child(1).isHidden() and members.isHidden() and panel.model()==before
    d=copy.deepcopy(panel.model()); d['nodes'][1]['x']+=1; panel.put(d)
    assert panel.model_tree.topLevelItem(0).child(0).isHidden() and not panel.model_tree.topLevelItem(0).child(1).isHidden()
    panel.tree_search.clear(); assert not panel.model_tree.topLevelItem(1).isHidden()

def test_viewport_context_event_node_selection(panel,qtapp):
    panel.put(cantilever3d()); px,py,_=panel.app.world_to_pixels([[0,0,0]])
    pos=QPoint(int(px[0]),int(py[0])); event=QContextMenuEvent(QContextMenuEvent.Reason.Mouse,pos,panel.app.viewport.mapToGlobal(pos))
    QApplication.sendEvent(panel.app.viewport,event)
    assert panel.selected_entity=='node:N1' and panel.commands.menu is not None
    assert actions(panel.commands.menu)['edit_selected'].isEnabled(); panel.commands.menu.close()

def test_search_export_current_then_stale(panel,qtapp):
    panel.put(cantilever3d()); run_background(panel,qtapp); panel.commands.show_search(); dialog=panel.commands.dialog; dialog.search.setText('csv')
    assert dialog.execute_button.isEnabled()
    d=copy.deepcopy(panel.model()); d['nodes'][1]['x']+=1; panel.put(d); dialog.activate()
    assert panel.result_status()=='Stale' and not dialog.execute_button.isEnabled() and 'Current' in dialog.notice.text(); dialog.close()
