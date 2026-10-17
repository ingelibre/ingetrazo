"""Native drag / click-click selected Host edits; immutable preview and one-step Undo."""
import copy,json,math,time
import numpy as np
from PySide6.QtCore import Qt,QPointF
from PySide6.QtGui import QVector3D,QPen,QColor
from tools.base import Tool
from tools.select import SelectTool
from . import shape_geometry as G,workflow as W,placement as P

def token(host):return W.host_token(host),json.dumps([host.ext['thai_bim'].get('member_type'),host.ext['thai_bim'].get('stair_type')],sort_keys=True)
def command(scene,host,result,pose,expected):
    from . import identity_issues,make_group,ExchangeGroups
    if scene.mesh is not scene.loose_mesh or host not in scene.groups or scene.selection!={host}:raise ValueError('Document / selection / edit context changed')
    if identity_issues(scene) or token(host)!=expected:raise ValueError('Host / copied IDs / type changed; restart shape editing')
    if result['kind']!=host.ext['thai_bim']['kind']:raise ValueError('Cannot change member kind')
    group=make_group(result,assembly=host.ext['thai_bim'].get('assembly',''),previous=host);group.xform=W.matrix(pose);group.name=host.name;group.layer=host.layer
    if group.ifc:group.ifc['name']=group.name
    group.ext['thai_bim']=dict(copy.deepcopy(host.ext['thai_bim']),**group.ext['thai_bim']);group.ext['thai_bim']['shape_edit']=dict(schema=1,source='selected viewport edit')
    group.ext['thai_bim']['instance_dimensions']=copy.deepcopy(result.get('params') or result.get('stair_params'))
    if result['kind']=='Stair':group.ext['thai_bim']['assembly_params']=copy.deepcopy(result['stair_params'])
    return ExchangeGroups(scene,replacements=[(host,group)]),group

class ShapeTool(Tool):
    name='Thai BIM selected shape edit';description='Drag beam ends, slab corners/edges, or stair landing; snap-aware, one member only'
    qt_cursor=Qt.CrossCursor;uses_snap=True;wireframe_color=(.05,.75,.9,1)
    def __init__(self,panel,host,opening=False,previous=None):
        self.panel=panel;self.scene=panel.app.scene;self.uid=host.uid;self.opening=opening;self.previous=previous if not isinstance(previous,ShapeTool) else previous.previous
        self.active=None;self.current=None;self.lines=[];self.error='';self.press=None;self.first=None;self.preview=None;self.last_hover=0;self.load(host)
    def load(self,host):
        self.expected=token(host);self.record=copy.deepcopy(host.ext['thai_bim']);self.pose=G.upright(W.pose(host));self.handles=G.handles(self.record);self.world_handles=[P._point(self.pose,h['point']) for h in self.handles]
    def host(self):return next((g for g in self.scene.groups if g.uid==self.uid),None)
    def valid(self,viewport):
        host=self.host()
        if self.panel.app.scene is not self.scene or self.scene.mesh is not self.scene.loose_mesh or host is None or self.scene.selection!={host}:
            self.on_cancel(viewport);return False
        return True
    @property
    def start_point(self):return QVector3D(*self.first) if self.first else QVector3D(*self.world_handles[self.active]) if self.active is not None else None
    def drag_plane(self,viewport):
        if self.active is not None:z=self.world_handles[self.active][2]
        else:z=self.world_handles[0][2]
        return QVector3D(0,0,z),QVector3D(0,0,1)
    def point(self,ctx):return (ctx.world.x(),ctx.world.y(),self.drag_plane(ctx.viewport)[0].z())
    def nearest(self,screen):
        x,y,front=self.panel.app.world_to_pixels(np.asarray(self.world_handles,float));candidates=[((float(x[i])-screen.x())**2+(float(y[i])-screen.y())**2,i) for i in range(len(x)) if front[i]]
        distance,index=min(candidates,default=(math.inf,None));return index if distance<=144 else None
    def on_activate(self,viewport):viewport.flash_status('คลิกจุดจับ → คลิกตำแหน่งใหม่ หรือกดลากแล้วปล่อย • Snap • Esc ยกเลิก • เหล็ก/แบบต้องตรวจใหม่',7000)
    def on_deactivate(self,viewport):self.lines=[]
    def on_hover(self,ctx):
        if not self.valid(ctx.viewport):return
        self.current=self.point(ctx)
        if self.active is None and self.first is None:return
        if time.monotonic()-self.last_hover<.035:return
        self.last_hover=time.monotonic();self.preview=None;self.error=''
        try:
            result,pose=G.add_opening(self.record,self.pose,self.first,self.current) if self.opening else G.change(self.record,self.pose,self.handles[self.active]['key'],self.current)
            self.preview=(result,pose);unique={}
            for f in result['faces']:
                for a,b in zip(f,f[1:]+f[:1]):unique.setdefault(tuple(sorted((tuple(a),tuple(b)))),(a,b))
            for holes in result.get('face_holes',{}).values():
                for hole in holes:
                    for a,b in zip(hole,hole[1:]+hole[:1]):unique.setdefault(tuple(sorted((tuple(a),tuple(b)))),(a,b))
            self.lines=[(QVector3D(*P._point(pose,a)),QVector3D(*P._point(pose,b))) for a,b in unique.values()]
        except ValueError as e:self.error=str(e);self.lines=[]
        ctx.viewport.update()
    def rubber_band_lines(self):return self.lines
    def status_clause(self):return ('ช่องเปิด: สองมุมใน local slab axes' if self.opening else 'แก้เฉพาะชิ้น: เลือกจุดจับ แล้วลาก/คลิกใหม่')+(' • '+self.error if self.error else '')
    def commit(self,viewport):
        if not self.valid(viewport):return
        if not self.preview:viewport.flash_status(self.error or 'Invalid shape; choose another point',5000);return
        def apply():
            cmd,host=command(self.scene,self.host(),*self.preview,self.expected);self.panel.execute(cmd);self.load(host);self.active=None;self.first=None;self.press=None;self.lines=[];self.preview=None;self.error=''
            viewport.flash_status('อัปเดตเฉพาะชิ้นแล้ว • Undo ได้ • ตรวจ/สร้างเหล็ก และอัปเดต Sheet / Analytical ใหม่',7000)
        self.panel.guard(apply);viewport.update()
    def on_click(self,ctx):
        if not self.valid(ctx.viewport):return
        if self.opening:
            if self.first is None:self.first=self.point(ctx);self.press=QPointF(ctx.screen);return
        elif self.active is None:
            self.active=self.nearest(ctx.screen)
            if self.active is None:ctx.viewport.flash_status('คลิกวงจุดจับสีส้ม',3000);return
            self.press=QPointF(ctx.screen);self.current=self.world_handles[self.active];return
        self.last_hover=0;self.on_hover(ctx);self.commit(ctx.viewport)
    def on_release(self,viewport):
        # First release without movement keeps click-click mode active.
        if self.current is not None and self.press is not None and self.preview:
            x,y,front=self.panel.app.world_to_pixels(np.asarray([self.current],float))
            if front[0] and math.hypot(float(x[0])-self.press.x(),float(y[0])-self.press.y())>=4:
                # Hover is throttled; release must commit the latest pointer,
                # never the earlier candidate from the preceding paint.
                try:self.preview=G.add_opening(self.record,self.pose,self.first,self.current) if self.opening else G.change(self.record,self.pose,self.handles[self.active]['key'],self.current)
                except ValueError as e:self.preview=None;self.error=str(e);self.lines=[]
                self.commit(viewport)
    def claims_key(self,key,mods):return key in (int(Qt.Key_Escape),int(Qt.Key_Backspace),int(Qt.Key_Delete)) and not mods&(Qt.ControlModifier|Qt.AltModifier|Qt.MetaModifier)
    def on_key(self,viewport,key,mods):
        if not self.valid(viewport):return True
        if key==int(Qt.Key_Delete) and self.active is not None and self.record['kind']=='Slab':
            handle=self.handles[self.active];ring=handle['key'][1]
            if ring>0:
                holes=copy.deepcopy(self.record['params'].get('holes',[]));holes.pop(ring-1);self.preview=(G.slab_spec(self.record['params'],holes=holes),self.pose);self.commit(viewport)
            else:viewport.flash_status('Delete removes an opening only; outer boundary retained',4000)
            return True
        if key in (int(Qt.Key_Escape),int(Qt.Key_Backspace)):
            if self.active is not None or self.first is not None:self.active=None;self.first=None;self.press=None;self.preview=None;self.lines=[];viewport.update()
            else:self.on_cancel(viewport)
            return True
        return False
    def on_cancel(self,viewport):
        self.lines=[];self.preview=None;self.active=None;self.first=None;viewport.set_active_tool(self.previous if self.panel.app.scene is self.scene else SelectTool());viewport.update()

