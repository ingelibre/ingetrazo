"""Run after the v16 native regressions: stair library + exact instance updates."""
from ingetrazo_plugin_thai_bim import stair_catalogue as SC16,stair_library_ui as SL16,stairs_ui as SU16
import importlib
SL16=importlib.reload(SL16)
from core.group import copy_group
from ingetrazo_plugin_thai_bim import copy_identity as CI16
actual16=(list(scene.groups),scene.version,set(scene.selection));checks07=checks07[:477]
la16=App07();lp16=tb07.setup(la16);lp16.guard=lambda fn:fn();ls16=la16.scene;lh16=la16.viewport.history;la16.window.show();settle07()
ld16=SU16.open_dialog(lp16,False);lib16=ld16.library;start16=list(ls16.groups)
check07('advanced stair library seeds six layouts and retains 21 icons',len(lib16.rows)==6 and len(lp16.toolbar.actions())==21)
pose16=W07.P.matrix((2,3,.4),25);ld16.pf['x'].setValue(2);ld16.pf['y'].setValue(3);ld16.pf['z'].setValue(.4);ld16.pf['yaw'].setValue(25)
for index16,row16 in enumerate(lib16.rows,1):
    lib16.load_index(index16);check07(row16['params']['layout']+' library preview loads geometry and complete rebar without placing',ld16.geometry()==row16['params'] and ld16.rebar()==row16['rebar'] and ls16.groups==start16 and W07.P.same_pose(ld16.pose(),pose16))
