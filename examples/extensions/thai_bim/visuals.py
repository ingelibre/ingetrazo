"""Native Qt illustrations. Preview widgets never write to the model."""
import math
from PySide6.QtCore import Qt, QPointF, QRectF, QTimer
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (QWidget, QDialog, QVBoxLayout, QHBoxLayout,
    QTabWidget, QLabel, QPushButton, QScrollArea)
from . import engine as E

BLUE='#2087a8'; ORANGE='#d88524'; INK='#283e50'


class Illustration(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(420,350)
        self.mode='message'; self.data='เลือกเครื่องมือเพื่อดูภาพประกอบ'; self.error=''

    def display(self, mode, data):
        self.mode=mode; self.data=data; self.error=''; self.update()

    def invalid(self, message):
        self.error=str(message); self.update()

    def paintEvent(self,event):
        p=QPainter(self)
        try:
            p.setRenderHint(QPainter.Antialiasing)
            p.fillRect(self.rect(),QColor('#f3f7fa'))
            scale=min(self.width()/640,self.height()/460)
            p.translate((self.width()-640*scale)/2,(self.height()-460*scale)/2);p.scale(scale,scale)
            p.setPen(QColor(INK));font=p.font();font.setPixelSize(15);p.setFont(font)
            def text(x,y,s,color=INK):
                p.setPen(QColor(color));p.drawText(QPointF(x,y),str(s))
            def line(a,b,color=INK,width=2):
                p.setPen(QPen(QColor(color),width));p.drawLine(QPointF(*a),QPointF(*b))
            def poly(points,color):
                p.setPen(QPen(QColor(INK),1));p.setBrush(QColor(color))
                p.drawPolygon(QPolygonF([QPointF(*a) for a in points]));p.setBrush(Qt.NoBrush)
            if self.error:
                text(25,35,'ยังแสดงพรีวิวไม่ได้',ORANGE)
                p.drawText(QRectF(25,60,590,350),Qt.TextWordWrap,self.error)
                return
            if self.mode=='member':
                d=self.data;w=d['width'];depth=d['depth'];h=d['height']
                scale=215/max(w,depth,h,.01)
                def point(x,y,z):return (270+scale*(x-.65*y),335-scale*(z+.32*y))
                a,b,c,f=[point(*v) for v in [(0,0,0),(w,0,0),(w,depth,0),(0,depth,0)]]
                aa,bb,cc,ff=[point(*v) for v in [(0,0,h),(w,0,h),(w,depth,h),(0,depth,h)]]
                poly([a,f,ff,aa],'#8faab9');poly([a,b,bb,aa],'#b6c9d4');poly([aa,bb,cc,ff],'#d6e2e8')
                text(25,35,'RC '+d['kind']+' • ภาพตามขนาดที่กรอก')
                line(a,b,BLUE,3);line(a,f,ORANGE,3);line(a,aa,'#6971bc',3)
                text(25,385,f"X กว้าง {w:g} m",BLUE);text(230,385,f"Y ลึก {depth:g} m",ORANGE)
                text(440,385,f"Z สูง {h:g} m",'#6971bc')
                text(25,420,f"มุมฐาน ({d['x']:g}, {d['y']:g}, {d['z']:g}) m • {w*depth*h:.4f} m³")
            elif self.mode=='roof':
                planes,specs=self.data
                points=[v for plane in planes for v in plane['vertices']]
                xmin=min(v[0] for v in points);xmax=max(v[0] for v in points)
                ymin=min(v[1] for v in points);ymax=max(v[1] for v in points)
                s=min(530/max(xmax-xmin,.01),300/max(ymax-ymin,.01))
                def xy(v):return (55+(v[0]-xmin)*s,365-(v[1]-ymin)*s)
                text(25,30,'ผังโครงหลังคา • ฉายลงระนาบ XY')
                for plane in planes:poly([xy(v) for v in plane['vertices']],'#e0e9ed')
                for spec in specs:
                    if spec.get('axis'):
                        line(xy(spec['axis'][0]),xy(spec['axis'][1]),BLUE if spec['kind']=='Rafter' else ORANGE,1.5)
                text(25,397,'จันทัน = สีฟ้า',BLUE);text(230,397,'แป = สีส้ม',ORANGE)
                text(25,427,f'{len(planes)} ระนาบ • ขอบเขต X {xmax-xmin:.3f} / Y {ymax-ymin:.3f} m')
            elif self.mode=='gable_section':
                d=self.data;w=d['width'];e=d['overhang'];slope=math.tan(math.radians(d['pitch']))
                scale=min(520/(w+2*e),220/max(w/2*slope,.01))
                x0=60+e*scale;y0=315
                left=(60,y0+e*slope*scale);ridge=(x0+w/2*scale,y0-w/2*slope*scale)
                right=(60+(w+2*e)*scale,left[1])
                text(25,30,'รูปตัดจั่ว • มองตามแนวสัน Y')
                line(left,ridge,BLUE,5);line(ridge,right,BLUE,5)
                line((x0,y0),(x0,y0+40),'#9daeb7',4)
                line((x0+w*scale,y0),(x0+w*scale,y0+40),'#9daeb7',4)
                line((x0,y0),(x0+w*scale,y0),'#9daeb7',1)
                text(25,390,f"กว้างผนัง X {w:g} m • ชายคาข้างละ {e:g} m")
                text(25,420,f"ลาด {d['pitch']:g}° • Z แนวผนัง {d['z']:+.3f} / สัน {d['z']+w/2*slope:+.3f} m")
                text(25,450,'รูปแสดงแนวผิวบนหลังคา • ความหนาและหน้าตัดดูแท็บวัสดุ')
            elif self.mode=='profiles':
                text(25,30,'หน้าตัดที่ใช้สร้างโมเดล • หน่วย mm')
                def section(points,ox,oy,s):poly([(ox+x*s,oy-z*s) for x,z in points],'#63899e')
                section(E.c_profile(),95,220,2000)
                section(E.batten_profile(),435,270,5000)
                line((95,70),(195,70),BLUE,1);text(135,60,'50',BLUE)
                line((75,95),(75,345),BLUE,1);text(30,220,'125',BLUE)
                line((282,300),(588,300),ORANGE,1);text(420,325,'61',ORANGE)
                text(590,225,'27',ORANGE);text(382,115,'20',ORANGE)
                text(30,390,'จันทัน C125×50×20×3.2',BLUE)
                text(330,390,'แป PROFAST ECO 0.7',ORANGE)
                text(325,417,'ฐาน 61 / สูง 27 / หน้าบน 20')
                text(30,447,'รูปพับโดยประมาณ • ภาพสองหน้าตัดใช้สเกลต่างกัน')
            elif self.mode=='cuts':
                plan=self.data;bars=plan['stocks'];stock=plan['stock_m']
                text(25,30,f'ผลคำนวณจริง • สต็อก {stock:g} m • แสดง {min(6,len(bars))}/{len(bars)} เส้น')
                examples=bars if len(bars)<=6 else bars[:2]+bars[-4:]
                for i,bar in enumerate(examples):
                    y=65+i*52;x=85;s=520/stock;marks=[]
                    text(20,y+20,'#'+str(bar['id']))
                    p.fillRect(QRectF(x,y,520,27),QColor('#dce2e6'))
                    for j,piece in enumerate(bar['pieces']):
                        length=piece['length']*s
                        p.fillRect(QRectF(x,y,length,27),QColor(BLUE if j%2==0 else '#6da7ba'))
                        if length>43:text(x+3,y+19,f"{piece['length']:.2f}",'#ffffff')
                        x+=length
                        if piece['kerf']>0:marks.append(x)
                        x+=piece['kerf']*s
                    if bar['remaining']*s>40:text(x+3,y+19,f"{bar['remaining']:.2f}")
                    for mark in marks:line((mark,y),(mark,y+27),ORANGE,1.5)
                text(25,411,'ฟ้า = ชิ้นตัด (m)   ส้ม = รอยตัด   เทา = เศษเหลือ')
                text(25,442,'รอยตัดขยายเพื่อให้มองเห็น • รายการครบอยู่ใน Excel')
            elif self.mode=='grid':
                xs,ys,levels=self.data
                text(25,30,'Grid / Level • ค่าจากช่องกรอก ยังไม่บันทึก')
                sx=260/max(max(xs)-min(xs),1);sy=250/max(max(ys)-min(ys),1)
                for i,x in enumerate(xs[:30]):
                    px=50+(x-min(xs))*sx;line((px,75),(px,325),BLUE,1);text(px,55,str(i+1),BLUE)
                for i,y in enumerate(ys[:30]):
                    py=325-(y-min(ys))*sy;line((50,py),(310,py),BLUE,1);text(20,py,chr(65+i%26),BLUE)
                for i,level in enumerate(levels[:10]):
                    yy=70+i*30;line((355,yy),(610,yy),ORANGE,1)
                    text(360,yy-4,f"{level['name']} {level['z']:+.3f}")
                text(25,405,f'{len(xs)} × {len(ys)} = {len(xs)*len(ys)} จุดตัด')
                text(25,437,'เสาตาม Grid วางศูนย์กลางชิ้นตรงจุดตัด')
            else:
                p.drawText(QRectF(25,40,590,380),Qt.TextWordWrap,str(self.data))
        finally:p.end()


def launcher(panel):
    """Move the existing panel into a modeless dialog; reuse document callbacks."""
    dialog=QDialog(panel.app.window);dialog.setWindowTitle('Thai BIM Toolkit 0.3 — ภาพประกอบและพารามิเตอร์')
    dialog.resize(1100,820);panel.workspace_dialog=dialog
    outer=QVBoxLayout(dialog);panel.setParent(dialog);outer.addWidget(panel)
    tabs=panel.findChildren(QTabWidget)[0]
    layout=panel.layout();layout.removeWidget(tabs)
    row=QHBoxLayout();layout.insertLayout(1,row);row.addWidget(tabs,4)
    tabs.setMinimumWidth(360)
    pane=QWidget();pv=QVBoxLayout(pane);row.addWidget(pane,6)
    panel.preview_tabs=QTabWidget();pv.addWidget(panel.preview_tabs,1)
    panel.visual=Illustration();panel.preview_tabs.addTab(panel.visual,'ภาพประกอบ')
    panel.section_visual=Illustration();panel.preview_tabs.addTab(panel.section_visual,'รูปตัดจั่ว')
    profiles=Illustration();profiles.display('profiles',None);panel.preview_tabs.addTab(profiles,'หน้าตัดวัสดุ')
    panel.visual_help=QLabel();panel.visual_help.setWordWrap(True);pv.addWidget(panel.visual_help)
    panel.report.setMinimumHeight(90);panel.report.setMaximumHeight(160)
    for label in panel.findChildren(QLabel):
        if label.text().startswith('Thai BIM Toolkit'):label.setText('Thai BIM Toolkit 0.3 • ตั้งค่า → ดูภาพ → สร้าง/อัปเดต')
    timer=QTimer(panel);timer.setSingleShot(True);timer.setInterval(180)
    def preview():
        try:
            index=tabs.currentIndex()
            panel.preview_tabs.setTabEnabled(1,index==2);panel.preview_tabs.setTabEnabled(2,index==2)
            if index!=2:panel.preview_tabs.setCurrentIndex(0)
            if index==0:
                panel.visual.display('grid',(E.coordinates(panel.gx.text()),E.coordinates(panel.gy.text()),E.levels(panel.lv.toPlainText())))
                helptext='ตั้ง Grid และ Level แล้วบันทึกค่าประจำโครงการ • หน่วยพิกัดเป็นเมตร'
            elif index==1:
                params={k:w.value() for k,w in panel.mfields.items()};params['kind']=panel.kind.currentText()
                E.box_spec(**params);panel.visual.display('member',params)
                helptext='X/Y/Z คือมุมล่างของชิ้น • สร้างชิ้นใหม่ หรืออ่านชิ้นที่เลือกแล้วอัปเดตเฉพาะชิ้นนั้น'
            elif index==2:
                params={k:w.value() for k,w in panel.rfields.items()};specs=E.roof_specs(**params)
                planes=[{'vertices':spec['faces'][0]} for spec in specs if spec['kind']=='Roof cover']
                panel.visual.display('roof',(planes,specs))
                panel.section_visual.display('gable_section',params)
                helptext=f"จั่วสันตาม Y • มุม {params['pitch']:g}° • Z ที่แนวผนัง {params['z']:g} m\nจันทันตามแนวลาด; ระยะแปวัดตามลาด • เปิดหลังคาหลายระนาบเพื่ออ่านหลังคาในไฟล์"
            else:
                panel.visual.display('message','QTO / ตรวจ\n\n1  สรุปปริมาณจากโมเดล\n2  ตรวจฐานการวัดและข้อสังเกต\n3  ส่งออก Excel หรือ CSV\n\nแผนตัด: เลือกแป/จันทัน → ระบุสต็อก/ทาบ/รอยตัด → คำนวณ → ดูแถบตัด → ส่งออก')
                helptext='Family10 ใช้ metadata เดิมใน QTO • แผนตัดตรวจความยาวตามแกน geometry ที่รองรับ'
            panel.visual_help.setText(helptext)
        except Exception as e:
            panel.visual.invalid(e);panel.section_visual.invalid(e)
            panel.visual_help.setText('แก้ค่าที่กรอกเพื่อดูพรีวิว • ยังไม่ได้สร้างชิ้นงาน')
    timer.timeout.connect(preview);panel.preview_timer=timer
    def schedule(*_):timer.start()
    tabs.currentChanged.connect(schedule);panel.kind.currentTextChanged.connect(schedule)
    for w in list(panel.mfields.values())+list(panel.rfields.values()):w.valueChanged.connect(schedule)
    for w in [panel.gx,panel.gy]:w.textChanged.connect(schedule)
    panel.lv.textChanged.connect(schedule)
    panel.update_visual=preview;preview()
    launch=QWidget();lay=QVBoxLayout(launch)
    label=QLabel('Thai BIM Toolkit '+E.VERSION+'\nเปิดหน้าต่างพร้อมภาพประกอบ\nโครงสร้าง • หลังคา • เหล็กเสริม • QTO');label.setWordWrap(True);lay.addWidget(label)
    b=QPushButton('เปิด Thai BIM พร้อมภาพตัวอย่าง…');lay.addWidget(b);lay.addStretch()
    def show():dialog.show();dialog.raise_();dialog.activateWindow()
    b.clicked.connect(lambda _:show());panel.open_workspace=show
    return launch


def decorate_multi(dialog):
    lay=dialog.layout();form=lay.takeAt(0).layout();lay.removeWidget(dialog.input)
    fields=lay.takeAt(0).layout();lay.removeWidget(dialog.output)
    row=QHBoxLayout();lay.addLayout(row)
    left=QWidget();column=QVBoxLayout(left);column.addLayout(form);column.addLayout(fields);column.addStretch();row.addWidget(left,4)
    right=QWidget();column=QVBoxLayout(right);row.addWidget(right,6)
    tabs=QTabWidget();column.addWidget(tabs)
    dialog.visual=Illustration();tabs.addTab(dialog.visual,'ผังจันทัน / แป')
    profiles=Illustration();profiles.display('profiles',None);tabs.addTab(profiles,'หน้าตัดวัสดุ')
    tabs.addTab(dialog.input,'ขั้นสูง: JSON ระนาบ')
    helptext=QLabel('1 อ่าน IfcRoof → 2 ปรับระยะ → 3 ตรวจพรีวิว → 4 สร้าง/อัปเดต\nภาพแสดงค่าร่างปัจจุบัน • เปลี่ยนผิวอ้างอิงแล้วต้องอ่านระนาบใหม่\nระยะเริ่ม/จบแปวัดตามลาด; offset วัดตั้งฉากระนาบ');helptext.setWordWrap(True);column.addWidget(helptext)
    dialog.output.setMaximumHeight(100);lay.addWidget(dialog.output);dialog.resize(1080,760)
    timer=QTimer(dialog);timer.setSingleShot(True);timer.setInterval(220);dialog.visual_timer=timer
    def update():
        if not dialog.input.toPlainText().strip():
            dialog.visual.display('message','เลือกหลังคา IfcRoof ในโมเดล\nแล้วกดอ่านระนาบที่เลือก\n\nหรืออ่าน IfcRoof ทั้งโครงการ\n\nภาพผังจะแสดงแนวจันทันและแปตามค่าที่กรอก');return
        try:dialog.preview()
        except Exception as e:dialog.visual.invalid(e);dialog.output.setPlainText(str(e))
    timer.timeout.connect(update)
    dialog.input.textChanged.connect(lambda:timer.start())
    for w in dialog.fields.values():w.valueChanged.connect(lambda _:timer.start())
    dialog.surface.currentIndexChanged.connect(lambda _:dialog.output.setPlainText('ผิวอ้างอิงเปลี่ยนแล้ว: กดอ่าน IfcRoof ใหม่ก่อนตรวจพรีวิว'))
    update()


def decorate_cut(dialog):
    lay=dialog.layout();form=lay.takeAt(0).layout();lay.removeWidget(dialog.output)
    row=QHBoxLayout();lay.addLayout(row)
    left=QWidget();col=QVBoxLayout(left);col.addLayout(form);col.addStretch();row.addWidget(left,4)
    dialog.visual=Illustration();row.addWidget(dialog.visual,6);lay.addWidget(dialog.output)
    dialog.output.setMaximumHeight(140);dialog.resize(1080,680)
    def invalidate(*_):
        dialog.visual.display('message','แผนตัดสต็อก\n\n1 เลือกแป หรือจันทัน\n2 ระบุสต็อก / ระยะทาบ / รอยตัด\n3 กดคำนวณแผนตัด\n\nจะแสดงชิ้นตัดและเศษเหลือจากโมเดลจริง\nเปลี่ยนค่าแล้วต้องคำนวณใหม่')
        dialog.output.setPlainText('ยังไม่มีผลคำนวณสำหรับค่าปัจจุบัน')
    for w in dialog.fields.values():w.valueChanged.connect(invalidate)
    dialog.material.currentTextChanged.connect(invalidate);dialog.selected.toggled.connect(invalidate);invalidate()
