"""Run after live_shape_bootstrap_v21.py; isolated native scene only."""
import numpy as np
from PySide6.QtCore import Qt,QEvent,QPointF
from PySide6.QtGui import QMouseEvent,QVector3D
from formats.igz import save_scene
def mouse21(point,event=QEvent.MouseMove,buttons=Qt.NoButton):
 point=QPointF(point);button=Qt.LeftButton if event!=QEvent.MouseMove else Qt.NoButton
 QApplication.sendEvent(app21.viewport,QMouseEvent(event,point,QPointF(app21.viewport.mapToGlobal(point.toPoint())),button,buttons,Qt.NoModifier))
def click21(point):
 mouse21(point,QEvent.MouseButtonPress,Qt.LeftButton);mouse21(point,QEvent.MouseButtonRelease)
def screen21(world):
 x,y,front=app21.world_to_pixels(np.asarray([world],float));assert front[0];return QPointF(float(x[0]),float(y[0]))
def focus21(host,target):
 ss21.selection={host};app21.viewport.camera.target=QVector3D(*target);app21.viewport.camera.distance=9;app21.viewport.camera.pitch=1.15;app21.viewport.camera.yaw=.5;app21.viewport.update();settle21()
def swap21(host,result,pose):
 cmd,new=SH21.command(ss21,host,result,pose,SH21.token(host));sp21.execute(cmd);return new
