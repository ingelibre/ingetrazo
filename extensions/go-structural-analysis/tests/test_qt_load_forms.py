import copy,json
import pytest
pytest.importorskip('PySide6')
from test_qt_v02 import panel,qtapp,run_background
from go_structural_analysis.model3d import cantilever3d
from go_structural_analysis.load_case_ui import LoadCaseManager,remap_cases
from go_structural_analysis.combination_ui import CombinationManager
from go_structural_analysis.thai_code import apply_manager
from go_structural_analysis.ui import Editor

def test_case_rename_updates_protected_combinations_and_weight(qtapp):
    d=cantilever3d(); d.update(self_weight=True)
    d=apply_manager(d,dict(method='ASD',bindings={'D':['DL'],'L':['LL']},enabled=['TH2566-ASD-01'],custom={'Custom':dict(factors={'DL':1.4,'LL':1.7})}))
    old=copy.deepcopy(d); renamed=remap_cases(d,{c:('Dead' if c=='DL' else c) for c in d['cases']})
    assert d==old and renamed['self_weight_case']=='Dead'
    assert renamed['point_loads'][1]['case']=='Dead'
    assert renamed['combinations']['Custom']=={'Dead':1.4,'LL':1.7}
    assert renamed['combination_metadata']['TH2566-ASD-01']['factors']=={'Dead':1.,'LL':1.}
    with pytest.raises(ValueError,match='ลบไม่ได้'): remap_cases(d,{c:c for c in d['cases'] if c!='DL'})

def test_case_form_add_remove_and_duplicate(qtapp):
    dialog=LoadCaseManager(cantilever3d()); dialog.add('ROOF'); dialog.apply()
    assert dialog.result()==1 and 'ROOF' in dialog.data['cases']; dialog.close()
    dialog=LoadCaseManager(cantilever3d()); dialog.table.item(1,0).setText('DL'); dialog.apply()
    assert dialog.result()==0 and 'ไม่ซ้ำ' in dialog.error.text(); dialog.close()

def test_unused_self_weight_case_can_be_removed(qtapp):
    d=cantilever3d(); d['cases'].append('Unused'); d.update(self_weight=False,self_weight_case='Unused')
    renamed=remap_cases(d,{c:c for c in d['cases'] if c!='Unused'})
    assert renamed['self_weight_case']=='DL' and d['self_weight_case']=='Unused'

def test_house_visible_form_adds_independent_combination(qtapp):
    from go_structural_analysis.house_example import house_model
    dialog=CombinationManager(house_model()); dialog.show(); qtapp.processEvents()
    original=copy.deepcopy(json.loads(dialog.custom.toPlainText()))
    dialog.new_custom_name.setText('QA Gravity'); dialog.add_custom()
    dialog.custom_factors.cellWidget(0,1).setValue(1.4); dialog.custom_factors.cellWidget(1,1).setValue(1.7)
    assert '1.4 × DL + 1.7 × LL' in dialog.custom_formula.text(),dialog.custom_formula.text()
    assert dialog.custom.isHidden()
    current=json.loads(dialog.custom.toPlainText())
    assert current['QA Gravity']['factors']=={'DL':1.4,'LL':1.7}
    assert all(current[k]==v for k,v in original.items())
    dialog.accept_model(); assert dialog.result()==1,dialog.warning.text(); dialog.close()

def test_numeric_custom_formula_and_no_json(qtapp):
    dialog=CombinationManager(cantilever3d()); assert dialog.method.currentText()=='Custom' and dialog.pages.currentIndex()==2
    dialog.new_custom_name.setText('Gravity'); dialog.add_custom()
    dialog.custom_factors.cellWidget(0,1).setValue(1.4); dialog.custom_factors.cellWidget(1,1).setValue(1.7)
    dialog.custom_factors.cellWidget(2,1).setValue(-.6)
    assert '1.4 × DL + 1.7 × LL' in dialog.custom_formula.text() and '− 0.6 × WX' in dialog.custom_formula.text()
    assert dialog.custom.isHidden()
    dialog.accept_model(); assert dialog.result()==1,dialog.warning.text()
    assert dialog.data['combinations']['Gravity']=={'DL':1.4,'LL':1.7,'WX':-.6}; dialog.close()

def test_checkbox_bindings_and_clone_protection(qtapp):
    dialog=CombinationManager(cantilever3d()); dialog.method.setCurrentText('LRFD')
    dialog.table.setCurrentCell(0,1); dialog.custom_name.setText('Cloned'); dialog.clone()
    dialog.custom_choice.setCurrentText('Cloned'); dialog.custom_factors.cellWidget(0,1).setValue(2)
    assert dialog.rows[0]['factors']['D']==1.4
    option=next(o for o in dialog.binding_choices['W'] if o.text()=='WX'); option.setChecked(False)
    assert option.text() not in dialog.config()['bindings']['W']; dialog.close()

def test_custom_rename_remove_cancel_and_precision(qtapp):
    d=cantilever3d(); d['combinations']={'Original':{'DL':1.2345678901234567}}; old=copy.deepcopy(d)
    dialog=CombinationManager(d); assert json.loads(dialog.custom.toPlainText())['Original']['factors']['DL']==1.2345678901234567
    dialog.new_custom_name.setText('Renamed'); dialog.rename_custom(); assert dialog.custom_choice.currentText()=='Renamed'
    dialog.remove_custom(); assert not json.loads(dialog.custom.toPlainText()); dialog.reject(); assert d==old; dialog.close()

def test_editor_has_forms_and_solver_superposition(panel,qtapp):
    editor=Editor(cantilever3d(),None); assert editor.cases.isHidden() and editor.combinations.isHidden() and editor.combination_button.text().startswith('Load Combinations'); editor.accept_model(); assert editor.result()==1; editor.close()
    dialog=CombinationManager(cantilever3d()); dialog.new_custom_name.setText('Gravity'); dialog.add_custom(); dialog.custom_factors.cellWidget(0,1).setValue(1.4); dialog.custom_factors.cellWidget(1,1).setValue(1.7); dialog.accept_model()
    panel.put(dialog.data); run_background(panel,qtapp)
    r=panel.result['cases']; assert r['Gravity']['nodes']['N2']['uz']==pytest.approx(1.4*r['DL']['nodes']['N2']['uz']+1.7*r['LL']['nodes']['N2']['uz']); dialog.close()

def test_case_names_with_comma_and_stale_on_rename(panel,qtapp):
    d=cantilever3d(); names={c:('Dead, floor' if c=='DL' else c) for c in d['cases']}; d=remap_cases(d,names)
    d=apply_manager(d,dict(method='ASD',bindings={'D':['Dead, floor'],'L':['LL']},enabled=['TH2566-ASD-01'],custom={}))
    dialog=CombinationManager(d); assert dialog.config()['bindings']['D']==['Dead, floor']; dialog.accept_model(); assert dialog.result()==1; dialog.close()
    panel.put(d); run_background(panel,qtapp)
    d=remap_cases(d,{c:('Dead revised' if c=='Dead, floor' else c) for c in d['cases']}); panel.put(d)
    assert panel.result_status()=='Stale' and not panel.inspector.csv.isEnabled()
    editor=Editor(d,None); t=editor.tables['point_loads']; casecol=editor.fields['point_loads'].index('case'); assert t.cellWidget(1,casecol).currentText()=='Dead revised'; editor.close()
