"""Assembly dialogs and tool icons, drawn locally with Qt."""
import math,copy,json
from PySide6.QtCore import Qt,QPointF,QSize,QTimer
from PySide6.QtGui import QPixmap,QIcon,QPainter,QPen,QColor,QPolygonF
from PySide6.QtWidgets import (QWidget,QDialog,QVBoxLayout,QHBoxLayout,QFormLayout,QScrollArea,
    QDoubleSpinBox,QSpinBox,QComboBox,QLabel,QPushButton,QPlainTextEdit,QToolBar,QTabWidget)
from . import engine as E
from . import structures as S
from . import detailing as D

PRESETS={'Footing':(.0,.0,-.4,1.2,1.2,.4),'Column':(0,0,0,.25,.25,3),
         'Beam':(0,0,3,3,.2,.4),'Slab':(0,0,3,4,3,.15)}


def icon(kind):
    pix=QPixmap(64,64);pix.fill(Qt.transparent);p=QPainter(pix)
    try:
        p.setRenderHint(QPainter.Antialiasing);p.setPen(QPen(QColor('#2183a4'),4,Qt.SolidLine,Qt.RoundCap,Qt.RoundJoin))
        paths={
            'Project':[[(12,8),(12,56)],[(32,8),(32,56)],[(52,8),(52,56)],[(8,18),(56,18)],[(8,42),(56,42)]],
            'Footing':[[(9,45),(55,45),(55,56),(9,56),(9,45)],[(24,45),(24,17),(40,17),(40,45)]],
            'Column':[[(24,8),(40,8),(40,56),(24,56),(24,8)]],
            'Beam':[[(8,22),(56,22),(56,38),(8,38),(8,22)],[(15,38),(15,56)],[(49,38),(49,56)]],
            'Slab':[[(6,28),(40,14),(58,27),(24,43),(6,28)],[(6,28),(6,37),(24,52),(58,36),(58,27)],[(24,43),(24,52)]],
            'Stair':[[(8,56),(8,44),(20,44),(20,32),(32,32),(32,20),(44,20),(44,8),(56,8)]],
            'Rebar':[[(12,12),(52,12),(52,52),(12,52),(12,12)],[(20,7),(20,57)],[(44,7),(44,57)]],
            'Roof':[[(7,43),(32,14),(57,43)],[(14,37),(14,56),(50,56),(50,37)]],
            'Multi':[[(7,44),(22,12),(44,12),(57,44),(7,44)],[(22,12),(32,32),(44,12)],[(7,44),(32,32),(57,44)]],
            'QTO':[[(13,8),(51,8),(51,56),(13,56),(13,8)],[(21,22),(44,22)],[(21,33),(44,33)],[(21,44),(44,44)]],
            'Place':[[(8,32),(56,32)],[(32,8),(32,56)],[(18,20),(46,20),(46,46),(18,46),(18,20)]],
            'Host':[[(10,10),(44,10),(44,44),(10,44),(10,10)],[(50,26),(56,34),(50,42)],[(56,34),(38,34)]],
            'Sheet':[[(8,7),(56,7),(56,57),(8,57),(8,7)],[(14,15),(42,15),(42,39),(14,39),(14,15)],[(32,46),(50,46),(50,52),(32,52),(32,46)],[(18,12),(18,43)],[(12,26),(46,26)]],
            'Cut':[[(7,17),(57,17),(57,29),(7,29),(7,17)],[(27,9),(27,36)],[(7,45),(26,45)],[(38,45),(57,45)]],
        }
        for path in paths[kind]:p.drawPolyline(QPolygonF([QPointF(*v) for v in path]))
        p.setPen(QPen(QColor('#d88524'),3));p.drawLine(12,60,52,60)
    finally:p.end()
    return QIcon(pix)


