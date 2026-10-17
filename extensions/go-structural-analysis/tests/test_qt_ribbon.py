import copy
import pytest
pytest.importorskip('PySide6')
from test_qt_v02 import panel,qtapp,run_background
from go_structural_analysis.model3d import cantilever3d

def test_ribbon_delegates_existing_forms(panel):
    panel.put(cantilever3d()); calls=[]
    panel.edit=lambda key:calls.append(('case',key))
    panel.edit_section=lambda key:calls.append(('section',key))
    panel.open_combinations=lambda:calls.append(('combination',None))
    for key in ('cases','combinations','point_loads','nodes'): panel.ribbon.buttons[key].click()
    assert calls==[('case','cases'),('combination',None),('section','point_loads'),('section','nodes')]

def test_ribbon_navigation_and_display_preserve_inputs(panel):
    panel.put(cantilever3d()); before=copy.deepcopy(panel.model())
    for index,target in ((1,1),(2,0),(3,2),(4,2),(0,0)):
        panel.ribbon.tabs.setCurrentIndex(index); assert panel.tabs.currentIndex()==target and panel.ribbon.pages.currentIndex()==index
    panel.tabs.setCurrentIndex(1); assert panel.ribbon.tabs.currentIndex()==1
    panel.ribbon.buttons['defaults'].click(); assert panel.model()==before

def test_ribbon_collapse_resize_and_panel_hide(panel,qtapp):
    panel.put(cantilever3d()); ribbon=panel.ribbon; original=ribbon.height()
    ribbon.collapse.setChecked(True); qtapp.processEvents()
    assert ribbon.pages.isHidden() and ribbon.height()<original
    panel.app.viewport.resize(460,600); qtapp.processEvents(); assert ribbon.width()==440
    panel.ribbon.buttons['panel'].click(); assert not panel.dock.isVisible() and ribbon.isVisible()
    panel.ribbon.buttons['panel'].click(); assert panel.dock.isVisible()
    ribbon.collapse.setChecked(False); assert not ribbon.pages.isHidden()

def test_ribbon_result_safety_and_background_run(panel,qtapp):
    panel.put(cantilever3d()); ribbon=panel.ribbon
    assert not ribbon.buttons['csv'].isEnabled() and not ribbon.buttons['report'].isEnabled()
    run_background(panel,qtapp); ribbon.refresh()
    assert ribbon.buttons['csv'].isEnabled() and ribbon.buttons['report'].isEnabled()
    before=copy.deepcopy(panel.result); ribbon.tabs.setCurrentIndex(4); ribbon.buttons['defaults'].click(); assert panel.result==before
    d=copy.deepcopy(panel.model()); d['nodes'][1]['x']+=1; panel.put(d)
    assert ribbon.status.text()=='Stale' and not ribbon.buttons['csv'].isEnabled() and not ribbon.buttons['report'].isEnabled()

def test_ribbon_inspector_and_themes(panel,qtapp):
    panel.put(cantilever3d()); panel.sections['Result Inspector'].toggle.setChecked(False)
    panel.ribbon.buttons['inspector'].click(); assert panel.tabs.currentIndex()==2 and panel.sections['Result Inspector'].toggle.isChecked()
    for theme in ('Light','Dark','System'):
        panel.theme_choice.setCurrentText(theme); qtapp.processEvents(); panel.ribbon.refresh()
        assert panel.ribbon.palette().color(panel.ribbon.backgroundRole())==panel.palette().color(panel.backgroundRole())
