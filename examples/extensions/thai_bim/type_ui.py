"""Project member library, portable shared JSON and selected-instance type edits."""
import copy,uuid
from pathlib import Path
from core.history import Command
from PySide6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QFormLayout,QComboBox,QLineEdit,QLabel,QPushButton,QTableWidget,QTableWidgetItem,QDoubleSpinBox,QSpinBox,QFileDialog
from . import catalogue as C,path_geometry as G,engine as E

def library(scene):return C.validate((scene.plugin_data.get('thai_bim') or {}).get('member_library') or C.defaults())
def shared_path():
    from core.extensions import user_plugins_dir
    return user_plugins_dir().parent/'thai_bim-member-library.json'

class LibraryChange(Command):
    def __init__(self,scene,data):
        self.scene=scene;self.before=copy.deepcopy(scene.plugin_data);self.after=copy.deepcopy(self.before)
        self.after.setdefault('thai_bim',{})['member_library']=C.validate(data)
    def do(self,scene):
        if scene is not self.scene or scene.plugin_data!=self.before:raise ValueError('Project changed; read library again')
        scene.plugin_data=copy.deepcopy(self.after);scene.version+=1
    def undo(self,scene):scene.plugin_data=copy.deepcopy(self.before);scene.version+=1

def tag(group,row):
    if row is None:return
    group.ext['thai_bim']['member_type']=C.snapshot(row)
    params=group.ext['thai_bim'].get('params') or group.ext['thai_bim'].get('stair_params') or {}
    variable={'Beam':{'width'},'Slab':{'width','depth'}}.get(row['kind'],set())
    group.ext['thai_bim']['member_type_overrides']={k:params[k] for k,v in row['params'].items() if k not in variable and k in params and abs(params[k]-v)>1e-8}
    group.name='TBIM '+row['kind']+' '+row['code']+' '+group.ext['thai_bim']['id'][:8]
    if group.ifc:group.ifc['name']=group.name

def update_selected(scene,row):
    from . import make_group,ExchangeGroups,identity_issues
    if identity_issues(scene):raise ValueError('Resolve copied or missing Thai BIM IDs before type updates')
    from .workflow import host_token,pose
    from . import placement as P,structures as S
    selected=[g for g in scene.selection if g in scene.groups]
    if len(selected)!=1:raise ValueError('Select exactly one Thai BIM concrete member')
    host=selected[0];host_token(host);r=host.ext['thai_bim'];kind=r['kind']
    row=C.snapshot(row)
    if row['kind']!=kind:raise ValueError('Selected member and type must have the same kind')
    p=copy.deepcopy(r.get('params') or r.get('stair_params'));dims=row['params']
    if kind=='Stair' and p.get('stair_schema')==2:raise ValueError('Advanced stair types are edited in Stair / landing dialog; legacy straight types cannot replace them')
    if kind=='Stair':
        sp=S.stair_spec(x=p['x'],y=p['y'],z=p['z'],**dims)
    elif p.get('shape')=='polygon':
        # Preserve exact outline and pose; update thickness only.
        sp,_=G.polygon(p['footprint'],p['z'],dict(height=dims['height']))
        # Footprint is local to its first point; existing toolkit footprints start at zero.
    else:
        if kind in ('Footing','Column'):
            p['x']+=(p['width']-dims['width'])/2;p['y']+=(p['depth']-dims['depth'])/2
            p.update(dims)
        elif kind=='Beam':
            if r.get('placement_mode')=='beam':p['y']=-dims['depth']/2
            p.update(depth=dims['depth'],height=dims['height'])
        else:p['height']=dims['height']
        sp=E.box_spec(kind,**{k:p[k] for k in ('x','y','z','width','depth','height')})
    group=make_group(sp,previous=host);tag(group,row)
    if kind=='Stair':
        group.ext['thai_bim'].update(assembly_kind='rc-stair',assembly_params=copy.deepcopy(sp['stair_params']))
    group.ext['thai_bim']['placement_mode']=r.get('placement_mode','point')
    return ExchangeGroups(scene,replacements=[(host,group)]),group

