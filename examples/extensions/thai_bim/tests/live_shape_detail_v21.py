"""Native drag, cage staleness, opening drawings, guard and persistence checks."""
from ingetrazo_plugin_thai_bim import selected_edit as UI21
ss21.selection={newbeam21};focus21(newbeam21,(2,.5,0));tool21=SH21.start(sp21);before21=newbeam21;mouse21(screen21(tool21.world_handles[1]),QEvent.MouseButtonPress,Qt.LeftButton);mouse21(screen21((4.5,1.5,0)),buttons=Qt.LeftButton);settle21()
check21('Native press-drag previews without commit',tool21.preview is not None and before21 in ss21.groups)
tool21.last_hover=__import__('time').monotonic();mouse21(screen21((5,2,0)),buttons=Qt.LeftButton);latest21=tool21.current
mouse21(screen21((5,2,0)),QEvent.MouseButtonRelease);newbeam21=tool21.host();check21('Native release commits latest endpoint despite preview throttling',newbeam21 is not before21 and math.dist(W21.P._point(W21.pose(newbeam21),(newbeam21.ext['thai_bim']['params']['width'],0,0)),latest21)<1e-5)
ss21.selection=set();tool21.valid(app21.viewport);check21('Selection guard exits tool before further edits',app21.viewport.active_tool is not tool21)
ss21.selection={newbeam21};tool21=SH21.start(sp21);expected21=tool21.expected;newbeam21.ext['thai_bim']['member_type']['revision']+=1
spec,pose=SG21.change(newbeam21.ext['thai_bim'],W21.pose(newbeam21),('beam',1),(6,2,0));reject21('Stale type snapshot rejects shape commit',lambda:SH21.command(ss21,newbeam21,spec,pose,expected21));newbeam21.ext['thai_bim']['member_type']['revision']-=1;tool21.on_cancel(app21.viewport)
nativecopy21=copy.deepcopy(newbeam21);nativecopy21.uid='copied-fixture';ss21.groups.append(nativecopy21);reject21('Copied business ID blocks shape entry',lambda:SH21.start(sp21));ss21.groups.remove(nativecopy21)
tilt21=QMatrix4x4();tilt21.rotate(15,QVector3D(1,0,0));oldpose21=newbeam21.xform;newbeam21.xform=tilt21;reject21('Tilted selected beam rejected',lambda:SH21.start(sp21));newbeam21.xform=oldpose21
sd21=UI21.open_dialog(sp21);check21('Selected edit dialog exposes shape and opening buttons',any('แก้ปลายคาน' in b.text() for b in sd21.findChildren(QPushButton)) and any('เพิ่มช่องเปิด' in b.text() for b in sd21.findChildren(QPushButton)));sd21.grab().save(str(out21/'selected-edit-dialog.png'));sd21.close()
for mode in ('One-way','Two-way','Precast'):
 h=tb21.make_group(SG21.slab_spec(EN21.box_spec('Slab',0,0,3,4,3,.2)['params'],holes=[[(1,1),(2,1),(2,2),(1,2)]]));ss21.groups.append(h);ss21.selection={h}
 rd=SL21.SlabDialog(sp21);rd.read_host();rd.mode.setCurrentText(mode);rd.review();rd.build();rd.close()
 src=MD21.source(ss21,h.uid);bars=[g for g in ss21.groups if g.ext.get('thai_bim',{}).get('host_uid')==h.uid]
 check21(mode+' native cage avoids opening',bool(bars) and all(not SG21.inside(tuple(v[:2]),[(1,1),(2,1),(2,2),(1,2)]) for b in bars for v in b.ext['thai_bim']['bar_path']))
 dlg=MD21.open_dialog(sp21);dlg.fields['name'].setText('Opening '+mode);dlg.prepare();dlg.build();parts,meta=MD21.validate(ss21,h.uid)
 check21(mode+' native sheet source retains inner outline',len(src['faces'])>=12 and len(parts)>=5)
 MD21.export_pdf(sp21,h.uid,out21/(mode+'-opening-A3-50.pdf'));MD21.export_bbs(ss21,h.uid,out21/(mode+'-opening-BBS.xlsx'))
 check21(mode+' native PDF and BBS exported',(out21/(mode+'-opening-A3-50.pdf')).stat().st_size>10000)
 if mode=='One-way':
  oldbars=list(bars);result,pose=SG21.change(h.ext['thai_bim'],W21.pose(h),('vertex',0,0),(-.2,-.2,3.2));edited=swap21(h,result,pose)
  check21('Shape edit leaves existing cage untouched for explicit review',all(b in ss21.groups for b in oldbars))
  reject21('Stale cage blocks drawing regeneration',lambda:MD21.source(ss21,edited.uid))
  reject21('Changed Host blocks old Sheet export',lambda:MD21.validate(ss21,edited.uid))
  validbars,issues=tb21.bbs_records(ss21);check21('Stale cage excluded from BBS',not any(r['host_uid']==edited.uid for r in validbars))
  ss21.selection={edited};rd=SL21.SlabDialog(sp21);rd.read_host();rd.review();rd.build();rd.close();dlg.prepare();dlg.build();dlg.acknowledge();check21('Explicit cage and sheet rebuild succeeds after shape edit',bool(MD21.validate(ss21,edited.uid)))
 dlg.close()
save_scene(ss21,out21/'selected-shape-edits.igz');reload21=Scene();load_into(reload21,out21/'selected-shape-edits.igz');check21('IGZ retains opening loops and rebuilt cages',[(g.uid,tb21.mesh_fingerprint(g)) for g in reload21.groups]==[(g.uid,tb21.mesh_fingerprint(g)) for g in ss21.groups])
check21('Actual user model remains unchanged after detail tests',actual21==[(g.uid,g.name,tb21.mesh_fingerprint(g)) for g in scene.groups] and actual_selection21=={g.uid for g in scene.selection})
app21.window.close();print('PASS',len(checks21),'native v21 checks')