class AssemblyPreview(QWidget):
    def __init__(self):
        super().__init__();self.setMinimumSize(440,360);self.specs=[];self.error='';self.host=[]
    def display(self,specs,host=()):self.specs=specs;self.host=list(host);self.error='';self.update()
    def invalid(self,e):self.error=str(e);self.specs=[];self.update()
    def paintEvent(self,event):
        p=QPainter(self)
        try:
            p.setRenderHint(QPainter.Antialiasing);p.fillRect(self.rect(),QColor('#14283a'))
            p.setPen(QColor('#f2f6fa'));p.drawText(QPointF(18,28),'พรีวิวรูปทรงตามค่า • หน่วย geometry = m')
            if self.error:p.drawText(self.rect().adjusted(20,50,-20,-20),Qt.TextWordWrap,self.error);return
            specs=self.host+self.specs
            if not specs:p.drawText(QPointF(20,65),'เลือกชิ้นงาน / กรอกค่าเพื่อดูพรีวิว');return
            def raw(v):return (v[0]-.65*v[1],-.35*v[0]-.25*v[1]-v[2])
            points=[raw(v) for s in specs for v in (s['bar_path'] if s.get('bar_path') else [v for f in s['faces'] for v in f])]
            xmin=min(v[0] for v in points);xmax=max(v[0] for v in points);ymin=min(v[1] for v in points);ymax=max(v[1] for v in points)
            scale=min((self.width()-70)/max(xmax-xmin,.01),(self.height()-100)/max(ymax-ymin,.01))
            ox=(self.width()-(xmax-xmin)*scale)/2;oy=50+(self.height()-100-(ymax-ymin)*scale)/2
            def point(v):
                u,w=raw(v);return QPointF(ox+(u-xmin)*scale,oy+(w-ymin)*scale)
            faces=[]
            for spec in specs:
                if spec.get('bar_path'):
                    pts=spec['bar_path'];pts=pts+pts[:1] if spec.get('bar_closed') else pts
                    p.setPen(QPen(QColor('#ffac66'),1.5));p.drawPolyline(QPolygonF([point(v) for v in pts]));continue
                if spec.get('axis'):
                    p.setPen(QPen(QColor('#2ac6e6') if spec['kind']=='Rafter' else QColor('#e3ac59'),1.3));p.drawLine(point(spec['axis'][0]),point(spec['axis'][1]));continue
                for face in spec['faces']:
                    faces.append((sum(v[0]+v[1]+v[2] for v in face)/len(face),face,spec in self.host,spec['kind']=='Roof cover'))
            for _,face,ghost,roof in sorted(faces,key=lambda v:v[0]):
                p.setPen(QPen(QColor('#7798ac'),1));p.setBrush(Qt.NoBrush if ghost or roof else QColor('#738b9b'))
                p.drawPolygon(QPolygonF([point(v) for v in face]))
            p.setBrush(Qt.NoBrush)
            # Draw steel over the concrete outline so reinforcement remains readable.
            for spec in self.specs:
                if spec.get('bar_path'):
                    pts=spec['bar_path'];pts=pts+pts[:1] if spec.get('bar_closed') else pts
                    p.setPen(QPen(QColor('#ffac66'),1.5));p.drawPolyline(QPolygonF([point(v) for v in pts]))
        finally:p.end()


class BuilderDialog(QDialog):
    def __init__(self,panel,title):
        super().__init__(panel.app.window);self.panel=panel;self.setWindowTitle('Thai BIM 0.11 — '+title);self.setWindowIcon(icon(title if title in ('Stair','Rebar') else 'Roof'));self.resize(1080,800)
        lay=QVBoxLayout(self);row=QHBoxLayout();lay.addLayout(row,1)
        scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setMinimumWidth(355);scroll.setMaximumWidth(470);row.addWidget(scroll,4)
        content=QWidget();self.form=QFormLayout(content);scroll.setWidget(content)
        self.visual=AssemblyPreview();row.addWidget(self.visual,6)
        self.output=QPlainTextEdit();self.output.setReadOnly(True);self.output.setMaximumHeight(130);lay.addWidget(self.output)
        self.fields={};self.timer=QTimer(self);self.timer.setSingleShot(True);self.timer.setInterval(200);self.timer.timeout.connect(self.preview)
    def field(self,key,label,value,integer=False,minimum=None,maximum=None):
        w=QSpinBox() if integer else QDoubleSpinBox()
        if not integer:w.setDecimals(3);w.setSingleStep(.05 if 'mm' not in label else 1)
        w.setRange(minimum if minimum is not None else -10000,maximum if maximum is not None else 10000)
        w.setValue(value);w.valueChanged.connect(lambda _:self.timer.start());self.form.addRow(label,w);self.fields[key]=w;return w
    def button(self,label,fn):
        b=QPushButton(label);b.clicked.connect(lambda _:self.panel.guard(fn));self.form.addRow(b);return b
    def note(self,text):w=QLabel(text);w.setWordWrap(True);self.form.addRow(w)
    def showEvent(self,event):super().showEvent(event);self.preview()
    def preview(self):
        try:
            specs=self.specs();self.visual.display(specs)
            self.output.setPlainText(f'พรีวิว {len(specs)} ชิ้น • ยังไม่ได้สร้าง\n'+'\n'.join(f'{item}: {value:.3f} {unit}' for item,unit,value in self.summary(specs)))
        except Exception as e:self.visual.invalid(e);self.output.setPlainText(str(e))
    @staticmethod
    def summary(specs):
        totals={}
        for s in specs:totals[(s['item'],s['unit'])]=totals.get((s['item'],s['unit']),0)+s['quantity']
        return [(item,unit,value) for (item,unit),value in totals.items()]
    def build(self,update=False):
        from . import assembly_command
        specs=self.specs();params=self.params();selected=list(self.panel.app.scene.selection) if update else None
        command,count=assembly_command(self.panel.app.scene,specs,self.assembly_kind,params,selected)
        self.panel.execute(command);self.output.setPlainText(f'สร้าง/อัปเดต {count} ชิ้น • Undo ได้')
    def read(self):
        from . import selected_assembly
        group=selected_assembly(self.panel.app.scene,self.assembly_kind)
        params=group.ext['thai_bim']['assembly_params']
        if hasattr(self,'kind'):self.kind.setCurrentText(params['kind'])
        for key,w in self.fields.items():w.setValue(params[key])
        self.preview()


