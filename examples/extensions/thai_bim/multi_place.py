"""Native snap-aware point workflows with wireframe preview and per-member Undo."""
import copy,math
from PySide6.QtCore import Qt
from PySide6.QtGui import QVector3D
from PySide6.QtWidgets import QDialog,QVBoxLayout,QFormLayout,QComboBox,QLabel,QDoubleSpinBox,QSpinBox,QPushButton
from tools.base import Tool
from core.history import Command
from . import catalogue as C,path_geometry as G,placement as P,engine as E
from .type_ui import library,tag

MODES={'Footing':['point'],'Column':['point'],'Beam':['beam'],'Slab':['rectangle','polygon'],'Stair':['stair']}
LABELS={'point':'คลิกวางซ้ำ (กึ่งกลางฐาน)','beam':'คาน: จุดเริ่ม → จุดปลาย (แนวแกนคาน)',
        'rectangle':'พื้นสี่เหลี่ยม: สองมุมตรงข้าม','polygon':'พื้นหลายจุด: คลิกขอบเขต → Enter ปิดวง',
        'stair':'บันไดตรง: จุดเริ่ม → ทิศขึ้น (ความยาวตามขั้น)'}

class TypedPlacement(Command):
    def __init__(self,scene,member):
        self.scene=scene;self.member=member;self.before=copy.deepcopy(scene.plugin_data);self.after=copy.deepcopy(self.before)
        self.after.setdefault('thai_bim',{})['member_library']=library(scene)
    def do(self,scene):
        if scene is not self.scene or scene.plugin_data!=self.before:raise ValueError('Document metadata changed before placement')
        self.member.do(scene);scene.plugin_data=copy.deepcopy(self.after)
    def undo(self,scene):self.member.undo(scene);scene.plugin_data=copy.deepcopy(self.before)

def create_command(scene,mode,points,z,params,row=None):
    from . import make_group,ExchangeGroups,identity_issues
    from .workflow import matrix
    sp,pose=G.build(mode,points,z,params);group=make_group(sp);group.xform=matrix(pose)
    group.ext['thai_bim']['placement_mode']=mode;tag(group,row)
    if sp['kind']=='Stair':group.ext['thai_bim'].update(assembly_kind='rc-stair',assembly_params=copy.deepcopy(sp['stair_params']))
    member=ExchangeGroups(scene,additions=[group])
    return (TypedPlacement(scene,member) if row is not None else member),group

