"""Host/pose checks, explicit reinforcement review and click placement UI."""
import copy,json,math
import numpy as np
from PySide6.QtCore import Qt,QPointF,QTimer
from PySide6.QtGui import QVector3D,QMatrix4x4
from PySide6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QComboBox,QCheckBox,QTableWidget,QTableWidgetItem
from tools.base import Tool
from core.snap import SnapResult
from . import engine as E,placement as P,detailing as D,structures as S

def pose(group):return [v for i in range(4) for v in group.xform.row(i).toTuple()] if group.xform is not None else None

def matrix(values):return QMatrix4x4(*P.rigid_matrix(values)) if values is not None else None

def host_token(host):
    from . import mesh_fingerprint
    rec=(host.ext or {}).get('thai_bim',{})
    params=rec.get('params') or rec.get('stair_params')
    if rec.get('kind') not in ('Footing','Column','Beam','Slab','Stair') or not params:raise ValueError('Select a Thai BIM concrete host')
    fingerprint=mesh_fingerprint(host)
    if fingerprint!=rec.get('fingerprint'):raise ValueError('Host geometry edited manually: verify / rebuild the concrete before reinforcement')
    m=P.rigid_matrix(pose(host))
    return (host.uid,rec.get('id'),fingerprint,tuple(m),json.dumps(params,sort_keys=True))

def bar_unchanged(group):
    from . import mesh_fingerprint
    rec=group.ext['thai_bim']
    if rec.get('copy_review_required'):return False
    if mesh_fingerprint(group)!=rec.get('fingerprint'):return False
    try:
        if 'bar_pose' in rec:return P.same_pose(pose(group),rec['bar_pose'])
        return group.xform is None
    except ValueError:return False

def host_matches(group,host,cache=None):
    if host is None:return False
    rec=group.ext['thai_bim']
    try:
        if cache is not None and host.uid in cache:token=cache[host.uid]
        else:
            token=host_token(host)
            if cache is not None:cache[host.uid]=token
        if token is None:return False
        if token[2]!=rec.get('host_hash'):return False
        if 'host_pose' in rec:return P.same_pose(token[3],rec['host_pose']) and bar_unchanged(group)
        return host.xform is None and bar_unchanged(group)
    except ValueError:
        if cache is not None:cache[host.uid]=None
        return False

def bar_specs(kind,host_params,ui_params):
    if host_params.get('stair_schema')==2:raise ValueError('Use advanced Stair / landing reinforcement dialog for schema 2 stairs')
    if host_params.get('shape')=='polygon':raise ValueError('Polygon slab reinforcement is not implemented; do not use a rectangular cage for this outline')
    p=copy.deepcopy(ui_params)
    for k in ('cover','diameter','tie_diameter','spacing','inside_radius','tie_inside_radius','hook_length','tie_hook_length','lap_length','extension_start','extension_end'):
        if k in p:p[k]/=1000
    if kind=='Stair':p['layers']=1
    return D.reinforcement(kind,host_params,**p)

def review_key(host,ui_params):return host_token(host),json.dumps(ui_params,sort_keys=True)

def host_notices(scene):
    """Inspect hosts once; do not sweep thousands of bar faces on every hover/edit."""
    from . import identity_issues
    if identity_issues(scene):return [dict(uid=None,name='Thai BIM identity',state='Blocked',reason='Copied / missing IDs: resolve before regeneration',count=0)]
    byuid={g.uid:g for g in scene.groups};sets={};notices=[]
    for g in scene.groups:
        r=(g.ext or {}).get('thai_bim',{})
        if r.get('host_uid'):sets.setdefault(r['host_uid'],[]).append(g)
    for uid,bars in sets.items():
        host=byuid.get(uid);name=host.name if host else uid;state='Current';reason='Host dimensions and pose match the last reinforcement build'
        try:
            if host is None:raise ValueError('Host missing; restore it or remove orphan bars explicitly')
            token=host_token(host)
            if any(token[2]!=g.ext['thai_bim'].get('host_hash') for g in bars):state='Review';reason='Host dimensions / local geometry changed'
            if any(not P.same_pose(token[3],g.ext['thai_bim'].get('host_pose')) for g in bars):
                reason=(reason+'; host moved / rotated') if state=='Review' else 'Host moved / rotated'
                state='Review'
            for g in bars:
                r=g.ext['thai_bim']
                if ('bar_pose' in r and not P.same_pose(pose(g),r['bar_pose'])) or ('bar_pose' not in r and g.xform is not None):
                    state='Blocked';reason='Bar independently moved / rotated; inspect it before regeneration';break
        except ValueError as error:state='Blocked';reason=str(error)
        notices.append(dict(uid=uid,name=name,state=state,reason=reason,count=len(bars)))
    return notices

