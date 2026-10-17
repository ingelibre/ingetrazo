"""Six RC stair forms, nested closed solids and explicit Host rebar review."""
import copy,json,math
from PySide6.QtWidgets import QComboBox,QCheckBox,QLabel,QFormLayout,QHBoxLayout,QPushButton,QTableWidget,QTableWidgetItem
from . import stairs as S,workflow as W,placement as P,steel as C
from .builders import BuilderDialog,icon

def concrete_command(scene,params,pose,host=None,expected=None):
    from . import identity_issues,make_group,ExchangeGroups
    if host is not None:
        if scene.selection!={host} or host not in scene.groups:raise ValueError('Select the Stair originally read')
        if identity_issues(scene) or W.host_token(host)!=expected:raise ValueError('Host / copied IDs changed; read selected Stair again')
    result=make_group(S.spec(**params),assembly=host.ext['thai_bim'].get('assembly','') if host else '',previous=host)
    result.xform=W.matrix(pose)
    if host:result.name=host.name;result.layer=host.layer
    result.ext['thai_bim'].update(assembly_kind='advanced-rc-stair',assembly_params=copy.deepcopy(params))
    return ExchangeGroups(scene,replacements=[(host,result)] if host else (),additions=[] if host else [result]),result
def rebar_key(host,params):return W.host_token(host),json.dumps(params,sort_keys=True),json.dumps([host.ext['thai_bim'].get('member_type'),host.ext['thai_bim'].get('stair_type')],sort_keys=True)
def review(scene,host,params):
    from . import identity_issues
    if host not in scene.groups or scene.selection!={host}:raise ValueError('Select the Stair originally read')
    if identity_issues(scene):raise ValueError('Repair copied / missing IDs before reinforcement review')
    token=rebar_key(host,params);hp=host.ext['thai_bim'].get('stair_params',{})
    if host.ext['thai_bim'].get('copy_review_required'):raise ValueError('Copied stair requires explicit concrete update before reinforcement review')
    if hp.get('stair_schema')!=2:raise ValueError('Select a schema 2 Stair; legacy straight stairs keep their existing tool')
    bars=[g for g in scene.groups if (g.ext or {}).get('thai_bim',{}).get('host_uid')==host.uid]
    if any(not W.bar_unchanged(g) for g in bars):raise ValueError('Existing bars edited / copied / independently moved; resolve them first')
    return S.reinforcement(hp,params),token
def rebar_command(scene,host,params,expected):
    from . import reconcile_specs
    specs,token=review(scene,host,params)
    if expected!=token:raise ValueError('Host / type / settings changed after review; review again')
    pose=W.pose(host)
    return reconcile_specs(scene,specs,'rebar-'+host.uid,dict(host_uid=host.uid,host_hash=token[0][2],host_pose=pose,bar_pose=pose,
        host_params=copy.deepcopy(host.ext['thai_bim']['stair_params']),host_kind='Stair',rebar_params=None,rebar_recipe_source=None,
        stair_rebar_schema=1,stair_rebar_params=copy.deepcopy(params)),rebar_host=host)

