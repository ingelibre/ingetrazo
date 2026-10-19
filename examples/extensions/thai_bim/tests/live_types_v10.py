"""Run after live_thai_bim_v10.py; isolated native member-library and Tool checks."""
from ingetrazo_plugin_thai_bim import catalogue as TC10,type_ui as TU10,multi_place as MP10,path_geometry as PG10
from tools.base import ToolContext
import tempfile,math
import numpy as np
checks07=checks07[:79]
actual10=(list(scene.groups),set(scene.selection))
ta10=App07();tw10=ta10.window;ts10=ta10.scene;tp10=tb07.setup(ta10);tp10.guard=lambda fn:fn();tv10=ta10.viewport
tw10.show();settle07();initial10=list(ts10.groups)
check07('type toolkit fresh setup has 19 nonempty icons',len(tp10.toolbar.actions())==19 and all(not a.icon().isNull() for a in tp10.toolbar.actions()))
TU10.install(tp10);check07('member type UI install idempotent',len(tp10.toolbar.actions())==19)
td10=TU10.open_library(tp10);td10.load_row(0);td10.fields['width'].setValue(1.6);td10.name.setText('ฐานราก F1 ทดสอบ');td10.save()
check07('native library saves Thai names and revision',TU10.library(ts10)['types'][-1]['name']=='ฐานราก F1 ทดสอบ' and td10.revision==2)
tv10.history.undo();check07('project library Undo restores prior type dimensions',TU10.library(ts10)['types'][0]['params']['width']==1.2)
tv10.history.redo();td10.refresh();td10.load_row(len(td10.rows)-1)
td10.duplicate();td10.code.setText('F2');td10.save()
check07('type duplicate uses a new persistent identity',len(TU10.library(ts10)['types'])==6 and len({r['id'] for r in TU10.library(ts10)['types']})==6)
td10.remove();check07('type removal retains placed geometry',ts10.groups==initial10 and len(TU10.library(ts10)['types'])==5)
tv10.history.undo();check07('type removal Undo restores exact library row',len(TU10.library(ts10)['types'])==6)
rows10={r['kind']:r for r in TU10.library(ts10)['types'] if r['code']!='F2'}
TC10.write(out07/'member-types-ไทย.json',TU10.library(ts10));check07('type library Unicode JSON roundtrip',TC10.read(out07/'member-types-ไทย.json')==TU10.library(ts10))
pd10=MP10.open_placement(tp10,rows10['Footing']);pd10.z.setValue(-.4)
tp10.gx.clear();tp10.gy.clear();tp10.lv.clear();pd10.start()
tool10=tv10.active_tool
def context10(point):
    q=QVector3D(*point);return ToolContext(viewport=tv10,world=q,screen=QPointF(100,100),snap=SnapResult(q,'endpoint',(1,0,0)),modifiers=Qt.NoModifier)
