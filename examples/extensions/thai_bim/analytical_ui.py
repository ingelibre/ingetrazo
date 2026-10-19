"""Native analytical preview and undoable project snapshot; no concrete edits."""
import copy,json,os,tempfile
from pathlib import Path
import numpy as np
from core.history import Command
from PySide6.QtCore import Qt,QPointF
from PySide6.QtGui import QPen,QColor
from PySide6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QDoubleSpinBox,QTableWidget,QTableWidgetItem,QFileDialog,QCheckBox
from . import analytical as A,workflow as W

KEY='thai_bim_analytical'
def sources(scene):
    from . import identity_issues
    if identity_issues(scene):raise ValueError('Repair copied / missing Thai BIM IDs before analytical conversion')
    rows=[]
    for g in scene.groups:
        r=(g.ext or {}).get('thai_bim',{})
        if r.get('kind') not in ('Beam','Column'):continue
        token=W.host_token(g)
        rows.append(dict(id=r['id'],native_uid=g.uid,name=g.name,kind=r['kind'],params=copy.deepcopy(r['params']),pose=list(token[3]),geometry_hash=token[2]))
    return sorted(rows,key=lambda r:r['id'])
def current(scene,model):
    try:return A.digest(sources(scene))==model['source_digest']
    except ValueError:return False

class SnapshotChange(Command):
    def __init__(self,scene,model):self.scene=scene;self.before=copy.deepcopy(scene.plugin_data);self.model=A.validate(model)
    def do(self,scene):
        if scene is not self.scene or scene.plugin_data!=self.before or not current(scene,self.model):raise ValueError('Document or sources changed; regenerate analytical preview')
        scene.plugin_data=copy.deepcopy(self.before);scene.plugin_data[KEY]=copy.deepcopy(self.model);scene.version+=1
    def undo(self,scene):scene.plugin_data=copy.deepcopy(self.before);scene.version+=1

class AnalyticalDialog(QDialog):
    def __init__(self,panel):
        super().__init__(panel.app.window);self.panel=panel;self.bound_scene=panel.app.scene;self.model=None;self.focus=None
        self.setWindowTitle('Thai BIM — Analytical Model / คาน–เสา');self.resize(1000,650)
        lay=QVBoxLayout(self);self.info=QLabel('โมเดลแนวแกนสำหรับตรวจความต่อเนื่อง • ยังไม่มี solver\nไม่มีวัสดุ จุดรองรับ และโหลด: ยังใช้คำนวณไม่ได้');self.info.setWordWrap(True);lay.addWidget(self.info)
        row=QHBoxLayout();lay.addLayout(row);row.addWidget(QLabel('ระยะตรวจจุดใกล้กัน (mm) • ไม่รวมจุดอัตโนมัติ'))
        self.tolerance=QDoubleSpinBox();self.tolerance.setRange(.001,100);self.tolerance.setDecimals(3);self.tolerance.setValue(10);row.addWidget(self.tolerance)
        self.visible=QCheckBox('แสดงแนวแกนและจุดต่อใน viewport');self.visible.setChecked(True);self.visible.toggled.connect(lambda _:panel.app.viewport.update());row.addWidget(self.visible)
        self.table=QTableWidget(0,3);self.table.setHorizontalHeaderLabels(['ประเภท','ตำแหน่ง / ชิ้นงาน','รายละเอียด']);self.table.setEditTriggers(QTableWidget.NoEditTriggers);lay.addWidget(self.table)
        self.table.currentCellChanged.connect(self.select_issue)
        buttons=QHBoxLayout();lay.addLayout(buttons)
        for label,fn in [('สร้าง / ตรวจพรีวิว',self.generate),('บันทึก Analytical Snapshot',self.save),('ส่งออก JSON…',self.export)]:
            b=QPushButton(label);b.clicked.connect(lambda checked=False,fn=fn:panel.guard(fn));buttons.addWidget(b)
        saved=self.bound_scene.plugin_data.get(KEY)
        if saved:self.model=A.validate(saved);self.display()
    def check(self):
        if self.panel.app.scene is not self.bound_scene:raise ValueError('Document changed; reopen Analytical Model')
    def generate(self):
        self.check();self.model=A.build(sources(self.bound_scene),self.tolerance.value()/1000,self.bound_scene.plugin_data.get(KEY));self.display();self.panel.app.viewport.update()
    def display(self):
        m=self.model;live=current(self.bound_scene,m)
        self.info.setText(f"revision {m['revision']} • {len(m['members'])} ชิ้น → {len(m['elements'])} elements • {len(m['nodes'])} จุดต่อ • {len(m['components'])} กลุ่ม\n"+('แหล่งข้อมูลตรงกับโมเดล' if live else 'แหล่งข้อมูลเปลี่ยน: ต้องสร้างพรีวิวใหม่')+' • ยังใช้คำนวณไม่ได้\nแนวแกนคานอยู่กลางความสูงคาน; เชื่อมเฉพาะจุดปลายที่อยู่บนแนวแกนจริง ไม่ปรับ offset อัตโนมัติ')
        self.table.setRowCount(len(m['issues']))
        nodes={n['id']:n['xyz_m'] for n in m['nodes']};names={r['id']:r['name'] for r in m['members']}
        labels={'free_endpoint':'ปลายอิสระ / ยังไม่กำหนดรองรับ','near_joint':'จุดใกล้กันแต่ยังไม่เชื่อม','disconnected_components':'กลุ่มที่ไม่เชื่อมกัน','duplicate_axis':'แนวแกนซ้ำ','overlapping_axes':'แนวแกนทับซ้อน','interior_crossing':'ตัดกันกลางช่วงแต่ยังไม่เชื่อม'}
        for i,r in enumerate(m['issues']):
            xyz=nodes.get(r.get('node_id'))
            location=', '.join(f'{v:.4f}' for v in xyz)+' m' if xyz else ', '.join(names.get(uid,uid) for uid in r.get('members',[])) or str(r.get('count',''))
            for j,v in enumerate((labels.get(r['code'],r['code']),location,r['message'])):self.table.setItem(i,j,QTableWidgetItem(str(v)))
        self.focus=None
        self.table.resizeColumnsToContents()
    def select_issue(self,row,*args):
        self.focus=self.model['issues'][row] if self.model and 0<=row<len(self.model['issues']) else None
        self.panel.app.viewport.update()
    def reviewed(self):
        self.check()
        if self.model is None or not current(self.bound_scene,self.model):raise ValueError('Sources changed or preview missing; generate preview first')
        if abs(self.model['inspection_tolerance_m']-self.tolerance.value()/1000)>1e-12:raise ValueError('Tolerance changed; generate preview first')
        return A.validate(self.model)
    def save(self):
        self.panel.execute(SnapshotChange(self.bound_scene,self.reviewed()));self.display()
    def export(self):
        model=self.reviewed();path,_=QFileDialog.getSaveFileName(self,'ส่งออก Analytical JSON','Thai-BIM-analytical.json','JSON (*.json)')
        if path:write(path,model)
    def closeEvent(self,event):self.visible.setChecked(False);super().closeEvent(event)