lib16.load_index(2);lib16.duplicate();lib16.code.setText('ST-TH');lib16.name.setText('บันได L ครอบครัว');ld16.gf['width'].setValue(1.1)
steel16=C07.selection(C07.TIS_DB,'DB12','SD40');combo16,records16=ld16.steels['main'];combo16.setCurrentIndex(records16.index(steel16))
ld16.add_connection();ld16.connections.item(0,0).setText('เหล็กต่อชานพัก');lib16.save();row16=copy.deepcopy(lib16.source);data16=SL16.library(ls16)
check07('stair type saves Thai name DB catalogue and connector table',row16['revision']==1 and row16['name']=='บันได L ครอบครัว' and row16['rebar']['main_steel']==steel16 and len(row16['rebar']['extra_connections'])==1)
check07('stair library stays separate from legacy member library',len(__import__('ingetrazo_plugin_thai_bim.type_ui',fromlist=['library']).library(ls16)['types'])==5 and len(data16['types'])==7)
lh16.undo();check07('stair type save Undo restores six default types',len(SL16.library(ls16)['types'])==6)
lh16.redo();lib16.refresh();check07('stair type save Redo restores exact snapshot',SL16.library(ls16)==data16)
ld16.create();first16=ld16.host();first_ext16=copy.deepcopy(first16.ext)
check07('typed concrete stores frozen type snapshot and no override',first16.ext['thai_bim']['stair_type']==row16 and first16.ext['thai_bim']['stair_type_overrides']=={} and first16.name.startswith('TBIM Stair ST-TH'))
check07('read new typed Host retains preset steel before cage exists',ld16.rebar()==row16['rebar'] and not any(g.ext['thai_bim'].get('host_uid')==first16.uid for g in ls16.groups))
rejects07('typed stair still needs explicit Host review before creating bars',ld16.build_rebar)
ld16.review();ld16.build_rebar();firstbars16=[g for g in ls16.groups if g.ext['thai_bim'].get('host_uid')==first16.uid]
check07('typed stair reviewed cage uses stored DB and connection patterns',firstbars16 and any('เหล็กต่อชานพัก' in g.ext['thai_bim']['bbs']['stair_role'] for g in firstbars16) and not tb07.bbs_records(ls16)[1])
ld16.pf['x'].setValue(12);ld16.create();second16=ld16.host();secondid16=second16.ext['thai_bim']['id'];secondpose16=W07.pose(second16)
check07('same type creates independent Host identities and positions',second16.uid!=first16.uid and secondid16!=first16.ext['thai_bim']['id'] and second16.ext['thai_bim']['stair_type']==row16 and W07.P.same_pose(secondpose16,W07.P.matrix((12,3,.4),25)))
ld16.gf['width'].setValue(1.2);lib16.name.setText('บันได L รุ่นแก้ไข');lib16.save();revised16=copy.deepcopy(lib16.source)
check07('editing saved type does not propagate to either placed Host',revised16['revision']==2 and first16.ext==first_ext16 and second16.ext['thai_bim']['stair_params']['width']==1.1)
before16=list(ls16.groups);ld16.update();secondnew16=ld16.host()
check07('explicit typed update preserves native ID business ID layer pose and sibling',secondnew16.uid==second16.uid and secondnew16.ext['thai_bim']['id']==secondid16 and secondnew16.layer==second16.layer and W07.pose(secondnew16)==secondpose16 and first16 in ls16.groups and first16.ext==first_ext16)
check07('explicit update records revision two and current geometry',secondnew16.ext['thai_bim']['stair_type']==revised16 and secondnew16.ext['thai_bim']['stair_params']['width']==1.2)
lh16.undo();check07('typed update Undo restores exact old concrete and all cage objects',ls16.groups==before16)
lh16.redo();ls16.selection={secondnew16};ld16.read_host();ld16.gf['width'].setValue(1.15);ld16.update();secondnew16=ld16.host()
check07('instance dimension override does not change saved type or sibling',secondnew16.ext['thai_bim']['stair_type_overrides']['params']['width']==1.15 and SL16.library(ls16)['types'][-1]['params']['width']==1.2 and first16.ext==first_ext16)
ld16.review();ld16.build_rebar();ls16.selection={secondnew16};ld16.read_host();ld16.rf['spacing'].setValue(180);ld16.update();secondnew16=ld16.host()
check07('concrete update retains edited per-instance rebar preview instead of reverting old cage',ld16.rebar()['spacing']==.18 and secondnew16.ext['thai_bim']['stair_type_overrides']['rebar']['spacing']==.18)
ld16.review();ld16.build_rebar();check07('instance cage changes preserve sibling cage objects',all(g in ls16.groups for g in firstbars16) and not tb07.bbs_records(ls16)[1])
# Concurrent modeless edits must not overwrite current saved revision.
otherdlg16=SU16.StairsDialog(lp16);otherlib16=otherdlg16.library;otherlib16.load_index(next(i+1 for i,r in enumerate(otherlib16.rows) if r['id']==revised16['id']))
lib16.refresh();lib16.load_index(next(i+1 for i,r in enumerate(lib16.rows) if r['id']==revised16['id']));lib16.name.setText('รุ่นสาม');lib16.save()
rejects07('stale concurrent stair type save is rejected',otherlib16.save);rejects07('stale concurrent stair type delete is rejected',otherlib16.remove)
rejects07('stale dropdown snapshot cannot load changed row',lambda:otherlib16.load_index(next(i+1 for i,r in enumerate(otherlib16.rows) if r['id']==revised16['id'])))
pending16=SL16.LibraryChange(ls16,SL16.library(ls16));ls16.plugin_data['unrelated']={'value':1};rejects07('stale project library command preserves intervening plugin data',lambda:pending16.do(ls16));ls16.plugin_data.pop('unrelated')
lib16.remove();check07('deleting type keeps existing geometry and snapshots',all(g in ls16.groups for g in firstbars16) and first16.ext['thai_bim']['stair_type']==row16 and secondnew16 in ls16.groups and len(SL16.library(ls16)['types'])==6)
lh16.undo();check07('type removal Undo restores exact revision three row',SL16.library(ls16)['types'][-1]['revision']==3)
# Files, empty libraries, shared path routing and invalid import.
SC16.write(out07/'stair-types-ไทย.json',SL16.library(ls16));check07('native stair JSON preserves Unicode full geometry and rebar',SC16.read(out07/'stair-types-ไทย.json')==SL16.library(ls16))
empty16=out07/'stair-types-empty.json';SC16.write(empty16,dict(schema=1,types=[]));lib16.import_path(empty16)
check07('empty stair library remains empty and import changes no geometry',SL16.library(ls16)['types']==[] and first16 in ls16.groups and secondnew16 in ls16.groups)
lh16.undo();lib16.refresh();check07('library import Undo restores project library',len(lib16.rows)==7)
bad16=out07/'invalid-stair-library.json';bad16.write_text('{"schema":1,"types":[{}]}',encoding='utf-8');beforedata16=copy.deepcopy(ls16.plugin_data)
try:lib16.import_path(bad16)
except (ValueError,KeyError,TypeError):check07('invalid import leaves all project data unchanged',ls16.plugin_data==beforedata16)
else:raise AssertionError('invalid stair import accepted')
sharedfn16=SL16.shared_path;SL16.shared_path=lambda:out07/'shared-stair-types-ไทย.json'
try:
    lib16.save_shared();lib16.load_shared();check07('local shared library roundtrip uses same validated schema',SL16.library(ls16)==SC16.read(SL16.shared_path()))
