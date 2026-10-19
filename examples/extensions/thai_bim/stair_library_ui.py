"""Project stair library embedded in the illustrated stair editor."""
import copy
from core.history import Command
from PySide6.QtWidgets import QComboBox,QLineEdit,QLabel,QHBoxLayout,QPushButton,QFileDialog
from . import stair_catalogue as C

def library(scene):
    value=(scene.plugin_data.get('thai_bim') or {}).get('advanced_stair_library')
    return C.validate(value) if value is not None else C.defaults()

def shared_path():
    from core.extensions import user_plugins_dir
    return user_plugins_dir().parent/'thai_bim-stair-library.json'

class LibraryChange(Command):
    def __init__(self,scene,data):
        self.scene=scene;self.before=copy.deepcopy(scene.plugin_data);self.after=copy.deepcopy(self.before)
        self.after.setdefault('thai_bim',{})['advanced_stair_library']=C.validate(data)
    def do(self,scene):
        if scene is not self.scene or scene.plugin_data!=self.before:raise ValueError('Project changed; refresh stair library')
        scene.plugin_data=copy.deepcopy(self.after);scene.version+=1
    def undo(self,scene):scene.plugin_data=copy.deepcopy(self.before);scene.version+=1

def tag(host,row,params,rebar):
    r=host.ext['thai_bim'];r['stair_rebar_preset']=copy.deepcopy(rebar)
    if row is None:
        r.pop('stair_type',None);r.pop('stair_type_overrides',None);return
    row=C.snapshot(row);r['stair_type']=row
    r['stair_type_overrides']={k:copy.deepcopy(v) for k,v in (('params',params),('rebar',rebar)) if v!=row[k]}
    host.name='TBIM Stair '+row['code']+' '+r['id'][:8]
    if host.ifc:host.ifc['name']=host.name