class RoofDialog(BuilderDialog):
    assembly_kind='roof-library'
    def __init__(self,panel):
        super().__init__(panel,'Roof');self.kind=QComboBox();self.kind.addItems(['Gable','Hip','Shed']);self.form.addRow('ชนิด: จั่ว / ปั้นหยา / เพิง',self.kind)
        self.kind.currentIndexChanged.connect(lambda _:self.timer.start())
        for key,label,v in [('x','X (m)',0),('y','Y (m)',0),('z','Z แนวผนังต่ำ (m)',3),('width','กว้าง X (m)',6),('depth','ลึก Y (m)',4),('pitch','มุมลาด (°)',30),('overhang','ชายคา (m)',.4),('cover','ความหนาหลังคา (m)',.06),('rafter_spacing','ระยะจันทันสูงสุด (m)',1),('batten_spacing','ระยะแปตามลาด (m)',.3)]:self.field(key,label,v)
        self.note('จั่วสันตาม Y • ปั้นหยาสันตามด้านยาว\nจันทัน/สัน/ตะเข้ C125×50×20×3.2; แป PROFAST\nยังไม่รวมข้อต่อ/การออกแบบรับแรง; gauge ตามกระเบื้อง')
        self.button('สร้างหลังคาชุดใหม่',self.build);self.button('อ่านชุดหลังคาที่เลือก',self.read);self.button('อัปเดตเฉพาะชุดที่เลือก',lambda:self.build(True))
    def params(self):return dict(kind=self.kind.currentText(),**{k:w.value() for k,w in self.fields.items()})
    def specs(self):return S.roof_assembly(**self.params())[1]


class StairDialog(BuilderDialog):
    assembly_kind='rc-stair'
    def __init__(self,panel):
        super().__init__(panel,'Stair')
        self.note('บันได RC ตรง • Z คือระดับชั้นล่าง; ท้องยื่นต่ำกว่าระดับนี้\nชั้นบนเป็นลูกตั้งสุดท้าย; ยังไม่รวมชานพัก/ราว/ฐานรองรับ')
        for key,label,v in [('x','X (m)',0),('y','Y (m)',0),('z','Z ระดับเริ่ม (m)',0),('width','กว้าง (m)',1),('height','สูงระหว่างชั้น (m)',3),('going','ลูกนอน (m)',.28),('waist','ความหนาท้องตั้งฉากลาด (m)',.15)]:self.field(key,label,v)
        self.field('risers','จำนวนลูกตั้ง',18,True,2,60)
        self.button('สร้างบันไดชุดใหม่',self.build);self.button('อ่านบันไดที่เลือก',self.read);self.button('อัปเดตบันไดที่เลือก',lambda:self.build(True))
    def params(self):return {k:w.value() for k,w in self.fields.items()}
    def specs(self):
        p=self.params();sp=S.stair_spec(**p);r=p['height']/p['risers']
        self.setToolTip(f"ลูกตั้ง {r*1000:.1f} mm; 2R+G = {(2*r+p['going'])*1000:.1f} mm (ข้อมูล ไม่ใช่เกณฑ์ผ่าน)")
        return [sp]
    def preview(self):
        super().preview()
        if not self.visual.error:
            p=self.params();r=p['height']/p['risers']
            self.output.appendPlainText(f"ลูกตั้ง {p['risers']} × {r*1000:.2f} mm • ลูกนอน {p['risers']-1} ขั้น\nระยะวิ่ง {(p['risers']-1)*p['going']:.3f} m • 2R+G {(2*r+p['going'])*1000:.1f} mm (ข้อมูลรูปทรง)")


