"""Run after all regression checks; actual Qt instance editing in isolated scenes."""
from ingetrazo_plugin_thai_bim import selected_edit as SE13,selected_geometry as SG13,analytical_ui as AU13,analytical as AN13,catalogue as TC13,type_ui as TU13
import importlib
SE13=importlib.reload(SE13)
actual13=(list(scene.groups),scene.version,set(scene.selection));checks07=checks07[:246]
ea13=App07();ep13=tb07.setup(ea13);ep13.guard=lambda fn:fn();es13=ea13.scene;ev13=ea13.viewport;ea13.window.show();settle07()
library13=TU13.library(es13);edited13={};siblings13={}
for row13 in library13['types']:
    kind13=row13['kind'];params13=row13['params']
    sp13=B07.S.stair_spec(**params13) if kind13=='Stair' else W07.P.member_spec(kind13,**params13)
    host13=tb07.make_group(sp13,assembly='fixture-'+kind13);TU13.tag(host13,row13);host13.name='ทดสอบ '+kind13;host13.xform=W07.matrix(W07.P.matrix((2,3,0),30))
    sibling13=tb07.make_group(sp13);TU13.tag(sibling13,row13);ep13.execute(tb07.ExchangeGroups(es13,additions=[host13,sibling13]));siblings13[kind13]=sibling13
    before13=list(es13.groups);ext13=copy.deepcopy(host13.ext);sibling_ext13=copy.deepcopy(sibling13.ext);mesh13=sibling13.mesh;pose13=W07.pose(host13)
    es13.selection={host13};dialog13=SE13.open_dialog(ep13)
    check07(kind13+' instance editor reads actual selected dimensions',dialog13.params()=={k:(ext13['thai_bim'].get('params') or ext13['thai_bim'].get('stair_params'))[k] for k in SG13.editable(kind13)})
    values13=dialog13.params();values13['height']+=.1
    if kind13 in ('Footing','Column'):values13['width']+=.1;values13['depth']+=.1
    if kind13=='Beam':values13['depth']+=.1
    if kind13=='Stair':values13['risers']+=2
    for k,v in values13.items():dialog13.edit_fields[k].setValue(v)
    values13=dialog13.params()
    dialog13.preview();check07(kind13+' instance edit preview leaves geometry untouched',not dialog13.visual.error and es13.groups==before13 and host13.ext==ext13)
    if kind13=='Beam':
        button13=next(b for b in dialog13.findChildren(QPushButton) if b.text().startswith('บันทึกขนาดเฉพาะ'))
        NativeEvents07.mouseClick(button13,Qt.LeftButton,Qt.NoModifier,button13.rect().center());settle07()
    else:dialog13.apply()
    new13=next(g for g in es13.groups if g.uid==host13.uid);edited13[kind13]=new13;p13=new13.ext['thai_bim'].get('params') or new13.ext['thai_bim'].get('stair_params');oldp13=ext13['thai_bim'].get('params') or ext13['thai_bim'].get('stair_params')
    check07(kind13+' edit retains identity pose type snapshot and name',new13.ext['thai_bim']['id']==ext13['thai_bim']['id'] and W07.pose(new13)==pose13 and new13.ext['thai_bim']['member_type']==row13 and new13.name==host13.name and new13.layer==host13.layer and new13.ext['thai_bim']['assembly']==ext13['thai_bim']['assembly'])
    check07(kind13+' edit changes only selected instance and not library',sibling13 in es13.groups and sibling13.mesh is mesh13 and sibling13.ext==sibling_ext13 and TU13.library(es13)==library13)
    check07(kind13+' actual saved dimensions match editor input',all(abs(p13[k]-v)<1e-8 for k,v in values13.items()))
    if kind13 in ('Footing','Column'):
        check07(kind13+' edit keeps local centre and base datum',all(abs(p13[axis]+p13[dim]/2-oldp13[axis]-oldp13[dim]/2)<1e-8 for axis,dim in (('x','width'),('y','depth'))) and p13['z']==oldp13['z'])
    if kind13=='Beam':check07('beam edit preserves exact span and width centreline',p13['x']==oldp13['x'] and p13['width']==oldp13['width'] and abs(p13['y']+p13['depth']/2-oldp13['y']-oldp13['depth']/2)<1e-8 and p13['z']==oldp13['z'])
    if kind13=='Slab':check07('rectangle slab edit preserves boundary coordinates',all(p13[k]==oldp13[k] for k in ('x','y','z','width','depth')))
    if kind13=='Stair':check07('straight stair edit retains start location and direction',all(p13[k]==oldp13[k] for k in ('x','y','z')) and W07.pose(new13)==pose13)
    ev13.history.undo();check07(kind13+' edit Undo restores exact original group',es13.groups==before13 and host13 in es13.groups and host13.ext==ext13)
    ev13.history.redo();check07(kind13+' edit Redo restores exact new group',new13 in es13.groups and new13.ext['thai_bim']['instance_dimensions']==values13)
    dialog13.close();dialog13.deleteLater()