class StairsDialog(BuilderDialog):
    def __init__(self,panel):
        super().__init__(panel,'Stair');self.setWindowTitle('Thai BIM — บันได RC / ชานพัก / เหล็กเชื่อมต่อ');self.setWindowIcon(icon('Stair'));self.form.setRowWrapPolicy(QFormLayout.WrapLongRows)
        self.uid=None;self.bound_scene=None;self.expected=None;self.reviewed=None;self.loading=False
        self.label=QLabel('สร้างชุดใหม่ หรือเลือกบันไดรุ่นใหม่แล้วกดอ่าน');self.label.setWordWrap(True);self.form.addRow(self.label)
        from .stair_library_ui import StairLibrary
        self.library=StairLibrary(self)
        self.layout_kind=self.combo('รูปแบบบันได',S.LAYOUTS);self.hand=self.combo('เลี้ยว / ทิศหมุน',('Left','Right'));self.view=self.combo('พรีวิว',('Concrete','Rebar + Concrete'))
        self.note('ระบบวัสดุ: RC • Steel รูปพรรณยังไม่เปิดใช้งาน\nรุ่นใหม่รวมลูกนอนสุดท้ายที่ระดับบน ชานพักไม่นับเป็นลูกตั้งเพิ่ม\nเกลียว/โค้ง: ระบุรัศมีช่องกลางและมุมกวาด; ยังไม่สร้างเสาแกน/ราว/โครงรองรับ\nบันไดลอย: ขั้น RC แยกชิ้น รองรับและผนังต้องกำหนดตามแบบ')
        self.gf={};self.rf={};self.pf={};self.steels={};defaults=S.defaults();rb=S.rebar_defaults()
        for key,label in [('x','ตำแหน่ง X (m)'),('y','ตำแหน่ง Y (m)'),('z','ระดับชั้นล่าง (m)'),('yaw','ทิศแรก / หมุน Z (°)')]:self.pf[key]=self.field('pose_'+key,label,0,minimum=-10000,maximum=10000);self.pf[key].setDecimals(6)
        labels={'width':'ความกว้างช่วง (m)','height':'สูงระหว่างระดับ (m)','going':'ลูกนอนทางตรง (m)','waist':'ท้องลาดตั้งฉาก / ท้องเกลียว (m)',
            'risers':'จำนวนลูกตั้งทั้งหมด','first_risers':'ลูกตั้งช่วงแรก L/U','landing_depth':'ความลึกชานพัก (m)','landing_thickness':'ความหนาชานพัก (m)','gap':'ช่องกลาง U (m)',
            'inner_radius':'รัศมีช่องกลาง (m)','sweep':'มุมกวาดเกลียว / โค้ง (°)','tread_thickness':'ความหนาขั้นลอย (m)'}
        for k,label in labels.items():
            self.gf[k]=self.field('geometry_'+k,label,defaults[k],k in ('risers','first_risers'),0,540 if k=='sweep' else 100)
            if k not in ('risers','first_risers'):self.gf[k].setDecimals(6)
        self.bottom=QCheckBox('ชานพักล่าง');self.bottom.setChecked(True);self.top=QCheckBox('ชานพักบน');self.top.setChecked(True)
        for w in (self.bottom,self.top):self.form.addRow(w);w.toggled.connect(lambda _:self.timer.start())
        self.rep=self.combo('รูปแบบเหล็ก',('Centreline','Lightweight','Full'));self.mats=self.combo('ชุดเหล็กท้องลาด / ชานพัก',('Bottom','Bottom + Top'))
        self.note('ตั้งค่าตามแบบก่อนสร้าง • ค่าเริ่มต้นเป็นตัวอย่าง\nทางตรง/L/U: เหล็กช่วงดัดปลายเข้าสู่ชานพัก พร้อม mat ชานพัก\nโค้ง: เหล็กหลักเกลียว + เหล็กกระจายแนวรัศมี; รอยต่อใช้ตารางพิเศษ\nลอย: เหล็กหลักบนฝังแนวผนัง + เหล็กกระจายล่างแต่ละขั้น')
        for k,label in [('cover','ระยะหุ้มถึงผิวเหล็ก'),('diameter','ขนาดเหล็กหลัก custom'),('distribution_diameter','ขนาดเหล็กกระจาย custom'),('spacing','ระยะเหล็กหลักสูงสุด'),('distribution_spacing','ระยะเหล็กกระจายสูงสุด'),('inside_radius','รัศมีดัดภายใน'),('connection','ระยะฝังชานพัก / ผนัง')]:self.rf[k]=self.field('rebar_'+k,label+' (mm)',rb[k]*1000,minimum=0,maximum=3000)
        for role,key,label in [('main','diameter','เหล็กหลัก'),('distribution','distribution_diameter','เหล็กกระจาย')]:self.steel_picker(role,key,label)
        self.note('เพิ่มรอยต่อพิเศษตามแบบได้ทุกทรง • พิกัดอ้างอิงรูป Left ก่อนสะท้อน Right\nX/Y/Z, ยาว, ขา และระยะในตารางใช้ m; ทิศใช้ °\nขา +Z/−Z สร้าง L; ขา 0 เป็นตรง; ซ้ำในแนวตั้งฉากกับทิศ\nตารางนี้ไม่ตรวจรองรับข้างเคียง ระยะพัฒนา หรือชนเหล็กทั้งโมเดล')
        self.connections=QTableWidget(0,9);self.connections.setHorizontalHeaderLabels(['ชื่อ','X','Y','Z','ทิศ°','ยาว m','ขา ±Z m','จำนวน','ระยะ m']);self.connections.setMinimumHeight(160);self.form.addRow(self.connections)
        self.connections.itemChanged.connect(lambda _:self.timer.start());self.button('เพิ่มแถวรอยต่อพิเศษ (ปรับตามแบบ)',self.add_connection);self.button('ลบแถวรอยต่อที่เลือก',self.remove_connection)
        for actions in [[('อ่านบันไดที่เลือก',self.read_host),('สร้างคอนกรีตชุดใหม่',self.create),('อัปเดตคอนกรีตเฉพาะชิ้นที่อ่าน',self.update)],
            [('ตรวจ Host + พรีวิวเหล็ก',self.review),('สร้าง / อัปเดตเหล็กที่ตรวจแล้ว',self.build_rebar)],
            [('เริ่มคลิกวางบันได: ปาก → ทิศขึ้น',self.start_placement),('ตรวจรอยต่อกับรองรับ…',self.open_connections),('แบบบันได / เหล็ก / Sheet…',self.open_drawings)]]:
            row=QHBoxLayout();self.layout().addLayout(row)
            for text,fn in actions:
                b=QPushButton(text);b.clicked.connect(lambda checked=False,fn=fn:panel.guard(fn));row.addWidget(b)
        b=QPushButton('ปรับความลึกชานพักในโมเดล (ใช้ร่วมทุกชานพักของบันไดนี้)');b.clicked.connect(lambda checked=False:panel.guard(self.start_shape_edit));self.layout().addWidget(b)
        clickrow=QHBoxLayout();self.layout().addLayout(clickrow);clickrow.addWidget(QLabel('ระดับฐานขณะคลิก'))
        self.click_z=QComboBox();self.click_z.addItems(('Fixed Z / ล็อกระดับ Z ที่กรอก','First point Z / ใช้ระดับจุดแรก'));clickrow.addWidget(self.click_z,1)
        self.note('คลิกวาง: จุดแรกกึ่งกลางปากบันไดระดับฐาน → จุดสองทิศขึ้นช่วงแรก\nวน/โค้งใช้แนวสัมผัสเริ่มต้น • ขนาดตามพรีวิว ไม่ยืดตามระยะคลิก\nคลิกต่อวางซ้ำ • Esc ล้างจุด; Esc อีกครั้งกลับไดอะลอก • Undo แยกแต่ละชิ้น\nสร้างคอนกรีตก่อน เหล็กต้องอ่าน Host ตรวจและสร้างแยก')
        self.layout_kind.currentIndexChanged.connect(self.changed_layout);self.mats.currentIndexChanged.connect(self.enable_fields);self.changed_layout()
    def start_shape_edit(self):
        from .shape_edit import start
        self.host();return start(self.panel)
    def combo(self,label,items):
        w=QComboBox();w.setMinimumContentsLength(14);w.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon);w.addItems(items);self.form.addRow(label,w);w.currentIndexChanged.connect(lambda _:self.timer.start());return w
    def steel_picker(self,role,key,label):
        combo=self.combo(label+' RB / DB / ASTM',('Custom',));records=[None]
        for cat,grades in ((C.TIS_RB,('SR24',)),(C.TIS_DB,('SD30','SD40','SD50')),(C.ASTM_SI,('Grade 60 [420]',)),(C.ASTM_IN,('Grade 60 [420]',))):
            for grade in grades:
                for r in C.entries(cat):combo.addItem(cat+' '+r['size']+' '+grade);records.append(C.selection(cat,r['size'],grade))
        self.steels[role]=(combo,records)
        def change(_):
            r=records[combo.currentIndex()];self.rf[key].setDecimals(6);self.rf[key].setEnabled(r is None)
            if r:self.rf[key].setValue(r['diameter_mm'])
        combo.currentIndexChanged.connect(change)
    def changed_layout(self,*_):
        if not self.loading:
            curved=self.layout_kind.currentText() in ('Spiral','Circular');self.rf['connection'].setValue(0 if curved else 200)
            if curved:self.gf['inner_radius'].setValue(.2 if self.layout_kind.currentText()=='Spiral' else 1.5);self.gf['sweep'].setValue(360 if self.layout_kind.currentText()=='Spiral' else 180)
            if self.layout_kind.currentText()=='Floating':self.mats.setCurrentIndex(0)
        self.enable_fields()
    def enable_fields(self,*_):
        layout=self.layout_kind.currentText();curved=layout in ('Spiral','Circular');floating=layout=='Floating'
        for k in ('going','landing_depth','landing_thickness'):self.gf[k].setEnabled(not floating if k!='going' else not curved)
        for k in ('first_risers','gap'):self.gf[k].setEnabled(layout in ('L','U') if k=='first_risers' else layout=='U')
        self.gf['waist'].setEnabled(not floating);self.gf['tread_thickness'].setEnabled(floating)
        for k in ('inner_radius','sweep'):self.gf[k].setEnabled(curved)
        self.bottom.setEnabled(not floating);self.top.setEnabled(not floating);self.rf['connection'].setEnabled(not curved);self.mats.setEnabled(not floating)
    def geometry(self):
        p=S.defaults();p.update({k:w.value() for k,w in self.gf.items()});p.update(layout=self.layout_kind.currentText(),hand=self.hand.currentText(),bottom_landing=self.bottom.isChecked(),top_landing=self.top.isChecked());return S.validated(p)
    def pose(self):return P.matrix(tuple(self.pf[k].value() for k in ('x','y','z')),self.pf['yaw'].value())
    def rebar(self):
        p=S.rebar_defaults();p.update({k:w.value()/1000 for k,w in self.rf.items()});p.update(representation=self.rep.currentText(),mats=self.mats.currentIndex()+1)
        for role,(combo,records) in self.steels.items():p[role+'_steel']=copy.deepcopy(records[combo.currentIndex()])
        keys=('name','x','y','z','angle','length','leg','count','spacing')
        p['extra_connections']=[{k:(self.connections.item(i,j).text() if k=='name' else float(self.connections.item(i,j).text())) for j,k in enumerate(keys)} for i in range(self.connections.rowCount())];return p
    def add_connection(self):
        i=self.connections.rowCount();self.connections.insertRow(i)
        for j,v in enumerate((f'Connection {i+1}',0,0,-.1,0,.4,.1,3,.15)):self.connections.setItem(i,j,QTableWidgetItem(str(v)))
    def remove_connection(self):
        if self.connections.currentRow()>=0:self.connections.removeRow(self.connections.currentRow());self.timer.start()
    def host(self):
        scene=self.panel.app.scene
        if scene is not self.bound_scene:raise ValueError('Read selected Stair in this document first')
        host=next((g for g in scene.groups if g.uid==self.uid),None)
        if host is None or scene.selection!={host}:raise ValueError('Select the Stair originally read, or read another Stair')
        return host
    def read_host(self):
        scene=self.panel.app.scene
        if len(scene.selection)!=1:raise ValueError('Select exactly one schema 2 Stair')
        host=next(iter(scene.selection));token=W.host_token(host);p=host.ext['thai_bim'].get('stair_params',{})
        if p.get('stair_schema')!=2:raise ValueError('This dialog edits schema 2 stairs; use the legacy straight tool for earlier stairs')
        pose=P.rigid_matrix(W.pose(host))
        if abs(pose[8])+abs(pose[9])+abs(pose[10]-1)>1e-5:raise ValueError('Tilted stairs: restore upright Z placement before editing')
        for k,v in zip(('x','y','z','yaw'),(pose[3],pose[7],pose[11],math.degrees(math.atan2(pose[4],pose[0])))):self.pf[k].setValue(v)
        self.uid=host.uid;self.bound_scene=scene;self.expected=token;self.reviewed=None;self.label.setText(host.name+' • '+host.ext['thai_bim']['id'][:8])
        saved=next((g.ext['thai_bim']['stair_rebar_params'] for g in scene.groups if (g.ext or {}).get('thai_bim',{}).get('host_uid')==host.uid and g.ext['thai_bim'].get('stair_rebar_params')),None)
        q=saved or host.ext['thai_bim'].get('stair_rebar_preset') or (host.ext['thai_bim'].get('stair_type') or {}).get('rebar') or S.rebar_defaults();q=copy.deepcopy(q)
        if not saved and not host.ext['thai_bim'].get('stair_rebar_preset') and not host.ext['thai_bim'].get('stair_type') and p['layout'] in ('Spiral','Circular'):q['connection']=0
        self.load_values(p,q);self.library.read_snapshot(host);self.preview()
    def load_values(self,p,q):
        self.loading=True
        try:
            self.layout_kind.setCurrentText(p['layout']);self.hand.setCurrentText(p['hand'])
            for k,w in self.gf.items():w.setValue(p[k])
            self.bottom.setChecked(p['bottom_landing']);self.top.setChecked(p['top_landing'])
        finally:self.loading=False
        self.rep.setCurrentText(q['representation']);self.mats.setCurrentIndex(q['mats']-1)
        for role,(combo,records) in self.steels.items():combo.setCurrentIndex(records.index(q[role+'_steel']))
        for k,w in self.rf.items():w.setValue(q[k]*1000)
        self.connections.setRowCount(0)
        for record in q['extra_connections']:
            self.add_connection();i=self.connections.rowCount()-1
            for j,k in enumerate(('name','x','y','z','angle','length','leg','count','spacing')):self.connections.item(i,j).setText(str(record[k]))
        self.enable_fields();self.preview()
    def preview(self):
        try:
            p=self.geometry();ghost=S.spec(**p);concrete=P.world_specs([ghost],self.pose())
            if self.view.currentIndex()==0:
                self.visual.display(concrete);self.output.setPlainText(f"พรีวิว RC {p['layout']} • คอนกรีตรวม {ghost['quantity']:.4f} m³\nลูกตั้ง {p['risers']} × {p['height']/p['risers']*1000:.2f} mm • ยังไม่สร้าง\nรูปใหม่รวมลูกนอนสุดท้ายที่ระดับบน; ไม่ตรวจ headroom / รองรับ / กำลัง")
            else:
                specs=S.reinforcement(p,self.rebar());self.visual.display(P.world_specs(specs,self.pose()),concrete);totals={}
                for s in specs:
                    role=s['bbs']['stair_role'];n,l,m=totals.get(role,(0,0,0));totals[role]=(n+1,l+s['quantity'],m+s['bbs']['mass_kg'])
                self.output.setPlainText('พรีวิวรายละเอียดผู้ใช้ • ยังไม่สร้าง\n'+'\n'.join(f'{role}: {n} เส้น / {l:.3f} m / {m:.3f} kg' for role,(n,l,m) in totals.items()))
        except Exception as error:self.visual.invalid(error);self.output.setPlainText(str(error))
    def create(self):
        from .stair_library_ui import tag
        self.timer.stop();row=self.library.model_source();p=self.geometry();q=self.rebar()
        if row:from .stair_catalogue import stair_type;stair_type(row['code'],row['name'],p,q,row['id'],row['revision'])
        cmd,host=concrete_command(self.panel.app.scene,p,self.pose());tag(host,row,p,q);self.panel.execute(cmd);self.panel.app.scene.selection={host};self.read_host();self.output.appendPlainText('สร้างคอนกรีตแล้ว • เหล็กต้องตรวจ Host แล้วสร้างแยก • Undo ได้')
    def start_placement(self):
        from .stair_place_ui import start
        return start(self)
    def open_drawings(self):
        from .stair_drawings import open_dialog
        return open_dialog(self.panel)
    def open_connections(self):
        from .stair_connection_ui import open_dialog
        return open_dialog(self.panel)
    def update(self):
        from .stair_library_ui import tag
        self.timer.stop();row=self.library.model_source();p=self.geometry();q=self.rebar()
        if row:from .stair_catalogue import stair_type;stair_type(row['code'],row['name'],p,q,row['id'],row['revision'])
        cmd,host=concrete_command(self.bound_scene,p,self.pose(),self.host(),self.expected);tag(host,row,p,q);self.panel.execute(cmd);self.panel.app.scene.selection={host};self.read_host();self.load_values(p,q);self.preview();self.output.appendPlainText('อัปเดตคอนกรีตเฉพาะชิ้นแล้ว • เหล็กเดิมยังอยู่ ต้องตรวจ Host ใหม่')
    def review(self):
        self.timer.stop();host=self.host()
        if self.geometry()!=host.ext['thai_bim']['stair_params'] or not P.same_pose(self.pose(),W.pose(host)):raise ValueError('Concrete preview differs from Host; save concrete or read Host before reviewing bars')
        _,self.reviewed=review(self.bound_scene,host,self.rebar());self.view.setCurrentIndex(1);self.preview();self.timer.stop();self.output.appendPlainText('ตรวจ Host แล้ว • เปลี่ยนค่าหรือ Host ต้องตรวจใหม่')
    def build_rebar(self):
        self.timer.stop()
        if self.reviewed is None:raise ValueError('Review current Host and reinforcement preview first')
        host=self.host()
        if self.geometry()!=host.ext['thai_bim']['stair_params'] or not P.same_pose(self.pose(),W.pose(host)):raise ValueError('Concrete preview changed; update concrete and review bars first')
        cmd,count=rebar_command(self.bound_scene,host,self.rebar(),self.reviewed);self.panel.execute(cmd);self.reviewed=None;self.output.setPlainText(f'สร้าง / อัปเดต {count} เส้นแล้ว • Undo ได้ • แยกบทบาทใน QTO/BBS')

def open_dialog(panel,read=True):
    old=getattr(panel,'stairs_dialog',None)
    if old:old.close();old.deleteLater()
    d=StairsDialog(panel);panel.stairs_dialog=d
    if read and len(panel.app.scene.selection)==1 and ((next(iter(panel.app.scene.selection)).ext or {}).get('thai_bim',{}).get('stair_params') or {}).get('stair_schema')==2:d.read_host()
    d.show();return d
def install(panel):
    if getattr(panel,'_advanced_stairs_installed',False):return
    panel._advanced_stairs_installed=True
    panel.button(panel.members,'บันได RC ทุกทรง / ชานพัก / เหล็กเชื่อมต่อ…',lambda:open_dialog(panel))
    panel.button(panel.members,'บันไดตรงเครื่องมือเดิม / Legacy…',lambda:legacy(panel))
def legacy(panel):
    from .builders import StairDialog
    d=StairDialog(panel);panel.legacy_stair_dialog=d;d.show();return d
