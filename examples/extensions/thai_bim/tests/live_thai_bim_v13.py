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

root07=Path(__file__).resolve().parents[1]
out07=root07/'verification-local';out07.mkdir(exist_ok=True)
for suffix in ('engine','visuals','structures','builders','detailing','placement','workflow','steel','management','audit','drawings','drawing_layout','catalogue','path_geometry','type_ui','multi_place','identity_data','copy_identity','rebar_recipe','analytical','analytical_ui','selected_edit'):sys.modules.pop('ingetrazo_plugin_thai_bim.'+suffix,None)
tb07=_import_by_path('thai_bim',user_plugins_dir()/'thai_bim/__init__.py')
from ingetrazo_plugin_thai_bim import workflow as W07,builders as B07,management as M07,steel as C07,audit as A071
checks07=[];actual07=(list(scene.groups),scene.version,set(scene.selection))
def check07(name,value):
    assert value,name;checks07.append(name)
    (out07/'live-checks.json').write_text(json.dumps(dict(version=tb07.E.VERSION,passed=checks07),indent=2),encoding='utf-8')
def rejects07(name,fn):
    try:fn()
    except ValueError:check07(name,True);return
    raise AssertionError(name+' did not reject')
def settle07():
    loop=QEventLoop();QTimer.singleShot(250,loop.quit);loop.exec()
class NativeEvents07:
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
panel07=viewport.window()._thai_bim_panel;old07=panel07.create_member.__func__.__globals__
for name in ['E','make_group','mesh_fingerprint','quantity_rows','identity_issues','roof_update','NormalizeColors','MultiRoofDialog','CutDialog','roof_planes_from_groups','multi_roof_update','cutting_runs']:old07[name]=getattr(tb07,name)
old07.update(ExchangeGroups=tb07.ExchangeGroups)
for method in ('create_member','update_member','execute'):getattr(panel07,method).__func__.__code__=getattr(tb07.Panel,method).__code__
bg07=panel07.open_builder.__globals__
for name in ('RoofDialog','StairDialog','RebarDialog'):bg07[name]=getattr(B07,name)
bg07.update(S=B07.S,D=B07.D,E=tb07.E,open_bbs=B07.open_bbs)
for dialog07 in panel07.builder_dialogs.values():dialog07.hide();dialog07.deleteLater()
panel07.builder_dialogs={};B07.add_tools(panel07);W07.install(panel07);M07.install(panel07);A071.install(panel07);__import__('ingetrazo_plugin_thai_bim.type_ui',fromlist=['install']).install(panel07);panel07.dock.setWindowTitle(tb07.TITLE);__import__('ingetrazo_plugin_thai_bim.analytical_ui',fromlist=['install']).install(panel07);__import__('ingetrazo_plugin_thai_bim.selected_edit',fromlist=['install']).install(panel07)
panel07.grid_columns.__func__.__code__=tb07.Panel.grid_columns.__code__
wg07=panel07.workflow.refresh.__func__.__globals__
for name in ('E','P','D','S','host_token','host_notices','bar_unchanged','host_matches','bar_specs','review_specs','placement_of','placed_member_command','PlacementDialog','PlacementTool'):
    wg07[name]=getattr(W07,name)
check07('21 actual toolbar actions with nonempty icons',len(panel07.toolbar.actions())==21 and all(not a.icon().isNull() for a in panel07.toolbar.actions()))

class App07:
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
app07=App07();fp07=tb07.setup(app07);ss07=app07.scene;hh07=app07.viewport.history
fp07.guard=lambda fn:fn()
check07('fresh setup has 21 icons',len(fp07.toolbar.actions())==21)
M07.install(fp07);check07('layer manager install idempotent',len(fp07.toolbar.actions())==21)
created07=[]
for kind,values in B07.PRESETS.items():
    fp07.kind.setCurrentText(kind)
    for key,value in zip(('x','y','z','width','depth','height'),values):fp07.mfields[key].setValue(value)
    fp07.create_member();created07.append(ss07.groups[-1])
    check07('create '+kind+' retains all prior members',all(g in ss07.groups for g in created07))
st07=B07.StairDialog(fp07);st07.build();created07.append(ss07.groups[-1])
check07('create Stair preserves footing column beam slab',all(g in ss07.groups for g in created07))
check07('five structural kinds have five layers',len({g.layer for g in created07})==5)
ss07.selection={created07[0]};fp07.kind.setCurrentText('Column')
rejects07('wrong kind cannot replace selected footing',fp07.update_member)
check07('rejected update preserves exact footing',created07[0] in ss07.groups)
for i in range(3):
    fp07.toolbar.actions()[i+2].trigger()
