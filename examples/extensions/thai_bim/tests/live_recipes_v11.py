"""Run after native baseline, types, drawings and copy tests; private isolated scene."""
from ingetrazo_plugin_thai_bim import catalogue as TC11,type_ui as TU11,rebar_recipe as RR11,builders as BB11,placement as PP11
from PySide6.QtWidgets import QPushButton
actual11=(list(scene.groups),scene.version,set(scene.selection))
checks07=checks07[:161]
ta11=App07();tp11=tb07.setup(ta11);tp11.guard=lambda fn:fn();ts11=ta11.scene;tv11=ta11.viewport
ta11.window.show();settle07();td11=TU11.open_library(tp11)
initial11=list(ts11.groups);recipes11={};hosts11={}
for kind11 in TC11.KINDS:
    td11.refresh();td11.load_row(next(i for i,r in enumerate(td11.rows) if r['kind']==kind11));td11.edit_recipe();ed11=td11.recipe_dialog
    ed11.representation.setCurrentText('Centreline')
    if kind11=='Beam':ed11.fields['count_x'].setValue(2);ed11.fields['count_y'].setValue(2);ed11.fields['spacing'].setValue(200)
    ed11.preview();check07(kind11+' recipe editor has actual sample bar preview',not ed11.visual.error and bool(ed11.visual.specs) and bool(ed11.visual.host))
    ed11.accept_type_recipe();check07(kind11+' recipe editing leaves geometry and library unchanged',ts11.groups==initial11 and next(r for r in TU11.library(ts11)['types'] if r['kind']==kind11)['rebar'] is None)
    td11.save();row11=td11.saved();recipes11[kind11]=copy.deepcopy(row11)
    check07(kind11+' recipe saved with type revision and nominal catalogue',row11['revision']==2 and row11['rebar']['main_steel']['size']=='DB12' and row11['rebar']['tie_steel']['size']=='RB6')
    tv11.history.undo();check07(kind11+' recipe save Undo retains exact prior library',next(r for r in TU11.library(ts11)['types'] if r['kind']==kind11)['rebar'] is None)
    tv11.history.redo()
    sp11=BB11.S.stair_spec(**row11['params']) if kind11=='Stair' else PP11.member_spec(kind11,**row11['params'])
    host11=tb07.make_group(sp11);TU11.tag(host11,row11);tp11.execute(tb07.ExchangeGroups(ts11,additions=[host11]));hosts11[kind11]=host11
    # Earlier loop geometries are allowed; compare exact host list for review-only operations.
    initial11=list(ts11.groups);ts11.selection={host11};rb11=BB11.RebarDialog(tp11);rb11.read_host()
    check07(kind11+' host loads snapshot recipe without generating bars',rb11.params()==row11['rebar'] and ts11.groups==initial11 and rb11.reviewed_key is None)
    rejects07(kind11+' recipe load requires explicit Host review',rb11.build)
    rb11.review();rb11.build();bars11=[g for g in ts11.groups if g.ext.get('thai_bim',{}).get('host_uid')==host11.uid]
    check07(kind11+' created cage records exact recipe revision hash and BBS',bool(bars11) and all(g.ext['thai_bim']['rebar_recipe_source']['type_revision']==2 and not g.ext['thai_bim']['rebar_recipe_source']['overridden'] and g.ext['thai_bim']['bbs'] for g in bars11))
    tv11.history.undo();check07(kind11+' cage Undo preserves concrete and prior cages',ts11.groups==initial11)
    tv11.history.redo();initial11=list(ts11.groups)
    rb11.deleteLater()

