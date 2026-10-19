"""Full saved project validation in an isolated native viewport; no fabrication inference."""
import json,time,hashlib,statistics,copy
from pathlib import Path
from core.scene import Scene
from core.history import History
from formats.igz import load_into,save_scene
from ingetrazo_plugin_thai_bim import audit as audit071,management as mg071
source071=Path(FAMILY10_TEST_FILE)  # provide your local Family10 R03 file; not bundled
projectout071=root07/'output/family10-v071';projectout071.mkdir(exist_ok=True)
actual071=(list(scene.groups),scene.version,set(scene.selection));sourcehash071=hashlib.sha256(source071.read_bytes()).hexdigest()
start071=time.perf_counter();full071=Scene();load_into(full071,source071);loadtime071=time.perf_counter()-start071
originaluids071=[g.uid for g in full071.groups];originaldata071=copy.deepcopy(full071.plugin_data)
start071=time.perf_counter();before071=audit071.project_report(full071);audittime071=time.perf_counter()-start071
assert before071['tagged']==3962,(before071['tagged'],before071['total_groups'])
check07('Family10 3962 source-tagged elements loaded',before071['tagged']==3962)
check07('Family10 17 footings retained',before071['legacy_classes']['IfcFooting']==17)
check07('Family10 identity and layer audit',not before071['issues'][:-1] and not any('Duplicate' in s for s in before071['issues']))
check07('Family10 original rebar explicitly excluded from detailed BBS',before071['bbs_bars']==0 and bool(before071['bbs_issues']) and before071['legacy_rebar_count']>3000)
appfull071=App07();appfull071.window.setWindowTitle('Family10 whole-model verification');vfull071=appfull071.viewport;hfull071=History(full071);vfull071.set_document(full071,hfull071)
originalmeshes071=[g.mesh for g in full071.groups];originalhidden071=[g.hidden for g in full071.groups];originallayers071=[g.layer for g in full071.groups]
cmd071=mg071.LayerChanges(full071,migrate=True,include_family10=True);hfull071.execute(cmd071)
assert not hfull071.last_error,hfull071.last_error
after071=audit071.project_report(full071)
check07('Family10 migration retains all group UIDs geometry hidden states',originaluids071==[g.uid for g in full071.groups] and originalmeshes071==[g.mesh for g in full071.groups] and originalhidden071==[g.hidden for g in full071.groups])
check07('Family10 source project metadata unchanged',originaldata071==full071.plugin_data)
check07('Family10 QTO identical after migration',after071['qto']==before071['qto'] and after071['qto_rows']==before071['qto_rows'])
check07('Family10 rebar host layers all assigned',all(g.layer!='TBIM S Rebar Unassigned' for g in full071.groups if (g.ext or {}).get('family10',{}).get('class')=='IfcReinforcingBar'))
hfull071.undo();check07('Family10 layer Undo restores every original tag',originallayers071==[g.layer for g in full071.groups]);hfull071.redo()
output071=projectout071/'family10-reviewed-v071.igz';start071=time.perf_counter();mg071.compact_save(full071,output071);savetime071=time.perf_counter()-start071
start071=time.perf_counter();reopened071=Scene();load_into(reopened071,output071);reopentime071=time.perf_counter()-start071
reopenreport071=audit071.project_report(reopened071)
check07('whole Family10 compact IGZ reopens all identities',originaluids071==[g.uid for g in reopened071.groups])
check07('whole Family10 reopened QTO unchanged',reopenreport071['qto']==before071['qto'])
check07('whole Family10 reopened layer visibility retained',[(l.name,l.visible,l.locked) for l in full071.layers]==[(l.name,l.visible,l.locked) for l in reopened071.layers])
del reopened071
vfull071.camera.target=QVector3D(4.5,6,4);vfull071.camera.distance=27;vfull071.camera.yaw=-2.15;vfull071.camera.pitch=.42
appfull071.window.show();vfull071.notify_scene_changed();settle07()
barsfull071=[g for g in full071.groups if (g.ext or {}).get('family10',{}).get('class')=='IfcReinforcingBar']
bench071={}
for visible071 in (False,True):
    for g in barsfull071:g.hidden=not visible071
    for l in full071.layers:
        if l.name.startswith('TBIM S Rebar'):l.visible=visible071
    full071.version+=1;vfull071.notify_scene_changed();vfull071.update();settle07()
    # Warm-up caches; timings include readback and event dispatch, not raw interactive FPS.
    vfull071.grabFramebuffer();times071=[]
    for i071 in range(8):
        t071=time.perf_counter();vfull071.camera.yaw+=.035;full071.bump_view();vfull071.update();QApplication.processEvents();frame071=vfull071.grabFramebuffer();times071.append(time.perf_counter()-t071)
    label071='rebar-visible' if visible071 else 'rebar-hidden';frame071.save(str(projectout071/(label071+'.png')))
    bench071[label071]=dict(samples=8,mean_frame_readback_ms=statistics.mean(times071)*1000,median_frame_readback_ms=statistics.median(times071)*1000,max_frame_readback_ms=max(times071)*1000)
for g,hidden in zip(full071.groups,originalhidden071):g.hidden=hidden
vfull071.hide();appfull071.window.hide();appfull071.window.deleteLater();settle07()
from core import units as units071
units071.bind_scene(scene)
check07('Family10 source file untouched',sourcehash071==hashlib.sha256(source071.read_bytes()).hexdigest())
check07('actual active document untouched by full-project tests',actual071==(list(scene.groups),scene.version,set(scene.selection)))
metrics071=dict(source_file_sha256=sourcehash071,source_bytes=source071.stat().st_size,reviewed_bytes=output071.stat().st_size,
    load_seconds=loadtime071,audit_seconds=audittime071,save_seconds=savetime071,reopen_seconds=reopentime071,
    total_groups=before071['total_groups'],tagged=before071['tagged'],legacy_rebar=before071['legacy_rebar_count'],mesh_faces=before071['mesh_faces'],mesh_edges=before071['mesh_edges'],
    navigation=bench071,measurement='8 synchronous rendered framebuffer readbacks after warm-up, includes event dispatch/GPU readback; not raw navigation FPS',
    limitation='Original bars are legacy nominal meshes, not toolkit cages; no Full/Lightweight conversion or fabrication BBS inferred')
(projectout071/'performance.json').write_text(json.dumps(metrics071,indent=2),encoding='utf-8')
(projectout071/'project-audit.json').write_text(json.dumps(after071,ensure_ascii=False,indent=2),encoding='utf-8')
tb07.E.write_xlsx(projectout071/'project-audit.xlsx',tables=audit071.report_tables(after071))
print(json.dumps(metrics071));print('Full project checks complete: '+str(len(checks07)))