class PathTool(Tool):
    name='Thai BIM typed placement';description='Snap placement: points, beam, slab and directed stair'
    qt_cursor=Qt.CrossCursor;uses_snap=True;wireframe_color=(.05,.75,.9,1)
    def __init__(self,panel,mode,params,z,row=None,previous=None):
        self.panel=panel;self.scene=panel.app.scene;self.mode=mode;self.params=copy.deepcopy(params);self.z=E.finite(z);self.row=copy.deepcopy(row)
        while isinstance(previous,PathTool):previous=previous.previous
        self.previous=previous;self.points=[];self.current=None;self.lines=[];self.count=0;self.error=''
    def drag_plane(self,viewport):return QVector3D(0,0,self.z),QVector3D(0,0,1)
    def point(self,ctx):return (ctx.world.x(),ctx.world.y(),self.z)
    def valid_scene(self,viewport):
        if self.panel.app.scene is not self.scene:self.on_cancel(viewport);return False
        return True
    def on_activate(self,viewport):viewport.flash_status(LABELS[self.mode]+' • Esc จบ',4000)
    def on_deactivate(self,viewport):self.lines=[]
    def on_hover(self,ctx):
        if not self.valid_scene(ctx.viewport):return
        self.current=self.point(ctx);pts=self.points+[self.current];self.error='';self.lines=[]
        try:
            if self.mode=='point' or len(pts)>=2 and self.mode!='polygon' or len(pts)>=3:
                sp,m=G.build(self.mode,pts,self.z,self.params)
                self.lines=[(QVector3D(*P.point(m,a)),QVector3D(*P.point(m,b))) for f in sp['faces'] for a,b in zip(f,f[1:]+f[:1])]
            elif len(pts)>1:self.lines=[(QVector3D(*a),QVector3D(*b)) for a,b in zip(pts,pts[1:])]
        except ValueError as error:
            self.error=str(error);self.lines=[(QVector3D(*a),QVector3D(*b)) for a,b in zip(pts,pts[1:])]
        ctx.viewport.update()
    def rubber_band_lines(self):return self.lines
    def status_clause(self):return LABELS[self.mode]+f' • Z {self.z:+.3f} m • {self.count} placed'+(' • '+self.error if self.error else '')
    def commit(self,viewport,points):
        if not self.valid_scene(viewport):return
        def build():
            cmd,group=create_command(self.scene,self.mode,points,self.z,self.params,self.row);self.panel.execute(cmd)
            self.count+=1;self.points=[];self.lines=[];self.error='';viewport.update()
        self.panel.guard(build)
    def on_click(self,ctx):
        if not self.valid_scene(ctx.viewport):return
        point=self.point(ctx)
        if self.mode=='point':self.commit(ctx.viewport,[point]);return
        if self.mode=='polygon':
            if len(self.points)>=3 and math.dist(G.xy(point),G.xy(self.points[0]))<.02:self.commit(ctx.viewport,list(self.points));return
            if len(self.points)>=100:self.error='Maximum 100 polygon points';return
            if self.points and math.dist(G.xy(point),G.xy(self.points[-1]))<.002:return
            self.points.append(point);self.on_hover(ctx);return
        if not self.points:self.points=[point];self.on_hover(ctx)
        else:self.commit(ctx.viewport,[self.points[0],point])
    def claims_key(self,key,modifiers):return key in (int(Qt.Key_Escape),int(Qt.Key_Return),int(Qt.Key_Enter),int(Qt.Key_Backspace)) and not modifiers & (Qt.ControlModifier|Qt.AltModifier|Qt.MetaModifier)
    def on_key(self,viewport,key,modifiers):
        if key in (int(Qt.Key_Return),int(Qt.Key_Enter)) and self.mode=='polygon':self.commit(viewport,list(self.points));return True
        if key==int(Qt.Key_Backspace):
            if self.points:self.points.pop()
            self.lines=[];viewport.update();return True
        if key==int(Qt.Key_Escape):
            if self.points:self.points=[];self.lines=[];viewport.update()
            else:self.on_cancel(viewport)
            return True
        return False
    def on_cancel(self,viewport):viewport.set_active_tool(self.previous);viewport.update()

