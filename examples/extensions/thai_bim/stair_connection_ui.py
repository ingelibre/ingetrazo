"""Explicit stair/support inspection, immutable project evidence and JSON export."""
import copy,json
from core.history import Command
from core.group import world_mesh
from PySide6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QFormLayout,QLabel,QComboBox,QDoubleSpinBox,QPushButton,QTableWidget,QTableWidgetItem,QFileDialog
from . import stairs as S,stair_connections as C,workflow as W,placement as P,analytical as A
from .builders import AssemblyPreview

KEY='thai_bim_stair_connections'
CLASSES=('IfcBeam','IfcSlab','IfcWall','IfcColumn')
STATES={'no_entry':'ไม่เข้าในรองรับ','surface_contact_only':'แตะผิวเท่านั้น','requirement_missing':'ยังไม่กำหนดระยะที่ต้องการ',
        'geometry_length_met':'ระยะรูปทรงถึงค่าที่กรอก','geometry_length_short':'ระยะรูปทรงสั้นกว่าค่าที่กรอก'}

def host(scene,uid):
    from . import identity_issues
    if identity_issues(scene):raise ValueError('Resolve copied / missing IDs before connection inspection')
    g=next((g for g in scene.groups if g.uid==uid),None)
    if g is None:raise ValueError('Stair no longer exists; read selected Stair')
    W.host_token(g)
    if g.ext['thai_bim'].get('stair_params',{}).get('stair_schema')!=2:raise ValueError('Select one advanced schema 2 RC Stair')
    return g

def support(scene,uid):
    g=next((g for g in scene.groups if g.uid==uid),None)
    if g is None or (g.ifc or {}).get('class') not in CLASSES:raise ValueError('Choose an actual IFC Beam / Slab / Wall / Column support')
    if (g.ext or {}).get('thai_bim'):W.host_token(g)
    mesh=world_mesh(g)
    if len(mesh.faces)>5000:raise ValueError('Support scope too large')
    triangles=[]
    for f in mesh.faces:triangles.extend([[tuple(p.toTuple()) for p in tri] for tri in f.triangulate()])
    triangles=C.prepare(triangles)
    return g,triangles

def bars(scene,g,mode):
    if mode not in ('Actual','Proposed'):raise ValueError('Choose Actual or Proposed reinforcement')
    r=g.ext['thai_bim'];p=r['stair_params'];out=[]
    if mode=='Actual':
        cache={g.uid:W.host_token(g)}
        for bar in scene.groups:
            br=(bar.ext or {}).get('thai_bim',{})
            if br.get('host_uid')!=g.uid:continue
            if br.get('stair_rebar_schema')!=1 or not W.host_matches(bar,g,cache):raise ValueError('Actual cage is stale / moved / edited; review and rebuild reinforcement first')
            out.append(dict(slot=br['slot'],role=br['bbs']['stair_role'],path=[list(P._point(P.rigid_matrix(W.pose(bar)),v)) for v in br['bar_path']],bar_uid=bar.uid))
        if not out:raise ValueError('No validated actual Stair cage; choose Proposed or build cage')
    else:
        q=copy.deepcopy(r.get('stair_rebar_preset') or (r.get('stair_type') or {}).get('rebar') or S.rebar_defaults())
        if not r.get('stair_rebar_preset') and not r.get('stair_type') and p['layout'] in ('Spiral','Circular'):q['connection']=0
        for spec in S.reinforcement(p,dict(q,representation='Centreline')):
            out.append(dict(slot=spec['slot'],role=spec['bbs']['stair_role'],path=[list(P._point(P.rigid_matrix(W.pose(g)),v)) for v in spec['bar_path']],bar_uid=None))
    return out

def inputs(scene,uid,target_uid,mode,role):
    g=host(scene,uid);target,triangles=support(scene,target_uid);paths=[b for b in bars(scene,g,mode) if b['role']==role]
    if not paths:raise ValueError('Bar role changed; read Stair and choose current role')
    sources=dict(stair_uid=g.uid,stair_id=g.ext['thai_bim']['id'],stair_name=g.name,host_token=W.host_token(g),
                 support_uid=target.uid,support_name=target.name,support_class=target.ifc['class'],support_triangles=triangles,
                 mode=mode,role=role,paths=paths)
    return g,target,triangles,paths,A.digest(sources)

def current(scene,report):
    try:return inputs(scene,report['stair_uid'],report['support_uid'],report['mode'],report['role'])[-1]==report['source_digest']
    except (ValueError,KeyError):return False

def generate(scene,uid,target_uid,mode,role,required=None):
    g,target,triangles,paths,digest=inputs(scene,uid,target_uid,mode,role);report=C.inspect(paths,triangles,required)
    report.update(stair_uid=g.uid,stair_id=g.ext['thai_bim']['id'],stair_name=g.name,support_uid=target.uid,support_name=target.name,
                  support_class=target.ifc['class'],mode=mode,role=role,source_digest=digest)
    return report,triangles