def overlay(panel,painter):
    tool=getattr(panel,'shape_tool',None)
    if not tool or panel.app.viewport.active_tool is not tool or panel.app.scene is not tool.scene:return
    x,y,front=panel.app.world_to_pixels(np.asarray(tool.world_handles,float))
    for i,handle in enumerate(tool.handles):
        if not front[i]:continue
        pos=QPointF(float(x[i]),float(y[i]));painter.setPen(QPen(QColor('#ff8e35' if tool.active!=i else '#2ae0ff'),2));painter.drawEllipse(pos,6,6);painter.drawText(pos+QPointF(8,-8),handle['label'])

def start(panel,opening=False):
    from . import identity_issues
    scene=panel.app.scene;vp=panel.app.viewport
    if scene.mesh is not scene.loose_mesh or len(scene.selection)!=1:raise ValueError('Exit group editing; select one Beam / Slab / Stair')
    if identity_issues(scene):raise ValueError('Repair copied / missing business IDs first')
    host=next(iter(scene.selection));rec=host.ext.get('thai_bim',{})
    if rec.get('kind') not in ('Beam','Slab','Stair'):raise ValueError('Select a Thai BIM Beam / Slab / schema-2 Stair with landing')
    G.handles(rec);G.upright(W.pose(host))
    if opening and rec['kind']!='Slab':raise ValueError('Select Slab for opening')
    if not getattr(panel,'_shape_overlay',False):panel._shape_overlay=True;panel.app.add_overlay(lambda vp,painter:overlay(panel,painter))
    tool=ShapeTool(panel,host,opening,getattr(vp,'active_tool',None));panel.shape_tool=tool
    for attr in ('selected_edit_dialog','stairs_dialog','workspace_dialog'):
        d=getattr(panel,attr,None)
        if d:d.hide()
    vp.set_active_tool(tool);vp.setFocus();return tool