class PathDialog(QDialog):
    def __init__(self,panel,row=None):
        super().__init__(panel.app.window);self.panel=panel;self.bound_scene=panel.app.scene;self.setWindowTitle('Thai BIM — วางจากชนิดชิ้นงาน');self.resize(640,580)
        main=QVBoxLayout(self);self.form=QFormLayout();main.addLayout(self.form)
        self.kind=QComboBox();self.kind.addItems(C.KINDS);self.types=QComboBox();self.mode=QComboBox()
        self.form.addRow('ชิ้นงาน',self.kind);self.form.addRow('ชนิดจากคลังโครงการ',self.types);self.form.addRow('วิธีคลิก',self.mode)
        self.z=QDoubleSpinBox();self.z.setRange(-1000,1000);self.z.setDecimals(3);self.form.addRow('ระดับฐาน Z (m) คงที่',self.z)
        self.top=QDoubleSpinBox();self.top.setRange(-1000,1000);self.top.setDecimals(3);self.top.setValue(3);self.form.addRow('บันได: ระดับชั้นบน (m)',self.top)
        self.params_form=QFormLayout();main.addLayout(self.params_form);self.fields={}
        self.info=QLabel('ไม่ต้องมี Grid • สเนป geometry ของ IngeTrazo • Z ยึดระดับฐานที่กรอก\nพรีวิวเส้นตามเมาส์ • คาน/พื้นสร้างเมื่อคลิกครบ • คลิกต่อเพื่อสร้างชิ้นใหม่\nพื้นหลายจุด Enter ปิดวง / Backspace ย้อนจุด\nEsc ล้างจุดที่กำลังวาด; Esc อีกครั้งจบ • Undo แยกแต่ละชิ้น\nบันไดจุดที่สองกำหนดทิศเท่านั้น ความยาวคงตามลูกนอน/จำนวนขั้น\nคานแนวราบ / พื้นแนวราบไม่มีช่องเจาะ / บันไดตรงไม่มีชานพัก');self.info.setWordWrap(True);main.addWidget(self.info)
        start=QPushButton('เริ่มคลิกวางพร้อมพรีวิว');start.clicked.connect(lambda:self.panel.guard(self.start));main.addWidget(start)
        self.kind.currentTextChanged.connect(self.configure);self.types.currentIndexChanged.connect(self.read_type);self.configure()
        if row:
            self.kind.setCurrentText(row['kind']);self.types.setCurrentIndex(self.types.findData(row['id']))
    def configure(self):
        while self.params_form.rowCount():self.params_form.removeRow(0)
        kind=self.kind.currentText();self.fields={}
        labels={'width':'กว้าง X / บันได (m)','depth':'หน้ากว้างคาน / กว้าง Y (m)','height':'สูง / หนา (m)','going':'ลูกนอน (m)','risers':'จำนวนลูกตั้ง','waist':'ความหนาท้อง (m)'}
        for key,value in C.DEFAULTS[kind].items():
            if kind=='Beam' and key=='width' or kind=='Slab' and key in ('width','depth') or kind=='Stair' and key=='height':continue
            w=QSpinBox() if key=='risers' else QDoubleSpinBox()
            if key=='risers':w.setRange(2,60)
            else:w.setDecimals(3);w.setRange(.002,100)
            w.setValue(value);self.fields[key]=w;self.params_form.addRow(labels[key],w)
        self.top.setEnabled(kind=='Stair');self.mode.clear()
        for mode in MODES[kind]:self.mode.addItem(LABELS[mode],mode)
        self.types.blockSignals(True);self.types.clear();self.types.addItem('Custom / ไม่ผูกชนิด',None)
        self.rows={r['id']:r for r in library(self.panel.app.scene)['types'] if r['kind']==kind}
        for r in self.rows.values():self.types.addItem(r['code']+' — '+r['name'],r['id'])
        self.types.blockSignals(False);self.read_type()
    def read_type(self):
        row=self.rows.get(self.types.currentData())
        p=row['params'] if row else C.DEFAULTS[self.kind.currentText()]
        for k,w in self.fields.items():w.setValue(p[k])
        if self.kind.currentText()=='Stair':self.top.setValue(self.z.value()+p['height'])
    def start(self):
        if self.panel.app.scene is not self.bound_scene:raise ValueError('Document changed; reopen placement')
        vp=self.panel.app.viewport
        if self.panel.app.scene.mesh is not self.panel.app.scene.loose_mesh:raise ValueError('Exit group editing before placement')
        kind=self.kind.currentText();p=copy.deepcopy(C.DEFAULTS[kind]);p.update({k:w.value() for k,w in self.fields.items()});p['kind']=kind
        if kind=='Stair':p['height']=self.top.value()-self.z.value()
        # Validate instance overrides before entering the live tool.
        C.member_type(kind,'Custom','Custom',{k:p[k] for k in C.FIELDS[kind]})
        row=self.rows.get(self.types.currentData());mode=self.mode.currentData()
        tool=PathTool(self.panel,mode,p,self.z.value(),row,getattr(vp,'active_tool',None))
        self.panel.path_tool=tool;self.hide();self.panel.workspace_dialog.hide();vp.set_active_tool(tool);vp.setFocus()

def open_placement(panel,row=None):
    old=getattr(panel,'path_dialog',None)
    if old:old.close();old.deleteLater()
    d=PathDialog(panel,row);panel.path_dialog=d;d.show();return d
