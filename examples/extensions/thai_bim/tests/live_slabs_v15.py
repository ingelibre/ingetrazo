"""Native tests of actual slab dialog in private scenes; no user geometry changes."""
import importlib
from ingetrazo_plugin_thai_bim import slab_rebar as SR14,slab_ui as SU14,selected_edit as SE14
SR14=importlib.reload(SR14);SU14=importlib.reload(SU14);SE14=importlib.reload(SE14)
B07.D=importlib.reload(B07.D)
actual14=(list(scene.groups),scene.version,set(scene.selection));checks07=checks07[:298]
sa14=App07();sp14=tb07.setup(sa14);sp14.guard=lambda fn:fn();ss14=sa14.scene;sa14.window.show();settle07()
other14=tb07.make_group(tb07.E.box_spec('Column',10,10,0,.25,.25,3));sp14.execute(tb07.ExchangeGroups(ss14,additions=[other14]));other_ext14=copy.deepcopy(other14.ext)
hostsp14,pose14=PG10.polygon([(5,5),(2,5),(2,2),(4,2),(4,4),(5,4)],3,dict(height=.18))
ph14=tb07.make_group(hostsp14);ph14.name='พื้นทางเดียวรูปเว้า';ph14.xform=W07.matrix(pose14);sp14.execute(tb07.ExchangeGroups(ss14,additions=[ph14]));ss14.selection={ph14}
sd14=SU14.open_dialog(sp14);settle07()
check07('slab dialog reads negative local concave Host with genuine preview',sd14.host_uid==ph14.uid and not sd14.visual.error and sd14.visual.host)
check07('slab initial preview creates no reinforcement',len(ss14.groups)==2)
rejects07('slab explicit review required before build',sd14.build)
sd14.review();sd14.fields['spacing_a'].setValue(180);rejects07('slab changed settings after review block build',sd14.build);sd14.fields['spacing_a'].setValue(150);sd14.review()
button14=next(b for b in sd14.findChildren(QPushButton) if b.text().startswith('สร้าง / อัปเดตเหล็กพื้น'))
NativeEvents07.mouseClick(button14,Qt.LeftButton,Qt.NoModifier,button14.rect().center());settle07()
bars14=[g for g in ss14.groups if (g.ext or {}).get('thai_bim',{}).get('host_uid')==ph14.uid]
check07('actual Qt create click builds concave slab centreline bars',len(bars14)>0 and all(not g.mesh.faces for g in bars14))
check07('slab bar pose applies Host transform exactly once',all(W07.pose(g)==W07.pose(ph14) for g in bars14))
check07('slab creation preserves original concrete and other members',ph14 in ss14.groups and other14 in ss14.groups and other14.ext==other_ext14)
check07('slab metadata stores individual roles and per Host settings',all(g.ext['thai_bim']['slab_rebar_schema']==1 and 'slab_role' in g.ext['thai_bim']['bbs'] for g in bars14))
records14,issues14=tb07.bbs_records(ss14);check07('polygon BBS validates actual Host and native geometry',not issues14 and len(records14)==len(bars14))
check07('polygon quantities equal clipped analytic wire paths',abs(sum(r['bbs']['length_m'] for r in records14)-sum(s['quantity'] for s in SR14.generate(ph14.ext['thai_bim']['params'],sd14.params())))<1e-7)
sa14.viewport.history.undo();check07('slab Undo removes bars and keeps exact concrete objects',ss14.groups==[other14,ph14]);sa14.viewport.history.redo();check07('slab Redo restores exact bars',all(g in ss14.groups for g in bars14))
ids14={g.ext['thai_bim']['slot']:(g.uid,g.ext['thai_bim']['id']) for g in bars14};sd14.review();sd14.build();barsnew14=[g for g in ss14.groups if g.ext['thai_bim'].get('host_uid')==ph14.uid]
check07('slab same slot update preserves native and business IDs',ids14=={g.ext['thai_bim']['slot']:(g.uid,g.ext['thai_bim']['id']) for g in barsnew14})
sd14.read_host();check07('slab dialog reloads saved per instance settings',sd14.params()==barsnew14[0].ext['thai_bim']['slab_rebar_params'])
sd14.review();ss14.selection={other14};rejects07('slab selection changed after preview blocks update',sd14.build);ss14.selection={ph14};sd14.review()
originalpose14=ph14.xform;ph14.xform=W07.matrix(W07.P.matrix((20,0,0)));rejects07('slab moved Host after review blocks update',sd14.build);ph14.xform=originalpose14
originalbarpose14=barsnew14[0].xform;barsnew14[0].xform=W07.matrix(W07.P.matrix((0,0,0)));rejects07('slab independently moved bars block regeneration',sd14.review);barsnew14[0].xform=originalbarpose14
from core.group import copy_group
clone14=copy_group(ph14);ss14.groups.append(clone14);rejects07('slab native copy IDs require repair before review',sd14.review);ss14.groups.remove(clone14)
bound14=sd14.bound_scene;sd14.bound_scene=Scene();rejects07('slab document switch cannot update original document',sd14.build);sd14.bound_scene=bound14
sd14.read_host();sd14.show();settle07();sd14.grab().save(str(out07/'slab-one-way-dialog.png'));sd14.close()
sp14.open_builder('Rebar');check07('existing Rebar icon routes selected Slab to new slab dialog',isinstance(sp14.slab_dialog,SU14.SlabDialog));sp14.slab_dialog.close()
legacy14=B07.RebarDialog(sp14);rejects07('legacy rectangular generator cannot overwrite new polygon cage',legacy14.read_host);legacy14.deleteLater()
# Rectangular host with rotated placement for Two-way and then Precast conversion.
rh14=tb07.make_group(tb07.E.box_spec('Slab',0,0,0,3,2,.18));rh14.xform=W07.matrix(W07.P.matrix((7,0,3),30));rh14.name='พื้นสองทาง / พื้นสำเร็จ';sp14.execute(tb07.ExchangeGroups(ss14,additions=[rh14]));ss14.selection={rh14}
rd14=SU14.open_dialog(sp14);rd14.mode.setCurrentText('Two-way');rd14.mats.setCurrentIndex(1)
cat14=C07.selection(C07.TIS_DB,'DB12','SD40');combo14,rows14=rd14.steels['a'];combo14.setCurrentIndex(rows14.index(cat14));rd14.review();rd14.build()
rc14=[g for g in ss14.groups if g.ext['thai_bim'].get('host_uid')==rh14.uid]
check07('two way native bars contain four distinct mat roles',len({g.ext['thai_bim']['bbs']['slab_role'] for g in rc14})==4)
check07('slab RB DB catalogue controls lock nominal millimetre diameter',not rd14.fields['diameter_a'].isEnabled() and rd14.fields['diameter_a'].value()==12 and any(g.ext['thai_bim'].get('steel')==cat14 for g in rc14))
rd14.show();settle07();rd14.grab().save(str(out07/'slab-two-way-dialog.png'))
rd14.mode.setCurrentText('Precast');rd14.fields['wire_a'].setValue(3);rd14.fields['wire_b'].setValue(3);rd14.wire_name.setText('ไวร์เมชตัวอย่าง 3 mm');rd14.dowels.setChecked(True);rd14.review()
before14=list(ss14.groups);rd14.build();pre14=[g for g in ss14.groups if g.ext['thai_bim'].get('host_uid')==rh14.uid]
check07('precast conversion replaces only selected Host cage',all(g not in ss14.groups for g in rc14) and all(g in ss14.groups for g in barsnew14) and other14 in ss14.groups)
check07('precast native mesh accepts 3 mm wires',any(g.ext['thai_bim']['bar_diameter']==.003 and g.ext['thai_bim']['bbs']['wire'] for g in pre14))
check07('precast native BBS distinguishes mesh and both end dowels',{g.ext['thai_bim']['bbs']['slab_role'] for g in pre14}=={'Wire mesh A','Wire mesh B','End dowel Start','End dowel End'})
check07('precast UI enables only relevant module parameters',not rd14.fields['diameter_a'].isEnabled() and rd14.fields['wire_a'].isEnabled() and rd14.fields['dowel_embed'].isEnabled() and not rd14.mats.isEnabled())
sa14.viewport.history.undo();check07('precast conversion Undo restores original two way cage',ss14.groups==before14);sa14.viewport.history.redo();check07('precast conversion Redo preserves independent polygon bars',all(g in ss14.groups for g in pre14+barsnew14))
rd14.read_host();check07('precast reopen restores mesh name size and dowel settings',rd14.params()==pre14[0].ext['thai_bim']['slab_rebar_params'])
records14,issues14=tb07.bbs_records(ss14);check07('combined slab BBS validates all installed bars',not issues14 and len(records14)==len(pre14)+len(barsnew14))
tables14=B07.D.tables(records14);check07('actual BBS export contains slab mode role and Thai mesh specification',tables14[0][1][0][-3:]==['Slab system','Slab role','Mesh specification'] and any(row[-1]=='ไวร์เมชตัวอย่าง 3 mm' for row in tables14[0][1][1:]))
tb07.E.write_xlsx(out07/'slab-reinforcement-BBS.xlsx',tables=B07.D.tables(records14));check07('slab BBS actual Excel artifact created',(out07/'slab-reinforcement-BBS.xlsx').stat().st_size>1000)
M07.compact_save(ss14,out07/'slab-reinforcement-ไทย.igz');reload14=Scene();load_into(reload14,out07/'slab-reinforcement-ไทย.igz')
check07('slab IGZ reopen retains exact Thai mesh name metadata and BBS',json.dumps([g.ext for g in reload14.groups],sort_keys=True)==json.dumps([g.ext for g in ss14.groups],sort_keys=True))
rr14,ii14=tb07.bbs_records(reload14);check07('slab reopened IGZ validates quantities against native geometry',not ii14 and len(rr14)==len(records14))
rd14.show();settle07();rd14.grab().save(str(out07/'slab-precast-dialog.png'))
SE14.open_dialog(sp14).rebar();check07('selected instance editor routes Slab Host review to slab module',isinstance(sp14.selected_edit_dialog.rebar_dialog,SU14.SlabDialog))
check07('slab install does not duplicate existing 21 toolbar icons',len(sp14.toolbar.actions())==21);SU14.install(sp14);check07('slab module install is idempotent',len(sp14.toolbar.actions())==21)
qrows14,qissues14=tb07.quantity_rows(ss14);check07('native QTO separates wire mesh and end dowel roles',not qissues14 and any('Wire mesh A' in r['item'] for r in qrows14) and any('End dowel Start' in r['item'] for r in qrows14))
for rep14 in ('Full','Lightweight'):
    fh14=tb07.make_group(tb07.E.box_spec('Slab',0,5,0,1,1,.18));sp14.execute(tb07.ExchangeGroups(ss14,additions=[fh14]));ss14.selection={fh14}
    fd14=SU14.open_dialog(sp14);fd14.mode.setCurrentText('Precast');fd14.representation.setCurrentText(rep14);fd14.fields['wire_a'].setValue(3);fd14.fields['wire_b'].setValue(3);fd14.review();fd14.build()
    fb14=[g for g in ss14.groups if g.ext['thai_bim'].get('host_uid')==fh14.uid]
    check07(rep14+' slab wire native closed geometry has positive volume',all(g.mesh.faces and tb07.bim.face_set_volume(list(g.mesh.faces))>0 for g in fb14))
    check07(rep14+' slab wire BBS remains valid against native Host',not tb07.bbs_records(ss14)[1]);fd14.close()
panel07.open_builder.__code__=sp14.open_builder.__code__;SU14.install(panel07)
check07('current actual panel has discoverable slab module',getattr(panel07,'_slab_rebar_installed',False))
sa14.window.deleteLater();settle07()
from core import units as units14
units14.bind_scene(scene);check07('slab tests preserve actual user document geometry',actual14==(list(scene.groups),scene.version,set(scene.selection)))
print('PASS: '+str(len(checks07))+' native checks including polygon slabs, two-way mats, mesh and end dowels')
