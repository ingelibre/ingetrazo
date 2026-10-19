"""Six stair forms, nested solids, native Qt actions, explicit connections and QTO."""
import importlib
from core.extensions import _import_by_path,user_plugins_dir
tb07=_import_by_path('thai_bim',user_plugins_dir()/'thai_bim/__init__.py')
from ingetrazo_plugin_thai_bim import stairs as ST15,stairs_ui as SU15,type_ui as TU15,selected_edit as SE15,selected_geometry as SG15
W07=importlib.reload(W07);ST15=importlib.reload(ST15);SU15=importlib.reload(SU15);TU15=importlib.reload(TU15);SE15=importlib.reload(SE15);SG15=importlib.reload(SG15);B07.D=importlib.reload(B07.D)
checks07=checks07[:343];actual15=(list(scene.groups),scene.version,set(scene.selection))
na15=App07();np15=tb07.setup(na15);np15.guard=lambda fn:fn();ns15=na15.scene;na15.window.show();settle07();hosts15={};bars15={}
other15=tb07.make_group(tb07.E.box_spec('Column',-5,-5,0,.25,.25,3));np15.execute(tb07.ExchangeGroups(ns15,additions=[other15]));other_ext15=copy.deepcopy(other15.ext)
for index15,layout15 in enumerate(ST15.LAYOUTS):
    nd15=SU15.open_dialog(np15,False);nd15.layout_kind.setCurrentText(layout15);nd15.pf['x'].setValue(index15*10);nd15.pf['yaw'].setValue(15);nd15.preview();before15=list(ns15.groups)
    check07(layout15+' native stair concrete preview leaves scene unchanged',not nd15.visual.error and ns15.groups==before15)
    if layout15=='L':
        button15=next(b for b in nd15.findChildren(QPushButton) if b.text()=='สร้างคอนกรีตชุดใหม่');NativeEvents07.mouseClick(button15,Qt.LeftButton,Qt.NoModifier,button15.rect().center());settle07()
    else:nd15.create()
    host15=nd15.host();hosts15[layout15]=host15;record15=host15.ext['thai_bim']
    check07(layout15+' creates one nested Stair Host with schema and material system',record15['composite_stair'] and record15['stair_params']['stair_schema']==2 and record15['stair_params']['material_system']=='RC' and host15.children)
    check07(layout15+' every native concrete child is individually closed',all(tb07.bim.face_set_volume(list(child.mesh.faces))>0 for child in host15.children))
    check07(layout15+' gross concrete quantity agrees with measured child solids',abs(record15['quantity']-record15['volume_m3'])<2e-5)
    check07(layout15+' parent and children use Stair layer',host15.layer=='TBIM S Stair' and all(c.layer==host15.layer for c in host15.children))
    check07(layout15+' source geometry survives original other members',other15 in ns15.groups and other15.ext==other_ext15)
    rejects07(layout15+' steel needs explicit Host review before build',nd15.build_rebar)
    nd15.review();nd15.rf['spacing'].setValue(180);rejects07(layout15+' changed steel settings invalidate review',nd15.build_rebar);nd15.rf['spacing'].setValue(150);nd15.review()
    if layout15=='U':
        button15=next(b for b in nd15.findChildren(QPushButton) if b.text()=='สร้าง / อัปเดตเหล็กที่ตรวจแล้ว');NativeEvents07.mouseClick(button15,Qt.LeftButton,Qt.NoModifier,button15.rect().center());settle07()
    else:nd15.build_rebar()
    cage15=[g for g in ns15.groups if (g.ext or {}).get('thai_bim',{}).get('host_uid')==host15.uid];bars15[layout15]=cage15
    check07(layout15+' builds native centreline cage with role metadata',cage15 and all(g.ext['thai_bim'].get('stair_rebar_schema')==1 and not g.mesh.faces and g.ext['thai_bim']['bbs']['stair_layout']==layout15 for g in cage15))
    check07(layout15+' reinforcement follows Host rigid placement once',all(W07.pose(g)==W07.pose(host15) for g in cage15))
    recs15,issues15=tb07.bbs_records(ns15);check07(layout15+' BBS validates actual native concrete and bar geometry',not issues15 and len(recs15)==sum(len(b) for b in bars15.values()))
    rows15,qi15=tb07.quantity_rows(ns15);check07(layout15+' QTO measures nested solids instead of welded nonmanifold interfaces',not qi15 and abs(next(r['quantity'] for r in rows15 if r['id']==host15.uid)-record15['volume_m3'])<1e-6)
    na15.viewport.history.undo();check07(layout15+' bar Undo retains exact concrete and other Hosts',host15 in ns15.groups and all(g not in ns15.groups for g in cage15));na15.viewport.history.redo();check07(layout15+' bar Redo restores exact cage objects',all(g in ns15.groups for g in cage15))
    ids15={g.ext['thai_bim']['slot']:(g.uid,g.ext['thai_bim']['id']) for g in cage15};nd15.review();nd15.build_rebar();cage15=[g for g in ns15.groups if g.ext['thai_bim'].get('host_uid')==host15.uid];bars15[layout15]=cage15
    check07(layout15+' same slot regeneration preserves native and business IDs',ids15=={g.ext['thai_bim']['slot']:(g.uid,g.ext['thai_bim']['id']) for g in cage15})
    if layout15 in ('L','Spiral','Floating'):
        nd15.show();settle07();nd15.grab().save(str(out07/('stair-'+layout15.lower()+'-dialog.png')))
    nd15.read_host();check07(layout15+' read restores exact saved geometry pose and steel settings',nd15.geometry()==host15.ext['thai_bim']['stair_params'] and nd15.rebar()==cage15[0].ext['thai_bim']['stair_rebar_params'] and W07.P.same_pose(nd15.pose(),W07.pose(host15)))
    if layout15=='L':
        old15=host15;nd15.gf['height'].setValue(3.12);oldroots15=list(ns15.groups);nd15.update();new15=nd15.host();hosts15[layout15]=new15
        check07('L concrete selected update retains identity and old bars for review',new15.uid==old15.uid and new15.ext['thai_bim']['id']==old15.ext['thai_bim']['id'] and all(g in ns15.groups for g in cage15))
        check07('L concrete update marks cage stale',any(r['uid']==new15.uid and r['state']=='Review' for r in W07.host_notices(ns15)))
        na15.viewport.history.undo();check07('L concrete Undo restores exact original nested Host',ns15.groups==oldroots15 and old15 in ns15.groups);na15.viewport.history.redo();ns15.selection={new15};nd15.read_host();nd15.review();nd15.build_rebar();bars15[layout15]=[g for g in ns15.groups if g.ext['thai_bim'].get('host_uid')==new15.uid]
        check07('L changed concrete cage rebuild restores valid BBS',not tb07.bbs_records(ns15)[1])
    nd15.close()
