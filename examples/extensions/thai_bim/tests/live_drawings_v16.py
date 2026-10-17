"""Run after live_thai_bim_v09.py in IngeTrazo; uses an isolated native viewport."""
from ingetrazo_plugin_thai_bim import drawings as DR09
from core.composition import TextoItem,Composicion
from core.section import SectionPlane
from core.saved_views import SavedView
from core.extensions import _import_by_path,user_plugins_dir
from core import units
checks07=checks07[:118]

from views.composer import ComposerWindow
da09=App07();dw09=da09.window;dw09.viewport=da09.viewport;dw09._current_path=None
def ensure09():
    if not hasattr(dw09,'_composer'):dw09._composer=ComposerWindow(dw09)
    return dw09._composer
dw09._ensure_composer=ensure09;dw09._refresh_sheet_tabs=lambda:None
ds09=da09.scene;dp09=tb07.setup(da09);dp09.guard=lambda fn:fn()
ds09.groups.append(tb07.make_group(tb07.E.box_spec('Column',-10,-10,0,.2,.2,1)))
ds09.groups[0].billboard=True;ds09.groups[0].hidden=True;ds09.groups[0].name='Test scale figure'
dw09.show();settle07()
start09=(list(scene.groups),set(scene.selection));before09=list(ds09.groups)
check07('drawing toolbar has 21 icons',len(dp09.toolbar.actions())==21 and not dp09.toolbar.actions()[-1].icon().isNull())
for kind,values in [('Slab',(0,0,0,6,4,.15)),('Column',(0,0,.15,.2,.2,3)),('Column',(5.8,3.8,.15,.2,.2,3)),
    ('Beam',(0,0,3.15,6,.2,.25)),('Beam',(0,3.8,3.15,6,.2,.25))]:
    ds09.groups.append(tb07.make_group(tb07.E.box_spec(kind,*values)))
for sp in tb07.E.roof_specs(z=3.4,width=6,depth=4):
    if sp['kind']=='Roof cover':ds09.groups.append(tb07.make_group(sp))
unrelated09=Composicion(name='User existing sheet');ds09.compositions.append(unrelated09)
usercut09=SectionPlane(QVector3D(0,0,2),QVector3D(0,1,0),name='User section',symbol='Z');ds09.section_planes.append(usercut09);ds09.set_active_section(usercut09)
ds09.groups[1].hidden=True
dialog09=DR09.DrawingDialog(dp09);dialog09.style.setCurrentIndex(1)
dialog09.fields['name'].setText('Thai BIM synthetic 6x4');dialog09.fields['author'].setText('Thai BIM Test')
dialog09.fields['grid_x'].setText('0,3,6');dialog09.fields['grid_y'].setText('0,4')
dialog09.levels.setPlainText('Ground=0\nUpper FFL=3.75\nUpper structure=3.65')
dialog09.review();dialog09.show();settle07();dialog09.grab().save(str(out07/'drawing-dialog.png'));dialog09.hide()
check07('paper preview keeps 1m equal to 20mm',dialog09.preview.layout['scale']==50)
dialog09.fields['revision'].setText('02');rejects07('changed UI cannot build stale preview',dialog09.build)
dialog09.review();dialog09.build()
parts09,meta09=DR09.validate_set(ds09);comps09=parts09[0]
check07('five native sheets created with unrelated sheet retained',len(comps09)==5 and unrelated09 in ds09.compositions)
check07('all frames are parallel at 1:50',all(f.scale_n==50 and not f.perspective for c in comps09 for f in c.frames))
check07('dimensions anchor to each frame and world points',all(c.cotas and all(d.anchored and d.anchor_uid==c.frames[0].uid for d in c.cotas) for c in comps09))
check07('native grid span dimensions measure 3000mm',any(abs(d.real_distance_m()-3)<1e-8 for c in comps09 for d in c.cotas))
check07('architectural levels retained not MEP levels',all(n.level_m() in (0,3.75,3.65) for c in comps09 for n in c.niveles))
before_groups09=list(ds09.groups);dw09.viewport.history.undo()
check07('sheet Undo preserves exact groups and prior sheet',ds09.groups==before_groups09 and ds09.compositions==[unrelated09])
dw09.viewport.history.redo();check07('sheet Redo restores exact new sheet objects',all(c in ds09.compositions for c in comps09))
dialog09.review();dialog09.build();parts09,meta09=DR09.validate_set(ds09);comps09=parts09[0]
check07('update replaces owned sheets without duplicates',len(ds09.compositions)==6 and len(parts09[1])==5 and unrelated09 in ds09.compositions)
paper09=DR09.composer(dp09);flags09=([(g,g.hidden) for g in ds09.groups],[(l,l.visible) for l in ds09.layers],ds09.active_section(),ds09.show_hidden_objects,ds09.show_hidden_geometry)
cam09=SavedView.capture('camera-before',ds09,dw09.viewport.camera).to_dict()
path09=DR09.export_set(dp09,out07/'Thai-BIM-drawings-1-50.pdf')
check07('native PDF generated',path09.exists() and path09.stat().st_size>1000)
check07('export retains all unrelated sheets',ds09.compositions[0] is unrelated09 and len(ds09.compositions)==6)
check07('export preserves object and layer visibility and active cut',flags09==([(g,g.hidden) for g in ds09.groups],[(l,l.visible) for l in ds09.layers],ds09.active_section(),ds09.show_hidden_objects,ds09.show_hidden_geometry))
check07('export preserves original camera',cam09==SavedView.capture('camera-before',ds09,dw09.viewport.camera).to_dict())
check07('rendered vector frames contain real model lines',all(len(paper09.hlr_cache.get(id(c.frames[0]),[]))>0 for c in comps09))
check07('export reprojection is not mistaken for manual edits',DR09.presentation_hash(parts09)==meta09['presentation_hash'])
dialog09.review();dialog09.build();parts09,meta09=DR09.validate_set(ds09);comps09=parts09[0]
check07('sheets regenerate after PDF export without duplication',len(ds09.compositions)==6)
frame09=comps09[0].frames[0];frame09.style='tecnico'
try:
    technical09=paper09.render_frame(frame09)
    check07('default technical renderer produces a native image',technical09 is not None and not technical09.isNull())
