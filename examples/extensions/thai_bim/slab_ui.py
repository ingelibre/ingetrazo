"""Explicit Host review for polygon RC mats and precast topping detailing."""
import copy,json
from PySide6.QtWidgets import QComboBox,QCheckBox,QLabel,QLineEdit,QFormLayout,QHBoxLayout,QPushButton
from . import slab_rebar as SR,workflow as W,engine as E,steel as C
from .builders import BuilderDialog

def key(host,params):return W.host_token(host),json.dumps(params,sort_keys=True),json.dumps(host.ext['thai_bim'].get('member_type'),sort_keys=True)
def review(scene,host,params):
    from . import identity_issues
    if host not in scene.groups or scene.selection!={host}:raise ValueError('Select the Slab originally read')
    if identity_issues(scene):raise ValueError('Repair copied / missing Thai BIM IDs first')
    token=key(host,params)
    if host.ext['thai_bim']['kind']!='Slab':raise ValueError('Select one concrete Slab')
    bars=[g for g in scene.groups if (g.ext or {}).get('thai_bim',{}).get('host_uid')==host.uid]
    if any(not W.bar_unchanged(g) for g in bars):raise ValueError('Existing bars changed / copied / independently moved; resolve them before regeneration')
    return SR.generate(host.ext['thai_bim']['params'],params),token
def command(scene,host,params,expected):
    from . import reconcile_specs
    specs,current=review(scene,host,params)
    if current!=expected:raise ValueError('Host / settings / type changed after review; review again')
    rec=host.ext['thai_bim'];pose=W.pose(host)
    return reconcile_specs(scene,specs,'rebar-'+host.uid,dict(host_uid=host.uid,host_hash=current[0][2],host_pose=pose,bar_pose=pose,
        host_params=copy.deepcopy(rec['params']),host_kind='Slab',rebar_params=None,rebar_recipe_source=None,
        slab_rebar_schema=1,slab_rebar_params=copy.deepcopy(params)),rebar_host=host)

