"""Native v0.5 detailing checks; synthetic scene, never edits the user's house."""
import json,sys
from pathlib import Path
from core.extensions import _import_by_path,user_plugins_dir
from core.scene import Scene
from core.history import History
from formats.igz import save_scene,load_into
from formats.gltf import save_glb
from PySide6.QtCore import QEventLoop,QTimer

root05=Path(__file__).resolve().parents[1]
out05=root05/'verification-local';out05.mkdir(exist_ok=True)
for suffix in ('engine','visuals','structures','builders','detailing'):sys.modules.pop('ingetrazo_plugin_thai_bim.'+suffix,None)
tb05=_import_by_path('thai_bim',user_plugins_dir()/'thai_bim/__init__.py')
from ingetrazo_plugin_thai_bim import builders as B05,detailing as D05
checks05=[];actual05=(list(scene.groups),scene.version,set(scene.selection))
def check05(name,condition):
    assert condition,name;checks05.append(name)
    (out05/'live-checks.json').write_text(json.dumps(dict(version=tb05.E.VERSION,passed=checks05),indent=2),encoding='utf-8')
def settle05():
    loop=QEventLoop();QTimer.singleShot(250,loop.quit);loop.exec()
panel05=viewport.window()._thai_bim_panel
old05=panel05.create_member.__func__.__globals__
for name in ['E','make_group','mesh_fingerprint','quantity_rows','identity_issues','roof_update','NormalizeColors','MultiRoofDialog','CutDialog','roof_planes_from_groups','multi_roof_update','cutting_runs']:
    old05[name]=getattr(tb05,name)
globals05=panel05.open_builder.__globals__
for name in ('RoofDialog','StairDialog','RebarDialog'):globals05[name]=getattr(B05,name)
globals05.update(S=B05.S,D=D05,E=tb05.E)
for dialog05 in panel05.builder_dialogs.values():dialog05.hide();dialog05.deleteLater()
panel05.builder_dialogs={};B05.add_tools(panel05);panel05.dock.setWindowTitle(tb05.TITLE)
check05('12 icons without duplicate toolbar',len(panel05.toolbar.actions())==12)
class VP05:
    def __init__(self,s):self.history=History(s)
    def notify_scene_changed(self):pass
    def update(self):pass
class App05:
    window=viewport.window()
    def __init__(self):self.scene=Scene();self.viewport=VP05(self.scene)
    def document_data(self,default):return default
    def on_document_changed(self,fn):self.callback=fn
fake05=App05();fp05=tb05.Panel(fake05);ss05=fake05.scene;history05=fake05.viewport.history
for kind05,x05,w05,d05,h05 in [('Footing',0,1.2,1.2,.4),('Column',2,.3,.3,3),('Beam',3,3,.3,.4)]:
    host05=tb05.make_group(tb05.E.box_spec(kind05,x05,0,0,w05,d05,h05));ss05.groups.append(host05);ss05.selection={host05}
    dialog05=B05.RebarDialog(fp05);dialog05.read_host()
    if kind05=='Footing':dialog05.fields['hook_length'].setValue(80)
    else:
        dialog05.fields['lap_length'].setValue(500);dialog05.fields['extension_start'].setValue(200);dialog05.fields['extension_end'].setValue(300)
    dialog05.show();settle05();dialog05.preview()
    check05(kind05+' real dialog valid preview',not dialog05.visual.error)
    dialog05.grab().save(str(out05/(kind05.lower()+'-detail-dialog.png')))
    dialog05.build();bars05=[g for g in ss05.groups if g.ext['thai_bim'].get('host_uid')==host05.uid]
    check05(kind05+' native positive bar solids',bool(bars05) and all(tb05.bim.face_set_volume(list(g.mesh.faces))>0 for g in bars05))
    check05(kind05+' BBS metadata persisted in groups',all(g.ext['thai_bim'].get('bbs') for g in bars05))
    ids05=[g.uid for g in bars05];refs05=list(ss05.groups)
    dialog05.build();check05(kind05+' stable repeated update IDs',ids05==[g.uid for g in ss05.groups if g.ext['thai_bim'].get('host_uid')==host05.uid])
    history05.undo();check05(kind05+' Undo restores exact references',ss05.groups==refs05)
    dialog05.fields['spacing'].setValue(200);dialog05.build()
    check05(kind05+' spacing update removes superseded bars',len([g for g in ss05.groups if g.ext['thai_bim'].get('host_uid')==host05.uid])<len(bars05))
    history05.undo();check05(kind05+' removal Undo',ss05.groups==refs05)
    records05,issues05=tb05.bbs_records(ss05);check05(kind05+' valid host BBS included',len([r for r in records05 if r['host_uid']==host05.uid])==len(bars05))
    saved05=bars05[0].ext['thai_bim']['host_hash'];bars05[0].ext['thai_bim']['host_hash']='stale'
    records05,issues05=tb05.bbs_records(ss05);check05(kind05+' stale host excluded with reason',bars05[0].uid not in [r['id'] for r in records05] and bool(issues05))
    bars05[0].ext['thai_bim']['host_hash']=saved05
    dialog05.hide();dialog05.deleteLater()
records05,issues05=tb05.bbs_records(ss05)
tb05.E.write_xlsx(out05/'detailed-BBS.xlsx',tables=D05.tables(records05,issues05))
bbs05=B05.open_bbs(fp05);settle05();bbs05.grab().save(str(out05/'bbs-dialog.png'))
check05('BBS dialog row selection produces shape preview',any(w.specs for w in bbs05.findChildren(B05.AssemblyPreview)))
bbs05.close();bbs05.deleteLater();fp05.bbs_dialog=None
save_scene(ss05,out05/'detailed-rebar-test.igz');loaded05=Scene();load_into(loaded05,out05/'detailed-rebar-test.igz')
reloaded05,problems05=tb05.bbs_records(loaded05)
check05('IGZ reload BBS identity and analytic lengths',records05==reloaded05 and not problems05)
check05('IGZ reload fingerprints',all(tb05.mesh_fingerprint(g)==g.ext['thai_bim']['fingerprint'] for g in loaded05.groups))
save_glb(ss05,out05/'detailed-rebar-test.glb');check05('RGB native GLB export',(out05/'detailed-rebar-test.glb').stat().st_size>1000)
legacy05=tb05.make_group(B05.S.bar_spec('legacy',[(0,0,0),(1,0,0)],.012));ss05.groups.append(legacy05)
rr05,ii05=tb05.bbs_records(ss05);check05('legacy undetailed bars excluded',legacy05.uid not in [r['id'] for r in rr05] and any('Legacy' in i for i in ii05))
ss05.groups.pop();fp05.deleteLater();settle05()
check05('actual house scene unchanged',actual05==(list(scene.groups),scene.version,set(scene.selection)))
panel05.report.setPlainText('Thai BIM 0.5 • เหล็กรายละเอียด / BBS พร้อมใช้\nฐานราก L/U • เสา/คานปลอก 135° • ทาบและฝังยึดตามค่าผู้ใช้\nพื้น/บันไดยังใช้รายละเอียดเดิม และแยกออกจาก BBS')
panel05.workspace_dialog.hide()
print('Thai BIM '+tb05.E.VERSION+': '+str(len(checks05))+' native checks passed; house unchanged')
