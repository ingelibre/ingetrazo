"""Offscreen Qt QA with a test app adapter. Does not claim installed-host QA."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import copy
import json
import math
import sys
import time
from pathlib import Path
import pytest
pytest.importorskip('PySide6')
from PySide6.QtWidgets import QApplication,QWidget,QDockWidget
from PySide6.QtCore import QPointF,QEvent,Qt,QTimer
from PySide6.QtGui import QImage,QPainter,QColor,QVector3D,QMouseEvent,QFontDatabase,QFont
import numpy as np
ROOT=Path(__file__).parents[1]; sys.path.insert(0,str(ROOT))
HOST=Path(os.environ.get('INGETRAZO_QA_SOURCE',str(ROOT.parent/'ingetrazo-api-reference')))
if not (HOST/'views/theme.py').is_file(): pytest.skip('Set INGETRAZO_QA_SOURCE to host source for offscreen adapter QA',allow_module_level=True)
sys.path.insert(0,str(HOST))
from go_structural_analysis.ui import Panel,Editor,setup
from go_structural_analysis.model import benchmark
from go_structural_analysis.model3d import cantilever3d
from go_structural_analysis.examples3d import example3d,CATALOG3D
from go_structural_analysis.results import is_current
from go_structural_analysis import visualization

class FakeApp:
    api_version=2
    def __init__(self):
        self.window=QWidget(); self.window.resize(1200,800); self.viewport=QWidget(self.window); self.viewport.resize(1000,700)
        self.viewport.camera=type('Camera',(),dict(target=QVector3D(),yaw=-.8,pitch=.45,perspective=False,distance=20))()
        self.scene=type('Scene',(),dict(plugin_data={},selection=[]))(); self.data={}; self.callbacks=[]; self._workspace=None
        self.window.set_tool_filter=lambda allowed:setattr(self.window,'tool_filter',set(allowed))
    def document_data(self,default=None): return copy.deepcopy(self.data) if self.data else default
    def set_document_data(self,data):
        self.data=copy.deepcopy(data)
        for callback in self.callbacks: callback()
    def on_document_changed(self,fn): self.callbacks.append(fn)
    def add_overlay(self,fn): self.overlay=fn
    def add_pickable(self,*args,**kwargs): self.pickable=kwargs
    def workspace(self): return self._workspace
    def add_panel(self,name,panel):
        dock=QDockWidget(name,self.window); dock.setWidget(panel); return dock
    def add_menu_action(self,*args,**kwargs): return None
    def show_panel(self,dock): dock.show()
    def world_to_pixels(self,points):
        c=self.viewport.camera; p=np.asarray(points,dtype=float)-np.asarray(c.target.toTuple()); yaw,pitch=c.yaw,c.pitch
        right=np.array([math.cos(yaw),math.sin(yaw),0]); up=np.array([-math.sin(yaw)*math.sin(pitch),math.cos(yaw)*math.sin(pitch),math.cos(pitch)])
        scale=1000/c.distance; return 500+scale*(p@right),350-scale*(p@up),np.ones(len(p),dtype=bool)

@pytest.fixture(scope='module')
def qtapp():
    app=QApplication.instance() or QApplication([])
    font=Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts/segoeui.ttf'
    if font.is_file(): QFontDatabase.addApplicationFont(str(font))
    app.setFont(QFont('Segoe UI',9)); return app
@pytest.fixture
def panel(qtapp):
    app=FakeApp(); p=setup(app); p.dock.resize(450,1000); app.window.show(); p.show(); yield p
    p.canvas.timer.stop()
    if p.inspector.dialog: p.inspector.dialog.close()
    p.close(); app.window.close(); QApplication.processEvents()

@pytest.mark.parametrize('dimension',['2D','3D'])
def test_editor_roundtrip(qtapp,dimension):
    d=benchmark() if dimension=='2D' else cantilever3d(); editor=Editor(d,None); editor.accept_model()
    assert editor.result()==1,editor.error.text()
    assert editor.data['schema']==d['schema']
    for k in ('nodes','materials','sections'): assert editor.data[k]==d[k]
    editor.close()

def test_panel_model_modes_and_idempotent_setup(panel):
    assert setup(panel.app) is panel
    panel.put(cantilever3d()); assert panel.dimension.currentText()=='3D'
    assert all(panel.diagram.findText(k)>=0 for k in ('Vy','Vz','My','Mz','T','Deformed'))
    panel.put(benchmark()); assert panel.dimension.currentText()=='2D' and panel.diagram.findText('V')>=0

def run_background(panel,qtapp):
    import go_structural_analysis.ui as ui
    from go_structural_analysis.client import analyze
    old=ui.analyze; ui.analyze=lambda model:analyze(model,python=str(ROOT/'.venv/Scripts/python.exe'))
    ticks=[]; timer=QTimer(); timer.setInterval(10); timer.timeout.connect(lambda:ticks.append(time.monotonic())); timer.start()
    try:
        panel.run(); deadline=time.monotonic()+90
        while panel.thread is not None and time.monotonic()<deadline: qtapp.processEvents(); time.sleep(.005)
        assert panel.thread is None,'worker timeout'
        assert is_current(panel.model(),panel.result),panel.status.text()
        assert ticks and panel.run_button.isEnabled()
    finally:
        timer.stop(); ui.analyze=old
    return len(ticks)

def test_background_inspector_tables_and_stale(panel,qtapp):
    d=example3d('3d_combo'); panel.put(d); assert run_background(panel,qtapp)>0
    panel.case.setCurrentText('ULS'); panel.inspector.select('B1',.371); assert 'T ' in panel.inspector.values.text()
    panel.inspector.envelope.setChecked(True); assert 'Reverse' in panel.inspector.values.text()
    panel.inspector.show_tables(); assert all(t.rowCount()>0 for t in panel.inspector.dialog.tables.values())
    d['nodes'][1]['y']=1; panel.put(d); assert not panel.inspector.csv.isEnabled() and 'out of date' in panel.inspector.values.text().lower()

def test_real_qpainter_overlays_camera_pick_and_theme(panel,qtapp):
    panel.put(example3d('3d_equilibrium')); run_background(panel,qtapp)
    out=ROOT/'artifacts/v0.2/offscreen'; out.mkdir(parents=True,exist_ok=True)
    for theme in ('Light','Dark','System'): panel.theme_choice.setCurrentText(theme); qtapp.processEvents()
    for mode in ('Model','N','Vy','Vz','My','Mz','T','D','Reaction','Deformed'):
        panel.diagram.setCurrentText(mode); panel.tabs.setCurrentIndex(2)
        image=QImage(1000,700,QImage.Format.Format_ARGB32); image.fill(QColor('#f1f4f7')); painter=QPainter(image)
        try: panel.paint(panel.app.viewport,painter)
        finally: painter.end()
        assert image.save(str(out/(mode+'.png')))
    for tab,name in enumerate(('Model-panel','Loads-panel','Results-panel')):
        panel.tabs.setCurrentIndex(tab); assert panel.grab().save(str(out/(name+'.png')))
    panel.tabs.setCurrentIndex(2); before=visualization.projected_members(panel); panel.app.viewport.camera.yaw+=.2; panel.app.viewport.camera.pitch+=.15; panel.app.viewport.camera.distance*=.85; panel.app.viewport.camera.target.setY(.3)
    panel.canvas.sync(); after=visualization.projected_members(panel); assert before!=after
    mid,a,b=after[0]; hit=visualization.pick(panel,(a[0]+b[0])/2,(a[1]+b[1])/2); assert hit[0]==mid
    point=QPointF((a[0]+b[0])/2,(a[1]+b[1])/2)
    event=QMouseEvent(QEvent.Type.MouseButtonPress,point,point,Qt.MouseButton.LeftButton,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(panel.app.viewport,event); assert panel.last_picked_member==mid
    panel.inspector.slider.setValue(423); assert panel.inspector.ratio.value()==pytest.approx(.423)
    panel.tabs.widget(2).ensureWidgetVisible(panel.inspector.values); assert panel.grab().save(str(out/'Inspector.png'))

def test_node_member_selection_delete_and_edit_preview(panel):
    d=example3d('3d_portal'); panel.put(d); panel.tabs.setCurrentIndex(0)
    node=d['nodes'][0]; px,py,_=panel.app.world_to_pixels([[node['x'],node['y'],node['z']]])
    assert panel.native_pick(float(px[0]),float(py[0]))=='node:'+node['id']
    point=QPointF(float(px[0]),float(py[0])); event=QMouseEvent(QEvent.Type.MouseButtonPress,point,point,Qt.MouseButton.LeftButton,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(panel.app.viewport,event); assert panel.selected_entity=='node:'+node['id']
    panel.select_entity('M1'); panel.delete_selected(); assert 'M1' not in [m['id'] for m in panel.model()['members']]

def test_source_host_api_save_load_history_and_migration(qtapp,tmp_path):
    from core.scene import Scene
    from core.history import History
    from views.extension_api import ExtensionApp
    from formats.igz import save_scene,load_into
    from go_structural_analysis.model3d import migrate2d
    window=QWidget(); window.viewport=QWidget(window); scene=Scene(); window.viewport.scene=scene; window.viewport.history=History(scene)
    app=ExtensionApp(window,'go_structural_analysis')
    original=copy.deepcopy(benchmark()); scene.mesh.add_edge(QVector3D(10,20,30),QVector3D(11,20,30))
    app.set_document_data({'version':'0.1.3','model':original,'result':None}); legacy=tmp_path/'legacy.igz'; save_scene(scene,legacy); before=legacy.read_bytes()
    app.set_document_data({'version':'0.2.3','model':migrate2d(original),'result':None})
    window.viewport.history.undo(); assert app.document_data()['model']==original
    window.viewport.history.redo(); assert app.document_data()['model']['schema']==2
    new=tmp_path/'new.igz'; save_scene(scene,new); loaded=Scene(); load_into(loaded,new)
    assert loaded.plugin_data==scene.plugin_data and len(loaded.mesh.edges)==1
    assert legacy.read_bytes()==before
    old=Scene(); load_into(old,legacy); assert old.plugin_data['go_structural_analysis']['model']==original
    window.close()

def test_workspace_orbit_filter(panel):
    panel.app._workspace=type('Workspace',(),dict(panel=panel,allowed_tools={'select','pan','zoom'}))()
    panel.put(cantilever3d())
    assert 'orbit' in panel.app.window.tool_filter
    panel.put(benchmark())
    assert 'orbit' not in panel.app.window.tool_filter

def test_navigation_press_does_not_pick(panel):
    panel.put(cantilever3d())
    panel.tabs.setCurrentIndex(0)
    panel.app.viewport.nav_mode='orbit'
    panel.native_pick=lambda *args: (_ for _ in ()).throw(AssertionError('Navigation must bypass selection'))
    event=QMouseEvent(QEvent.Type.MouseButtonPress,QPointF(30,30),QPointF(30,30),Qt.LeftButton,Qt.LeftButton,Qt.NoModifier)
    assert panel.canvas.eventFilter(panel.app.viewport,event) is False