class SlabDialog(BuilderDialog):
    def __init__(self,panel):
        super().__init__(panel,'Rebar');self.setWindowTitle('Thai BIM — เหล็กพื้น / ไวร์เมช / โดเวล');self.host_uid=None;self.bound_scene=None;self.reviewed=None
        self.form.setRowWrapPolicy(QFormLayout.WrapLongRows)
        self.label=QLabel('เลือกพื้น Thai BIM หนึ่งชิ้น แล้วอ่าน Host');self.label.setWordWrap(True);self.form.addRow(self.label)
        self.button('อ่านพื้นที่เลือก / โหลดรายละเอียดเดิม',self.read_host)
        self.mode=self.combo('ระบบพื้น',SR.MODES);self.axis=self.combo('ทิศพาดหลัก local Host',('X','Y'))
        self.mats=self.combo('ชั้นเหล็ก RC',('Bottom','Bottom + Top'))
        self.representation=self.combo('รูปแบบโมเดล',('Centreline','Lightweight','Full'))
        self.note('ค่าตั้งต้นเป็นตัวอย่างสำหรับพรีวิว ต้องปรับตามแบบก่อนสร้าง\nOne-way: เหล็กหลักตามทิศพาด + เหล็กกระจายตั้งฉาก\nTwo-way: เหล็ก A ตามทิศพาด + B ตั้งฉาก กำหนดขนาด/ระยะแยกกัน\nระยะหุ้มวัดถึงผิวเหล็ก; A และ B วางคนละระดับสัมผัสกัน')
        self.defaults=SR.defaults();self.steels={}
        self.numeric('cover','ระยะหุ้ม RC / mesh (mm)')
        for role,text in (('a','A / เหล็กหลัก'),('b','B / เหล็กกระจาย')):
            self.numeric('diameter_'+role,text+' ขนาด custom (mm)')
            self.numeric('spacing_'+role,text+' ระยะสูงสุด (mm)')
            self.steel_picker(role,text)
        self.numeric('topping','ความหนา topping ภายในส่วนบนของ Host (mm)')
        self.wire_name=QLineEdit(self.defaults['wire_name']);self.form.addRow('ชื่อ / รุ่นไวร์เมช',self.wire_name);self.wire_name.textChanged.connect(lambda _:self.timer.start())
        for role in ('a','b'):
            self.numeric('wire_'+role,'ไวร์เมช '+role.upper()+' เส้นผ่านศูนย์กลาง (mm)')
            self.numeric('wire_spacing_'+role,'ไวร์เมช '+role.upper()+' ระยะสูงสุด (mm)')
        self.dowels=QCheckBox('สร้างโดเวลปลายพื้นสำเร็จ');self.form.addRow(self.dowels);self.dowels.toggled.connect(lambda _:self.timer.start())
        self.ends=self.combo('ปลายตามทิศพาด',('Both','Start','End'));self.shape=self.combo('รูปโดเวล',('Straight','L'))
        for k,label in [('dowel_diameter','ขนาดโดเวล custom'),('dowel_spacing','ระยะโดเวลสูงสุด'),('dowel_cover','ระยะหุ้มใต้โดเวลใน topping'),('dowel_embed','ระยะฝังเข้าพื้น'),('dowel_extension','ระยะยื่นนอกพื้นเข้าแนวรองรับ'),('dowel_leg','ขาตั้ง L ขึ้นด้านบน'),('dowel_radius','รัศมีดัดภายใน')]:self.numeric(k,label+' (mm)')
        self.steel_picker('dowel','โดเวล')
        self.note('Precast: Host เป็นความหนารวมเดิม; ไม่สร้างคอนกรีต topping ซ้ำ\nMesh เป็นเส้นสุทธิ ไม่รวมทาบ เศษ หรือจำนวนแผ่นสั่งซื้อ\nโดเวลรุ่นนี้รองรับ Host สี่เหลี่ยม; ไม่มีการเลือกคานรองรับอัตโนมัติ\nระยะฝัง/ยื่น/ดัดเป็นรายละเอียดจากแบบ ไม่มีการตรวจแรงหรือระยะพัฒนา\nยังไม่สร้างแผ่นพื้นสำเร็จแบ่งชิ้น ลวดอัดแรง หรือเหล็กเสริมพิเศษเหนือรองรับ')
        footer=QHBoxLayout();self.layout().addLayout(footer)
        for text,fn in [('ตรวจ Host + ยืนยันพรีวิวก่อนสร้าง',self.review),('สร้าง / อัปเดตเหล็กพื้นจากพรีวิวที่ตรวจแล้ว',self.build)]:
            button=QPushButton(text);button.clicked.connect(lambda checked=False,fn=fn:panel.guard(fn));footer.addWidget(button)
        self.mode.currentIndexChanged.connect(self.enable_fields);self.dowels.toggled.connect(self.enable_fields);self.shape.currentIndexChanged.connect(self.enable_fields);self.enable_fields()
    def enable_fields(self,*_):
        precast=self.mode.currentText()=='Precast';dowels=precast and self.dowels.isChecked()
        self.mats.setEnabled(not precast);self.dowels.setEnabled(precast);self.wire_name.setEnabled(precast);self.ends.setEnabled(dowels);self.shape.setEnabled(dowels)
        for k,w in self.fields.items():
            if k.startswith('wire_') or k=='topping':enabled=precast
            elif k.startswith('dowel_'):enabled=dowels and (k not in ('dowel_leg','dowel_radius') or self.shape.currentText()=='L')
            elif k in ('diameter_a','diameter_b','spacing_a','spacing_b'):enabled=not precast
            else:enabled=True
            if k.startswith('diameter_') or k=='dowel_diameter':
                role='dowel' if k=='dowel_diameter' else k[-1];combo,records=self.steels[role];enabled=enabled and records[combo.currentIndex()] is None
            w.setEnabled(enabled)
        for role,(w,_) in self.steels.items():w.setEnabled(dowels if role=='dowel' else not precast)
    def combo(self,label,items):
        w=QComboBox();w.setMinimumContentsLength(15);w.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon);w.addItems(items);w.currentIndexChanged.connect(lambda _:self.timer.start());self.form.addRow(label,w);return w
    def numeric(self,key,label):self.field(key,label,self.defaults[key]*1000,minimum=0,maximum=3000).setDecimals(3)
    def steel_picker(self,role,label):
        w=self.combo(label+' RB / DB / ASTM',('Custom (not certified)',));records=[None]
        for cat,grade in ((C.TIS_RB,'SR24'),(C.TIS_DB,'SD40'),(C.ASTM_SI,'Grade 60 [420]'),(C.ASTM_IN,'Grade 60 [420]')):
            for row in C.entries(cat):w.addItem(cat+' '+row['size']+' '+grade);records.append(C.selection(cat,row['size'],grade))
        self.steels[role]=(w,records)
        def selected(_):
            r=records[w.currentIndex()];field=self.fields['dowel_diameter' if role=='dowel' else 'diameter_'+role]
            field.setDecimals(6);field.setEnabled(r is None)
            if r:field.setValue(r['diameter_mm'])
        w.currentIndexChanged.connect(selected)
    def params(self):
        p=SR.defaults();p.update({k:w.value()/1000 for k,w in self.fields.items()})
        p.update(mode=self.mode.currentText(),axis=self.axis.currentText(),mats=self.mats.currentIndex()+1,representation=self.representation.currentText(),
            wire_name=self.wire_name.text().strip(),dowels=self.dowels.isChecked(),dowel_ends=self.ends.currentText(),dowel_shape=self.shape.currentText())
        for role,(w,records) in self.steels.items():p['dowel_steel' if role=='dowel' else 'steel_'+role]=copy.deepcopy(records[w.currentIndex()])
        return p
    def set_params(self,p):
        self.mode.setCurrentText(p['mode']);self.axis.setCurrentText(p['axis']);self.mats.setCurrentIndex(p['mats']-1);self.representation.setCurrentText(p['representation'])
        for role,(w,records) in self.steels.items():
            r=p.get('dowel_steel' if role=='dowel' else 'steel_'+role);w.setCurrentIndex(records.index(r) if r in records else 0)
        for k,w in self.fields.items():w.setValue(p[k]*1000)
        self.wire_name.setText(p['wire_name']);self.dowels.setChecked(p['dowels']);self.ends.setCurrentText(p['dowel_ends']);self.shape.setCurrentText(p['dowel_shape'])
        self.enable_fields()
    def host(self):
        scene=self.panel.app.scene
        if scene is not self.bound_scene:raise ValueError('Read the selected Slab in this document first')
        host=next((g for g in scene.groups if g.uid==self.host_uid),None)
        if host is None or scene.selection!={host}:raise ValueError('Select the Slab originally read, or read another Slab')
        return host
    def read_host(self):
        scene=self.panel.app.scene
        if len(scene.selection)!=1:raise ValueError('Select exactly one concrete Slab')
        host=next(iter(scene.selection));W.host_token(host)
        if host.ext['thai_bim']['kind']!='Slab':raise ValueError('Select a Thai BIM Slab')
        self.host_uid=host.uid;self.bound_scene=scene;self.reviewed=None;self.label.setText(host.name+' • '+host.ext['thai_bim']['id'][:8])
        old=next((g.ext['thai_bim'].get('slab_rebar_params') for g in scene.groups if (g.ext or {}).get('thai_bim',{}).get('host_uid')==host.uid and g.ext['thai_bim'].get('slab_rebar_params')),None)
        self.set_params(old or SR.defaults());self.preview()
    def preview(self):
        if self.host_uid is None:
            self.visual.display([]);self.output.setPlainText('เลือกพื้นคอนกรีต Thai BIM หนึ่งชิ้นในโมเดล แล้วกดอ่านพื้นที่เลือก\nจากนั้นเลือกระบบพื้น → ตั้งรายละเอียดจากแบบ → ตรวจ Host → สร้าง');return
        try:
            host=self.host();specs,_=review(self.bound_scene,host,self.params());self.visual.display(W.P.world_specs(specs,W.pose(host)),W.P.world_specs([E.box_spec('Slab',**{k:host.ext['thai_bim']['params'][k] for k in ('x','y','z','width','depth','height')})],W.pose(host)))
            # Real polygon outline replaces the rectangular ghost.
            if host.ext['thai_bim']['params'].get('shape')=='polygon':
                ghost=dict(kind='Slab',faces=[[tuple(v.toTuple()) for v in tri] for f in host.mesh.faces for tri in f.triangulate()])
                self.visual.display(W.P.world_specs(specs,W.pose(host)),W.P.world_specs([ghost],W.pose(host)))
            totals={}
            for s in specs:
                role=s['bbs']['slab_role'];a,b,n=totals.get(role,(0,0,0));totals[role]=(a+s['quantity'],b+s['bbs']['mass_kg'],n+1)
            self.output.setPlainText('พรีวิวตาม Host จริง • ยังไม่สร้าง • หน่วยกรอก mm / โมเดล m\n'+'\n'.join(f'{role}: {n} เส้น / {a:.3f} m / {b:.3f} kg' for role,(a,b,n) in totals.items()))
        except Exception as error:self.visual.invalid(error);self.output.setPlainText(str(error))
    def review(self):
        self.timer.stop();_,self.reviewed=review(self.bound_scene,self.host(),self.params());self.preview()
        self.output.appendPlainText('ตรวจ Host แล้ว; เปลี่ยนค่า / Host ต้องตรวจใหม่ • เหล็กเดิมจะถูกแทนที่เฉพาะ Host นี้')
    def build(self):
        self.timer.stop()
        if self.reviewed is None:raise ValueError('Review Host and preview explicitly before creating slab bars')
        cmd,count=command(self.bound_scene,self.host(),self.params(),self.reviewed);self.panel.execute(cmd);self.reviewed=None
        self.output.setPlainText(f'สร้าง / อัปเดต {count} เส้นแล้ว • Undo ได้ • แยกบทบาทใน QTO/BBS')

def open_dialog(panel):
    old=getattr(panel,'slab_dialog',None)
    if old:old.close();old.deleteLater()
    d=SlabDialog(panel);panel.slab_dialog=d
    if len(panel.app.scene.selection)==1:d.read_host()
    d.show();return d

def install(panel):
    if getattr(panel,'_slab_rebar_installed',False):return
    panel._slab_rebar_installed=True
    panel.button(panel.members,'เหล็กพื้นทางเดียว / สองทาง / ไวร์เมช / โดเวล…',lambda:open_dialog(panel))