def record_key(report):return A.digest([report['stair_uid'],report['support_uid'],report['mode'],report['role']])

class SaveInspection(Command):
    def __init__(self,scene,report):
        self.scene=scene;self.before=copy.deepcopy(scene.plugin_data);self.report=copy.deepcopy(report);self.after=copy.deepcopy(self.before)
        records=self.after.setdefault(KEY,dict(schema=1,records={}))
        if records.get('schema')!=1 or not isinstance(records.get('records'),dict):raise ValueError('Invalid connection evidence store')
        if len(records['records'])>=500 and record_key(report) not in records['records']:raise ValueError('Project limited to 500 connection reports')
        records['records'][record_key(report)]=copy.deepcopy(report)
    def do(self,scene):
        if scene is not self.scene or scene.plugin_data!=self.before or not current(scene,self.report):raise ValueError('Sources or project changed; inspect again before saving')
        scene.plugin_data=copy.deepcopy(self.after);scene.version+=1
    def undo(self,scene):scene.plugin_data=copy.deepcopy(self.before);scene.version+=1

class ConnectionDialog(QDialog):
    def __init__(self,panel):
        super().__init__(panel.app.window);self.panel=panel;self.scene=panel.app.scene;self.uid=None;self.report=None;self.triangles=[]
        self.setWindowTitle('Thai BIM — รอยต่อบันได / รองรับ / ระยะรูปทรง');self.resize(1280,860)
        lay=QVBoxLayout(self);self.info=QLabel('อ่านบันได → เลือกรองรับและบทบาทเหล็ก → ตรวจรูปทรง\nเทียบช่วงแนวศูนย์กลางต่อเนื่องยาวสุดภายใน ไม่ใช่ผลออกแบบระยะฝัง/กำลัง/ระยะหุ้ม');self.info.setWordWrap(True);lay.addWidget(self.info)
        form=QFormLayout();lay.addLayout(form);self.stair_label=QLabel('ยังไม่ได้อ่าน Stair');form.addRow('บันได',self.stair_label)
        self.mode=QComboBox();self.mode.addItems(('Actual','Proposed'));form.addRow('Actual = เหล็กสร้างแล้ว / Proposed = ค่า Host ที่บันทึก',self.mode)
        self.targets=QComboBox();form.addRow('ชิ้นรองรับจริง (ต้องตรวจว่าเป็นรองรับตามแบบ)',self.targets)
        self.roles=QComboBox();form.addRow('บทบาทเหล็กที่จะตรวจ',self.roles)
        self.required=QDoubleSpinBox();self.required.setRange(0,3000);self.required.setDecimals(3);self.required.setSuffix(' mm');self.required.setSpecialValueText('ยังไม่กำหนด');form.addRow('ระยะรูปทรงที่ผู้ใช้ต้องการ (ไม่คำนวณตามมาตรฐาน)',self.required)
        self.visual=AssemblyPreview();lay.addWidget(self.visual,1)
        self.table=QTableWidget(0,5);self.table.setHorizontalHeaderLabels(['Slot เหล็ก','ภายในรวม mm','ต่อเนื่องยาวสุด mm','อยู่บนผิว mm','ผลรูปทรง']);self.table.setEditTriggers(QTableWidget.NoEditTriggers);self.table.setMaximumHeight(200);lay.addWidget(self.table)
        self.table.currentCellChanged.connect(self.focus_row)
        row=QHBoxLayout();lay.addLayout(row)
        for text,fn in [('อ่าน Stair ที่เลือก',self.read_stair),('รีเฟรชรองรับ',self.refresh_targets),('อ่านรองรับที่เลือก',self.read_support),('ตรวจและพรีวิว',self.inspect),('บันทึกรายงานในโครงการ',self.save),('อ่านรายงานคู่ที่เลือก',self.load_saved),('ส่งออก JSON…',self.export)]:
            button=QPushButton(text);button.clicked.connect(lambda checked=False,fn=fn:panel.guard(fn));row.addWidget(button)
        self.mode.currentIndexChanged.connect(lambda _:panel.guard(self.refresh_roles) if self.uid else None)
        self.refresh_targets()
    def check(self):
        if self.panel.app.scene is not self.scene:raise ValueError('Document changed; reopen connection inspection')
        if self.scene.mesh is not self.scene.loose_mesh:raise ValueError('Exit group editing before connection inspection')
    def read_stair(self):
        self.check()
        if len(self.scene.selection)!=1:raise ValueError('Select exactly one advanced Stair')
        g=host(self.scene,next(iter(self.scene.selection)).uid);self.uid=g.uid;self.stair_label.setText(g.name);self.report=None
        actual=any((b.ext or {}).get('thai_bim',{}).get('host_uid')==g.uid for b in self.scene.groups)
        self.mode.blockSignals(True);self.mode.setCurrentText('Actual' if actual else 'Proposed');self.mode.blockSignals(False);self.refresh_roles()
    def refresh_roles(self):
        self.check();g=host(self.scene,self.uid);rows=bars(self.scene,g,self.mode.currentText());self.roles.clear();self.roles.addItems(list(dict.fromkeys(r['role'] for r in rows)));self.report=None;self.table.setRowCount(0);self.visual.display([],P.world_specs([S.spec(**g.ext['thai_bim']['stair_params'])],W.pose(g)))
    def refresh_targets(self):
        self.check();uid=self.targets.currentData();self.targets.clear();self.targets.addItem('เลือกรองรับ',None)
        for g in self.scene.groups:
            if (g.ifc or {}).get('class') in CLASSES:self.targets.addItem(g.name+' • '+g.ifc['class']+' • '+g.uid[:8],g.uid)
        index=self.targets.findData(uid);self.targets.setCurrentIndex(index if index>=0 else 0)
    def read_support(self):
        self.check()
        if len(self.scene.selection)!=1:raise ValueError('Select exactly one actual support')
        g=next(iter(self.scene.selection));support(self.scene,g.uid);self.refresh_targets();self.targets.setCurrentIndex(self.targets.findData(g.uid))
    def inspect(self):
        self.check();self.report,self.triangles=generate(self.scene,self.uid,self.targets.currentData(),self.mode.currentText(),self.roles.currentText(),self.required.value()/1000 or None);self.display()
    def display(self):
        report=self.report;self.table.setRowCount(len(report['rows']))
        for i,r in enumerate(report['rows']):
            for j,value in enumerate((r['slot'],f"{r['inside_length_m']*1000:.3f}",f"{r['longest_inside_m']*1000:.3f}",f"{r['boundary_length_m']*1000:.3f}",STATES[r['state']])):self.table.setItem(i,j,QTableWidgetItem(str(value)))
        self.table.resizeColumnsToContents();fresh=current(self.scene,report)
        self.info.setText(('ข้อมูลปัจจุบัน' if fresh else 'ข้อมูลเก่า / แหล่งข้อมูลเปลี่ยน ต้องตรวจใหม่')+' • '+report['mode']+' • '+report['role']+'\n'+report['support_name']+' • เทียบช่วงต่อเนื่องยาวสุดของแนวศูนย์กลางเท่านั้น • ไม่รับรองระยะฝัง กำลัง หรือระยะหุ้ม')
        if fresh:self.focus_row(-1)
        else:self.visual.invalid('Sources changed; inspect again')
    def focus_row(self,row,*_):
        if self.report is None:return
        if not current(self.scene,self.report):self.visual.invalid('Sources changed; inspect again');return
        g=host(self.scene,self.uid);rows=[self.report['rows'][row]] if 0<=row<len(self.report['rows']) else self.report['rows']
        specs=[dict(kind='Support',faces=self.triangles)]+[dict(kind='Rebar',faces=[],bar_path=r['path']) for r in rows]
        self.visual.display(specs,P.world_specs([S.spec(**g.ext['thai_bim']['stair_params'])],W.pose(g)))
    def reviewed(self):
        self.check()
        if not self.report or self.uid!=self.report['stair_uid'] or self.targets.currentData()!=self.report['support_uid'] or self.roles.currentText()!=self.report['role'] or self.mode.currentText()!=self.report['mode'] or (self.required.value()/1000 or None)!=self.report['required_m'] or not current(self.scene,self.report):raise ValueError('Source / role / required length changed; inspect again')
        return copy.deepcopy(self.report)
    def save(self):self.panel.execute(SaveInspection(self.scene,self.reviewed()));self.display()
    def load_saved(self):
        self.check();key=A.digest([self.uid,self.targets.currentData(),self.mode.currentText(),self.roles.currentText()]);report=copy.deepcopy((self.scene.plugin_data.get(KEY) or {}).get('records',{}).get(key))
        if report is None:raise ValueError('No saved report for this Stair / support / role / mode')
        self.report=report;self.required.setValue((report['required_m'] or 0)*1000)
        if current(self.scene,report):self.triangles=support(self.scene,report['support_uid'])[1]
        self.display()
    def export(self):
        report=self.reviewed();path,_=QFileDialog.getSaveFileName(self,'ส่งออกรายงานรูปทรงรอยต่อ','','JSON (*.json)')
        if path:
            with open(path,'w',encoding='utf-8') as f:json.dump(report,f,ensure_ascii=False,indent=2,allow_nan=False)

def open_dialog(panel):
    old=getattr(panel,'stair_connection_dialog',None)
    if old:old.close();old.deleteLater()
    d=ConnectionDialog(panel);panel.stair_connection_dialog=d
    if len(panel.app.scene.selection)==1 and next(iter(panel.app.scene.selection)).ext.get('thai_bim',{}).get('stair_params',{}).get('stair_schema')==2:d.read_stair()
    d.show();return d