# New routing and legacy compatibility.
ns15.selection={hosts15['U']};np15.open_builder('Stair');check07('Stair toolbar opens new illustrated forms dialog',isinstance(np15.stairs_dialog,SU15.StairsDialog));np15.stairs_dialog.close()
np15.open_builder('Rebar');check07('Rebar toolbar routes schema 2 Stair to new module',isinstance(np15.stairs_dialog,SU15.StairsDialog));np15.stairs_dialog.close()
advanced15=SE15.open_dialog(np15);check07('selected instance editor routes schema 2 Stair correctly',isinstance(advanced15,SU15.StairsDialog));advanced15.close()
legacy15=B07.RebarDialog(np15);rejects07('legacy rebar builder cannot replace advanced Stair cage',legacy15.read_host);legacy15.deleteLater()
row15=next(r for r in TU15.library(ns15)['types'] if r['kind']=='Stair');rejects07('legacy straight type cannot silently replace U geometry',lambda:TU15.update_selected(ns15,row15))
# Exact guards after read / review, copied compound groups and child edits.
nd15=SU15.open_dialog(np15);nd15.review();savedpose15=hosts15['U'].xform;hosts15['U'].xform=W07.matrix(W07.P.matrix((100,0,0)));rejects07('moved Stair after review blocks stale cage creation',nd15.build_rebar);hosts15['U'].xform=savedpose15
nd15.read_host();nd15.review();ns15.selection={other15};rejects07('Stair selection switch blocks previously reviewed cage',nd15.build_rebar);ns15.selection={hosts15['U']}
nd15.read_host();nd15.review();bound15=nd15.bound_scene;nd15.bound_scene=Scene();rejects07('Stair document switch blocks creating bars in another file',nd15.build_rebar);nd15.bound_scene=bound15
child15=hosts15['U'].children[0];vertex15=next(iter(child15.mesh.vertices));point15=QVector3D(vertex15.position);vertex15.position+=QVector3D(.01,0,0);rejects07('nested stair child edit invalidates Host fingerprint',nd15.read_host);vertex15.position=point15
nd15.read_host();nd15.review();bar15=bars15['U'][0];barpose15=bar15.xform;bar15.xform=W07.matrix(W07.P.matrix((0,0,0)));rejects07('independently moved stair bar prevents regeneration',nd15.review);bar15.xform=barpose15
from core.group import copy_group
from ingetrazo_plugin_thai_bim import copy_identity as CI15
clone15=copy_group(hosts15['U']);ns15.groups.append(clone15);rejects07('copied Stair IDs block selected update',nd15.update);np15.execute(CI15.RepairCopies(ns15));ns15.selection={clone15};nd15.read_host();check07('repaired copied compound Stair receives independent business binding',clone15.ext['thai_bim']['id']!=hosts15['U'].ext['thai_bim']['id'] and clone15.ext['thai_bim']['native_uid']==clone15.uid);nd15.update();clone_new15=nd15.host();nd15.review();nd15.build_rebar()
check07('native compound Stair copy can update and build independent cage',clone_new15.ext['thai_bim']['id']!=hosts15['U'].ext['thai_bim']['id'] and all(g in ns15.groups for g in bars15['U']) and not tb07.bbs_records(ns15)[1])
# Designer-specified connector table, catalogue and top/bottom mats.
ns15.selection={hosts15['Circular']};nd15.read_host();nd15.add_connection();nd15.connections.item(0,0).setText('รอยต่อชานพักโค้ง');nd15.review();nd15.build_rebar();circ15=[g for g in ns15.groups if g.ext['thai_bim'].get('host_uid')==hosts15['Circular'].uid]
check07('connection table creates repeated planar L bars with Thai names',len([g for g in circ15 if 'รอยต่อชานพักโค้ง' in g.ext['thai_bim']['bbs']['stair_role']])==3)
nd15.read_host();check07('connection table survives Host read with exact coordinates and name',nd15.connections.rowCount()==1 and nd15.connections.item(0,0).text()=='รอยต่อชานพักโค้ง')
ns15.selection={hosts15['Straight']};nd15.read_host();nd15.gf['waist'].setValue(.2);nd15.gf['landing_thickness'].setValue(.25);nd15.update();hosts15['Straight']=nd15.host();nd15.mats.setCurrentIndex(1)
steel15=C07.selection(C07.TIS_DB,'DB12','SD40');combo15,records15=nd15.steels['main'];combo15.setCurrentIndex(records15.index(steel15));nd15.review();nd15.build_rebar()
check07('two mat Stair detailing uses separate Top Bottom roles and DB nominal size',not nd15.rf['diameter'].isEnabled() and nd15.rf['diameter'].value()==12 and any('Main Top' in r['bbs']['stair_role'] for r in tb07.bbs_records(ns15)[0]))
# Native 3D helix tube, plus Full and Lightweight planar connection tubes.
curve15=next(s for s in ST15.reinforcement(dict(layout='Circular',inner_radius=1.5,sweep=180),dict(connection=0,representation='Lightweight')) if s['bbs']['shape']=='3D helix');tube15=tb07.make_group(curve15)
check07('Lightweight 3D helical bar is a native watertight solid',tb07.bim.face_set_volume(list(tube15.mesh.faces))>0)
for rep15 in ('Full','Lightweight'):
    s15=ST15.reinforcement(dict(layout='L'),dict(representation=rep15))[0];g15=tb07.make_group(s15);check07(rep15+' stair cranked main bar is native watertight solid',tb07.bim.face_set_volume(list(g15.mesh.faces))>0)