def review_specs(scene,host,ui_params):
    from . import identity_issues
    if identity_issues(scene):raise ValueError('Resolve copied / missing Thai BIM IDs before reviewing')
    token=host_token(host);r=host.ext['thai_bim'];hp=r.get('params') or r.get('stair_params')
    old=[g for g in scene.groups if (g.ext or {}).get('thai_bim',{}).get('host_uid')==host.uid]
    if any(not bar_unchanged(g) for g in old):raise ValueError('Existing bar edited / independently moved: inspect it before regeneration')
    specs=bar_specs(r['kind'],hp,ui_params)
    before=sum(E.finite(g.ext['thai_bim']['quantity']) for g in old)
    after=sum(s['quantity'] for s in specs)
    return specs,token,dict(old_count=len(old),new_count=len(specs),old_m=before,new_m=after)

def placed_member_command(scene,config,previous=None,expected=None):
    from . import make_group,ExchangeGroups,identity_issues
    if previous is not None and identity_issues(scene):raise ValueError('Resolve Thai BIM copied / missing IDs before selected updates')
    if previous is not None:
        if previous not in scene.groups:raise ValueError('The selected host is no longer in this document')
        current=host_token(previous)
        if expected is not None and current!=expected:raise ValueError('Host changed after reading placement; read it again')
        if previous.ext['thai_bim']['kind']!=config['kind']:raise ValueError('Changing member type requires creating a new member')
    spec=P.member_spec(config['kind'],config['width'],config['depth'],config['height'])
    group=make_group(spec,previous.ext['thai_bim'].get('assembly','') if previous else '',previous)
    group.xform=matrix(P.matrix((config['x'],config['y'],config['z']),config['yaw']))
    group.ext['thai_bim']['placement']=dict(schema=1,anchor=[config[k] for k in ('x','y','z')],yaw=config['yaw'],
        basis='Centre bottom for Column/Footing; corner bottom for Beam/Slab')
    return ExchangeGroups(scene,replacements=[(previous,group)] if previous else (),additions=[] if previous else [group]),group

def placement_of(host):
    host_token(host);r=host.ext['thai_bim'];hp=r['params'];m=P.rigid_matrix(pose(host))
    if hp.get('shape')=='polygon':raise ValueError('Use the type library to change polygon slab thickness; rectangular placement would discard its outline')
    if any(abs(m[i]-P.IDENTITY[i])>1e-5 for i in (2,6,8,9,10)):raise ValueError('Placement dialog supports upright members rotated around Z; use rigid host review for tilted hosts')
    centred=r['kind'] in ('Column','Footing')
    local=(hp['x']+(hp['width']/2 if centred else 0),hp['y']+(hp['depth']/2 if centred else 0),hp['z'])
    anchor=P.point(m,local)
    return dict(kind=r['kind'],width=hp['width'],depth=hp['depth'],height=hp['height'],x=anchor[0],y=anchor[1],z=anchor[2],yaw=math.degrees(math.atan2(m[4],m[0])))

from .builders import BuilderDialog,icon

