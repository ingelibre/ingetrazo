"""Final full-cage graphics, native Qt events, scale exports and source identity."""
from PySide6.QtCore import Qt
MG20=importlib.reload(MG20);SD20=importlib.reload(SD20);MD20=importlib.reload(MD20)
for label20,h20 in fixtures20.items():
 ss20.selection={h20};d20=MD20.open_dialog(sp20);button20=next(b for b in d20.findChildren(QPushButton) if b.text()=='ตรวจพรีวิวทุกหน้า')
 NativeEvents07.mouseClick(button20,Qt.LeftButton,Qt.NoModifier,button20.rect().center());settle20();d20.build()
 if any(r['reasons'] for r in MD20.status(ss20,h20.uid)):d20.acknowledge()
 check20(label20+' actual Qt preview button and final full-cage projection',d20.review is not None and len(d20.preview_parts[0].shapes)>25)
 MD20.export_pdf(sp20,h20.uid,out20/(label20+'-A3-50.pdf'));MD20.export_bbs(ss20,h20.uid,out20/(label20+'-BBS.xlsx'))
 if label20=='Footing':d20.grab().save(str(out20/'member-drawing-dialog.png'))
 if label20=='Beam':d20.pages.setCurrentIndex(1);d20.grab().save(str(out20/'beam-drawing-dialog.png'))
 d20.close()
ss20.selection={fixtures20['Footing']};d20=MD20.open_dialog(sp20)
for n20 in (20,25):
 d20.scale.setCurrentText(str(n20));d20.prepare();d20.build();d20.acknowledge();MD20.export_pdf(sp20,d20.uid,out20/('Footing-scale-'+str(n20)+'-A3.pdf'))
d20.scale.setCurrentText('50');d20.prepare();d20.build();d20.acknowledge();d20.close()
from ingetrazo_plugin_thai_bim import path_geometry as PG20
bs20,bp20=PG20.beam((1,2),(4,6),3.65,dict(depth=.3,height=.5));two20=tb20.make_group(bs20);two20.xform=W20.matrix(bp20);ss20.groups.append(two20);ss20.selection={two20};bd20=MD20.open_dialog(sp20);bd20.steel.setChecked(False);bd20.prepare();bd20.build()
pc20,_=MD20.validate(ss20,two20.uid);check20('native two-point rotated beam drawings retain 5m span and +3.65 level',any(abs(d.real_distance_m()-5)<1e-6 for d in pc20[1].cotas) and set(round(n.level_m(),3) for n in pc20[1].niveles)=={3.65,4.15});bd20.close()
ss20.selection={fixtures20['Footing']};d20=MD20.open_dialog(sp20);new20=Scene();app20.viewport.scene=new20;reject20('member sheet dialog refuses switched document',d20.check);app20.viewport.scene=ss20
edit20=tb20.make_group(EN20.box_spec('Column',-10,-10,0,1,1,1));ss20.groups.append(edit20);app20.viewport.begin_group_edit(edit20);reject20('member sheets refuse group edit context',d20.check);app20.viewport.end_group_edit();ss20.groups.remove(edit20)
# Events refresh a visible member status without manually opening it again.
rename20=fixtures20['Footing'];oldname20=rename20.name;rename20.name='Changed name';app20.viewport.notify_scene_changed();settle20()
check20('member status table refreshes automatically on scene-version event',any('เปลี่ยน' in d20.table.item(i,3).text() for i in range(d20.table.rowCount())));rename20.name=oldname20;app20.viewport.notify_scene_changed();d20.close()
M20.compact_save(ss20,out20/'members-drawings-ไทย.igz');read20=Scene();load_into(read20,out20/'members-drawings-ไทย.igz')
check20('final full-cage member IGZ retains current sets and manual archives',all(not any(r['reasons'] for r in MD20.status(read20,h.uid)) for h in fixtures20.values()) and any(any(t.text.startswith('USER ไทย:') for t in c.texts) for c in read20.compositions))
check20('final development leaves actual user geometry and selection unchanged',actual20==[(g.uid,g.name,tb20.mesh_fingerprint(g)) for g in scene.groups] and actual_selection20=={g.uid for g in scene.selection})
print('PASS',len(checks20),'native checks')
