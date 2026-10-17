"""Instance-only edits: preserve placement, identity, beam span and slab outline."""
import copy,json
from PySide6.QtWidgets import QLabel,QPushButton
from . import workflow as W
from .selected_geometry import editable,edit_spec
from .builders import BuilderDialog,icon

def spec(host,values):
    return edit_spec(host.ext['thai_bim'],values)

def token(host):return W.host_token(host),json.dumps(host.ext['thai_bim'].get('member_type'),sort_keys=True)

def command(scene,host,values,expected):
    from . import identity_issues,make_group,ExchangeGroups
    if host not in scene.groups or scene.selection!={host}:raise ValueError('Selection changed; read the selected member again')
    if identity_issues(scene):raise ValueError('Repair copied IDs before editing selected members')
    if token(host)!=expected:raise ValueError('Host or type changed; read the member again')
    result=spec(host,values);group=make_group(result,assembly=host.ext['thai_bim'].get('assembly',''),previous=host)
    group.name=host.name
    if group.ifc:group.ifc['name']=group.name
    group.layer=host.layer
    group.ext['thai_bim']['instance_dimensions']=copy.deepcopy(values)
    if result['kind']=='Stair':group.ext['thai_bim'].update(assembly_kind='rc-stair',assembly_params=copy.deepcopy(result['stair_params']))
    return ExchangeGroups(scene,replacements=[(host,group)]),group