check07('switching toolbar kinds changes no geometry',all(g in ss07.groups for g in created07))
# A command prepared before another operation must never overwrite that operation.
extra07=tb07.make_group(tb07.E.box_spec('Column',10,0,0,.3,.3,3))
pending07=tb07.ExchangeGroups(ss07,additions=[extra07])
fp07.create_member();latest07=ss07.groups[-1];before07=list(ss07.groups)
rejects07('stale snapshot blocked before overwriting members',lambda:pending07.do(ss07))
check07('stale command preserved intervening creation',ss07.groups==before07 and latest07 in ss07.groups)
hh07.undo();check07('single create Undo preserves earlier five members',ss07.groups==created07)
hh07.redo();check07('create Redo valid',latest07 in ss07.groups)
hh07.undo()
# Migration modifies tags only and retains exact geometry objects and visibility.
for g in created07:g.layer='TBIM Structure'
ss07.layers.append(tb07.Layer('TBIM Structure',False))
fp07.execute(M07.LayerChanges(ss07,migrate=True))
check07('existing groups relayered without replacement',ss07.groups==created07 and len({g.layer for g in created07})==5)
hh07.undo();check07('migration Undo restores original layer assignment',all(g.layer=='TBIM Structure' for g in created07))
hh07.redo();check07('migration Redo restores five layers',len({g.layer for g in created07})==5)
# Native full/light/wire geometry, BBS, stable UIDs and persistence.
ss07.selection={created07[1]};reb07=B07.RebarDialog(fp07);reb07.read_host()
check07('new cage defaults DB12 SD40 and RB6 SR24',reb07.params()['main_steel']['size']=='DB12' and reb07.params()['tie_steel']['size']=='RB6')
stats07={};uids07=None;reference07=None
import time
for mode07 in ('Full','Lightweight','Centreline'):
    reb07.representation.setCurrentText(mode07);start07=time.perf_counter();reb07.review();reb07.build();elapsed07=time.perf_counter()-start07
    bars07=[g for g in ss07.groups if g.ext['thai_bim'].get('host_uid')==created07[1].uid]
    records07,issues07=tb07.bbs_records(ss07)
    check07(mode07+' BBS valid',len(records07)==len(bars07) and not issues07)
    values07={r['id']:(r['bbs']['mark'],r['bbs']['length_m'],r['bbs']['mass_kg']) for r in records07}
    if reference07 is None:reference07=values07;uids07=[g.uid for g in bars07]
    else:check07(mode07+' retains UIDs lengths marks and mass',values07==reference07 and [g.uid for g in bars07]==uids07)
    check07(mode07+' rebar isolated on column layer',all(g.layer=='TBIM S Rebar Column' for g in bars07))
    check07(mode07+' preserves all RC members',all(g in ss07.groups for g in created07))
    if mode07=='Centreline':check07('wire has edges and zero faces',all(not g.mesh.faces and g.mesh.edges for g in bars07))
    else:check07(mode07+' bar closed volume positive',all(tb07.bim.face_set_volume(list(g.mesh.faces))>0 for g in bars07))
    native07=out07/(mode07+'.igz');save_scene(ss07,native07)
    compact07=out07/(mode07+'-compact.igz');M07.compact_save(ss07,compact07)
    loaded07=Scene();load_into(loaded07,compact07)
    check07(mode07+' compact IGZ roundtrip BBS valid',len(tb07.bbs_records(loaded07)[0])==len(bars07) and not tb07.bbs_records(loaded07)[1])
    stats07[mode07]=dict(bars=len(bars07),faces=sum(len(g.mesh.faces) for g in bars07),edges=sum(len(g.mesh.edges) for g in bars07),native_bytes=native07.stat().st_size,compact_bytes=compact07.stat().st_size,review_build_seconds=elapsed07)