sp13,pm13=PG10.polygon([(5,5),(2,5),(2,2),(4,2),(4,4),(5,4)],3,dict(height=.15));poly13=tb07.make_group(sp13);poly13.xform=W07.matrix(pm13);ep13.execute(tb07.ExchangeGroups(es13,additions=[poly13]));es13.selection={poly13}
pd13=SE13.open_dialog(ep13);outline13=copy.deepcopy(poly13.ext['thai_bim']['params']['footprint']);pd13.edit_fields['height'].setValue(.3);pd13.apply();polynew13=next(g for g in es13.groups if g.uid==poly13.uid)
check07('polygon slab selected edit preserves concave outline and doubles quantity',polynew13.ext['thai_bim']['params']['footprint']==outline13 and abs(polynew13.ext['thai_bim']['quantity']-poly13.ext['thai_bim']['quantity']*2)<1e-8)
es13.selection={edited13['Column']};pd13.read_host();values13=pd13.params();expected13=pd13.expected;col13=edited13['Column']
es13.selection={siblings13['Column']};rejects07('selection change cannot edit previously read member',pd13.apply)
es13.selection={col13};oldpose13=col13.xform;col13.xform=W07.matrix(W07.P.matrix((5,0,0)));rejects07('host moved after read blocks stale selected edit',pd13.apply);col13.xform=oldpose13;pd13.read_host()
pd13.bound_scene=Scene();rejects07('document switch blocks selected edit',pd13.apply);pd13.bound_scene=es13;pd13.read_host()
from core.group import copy_group
from ingetrazo_plugin_thai_bim import copy_identity as CI13
copy13=copy_group(col13);es13.groups.append(copy13);rejects07('native copied IDs require repair before instance edit',pd13.read_host);es13.groups.remove(copy13)
# Existing bars must survive concrete edits, while their old review becomes stale.
es13.selection={col13};rb13=B07.RebarDialog(ep13);rb13.read_host();rb13.representation.setCurrentText('Centreline');rb13.review();rb13.build()
bars13=[g for g in es13.groups if g.ext['thai_bim'].get('host_uid')==col13.uid]
am13=AN13.build(AU13.sources(es13));ep13.execute(AU13.SnapshotChange(es13,am13))
pd13.read_host();pd13.edit_fields['width'].setValue(pd13.params()['width']+.05);pd13.apply();colnew13=next(g for g in es13.groups if g.uid==col13.uid)
check07('concrete instance edit retains all prior bars for review',all(g in es13.groups for g in bars13))
check07('instance edit marks existing reinforcement and analytical snapshot stale',any(r['uid']==colnew13.uid and r['state']=='Review' for r in W07.host_notices(es13)) and not AU13.current(es13,am13))
pd13.rebar();check07('instance editor opens actual selected host reinforcement preview',pd13.rebar_dialog.host_uid==colnew13.uid and not pd13.rebar_dialog.visual.error)
# A genuine native Copy shares mesh; editing its repaired instance creates a separate new mesh.
copy13=copy_group(colnew13);es13.groups.append(copy13);ep13.execute(CI13.RepairCopies(es13));es13.selection={copy13};pd13.read_host();shared13=colnew13.mesh
pd13.edit_fields['height'].setValue(pd13.params()['height']+.2);pd13.apply();copynew13=next(g for g in es13.groups if g.uid==copy13.uid)
check07('editing repaired native copy leaves shared original geometry intact',colnew13.mesh is shared13 and copynew13.mesh is not shared13 and abs(copynew13.ext['thai_bim']['params']['height']-colnew13.ext['thai_bim']['params']['height']-.2)<1e-8)
M07.compact_save(es13,out07/'selected-instance-edits.igz');reload13=Scene();load_into(reload13,out07/'selected-instance-edits.igz')
check07('IGZ reopen retains per-instance dimensions and original type snapshots',json.dumps([g.ext for g in reload13.groups],sort_keys=True)==json.dumps([g.ext for g in es13.groups],sort_keys=True))
pd13.show();settle07();pd13.grab().save(str(out07/'selected-instance-editor.png'))
SE13.install(ep13);check07('selected editor installation idempotent with 21 icons',len(ep13.toolbar.actions())==21)
ea13.window.deleteLater();settle07();units07.bind_scene(scene)
check07('selected edit tests preserve actual user document geometry',actual13==(list(scene.groups),scene.version,set(scene.selection)))
print('PASS: '+str(len(checks07))+' native checks including selected edits for all five kinds and polygon slabs')
