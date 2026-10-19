"""Native stair/support clipping, explicit evidence, stale guards and Qt preview."""
import importlib
from core.group import Group,copy_group
from core.mesh import Mesh
from PySide6.QtGui import QMatrix4x4
from PySide6.QtWidgets import QFileDialog
from core.bim import tag_group
from ingetrazo_plugin_thai_bim import stair_connections as CN18,stair_connection_ui as CU18,stairs_ui as SU18
CN18=importlib.reload(CN18);CU18=importlib.reload(CU18);SU18=importlib.reload(SU18)
actual18=(list(scene.groups),scene.version,set(scene.selection));checks07=checks07[:623]
ca18=App07();cp18=tb07.setup(ca18);cp18.guard=lambda fn:fn();cs18=ca18.scene;cv18=ca18.viewport;ch18=cv18.history;ca18.window.show();settle07()
sd18=SU18.open_dialog(cp18,False);sd18.layout_kind.setCurrentText('Straight');sd18.add_connection()
for j,v in enumerate(('เหล็กต่อรองรับ',-.4,.2,-.1,0,.8,0,3,.15)):sd18.connections.item(0,j).setText(str(v))
sd18.create();st18=sd18.host();role18='Explicit connection เหล็กต่อรองรับ';start18=list(cs18.groups)
sp18=tb07.make_group(tb07.E.box_spec('Beam',-.2,.1,-.2,.4,.8,.2));cp18.execute(tb07.ExchangeGroups(cs18,additions=[sp18]));cs18.selection={st18}
cd18=CU18.open_dialog(cp18);cd18.roles.setCurrentText(role18);cd18.targets.setCurrentIndex(cd18.targets.findData(sp18.uid));cd18.required.setValue(300)
check07('connection button opens native dialog with five geometric result columns',cd18.isVisible() and cd18.table.columnCount()==5 and len(cp18.toolbar.actions())==21)
check07('new Host without cage offers Proposed saved Host settings',cd18.mode.currentText()=='Proposed' and role18 in [cd18.roles.itemText(i) for i in range(cd18.roles.count())])
btn18=next(b for b in cd18.findChildren(QPushButton) if b.text()=='ตรวจและพรีวิว');NativeEvents07.mouseClick(btn18,Qt.LeftButton,Qt.NoModifier,btn18.rect().center());settle07()
r18=cd18.reviewed();check07('native triangle clipping measures 400 mm inside actual Beam for three explicit bars',len(r18['rows'])==3 and all(abs(r['longest_inside_m']-.4)<1e-6 and r['state']=='geometry_length_met' for r in r18['rows']))
check07('native geometric report explicitly excludes strength certification',r18['design_verified'] is False and r18['mode']=='Proposed' and r18['support_class']=='IfcBeam')
check07('connection preview leaves concrete and bars unchanged',cs18.groups==start18+[sp18] and not cd18.visual.error)
cd18.table.setCurrentCell(1,0);settle07();check07('native row selection focuses one bar with support and stair context',not cd18.visual.error)
cd18.grab().save(str(out07/'stair-connection-dialog.png'))
cd18.required.setValue(500);rejects07('changed requested geometric length blocks saving prior review',cd18.reviewed);cd18.inspect();check07('500 mm user input reports short against continuous 400 mm',all(r['state']=='geometry_length_short' for r in cd18.report['rows']))
cd18.required.setValue(0);cd18.inspect();check07('missing requested length is explicit rather than passed',all(r['state']=='requirement_missing' for r in cd18.report['rows']))
cd18.required.setValue(300);cd18.inspect();beforedata18=copy.deepcopy(cs18.plugin_data);beforegroups18=list(cs18.groups);cd18.save();saved18=copy.deepcopy(cs18.plugin_data)
check07('connection evidence is project data and leaves all geometry intact',saved18[CU18.KEY]['records'] and cs18.groups==beforegroups18)
ch18.undo();check07('connection save Undo restores exact project data',cs18.plugin_data==beforedata18 and cs18.groups==beforegroups18)
ch18.redo();check07('connection save Redo restores exact immutable evidence',cs18.plugin_data==saved18)
cd18.report=None;cd18.load_saved();check07('saved pair report loads with current geometry and input',CU18.current(cs18,cd18.report) and cd18.required.value()==300)
sd18.connections.item(0,5).setText('1.2');check07('Proposed uses stored Host values instead of unsaved parent dialog edits',CU18.generate(cs18,st18.uid,sp18.uid,'Proposed',role18,.3)[0]['source_digest']==cd18.report['source_digest']);sd18.connections.item(0,5).setText('.8')
cs18.selection={sp18};cd18.read_support();check07('reading selected support retains independently bound Stair',cd18.uid==st18.uid and cd18.targets.currentData()==sp18.uid)
cs18.selection={st18};sd18.read_host();sd18.review();sd18.build_rebar();cd18.read_stair();cd18.roles.setCurrentText(role18);cd18.inspect()
check07('actual cage mode validates generated reinforcement against Host',cd18.mode.currentText()=='Actual' and all(r['state']=='geometry_length_met' for r in cd18.report['rows']))
check07('Actual and Proposed geometric lengths agree for saved explicit connectors',all(abs(r['longest_inside_m']-.4)<1e-6 for r in cd18.report['rows']))
bar18=next(g for g in cs18.groups if g.ext.get('thai_bim',{}).get('host_uid')==st18.uid);barpose18=copy.deepcopy(bar18.xform);bar18.xform=QMatrix4x4(*W07.P.matrix((.1,0,0),0))
rejects07('moved actual cage rejects connection inspection',lambda:CU18.generate(cs18,st18.uid,sp18.uid,'Actual',role18,.3));bar18.xform=barpose18
check07('restoring actual bar pose restores source freshness',CU18.current(cs18,cd18.report))
# Explicit generic IFC support with disconnected closed shells: real gap, not a bounding box.
left18=tb07.make_group(tb07.E.box_spec('Beam',-.4,.1,-.2,.2,.8,.2));right18=tb07.make_group(tb07.E.box_spec('Beam',.2,.1,-.2,.2,.8,.2));gap18=Group(Mesh(),name='Wall with geometric gap');gap18.children=[left18,right18];tag_group(gap18,'IfcWall',gap18.name);cs18.groups.append(gap18)
gapreport18,_=CU18.generate(cs18,st18.uid,gap18.uid,'Actual',role18,.3)
check07('native nested support gap is clipped rather than AABB-filled',all(abs(r['inside_length_m']-.4)<1e-6 and abs(r['longest_inside_m']-.2)<1e-6 and r['state']=='geometry_length_short' for r in gapreport18['rows']))
for cls18 in ('IfcSlab','IfcWall','IfcColumn'):
 generic18=copy_group(sp18);generic18.ext={};tag_group(generic18,cls18,'Generic '+cls18);cs18.groups.append(generic18)
 rr18,_=CU18.generate(cs18,st18.uid,generic18.uid,'Actual',role18,.3)
 check07(cls18+' closed native support gives actual geometric interval',all(abs(r['longest_inside_m']-.4)<1e-6 for r in rr18['rows']));cs18.groups.remove(generic18)