check07('lightweight face count below 30 percent of Full',stats07['Lightweight']['faces']<stats07['Full']['faces']*.3)
check07('wire native file below 20 percent of Full',stats07['Centreline']['native_bytes']<stats07['Full']['native_bytes']*.2)
rows07,qissues07=tb07.quantity_rows(ss07)
check07('wire QTO counts all bars',sum(r['name'].startswith('TBIM Rebar') for r in rows07)==len(bars07) and not qissues07)
finger07=tb07.mesh_fingerprint(bars07[0]);edge07=next(iter(bars07[0].mesh.edges));oldpos07=QVector3D(edge07.v0.position);edge07.v0.position+=QVector3D(.01,0,0)
check07('edited wire fingerprint detected',tb07.mesh_fingerprint(bars07[0])!=finger07)
check07('edited wire excluded from BBS',bars07[0].uid not in [r['id'] for r in tb07.bbs_records(ss07)[0]])
edge07.v0.position=oldpos07
rejects07('wire conversion invalidated by independent movement',lambda:(setattr(bars07[0],'xform',W07.matrix(W07.P.matrix((2,0,0)))),reb07.review())[-1])
bars07[0].xform=W07.matrix(W07.pose(created07[1]))
pre07=list(ss07.groups);fp07.execute(M07.LayerChanges(ss07,visibility={'TBIM S Rebar Column':False}))
check07('hide bars retains geometry and BBS',ss07.groups==pre07 and len(tb07.bbs_records(ss07)[0])==len(bars07))
hh07.undo();check07('layer visibility Undo',next(l for l in ss07.layers if l.name=='TBIM S Rebar Column').visible)
hh07.undo();check07('representation Undo restores Lightweight',all(g.ext['thai_bim'].get('representation')=='Lightweight' for g in ss07.groups if g.ext['thai_bim'].get('kind')=='Rebar'))
hh07.redo();check07('representation Redo restores valid wire BBS',len(tb07.bbs_records(ss07)[0])==len(bars07))
# UI unit selector must preserve independent ASTM inch precision, not rounded SI.
cat07,size07,grade07=reb07.steel_controls['main_steel'];cat07.setCurrentText(C07.ASTM_IN);size07.setCurrentText('#18')
check07('native UI inch #18 retains 57.3278 mm',abs(reb07.params()['diameter']-57.3278)<1e-6)
cat07.setCurrentText(C07.ASTM_SI)
size07.setCurrentText('#18');check07('native UI SI #18 is 57.3 mm',reb07.params()['diameter']==57.3)
cat07.setCurrentText(C07.TIS_DB);size07.setCurrentText('DB12');reb07.review();reb07.show();settle07();reb07.grab().save(str(out07/'rebar-catalogue.png'));reb07.hide()
manager07=M07.open_manager(fp07);settle07();manager07.grab().save(str(out07/'layer-manager.png'));manager07.hide()
tb07.E.write_xlsx(out07/'layer-rebar-BBS.xlsx',tables=B07.D.tables(tb07.bbs_records(ss07)[0]))
(out07/'performance.json').write_text(json.dumps(stats07,indent=2),encoding='utf-8')
# Floor and stair paths also support the two display modes, retaining their net-path QTO basis.
for host07 in (created07[0],created07[3],created07[4]):
    ss07.selection={host07};local07=B07.RebarDialog(fp07);local07.read_host();local07.representation.setCurrentText('Centreline');local07.review();local07.build()
    cage07=[g for g in ss07.groups if g.ext['thai_bim'].get('host_uid')==host07.uid]
    check07(host07.ext['thai_bim']['kind']+' wire cage uses own layer',bool(cage07) and all(g.layer=='TBIM S Rebar '+host07.ext['thai_bim']['kind'] and not g.mesh.faces for g in cage07))
    local07.representation.setCurrentText('Lightweight');local07.review();local07.build()
    check07(host07.ext['thai_bim']['kind']+' wire-to-light conversion preserves RC',all(g in ss07.groups for g in created07))
    local07.deleteLater()
rows_all07,_=tb07.quantity_rows(ss07)
check07('floor stair footing bars have valid QTO lengths',all(r['quantity'] is not None for r in rows_all07))
check07('slab stair included in detailed BBS',{'Slab','Stair'}.issubset({next(g for g in ss07.groups if g.uid==r['host_uid']).ext['thai_bim']['kind'] for r in tb07.bbs_records(ss07)[0]}))

