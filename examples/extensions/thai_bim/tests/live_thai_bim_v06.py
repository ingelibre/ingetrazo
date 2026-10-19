"""Native mouse/keyboard placement, host review, rigid BBS and Undo in isolated scenes."""
import copy,json,sys
from pathlib import Path
from core.extensions import _import_by_path,user_plugins_dir
from core.scene import Scene
from core.history import History,MoveGroupCommand,RotateGroupCommand
from core.group import world_mesh
from formats.igz import save_scene,load_into
from formats.gltf import save_glb
from PySide6.QtWidgets import QMainWindow,QDockWidget,QLabel,QApplication
from PySide6.QtCore import Qt,QEvent,QEventLoop,QTimer,QPoint,QPointF
from PySide6.QtGui import QVector3D,QAction,QMouseEvent,QKeyEvent
from tools.base import ToolContext
from tools.select import SelectTool
from core.snap import SnapResult
from views.viewport import Viewport

root06=Path(__file__).resolve().parents[1]
out06=root06/'verification-local';out06.mkdir(exist_ok=True)
for suffix in ('engine','visuals','structures','builders','detailing','placement','workflow'):sys.modules.pop('ingetrazo_plugin_thai_bim.'+suffix,None)
tb06=_import_by_path('thai_bim',user_plugins_dir()/'thai_bim/__init__.py')
from ingetrazo_plugin_thai_bim import workflow as W06,builders as B06
checks06=[];actual06=(list(scene.groups),scene.version,set(scene.selection))
def check06(name,value):
    assert value,name;checks06.append(name)
    (out06/'live-checks.json').write_text(json.dumps(dict(version=tb06.E.VERSION,passed=checks06),indent=2),encoding='utf-8')
def rejects06(name,fn):
    try:fn()
    except ValueError:check06(name,True);return
    raise AssertionError(name+' did not reject')
def settle06():
    loop=QEventLoop();QTimer.singleShot(250,loop.quit);loop.exec()
class NativeEvents06:
    # The installed app omits QtTest; dispatch actual Qt events through QApplication.
    @staticmethod
    def mouseMove(widget,point):
        QApplication.sendEvent(widget,QMouseEvent(QEvent.MouseMove,QPointF(point),QPointF(widget.mapToGlobal(point)),Qt.NoButton,Qt.NoButton,Qt.NoModifier))
    @staticmethod
    def mouseClick(widget,button,modifiers,point):
        for event,buttons in [(QEvent.MouseButtonPress,button),(QEvent.MouseButtonRelease,Qt.NoButton)]:
            QApplication.sendEvent(widget,QMouseEvent(event,QPointF(point),QPointF(widget.mapToGlobal(point)),button,buttons,modifiers))
    @staticmethod
    def keyClick(widget,key):
        QApplication.sendEvent(widget,QKeyEvent(QEvent.KeyPress,int(key),Qt.NoModifier,'r' if key==Qt.Key_R else ''))
        QApplication.sendEvent(widget,QKeyEvent(QEvent.KeyRelease,int(key),Qt.NoModifier))
# Reuse the current panel; retain the original document/overlay callbacks.
panel06=viewport.window()._thai_bim_panel;old06=panel06.create_member.__func__.__globals__
for name in ['E','make_group','mesh_fingerprint','quantity_rows','identity_issues','roof_update','NormalizeColors','MultiRoofDialog','CutDialog','roof_planes_from_groups','multi_roof_update','cutting_runs']:old06[name]=getattr(tb06,name)
bg06=panel06.open_builder.__globals__
for name in ('RoofDialog','StairDialog','RebarDialog'):bg06[name]=getattr(B06,name)
bg06.update(S=B06.S,D=B06.D,E=tb06.E)
for dialog06 in panel06.builder_dialogs.values():dialog06.hide();dialog06.deleteLater()
panel06.builder_dialogs={};B06.add_tools(panel06);W06.install(panel06);panel06.dock.setWindowTitle(tb06.TITLE)
panel06.grid_columns.__func__.__code__=tb06.Panel.grid_columns.__code__
wg06=panel06.workflow.refresh.__func__.__globals__
for name in ('E','P','D','S','host_token','host_notices','bar_unchanged','host_matches','bar_specs','review_specs','placement_of','placed_member_command','PlacementDialog','PlacementTool'):
    wg06[name]=getattr(W06,name)
check06('14 actual toolbar actions with nonempty icons',len(panel06.toolbar.actions())==14 and all(not a.icon().isNull() for a in panel06.toolbar.actions()))