row11=recipes11['Beam'];host11=hosts11['Beam'];ts11.selection={host11};rb11=BB11.RebarDialog(tp11);rb11.read_host()
check07('existing cage details take precedence over library defaults',rb11.params()['spacing']==200 and rb11.recipe_source['type_revision']==2)
rb11.fields['spacing'].setValue(180);rejects07('editing loaded recipe invalidates prior review',rb11.build);rb11.review();rb11.build()
check07('user overrides retain base recipe provenance',all(g.ext['thai_bim']['rebar_recipe_source']['overridden'] and g.ext['thai_bim']['rebar_params']['spacing']==180 for g in ts11.groups if g.ext['thai_bim'].get('host_uid')==host11.uid))
latest11=TC11.snapshot(row11);latest11['revision']+=1;latest11['rebar']['spacing']=250
tp11.execute(TU11.LibraryChange(ts11,TC11.upsert(TU11.library(ts11),latest11)))
rb11.load_host_recipe();check07('latest library revision does not silently replace placed snapshot',rb11.params()['spacing']==200 and rb11.recipe_source['type_revision']==2 and host11.ext['thai_bim']['member_type']['revision']==2)
rb11.review();cmd11,newhost11=TU11.update_selected(ts11,latest11);tp11.execute(cmd11)
rejects07('recipe-only selected type update invalidates old Host review',rb11.build)
ts11.selection={newhost11};rb11.read_host();check07('existing cage values remain until explicit recipe reload',rb11.params()['spacing']==180)
rb11.load_host_recipe();check07('explicit load retrieves selected host new recipe revision',rb11.params()['spacing']==250 and rb11.recipe_source['type_revision']==3)
rejects07('explicit new revision load needs review again',rb11.build);rb11.review();rb11.build()
check07('new revision cage built with explicit review',all(g.ext['thai_bim']['rebar_recipe_source']['type_revision']==3 for g in ts11.groups if g.ext['thai_bim'].get('host_uid')==newhost11.uid))
# Modeless type editor must not overwrite another type or edited form.
td11.refresh();td11.load_row(next(i for i,r in enumerate(td11.rows) if r['kind']=='Beam'));td11.edit_recipe();ed11=td11.recipe_dialog
td11.name.setText('changed while editor open');rejects07('stale modeless recipe editor cannot overwrite type form',ed11.accept_type_recipe)
ed11.close();td11.refresh();td11.load_row(next(i for i,r in enumerate(td11.rows) if r['kind']=='Beam'))
td11.duplicate();td11.code.setText('B2');td11.save();check07('duplicate type carries independent nested recipe',td11.saved()['rebar']==latest11['rebar'] and td11.saved()['id']!=latest11['id'])
td11.clear_recipe();rejects07('unsaved recipe removal cannot be used for placement',td11.saved);td11.save();check07('clear recipe removes only selected type recipe',td11.saved()['rebar'] is None and next(r for r in TU11.library(ts11)['types'] if r['id']==latest11['id'])['rebar'] is not None)
tv11.history.undo();check07('recipe removal Undo restores exact recipe',next(r for r in TU11.library(ts11)['types'] if r['code']=='B2')['rebar']==latest11['rebar'])
TC11.write(out07/'member-rebar-types-ไทย.json',TU11.library(ts11));check07('native recipe library Unicode JSON roundtrip',TC11.read(out07/'member-rebar-types-ไทย.json')==TU11.library(ts11))
records11,issues11=tb07.bbs_records(ts11);check07('all five typed cages produce valid BBS',records11 and not issues11 and len({r['host_uid'] for r in records11})==5)
M07.compact_save(ts11,out07/'typed-rebar-recipes.igz');reopened11=Scene();load_into(reopened11,out07/'typed-rebar-recipes.igz')
check07('IGZ reopen preserves project type recipes and bar provenance',TU11.library(reopened11)==TU11.library(ts11) and json.dumps([g.ext for g in reopened11.groups],sort_keys=True)==json.dumps([g.ext for g in ts11.groups],sort_keys=True) and not tb07.bbs_records(reopened11)[1])
# New unsaved types have a generated ID; editor acceptance binds to form values, not that volatile ID.
td11.new();td11.kind.setCurrentText('Column');td11.code.setText('C-ASTM');td11.name.setText('เสา ASTM นิ้ว');td11.fields['width'].setValue(.5);td11.fields['depth'].setValue(.5)
td11.edit_recipe();ed11=td11.recipe_dialog;cat11,size11,grade11=ed11.steel_controls['main_steel'];cat11.setCurrentText(C07.ASTM_IN);size11.setCurrentText('#9');ed11.representation.setCurrentText('Centreline');ed11.show();settle07()
commit11=next(b for b in ed11.findChildren(QPushButton) if b.text().startswith('ใช้รายละเอียดนี้'))
check07('recipe accept button visible outside scrolling parameter form',commit11.isVisible() and commit11.parent() is ed11)
NativeEvents07.mouseClick(commit11,Qt.LeftButton,Qt.NoModifier,commit11.rect().center());settle07()
check07('native button accepts recipe for a new unsaved type',td11.recipe is not None and not ed11.isVisible() and abs(td11.recipe['diameter']-28.6512)<1e-6)
td11.save();check07('new ASTM type saves exact inch diameter and recipe',abs(td11.saved()['rebar']['diameter']-28.6512)<1e-6 and td11.saved()['rebar']['main_steel']['catalogue']==C07.ASTM_IN)
td11.duplicate();td11.kind.setCurrentText('Footing');check07('changing duplicated host kind clears incompatible recipe',td11.recipe is None)
td11.refresh();td11.load_row(next(i for i,r in enumerate(td11.rows) if r['kind']=='Footing'));td11.show();settle07();td11.grab().save(str(out07/'rebar-type-library.png'))
td11.edit_recipe();ed11=td11.recipe_dialog;settle07();ed11.grab().save(str(out07/'rebar-type-editor.png'))
ed11.hide();td11.hide();ts11.selection={hosts11['Footing']};rf11=BB11.RebarDialog(tp11);rf11.read_host();rf11.show();settle07();rf11.grab().save(str(out07/'rebar-type-host-review.png'));rf11.hide()
ta11.window.deleteLater();settle07();units07.bind_scene(scene)
check07('recipe tests preserve actual user document geometry',actual11==(list(scene.groups),scene.version,set(scene.selection)))
print('PASS: '+str(len(checks07))+' cumulative native checks; all five member recipes verified')