# New detailing verified through the same native UI/controller used by customers.
for host08 in (created07[3],created07[4]):
    kind08=host08.ext['thai_bim']['kind']
    ss07.selection={host08};dialog08=B07.RebarDialog(fp07);dialog08.read_host()
    check07(kind08+' hook controls enabled',dialog08.fields['hook_length'].isEnabled())
    # Rebuild a thicker fixture through the public native host update path.
    if kind08=='Slab':
        fp07.kind.setCurrentText('Slab');fp07.mfields['height'].setValue(.3);fp07.update_member()
        host08=next(g for g in ss07.groups if g.uid==host08.uid)
        ss07.selection={host08};dialog08.read_host();dialog08.fields['layers'].setValue(2)
        dialog08.fields['hook_length'].setValue(25)
    else:
        # Default 150 mm waist permits short vertical legs; larger ones must reject.
        dialog08.fields['hook_length'].setValue(12)
        dialog08.review();dialog08.build()
        hooked08=[g for g in ss07.groups if g.ext['thai_bim'].get('host_uid')==host08.uid]
        check07('stair vertical hooks form positive native solids',any(g.ext['thai_bim']['bbs']['shape']=='Stair-U' for g in hooked08) and all(tb07.bim.face_set_volume(list(g.mesh.faces))>0 for g in hooked08))
        check07('stair anchorage controls enabled',dialog08.fields['extension_start'].isEnabled())
        dialog08.fields['hook_length'].setValue(0)
        dialog08.fields['extension_start'].setValue(300);dialog08.fields['extension_end'].setValue(400)
    dialog08.representation.setCurrentText('Centreline');dialog08.review();dialog08.build()
    bars08=[g for g in ss07.groups if g.ext['thai_bim'].get('host_uid')==host08.uid]
    ids08={g.ext['thai_bim']['slot']:(g.uid,g.ext['thai_bim']['id']) for g in bars08}
    bbs08={g.uid:g.ext['thai_bim']['bbs'] for g in bars08}
    check07(kind08+' detailed cage has BBS and its layer',bool(bars08) and all(g.ext['thai_bim'].get('bbs') and g.layer=='TBIM S Rebar '+kind08 for g in bars08))
    dialog08.show();settle07();dialog08.grab().save(str(out07/(kind08+'-dialog.png')));dialog08.hide()
    dialog08.representation.setCurrentText('Lightweight');dialog08.review();dialog08.build()
    upgraded08=[g for g in ss07.groups if g.ext['thai_bim'].get('host_uid')==host08.uid]
    check07(kind08+' display update retains UID and business ID',ids08=={g.ext['thai_bim']['slot']:(g.uid,g.ext['thai_bim']['id']) for g in upgraded08})
    check07(kind08+' display update retains all marks lengths and mass',bbs08=={g.uid:g.ext['thai_bim']['bbs'] for g in upgraded08})
    hh07.undo();check07(kind08+' Undo restores exact cage objects',all(g in ss07.groups for g in bars08))
    hh07.redo();check07(kind08+' Redo retains other concrete members',all(g.uid in {h.uid for h in ss07.groups} for g in created07))
    before08=list(ss07.groups);dialog08.fields['hook_length'].setValue(1000)
    if kind08=='Stair':dialog08.fields['extension_start'].setValue(0);dialog08.fields['extension_end'].setValue(0)
    rejects07(kind08+' impossible hook rejected',lambda:dialog08.specs())
    check07(kind08+' rejected hook preserves all geometry',ss07.groups==before08)
    dialog08.deleteLater()
records08,issues08=tb07.bbs_records(ss07)
check07('slab stair host revisions restored valid BBS',not issues08 and records08)
tb07.E.write_xlsx(out07/'slab-stair-BBS.xlsx',tables=B07.D.tables(records08))
M07.compact_save(ss07,out07/'slab-stair-compact.igz')
reopened08=Scene();load_into(reopened08,out07/'slab-stair-compact.igz')
recs08,issues08=tb07.bbs_records(reopened08)
check07('slab stair native save reopen preserves detailed BBS',not issues08 and {r['id']:r['bbs'] for r in records08}=={r['id']:r['bbs'] for r in recs08})
bbdialog08=B07.open_bbs(fp07);bbdialog08.show();settle07()
from PySide6.QtWidgets import QTableWidget,QTabWidget
table08=bbdialog08.findChild(QTabWidget).widget(0);table08.setCurrentCell(0,0);settle07()
check07('selected BBS row displays matching shape preview',any(table08.item(0,1).text() in label.text() and 'mm' in label.text() for label in bbdialog08.findChildren(QLabel)))
bbdialog08.grab().save(str(out07/'bbs-dialog.png'));bbdialog08.hide()

app07.window.deleteLater();settle07()
from core import units as units07
units07.bind_scene(scene)
check07('actual user scene unchanged',actual07==(list(scene.groups),scene.version,set(scene.selection)))
print('Thai BIM 0.10 '+str(len(checks07))+' native checks passed\n'+json.dumps(stats07))