class App06:
    api_version=2
    def __init__(self):
        self.window=QMainWindow();self.window.setWindowTitle('Thai BIM isolated verification');self.window.resize(960,700)
        self.viewport=Viewport(self.window);self.window.setCentralWidget(self.viewport);self.callbacks=[]
    @property
    def scene(self):return self.viewport.scene
    def document_data(self,default):return getattr(self,'project_data',default)
    def on_document_changed(self,fn):self.callbacks.append(fn);self.viewport.sceneVersionChanged.connect(lambda version:fn())
    def add_panel(self,title,widget):d=QDockWidget(title,self.window);d.setWidget(widget);return d
    def add_menu_action(self,*args,**kwargs):pass
    def add_overlay(self,fn):self.viewport._ext_overlays.append(fn)
    def add_snap_provider(self,fn):self.viewport._ext_snap_providers.append(fn)
    def world_to_pixels(self,points):return self.viewport.world_to_pixels(points)
app06=App06();fp06=tb06.setup(app06);ss06=app06.scene;vp06=app06.viewport;hh06=vp06.history
fp06.guard=lambda fn:fn()  # surface errors in the test instead of a modal warning
check06('fresh plugin setup has 14 icons',len(fp06.toolbar.actions())==14)
W06.install(fp06);check06('workflow install is idempotent',len(fp06.toolbar.actions())==14 and len(vp06._ext_snap_providers)==1)
place06=fp06.workflow.open_placement();place06.kind.setCurrentText('Footing')
for key,value in dict(width=.8,depth=.8,height=.4,x=3,y=4,z=3.65,yaw=45).items():place06.fields[key].setValue(value)
place06.preview();place06.show();settle06();place06.grab().save(str(out06/'placement-dialog.png'))
check06('placement preview valid',not place06.visual.error)
place06.build();host06=ss06.groups[-1];ss06.selection={host06}
check06('centred rotated member world anchor',all(abs(a-b)<1e-5 for a,b in zip((W06.placement_of(host06)[k] for k in ('x','y','z')),(3,4,3.65))))
check06('world concrete volume unchanged by rigid pose',abs(tb06.bim.face_set_volume(list(world_mesh(host06).faces))-.256)<1e-5)
reb06=B06.RebarDialog(fp06);reb06.read_host();reb06.fields['hook_length'].setValue(80)
rejects06('changed UI parameters require explicit review',reb06.build)
reb06.review();reb06.build();bars06=[g for g in ss06.groups if g.ext['thai_bim'].get('host_uid')==host06.uid]
records06,issues06=tb06.bbs_records(ss06)
check06('rotated host BBS valid',len(records06)==len(bars06) and not issues06)
check06('bar poses match host',all(W06.P.same_pose(W06.pose(g),W06.pose(host06)) for g in bars06))
check06('rotated bar solid world volume positive',all(tb06.bim.face_set_volume(list(world_mesh(g).faces))>0 for g in bars06))
length06=sum(r['bbs']['length_m'] for r in records06);ids06=[g.uid for g in bars06]
place06.read_member();place06.fields['x'].setValue(5);place06.fields['yaw'].setValue(90);place06.build(True)
moved06=next(g for g in ss06.groups if g.uid==host06.uid)
check06('placement update preserves host UID',moved06.uid==host06.uid)
check06('moved host flagged for review',any(r['state']=='Review' for r in W06.host_notices(ss06)))
invalid06,why06=tb06.bbs_records(ss06);check06('stale posed BBS excluded',not invalid06 and bool(why06))
rejects06('host move invalidates reviewed build',reb06.build)
reb06.preview();reb06.show();settle06();reb06.grab().save(str(out06/'host-rebar-review.png'));reb06.review();refs06=list(ss06.groups);reb06.build()
new06=[g for g in ss06.groups if g.ext['thai_bim'].get('host_uid')==host06.uid]
check06('moved host regeneration retains bar IDs',[g.uid for g in new06]==ids06)
check06('moved host regeneration follows pose',all(W06.P.same_pose(W06.pose(g),W06.pose(moved06)) for g in new06))
rr06,ii06=tb06.bbs_records(ss06);check06('moving keeps analytic BBS lengths',not ii06 and abs(sum(r['bbs']['length_m'] for r in rr06)-length06)<1e-8)
hh06.undo();check06('regeneration Undo exact references',ss06.groups==refs06)
hh06.undo();check06('placement Undo restores original host and valid BBS',host06 in ss06.groups and len(tb06.bbs_records(ss06)[0])==len(bars06))
hh06.redo();hh06.redo();check06('placement and rebar Redo restores valid BBS',len(tb06.bbs_records(ss06)[0])==len(bars06))
ss06.selection={next(g for g in ss06.groups if g.uid==host06.uid)};place06.read_member();place06.fields['width'].setValue(1.1);place06.build(True)
check06('dimension change flagged for review',any(r['state']=='Review' for r in W06.host_notices(ss06)))
rejects06('size change invalidates previous preview',reb06.build)
host_list06=fp06.workflow.open_hosts();settle06();host_list06.grab().save(str(out06/'host-status-dialog.png'));host_list06.hide()
reb06.review();reb06.build();check06('size regeneration reconciles count',len(tb06.bbs_records(ss06)[0])>len(bars06))
fp06.workflow.refresh();check06('host notice returns to Current',all(r['state']=='Current' for r in fp06.workflow.rows))
rows06,qissues06=tb06.quantity_rows(ss06);check06('QTO accepts tracked rigid bars',all(r['quantity'] is not None for r in rows06))
current06=next(g for g in ss06.groups if g.uid==host06.uid);bar06=next(g for g in ss06.groups if g.ext['thai_bim'].get('host_uid')==host06.uid)
old_pose06=W06.pose(bar06);bar06.xform=W06.matrix(W06.P.matrix((99,0,0),0))
rejects06('independently moved bar blocks regeneration',reb06.review)
check06('independently moved bar excluded from BBS',bar06.uid not in [r['id'] for r in tb06.bbs_records(ss06)[0]])
bar06.xform=W06.matrix(old_pose06);old_host_pose06=W06.pose(current06);current06.xform.scale(2)
rejects06('scaled host blocked',reb06.review);check06('scaled host notice Blocked',any(r['state']=='Blocked' for r in W06.host_notices(ss06)))
current06.xform=W06.matrix(old_host_pose06)
token06=W06.host_token(current06);current06.ext['thai_bim']['fingerprint']='manually-edited'
rejects06('manually edited host blocked',reb06.review);current06.ext['thai_bim']['fingerprint']=token06[2]
ss06.groups.remove(current06);check06('missing host BBS excluded with reason',not tb06.bbs_records(ss06)[0] and any(r['state']=='Blocked' for r in W06.host_notices(ss06)))
ss06.groups.insert(0,current06)

