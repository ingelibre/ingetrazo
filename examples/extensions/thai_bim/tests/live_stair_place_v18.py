"""Native two-point stair Tool, preview framebuffer, snaps, repeat and Undo."""
from ingetrazo_plugin_thai_bim import stair_place_ui as SP17,stair_placement as GP17,stairs_ui as SU17,stair_library_ui as SL17
from PySide6.QtWidgets import QPushButton
from PySide6.QtGui import QImage
import importlib,time
SP17=importlib.reload(SP17);actual17=(list(scene.groups),scene.version,set(scene.selection));checks07=checks07[:523]
pa17=App07();pp17=tb07.setup(pa17);pp17.guard=lambda fn:fn();ps17=pa17.scene;pv17=pa17.viewport;ph17=pv17.history;pa17.window.show();settle07()
pd17=SU17.open_dialog(pp17,False);lib17=pd17.library;initial17=list(ps17.groups);placed17=[]
def ctx17(point):
    q=QVector3D(*point);return ToolContext(viewport=pv17,world=q,screen=QPointF(100,100),snap=SnapResult(q,'endpoint',(1,0,0)),modifiers=Qt.NoModifier)
for i17,layout17 in enumerate(ST15.LAYOUTS):
    lib17.refresh();lib17.load_index(next(i+1 for i,r in enumerate(lib17.rows) if r['params']['layout']==layout17))
    for hand17 in ('Left','Right'):
        pd17.hand.setCurrentText(hand17);pd17.pf['z'].setValue(-.4);pd17.click_z.setCurrentIndex(0);p17=pd17.geometry();q17=pd17.rebar();row17=copy.deepcopy(lib17.source)
        tool17=pd17.start_placement();before17=list(ps17.groups);a17=(i17*12,0 if hand17=='Left' else 12,7);b17=(a17[0]+3,a17[1]+2,-8)
        tool17.on_hover(ctx17(a17));check07(layout17+' '+hand17+' hover previews before first click without geometry changes',tool17.rubber_band_lines() and ps17.groups==before17 and not tool17.error)
        tool17.on_click(ctx17(a17));tool17.on_hover(ctx17(b17));check07(layout17+' '+hand17+' direction preview is cached and base Z stays fixed',len(tool17.points)==1 and tool17.points[0][2]==-.4 and len(tool17.rubber_band_lines())>10 and ps17.groups==before17)
        tool17.on_click(ctx17(b17));host17=next(g for g in ps17.groups if g.uid==tool17.last_uid);placed17.append(host17)
        check07(layout17+' '+hand17+' click creates exactly one nested Stair retaining siblings',len(ps17.groups)==len(before17)+1 and all(g in ps17.groups for g in before17) and all(tb07.bim.face_set_volume(list(c.mesh.faces))>0 for c in host17.children))
        anchor17=W07.P.point(W07.pose(host17),GP17.entrance(p17));check07(layout17+' '+hand17+' actual entrance anchor and initial ascent agree with clicked direction',all(abs(x-y)<1e-5 for x,y in zip(anchor17,(a17[0],a17[1],-.4))) and all(abs(x-y)<1e-5 for x,y in zip(W07.pose(host17),GP17.pose(p17,a17,b17,-.4))))
        check07(layout17+' '+hand17+' stores type snapshot preset overrides and click mode',host17.ext['thai_bim']['stair_type']==row17 and host17.ext['thai_bim']['stair_params']==p17 and host17.ext['thai_bim']['stair_rebar_preset']==q17 and host17.ext['thai_bim']['placement_mode']=='advanced-stair-two-point')
        tool17.on_cancel(pv17)
        check07(layout17+' '+hand17+' Escape return reads exact newly placed Host for detailing',pd17.isVisible() and pd17.host() is host17 and pd17.geometry()==p17 and pd17.rebar()==q17)
# Snap-Z then fixed elevation for the direction point; payload frozen at start.
lib17.refresh();lib17.load_index(1);pd17.click_z.setCurrentIndex(1);tool17=pd17.start_placement();frozen17=copy.deepcopy(tool17.params);pd17.gf['width'].setValue(1.2)
tool17.on_click(ctx17((90,0,1.25)));tool17.on_hover(ctx17((94,0,20)))
check07('first-point Z mode captures snapped level and then locks second-point plane',tool17.points[0][2]==1.25 and tool17.current[2]==1.25 and tool17.drag_plane(pv17)[0].z()==1.25)
specfn17=SP17.S.spec;SP17.S.spec=lambda **kw:(_ for _ in ()).throw(AssertionError('hover rebuilt geometry'))
try:
    clock17=time.perf_counter()
    for k17 in range(20):tool17.on_hover(ctx17((94,k17*.01,30)))
    elapsed17=time.perf_counter()-clock17;check07('twenty hover frames reuse cached local geometry without rebuilding solids',tool17.rubber_band_lines() and elapsed17<5)
