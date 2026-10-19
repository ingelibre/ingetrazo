"""Native snap Tool for all six stairs; cached local preview, per-click Undo."""
import copy
from PySide6.QtCore import Qt
from PySide6.QtGui import QVector3D
from tools.base import Tool
from tools.select import SelectTool
from . import stair_placement as G,stairs as S,placement as P,engine as E,workflow as W
from .stair_library_ui import tag

def create_command(scene,params,rebar,row,a,b,z):
    from .stairs_ui import concrete_command
    m=G.pose(params,a,b,z);command,host=concrete_command(scene,params,m)
    tag(host,row,params,rebar);host.ext['thai_bim'].update(placement_mode='advanced-stair-two-point',
        stair_placement=dict(schema=1,entrance=[a[0],a[1],z],direction_point=[b[0],b[1],z],anchor='lower entrance midpoint',direction='initial ascent tangent'))
    return command,host

class StairTool(Tool):
    name='Thai BIM RC stair placement';description='Entrance midpoint then initial ascent direction; snap and repeat'
    qt_cursor=Qt.CrossCursor;uses_snap=True;wireframe_color=(.05,.75,.9,1)
    def __init__(self,dialog,params,rebar,row,z,snap_z=False,previous=None):
        self.dialog=dialog;self.panel=dialog.panel;self.scene=self.panel.app.scene
        self.params=S.validated(copy.deepcopy(params));self.rebar=copy.deepcopy(rebar);self.row=copy.deepcopy(row)
        self.z=E.finite(z);self.snap_z=bool(snap_z);self.previous=previous;self.points=[];self.current=None;self.lines=[];self.count=0;self.error='';self.last_uid=None
        self.local_edges=G.edges(S.spec(**self.params))
        u=G.ascent(self.params);m=P.matrix((0,0,0),dialog.pf['yaw'].value());self.initial_direction=P._point(m,u)
    @property
    def start_point(self):return QVector3D(*self.points[0]) if self.points else None
    def drag_plane(self,viewport):
        if self.snap_z and not self.points:return None
        return QVector3D(0,0,self.points[0][2] if self.points else self.z),QVector3D(0,0,1)
    def point(self,ctx):
        z=self.points[0][2] if self.points else ctx.world.z() if self.snap_z else self.z
        return tuple(E.finite(v) for v in (ctx.world.x(),ctx.world.y(),z))
    def valid_scene(self,viewport):
        if self.panel.app.scene is not self.scene or self.scene.mesh is not self.scene.loose_mesh:
            self.on_cancel(viewport);return False
        return True
    def on_activate(self,viewport):viewport.flash_status('บันได: คลิกกึ่งกลางปาก → ทิศขึ้น • จุดสองไม่เปลี่ยนขนาด • Esc จบ',5000)
    def on_deactivate(self,viewport):self.lines=[]
    def on_hover(self,ctx):
        if not self.valid_scene(ctx.viewport):return
        self.current=self.point(ctx);self.lines=[];self.error=''
        a=self.points[0] if self.points else self.current
        b=self.current if self.points else tuple(a[i]+self.initial_direction[i] for i in range(3))
        try:
            m=G.pose(self.params,a,b,a[2]);self.lines=[(QVector3D(*P._point(m,x)),QVector3D(*P._point(m,y))) for x,y in self.local_edges]
            if self.points:self.lines.append((QVector3D(*a),QVector3D(*b)))
        except ValueError as error:self.error=str(error);self.lines=[(QVector3D(*a),QVector3D(*b))]
        ctx.viewport.update()
    def rubber_band_lines(self):return self.lines
    def status_clause(self):
        step='คลิกทิศขึ้นช่วงแรก' if self.points else 'คลิกกึ่งกลางปากบันได';z=self.points[0][2] if self.points else self.z
        return f"{self.params['layout']} • {step} • Z {z:+.3f} m • สร้าง {self.count} ครั้ง"+(' • '+self.error if self.error else '')
    def on_click(self,ctx):
        if not self.valid_scene(ctx.viewport):return
        point=self.point(ctx)
        if not self.points:self.points=[point];self.on_hover(ctx);return
        a=self.points[0]
        def build():
            command,host=create_command(self.scene,self.params,self.rebar,self.row,a,point,a[2]);self.panel.execute(command)
            self.scene.selection={host};self.last_uid=host.uid;self.count+=1;self.points=[];self.lines=[];self.error='';ctx.viewport.update()
        try:self.panel.guard(build)
        except ValueError as error:self.error=str(error);raise
    def claims_key(self,key,modifiers):
        return key in (int(Qt.Key_Escape),int(Qt.Key_Backspace)) and not modifiers & (Qt.ControlModifier|Qt.AltModifier|Qt.MetaModifier)
    def on_key(self,viewport,key,modifiers):
        if not self.valid_scene(viewport):return True
        if key==int(Qt.Key_Backspace) or key==int(Qt.Key_Escape) and self.points:
            self.points=[];self.lines=[];self.error='';viewport.update();return True
        if key==int(Qt.Key_Escape):self.on_cancel(viewport);return True
        return False
    def on_cancel(self,viewport):
        same=self.panel.app.scene is self.scene;self.points=[];self.lines=[]
        viewport.set_active_tool(self.previous if same else SelectTool());viewport.update()
        if same and getattr(self.panel,'stairs_dialog',None) is self.dialog:
            self.dialog.show()
            host=next((g for g in self.scene.groups if g.uid==self.last_uid),None)
            if host is not None and self.scene.selection=={host}:self.dialog.read_host()

def start(dialog):
    dialog.library.check_scene();panel=dialog.panel;scene=panel.app.scene;vp=panel.app.viewport
    if scene.mesh is not scene.loose_mesh:raise ValueError('Exit group editing before stair placement')
    row=dialog.library.model_source();p=dialog.geometry();q=dialog.rebar()
    S.reinforcement(p,dict(q,representation='Centreline'))
    previous=getattr(vp,'active_tool',None)
    from .multi_place import PathTool
    while isinstance(previous,(StairTool,PathTool)):previous=previous.previous
    tool=StairTool(dialog,p,q,row,dialog.pf['z'].value(),dialog.click_z.currentIndex()==1,previous)
    panel.stair_tool=tool;dialog.timer.stop();dialog.hide();panel.workspace_dialog.hide();vp.set_active_tool(tool);vp.setFocus()
    return tool