# Standard native Move/Rotate must preserve parametric geometry for new RC hosts.
for kind06,xyz06,dims06 in [('Column',(7,0,0),(.3,.3,2.5)),('Beam',(8,0,0),(1.5,.3,.4))]:
    config_kind06=dict(kind=kind06,x=xyz06[0],y=xyz06[1],z=xyz06[2],width=dims06[0],depth=dims06[1],height=dims06[2],yaw=0)
    cmd06,h06=W06.placed_member_command(ss06,config_kind06);fp06.execute(cmd06);ss06.selection={h06}
    d06=B06.RebarDialog(fp06);d06.read_host();d06.fields['spacing'].setValue(500);d06.fields['lap_length'].setValue(300);d06.review();d06.build()
    rb06=[g for g in ss06.groups if g.ext['thai_bim'].get('host_uid')==h06.uid];u06=[g.uid for g in rb06];f06=tb06.mesh_fingerprint(h06)
    fp06.execute(MoveGroupCommand(h06,QVector3D(1,2,.1)))
    fp06.execute(RotateGroupCommand(h06,QVector3D(8,2,.1),QVector3D(0,0,1),30))
    check06(kind06+' native Move/Rotate keeps local fingerprint',tb06.mesh_fingerprint(h06)==f06)
    check06(kind06+' native Move/Rotate prompts review',next(r for r in W06.host_notices(ss06) if r['uid']==h06.uid)['state']=='Review')
    rejects06(kind06+' native pose change invalidates preview',d06.build)
    d06.review();old_refs06=list(ss06.groups);d06.build()
    check06(kind06+' native pose regeneration stable IDs',[g.uid for g in ss06.groups if g.ext['thai_bim'].get('host_uid')==h06.uid]==u06)
    check06(kind06+' native posed BBS valid',len([r for r in tb06.bbs_records(ss06)[0] if r['host_uid']==h06.uid])==len(rb06))
    hh06.undo();check06(kind06+' regeneration Undo',ss06.groups==old_refs06);hh06.redo();d06.deleteLater()
test_count06=len(ss06.groups);fp06.kind.setCurrentText('Column');fp06.mfields['width'].setValue(.3);fp06.mfields['depth'].setValue(.3);fp06.mfields['height'].setValue(2)
fp06.create_member();plain_host06=ss06.groups[-1];hash_plain06=tb06.mesh_fingerprint(plain_host06)
fp06.execute(MoveGroupCommand(plain_host06,QVector3D(1,0,0)));check06('regular RC creation supports native Move',tb06.mesh_fingerprint(plain_host06)==hash_plain06 and plain_host06.xform is not None)
hh06.undo();hh06.undo();check06('regular RC Move and create Undo',len(ss06.groups)==test_count06)
app06.project_data={'grid_x':[0,1],'grid_y':[0,1],'levels':[{'name':'Ground','z':0}]}
fp06.grid_columns();grid_ids06=[g.uid for g in ss06.groups if g.ext['thai_bim'].get('assembly')=='grid-columns'];fp06.grid_columns()
check06('existing grid-column workflow keeps repeat IDs',grid_ids06==[g.uid for g in ss06.groups if g.ext['thai_bim'].get('assembly')=='grid-columns'])
hh06.undo();hh06.undo();del app06.project_data
save_scene(ss06,out06/'placed-host-rebar.igz');loaded06=Scene();load_into(loaded06,out06/'placed-host-rebar.igz')
check06('IGZ persistence of tracked host and bar poses',tb06.bbs_records(ss06)==tb06.bbs_records(loaded06))
save_glb(ss06,out06/'placed-host-rebar.glb');check06('placed host and bar native GLB export',(out06/'placed-host-rebar.glb').stat().st_size>1000)
tb06.E.write_xlsx(out06/'placed-host-BBS.xlsx',tables=W06.D.tables(*tb06.bbs_records(loaded06)))
reb06.hide();place06.hide();fp06.workspace_dialog.hide()

