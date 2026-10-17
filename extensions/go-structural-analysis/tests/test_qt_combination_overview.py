import copy,json
import pytest
pytest.importorskip('PySide6')
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QStyleOptionViewItem
from PySide6.QtTest import QTest
from test_qt_v02 import qtapp,panel,run_background
from go_structural_analysis.model import benchmark
from go_structural_analysis.model3d import cantilever3d
from go_structural_analysis.combination_ui import CombinationManager,FactorInput
from go_structural_analysis.combination_tools import LoadingGenerator,FactorDelegate
from go_structural_analysis.thai_code import apply_manager

def add(dialog,name): dialog.new_custom_name.setText(name); dialog.add_custom()
def row(dialog,name): return next(i for i,r in enumerate(dialog.overview.rows) if r['name']==name)

def test_matrix_edits_multiple_rows_and_disable(qtapp):
    dialog=CombinationManager(cantilever3d()); add(dialog,'Gravity'); add(dialog,'Wind')
    t=dialog.overview.table; t.item(row(dialog,'Gravity'),3).setText('1.4'); t.item(row(dialog,'Gravity'),4).setText('1.7')
    t.item(row(dialog,'Wind'),5).setText('-.6'); t.item(row(dialog,'Wind'),0).setCheckState(Qt.CheckState.Unchecked)
    config=dialog.config()['custom']; assert config['Gravity']['factors']=={'DL':1.4,'LL':1.7}
    assert config['Wind']['factors']=={'DL':1.,'WX':-.6} and not config['Wind']['enabled']
    dialog.accept_model(); assert dialog.result()==1,dialog.warning.text(); assert dialog.data['combinations']=={'Gravity':{'DL':1.4,'LL':1.7}}; dialog.close()

def test_matrix_precision_delegate_no_edit_and_filter(qtapp):
    d=cantilever3d(); d['combinations']={'Original':{'DL':1.2345678901234567}}
    dialog=CombinationManager(d); table=dialog.overview.table; index=table.model().index(0,3); delegate=table.itemDelegateForColumn(3)
    editor=delegate.createEditor(table,QStyleOptionViewItem(),index); delegate.setEditorData(editor,index); delegate.setModelData(editor,table.model(),index)
    assert dialog.config()['custom']['Original']['factors']['DL']==1.2345678901234567
    dialog.overview.search.setText('no-match'); assert table.isRowHidden(0)
    dialog.overview.search.clear(); assert not table.isRowHidden(0); editor.close(); dialog.close()

def test_matrix_numeric_editor_enter_commits(qtapp):
    dialog=CombinationManager(cantilever3d()); add(dialog,'Typed'); dialog.show(); qtapp.processEvents()
    table=dialog.overview.table; table.editItem(table.item(0,3)); qtapp.processEvents(); editor=table.findChild(FactorInput)
    assert editor is not None; editor.setValue(2.4); QTest.keyClick(editor,Qt.Key.Key_Return); qtapp.processEvents()
    assert dialog.config()['custom']['Typed']['factors']['DL']==2.4 and table.currentRow()==0; dialog.close()

def test_matrix_duplicate_and_protected_clone(qtapp):
    d=apply_manager(cantilever3d(),dict(method='LRFD',bindings={'D':['DL'],'L':['LL'],'W':['WX']},enabled=['TH2566-LRFD-01'],custom={}))
    dialog=CombinationManager(d); t=dialog.overview.table
    assert not t.item(0,3).flags()&Qt.ItemFlag.ItemIsEditable
    dialog.overview.duplicate(); custom=dialog.config()['custom']; name=next(iter(custom))
    assert not name.startswith('TH2566-') and custom[name]['cloned_from']=='TH2566-LRFD-01'
    t.item(row(dialog,name),3).setText('2')
    assert dialog.config()['custom'][name]['factors']['DL']==2 and d['combinations']['TH2566-LRFD-01']['DL']==1.4
    dialog.accept_model(); assert dialog.data['combinations']['TH2566-LRFD-01']['DL']==1.4; dialog.close()

def test_first_custom_from_protected_selects_new_row(qtapp):
    d=apply_manager(cantilever3d(),dict(method='LRFD',bindings={'D':['DL'],'L':['LL'],'W':['WX']},enabled=['TH2566-LRFD-01'],custom={}))
    dialog=CombinationManager(d); add(dialog,'New Custom')
    assert dialog.overview.rows[dialog.overview.table.currentRow()]['name']=='New Custom'
    dialog.overview.duplicate()
    assert 'New Custom copy' in dialog.config()['custom'] and dialog.overview.rows[dialog.overview.table.currentRow()]['name']=='New Custom copy'; dialog.close()