class StairLibrary:
    def __init__(self,dialog):
        self.dialog=dialog;self.panel=dialog.panel;self.scene=self.panel.app.scene;self.source=None
        self.pick=QComboBox();self.pick.setMinimumContentsLength(18);self.pick.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.code=QLineEdit();self.name=QLineEdit();self.code.setMaxLength(30);self.name.setMaxLength(80)
        dialog.form.addRow('คลังชนิดบันได RC',self.pick);dialog.form.addRow('รหัส เช่น ST-01',self.code);dialog.form.addRow('ชื่อชนิด',self.name)
        self.info=QLabel('เลือกชนิดเพื่อโหลดพรีวิว • ยังไม่สร้างหรือเปลี่ยนชิ้นงาน');self.info.setWordWrap(True);dialog.form.addRow(self.info)
        for actions in [[('ใหม่ / ไม่ผูกชนิด',self.new),('สำเนาชนิด',self.duplicate),('บันทึกชนิด',self.save),('ลบชนิด',self.remove)],
                        [('รีเฟรชคลัง',self.refresh),('นำเข้า JSON…',self.import_file),('ส่งออก JSON…',self.export_file)],
                        [('บันทึกคลังกลาง',self.save_shared),('อ่านคลังกลาง',self.load_shared)]]:
            row=QHBoxLayout();dialog.form.addRow(row)
            for label,fn in actions:
                button=QPushButton(label);button.clicked.connect(lambda checked=False,fn=fn:self.panel.guard(fn));row.addWidget(button)
        self.pick.activated.connect(lambda i:self.panel.guard(lambda:self.load_index(i)))
        self.refresh()
    def check_scene(self):
        if self.panel.app.scene is not self.scene:raise ValueError('Document changed; reopen Stair dialog')
    def refresh(self):
        self.check_scene();self.rows=library(self.scene)['types'];self.pick.blockSignals(True);self.pick.clear();self.pick.addItem('Custom / ไม่ผูกชนิด')
        for r in self.rows:self.pick.addItem(r['code']+' • '+r['name']+' • '+r['params']['layout']+' • r'+str(r['revision']))
        index=next((i+1 for i,r in enumerate(self.rows) if r==self.source),0)
        if self.source and not index:
            self.pick.addItem(f"ค่าที่อ่าน: {self.source['code']} • {self.source['name']} • r{self.source['revision']} (snapshot)")
            index=len(self.rows)+1;self.pick.model().item(index).setEnabled(False)
        self.pick.setCurrentIndex(index);self.pick.blockSignals(False)
    def read_snapshot(self,host):
        row=host.ext['thai_bim'].get('stair_type');self.source=C.snapshot(row) if row else None
        self.code.setText(row['code'] if row else '');self.name.setText(row['name'] if row else '');self.refresh()
        self.status('ค่าจากชิ้นงาน • การแก้คลังไม่เปลี่ยนชิ้นงานอื่น')
    def status(self,text):
        self.info.setText(text+(f" • {self.source['code']} r{self.source['revision']}" if self.source else ''))
    def new(self):
        self.check_scene();self.source=None;self.code.clear();self.name.clear();self.pick.setCurrentIndex(0);self.dialog.reviewed=None
        self.status('ใช้ค่าพรีวิวปัจจุบันเป็น Custom; กรอกรหัสและชื่อแล้วบันทึกชนิดใหม่ได้')
    def duplicate(self):
        self.check_scene();code=self.code.text();name=self.name.text();self.new();self.code.setText(code+'-copy');self.name.setText(name+' copy')
    def load_index(self,index):
        self.check_scene()
        if index==0:self.new();return
        if not 1<=index<=len(self.rows):raise ValueError('This is the stored Host snapshot; select a current library row to load its latest revision')
        expected=self.rows[index-1];current=next((r for r in library(self.scene)['types'] if r['id']==expected['id']),None)
        if current!=expected:raise ValueError('Library changed; refresh and select current type')
        self.source=C.snapshot(current);self.code.setText(current['code']);self.name.setText(current['name'])
        self.dialog.load_values(current['params'],current['rebar']);self.dialog.reviewed=None;self.dialog.preview()
        self.status('โหลดพรีวิวแล้ว • XYZ/ทิศวางเดิม • ใช้สร้างใหม่ หรือกดอัปเดตเฉพาะ Host ที่อ่าน')
    def model_source(self):
        self.check_scene()
        if self.source and (self.code.text().strip()!=self.source['code'] or self.name.text().strip()!=self.source['name']):raise ValueError('Save edited type name/code, or choose Custom before creating/updating concrete')
        return copy.deepcopy(self.source)
    def save(self):
        self.check_scene();data=library(self.scene);source=self.source
        if source and next((r for r in data['types'] if r['id']==source['id']),None)!=source:raise ValueError('Saved type changed or was deleted; refresh and load it, or duplicate as a new type')
        row=C.stair_type(self.code.text(),self.name.text(),self.dialog.geometry(),self.dialog.rebar(),source['id'] if source else None,source['revision']+1 if source else 1)
        self.panel.execute(LibraryChange(self.scene,C.upsert(data,row)));self.source=row;self.code.setText(row['code']);self.name.setText(row['name']);self.refresh();self.dialog.reviewed=None
        self.status('บันทึกชนิดพร้อมเหล็กแล้ว • ชิ้นงานเดิมไม่เปลี่ยน • Undo ได้')
    def remove(self):
        self.check_scene();data=library(self.scene)
        if not self.source or next((r for r in data['types'] if r['id']==self.source['id']),None)!=self.source:raise ValueError('Select a current saved type before deleting')
        data['types']=[r for r in data['types'] if r['id']!=self.source['id']];self.panel.execute(LibraryChange(self.scene,data));self.new();self.refresh()
        self.status('ลบจากคลังแล้ว • ชิ้นงานและสำเนาค่าชนิดเดิมยังอยู่ • Undo ได้')
    def import_path(self,path):
        self.check_scene();data=C.read(path);self.panel.execute(LibraryChange(self.scene,data));self.new();self.refresh();self.status('แทนคลังโครงการจาก JSON แล้ว • ชิ้นงานเดิมไม่เปลี่ยน • Undo ได้')
    def import_file(self):
        self.check_scene();path,_=QFileDialog.getOpenFileName(self.dialog,'นำเข้าแทนคลังบันไดโครงการ (Undo ได้)','','JSON (*.json)')
        if path:self.import_path(path)
    def export_file(self):
        self.check_scene();path,_=QFileDialog.getSaveFileName(self.dialog,'ส่งออกคลังบันได','','JSON (*.json)')
        if path:C.write(path,library(self.scene));self.status('ส่งออกคลังบันไดแล้ว')
    def save_shared(self):self.check_scene();C.write(shared_path(),library(self.scene));self.status('บันทึกคลังกลาง: '+str(shared_path()))
    def load_shared(self):self.import_path(shared_path())
