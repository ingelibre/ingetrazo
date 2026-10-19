"""Native solids, reversible assemblies, host association and toolbar callbacks."""
import copy,json,sys,types
from pathlib import Path
from core.extensions import _import_by_path,user_plugins_dir
from core.scene import Scene
from core.history import History
from formats.igz import save_scene,load_into
from formats.gltf import save_glb
from PySide6.QtWidgets import QTabWidget,QApplication,QLabel,QToolBar
from PySide6.QtCore import QEventLoop,QTimer

root04=Path(__file__).resolve().parents[1]
out04=root04/'verification-local';out04.mkdir(exist_ok=True)
for suffix in ('engine','visuals','structures','builders'):sys.modules.pop('ingetrazo_plugin_thai_bim.'+suffix,None)
tb04=_import_by_path('thai_bim',user_plugins_dir()/'thai_bim/__init__.py')
from ingetrazo_plugin_thai_bim import structures as S04,builders as B04
checks04=[]
actual_before04=(list(scene.groups),scene.version,set(scene.selection))
def check04(name,condition):
    assert condition,name;checks04.append(name)
    (out04/'live-checks.json').write_text(json.dumps({'version':'0.4.0','passed':checks04},indent=2),encoding='utf-8')
def settle04():
    loop=QEventLoop();QTimer.singleShot(300,loop.quit);loop.exec()

# Upgrade the existing panel, keep its document and overlay subscriptions alive.
panel04=viewport.window()._thai_bim_panel
old_globals04=panel04.create_member.__func__.__globals__
for name in ['E','make_group','mesh_fingerprint','quantity_rows','identity_issues','roof_update','NormalizeColors',
             'MultiRoofDialog','CutDialog','roof_planes_from_groups','multi_roof_update','cutting_runs']:
    old_globals04[name]=getattr(tb04,name)
tb04.add_tools(panel04);panel04.dock.setWindowTitle(tb04.TITLE)
builder_globals04=panel04.open_builder.__globals__
for name in ('RoofDialog','StairDialog','RebarDialog'):builder_globals04[name]=getattr(B04,name)
builder_globals04.update(S=S04,E=tb04.E)
for dialog04 in panel04.builder_dialogs.values():dialog04.hide();dialog04.deleteLater()
panel04.builder_dialogs={}
viewport.window().insertToolBarBreak(panel04.toolbar)
check04('11 native toolbar icons',len([a for a in panel04.toolbar.actions() if not a.isSeparator()])==11 and all(not a.icon().isNull() for a in panel04.toolbar.actions()))
for label in panel04.dock.widget().findChildren(QLabel):
    if label.text().startswith('Thai BIM Toolkit'):label.setText('Thai BIM Toolkit 0.4\nโครงสร้าง • หลังคา • เหล็กเสริม • QTO')
for index in range(1,5):
    panel04.toolbar.actions()[index].trigger();settle04()
    kind=panel04.kind.currentText();expected=B04.PRESETS[kind]
    check04('toolbar preset '+kind,tuple(w.value() for w in panel04.mfields.values())==expected)
panel04.toolbar.actions()[2].trigger();panel04.place_grid()
gx04,gy04,lv04=panel04.grid_place_controls
check04('Grid centred column placement',abs(panel04.mfields['x'].value()+panel04.mfields['width'].value()/2-gx04.currentData())<1e-6)
for index,key in [(5,'Stair'),(6,'Rebar'),(7,'Roof')]:
    panel04.toolbar.actions()[index].trigger();settle04()
    d=panel04.builder_dialogs[key];check04('toolbar opens '+key,d.isVisible());d.hide()

class FakeVP04:
    def __init__(self,s):self.history=History(s)
    def notify_scene_changed(self):pass
    def update(self):pass
class FakeApp04:
    window=viewport.window()
    def __init__(self):self.scene=Scene();self.viewport=FakeVP04(self.scene)
    def document_data(self,default):return default
    def on_document_changed(self,fn):self.callback=fn
fake04=FakeApp04();fp04=tb04.Panel(fake04)
scene04=fake04.scene;history04=fake04.viewport.history

for kind,number in [('Gable',2),('Hip',4),('Shed',1)]:
    planes04,specs04=S04.roof_assembly(kind)
    cmd,n=tb04.assembly_command(scene04,specs04,'roof-library',dict(kind=kind))
    history04.execute(cmd)
    check04(kind+' native closed solids',all(tb04.bim.face_set_volume(list(g.mesh.faces))>0 for g in scene04.groups))
    selected04=scene04.groups[0];old04=list(scene04.groups);ids04=[g.uid for g in old04]
    cmd,n=tb04.assembly_command(scene04,specs04,'roof-library',dict(kind=kind),[selected04]);history04.execute(cmd)
    check04(kind+' stable update IDs',[g.uid for g in scene04.groups]==ids04)
    history04.undo();check04(kind+' Undo exact references',scene04.groups==old04)
    scene04.groups.clear();scene04.selection.clear()
try:tb04.assembly_command(scene04,specs04,'roof-library',{},[]);raise AssertionError('Empty update accepted')
except ValueError:check04('empty update rejected',True)