def test_protected_selection_disables_custom_operations(qtapp):
    d=apply_manager(cantilever3d(),dict(method='LRFD',bindings={'D':['DL'],'L':['LL'],'W':['WX']},enabled=['TH2566-LRFD-01'],custom={}))
    dialog=CombinationManager(d); add(dialog,'New'); protected=next(i for i,r in enumerate(dialog.overview.rows) if r['origin']!='Custom'); dialog.overview.table.setCurrentCell(protected,1)
    assert not dialog.rename_custom_button.isEnabled() and not dialog.remove_custom_button.isEnabled() and not dialog.custom_factors.isEnabled()
    assert '1.4 × DL + 1.7 × LL' in dialog.custom_formula.text()
    dialog.overview.table.setCurrentCell(row(dialog,'New'),1); assert dialog.rename_custom_button.isEnabled(); dialog.close()

def test_matrix_invalid_factor_and_empty_rejected(qtapp):
    dialog=CombinationManager(cantilever3d()); add(dialog,'Invalid'); dialog.overview.table.item(0,3).setText('nan'); dialog.accept_model()
    assert dialog.result()==0 and dialog.custom_error
    dialog.overview.table.item(0,3).setText('0'); dialog.accept_model(); assert dialog.result()==0 and not dialog.config()['custom']['Invalid']['factors']; dialog.close()

def test_generator_golden_factors_and_missing(qtapp):
    dialog=CombinationManager(cantilever3d()); add(dialog,'Original'); generator=LoadingGenerator(dialog)
    generator.method.setCurrentText('LRFD'); generator.apply(); assert generator.result()==1
    compiled=apply_manager(dialog.original,generator.data)['combinations']
    factors=list(compiled.values())
    assert {'DL':1.4,'LL':1.7} in factors
    assert any(f['DL']==pytest.approx(1.05) and f['LL']==pytest.approx(1.275) and f['WX']==1.6 for f in factors if 'WX' in f and 'LL' in f)
    assert {'DL':.9,'WX':1.6} in factors and compiled['Original']=={'DL':1.}
    assert not generator.table.item(3,0).flags()&Qt.ItemFlag.ItemIsEnabled and 'Missing' in generator.table.item(3,2).text()
    generator.close(); dialog.close()

def test_generator_cancel_no_case_creation_and_direction_alternatives(qtapp):
    d=cantilever3d(); d['cases']+=['WX-','WY+','WY-']; before=copy.deepcopy(d); dialog=CombinationManager(d); generator=LoadingGenerator(dialog)
    generator.apply(); compiled=apply_manager(d,generator.data)
    for name,factors in compiled['combinations'].items(): assert len(set(factors)&{'WX','WX-','WY+','WY-'})<=1
    assert compiled['cases']==before['cases']; generator.reject(); assert dialog.original==before; dialog.close()

def test_details_sync_matrix_and_selected_duplicate(qtapp):
    dialog=CombinationManager(cantilever3d()); add(dialog,'First'); add(dialog,'Second')
    assert dialog.overview.rows[dialog.overview.table.currentRow()]['name']=='Second'
    dialog.custom_factors.cellWidget(0,1).setValue(2.3)
    assert float(dialog.overview.table.item(row(dialog,'Second'),3).text())==2.3
    dialog.overview.duplicate(); assert dialog.config()['custom']['Second copy']['factors']['DL']==2.3; dialog.close()

@pytest.mark.parametrize('model',[benchmark,cantilever3d])
def test_matrix_2d_3d_background_superposition(panel,qtapp,model):
    dialog=CombinationManager(model()); cases=dialog.original['cases']; add(dialog,'Combined')
    dialog.overview.table.item(0,3).setText('1.4')
    dialog.accept_model(); assert dialog.result()==1,dialog.warning.text(); panel.put(dialog.data); run_background(panel,qtapp)
    values=panel.result['cases']; node='N2' if model==cantilever3d else next(iter(values[cases[0]]['nodes'])); key='uz' if model==cantilever3d else 'Rz'
    assert values['Combined']['nodes'][node][key]==pytest.approx(1.4*values[cases[0]]['nodes'][node][key]); dialog.close()

def test_matrix_save_invalidates_current_results(panel,qtapp):
    panel.put(cantilever3d()); run_background(panel,qtapp)
    dialog=CombinationManager(panel.model()); add(dialog,'New combination'); dialog.overview.table.item(0,3).setText('1.4'); dialog.accept_model(); panel.put(dialog.data)
    assert panel.result_status()=='Stale' and not panel.inspector.csv.isEnabled() and not panel.report_button.isEnabled(); dialog.close()