class PlacementDialog(BuilderDialog):
    def __init__(self,panel):
        super().__init__(panel,'Place');self.setWindowIcon(icon('Place'));self.selected_uid=None;self.selected_token=None;self.selected_scene=None
        self.kind=QComboBox();self.kind.addItems(['Footing','Column','Beam','Slab']);self.form.addRow('ชนิด RC',self.kind)
        self.kind.currentTextChanged.connect(lambda _:self.timer.start())
        self.note('ฐานราก/เสา: จุดวางกึ่งกลางฐาน • คาน/พื้น: มุมฐาน\nหมุนรอบ Z ที่จุดวาง • กรอกขนาดหน่วยเมตร')
        for key,label,value in [('width','ขนาดตาม local X (m)',1.2),('depth','ขนาดตาม local Y (m)',1.2),('height','สูง local Z (m)',.4)]:self.field(key,label,value,False,.05,40)
        for key,label,value in [('x','จุดวาง X (m)',0),('y','จุดวาง Y (m)',0),('z','ระดับฐาน Z คงที่ (m)',0),('yaw','หมุนรอบ Z (°)',0)]:self.field(key,label,value)
        self.grid_x=QComboBox();self.grid_y=QComboBox();self.level=QComboBox()
        self.form.addRow('Grid X',self.grid_x);self.form.addRow('Grid Y',self.grid_y);self.form.addRow('Level',self.level)
        self.snap_grid=QCheckBox('Snap จุดตัด Grid ภายใน 9 px');self.snap_grid.setChecked(True);self.form.addRow(self.snap_grid)
        self.button('อ่าน Grid/Level จากโครงการ',self.read_grid);self.button('ใช้จุดตัด Grid / Level ที่เลือก',self.use_grid)
        self.button('ใช้ขนาดจากหน้าชิ้นงาน',self.pick_form)
        self.button('สร้างหนึ่งชิ้นตามพรีวิว',self.build)
        self.button('เริ่มคลิกวางซ้ำในโมเดล',self.start)
        self.button('อ่านตำแหน่งชิ้น RC ที่เลือก',self.read_member)
        self.button('อัปเดตเฉพาะชิ้นที่อ่านไว้',lambda:self.build(True))
        self.note('คลิกซ้ายวาง • R หมุน +90° • Shift+R หมุน −90° • Esc จบ\nแต่ละคลิกเป็นหนึ่ง Undo; Z ใช้ระดับที่เลือกเสมอ\nหากชิ้นมีเหล็กเดิม ให้ตรวจ Host แล้วอัปเดตเหล็กแยก')
        self.read_grid();self.pick_form()
    def params(self):return dict(kind=self.kind.currentText(),**{k:w.value() for k,w in self.fields.items()})
    def specs(self):
        p=self.params();return P.world_specs([P.member_spec(p['kind'],p['width'],p['depth'],p['height'])],P.matrix((p['x'],p['y'],p['z']),p['yaw']))
    def read_grid(self):
        self.xs=E.coordinates(self.panel.gx.text());self.ys=E.coordinates(self.panel.gy.text());levels=E.levels(self.panel.lv.toPlainText())
        P.grid_points(self.xs,self.ys,0);self.grid_x.clear();self.grid_y.clear();self.level.clear()
        for v in self.xs:self.grid_x.addItem(f'X {v:g} m',v)
        for v in self.ys:self.grid_y.addItem(f'Y {v:g} m',v)
        for item in levels:self.level.addItem(f"{item['name']} {item['z']:+.3f} m",item['z'])
    def use_grid(self):
        for key,combo in [('x',self.grid_x),('y',self.grid_y),('z',self.level)]:
            if combo.currentData() is None:raise ValueError('Read Grid/Level first')
            self.fields[key].setValue(combo.currentData())
        self.preview()
    def pick_form(self):
        self.kind.setCurrentText(self.panel.kind.currentText())
        for key in ('width','depth','height'):self.fields[key].setValue(self.panel.mfields[key].value())
        self.fields['z'].setValue(self.panel.mfields['z'].value());self.preview()
    def read_member(self):
        scene=self.panel.app.scene;selected=[g for g in scene.selection if g in scene.groups]
        if len(selected)!=1:raise ValueError('Select one Thai BIM RC member')
        host=selected[0];p=placement_of(host);self.kind.setCurrentText(p['kind'])
        for key,w in self.fields.items():w.setValue(p[key])
        self.selected_uid=host.uid;self.selected_token=host_token(host);self.selected_scene=scene;self.preview()
    def build(self,update=False):
        scene=self.panel.app.scene;previous=None
        if update:
            if scene is not self.selected_scene:raise ValueError('Document changed; read placement again')
            previous=next((g for g in scene.groups if g.uid==self.selected_uid),None)
            if previous is None:raise ValueError('Read the selected RC member first')
        command,group=placed_member_command(scene,self.params(),previous,self.selected_token if update else None)
        self.panel.execute(command)
        if update:self.selected_token=host_token(group)
        self.output.setPlainText('อัปเดตชิ้นที่อ่านไว้แล้ว; เหล็กเดิมต้องตรวจ Host ใหม่' if update else 'สร้าง RC แล้ว • Undo หนึ่งครั้งต่อชิ้น')
    def start(self):
        self.specs();vp=self.panel.app.viewport
        if self.panel.app.scene.mesh is not self.panel.app.scene.loose_mesh:raise ValueError('Leave group editing before placement')
        tool=PlacementTool(self.panel,self.params(),self.xs,self.ys,self.snap_grid.isChecked(),getattr(vp,'active_tool',None))
        self.panel.placement_tool=tool;self.hide();self.panel.workspace_dialog.hide();vp.set_active_tool(tool);vp.setFocus()

