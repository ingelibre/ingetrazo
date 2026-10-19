import copy
import pytest
pytest.importorskip('PySide6')
from PySide6.QtCore import Qt
from test_qt_v02 import qtapp,panel,run_background
from go_structural_analysis.model import benchmark
from go_structural_analysis.model3d import cantilever3d
from go_structural_analysis.ui import Editor
from go_structural_analysis.combination_ui import CombinationManager
from go_structural_analysis.combination_tools import LoadingGenerator
from go_structural_analysis.member_graph_ui import MemberGraphDialog,MemberPlot
from go_structural_analysis.thai_code import apply_manager
from test_member_workflows import configuration

def test_both_methods_and_switch_preserves_presets(qtapp):
    dialog=CombinationManager(cantilever3d()); dialog.method.setCurrentText('ASD + LRFD')
    assert len(dialog.rows)==18
    for i,r in enumerate(dialog.rows):
        if r['id'] in ('TH2566-ASD-01','TH2566-LRFD-01'): dialog.table.item(i,0).setCheckState(Qt.CheckState.Checked)
    dialog.method.setCurrentText('Custom'); dialog.accept_model()
    assert dialog.result()==1,dialog.warning.text()
    assert set(dialog.data['combination_metadata'][n]['method'] for n in dialog.data['combinations'])=={'ASD','LRFD'}
    restored=CombinationManager(dialog.data); assert restored.method.currentText()=='ASD + LRFD'; assert len(restored.overview.rows)==2
    restored.close(); dialog.close()

def test_generator_adds_lrfd_without_losing_asd_custom(qtapp):
    model=apply_manager(cantilever3d(),configuration()); dialog=CombinationManager(model); generator=LoadingGenerator(dialog)
    generator.method.setCurrentText('LRFD'); generator.apply(); out=apply_manager(model,generator.data)
    assert out['combinations']['TH2566-ASD-01']=={'DL':1.,'LL':1.}
    assert 'TH2566-LRFD-01' in out['combinations'] and 'Service' in out['combinations']
    generator.close(); dialog.close()

@pytest.mark.parametrize('factory',[benchmark,cantilever3d])
def test_load_extent_full_length_and_geometry_edit(qtapp,factory):
    m=factory(); mid=m['members'][0]['id']; m['distributed_loads']=[dict(member=mid,direction='FZ',w1=-2,w2=-2,x1=.1,x2=.2,case=m['cases'][0])]
    dialog=Editor(m,None); t=dialog.tables['distributed_loads']; t.selectRow(0); dialog.update_load_extent()
    from go_structural_analysis.member_geometry import member_length
    length=member_length(m,mid); assert f'{length:.10g}' in dialog.load_extent.text()
    assert dialog.collect_data()['distributed_loads'][0]['x2']==.2
    dialog.full_length.click(); row=dialog.collect_data()['distributed_loads'][0]; assert row['x1']==0 and row['x2']==length
    node=dialog.tables['nodes']; col=dialog.fields['nodes'].index('z'); node.item(1,col).setText('7')
    assert dialog.selected_load_length()[2]!=length
    assert dialog.collect_data()['distributed_loads'][0]['x2']==length
    t.item(0,0).setText('missing'); assert not dialog.full_length.isEnabled(); dialog.close()

@pytest.mark.parametrize('factory',[benchmark,cantilever3d])
def test_graph_context_current_stale_no_input_mutation(panel,qtapp,factory):
    panel.put(factory()); run_background(panel,qtapp); mid=panel.model()['members'][0]['id']; before=copy.deepcopy(panel.model())
    menu=panel.commands.make_context_menu(mid); action=next(a for a in menu.actions() if a.data()=='member_graph'); assert action.isEnabled()
    action.trigger(); dialog=panel.member_graph_dialog; assert dialog.isVisible() and not dialog.isModal()
    dialog.ratio.setValue(.5); assert 'x=' in dialog.values.text()
    for i in range(dialog.quantity.count()): dialog.quantity.setCurrentIndex(i); dialog.grab()
    dialog.scope.setCurrentIndex(1); assert dialog.member.count()>=1 and panel.model()==before
    changed=copy.deepcopy(before); changed['nodes'][1]['z']+=.2; panel.put(changed); dialog.refresh()
    assert 'OUT OF DATE' in dialog.notice.text() and not dialog.values.text()
    assert not any(dialog.graphs.itemAt(i).widget() and isinstance(dialog.graphs.itemAt(i).widget(),MemberPlot) for i in range(dialog.graphs.count()))
    dialog.close(); menu.close()

@pytest.mark.parametrize('factory',[benchmark,cantilever3d])
def test_mixed_solver_superposition_envelopes_and_igz(panel,qtapp,factory,tmp_path):
    model=factory()
    if 'LL' not in model['cases']: model['cases'].append('LL')
    if 'DL' not in model['cases']:
        previous=model['cases'][0]; model['cases'][0]='DL'
        for kind in ('point_loads','distributed_loads'):
            for load in model.get(kind,[]):
                if load['case']==previous: load['case']='DL'
    model=apply_manager(model,configuration()); panel.put(model); run_background(panel,qtapp)
    assert {'ASD','LRFD','Custom'}<=set(panel.result['envelope_groups'])
    for group,identifier in [('ASD','TH2566-ASD-01'),('LRFD','TH2566-LRFD-01')]:
        assert panel.result['envelope_groups'][group]['combinations']==[identifier]
        factors=model['combinations'][identifier]
        for node,values in panel.result['cases'][identifier]['nodes'].items():
            for key in (('ux','uy','uz','rx','ry','rz') if model.get('schema')==2 else ('ux','uz','rotation','Rx','Rz','My')):
                expected=sum(factor*panel.result['cases'][case]['nodes'][node][key] for case,factor in factors.items())
                assert values[key]==pytest.approx(expected,rel=1e-8,abs=1e-9)
    from formats.igz import save_scene,load_into
    from core.scene import Scene
    scene=Scene(); scene.plugin_data['go_structural_analysis']=copy.deepcopy(panel.app.data)
    target=tmp_path/'mixed.igz'; save_scene(scene,target); restored=Scene(); load_into(restored,target)
    assert restored.plugin_data['go_structural_analysis']['model']['combination_manager']['methods']==['ASD','LRFD']