class SelectedEditDialog(BuilderDialog):
    def __init__(self,panel):
        super().__init__(panel,'Place');self.setWindowTitle('Thai BIM — แก้ไขเฉพาะชิ้นที่เลือก');self.uid=None;self.bound_scene=None;self.expected=None
        self.label=QLabel('เลือกคอนกรีต Thai BIM หนึ่งชิ้น แล้วกดอ่านค่า');self.label.setWordWrap(True);self.form.addRow(self.label)
        self.button('อ่านชิ้นงานที่เลือก / โหลดค่าใหม่',self.read_host)
        self.note('แก้เฉพาะชิ้นนี้ ไม่แก้คลังชนิดหรือชิ้นอื่น\nช่องตัวเลข: คงแนวคาน/ขอบพื้น • เปลี่ยนรูปทรงด้วยปุ่มแก้ในโมเดล\nฐาน–เสา: คงศูนย์กลางและระดับฐาน / บันไดตรง: คงจุดเริ่มและทิศขึ้น\nหลังแก้คอนกรีต ต้องตรวจเหล็กและ Analytical Model ใหม่')
        self.edit_fields={};self.widgets=[]
        save=QPushButton('บันทึกขนาดเฉพาะชิ้นจากพรีวิว (Undo ได้)');save.clicked.connect(lambda checked=False:panel.guard(self.apply));self.layout().addWidget(save)
        steel=QPushButton('อ่านชิ้นนี้ในหน้าต่างเหล็ก / Host review');steel.clicked.connect(lambda checked=False:panel.guard(self.rebar));self.layout().addWidget(steel)
        for text,opening in [('แก้ปลายคาน / ขอบพื้น / ชานพัก ในโมเดล',False),('เพิ่มช่องเปิดพื้น: คลิกสองมุม',True)]:
            b=QPushButton(text);b.clicked.connect(lambda checked=False,opening=opening:panel.guard(lambda:self.shape(opening)));self.layout().addWidget(b)
    def shape(self,opening=False):
        from .shape_edit import start
        self.host();return start(self.panel,opening)
    def host(self):
        scene=self.panel.app.scene
        if self.uid is None:raise ValueError('เลือกชิ้นคอนกรีต Thai BIM หนึ่งชิ้น แล้วกดอ่านค่า')
        if scene is not self.bound_scene:raise ValueError('Document changed; read selected member again')
        host=next((g for g in scene.groups if g.uid==self.uid),None)
        if host is None or scene.selection!={host}:raise ValueError('Select the member originally read; or read a new selected member')
        if token(host)!=self.expected:raise ValueError('Selected geometry / type changed; read the member again')
        return host
    def read_host(self):
        from . import identity_issues
        self.timer.stop()
        scene=self.panel.app.scene
        if len(scene.selection)!=1:raise ValueError('Select exactly one Thai BIM concrete member')
        if identity_issues(scene):raise ValueError('Repair copied IDs before editing selected members')
        host=next(iter(scene.selection));expected=token(host)
        for w in self.widgets:self.form.removeRow(w)
        self.widgets=[];self.fields={};self.edit_fields={}
        self.uid=host.uid;self.bound_scene=scene;self.expected=expected
        rec=host.ext['thai_bim'];p=rec.get('params') or rec.get('stair_params');row=rec.get('member_type')
        self.label.setText(host.name+'\n'+('ชนิด '+row['code']+' revision '+str(row['revision']) if row else 'ชิ้นงานไม่มีชนิดในคลัง')+' • ID '+rec['id'][:8])
        labels={'width':'กว้าง / หน้าตัด local X (m)','depth':'กว้างหน้าตัด local Y (m)','height':'สูง / หนาคอนกรีต (m)','going':'ลูกนอน (m)','risers':'จำนวนลูกตั้ง','waist':'ความหนาท้องบันได (m)'}
        if rec['kind']=='Stair':labels.update(width='ความกว้างบันได (m)',height='สูงระหว่างชั้น (m)')
        if rec['kind']=='Beam':labels['height']='ความสูงหน้าตัดคาน (m)'
        if rec['kind']=='Slab':labels['height']='ความหนาพื้น (m)'
        for k in editable(rec['kind']):
            w=self.field(k,labels[k],p[k],k=='risers',2 if k=='risers' else .002,60 if k=='risers' else 100);self.widgets.append(w);self.edit_fields[k]=w
        self.preview()
    def params(self):return {k:w.value() for k,w in self.edit_fields.items()}
    def specs(self):return [spec(self.host(),self.params())]
    def preview(self):
        try:
            host=self.host();specs=self.specs();self.visual.display(W.P.world_specs(specs,W.pose(host)))
            before=host.ext['thai_bim']['volume_m3'];after=specs[0]['quantity']
            self.output.setPlainText(f'พรีวิวเฉพาะ {host.name}\nปริมาณคอนกรีต {before:.4f} → {after:.4f} m³ • ยังไม่บันทึก\nคง ID, ตำแหน่ง, การหมุน และขอบเขต/แนววางเดิม • เหล็กเดิมต้องตรวจ Host ใหม่')
        except Exception as error:self.visual.invalid(error);self.output.setPlainText(str(error))
    def apply(self):
        self.timer.stop()
        host=self.host();self.preview()
        if self.visual.error:raise ValueError(self.visual.error)
        cmd,group=command(self.bound_scene,host,self.params(),self.expected);self.panel.execute(cmd);self.read_host()
        self.output.appendPlainText('บันทึกเฉพาะชิ้นนี้แล้ว • Undo ได้ • ชิ้นอื่นและคลังชนิดไม่เปลี่ยน')
    def rebar(self):
        if self.host().ext['thai_bim']['kind']=='Slab':
            from .slab_ui import open_dialog
            self.rebar_dialog=open_dialog(self.panel);return
        from .builders import RebarDialog
        old=getattr(self,'rebar_dialog',None)
        if old:old.close();old.deleteLater()
        d=RebarDialog(self.panel);self.rebar_dialog=d;d.read_host();d.show()

def open_dialog(panel):
    if len(panel.app.scene.selection)==1 and ((next(iter(panel.app.scene.selection)).ext or {}).get('thai_bim',{}).get('stair_params') or {}).get('stair_schema')==2:
        from .stairs_ui import open_dialog as advanced_stair
        return advanced_stair(panel)
    old=getattr(panel,'selected_edit_dialog',None)
    if old:old.close();old.deleteLater()
    d=SelectedEditDialog(panel);panel.selected_edit_dialog=d
    if len(panel.app.scene.selection)==1:d.read_host()
    d.show();return d
def install(panel):
    if getattr(panel,'_selected_edit_installed',False):return
    panel._selected_edit_installed=True
    action=panel.toolbar.addAction(icon('Place'),'แก้ไขเฉพาะชิ้นที่เลือก / Instance dimensions');action.triggered.connect(lambda checked=False:panel.guard(lambda:open_dialog(panel)))
    panel.button(panel.members,'แก้ไขเฉพาะชิ้นที่เลือก / Instance dimensions',lambda:open_dialog(panel))