recs15,issues15=tb07.bbs_records(ns15);check07('all final stair BBS records validate native model and poses',not issues15)
tables15=B07.D.tables(recs15);check07('stair BBS export separates roles layouts and length basis',tables15[0][1][0][-3:]==['Stair layout','Stair role','Length basis'] and any('Helical' in str(v) for row in tables15[0][1] for v in row))
tb07.E.write_xlsx(out07/'stairs-reinforcement-BBS.xlsx',tables=tables15);M07.compact_save(ns15,out07/'stairs-RC-all-forms-ไทย.igz');opened15=Scene();load_into(opened15,out07/'stairs-RC-all-forms-ไทย.igz')
check07('nested Stair IGZ roundtrip preserves all parent metadata',json.dumps([g.ext for g in opened15.groups],sort_keys=True)==json.dumps([g.ext for g in ns15.groups],sort_keys=True))
check07('nested concrete children and roles persist through IGZ',sum(len(g.children) for g in opened15.groups)==sum(len(g.children) for g in ns15.groups) and all(child.ext.get('thai_bim_part') for g in opened15.groups for child in g.children))
check07('all six Stair forms BBS validates after native IGZ reopen',not tb07.bbs_records(opened15)[1] and len(tb07.bbs_records(opened15)[0])==len(recs15))
qr15,qi15=tb07.quantity_rows(opened15);check07('reopened Stair quantities are measured closed component sums',not qi15 and all(r['quantity'] is not None for r in qr15))
save_glb(opened15,out07/'stairs-RC-all-forms.glb');check07('nested stairs and centreline bars export native GLB',(out07/'stairs-RC-all-forms.glb').stat().st_size>1000)
check07('new stair module retains 21 icons and installs idempotently',len(np15.toolbar.actions())==21);SU15.install(np15);check07('reinstall advanced stairs does not duplicate toolbar icons',len(np15.toolbar.actions())==21)
original_token15=W07.host_token;calls15={}
def counted_token15(host):
    calls15[host.uid]=calls15.get(host.uid,0)+1;return original_token15(host)
