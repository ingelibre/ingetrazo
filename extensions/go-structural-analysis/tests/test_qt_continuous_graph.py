import copy
import pytest
pytest.importorskip('PySide6')
from PySide6.QtCore import Qt,QPoint
from PySide6.QtTest import QTest
from test_qt_v02 import qtapp,panel,run_background
from test_continuous_graph import split
from go_structural_analysis.model3d import cantilever3d
from go_structural_analysis.member_graph_ui import MemberGraphDialog,MemberPlot

def visible_plots(dialog): return [w for w in dialog.body.findChildren(MemberPlot) if not w.isHidden()]

@pytest.mark.parametrize('reverse',[False,True])
def test_one_continuous_axis_station_click_signed_components_and_stale(panel,qtapp,reverse):
    model=cantilever3d(); model['distributed_loads']=[]; model=split(model,reverse)
    panel.put(model); run_background(panel,qtapp); before=copy.deepcopy(panel.model())
    dialog=MemberGraphDialog(panel,'A'); dialog.show(); dialog.scope.setCurrentIndex(1); qtapp.processEvents()
    assert len(visible_plots(dialog))==1
    assert dialog.chain_data['L']==pytest.approx(4)
    assert 'total L=4 m' in dialog.notice.text()
    assert [r['id'] for r in dialog.chain_data['records']]==['A','B']
    for i in range(dialog.quantity.count()):
        dialog.quantity.setCurrentIndex(i); qtapp.processEvents(); dialog.grab()
        assert len(visible_plots(dialog))==1
    plot=visible_plots(dialog)[0]; x=65+.75*(plot.width()-90)
    QTest.mouseClick(plot,Qt.MouseButton.LeftButton,pos=QPoint(round(x),plot.height()//2)); qtapp.processEvents()
    assert dialog.member.currentText()=='B'
    assert dialog.ratio.value()==pytest.approx(.5,abs=.003)
    assert 's=' in dialog.values.text()
    dialog.side.setCurrentText('left'); dialog.select_station(2); assert dialog.member.currentText()=='A'
    dialog.side.setCurrentText('right'); dialog.select_station(2); assert dialog.member.currentText()=='B'
    assert dialog.ratio.value()==(1 if reverse else 0)
    assert panel.model()==before
    changed=copy.deepcopy(before); changed['nodes'][1]['z']+=.1; panel.put(changed); dialog.refresh()
    assert not visible_plots(dialog) and dialog.chain_data is None and 'OUT OF DATE' in dialog.notice.text()
    dialog.close()

def test_many_members_horizontal_scroll_and_single_mode_preserved(panel,qtapp):
    model=cantilever3d(); model['distributed_loads']=[]; model['point_loads']=[]
    template=model['members'][0]; model['members']=[]
    model['nodes']=[dict(id=f'N{i}',x=i,y=0,z=0,support='Fixed' if i==0 else 'Free') for i in range(7)]
    for i in range(6): model['members'].append(dict(template,id=f'B{i}',i=f'N{i}',j=f'N{i+1}'))
    model['point_loads']=[dict(node='N6',direction='FZ',value=-10,case='DL')]
    panel.put(model); run_background(panel,qtapp); assert panel.results_are_current(),panel.status.text()
    dialog=MemberGraphDialog(panel,'B2'); dialog.show(); qtapp.processEvents()
    assert len(visible_plots(dialog))==1 and visible_plots(dialog)[0].continuous is None
    dialog.scope.setCurrentIndex(1); qtapp.processEvents()
    plot=visible_plots(dialog)[0]; assert plot.minimumWidth()>=1320 and len(dialog.chain_data['records'])==6
    from PySide6.QtWidgets import QScrollArea
    scroll=dialog.findChild(QScrollArea); assert scroll.horizontalScrollBar().maximum()>0
    dialog.scope.setCurrentIndex(0); qtapp.processEvents(); assert visible_plots(dialog)[0].continuous is None
    dialog.close()