class RebarDialog(BuilderDialog):
    def __init__(self,panel,recipe_type=None,accept_recipe=None):
        super().__init__(panel,'Rebar');self.host_uid=None;self.host_params=None;self.host_kind=None;self.bound_scene=None;self.reviewed_key=None;self.reviewed_specs=None
        self.recipe_type=copy.deepcopy(recipe_type);self.accept_recipe=accept_recipe;self.recipe_source=None
        self.host_label=QLabel('เลือก RC หนึ่งชิ้น แล้วกดอ่าน Host');self.host_label.setWordWrap(True);self.form.addRow(self.host_label)
        self.read_button=self.button('อ่านฐานราก / คาน / เสา / พื้น / บันไดที่เลือก',self.read_host)
        self.recipe_label=QLabel('รายละเอียดผู้ใช้ • ยังไม่ได้เลือกจากชนิด');self.recipe_label.setWordWrap(True);self.form.addRow(self.recipe_label)
        if recipe_type is None:
            self.button('เรียกเหล็กจากรุ่นชนิดที่ติดกับ Host',self.load_host_recipe)
        self.field('cover','Cover ถึงผิวนอกเหล็ก (mm)',40,False,15,150)
        self.field('diameter','เหล็กหลัก / ตะแกรง (mm)',12,False,4,60)
        self.field('tie_diameter','เหล็กปลอก (mm)',6,False,4,60)
        for key in ('diameter','tie_diameter'):self.fields[key].setDecimals(6)
        self.steel_controls={}
        self.steel_picker('main_steel','เหล็กหลัก', 'diameter','DB12')
        self.steel_picker('tie_steel','เหล็กปลอก', 'tie_diameter','RB6')
        self.representation=QComboBox();self.representation.addItems(['Lightweight','Centreline','Full'])
        self.form.addRow('แสดงผล: เบา / เส้นแกน / เต็ม',self.representation)
        self.representation.currentTextChanged.connect(lambda _:self.timer.start())
        self.note('Lightweight: 6 ด้าน / โค้ง 30° • Full: 12 ด้าน / โค้ง 10°\nCentreline: เส้นแกน ไม่มีผิว solid; ใช้ถอดความยาวเดิม\nRB ผิวเรียบ / DB และ ASTM เป็นข้อมูลชนิด ไม่สร้างบั้งนูน\nขนาด #9 ขึ้นไปใช้ตาราง ไม่หาร 8; SI และ inch เป็นคนละชุดหน่วย')
        self.field('spacing','ระยะปลอก / ตะแกรงสูงสุด (mm)',150,False,40,1000)
        self.field('count_x','จำนวนหลักตามด้านที่ 1',3,True,2,30)
        self.field('count_y','จำนวนหลักตามด้านที่ 2',3,True,2,30)
        self.field('layers','ชั้นตะแกรงฐาน/พื้น: 1 ล่าง / 2 บนล่าง',1,True,1,2)
        for key,label,value,minimum,maximum in [
            ('inside_radius','รัศมีด้านในเหล็กหลัก (mm)',24,2,250),
            ('tie_inside_radius','รัศมีด้านในปลอก (mm)',12,2,250),
            ('hook_length','ขาตะขอฐาน/พื้น/บันได หลังจุดสัมผัส (mm)',0,0,1000),
            ('tie_hook_length','ขาปลอก 135° หลังจุดสัมผัส (mm)',40,10,500),
            ('lap_length','ระยะทาบกลางเสา/คาน (mm); 0 = ไม่ทาบ',0,0,3000),
            ('extension_start','ยื่นต้นเสา/คาน/เหล็กหลักบันไดตามแนวแกน (mm)',0,0,3000),
            ('extension_end','ยื่นปลายเสา/คาน/เหล็กหลักบันไดตามแนวแกน (mm)',0,0,3000),
            ('density','ความหนาแน่นตามวัสดุ (kg/m³)',7850,1000,20000)]:
            self.field(key,label,value,False,minimum,maximum)
        self.field('hook_ends','ตะขอ: 1 = ปลายต้น / 2 = สองปลาย',2,True,1,2)
        self.note('ฐาน/พื้น L/U 90° พับเข้ากลางความหนา • บันไดตรง: ขาตะขอตั้งขึ้น\nบันได: Cover ตั้งฉากท้องพื้น; เหล็กขวางไม่ยื่นตามเหล็กหลัก\nเลือกตะขอหรือยื่นตามลาดบันได; ไม่มีทาบพื้น/บันได\nทุกชนิดรวม BBS; ค่ามาจากผู้ใช้ ไม่มีการออกแบบรับแรง\nส่วนยื่นต้องตรวจคอนกรีตข้างเคียง; ไม่มีตรวจชนทั้งโมเดล')
        if recipe_type is None:
            self.button('ตาราง BBS / ส่งออก Excel…',lambda:open_bbs(self.panel))
            self.button('ตรวจพรีวิวและข้อมูล Host ล่าสุด',self.review)
            self.button('สร้าง / อัปเดตเหล็กที่ตรวจพรีวิวแล้ว',self.build)
        else:
            self.read_button.hide();self.host_kind=recipe_type['kind'];self.bound_scene=panel.app.scene
            self.setWindowTitle('Thai BIM — รายละเอียดเหล็ก '+recipe_type['code'])
            from . import placement as P,rebar_recipe as R
            sp=S.stair_spec(**recipe_type['params']) if self.host_kind=='Stair' else P.member_spec(self.host_kind,**recipe_type['params'])
            self.host_params=sp.get('params') or sp.get('stair_params')
            self.host_label.setText('พรีวิวชนิด '+recipe_type['code']+' • ขนาดตัวอย่างของชนิด • หน่วยเหล็ก mm')
            self.configure_kind();self.set_params(recipe_type.get('rebar') or R.defaults())
            self.recipe_label.setText('แก้ค่าชั่วคราว → ใช้รายละเอียดนี้ → บันทึกชนิดในโครงการ\nขนาดคาน/พื้นจริงอาจต่างจากตัวอย่าง; ต้องตรวจ Host ก่อนสร้าง')
            # Keep the commit action visible even when the parameter form scrolls.
            commit=self.button('ใช้รายละเอียดนี้ในชนิด (ยังไม่สร้างเหล็ก)',self.accept_type_recipe)
            self.form.removeWidget(commit);self.layout().addWidget(commit)
    def configure_kind(self):
        for key in ('count_x','count_y','tie_inside_radius','tie_hook_length','lap_length'):
            self.fields[key].setEnabled(self.host_kind in ('Beam','Column'))
        self.fields['layers'].setEnabled(self.host_kind in ('Footing','Slab'))
        for key in ('hook_length','hook_ends'):self.fields[key].setEnabled(self.host_kind in ('Footing','Slab','Stair'))
        for key in ('extension_start','extension_end'):self.fields[key].setEnabled(self.host_kind in ('Beam','Column','Stair'))
        for control in self.steel_controls['tie_steel']:control.setEnabled(self.host_kind in ('Beam','Column'))
    def set_params(self,saved):
        from . import steel as C
        for key,controls in self.steel_controls.items():
            record=saved.get(key);controls[0].setCurrentText(record['catalogue'] if record else C.CUSTOM)
            if record:controls[1].setCurrentText(record['size']);controls[2].setCurrentText(record['grade'])
        self.representation.setCurrentText(saved.get('representation','Full'))
        for key,w in self.fields.items():
            if key in saved:w.setValue(saved[key])
        self.timer.stop();self.reviewed_key=None;self.reviewed_specs=None
    def accept_type_recipe(self):
        from . import rebar_recipe as R
        if self.panel.app.scene is not self.bound_scene:raise ValueError('Document changed; reopen the type editor')
        recipe=R.validate(self.host_kind,self.params());self.preview()
        if self.visual.error:raise ValueError(self.visual.error)
        self.accept_recipe(recipe);self.close()
    def load_host_recipe(self):
        from . import rebar_recipe as R,catalogue as C
        row=self.host().ext['thai_bim'].get('member_type')
        if not row or row.get('rebar') is None:raise ValueError('Host has no saved recipe; edit its type and apply that type to this selected host first')
        row=C.snapshot(row);self.set_params(row['rebar']);self.recipe_source=R.source(row)
        self.recipe_label.setText('ชนิด '+row['code']+' revision '+str(row['revision'])+' • รุ่นที่ติดกับ Host • ต้องตรวจพรีวิวก่อนสร้าง')
        self.preview()
    def current_key(self):
        from .workflow import review_key
        # Track the exact host type snapshot too: recipe-only selected updates invalidate review.
        host=self.host()
        return (review_key(host,self.params()),json.dumps(host.ext['thai_bim'].get('member_type'),sort_keys=True),json.dumps(self.recipe_source,sort_keys=True))
    def read_host(self):
        from .workflow import host_token
        scene=self.panel.app.scene;selected=[g for g in scene.selection if g in scene.groups]
        if len(selected)!=1:raise ValueError('เลือกชิ้นคอนกรีต Thai BIM หนึ่งชิ้น')
        host=selected[0];rec=(host.ext or {}).get('thai_bim',{})
        params=rec.get('params') or rec.get('stair_params')
        if params and params.get('stair_schema')==2:raise ValueError('Use advanced Stair / landing reinforcement dialog for this Host')
        if any((g.ext or {}).get('thai_bim',{}).get('slab_rebar_schema') for g in scene.groups if (g.ext or {}).get('thai_bim',{}).get('host_uid')==host.uid):raise ValueError('Use Slab reinforcement / mesh / dowel dialog for this Host')
        if not params or rec.get('kind') not in ('Footing','Column','Beam','Slab','Stair'):raise ValueError('รองรับ RC และบันไดตรงที่สร้างด้วย Thai BIM')
        if params.get('shape')=='polygon':raise ValueError('เหล็กพื้นหลายจุดยังไม่รองรับ; ไม่ใช้ตะแกรงสี่เหลี่ยมแทนขอบเขตจริง')
        host_token(host);self.bound_scene=scene;self.reviewed_key=None;self.reviewed_specs=None
        self.host_uid=host.uid;self.host_params=params;self.host_kind=rec['kind'];self.host_label.setText(host.name)
        from . import rebar_recipe as R
        self.recipe_source=None;self.set_params(R.defaults());self.configure_kind()
        self.recipe_label.setText('รายละเอียดผู้ใช้ • ยังไม่ได้เลือกจากชนิด')
        old=next(((g.ext or {}).get('thai_bim',{}) for g in scene.groups if (g.ext or {}).get('thai_bim',{}).get('host_uid')==host.uid),{})
        if old.get('rebar_params'):
            self.set_params(old['rebar_params']);self.recipe_source=copy.deepcopy(old.get('rebar_recipe_source'))
            self.recipe_label.setText('อ่านรายละเอียดเหล็กเดิมของ Host • '+('ชนิด '+str(self.recipe_source['type_code'])+' revision '+str(self.recipe_source['type_revision']) if self.recipe_source else 'ค่าผู้ใช้'))
        elif (rec.get('member_type') or {}).get('rebar') is not None:
            self.load_host_recipe()
            return
        self.review()
    def host(self):
        from .workflow import host_token
        if self.panel.app.scene is not self.bound_scene:raise ValueError('เอกสารเปลี่ยน: อ่าน Host ในเอกสารนี้ใหม่')
        host=next((g for g in self.panel.app.scene.groups if g.uid==self.host_uid),None)
        if host is None:raise ValueError('กรุณาอ่าน Host ในเอกสารปัจจุบันก่อน')
        rec=host.ext['thai_bim']
        host_token(host)
        if rec['kind']!=self.host_kind:raise ValueError('Host เปลี่ยนชนิด: กดอ่าน Host ใหม่')
        self.host_params=rec.get('params') or rec.get('stair_params');return host
    def steel_picker(self,key,label,field,default):
        from . import steel as C
        catalogue=QComboBox();catalogue.addItems(C.CATALOGUES);size=QComboBox();grade=QComboBox()
        self.steel_controls[key]=(catalogue,size,grade)
        self.form.addRow(label+' มาตรฐาน / ผิว',catalogue);self.form.addRow(label+' ขนาด',size);self.form.addRow(label+' ชั้นคุณภาพ',grade)
        def sync():
            rows=C.entries(catalogue.currentText());size.blockSignals(True);size.clear()
            for row in rows:size.addItem(row['size'],row)
            size.blockSignals(False);grade.clear()
            grade.addItems(['SR24'] if catalogue.currentText()==C.TIS_RB else (['SD30','SD40','SD50'] if catalogue.currentText()==C.TIS_DB else ['Grade 60 [420]','Grade 80 [550]','Grade 100 [690]','Grade 40 [280]']))
            if catalogue.currentText()==C.TIS_DB:grade.setCurrentText('SD40')
            custom=catalogue.currentText()==C.CUSTOM;self.fields[field].setEnabled(custom);size.setEnabled(not custom);grade.setEnabled(not custom);apply()
        def apply():
            if size.currentData():self.fields[field].setValue(size.currentData()['diameter_mm'])
            self.timer.start()
        catalogue.currentTextChanged.connect(sync);size.currentIndexChanged.connect(apply);grade.currentTextChanged.connect(lambda _:self.timer.start())
        catalogue.setCurrentText(C.TIS_RB if default.startswith('RB') else C.TIS_DB);sync();size.setCurrentText(default)
    def params(self):
        from . import steel as C
        p={k:w.value() for k,w in self.fields.items()};p['representation']=self.representation.currentText()
        for key,(catalogue,size,grade) in self.steel_controls.items():
            p[key]=None if catalogue.currentText()==C.CUSTOM else C.selection(catalogue.currentText(),size.currentText(),grade.currentText())
        return p
    def specs(self):
        from .workflow import review_specs
        host=self.host();return review_specs(self.panel.app.scene,host,self.params())[0]
    def preview(self):
        from . import workflow as W
        try:
            if self.recipe_type is not None:
                from . import rebar_recipe as R
                params=R.validate(self.host_kind,self.params());specs=W.bar_specs(self.host_kind,self.host_params,params)
                hostspec=S.stair_spec(**self.host_params) if self.host_kind=='Stair' else E.box_spec(**self.host_params)
                self.visual.display(specs,[hostspec]);self.output.setPlainText('พรีวิวขนาดตัวอย่าง • '+str(len(specs))+' เส้น • ยังไม่สร้างโมเดล\nต้องตรวจขนาดและตำแหน่ง Host จริงอีกครั้งก่อนสร้างเหล็ก')
                return
            host=self.host();specs,token,summary=W.review_specs(self.panel.app.scene,host,self.params())
            if self.recipe_source:
                from . import rebar_recipe as R
                source=R.provenance(self.host_kind,self.recipe_source,self.params())
                self.recipe_label.setText('ชนิด '+source['type_code']+' revision '+str(source['type_revision'])+' • รุ่นที่เรียกมา'+(' • แก้ค่าจากชนิดแล้ว' if source['overridden'] else ' • ค่าตรงกับชนิด'))
            hostspec=S.stair_spec(**self.host_params) if self.host_kind=='Stair' else E.box_spec(**self.host_params)
            self.visual.display(W.P.world_specs(specs,W.pose(host)),W.P.world_specs([hostspec],W.pose(host)))
            self._preview_specs=specs;self._preview_token=token
            ready=self.reviewed_key==self.current_key()
            self.output.setPlainText(f"Host {host.name} • เหล็ก {summary['old_count']} → {summary['new_count']} เส้น\nความยาว {summary['old_m']:.3f} → {summary['new_m']:.3f} m\n"+('ตรวจพรีวิวแล้ว พร้อมสร้าง/อัปเดต' if ready else 'กดตรวจพรีวิวและข้อมูล Host ล่าสุดก่อนสร้าง/อัปเดต')+'\nรองรับย้าย/หมุนแบบ rigid; ไม่รองรับ Scale / mirror / แก้ผิวด้วยมือ')
        except Exception as error:
            self._preview_specs=None;self.visual.invalid(error);self.output.setPlainText(str(error))
    def review(self):
        from .workflow import review_key
        self.preview()
        if self.visual.error:raise ValueError(self.visual.error)
        self.reviewed_key=self.current_key();self.reviewed_specs=self._preview_specs
        self.output.appendPlainText('ตรวจพรีวิวแล้ว • หาก Host/ค่าเปลี่ยน ต้องตรวจใหม่ • ยังไม่ได้แก้โมเดล')
    def build(self,update=False):
        from . import rebar_command
        from .workflow import review_key
        host=self.host();key=self.current_key()
        if key!=self.reviewed_key or self.reviewed_specs is None:raise ValueError('Host หรือค่าเปลี่ยนหลังพรีวิว: กดตรวจพรีวิวและข้อมูล Host ล่าสุดก่อนสร้าง')
        command,count=rebar_command(self.panel.app.scene,host,self.reviewed_specs,self.params(),expected=key[0][0],recipe_source=self.recipe_source)
        self.panel.execute(command);self.output.setPlainText(f'เหล็ก {count} เส้น • Host {host.name}\nกดซ้ำอัปเดตชุดเดิม • Undo ได้ • BBS ใช้รายละเอียดและตำแหน่งที่ตรวจแล้ว')