W07.host_token=counted_token15
try:
    cached15=tb07.bbs_records(ns15);check07('BBS export computes geometry token exactly once per reinforcement Host',not cached15[1] and calls15 and set(calls15.values())=={1})
    calls15.clear();cached15=tb07.bbs_records(ns15);check07('BBS geometry cache is fresh for every export',not cached15[1] and set(calls15.values())=={1})
finally:W07.host_token=original_token15
testhost15=hosts15['Spiral'];ch15=testhost15.children[0];v15=next(iter(ch15.mesh.vertices));pos15=QVector3D(v15.position);v15.position+=QVector3D(.01,0,0)
changed15=tb07.bbs_records(ns15);check07('new export detects child edits despite earlier valid cached export',changed15[1] and all(r['host_uid']!=testhost15.uid for r in changed15[0]));v15.position=pos15
right15=tb07.make_group(ST15.spec(layout='U',hand='Right'));check07('Right hand reflected stair is native closed composite',all(tb07.bim.face_set_volume(list(c.mesh.faces))>0 for c in right15.children))
fullcurve15=next(s for s in ST15.reinforcement(dict(layout='Circular',inner_radius=1.5,sweep=180),dict(connection=0,representation='Full')) if s['bbs']['shape']=='3D helix');fulltube15=tb07.make_group(fullcurve15);check07('Full 3D helix native volume agrees with nominal tube within facet tolerance',.90<tb07.bim.face_set_volume(list(fulltube15.mesh.faces))/(math.pi*fullcurve15['bar_diameter']**2/4*fullcurve15['quantity'])<1.01)
panel07.open_builder.__code__=np15.open_builder.__code__;SU15.install(panel07)
na15.window.deleteLater();settle07()
from core import units as units15
units15.bind_scene(scene);check07('stair tests preserve actual user document geometry',actual15==(list(scene.groups),scene.version,set(scene.selection)))
print('PASS: '+str(len(checks07))+' native checks including six RC stair forms and reinforcement')