class TypeDialog(QDialog):
    def __init__(self,panel):
        super().__init__(panel.app.window);self.panel=panel;self.bound_scene=panel.app.scene;self.uid=None;self.revision=0;self.recipe=None
        self.setWindowTitle('Thai BIM — คลังชนิดชิ้นงาน');self.resize(1120,720)
        main=QVBoxLayout(self);row=QHBoxLayout();main.addLayout(row)
        self.table=QTableWidget(0,4);self.table.setHorizontalHeaderLabels(['ชนิด','รหัส','ชื่อ','Revision']);self.table.setEditTriggers(QTableWidget.NoEditTriggers);self.table.setSelectionBehavior(QTableWidget.SelectRows)
        row.addWidget(self.table,1);right=QVBoxLayout();row.addLayout(right,1);form=QFormLayout();right.addLayout(form)
        self.kind=QComboBox();self.kind.addItems(C.KINDS);form.addRow('ชนิดชิ้นงาน',self.kind)
        self.code=QLineEdit();self.name=QLineEdit();form.addRow('รหัสชนิด เช่น F1/B1',self.code);form.addRow('ชื่อ',self.name)
        self.params_form=QFormLayout();right.addLayout(self.params_form);self.fields={}
        from .builders import AssemblyPreview
        self.visual=AssemblyPreview();self.visual.setMinimumSize(380,240);right.addWidget(self.visual,1)
        self.info=QLabel('ค่าหน่วยเมตร • รหัสชนิดแยกจาก ID ของแต่ละชิ้น\nคานใช้ความยาวจากสองจุด; พื้นใช้ขอบเขตที่คลิก\nแก้คลังไม่เปลี่ยนชิ้นเดิม; ใช้ปุ่มอัปเดตเฉพาะชิ้นที่เลือก\nรายละเอียดเหล็กประจำชนิด → บันทึกชนิด → อ่าน Host → ตรวจพรีวิวก่อนสร้าง');self.info.setWordWrap(True);main.addWidget(self.info)
        recipes=QHBoxLayout();main.addLayout(recipes)
        self.recipe_info=QLabel();recipes.addWidget(self.recipe_info)
        self.button(recipes,'แก้รายละเอียดเหล็ก / ดูพรีวิว…',self.edit_recipe)
        self.button(recipes,'ล้างรายละเอียดเหล็กจากชนิด',self.clear_recipe)
        buttons=QHBoxLayout();main.addLayout(buttons)
        for label,fn in [('ใหม่',self.new),('ทำสำเนา',self.duplicate),('บันทึกชนิดในโครงการ',self.save),('ลบจากคลัง',self.remove),('วางชนิดนี้…',self.place),('อัปเดตเฉพาะชิ้นที่เลือก',self.apply)]:self.button(buttons,label,fn)
        files=QHBoxLayout();main.addLayout(files)
        for label,fn in [('นำเข้าคลัง JSON (แทนคลังโครงการ)',self.import_file),('ส่งออกคลัง JSON…',self.export_file),('บันทึกเป็นคลังกลางในเครื่อง',self.save_shared),('อ่านคลังกลางแทนคลังโครงการ',self.load_shared)]:self.button(files,label,fn)
        self.kind.currentTextChanged.connect(self.configure);self.table.cellClicked.connect(lambda r,c:self.load_row(r))
        self.code.textChanged.connect(self.preview);self.name.textChanged.connect(self.preview)
        self.configure();self.refresh();self.new()
    def button(self,layout,label,fn):
        b=QPushButton(label);b.clicked.connect(lambda checked=False:self.panel.guard(fn));layout.addWidget(b)
    def check_scene(self):
        if self.panel.app.scene is not self.bound_scene:raise ValueError('Document changed; reopen the type library')
    def configure(self):
        while self.params_form.rowCount():self.params_form.removeRow(0)
        self.fields={};kind=self.kind.currentText()
        if self.recipe is not None and getattr(self,'recipe_kind',kind)!=kind:self.recipe=None
        self.recipe_kind=kind
        if hasattr(self,'recipe_info'):self.recipe_status()
        labels={'width':'กว้าง X / ระยะวิ่งตัวอย่าง (m)','depth':'กว้าง Y (m)','height':'สูง / ความหนา / สูงระหว่างชั้น (m)','going':'ลูกนอน (m)','risers':'จำนวนลูกตั้ง','waist':'ความหนาท้องบันได (m)'}
        for key,value in C.DEFAULTS[kind].items():
            w=QSpinBox() if key=='risers' else QDoubleSpinBox()
            if key=='risers':w.setRange(2,60)
            else:w.setDecimals(3);w.setRange(.002,100);w.setSingleStep(.05)
            w.setValue(value);w.valueChanged.connect(self.preview);self.fields[key]=w;self.params_form.addRow(labels[key],w)
        self.preview()
    def row(self):
        return C.member_type(self.kind.currentText(),self.code.text(),self.name.text(),{k:w.value() for k,w in self.fields.items()},self.uid,self.revision+1,self.recipe)
    def preview(self,*args):
        try:
            row=self.row();p=row['params'];kind=row['kind']
            from . import placement as P,structures as S
            self.visual.display([S.stair_spec(**p) if kind=='Stair' else P.member_spec(kind,**p)])
        except (ValueError,AttributeError) as error:
            if hasattr(self,'visual'):self.visual.invalid(str(error))
    def refresh(self):
        self.check_scene();self.rows=library(self.bound_scene)['types'];self.table.setRowCount(len(self.rows))
        for i,r in enumerate(self.rows):
            for j,k in enumerate(('kind','code','name','revision')):self.table.setItem(i,j,QTableWidgetItem(str(r[k])))
        self.table.resizeColumnsToContents()
    def new(self):
        self.uid=None;self.revision=0;self.recipe=None;self.recipe_status();self.kind.setEnabled(True);self.code.clear();self.name.clear();self.configure()
    def load_row(self,index):
        self.check_scene();r=self.rows[index];self.uid=r['id'];self.revision=r['revision'];self.recipe=copy.deepcopy(r.get('rebar'));self.recipe_kind=r['kind'];self.recipe_status();self.kind.setCurrentText(r['kind']);self.kind.setEnabled(False)
        self.code.setText(r['code']);self.name.setText(r['name'])
        for k,w in self.fields.items():w.setValue(r['params'][k])
        self.preview()
    def duplicate(self):
        self.uid=None;self.revision=0;self.kind.setEnabled(True);self.code.setText(self.code.text()+'-copy');self.name.setText(self.name.text()+' copy')
    def save(self):
        self.check_scene();data=library(self.bound_scene)
        old=next((r for r in data['types'] if r['id']==self.uid),None)
        if self.uid and (old is None or old['revision']!=self.revision):raise ValueError('Type changed since read; select it again')
        row=self.row();self.panel.execute(LibraryChange(self.bound_scene,C.upsert(data,row)));self.refresh();self.load_row(next(i for i,r in enumerate(self.rows) if r['id']==row['id']))
    def remove(self):
        self.check_scene();data=library(self.bound_scene);old=next((r for r in data['types'] if r['id']==self.uid),None)
        if not old or old['revision']!=self.revision:raise ValueError('Select a current saved type')
        data['types']=[r for r in data['types'] if r['id']!=self.uid];self.panel.execute(LibraryChange(self.bound_scene,data));self.refresh();self.new()
    def saved(self):
        self.check_scene();r=next((r for r in library(self.bound_scene)['types'] if r['id']==self.uid),None)
        if not r or C.member_type(r['kind'],r['code'],r['name'],r['params'],r['id'],r['revision'],r.get('rebar'))!=C.member_type(self.kind.currentText(),self.code.text(),self.name.text(),{k:w.value() for k,w in self.fields.items()},self.uid,self.revision,self.recipe):raise ValueError('Save this type before use; or select its saved row again')
        return r
    def recipe_status(self):
        self.recipe_info.setText('มีรายละเอียดเหล็ก • ยังไม่สร้างโมเดล' if self.recipe is not None else 'ยังไม่มีรายละเอียดเหล็ก')
    def clear_recipe(self):
        self.check_scene();self.recipe=None;self.recipe_status();self.preview()
    def edit_recipe(self):
        self.check_scene();row=self.row()
        from .builders import RebarDialog
        # Bind to the exact edit form. A modeless editor cannot overwrite another row.
        expected=copy.deepcopy(row);bound=self.bound_scene
        def accept(recipe):
            self.check_scene()
            current=self.row();current['id']=expected['id'] if self.uid is None else current['id']
            if self.bound_scene is not bound or current!=expected:raise ValueError('Type form changed; reopen its reinforcement editor')
            self.recipe=copy.deepcopy(recipe);self.recipe_status();self.preview()
        old=getattr(self,'recipe_dialog',None)
        if old:old.close();old.deleteLater()
        self.recipe_dialog=RebarDialog(self.panel,recipe_type=row,accept_recipe=accept);self.recipe_dialog.show()
    def place(self):
        row=self.saved();from .multi_place import open_placement
        open_placement(self.panel,row);self.hide()
    def apply(self):
        row=self.saved();cmd,group=update_selected(self.bound_scene,row);self.panel.execute(cmd)
        self.info.setText('อัปเดตเฉพาะชิ้นที่เลือกแล้ว • ชิ้นอื่นไม่เปลี่ยน • เหล็กเดิมต้องตรวจ Host ใหม่')
    def import_file(self):
        self.check_scene();path,_=QFileDialog.getOpenFileName(self,'นำเข้าคลัง JSON แทนคลังโครงการ','','JSON (*.json)')
        if path:self.panel.execute(LibraryChange(self.bound_scene,C.read(path)));self.refresh();self.new()
    def export_file(self):
        self.check_scene();path,_=QFileDialog.getSaveFileName(self,'ส่งออกคลังชนิด','Thai-BIM-types.json','JSON (*.json)')
        if path:C.write(path,library(self.bound_scene))
    def save_shared(self):self.check_scene();C.write(shared_path(),library(self.bound_scene));self.info.setText('บันทึกคลังกลาง: '+str(shared_path()))
    def load_shared(self):self.check_scene();self.panel.execute(LibraryChange(self.bound_scene,C.read(shared_path())));self.refresh();self.new()

def open_library(panel):
    old=getattr(panel,'type_dialog',None)
    if old:old.close();old.deleteLater()
    d=TypeDialog(panel);panel.type_dialog=d;d.show();return d

def install(panel):
    if getattr(panel,'_member_types_installed',False):return
    panel._member_types_installed=True
    panel.button(panel.members,'คลังชนิดบันได RC ทุกทรง + ชุดเหล็ก…',lambda:__import__(__package__+'.stairs_ui',fromlist=['open_dialog']).open_dialog(panel))
    from .builders import icon
    for key,label,fn in [('Project','คลังชนิดชิ้นงาน / F C B S ST',lambda:open_library(panel)),('Place','คานสองจุด / พื้น / บันไดคลิกวาง',lambda:__import__(__package__+'.multi_place',fromlist=['open_placement']).open_placement(panel))]:
        action=panel.toolbar.addAction(icon(key),label);action.setToolTip(label);action.triggered.connect(lambda checked=False,fn=fn:panel.guard(fn))
        panel.button(panel.members,label,fn)
