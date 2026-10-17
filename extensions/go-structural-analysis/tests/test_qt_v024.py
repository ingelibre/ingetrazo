import copy
import json
import pytest
from test_qt_v02 import panel,qtapp,run_background
from go_structural_analysis.combination_ui import CombinationManager
from go_structural_analysis.thai_code import presets,apply_manager
from go_structural_analysis.model3d import cantilever3d
from go_structural_analysis.model import benchmark
from go_structural_analysis.ui import Editor
from go_structural_analysis.display import LabelPlacer,format_value,axes_visible
from PySide6.QtGui import QFontMetrics,QVector3D
from PySide6.QtCore import QPointF,Qt

def test_manager_missing_clone_readonly(qtapp):
    d=cantilever3d(); dialog=CombinationManager(d)
    dialog.method.setCurrentText('LRFD'); assert len(dialog.rows)==11
    assert 'Missing' in dialog.table.item(3,2).text() or 'Disabled' in dialog.table.item(3,2).text()
    assert not dialog.table.item(3,0).flags()&Qt.ItemFlag.ItemIsEnabled
    dialog.table.setCurrentCell(0,1); dialog.custom_name.setText('Edited custom'); dialog.clone()
    custom=json.loads(dialog.custom.toPlainText()); custom['Edited custom']['factors']['DL']=2.
    dialog.custom.setPlainText(json.dumps(custom)); dialog.enabled={presets('LRFD')[0]['id']}; dialog.accept_model()
    assert dialog.result()==1,dialog.warning.text()
    assert dialog.data['combinations']['Edited custom']['DL']==2.
    assert dialog.data['combinations']['TH2566-LRFD-01']['DL']==1.4
    editor=Editor(dialog.data,None); editor.accept_model()
    assert editor.result()==1,editor.error.text()
    assert editor.data['combination_manager']==dialog.data['combination_manager']
    dialog.close(); editor.close()

def test_display_collision_and_scale(qtapp):
    metrics=QFontMetrics(qtapp.font()); placer=LabelPlacer(800,600,metrics,'Normal')
    for i in range(100): placer.place(QPointF(400,300),'Member label '+str(i))
    assert len(placer.rects)>1
    assert all(placer.bounds.contains(r) for r in placer.rects)
    assert all(not a.intersects(b) for i,a in enumerate(placer.rects) for b in placer.rects[i+1:])
    assert '≈0' in format_value(1e-7,'N',100,1e-6)
    assert '≈0' not in format_value(1e-7,'N',.001,1e-6)
    assert format_value(.001,'D',1,0)=='1 mm'

def test_display_independent_and_axes_defaults(panel,qtapp):
    d=cantilever3d(); panel.put(d); run_background(panel,qtapp)
    snapshot=copy.deepcopy(panel.result); model=copy.deepcopy(panel.model())
    assert panel.axes_mode.currentText()=='Selected'
    assert axes_visible(panel,'B1') and not axes_visible(panel,'unknown')
    panel.axes_mode.setCurrentText('None'); assert not axes_visible(panel,'B1')
    panel.axes_mode.setCurrentText('All'); assert axes_visible(panel,'B1')
    for mode in ('N','T','D','Deformed'): panel.diagram.setCurrentText(mode); panel.canvas.repaint()
    panel.display_tolerance.setValue(.01); panel.scale.setValue(500); panel.labels.setChecked(False)
    assert panel.result==snapshot and panel.model()==model
    panel.restore_display(); assert panel.scale.value()==100 and panel.labels.isChecked()
    for section in panel.sections.values(): section.toggle.setChecked(False); assert section.body.isHidden(); section.toggle.setChecked(True)
    assert panel.quick.case.currentText()==panel.case.currentText()

def test_geometry_failure_and_report_gate(panel,qtapp):
    panel.put(cantilever3d()); run_background(panel,qtapp)
    assert panel.result_status()=='Current' and panel.report_button.isEnabled()
    panel.app.scene.edges=[type('Edge',(),dict(a=QVector3D(),b=QVector3D(1,2,3)))()]
    panel.redraw(); assert panel.result_status()=='Stale' and not panel.inspector.csv.isEnabled()
    panel.record_failure('test failure'); assert panel.result_status()=='Failed'
    assert not panel.report_button.isEnabled() and not panel.inspector.csv.isEnabled()
    assert panel.data()['analysis_state']['state']=='Failed'
    assert panel.inspector.archive.isEnabled()

@pytest.mark.parametrize('dimension',[2,3])
def test_code_manager_result_envelope_ui(panel,qtapp,dimension):
    d=benchmark() if dimension==2 else cantilever3d()
    if dimension==2:
        d['cases']=['DL','LL']; d['distributed_loads'][0]['case']='DL'
    c=dict(method='ASD',bindings={'D':['DL'],'L':['LL']},enabled=['TH2566-ASD-01'],custom={'Reverse':{'factors':{'DL':-1,'LL':-1}}})
    panel.put(apply_manager(d,c)); run_background(panel,qtapp)
    assert 'ASD' in panel.result['envelope_groups'] and 'Custom' in panel.result['envelope_groups']
    panel.envelope_group.setCurrentText('ASD'); panel.inspector.envelope.setChecked(True)
    assert 'TH2566-ASD-01' in panel.inspector.values.text()
    panel.inspector.show_tables(); assert panel.inspector.dialog.tables['Member Force Envelope'].rowCount()>0

def test_geometry_fingerprint_transform_values(panel):
    from PySide6.QtGui import QMatrix4x4
    vertex=type('Vertex',(),dict(position=QVector3D(1,2,3)))()
    group=type('Group',(),dict(name='Test',mesh=type('Mesh',(),dict(vertices=[vertex],edges=[],faces=[]))(),xform=QMatrix4x4(),children=[]))()
    panel.app.scene.groups=[group]
    first=panel.geometry_token(); group.xform=QMatrix4x4(group.xform)
    assert panel.geometry_token()==first
    vertex.position.setX(2); assert panel.geometry_token()!=first

def test_migration_editor_protection_and_duplicate_weight_feedback(panel):
    from go_structural_analysis.model3d import migrate2d
    d=benchmark(); d.update(cases=['DL','LL'],distributed_loads=[],self_weight=True,self_weight_case='DL')
    d=apply_manager(d,dict(method='ASD',bindings={'D':['DL'],'L':['LL']},enabled=['TH2566-ASD-01'],custom={}))
    converted=migrate2d(d); panel.put(converted); editor=Editor(converted,None)
    assert editor.combinations.isReadOnly()
    panel.set_weight(True)
    assert not panel.model()['self_weight'] and 'Self-weight rejected' in panel.status.text()
    editor.close()