for kind,w,d,h in [('Footing',1.2,1.2,.4),('Column',.25,.25,3),('Beam',3,.25,.4),('Slab',4,3,.15),('Stair',1,0,3)]:
    hostspec04=S04.stair_spec() if kind=='Stair' else tb04.E.box_spec(kind,0,0,0,w,d,h)
    host04=tb04.make_group(hostspec04);scene04.groups[:]=[host04];scene04.selection={host04}
    rebar04=B04.RebarDialog(fp04);rebar04.show();rebar04.read_host();settle04()
    rebar04.build();generated04=[g for g in scene04.groups if g is not host04]
    check04(kind+' rebar native solids',len(generated04)>4 and all(tb04.bim.face_set_volume(list(g.mesh.faces))>0 for g in generated04))
    old04=list(scene04.groups);ids04=[g.uid for g in old04]
    rebar04.build();check04(kind+' rebar repeat stable IDs',[g.uid for g in scene04.groups]==ids04)
    history04.undo();check04(kind+' rebar Undo references',scene04.groups==old04)
    rows04,issues04=tb04.quantity_rows(scene04)
    check04(kind+' quantities usable',all(r['quantity'] is not None and r['quantity']>0 for r in rows04))
    rebar04.repaint();rebar04.grab().save(str(out04/(kind.lower()+'-rebar-dialog.png')))
    rebar04.fields['spacing'].setValue(250);rebar04.build()
    check04(kind+' reconcile fewer bars',len(scene04.groups)<len(old04))
    history04.undo();check04(kind+' removed bars Undo',scene04.groups==old04)
    # Changing a host must invalidate associated quantities until regeneration.
    saved04=host04.ext['thai_bim']['fingerprint'];host04.ext['thai_bim']['fingerprint']='edited'
    try:rebar04.build();raise AssertionError('Edited host accepted')
    except ValueError:check04(kind+' edited host rejected',True)
    host04.ext['thai_bim']['fingerprint']=saved04
    hash04=generated04[0].ext['thai_bim']['host_hash'];generated04[0].ext['thai_bim']['host_hash']='stale'
    rows04,issues04=tb04.quantity_rows(scene04)
    check04(kind+' stale host QTO invalidated',any(r['quantity'] is None for r in rows04))
    generated04[0].ext['thai_bim']['host_hash']=hash04
    rebar04.hide();rebar04.deleteLater()

stair04=B04.StairDialog(fp04);stair04.show();stair04.preview();settle04()
stair04.grab().save(str(out04/'stair-dialog.png'));stair04.hide()
roof04=B04.RoofDialog(fp04);roof04.kind.setCurrentText('Hip');roof04.show();settle04()
roof04.grab().save(str(out04/'hip-roof-dialog.png'));roof04.hide()
save_groups04=list(scene04.groups)
roof04.build();roof_master04=next(g for g in scene04.groups if g not in save_groups04)
scene04.selection={roof_master04};roof04.read();old_hip_ids04={g.ext['thai_bim']['slot']:g.uid for g in scene04.groups if g.ext['thai_bim'].get('assembly')==roof_master04.ext['thai_bim']['assembly']}
roof04.fields['batten_spacing'].setValue(.4);roof04.build(True)
new_hip_ids04={g.ext['thai_bim']['slot']:g.uid for g in scene04.groups if g.ext['thai_bim'].get('assembly')==roof_master04.ext['thai_bim']['assembly']}
check04('roof dialog rebuild keeps support IDs',all(new_hip_ids04[k]==old_hip_ids04[k] for k in new_hip_ids04 if k.startswith('support-')))
history04.undo();history04.undo();scene04.selection.clear()
stair04.build();stair_master04=scene04.groups[-1];scene04.selection={stair_master04};stair04.read();stair04.fields['risers'].setValue(20);stair04.build(True)
check04('stair dialog selected update preserves UID',scene04.groups[-1].uid==stair_master04.uid)
history04.undo();history04.undo();scene04.selection.clear()
save_scene(scene04,out04/'stair-rebar-test.igz');loaded04=Scene();load_into(loaded04,out04/'stair-rebar-test.igz')
check04('native IGZ persistence',len(loaded04.groups)==len(scene04.groups) and all(tb04.mesh_fingerprint(g)==g.ext['thai_bim']['fingerprint'] for g in loaded04.groups))
save_glb(scene04,out04/'stair-rebar-test.glb')
check04('native RGB GLB export',(out04/'stair-rebar-test.glb').stat().st_size>1000)
tb04.E.write_xlsx(out04/'stair-rebar-QTO.xlsx',*tb04.quantity_rows(scene04))
fp04.hide();fp04.deleteLater();stair04.deleteLater();roof04.deleteLater()
check04('actual user scene unchanged',actual_before04==(list(scene.groups),scene.version,set(scene.selection)))
panel04.report.setPlainText('Thai BIM 0.4 • แถบไอคอนพร้อมใช้\nRC / บันไดตรง / จั่ว-ปั้นหยา-เพิง / เหล็กเสริม Host\nปลอกเชิง geometry; ปริมาณยังไม่รวมตะขอ/ทาบ/ฝังยึด')
panel04.open_workspace();panel04.workspace_dialog.hide();settle04()
viewport.window().grab().save(str(out04/'toolbar-installed.png'))
print('Thai BIM 0.4: '+str(len(checks04))+' native checks passed; actual scene unchanged')