tool10.on_hover(context10((0,0,7)))
check07('live snap preview honors XY but holds typed base level',tool10.current==(0,0,-.4) and tool10.rubber_band_lines())
tool10.on_click(context10((0,0,7)));tool10.on_click(context10((3,0,9)))
check07('no-grid footing placement repeats without replacing prior groups',len(ts10.groups)==len(initial10)+2 and tool10.count==2)
foot10=ts10.groups[-2];sibling10=ts10.groups[-1]
check07('placed members contain stable type snapshot and instance IDs',foot10.ext['thai_bim']['member_type']['id']==rows10['Footing']['id'] and foot10.ext['thai_bim']['id']!=sibling10.ext['thai_bim']['id'])
changed10=TC10.snapshot(rows10['Footing']);changed10['params']['width']=2;changed10['revision']+=1
tp10.execute(TU10.LibraryChange(ts10,TC10.upsert(TU10.library(ts10),changed10)))
check07('editing type library does not mutate existing members',foot10.ext['thai_bim']['member_type']==rows10['Footing'] and foot10.ext['thai_bim']['params']['width']==1.6)
ts10.selection={foot10};cmd10,updated10=TU10.update_selected(ts10,changed10);tp10.execute(cmd10)
check07('type apply changes selected host only and preserves centre identity',sibling10 in ts10.groups and sibling10.ext['thai_bim']['params']['width']==1.6 and updated10.uid==foot10.uid and updated10.ext['thai_bim']['id']==foot10.ext['thai_bim']['id'] and abs(updated10.ext['thai_bim']['params']['x']+1)<1e-8)
tv10.history.undo();check07('selected type apply Undo restores exact original host',foot10 in ts10.groups and updated10 not in ts10.groups);tv10.history.redo()
ts10.selection=set();tool10.on_cancel(tv10)
pd10=MP10.open_placement(tp10,rows10['Column']);pd10.start();tool10=tv10.active_tool
tool10.on_click(context10((3,0,0)));column10=ts10.groups[-1]
check07('typed column placement retains prior footings and correct dimensions',updated10 in ts10.groups and sibling10 in ts10.groups and column10.ext['thai_bim']['kind']=='Column' and column10.ext['thai_bim']['params']['width']==.25)
tool10.on_cancel(tv10)
pd10=MP10.open_placement(tp10,rows10['Beam']);pd10.z.setValue(3);pd10.start();tool10=tv10.active_tool
tool10.on_click(context10((1,2,0)));count10=len(ts10.groups);tool10.on_hover(context10((4,6,0)))
check07('beam first point only previews native wireframe',len(ts10.groups)==count10 and tool10.rubber_band_lines())
tool10.on_click(context10((4,6,0)));beam10=ts10.groups[-1];br10=beam10.ext['thai_bim'];bp10=br10['params']
check07('two-point diagonal beam native closed solid and measured length',abs(bp10['width']-5)<1e-8 and abs(br10['volume_m3']-.4)<1e-5)
check07('two-point beam endpoint is centreline at input Z',all(abs(a-b)<1e-5 for a,b in zip(W07.P.point(W07.pose(beam10),(5,0,0)),(4,6,3))))
tv10.history.undo();check07('two-point beam Undo affects one member',beam10 not in ts10.groups and updated10 in ts10.groups);tv10.history.redo()
newbeam10=TC10.snapshot(rows10['Beam']);newbeam10['params']['depth']=.3;ts10.selection={beam10};cmd10,beamnew10=TU10.update_selected(ts10,newbeam10);tp10.execute(cmd10)
check07('beam type update preserves clicked length and centreline',beamnew10.ext['thai_bim']['params']['width']==5 and abs(beamnew10.ext['thai_bim']['params']['y']+.15)<1e-8)
ts10.selection=set();tool10.on_click(context10((0,0,0)));rejects07('zero-length beam cannot commit',lambda:tool10.on_click(context10((0,0,0))))
check07('Esc clears partial path before exiting',tool10.on_key(tv10,int(Qt.Key_Escape),Qt.NoModifier) and not tool10.points and tv10.active_tool is tool10)
tool10.on_key(tv10,int(Qt.Key_Escape),Qt.NoModifier)
pd10=MP10.open_placement(tp10,rows10['Slab']);pd10.z.setValue(3);pd10.start();tool10=tv10.active_tool
tool10.on_click(context10((6,4,0)));tool10.on_click(context10((0,0,0)));rect10=ts10.groups[-1]
check07('two-corner slab supports reverse corners and native volume',abs(rect10.ext['thai_bim']['volume_m3']-3.6)<1e-5)
tool10.on_cancel(tv10);pd10=MP10.open_placement(tp10,rows10['Slab']);pd10.mode.setCurrentIndex(1);pd10.z.setValue(4);pd10.start();tool10=tv10.active_tool
for a,b in ((0,0),(4,0),(4,2),(2,2),(2,4),(0,4)):tool10.on_click(context10((a,b,0)))
tool10.on_key(tv10,int(Qt.Key_Return),Qt.NoModifier);poly10=ts10.groups[-1]
check07('concave polygon slab native solid has actual outline volume',poly10.ext['thai_bim']['params']['shape']=='polygon' and abs(poly10.ext['thai_bim']['volume_m3']-1.8)<1e-5)
rejects07('polygon reinforcement clearly blocks rectangular substitution',lambda:W07.bar_specs('Slab',poly10.ext['thai_bim']['params'],{}))
ts10.selection={poly10};rejects07('old rectangle editor blocks polygon outline loss',tp10.selected)
newslab10=TC10.snapshot(rows10['Slab']);newslab10['params']['height']=.2;cmd10,polynew10=TU10.update_selected(ts10,newslab10);tp10.execute(cmd10)
check07('polygon type apply changes thickness and retains exact footprint',polynew10.ext['thai_bim']['params']['footprint']==poly10.ext['thai_bim']['params']['footprint'] and abs(polynew10.ext['thai_bim']['volume_m3']-2.4)<1e-5)
ts10.selection=set();tool10.on_cancel(tv10)
pd10=MP10.open_placement(tp10,rows10['Stair']);pd10.z.setValue(.15);pd10.top.setValue(3.75);pd10.start();tool10=tv10.active_tool
tool10.on_click(context10((8,0,0)));tool10.on_hover(context10((8,3,0)));check07('stair live preview follows second-point direction',bool(tool10.rubber_band_lines()))
tool10.on_click(context10((8,3,0)));stair10=ts10.groups[-1];sr10=stair10.ext['thai_bim'];hp10=sr10['stair_params']
check07('directed stair retains step going and architectural floor height',hp10['going']==.28 and abs(hp10['height']-3.6)<1e-8 and abs(W07.pose(stair10)[7])<1e-8)
specs10,token10,stats10=W07.review_specs(ts10,stair10,dict(cover=40,diameter=12,tie_diameter=6,spacing=150,layers=1,representation='Centreline'))
command10,_=tb07.rebar_command(ts10,stair10,specs10,{},expected=token10);tp10.execute(command10)
check07('directed stair supports explicit reinforcement Host review',any((g.ext or {}).get('thai_bim',{}).get('host_uid')==stair10.uid for g in ts10.groups) and not [r for r in W07.host_notices(ts10) if r['state']!='Current'])
tool10.on_cancel(tv10);td10=TU10.open_library(tp10);td10.load_row(next(i for i,r in enumerate(td10.rows) if r['kind']=='Beam'));settle07();td10.grab().save(str(out07/'member-library.png'));td10.hide()
pd10=MP10.open_placement(tp10,rows10['Stair']);pd10.grab().save(str(out07/'path-placement.png'));pd10.hide()
M07.compact_save(ts10,out07/'typed-members-click-placement.igz');rt10=Scene();load_into(rt10,out07/'typed-members-click-placement.igz')
check07('native IGZ persists library polygon types and host reinforcement',TU10.library(rt10)==TU10.library(ts10) and any((g.ext or {}).get('thai_bim',{}).get('params',{}).get('shape')=='polygon' for g in rt10.groups if (g.ext or {}).get('thai_bim',{}).get('params')))
ea10=App07();ep10=tb07.setup(ea10);ep10.guard=lambda fn:fn();ev10=ea10.viewport;ea10.window.show();settle07()
ed10=MP10.open_placement(ep10,TC10.defaults()['types'][2]);ed10.z.setValue(0);ed10.start();et10=ev10.active_tool
ev10.camera.target=QVector3D(1.5,0,0);ev10.camera.pitch=math.pi/2;ev10.camera.yaw=-math.pi/2;ev10.camera.distance=8;ev10.camera.perspective=False;ev10.update();settle07()
px10,py10,front10=ea10.world_to_pixels(np.asarray([(0,0,0),(3,0,0)],float));screen10=[QPoint(round(x),round(y)) for x,y in zip(px10,py10)]
NativeEvents07.mouseMove(ev10,screen10[0]);NativeEvents07.mouseClick(ev10,Qt.LeftButton,Qt.NoModifier,screen10[0]);NativeEvents07.mouseMove(ev10,screen10[1]);settle07()
check07('real Qt mouse events drive native beam rubber-band preview',len(et10.points)==1 and bool(et10.rubber_band_lines()) and not ea10.scene.groups)
from PySide6.QtGui import QImage
ev10.repaint();preview10=ev10.grabFramebuffer();preview10.save(str(out07/'live-beam-preview.png'))
rgba10=preview10.convertToFormat(QImage.Format_RGBA8888)
check07('native framebuffer contains visible cyan preview pixels',rgba10.constBits().tobytes().count(bytes([13,191,229,255]))>100)
NativeEvents07.mouseClick(ev10,Qt.LeftButton,Qt.NoModifier,screen10[1]);settle07()
check07('real Qt mouse clicks create beam at measured snap-plane span',et10.count==1 and len(ea10.scene.groups)==1 and abs(ea10.scene.groups[0].ext['thai_bim']['params']['width']-3)<.03)
check07('first typed placement persists project type library',ea10.scene.plugin_data['thai_bim']['member_library']==TC10.defaults())
ev10.history.undo();check07('first typed placement Undo removes only its new library snapshot and member',not ea10.scene.groups and not (ea10.scene.plugin_data.get('thai_bim') or {}).get('member_library'))
ev10.history.redo();check07('first typed placement Redo restores member and exact type library',len(ea10.scene.groups)==1 and ea10.scene.plugin_data['thai_bim']['member_library']==TC10.defaults())
NativeEvents07.keyClick(ev10,Qt.Key_Escape);check07('real Escape returns native viewport to prior tool',ev10.active_tool is not et10)
ea10.window.deleteLater();settle07()
tw10.deleteLater();settle07();from core import units;units.bind_scene(scene)
check07('type placement tests leave active user model unchanged',actual10==(list(scene.groups),set(scene.selection)))
print('PASS: '+str(len(checks07))+' cumulative native checks; member library and snap placement verified')