finally:SL16.shared_path=sharedfn16
oldscene16=la16.viewport.scene;la16.viewport.scene=Scene();rejects07('document switch blocks stale library save',lib16.save);rejects07('document switch blocks preset placement',ld16.create);la16.viewport.scene=oldscene16
# Duplicates and raw source edits remain guarded.
lib16.refresh();lib16.load_index(2);lib16.code.setText('changed-unsaved');rejects07('unsaved type name cannot be attached to concrete',ld16.create);lib16.load_index(2)
ld16.gf['waist'].setValue(.08);beforegroups16=list(ls16.groups);rejects07('invalid typed reinforcement fit blocks creation before geometry changes',ld16.create);check07('failed typed creation leaves exact groups unchanged',ls16.groups==beforegroups16)
ls16.selection={first16};ld16.read_host();clone16=copy_group(first16);ls16.groups.append(clone16);lp16.execute(CI16.RepairCopies(ls16));ls16.selection={clone16};ld16.read_host();ld16.update();clonenew16=ld16.host();ld16.review();ld16.build_rebar()
check07('copied typed stairs retain frozen type but have independent cage binding',clonenew16.ext['thai_bim']['stair_type']==row16 and clonenew16.ext['thai_bim']['id']!=first16.ext['thai_bim']['id'] and all(g in ls16.groups for g in firstbars16) and not tb07.bbs_records(ls16)[1])
M07.compact_save(ls16,out07/'stair-library-instances-ไทย.igz');reopened16=Scene();load_into(reopened16,out07/'stair-library-instances-ไทย.igz')
check07('IGZ reopen retains project stair library and exact type snapshots',SL16.library(reopened16)==SL16.library(ls16) and json.dumps([g.ext for g in reopened16.groups],sort_keys=True)==json.dumps([g.ext for g in ls16.groups],sort_keys=True))
check07('IGZ reopened typed instance BBS and QTO retain valid bindings',not tb07.bbs_records(reopened16)[1] and not tb07.quantity_rows(reopened16)[1])
check07('read old Host snapshot shows its actual revision instead of latest library revision',lib16.source['revision']==1 and 'r1 (snapshot)' in lib16.pick.currentText())
rejects07('snapshot display row cannot be loaded as a current saved library type',lambda:lib16.load_index(len(lib16.rows)+1))
ld16.show();ld16.view.setCurrentIndex(1);ld16.preview();settle07();ld16.grab().save(str(out07/'stair-type-library.png'))
check07('native library screenshot has illustrated preview and visible action footer',not ld16.visual.error and ld16.width()>900 and (out07/'stair-type-library.png').stat().st_size>10000)
otherdlg16.deleteLater();la16.window.deleteLater();settle07();__import__('core.units',fromlist=['bind_scene']).bind_scene(scene)
check07('stair library tests preserve actual user document geometry',actual16==(list(scene.groups),scene.version,set(scene.selection)))
print('PASS: '+str(len(checks07))+' native checks including RC stair library and selected instance updates')