open18=tb07.make_group(tb07.E.box_spec('Beam',-.2,.1,-.2,.4,.8,.2));open18.ext={};open18.mesh.remove_face(next(iter(open18.mesh.faces)));tag_group(open18,'IfcBeam','Open support');cs18.groups.append(open18)
rejects07('open native support is rejected instead of substituted by a box',lambda:CU18.support(cs18,open18.uid));cs18.groups.remove(open18)
# Current report invalidation and command guards.
cd18.inspect();fresh18=copy.deepcopy(cd18.report);oldpose18=copy.deepcopy(sp18.xform);sp18.xform=QMatrix4x4(*W07.P.matrix((2,0,0),0))
check07('moving support invalidates saved source digest',not CU18.current(cs18,fresh18));rejects07('moved support blocks stale dialog evidence save',cd18.reviewed);rejects07('stale snapshot command independently rejects changed geometry',lambda:CU18.SaveInspection(cs18,fresh18).do(cs18))
cd18.display();check07('stale report is visibly marked and preview invalidated','ข้อมูลเก่า' in cd18.info.text() and bool(cd18.visual.error));sp18.xform=oldpose18;cd18.inspect()
cs18.groups.remove(sp18);rejects07('deleted support blocks report reuse',cd18.reviewed);cs18.groups.append(sp18);cd18.refresh_targets();cd18.targets.setCurrentIndex(cd18.targets.findData(sp18.uid));cd18.inspect()
cv18.begin_group_edit(st18);rejects07('native group editing blocks connection workflow',cd18.check);cv18.end_group_edit();cd18.inspect()
cs18.selection={st18};copied18=copy_group(st18);cs18.groups.append(copied18);rejects07('native copied business IDs require reconciliation before inspection',cd18.inspect);cs18.groups.remove(copied18)
otherScene18=Scene();cv18.scene=otherScene18;rejects07('switching document blocks bound connection dialog',cd18.check);cv18.scene=cs18
cs18.selection={st18};cd18.read_stair();cd18.roles.setCurrentText(role18);cd18.targets.setCurrentIndex(cd18.targets.findData(sp18.uid));cd18.required.setValue(300);cd18.inspect();cd18.save()
M07.compact_save(cs18,out07/'stair-connections-ไทย.igz');reopen18=Scene();load_into(reopen18,out07/'stair-connections-ไทย.igz');stored18=next(iter(reopen18.plugin_data[CU18.KEY]['records'].values()))
check07('native IGZ roundtrip preserves report snapshots exactly',reopen18.plugin_data[CU18.KEY]==cs18.plugin_data[CU18.KEY])
check07('IGZ reopened connection report can validate actual saved support geometry',CU18.current(reopen18,stored18))
export18=cd18.reviewed();(out07/'stair-connections-ไทย.json').write_text(json.dumps(export18,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf8');check07('Unicode JSON report roundtrip retains all geometric rows',json.loads((out07/'stair-connections-ไทย.json').read_text(encoding='utf8'))==export18)
original_token18=W07.host_token;calls18=[]
def counting_token18(g):
 calls18.append(g.uid);return original_token18(g)
W07.host_token=counting_token18
try:
 CU18.bars(cs18,st18,'Actual')
 check07('actual cage inspection fingerprints Host once per fresh bar collection',calls18==[st18.uid])
finally:W07.host_token=original_token18
# Native export invokes the real implementation; only the file chooser is substituted.
chooser18=QFileDialog.getSaveFileName
try:
 QFileDialog.getSaveFileName=lambda *a,**k:(str(out07/'stair-connections-export-ไทย.json'),'JSON (*.json)')
 cd18.export()
finally:QFileDialog.getSaveFileName=chooser18
check07('native JSON export implementation writes exact reviewed Unicode report',json.loads((out07/'stair-connections-export-ไทย.json').read_text(encoding='utf8'))==export18)
rejects07('unknown reinforcement source mode rejected explicitly',lambda:CU18.bars(cs18,st18,'unexpected'))
bv18=next(iter(bar18.mesh.vertices));bp18=QVector3D(bv18.position);bv18.position+=QVector3D(.01,0,0)
rejects07('actual cage geometry edits block connection inspection',lambda:CU18.generate(cs18,st18.uid,sp18.uid,'Actual',role18,.3));bv18.position=bp18
# Rigid placement of both concrete objects, then explicitly rebuild the moved stair cage.
stpose18=copy.deepcopy(st18.xform);supportpose18=copy.deepcopy(sp18.xform)
st18.xform=QMatrix4x4(*W07.P.matrix((2,3,.7),35));sp18.xform=QMatrix4x4(*W07.P.matrix((2,3,.7),35))
cs18.selection={st18};sd18.read_host();sd18.review();sd18.build_rebar();cd18.read_stair();cd18.roles.setCurrentText(role18);cd18.inspect()
check07('rotated translated Stair and support preserve 400 mm actual intervals',all(abs(r['longest_inside_m']-.4)<2e-6 and r['state']=='geometry_length_met' for r in cd18.report['rows']))
check07('old stationary report is stale after rigid relocation and cage rebuild',not CU18.current(cs18,export18))
st18.xform=stpose18;sp18.xform=supportpose18;cs18.selection={st18};sd18.read_host();sd18.review();sd18.build_rebar()
# A support selection may open the tool; reading Stair remains an explicit action.
cs18.selection={sp18};cd18=CU18.open_dialog(cp18)
check07('opening connection dialog with support selected does not fail or bind wrong Host',cd18.isVisible() and cd18.uid is None)
cs18.selection={st18};cd18.read_stair();cd18.roles.setCurrentText(role18);cd18.targets.setCurrentIndex(cd18.targets.findData(sp18.uid));cd18.required.setValue(300);cd18.inspect()
check07('explicit Stair read restores working actual inspection after support-first opening',all(r['state']=='geometry_length_met' for r in cd18.report['rows']))
ca18.window.deleteLater();settle07();__import__('core.units',fromlist=['bind_scene']).bind_scene(scene)
check07('stair connection tests preserve actual user document geometry',actual18==(list(scene.groups),scene.version,set(scene.selection)))
print('PASS: '+str(len(checks07))+' native checks including actual support clipping and saved evidence')