class PlacementTool(Tool):
    name='Thai BIM click placement';description='Click to place repeated RC members; R rotates, Esc exits'
    qt_cursor=Qt.CrossCursor;uses_snap=True;wireframe_color=(.05,.7,.9,1)
    def __init__(self,panel,config,xs,ys,snap_grid=True,previous=None):
        self.panel=panel;self.config=copy.deepcopy(config);self.points=P.grid_points(xs,ys,config['z']);self.snap_grid=snap_grid
        while isinstance(previous,PlacementTool):previous=previous.previous
        self.previous=previous;self.bound_scene=panel.app.scene;self.current=None;self.lines=[];self.count=0
    def on_activate(self,viewport):viewport.flash_status('Thai BIM • คลิกวางซ้ำ / R หมุน / Esc จบ',4000)
    def on_deactivate(self,viewport):self.current=None;self.lines=[]
    def drag_plane(self,viewport):return QVector3D(0,0,self.config['z']),QVector3D(0,0,1)
    def resolve(self,ctx):
        result=self.panel.workflow.snap(ctx.viewport,ctx.snap,ctx.screen.x(),ctx.screen.y()) if self.snap_grid else None
        p=(result.point if result is not None else ctx.world).toTuple()
        return p[0],p[1],self.config['z']
    def on_hover(self,ctx):
        if self.panel.app.scene is not self.bound_scene:self.on_cancel(ctx.viewport);return
        self.current=self.resolve(ctx);self.config.update(zip(('x','y','z'),self.current));specs=self.preview_specs()
        self.lines=[(QVector3D(*a),QVector3D(*b)) for s in specs for f in s['faces'] for a,b in zip(f,f[1:]+f[:1])]
        ctx.viewport.update()
    def preview_specs(self):
        p=self.config;return P.world_specs([P.member_spec(p['kind'],p['width'],p['depth'],p['height'])],P.matrix((p['x'],p['y'],p['z']),p['yaw']))
    def rubber_band_lines(self):return self.lines
    def guide_preview_lines(self):
        if not self.snap_grid:return []
        xs=sorted({p[0] for p in self.points});ys=sorted({p[1] for p in self.points});z=self.config['z']
        return [(QVector3D(x,ys[0]-.5,z),QVector3D(x,ys[-1]+.5,z)) for x in xs]+[(QVector3D(xs[0]-.5,y,z),QVector3D(xs[-1]+.5,y,z)) for y in ys]
    def on_click(self,ctx):
        if self.panel.app.scene is not self.bound_scene:self.on_cancel(ctx.viewport);return
        self.on_hover(ctx)
        def create():
            command,group=placed_member_command(self.bound_scene,self.config);self.panel.execute(command);self.count+=1
            self.panel.report.setPlainText(f"คลิกวาง {self.config['kind']} {self.count} ชิ้น • จุดฐาน {self.current} • หมุน {self.config['yaw']:g}°")
        self.panel.guard(create)
    def on_key(self,viewport,key,modifiers):
        if key==int(Qt.Key_Escape):self.on_cancel(viewport);return True
        if key!=int(Qt.Key_R):return False
        self.config['yaw']+=( -90 if modifiers & Qt.ShiftModifier else 90)
        if self.current:
            specs=self.preview_specs();self.lines=[(QVector3D(*a),QVector3D(*b)) for s in specs for f in s['faces'] for a,b in zip(f,f[1:]+f[:1])]
        viewport.update();return True
    def claims_key(self,key,modifiers):
        return key in (int(Qt.Key_R),int(Qt.Key_Escape)) and not modifiers & (Qt.ControlModifier|Qt.AltModifier|Qt.MetaModifier)
    def status_clause(self):return f"Thai BIM {self.config['kind']} • R ±90° / Esc • Z {self.config['z']:+.3f} m • {self.count} placed"
    def on_cancel(self,viewport):viewport.set_active_tool(self.previous);viewport.update()

