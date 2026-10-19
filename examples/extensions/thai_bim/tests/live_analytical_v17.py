"""Run after regression suite. Analytical graph, source guards and native overlay."""
from ingetrazo_plugin_thai_bim import analytical as AN12,analytical_ui as AU12
from core.group import copy_group
actual12=(list(scene.groups),scene.version,set(scene.selection))
checks07=checks07[:223];aa12=App07();ap12=tb07.setup(aa12);ap12.guard=lambda fn:fn();as12=aa12.scene;av12=aa12.viewport
aa12.window.show();settle07();geometry12=list(as12.groups)
for sp12 in (tb07.E.box_spec('Column',-.1,-.1,0,.2,.2,3),tb07.E.box_spec('Beam',0,-.1,1.3,4,.2,.4)):
    ap12.execute(tb07.ExchangeGroups(as12,additions=[tb07.make_group(sp12)]))
original12=list(as12.groups);native12={g.uid:(g.mesh,W07.pose(g),copy.deepcopy(g.ext)) for g in original12}
ad12=AU12.open_dialog(ap12);ad12.generate();m12=ad12.model
check07('analytical conversion splits column at internal beam endpoint',len(m12['members'])==2 and len(m12['nodes'])==4 and len(m12['elements'])==3 and len(m12['components'])==1)
check07('analytical conversion preserves physical members and quantities',as12.groups==original12 and all(g.mesh is native12[g.uid][0] and g.ext==native12[g.uid][2] for g in original12))
check07('analytical graph explicitly not solver ready',not m12['solver_ready'] and m12['materials']==[] and m12['supports']==[] and m12['load_cases']==[])
ad12.save();check07('analytical snapshot stores centrally with source bindings',as12.plugin_data[AU12.KEY]['source_digest']==AN12.digest(AU12.sources(as12)) and len(as12.plugin_data[AU12.KEY]['sources'])==2)
av12.history.undo();check07('analytical snapshot Undo removes only metadata',AU12.KEY not in as12.plugin_data and as12.groups==original12)
av12.history.redo();check07('analytical snapshot Redo restores exact data',as12.plugin_data[AU12.KEY]==m12)
ad12.generate();check07('analytical regeneration retains model and node IDs with new revision',ad12.model['id']==m12['id'] and ad12.model['revision']==2 and ad12.model['nodes']==m12['nodes'])
ad12.tolerance.setValue(20);rejects07('tolerance edit blocks saving unreviewed graph',ad12.save);ad12.generate();ad12.save()
AU12.write(out07/'analytical-model-ไทย.json',ad12.reviewed());check07('analytical neutral JSON Unicode roundtrip',AN12.validate(json.loads((out07/'analytical-model-ไทย.json').read_text(encoding='utf-8')))==ad12.model)
M07.compact_save(as12,out07/'analytical-frame.igz');re12=Scene();load_into(re12,out07/'analytical-frame.igz')
check07('IGZ reopen retains analytical snapshot and source references',re12.plugin_data[AU12.KEY]==ad12.model and AU12.current(re12,re12.plugin_data[AU12.KEY]))
host12=original12[-1];oldpose12=host12.xform;host12.xform=W07.matrix(W07.P.matrix((0,.005,0)));as12.version+=1
check07('rigid BIM move marks analytical snapshot stale',not AU12.current(as12,ad12.model))
rejects07('stale BIM move blocks snapshot save',ad12.save);ad12.generate()
check07('near beam column gap reported without joining nodes',any(i['code']=='near_joint' for i in ad12.model['issues']) and len(ad12.model['components'])==2)
host12.xform=oldpose12;as12.version+=1;ad12.generate()
pending12=AU12.SnapshotChange(as12,ad12.model);as12.plugin_data['unrelated']=dict(value=1)
rejects07('stale analytical command cannot overwrite intervening project edits',lambda:pending12.do(as12));del as12.plugin_data['unrelated']
copy12=copy_group(host12);as12.groups.append(copy12)
rejects07('native copied duplicate BIM IDs block analytical conversion',ad12.generate);as12.groups.remove(copy12)
ad12.generate();aa12.project_data={};ad12.show();av12.camera.target=QVector3D(1.5,0,1.5);av12.camera.pitch=.3;av12.camera.yaw=-1.2;av12.camera.distance=7;av12.update();settle07()
overlays12=len(av12._ext_overlays);av12.repaint();settle07()
check07('native analytical overlay callback survives actual viewport drawing',len(av12._ext_overlays)==overlays12)
ad12.grab().save(str(out07/'analytical-dialog.png'));image12=av12.grabFramebuffer();image12.save(str(out07/'analytical-preview.png'))
from PySide6.QtGui import QImage
rgba12=image12.convertToFormat(QImage.Format_RGBA8888);pixels12=rgba12.constBits().tobytes()
check07('native analytical viewport contains projected gold axes and nodes',pixels12.count(bytes([241,182,66,255]))>30)
ad12.table.setCurrentCell(0,0);av12.repaint();settle07();focus12=av12.grabFramebuffer().convertToFormat(QImage.Format_RGBA8888)
check07('diagnostic row identifies actual node coordinates',ad12.focus.get('node_id') and ' m' in ad12.table.item(0,1).text())
check07('selected diagnostic node highlights in native viewport',focus12.constBits().tobytes().count(bytes([232,81,81,255]))>10)
ad12.visible.setChecked(False);av12.repaint();imageoff12=av12.grabFramebuffer().convertToFormat(QImage.Format_RGBA8888)
check07('analytical preview toggle removes gold overlay',imageoff12.constBits().tobytes().count(bytes([241,182,66,255]))<pixels12.count(bytes([241,182,66,255])))
AU12.install(ap12);check07('analytical installation idempotent with nonempty toolbar icon',len(ap12.toolbar.actions())==21 and not ap12.toolbar.actions()[-1].icon().isNull())
ad12.bound_scene=Scene();rejects07('analytical modeless dialog blocks document switch',ad12.generate);ad12.bound_scene=as12
aa12.window.deleteLater();settle07();units07.bind_scene(scene)
check07('analytical tests preserve actual user document geometry',actual12==(list(scene.groups),scene.version,set(scene.selection)))
print('PASS: '+str(len(checks07))+' native checks including analytical graph, Undo, IGZ and visible overlay')