finally:frame09.style='vectorial'
DR09.export_set(dp09,path09)
comps09[0].texts.append(TextoItem(x_mm=18,y_mm=238,w_mm=160,text='Manual coordination note',size_pt=8))
check07('manual annotations allowed for export',DR09.validate_set(ds09)[0][0][0] is comps09[0])
dialog09.review();rejects07('manual sheet edits not overwritten by regeneration',dialog09.build)
comps09[0].texts.pop()
g09=next(g for g in ds09.groups if g.uid in meta09['source_uids']);oldform09=g09.xform
g09.xform=W07.matrix(W07.P.matrix((.1,0,0)))
rejects07('moved model blocks stale PDF export',lambda:DR09.validate_set(ds09));g09.xform=oldform09
foreign09=list(ds09.compositions);pending09=DR09.DrawingSet(ds09,DR09.sources(ds09),dialog09.options(),DR09.source_info(ds09,DR09.sources(ds09))['stamp'])
unrelated09.texts.append(TextoItem(text='intervening user edit'))
rejects07('intervening sheet mutation blocks prepared command',lambda:pending09.do(ds09));unrelated09.texts.pop()
check07('rejected stale command retains all current sheets',ds09.compositions==foreign09)
M07.compact_save(ds09,out07/'drawing-set-1-50.igz')
read09=Scene();load_into(read09,out07/'drawing-set-1-50.igz')
check07('native IGZ roundtrip retains sheets metadata and anchors',len(DR09.validate_set(read09)[0][0])==5 and all(d.anchored for c in DR09.validate_set(read09)[0][0] for d in c.cotas))
# Saved-view scope intentionally shows only the reviewed model, including a selected hidden member.
check07('scale person excluded from saved drawing views',all(before09[0].uid in v.hidden_objects for v in parts09[1]))
paper09.comp=comps09[0];paper09._rebuild_canvas();paper09.grab().save(str(out07/'composer-sheet.png'))
dw09.deleteLater();settle07();units.bind_scene(scene)
check07('drawing tests leave active user model unchanged',start09==(list(scene.groups),set(scene.selection)))
print('Drawings complete: '+str(len(checks07))+' cumulative native checks; PDF '+str(path09))