def open_bbs(panel):
    from . import bbs_records
    from PySide6.QtWidgets import QTableWidget,QTableWidgetItem,QFileDialog
    records,issues=bbs_records(panel.app.scene);tables=D.tables(records,issues)
    old=getattr(panel,'bbs_dialog',None)
    if old is not None:old.close();old.deleteLater()
    dialog=QDialog(panel.app.window);dialog.setWindowTitle('Thai BIM 0.11 — BBS / Bar bending schedule');dialog.resize(1280,780)
    lay=QVBoxLayout(dialog);lay.addWidget(QLabel(f'เหล็กรายละเอียด {len(records)} เส้น • กลุ่มรูปดัด {len(tables[0][1])-1} • รายการต้องตรวจ {len(issues)}'))
    tabs=QTabWidget();lay.addWidget(tabs)
    preview=AssemblyPreview();preview.setMinimumSize(440,220);lay.addWidget(preview)
    caption=QLabel('เลือกแถว BBS เพื่อดูรูปดัด • ชื่อ Shape เป็นรหัสภายใน Thai BIM');caption.setWordWrap(True);lay.addWidget(caption)
    for title,rows in tables:
        table=QTableWidget(len(rows)-1,len(rows[0]));table.setHorizontalHeaderLabels(rows[0]);table.setEditTriggers(QTableWidget.NoEditTriggers)
        for i,row in enumerate(rows[1:]):
            for j,value in enumerate(row):table.setItem(i,j,QTableWidgetItem(f'{value:.6f}' if isinstance(value,float) else str(value)))
        table.resizeColumnsToContents();tabs.addTab(table,title)
        if title=='BBS':
            def pick(row,column=0,previous_row=-1,previous_column=-1):
                if row<0:return
                values=tables[0][1][row+1];host,mark=values[13],values[1]
                g=next((g for g in panel.app.scene.groups if (g.ext or {}).get('thai_bim',{}).get('host_uid')==host and (g.ext or {}).get('thai_bim',{}).get('bbs',{}).get('mark')==mark),None)
                if g is None:preview.invalid('รายการเปลี่ยนแล้ว: กดรีเฟรช');return
                r=g.ext['thai_bim'];faces=[[getattr(v,'position',v).toTuple() for v in f.vertices] for f in g.mesh.faces]
                preview.display([dict(faces=faces,bar_path=r['bar_path'],kind='Rebar')])
                b=r['bbs'];caption.setText(f"{mark} • {b['shape']} • D{b['diameter_mm']:g} • ความยาวตัด {b['length_m']*1000:.2f} mm\nขาตรง tangent {b['straight_mm']} mm • มุมดัด {b['bend_degrees']}° • รัศมีด้านใน {b['inside_radius_mm']:g} mm")
            table.currentCellChanged.connect(pick)
            if records:table.setCurrentCell(next((i for i,v in enumerate(tables[0][1][1:]) if v[2]=='Tie-135'),0),0)
    def export():
        # Re-read the current scene: a modeless dialog can outlive an edit or document switch.
        live,problems=bbs_records(panel.app.scene)
        if not live:raise ValueError('ไม่มีเหล็กรายละเอียดที่ตรวจสอบ Host ได้สำหรับส่งออก')
        path,_=QFileDialog.getSaveFileName(dialog,'Export BBS','Thai-BIM-BBS.xlsx','Excel (*.xlsx)')
        if path:
            if not path.lower().endswith('.xlsx'):path+='.xlsx'
            E.write_xlsx(path,tables=D.tables(live,problems))
    button=QPushButton('ส่งออก BBS Excel จากโมเดลปัจจุบัน');button.clicked.connect(lambda:panel.guard(export));lay.addWidget(button)
    refresh=QPushButton('รีเฟรชจากโมเดลปัจจุบัน');refresh.clicked.connect(lambda:panel.guard(lambda:open_bbs(panel)));lay.addWidget(refresh)
    close=QPushButton('ปิด');close.clicked.connect(dialog.close);lay.addWidget(close)
    panel.bbs_dialog=dialog;dialog.show();return dialog