finally:SP17.S.spec=specfn17
before17=list(ps17.groups);rejects07('coincident XY direction point cannot place a stair',lambda:tool17.on_click(ctx17((90,0,50))))
check07('rejected point keeps origin and all existing groups',len(tool17.points)==1 and ps17.groups==before17 and tool17.count==0)
tool17.on_click(ctx17((94,0,50)));snapped17=next(g for g in ps17.groups if g.uid==tool17.last_uid);placed17.append(snapped17)
check07('stair payload is frozen despite hidden form changes during placement',snapped17.ext['thai_bim']['stair_params']==frozen17 and snapped17.ext['thai_bim']['stair_placement']['entrance']==[90,0,1.25])
tool17.on_click(ctx17((100,0,2)));tool17.on_click(ctx17((104,0,-50)));repeat17=next(g for g in ps17.groups if g.uid==tool17.last_uid)
check07('same native Tool repeats without replacing first or any previous stairs',tool17.count==2 and snapped17 in ps17.groups and all(g in ps17.groups for g in placed17))
ph17.undo();check07('placement Undo removes only last repeated stair',repeat17 not in ps17.groups and snapped17 in ps17.groups and all(g in ps17.groups for g in placed17))
ph17.redo();check07('placement Redo restores exact original instance and snapshot',repeat17 in ps17.groups and repeat17.ext['thai_bim']['stair_params']==frozen17)
tool17.on_click(ctx17((110,0,9)));NativeEvents07.keyClick(pv17,Qt.Key_Escape);check07('first real Escape clears pending point but keeps repeated placement active',not tool17.points and pv17.active_tool is tool17)
NativeEvents07.keyClick(pv17,Qt.Key_Escape);check07('second real Escape exits placement and shows stair editor',pv17.active_tool is not tool17 and pd17.isVisible())
# Backspace, document switch, nested edit and previous-tool chaining.
tool17=pd17.start_placement();tool17.on_click(ctx17((110,0,0)));NativeEvents07.keyClick(pv17,Qt.Key_Backspace);check07('native Backspace resets pending entrance without creating geometry',not tool17.points and pv17.active_tool is tool17)
check07('Ctrl Z is left to native history shortcuts',not tool17.claims_key(int(Qt.Key_Z),Qt.ControlModifier))
toolagain17=pd17.start_placement();check07('starting another stair Tool unwraps earlier placement Tool',toolagain17.previous is tool17.previous)
oldscene17=pv17.scene;pv17.scene=Scene();toolagain17.on_click(ctx17((1,2,3)));check07('stale document Tool cancels without adding to new document',not pa17.scene.groups and pv17.active_tool is not toolagain17);pv17.scene=oldscene17
toolagain17.on_cancel(pv17)
M07.compact_save(ps17,out07/'stairs-two-point-all-forms-ไทย.igz');allopened17=Scene();load_into(allopened17,out07/'stairs-two-point-all-forms-ไทย.igz')
check07('all twelve form and hand variants persist with correct typed two-point metadata',len(allopened17.groups)==14 and {(g.ext['thai_bim']['stair_params']['layout'],g.ext['thai_bim']['stair_params']['hand']) for g in allopened17.groups}=={(k,h) for k in ST15.LAYOUTS for h in ('Left','Right')})
check07('all saved clicked stair concrete quantities remain valid after reopen',not tb07.quantity_rows(allopened17)[1])
pv17.begin_group_edit(placed17[0]);rejects07('group editing blocks starting stair placement',pd17.start_placement);pv17.end_group_edit()
# Native endpoint snaps + Qt mouse clicks and a visible OpenGL preview.
ra17=App07();rp17=tb07.setup(ra17);rp17.guard=lambda fn:fn();rv17=ra17.viewport;rs17=ra17.scene;ra17.window.show();settle07()
rd17=SU17.open_dialog(rp17,False);rd17.library.load_index(2);rd17.pf['z'].setValue(-.4)
ref17=tb07.make_group(tb07.E.box_spec('Column',0,0,.75,.2,.2,.5));rp17.execute(tb07.ExchangeGroups(rs17,additions=[ref17]))
button17=next(b for b in rd17.findChildren(QPushButton) if b.text()=='เริ่มคลิกวางบันได: ปาก → ทิศขึ้น');rd17.show();settle07();NativeEvents07.mouseClick(button17,Qt.LeftButton,Qt.NoModifier,button17.rect().center());rt17=rv17.active_tool
check07('real footer button starts native crosshair Tool and hides dialog',isinstance(rt17,SP17.StairTool) and not rd17.isVisible())
rv17.camera.target=QVector3D(2,1,0);rv17.camera.pitch=math.pi/2;rv17.camera.yaw=-math.pi/2;rv17.camera.distance=12;rv17.camera.perspective=False;rv17.update();settle07()
xs17,ys17,front17=ra17.world_to_pixels(np.asarray([(0,0,.75),(3,0,-.4)],float));screens17=[QPoint(round(x),round(y)) for x,y in zip(xs17,ys17)]
NativeEvents07.mouseMove(rv17,screens17[0]);NativeEvents07.mouseClick(rv17,Qt.LeftButton,Qt.NoModifier,screens17[0]);NativeEvents07.mouseMove(rv17,screens17[1]);settle07()
check07('native endpoint snapping supplies entrance XY while fixed Z remains lower datum',len(rt17.points)==1 and abs(rt17.points[0][0])<.03 and abs(rt17.points[0][1])<.03 and rt17.points[0][2]==-.4 and rv17.last_snap is not None)
rv17.repaint();frame17=rv17.grabFramebuffer();frame17.save(str(out07/'live-stair-click-preview.png'));rgba17=frame17.convertToFormat(QImage.Format_RGBA8888)
check07('real native framebuffer shows cyan stair ghost before commit',rgba17.constBits().tobytes().count(bytes([13,191,229,255]))>100 and rs17.groups==[ref17])
NativeEvents07.mouseClick(rv17,Qt.LeftButton,Qt.NoModifier,screens17[1]);settle07();realhost17=next(g for g in rs17.groups if g.uid==rt17.last_uid)
check07('real mouse clicks commit measured entrance and original stair dimensions',rt17.count==1 and len(rs17.groups)==2 and realhost17.ext['thai_bim']['stair_params']==rt17.params and abs(realhost17.ext['thai_bim']['stair_placement']['entrance'][0])<.03)
NativeEvents07.keyClick(rv17,Qt.Key_Escape);check07('real Escape opens placed Host ready for explicit rebar review',rd17.host() is realhost17 and rd17.isVisible())
rd17.review();rd17.build_rebar();check07('two-point native placed stair supports rigid Host rebar and BBS',not tb07.bbs_records(rs17)[1] and tb07.bbs_records(rs17)[0])
rd17.grab().save(str(out07/'stair-click-dialog.png'))
# Placement and reinforcement source survive save/reopen, and native copies.
from core.group import copy_group
from ingetrazo_plugin_thai_bim import copy_identity as CI17
cp17=copy_group(realhost17);rs17.groups.append(cp17);rs17.selection={realhost17};rd17.read_host();rt17=rd17.start_placement();rt17.on_click(ToolContext(viewport=rv17,world=QVector3D(12,0,9),screen=QPointF(100,100),snap=None,modifiers=Qt.NoModifier));rt17.on_click(ToolContext(viewport=rv17,world=QVector3D(16,0,9),screen=QPointF(100,100),snap=None,modifiers=Qt.NoModifier))
check07('native copied IDs are repaired automatically on a following stair placement',rt17.count==1 and not tb07.identity_issues(rs17) and realhost17 in rs17.groups and cp17 in rs17.groups)
rt17.on_cancel(rv17);M07.compact_save(rs17,out07/'stairs-two-point-ไทย.igz');reopened17=Scene();load_into(reopened17,out07/'stairs-two-point-ไทย.igz')
check07('native two-point stairs IGZ retains click metadata type and measured concrete',json.dumps([g.ext for g in reopened17.groups],sort_keys=True)==json.dumps([g.ext for g in rs17.groups],sort_keys=True) and not tb07.quantity_rows(reopened17)[1])
check07('native clicked stair BBS stays valid after IGZ reopen',not tb07.bbs_records(reopened17)[1])
tb07.E.write_xlsx(out07/'stairs-two-point-BBS.xlsx',tables=B07.D.tables(tb07.bbs_records(reopened17)[0]))
(out07/'stair-hover-performance.json').write_text(json.dumps(dict(frames=20,seconds=elapsed17,cached_edges=len(tool17.local_edges),basis='Synthetic Straight fixture; cached geometry; not whole-building benchmark'),indent=2),encoding='utf-8')
check07('new point Tool retains existing toolbar icon count',len(pp17.toolbar.actions())==21 and len(rp17.toolbar.actions())==21)
ra17.window.deleteLater();pa17.window.deleteLater();settle07();__import__('core.units',fromlist=['bind_scene']).bind_scene(scene)
check07('stair point placement tests preserve actual user document geometry',actual17==(list(scene.groups),scene.version,set(scene.selection)))
print('PASS: '+str(len(checks07))+' native checks including all stair forms two-point snap placement')