def write(path,model):
    model=A.validate(model);path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);handle,name=tempfile.mkstemp(dir=path.parent,suffix='.json')
    try:
        with os.fdopen(handle,'w',encoding='utf-8') as f:json.dump(model,f,ensure_ascii=False,indent=2,allow_nan=False)
        os.replace(name,path)
    finally:
        if Path(name).exists():Path(name).unlink()

def overlay(panel,painter):
    d=getattr(panel,'analytical_dialog',None)
    if d is None or not d.isVisible() or not d.visible.isChecked() or not d.model or panel.app.scene is not d.bound_scene:return
    m=d.model;pts=np.asarray([n['xyz_m'] for n in m['nodes']],dtype=float);px,py,front=panel.app.world_to_pixels(pts);lookup={n['id']:i for i,n in enumerate(m['nodes'])}
    color=QColor('#f1b642' if current(panel.app.scene,m) else '#e85151');focus=d.focus or {}
    for e in m['elements']:
        painter.setPen(QPen(QColor('#e85151') if e['member_id'] in focus.get('members',[]) else color,2))
        a,b=lookup[e['node_i']],lookup[e['node_j']]
        if front[a] and front[b]:painter.drawLine(QPointF(float(px[a]),float(py[a])),QPointF(float(px[b]),float(py[b])))
    for i,n in enumerate(m['nodes']):
        painter.setPen(QPen(QColor('#e85151') if n['id']==focus.get('node_id') else color,3 if n['id']==focus.get('node_id') else 2))
        if front[i]:painter.drawEllipse(QPointF(float(px[i]),float(py[i])),4,4)

def open_dialog(panel):
    old=getattr(panel,'analytical_dialog',None)
    if old:old.close();old.deleteLater()
    d=AnalyticalDialog(panel);panel.analytical_dialog=d;d.show();return d
def install(panel):
    if getattr(panel,'_analytical_installed',False):return
    panel._analytical_installed=True
    from .builders import icon
    action=panel.toolbar.addAction(icon('Host'),'Analytical Model / แนวแกนคาน–เสา');action.triggered.connect(lambda checked=False:panel.guard(lambda:open_dialog(panel)))
    panel.button(panel.members,'Analytical Model / แนวแกนคาน–เสา',lambda:open_dialog(panel));panel.app.add_overlay(lambda vp,painter:overlay(panel,painter))
