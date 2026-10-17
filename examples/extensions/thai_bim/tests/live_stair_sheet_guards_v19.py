"""Native scale choices, steel catalogues, events, guards and unchanged document."""
from core.group import copy_group
from PySide6.QtWidgets import QPushButton
from PySide6.QtGui import QMatrix4x4
DR19=importlib.reload(SD19.D);SD19=importlib.reload(SD19)
ss19.selection={host19};sd19=DR19.open_dialog(sp19)
check19('existing Sheet toolbar route opens Stair Sheets for selected schema-2 Stair',isinstance(sd19,SD19.StairDrawingDialog) and sd19.isVisible())
# Actual Qt event runs the review operation, not a separate mock implementation.
button19=next(b for b in sd19.findChildren(QPushButton) if b.text()=='ตรวจพรีวิวทุกหน้า');NativeEvents07.mouseClick(button19,Qt.LeftButton,Qt.NoModifier,button19.rect().center());settle07()
check19('native Qt review button produces linked page previews',sd19.review is not None and sd19.pages.count()==9)
for n19 in (20,25):
 sd19.paper.setCurrentText('A1' if n19==20 else 'A2');sd19.scale.setCurrentText(str(n19));sd19.prepare();sd19.build();sd19.acknowledge();parts19,meta19=SD19.validate(ss19,host19.uid)
 check19('requested 1:'+str(n19)+' kept in native dimension scaling',all(d.scale_n==n19 for c in parts19 for d in c.cotas) and abs(abs(next(d for d in parts19[0].cotas if abs(d.real_distance_m()-1)<1e-6).dy_mm)-1000/n19)<1e-4)
 SD19.export_pdf(sp19,host19.uid,out19/('stair-scale-'+str(n19)+('-A1.pdf' if n19==20 else '-A2.pdf')))
 check19('1:'+str(n19)+' PDF exported without auto fit',(out19/('stair-scale-'+str(n19)+('-A1.pdf' if n19==20 else '-A2.pdf'))).stat().st_size>1000)
sd19.paper.setCurrentText('A3');sd19.scale.setCurrentText('20');reject19('too-small A3 at 1:20 rejects clipping instead of auto-scaling',sd19.prepare)
sd19.scale.setCurrentText('50');sd19.prepare();sd19.build();sd19.acknowledge()
check19('restored default A3 1:50 retains valid original Stair set',not any(r['reasons'] for r in SD19.status(ss19,host19.uid)))
# Source changes automatically appear in visible native status table.
bar19=next(g for g in ss19.groups if g.ext.get('thai_bim',{}).get('host_uid')==host19.uid);vertex19=next(iter(bar19.mesh.vertices));pos19=QVector3D(vertex19.position);vertex19.position+=QVector3D(.01,0,0);sa19.viewport.notify_scene_changed();settle07()
check19('native scene-version event refreshes stale drawing status automatically',any('stale' in sd19.table.item(i,3).text().lower() or 'edited' in sd19.table.item(i,3).text().lower() for i in range(sd19.table.rowCount())))
reject19('edited actual cage cannot produce fabrication details',sd19.prepare);vertex19.position=pos19;sa19.viewport.notify_scene_changed()
copy19=copy_group(host19);ss19.groups.append(copy19);reject19('copied business IDs block ambiguous stair source',sd19.prepare);ss19.groups.remove(copy19)
uid19=host19.uid;guard_scene19=Scene();sa19.viewport.scene=guard_scene19;reject19('document change blocks bound drawing dialog',sd19.check);sa19.viewport.scene=ss19
editbox19=tb07.make_group(tb07.E.box_spec('Beam',-10,-10,0,1,1,1));ss19.groups.append(editbox19);sa19.viewport.begin_group_edit(editbox19);reject19('nested group editing blocks drawing creation',sd19.check);sa19.viewport.end_group_edit();ss19.groups.remove(editbox19)
oldpose19=copy.deepcopy(host19.xform);tilt19=QMatrix4x4();tilt19.rotate(15,1,0,0);host19.xform=tilt19;reject19('tilted Stair is rejected rather than reporting wrong world levels',lambda:SD19.source(ss19,host19.uid,False));host19.xform=oldpose19
# Full actual structural/steel catalogue is copied to sheet rows, not guessed from diameter.
for label19,record19 in [('TIS RB',C07.selection(C07.TIS_RB,'RB6','SR24')),('TIS DB',C07.selection(C07.TIS_DB,'DB12','SD40')),('ASTM',C07.selection(C07.ASTM_IN,'#3','Grade 60 [420]'))]:
 check19(label19+' exact steel catalogue label preserved for drawing detail',record19['size'] in SD19.steel_label(dict(steel=record19)) and record19['grade'] in SD19.steel_label(dict(steel=record19)))
# Concrete-only set works without inventing reinforcement, but BBS export is guarded.
cspec19=tb07.make_group(ST15.spec(layout='Straight'));ss19.groups.append(cspec19);ss19.selection={cspec19};cd19=SD19.open_dialog(sp19);cd19.steel.setChecked(False);cd19.prepare();cd19.build()
check19('concrete-only Stair creates plan and true section without fake BBS',len(SD19.validate(ss19,cspec19.uid)[0])==2 and not ss19.plugin_data[SD19.KEY][cspec19.uid]['steel'])
reject19('concrete-only set cannot export invented BBS',lambda:SD19.export_bbs(ss19,cspec19.uid,out19/'should-not-exist.xlsx'))
# Typed copy of a sheet remains independent when original name is present.
ss19.selection={host19};sd19=SD19.open_dialog(sp19);parts19,meta19=SD19.validate(ss19,host19.uid);copysheet19=copy.deepcopy(parts19[0]);copysheet19.name='User copied plan';ss19.compositions.append(copysheet19)
check19('user copied sheet does not redirect original managed-sheet ownership',SD19.validate(ss19,host19.uid)[0][0] is parts19[0])
M07.compact_save(ss19,out19/'stair-all-forms-drawings-ไทย.igz');readall19=Scene();load_into(readall19,out19/'stair-all-forms-drawings-ไทย.igz')
check19('all six final drawing sets validate after native IGZ roundtrip',all(not any(r['reasons'] for r in SD19.status(readall19,h.uid)) for h in fixtures19.values()))
check19('stair drawing tools retain 21 toolbar icons',len(sp19.toolbar.actions())==21)
check19('all stair drawing tests preserve actual user document geometry',[(g.uid,g.name,tb07.mesh_fingerprint(g)) for g in actual19[0]]==[(g.uid,g.name,tb07.mesh_fingerprint(g)) for g in scene.groups] and sorted(g.uid for g in actual19[2])==sorted(g.uid for g in scene.selection))
(out19/'final-fixture-pages.json').write_text(json.dumps({layout:len(SD19.validate(ss19,h.uid)[0]) for layout,h in fixtures19.items()},indent=2),encoding='utf8')
print('PASS '+str(len(checks19))+' native stair drawing checks')
