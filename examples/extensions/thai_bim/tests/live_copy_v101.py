"""Run in a prepared App07 harness; copy_group is the native Copy operation."""
from core.group import copy_group
from ingetrazo_plugin_thai_bim import copy_identity as CI101,multi_place as MP101
from ingetrazo_plugin_thai_bim import catalogue as CT101,workflow as WW101
import copy
checks07=checks07[:145]
root101=(list(scene.groups),[(g,g.mesh,g.xform) for g in scene.groups])
ca101=App07();cp101=tb07.setup(ca101);cp101.guard=lambda fn:fn();cs101=ca101.scene;ch101=ca101.viewport.history
cp101.kind.setCurrentText('Column')
for key,val in dict(width=.25,depth=.25,height=3).items():cp101.mfields[key].setValue(val)
cp101.create_member();original101=cs101.groups[-1]
dup101=copy_group(original101,QVector3D(3,0,0));cs101.groups.append(dup101)
check07('native Copy reproduces duplicate business IDs',bool(tb07.identity_issues(cs101)) and dup101.mesh is original101.mesh)
before101=list(cs101.groups);ext101=[copy.deepcopy(g.ext) for g in cs101.groups];pose101=[WW101.pose(g) for g in cs101.groups]
cmd101,new101=MP101.create_command(cs101,'beam',[(0,0,0),(3,0,0)],3,dict(depth=.2,height=.4))
cp101.execute(cmd101)
check07('copy then typed beam automatically repairs identity and retains all members',not tb07.identity_issues(cs101) and all(g in cs101.groups for g in before101) and new101 in cs101.groups)
check07('original ID and native instance identities remain unchanged',original101.ext['thai_bim']['id']==ext101[0]['thai_bim']['id'] and original101.uid!=dup101.uid and original101.ext['thai_bim']['native_uid']==original101.uid)
check07('repair does not detach shared geometry or move copies',dup101.mesh is original101.mesh and [WW101.pose(g) for g in before101]==pose101)
ch101.undo();check07('one Undo restores exact copy metadata and removes only new beam',cs101.groups==before101 and [g.ext for g in cs101.groups]==ext101)
ch101.redo();check07('Redo reuses repaired IDs and the same new member',not tb07.identity_issues(cs101) and new101 in cs101.groups)
dup2101=copy_group(dup101,QVector3D(0,3,0));cs101.groups.append(dup2101);cp101.kind.setCurrentText('Footing');cp101.create_member()
check07('copy of a copy followed by normal member creation succeeds',not tb07.identity_issues(cs101) and cs101.groups[-1].ext['thai_bim']['kind']=='Footing')
cs101.selection={dup101};row101=CT101.defaults()['types'][1];row101['params']['width']=.4
from ingetrazo_plugin_thai_bim.type_ui import update_selected
command101,updated101=update_selected(cs101,row101);cp101.execute(command101)
check07('adopted copy selected edit leaves original shared definition intact',original101.ext['thai_bim']['params']['width']==.25 and updated101.ext['thai_bim']['params']['width']==.4 and original101.mesh is not updated101.mesh)
cs101.selection=set();hp101=original101.ext['thai_bim']['params'];rp101=dict(cover=40,diameter=12,tie_diameter=6,spacing=150,layers=1,representation='Centreline')
sp101,token101,_=WW101.review_specs(cs101,original101,rp101);command101,_=tb07.rebar_command(cs101,original101,sp101,rp101,expected=token101);cp101.execute(command101)
bar101=next(g for g in cs101.groups if (g.ext or {}).get('thai_bim',{}).get('host_uid')==original101.uid)
barcopy101=copy_group(bar101,QVector3D(3,0,0));cs101.groups.append(barcopy101)
cp101.execute(CI101.RepairCopies(cs101))
check07('copied rebar quarantined without joining original Host assembly',barcopy101.ext['thai_bim']['copy_review_required'] and barcopy101.ext['thai_bim']['host_uid']!=original101.uid and barcopy101.ext['thai_bim']['assembly']!=bar101.ext['thai_bim']['assembly'])
records101,issues101=tb07.bbs_records(cs101);q101,qissues101=tb07.quantity_rows(cs101)
check07('original BBS remains usable and copied bar is excluded',any(r['id']==bar101.uid for r in records101) and not any(r['id']==barcopy101.uid for r in records101))
check07('copied bar QTO quantity is unverified instead of falsely counted',next(r for r in q101 if r['id']==barcopy101.uid)['quantity'] is None)
ch101.undo();check07('explicit copy repair Undo restores original duplicate bar metadata',barcopy101.ext['thai_bim']['id']==bar101.ext['thai_bim']['id']);ch101.redo()
temporary101=copy_group(original101);cs101.groups.append(temporary101);prepared101=CI101.RepairCopies(cs101)
saved101=copy.deepcopy(temporary101.ext);temporary101.ext['thai_bim']['note']='intervening metadata edit'
rejects07('stale identity repair does not overwrite intervening metadata edits',lambda:prepared101.do(cs101))
temporary101.ext=saved101;cs101.groups.remove(temporary101)
cp101.execute(CI101.RepairCopies(cs101));check07('repeated copy repair is idempotent',not tb07.identity_issues(cs101))
M07.compact_save(cs101,out07/'native-copies-adopted.igz');reload101=Scene();load_into(reload101,out07/'native-copies-adopted.igz')
check07('native IGZ persists repaired identity and copied-bar quarantine',not tb07.identity_issues(reload101) and any((g.ext or {}).get('thai_bim',{}).get('copy_review_required') for g in reload101.groups))
from core import units;units.bind_scene(scene);ca101.window.deleteLater();settle07()
check07('copy tests preserve actual user document geometry',root101==(list(scene.groups),[(g,g.mesh,g.xform) for g in scene.groups]))
print('PASS: '+str(len(checks07))+' cumulative checks; native Copy → create → Undo/Redo verified')