from ingetrazo_plugin_thai_bim import catalogue as CAT21
beam21=tb21.make_group(EN21.box_spec('Beam',0,-.15,0,3,.3,.5));beam21.ext['thai_bim']['member_type']=CAT21.member_type('Beam','B1','Synthetic beam',{k:beam21.ext['thai_bim']['params'][k] for k in ('width','depth','height')});ss21.groups.append(beam21)
focus21(beam21,(1.5,0,0));tool21=SH21.start(sp21);start21=screen21(tool21.world_handles[1]);dest21=screen21((4,1,0));click21(start21)
check21('Native first click retains click-click mode and original Host',tool21.active==1 and beam21 in ss21.groups)
mouse21(dest21);settle21();check21('Native hover shows immutable wire preview',tool21.preview is not None and len(tool21.lines)>0 and beam21 in ss21.groups)
app21.viewport.grabFramebuffer().save(str(out21/'beam-shape-preview.png'));click21(dest21);settle21();newbeam21=tool21.host()
check21('Native second click replaces only selected beam',newbeam21 is not beam21 and len(ss21.groups)==1)
check21('Beam UID and member type preserved',newbeam21.uid==beam21.uid and newbeam21.ext['thai_bim']['member_type']==beam21.ext['thai_bim']['member_type'])
check21('Beam fixed end retained',math.dist(W21.P._point(W21.pose(newbeam21),(0,0,0)),(0,0,0))<1e-6)
app21.viewport.history.undo();check21('One Undo restores exact original beam',ss21.groups==[beam21]);app21.viewport.history.redo();check21('One Redo restores exact edited beam',ss21.groups==[newbeam21])
ss21.selection={newbeam21};tool21=SH21.start(sp21);click21(screen21(tool21.world_handles[1]));mouse21(screen21((4.5,1.5,0)));tool21.on_key(app21.viewport,int(Qt.Key_Escape),Qt.NoModifier)
check21('Escape cancels preview without altering geometry',newbeam21 in ss21.groups and tool21.active is None and not tool21.lines)
tool21.on_cancel(app21.viewport)
slab21=tb21.make_group(EN21.box_spec('Slab',0,0,3,4,3,.2));ss21.groups.append(slab21);focus21(slab21,(2,1.5,3.2))
tool21=SH21.start(sp21,opening=True);click21(screen21((1,1,3.2)));mouse21(screen21((2,2,3.2)));settle21()
check21('Opening native hover previews before commit',tool21.preview is not None and slab21 in ss21.groups)
click21(screen21((2,2,3.2)));slabhole21=tool21.host()
check21('Opening is two real native face hole loops',sum(len(f.holes) for f in slabhole21.mesh.faces)==2)
check21('Native opening net concrete volume',abs(tb21.bim.face_set_volume(list(slabhole21.mesh.faces))-slabhole21.ext['thai_bim']['quantity'])<1e-5)
holeparam21=slabhole21.ext['thai_bim']['params'];check21('Native pixel placement stays within 20 mm of target corners',len(holeparam21['holes'])==1 and all(math.dist(a,b)<.02 for a,b in zip(holeparam21['holes'][0],[(1,1),(2,1),(2,2),(1,2)])))
app21.viewport.grabFramebuffer().save(str(out21/'slab-opening.png'))
fp21=tb21.mesh_fingerprint(slabhole21);cap21=next(f for f in slabhole21.mesh.faces if f.holes);vertex21=cap21.hole_loops[0][0];original21=QVector3D(vertex21.position);vertex21.position=original21+QVector3D(.01,0,0)
check21('Hole-loop tampering changes guarded mesh fingerprint',tb21.mesh_fingerprint(slabhole21)!=fp21);vertex21.position=original21
newsp21,newpose21=SG21.change(slabhole21.ext['thai_bim'],W21.pose(slabhole21),('edge',0,0),(2,-.3,3.2));slabedge21=swap21(slabhole21,newsp21,newpose21)
check21('Slab edge edit retains opening',len(slabedge21.ext['thai_bim']['params']['holes'])==1)
check21('Native slab edge volume matches net metadata',abs(tb21.bim.face_set_volume(list(slabedge21.mesh.faces))-newsp21['quantity'])<1e-5)
ss21.selection={slabedge21};tool21=SH21.start(sp21);tool21.active=next(i for i,h in enumerate(tool21.handles) if h['key']==('vertex',1,0));tool21.on_key(app21.viewport,int(Qt.Key_Delete),Qt.NoModifier);slabclosed21=tool21.host()
check21('Delete hole handle removes whole opening only',not slabclosed21.ext['thai_bim']['params']['holes'] and len(ss21.groups)==2)
app21.viewport.history.undo();check21('Opening deletion Undo restores exact hole Host',slabedge21 in ss21.groups);app21.viewport.history.redo();check21('Opening deletion Redo restores closed Host',slabclosed21 in ss21.groups)
tool21.on_cancel(app21.viewport);ss21.selection={slabclosed21}
reject21('Outside opening rejected without mutation',lambda:SG21.add_opening(slabclosed21.ext['thai_bim'],W21.pose(slabclosed21),(-1,0,3.2),(1,1,3.2)))
for layout in ('Straight','L','U','Spiral','Circular'):
 for hand in ('Left','Right'):
  sh=tb21.make_group(ST21.spec(layout=layout,hand=hand,top_landing=True,bottom_landing=True));ss21.groups.append(sh);ss21.selection={sh};r=sh.ext['thai_bim'];handle=SG21.handles(r)[0];newpt=EN21.add(handle['point'],EN21.mul(handle['axis'],.15));spec,pose=SG21.change(r,W21.pose(sh),handle['key'],newpt);new=swap21(sh,spec,pose)
  check21(layout+' '+hand+' landing edit preserves UID and native closed children',new.uid==sh.uid and all(tb21.bim.face_set_volume(list(c.mesh.faces))>0 for c in new.children))
  check21(layout+' '+hand+' shared landing depth stored',abs(new.ext['thai_bim']['stair_params']['landing_depth']-r['stair_params']['landing_depth']-.15)<1e-6)
save_scene(ss21,out21/'selected-shape-edits.igz');reload21=Scene();load_into(reload21,out21/'selected-shape-edits.igz')
check21('Native IGZ retains all edited Hosts and identities',[(g.uid,g.name,tb21.mesh_fingerprint(g)) for g in reload21.groups]==[(g.uid,g.name,tb21.mesh_fingerprint(g)) for g in ss21.groups])
check21('Actual open user model and selection unchanged',actual21==[(g.uid,g.name,tb21.mesh_fingerprint(g)) for g in scene.groups] and actual_selection21=={g.uid for g in scene.selection})
print('PASS',len(checks21),'native shape checks')