# Exercise native mouse dispatch and keyboard shortcut claims in a separate empty Scene.
old_test_scene06=vp06.scene;old_test_history06=vp06.history;vp06.set_document(Scene(),History(Scene()))
vp06.history=History(vp06.scene);ss_click06=vp06.scene;vp06.set_active_tool(SelectTool())
app06.window.show();settle06();vp06.setFocus()
config06=dict(kind='Column',width=.3,depth=.3,height=2,x=0,y=0,z=0,yaw=0)
tool06=W06.PlacementTool(fp06,config06,[0,3],[0,4],True,vp06.active_tool);fp06.placement_tool=tool06;vp06.set_active_tool(tool06)
px06,py06,front06=app06.world_to_pixels(W06.np.asarray(tool06.points,float));cursor06=QPoint(round(px06[0]),round(py06[0]))
snap06=fp06.workflow.snap(vp06,SnapResult(QVector3D(0,0,0),'none'),cursor06.x(),cursor06.y())
check06('native projected Grid snap',snap06 is not None and snap06.label.startswith('Grid'))
check06('temporary Grid guides visible while placing',len(tool06.guide_preview_lines())==4)
check06('native named endpoint keeps priority',fp06.workflow.snap(vp06,SnapResult(QVector3D(0,0,0),'endpoint'),cursor06.x(),cursor06.y()) is None)
conflict06=[];action06=QAction('Rectangle R shortcut',app06.window);action06.setShortcut('R');action06.triggered.connect(lambda:conflict06.append(True));app06.window.addAction(action06)
NativeEvents06.mouseMove(vp06,cursor06);settle06();NativeEvents06.keyClick(vp06,Qt.Key_R);check06('native R overrides conflicting window shortcut',tool06.config['yaw']==90 and not conflict06)
check06('wire preview ready',bool(tool06.rubber_band_lines()))
NativeEvents06.mouseClick(vp06,Qt.LeftButton,Qt.NoModifier,cursor06);settle06()
check06('native mouse click creates one member',len(ss_click06.groups)==1)
second06=QPoint(round(px06[2]),round(py06[2]));NativeEvents06.mouseMove(vp06,second06);settle06();NativeEvents06.mouseClick(vp06,Qt.LeftButton,Qt.NoModifier,second06);settle06()
check06('native repeated placement creates separate IDs',len(ss_click06.groups)==2 and ss_click06.groups[0].uid!=ss_click06.groups[1].uid)
vp06.history.undo();check06('one click is one Undo',len(ss_click06.groups)==1)
ss_click06.selection={ss_click06.groups[0]};NativeEvents06.keyClick(vp06,Qt.Key_Escape);check06('native Esc exits despite current selection',not isinstance(vp06.active_tool,W06.PlacementTool))
vp06.set_active_tool(tool06);vp06.set_document(Scene(),History(Scene()));ctx06=ToolContext(vp06,QVector3D(),QPointF(),Qt.NoModifier,SnapResult(QVector3D(),'none'))
tool06.on_click(ctx06);check06('document switch cancels placement without creating',not vp06.scene.groups and not isinstance(vp06.active_tool,W06.PlacementTool))
app06.window.hide();vp06.set_document(old_test_scene06,old_test_history06)
fp06.workflow.refresh();check06('notification label updates after model changes','Host' in fp06.workflow.label.text())
app06.window.deleteLater();settle06()
from core import units as units06
units06.bind_scene(scene)
check06('actual user scene unchanged',actual06==(list(scene.groups),scene.version,set(scene.selection)))
panel06.report.setPlainText('Thai BIM 0.6 • วาง RC ตาม Grid/Level / หมุน / คลิกซ้ำ\nHost เปลี่ยน: เปิดพรีวิว ตรวจ แล้วอัปเดตเหล็ก • รองรับ rigid transform\nScale / mirror / แก้ผิวด้วยมือยังต้องตรวจทาน')
print('Thai BIM 0.6: '+str(len(checks06))+' native checks passed; actual scene unchanged')