def add_tools(panel):
    if not getattr(panel,'_v05_tools',False) and getattr(panel,'_v04_tools',False):
        panel._v05_tools=True
        action=panel.toolbar.addAction(icon('QTO'),'BBS / รูปดัดเหล็ก');action.setToolTip('ตารางรูปดัด ความยาวตัด และน้ำหนักเหล็ก')
        action.triggered.connect(lambda checked=False:panel.guard(lambda:open_bbs(panel)))
        panel.workspace_dialog.setWindowTitle('Thai BIM Toolkit 0.10 — รายละเอียดเหล็ก / BBS')
    if getattr(panel,'_v04_tools',False):return
    panel._v04_tools=True
    panel.builder_dialogs={}
    def open_builder(kind):
        if kind=='Stair':
            from .stairs_ui import open_dialog
            return open_dialog(panel)
        if kind=='Rebar' and len(panel.app.scene.selection)==1 and ((next(iter(panel.app.scene.selection)).ext or {}).get('thai_bim',{}).get('stair_params') or {}).get('stair_schema')==2:
            from .stairs_ui import open_dialog
            return open_dialog(panel)
        if kind=='Rebar' and len(panel.app.scene.selection)==1 and next(iter(panel.app.scene.selection)).ext.get('thai_bim',{}).get('kind')=='Slab':
            from .slab_ui import open_dialog
            return open_dialog(panel)
        if kind not in panel.builder_dialogs:panel.builder_dialogs[kind]={'Roof':RoofDialog,'Stair':StairDialog,'Rebar':RebarDialog}[kind](panel)
        d=panel.builder_dialogs[kind];d.show();d.raise_();d.activateWindow()
    panel.open_builder=open_builder
    tabs=next(w for w in panel.findChildren(QTabWidget) if w.tabText(0)=='โครงการ')
    def member(kind):
        tabs.setCurrentIndex(1);panel.kind.setCurrentText(kind)
        for key,value in zip(('x','y','z','width','depth','height'),PRESETS[kind]):panel.mfields[key].setValue(value)
        panel.open_workspace()
    panel.apply_member_preset=lambda:member(panel.kind.currentText())
    grid_x=QComboBox();grid_y=QComboBox();level=QComboBox()
    panel.members.addRow('จุดวาง Grid X',grid_x);panel.members.addRow('จุดวาง Grid Y',grid_y);panel.members.addRow('ระดับฐานชิ้น',level)
    def read_grid():
        grid_x.clear();grid_y.clear();level.clear()
        for v in E.coordinates(panel.gx.text()):grid_x.addItem(f'X {v:g} m',v)
        for v in E.coordinates(panel.gy.text()):grid_y.addItem(f'Y {v:g} m',v)
        for p in E.levels(panel.lv.toPlainText()):level.addItem(f"{p['name']} {p['z']:+.3f} m",p['z'])
    def place_grid():
        if grid_x.currentData() is None or grid_y.currentData() is None or level.currentData() is None:raise ValueError('อ่าน Grid/Level ก่อน')
        centred=panel.kind.currentText() in ('Column','Footing')
        panel.mfields['x'].setValue(grid_x.currentData()-(panel.mfields['width'].value()/2 if centred else 0))
        panel.mfields['y'].setValue(grid_y.currentData()-(panel.mfields['depth'].value()/2 if centred else 0))
        panel.mfields['z'].setValue(level.currentData())
        panel.report.setPlainText('ตั้งจุดวางแล้ว • เสา/ฐานรากใช้ศูนย์กลางตรง Grid; คาน/พื้นใช้มุมฐาน • กดสร้างเมื่อพร้อม')
    panel.button(panel.members,'อ่าน Grid/Level จากช่องโครงการ',read_grid)
    panel.button(panel.members,'ใช้จุดตัด Grid / Level เป็นจุดวาง',place_grid)
    panel.grid_place_controls=(grid_x,grid_y,level);panel.place_grid=place_grid
    read_grid()
    panel.button(panel.members,'ใช้ขนาดตัวอย่างชนิดนี้',panel.apply_member_preset)
    panel.button(panel.members,'เหล็กเสริมของชิ้นที่เลือก…',lambda:open_builder('Rebar'))
    panel.button(panel.members,'บันได RC / ชานพัก / หลายรูปแบบ…',lambda:open_builder('Stair'))
    panel.button(panel.roof,'หลังคาจั่ว / ปั้นหยา / เพิง…',lambda:open_builder('Roof'))
    toolbar=QToolBar('Thai BIM 0.11',panel.app.window);toolbar.setObjectName('thai_bim_toolbar');toolbar.setIconSize(QSize(28,28));toolbar.setMovable(True);toolbar.setFloatable(True)
    panel.app.window.addToolBarBreak(Qt.TopToolBarArea)
    panel.app.window.addToolBar(Qt.TopToolBarArea,toolbar);panel.toolbar=toolbar
    actions=[('Project','โครงการ / Grid / Level',lambda:(tabs.setCurrentIndex(0),panel.open_workspace()))]
    actions += [(k,'สร้าง '+{'Footing':'ฐานราก','Column':'เสา','Beam':'คาน','Slab':'พื้น'}[k],lambda k=k:member(k)) for k in PRESETS]
    actions += [('Stair','บันได RC ตรง',lambda:open_builder('Stair')),('Rebar','เหล็กเสริม Host',lambda:open_builder('Rebar')),
        ('Roof','หลังคาจั่ว / ปั้นหยา / เพิง',lambda:open_builder('Roof')),('Multi','โครงหลังคาจาก IfcRoof',panel.open_multi),
        ('QTO','ปริมาณ / Excel',lambda:(tabs.setCurrentIndex(3),panel.open_workspace())),('Cut','แผนตัดวัสดุ',panel.open_cuts)]
    for k,title,fn in actions:
        action=toolbar.addAction(icon(k),title);action.setToolTip(title);action.triggered.connect(lambda checked=False,fn=fn:panel.guard(fn))
    panel.workspace_dialog.setWindowIcon(icon('Project'));panel.workspace_dialog.setWindowTitle('Thai BIM Toolkit 0.10 — โครงสร้าง / หลังคา / เหล็กเสริม')
    for label in panel.findChildren(QLabel):
        if label.text().startswith('Thai BIM Toolkit'):label.setText('Thai BIM Toolkit 0.10 • โครงสร้าง / หลังคา / เหล็กเสริม')
    for action in panel.app.window.findChildren(type(toolbar.toggleViewAction())):
        if action.text()=='Thai BIM Toolkit…':action.setIcon(icon('Project'))
    # QToolBar has a native visibility action; no private host toolbar API needed.
    panel.app.add_menu_action('แสดงแถบไอคอน Thai BIM',lambda:toolbar.setVisible(True),tip='Thai BIM toolbar')
    add_tools(panel)