class Workflow:
    def __init__(self,panel):
        self.panel=panel;self.label=QLabel();self.label.setWordWrap(True);panel.members.addRow(self.label)
        self.timer=QTimer(panel);self.timer.setSingleShot(True);self.timer.setInterval(120);self.timer.timeout.connect(self.refresh)
        self.dialog=None;self.placement_dialog=None;self.rows=[]
    def schedule(self):self.timer.start()
    def refresh(self):
        self.rows=host_notices(self.panel.app.scene);pending=[r for r in self.rows if r['state']!='Current']
        self.label.setText(f'Host เหล็ก: {len(self.rows)} ชุด • ต้องตรวจ {len(pending)} ชุด')
        d=self.panel.builder_dialogs.get('Rebar')
        if d is not None and d.isVisible() and d.host_uid:d.timer.start()
    def snap(self,viewport,snap,x,y):
        tool=getattr(viewport,'active_tool',None)
        if not isinstance(tool,PlacementTool) or not tool.snap_grid:return None
        px,py,front=self.panel.app.world_to_pixels(np.asarray(tool.points,float))
        candidate=P.nearest_grid(tool.points,list(zip(px,py)),front,(x,y),snap.kind)
        return SnapResult(QVector3D(*candidate),'tbim_grid',(.05,.75,.9),label=f'Grid • Z {candidate[2]:+.3f} m') if candidate else None
    def open_placement(self):
        if self.placement_dialog is None:self.placement_dialog=PlacementDialog(self.panel)
        self.placement_dialog.show();self.placement_dialog.raise_();self.placement_dialog.activateWindow();return self.placement_dialog
    def open_hosts(self):
        self.refresh()
        if self.dialog is not None:self.dialog.close();self.dialog.deleteLater()
        dialog=QDialog(self.panel.app.window);dialog.setWindowTitle('Thai BIM 0.11 — Host / ตรวจเหล็กก่อนอัปเดต');dialog.resize(1080,570)
        lay=QVBoxLayout(dialog);lay.addWidget(QLabel('เลือก Host → เปิดพรีวิว → ตรวจรายละเอียด → อัปเดตเหล็ก • ไม่มีการสร้างใหม่อัตโนมัติ'))
        table=QTableWidget(len(self.rows),4);table.setHorizontalHeaderLabels(['Host','State','Reason','Bars']);table.setEditTriggers(QTableWidget.NoEditTriggers)
        rows=copy.deepcopy(self.rows);bound_scene=self.panel.app.scene
        for i,row in enumerate(rows):
            for j,key in enumerate(('name','state','reason','count')):table.setItem(i,j,QTableWidgetItem(str(row[key])))
        table.resizeColumnsToContents();lay.addWidget(table)
        def inspect():
            if self.panel.app.scene is not bound_scene:raise ValueError('Document changed; refresh the Host list')
            i=table.currentRow()
            if i<0:raise ValueError('Select a host row first')
            host=next((g for g in self.panel.app.scene.groups if g.uid==rows[i]['uid']),None)
            if host is None:raise ValueError('Host missing or document changed; refresh the list')
            self.panel.app.scene.selection={host};self.panel.app.viewport.update();self.panel.open_builder('Rebar')
            self.panel.builder_dialogs['Rebar'].read_host();dialog.hide()
        button=QPushButton('เปิดพรีวิวเหล็กของ Host ที่เลือก');button.clicked.connect(lambda:self.panel.guard(inspect));lay.addWidget(button)
        button=QPushButton('รีเฟรชรายการ');button.clicked.connect(lambda:self.panel.guard(self.open_hosts));lay.addWidget(button)
        self.dialog=dialog;dialog.show();return dialog

def install(panel):
    if getattr(panel,'workflow',None) is not None:return panel.workflow
    controller=Workflow(panel);panel.workflow=controller
    panel.app.on_document_changed(controller.schedule);panel.app.add_snap_provider(controller.snap)
    panel.button(panel.members,'วาง RC / Grid / หมุน / คลิกซ้ำ…',controller.open_placement)
    panel.button(panel.members,'ตรวจ Host และพรีวิวเหล็กที่เปลี่ยน…',controller.open_hosts)
    for key,text,fn in [('Place','วาง RC แบบคลิกซ้ำ / Grid / Level',controller.open_placement),('Host','ตรวจ Host / อัปเดตเหล็กหลังย้ายหรือปรับขนาด',controller.open_hosts)]:
        action=panel.toolbar.addAction(icon(key),text);action.setToolTip(text);action.triggered.connect(lambda checked=False,fn=fn:panel.guard(fn))
    panel.toolbar.setWindowTitle('Thai BIM 0.11');panel.workspace_dialog.setWindowTitle('Thai BIM Toolkit 0.10 — Placement / Host review / BBS')
    controller.refresh();return controller
