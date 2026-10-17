"""Native Composer sheets; explicit source review and reversible set replacement."""
import copy,hashlib,json,math,os,tempfile,uuid
from datetime import datetime,timezone,timedelta
from pathlib import Path
import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QVector3D,QPainter,QPen,QColor
from PySide6.QtWidgets import (QDialog,QWidget,QVBoxLayout,QHBoxLayout,QFormLayout,QLabel,QLineEdit,
    QComboBox,QDoubleSpinBox,QPlainTextEdit,QPushButton,QCheckBox,QFileDialog)
from core.history import Command
from core.group import iter_placements
from core.composition import Composicion,MarcoVista,TextoItem,CotaItem,NivelItem,FormaItem,Cajetin,BarraEscala
from core.saved_views import SavedView
from core.section import SectionPlane
from . import engine as E,drawing_layout as L

def digest(value):
    # Camera reprojection introduces sub-micron paper roundoff, not a user edit.
    def canonical(v):
        if isinstance(v,dict):return {k:canonical(x) for k,x in v.items()}
        if isinstance(v,(list,tuple)):return [canonical(x) for x in v]
        if isinstance(v,(bool,np.bool_)):return bool(v)
        # Native reprojection also converts integer coordinates to floats.
        if isinstance(v,(int,float,np.integer,np.floating)):
            n=round(float(v),4)
            return 0.0 if n==0 else n
        return v
    return hashlib.sha256(json.dumps(canonical(value),sort_keys=True,ensure_ascii=False).encode()).hexdigest()

def sources(scene,selected=False):
    result=[]
    for g in scene.groups:
        record=(g.ext or {}).get('thai_bim') or (g.ext or {}).get('family10') or g.ifc or {}
        cls=record.get('kind',record.get('class',''))
        if selected:
            if g in scene.selection and not g.billboard:result.append(g)
        elif record and cls not in ('Rebar','IfcReinforcingBar') and not g.billboard:result.append(g)
    if not result:raise ValueError('เลือกชิ้นงาน หรือใช้โมเดลที่มี BIM metadata; ไม่รวมคนสเกล')
    return result

def source_info(scene,groups):
    from . import mesh_fingerprint
    if len({g.uid for g in scene.groups})!=len(scene.groups):raise ValueError('Duplicate native group UID')
    points=[];stamp=[];faces=0
    for root in groups:
        if root not in scene.groups:raise ValueError('Drawing source no longer exists')
        for g,m in iter_placements(root):
            pts=np.array([v.position.toTuple() for v in g.mesh.vertices],dtype=float).reshape(-1,3)
            if m is not None and len(pts):
                d=m.data();rot=np.array([[d[0],d[4],d[8]],[d[1],d[5],d[9]],[d[2],d[6],d[10]]])
                pts=pts@rot.T+np.array([d[12],d[13],d[14]])
            if len(pts):points.extend([pts.min(axis=0),pts.max(axis=0)])
            stamp.append([root.uid,g.uid,mesh_fingerprint(g),list(m.data()) if m is not None else None])
            faces+=len(g.mesh.faces)
    if not points:raise ValueError('Selected sources contain no geometry')
    a=np.array(points);bounds=[a.min(axis=0).tolist(),a.max(axis=0).tolist()]
    return dict(bounds=bounds,faces=faces,source_uids=[g.uid for g in groups],
                stamp=digest(dict(groups=[g.uid for g in scene.groups],geometry=stamp)))

def owned(scene,meta):
    ids=set(meta.get('frame_uids',[]));names=set(meta.get('view_names',[]));cuts=set(meta.get('section_uids',[]))
    comps=[c for c in scene.compositions if any(f.uid in ids for f in c.frames)]
    views=[v for v in scene.saved_views if v.name in names];sections=[s for s in scene.section_planes if s.uid in cuts]
    return comps,views,sections

def presentation_hash(parts):return digest([[v.to_dict() for v in seq] for seq in parts])

def render_hash(parts):return digest([[dict(name=c.name,paper=c.paper,landscape=c.landscape,frames=[f.__dict__ for f in c.frames]) for c in parts[0]],
    [v.to_dict() for v in parts[1]],[s.to_dict() for s in parts[2]]])

def validate_set(scene):
    meta=(scene.plugin_data.get('thai_bim') or {}).get('drawing_set')
    if not meta:raise ValueError('สร้างชุดแบบ Thai BIM ก่อน')
    parts=owned(scene,meta)
    if render_hash(parts)!=meta['render_hash']:raise ValueError('Frame / view / section edited: grid positions may be stale; restore the view or preserve your edits in a separate sheet set')
    byuid={g.uid:g for g in scene.groups}
    if any(uid not in byuid for uid in meta['source_uids']):raise ValueError('Drawing source missing; review and update sheets')
    info=source_info(scene,[byuid[uid] for uid in meta['source_uids']])
    if info['stamp']!=meta['source_stamp']:raise ValueError('โมเดลเปลี่ยนหลังสร้างแบบ: ตรวจพรีวิวและอัปเดตชุด Sheet ก่อนส่งออก')
    return parts,meta

def create_parts(scene,groups,options,set_uid):
    cfg=L.config(options['bounds'],options['grid_x'],options['grid_y'],options['levels'],options['paper'],
        options['cut_z'],options['section_x'],options['views'],options.get('datum',0))
    prefix='TBIM-'+set_uid[:8];comps=[];views=[];sections=[]
    allowed={g.uid for root in groups for g,_ in iter_placements(root)}
    hidden=[uid for uid in scene.groups_by_uid() if uid not in allowed]
    for s in cfg['sheets']:
        key=s['key'];code=s['code'];cut=None
        if key=='plan':cut=SectionPlane(QVector3D(0,0,cfg['cut_z']),QVector3D(0,0,1),name=prefix+' Plan cut',symbol='P')
        if key=='section':cut=SectionPlane(QVector3D(cfg['section_x'],0,0),QVector3D(1,0,0),name=prefix+' Section A-A',symbol='A')
        if cut:sections.append(cut)
        sv=SavedView(prefix+' '+code,target=s['target'],yaw=s['yaw'],pitch=s['pitch'],perspective=False,
            hidden_objects=hidden,hidden_shown={'objects':False,'geometry':False},
            georef={'base_map':False,'terrain':False,'photomesh':False},
            section={'active':cut.uid if cut else None,'planes_shown':False,'cuts_shown':True})
        views.append(sv);pw,ph=cfg['paper_size'];x,y,w,h=s['frame']
        comp=Composicion(name=prefix+' '+code+' '+s['title'],paper=cfg['paper'],landscape=True,margin_mm=10,border=True)
        frame=MarcoVista(x_mm=x,y_mm=y,w_mm=w,h_mm=h,scale_n=50,view_key='scene:'+sv.name,
            uid=uuid.uuid4().hex,style=options['style'],cam_target=s['target'],paper_bg=True,
            perspective=False,shadows=False,show_title=False,annotations=False,pen_cut_mm=.5,pen_profile_mm=.35,pen_edge_mm=.18,
            cut_fill='hatch',cut_hatch_mm=1.2,locked=True)
        comp.frames=[frame]
        def text(tx,ty,tw,value,size=8,bold=False,align='left'):
            comp.texts.append(TextoItem(x_mm=tx,y_mm=ty,w_mm=tw,text=value,size_pt=size,bold=bold,align=align,family='Arial',z=20,locked=True))
        def line(a,b,weight=.18,kind='linea'):
            ax,ay=a;bx,by=b
            comp.shapes.append(FormaItem(kind=kind,x_mm=min(ax,bx),y_mm=min(ay,by),w_mm=abs(bx-ax),h_mm=abs(by-ay),
                invert=bool((bx-ax)*(by-ay)<0),stroke_mm=weight,color='#505050',z=10,locked=True))
        def dash(a,b):
            length=math.dist(a,b)
            for start in np.arange(0,length,4):
                line(tuple(a[i]+(b[i]-a[i])*start/length for i in range(2)),tuple(a[i]+(b[i]-a[i])*min(start+2.7,length)/length for i in range(2)),.13)
        def bubble(px,py,label):
            comp.shapes.append(FormaItem(kind='elipse',x_mm=px-3,y_mm=py-3,w_mm=6,h_mm=6,stroke_mm=.2,
                fill=True,fill_color='#ffffff',z=15,locked=True))
            text(px-3,py-1.7,6,label,7,True,'center')
        def project(p):return L.project(s,p)
        def dim(a,b,offset,axis):
            pa,pb=project(a),project(b)
            if axis=='h' and pa[0]>pb[0] or axis=='v' and pa[1]>pb[1]:pa,pb=pb,pa;a,b=b,a
            comp.cotas.append(CotaItem(x_mm=pa[0],y_mm=pa[1],dx_mm=pb[0]-pa[0],dy_mm=pb[1]-pa[1],scale_n=50,
                sep_mm=offset,offset_mm=1.5,text_mm=2.4,units='mm',decimals=0,ends='tick',stroke_mm=.18,
                anchor_uid=frame.uid,a_world=list(a),b_world=list(b),axis=axis,text_bg='#ffffff',z=20,locked=True,group_id='thai_bim_reference'))
        lo,hi=cfg['bounds'];horizontal=cfg['grid_x'] if key in ('plan','roof','front') else cfg['grid_y']
        axis=0 if key in ('plan','roof','front') else 1
        for i,value in enumerate(horizontal):
            p=list(s['target']);p[axis]=value;px,_=project(p)
            dash((px,y+5),(px,y+h-5));bubble(px,y+5,L.grid_label(i) if axis==0 else str(i+1))
        if key in ('plan','roof'):
            for i,value in enumerate(cfg['grid_y']):
                p=list(s['target']);p[1]=value;_,py=project(p)
                dash((x+5,py),(x+w-5,py));bubble(x+5,py,str(i+1))
            for vals,axis_d in [(cfg['grid_x'],0),(cfg['grid_y'],1)]:
                for i,(a,b) in enumerate(zip(vals,vals[1:])):
                    p=list(lo);q=list(lo);p[2]=q[2]=s['target'][2];p[axis_d]=a;q[axis_d]=b
                    if (b-a)*20>=8:dim(p,q,14 if axis_d==0 else -14,'h' if axis_d==0 else 'v')
            a=[lo[0],lo[1],s['target'][2]];b=[hi[0],lo[1],s['target'][2]];c=[lo[0],hi[1],s['target'][2]]
            dim(a,b,26,'h');dim(a,c,-26,'v')
            if key=='plan' and 'section' in options['views']:
                p=[cfg['section_x'],lo[1],cfg['cut_z']];q=[cfg['section_x'],hi[1],cfg['cut_z']]
                dash(project(p),project(q));text(project(p)[0]+4,project(p)[1]+5,45,'A / A301',7,True)
                for point in (p,q):
                    end=list(point);end[0]-=.35;line(project(point),project(end),.3,'flecha')
        else:
            for i,(a,b) in enumerate(zip(horizontal,horizontal[1:])):
                p=list(lo);q=list(lo);p[axis]=a;q[axis]=b
                if (b-a)*20>=8:dim(p,q,15,'h')
            p=list(lo);q=list(lo);q[axis]=hi[axis];dim(p,q,26,'h')
            levels=L.level_positions(s,cfg['levels'])
            for level,py,label_y in levels:
                world=list(s['target']);world[axis]=hi[axis];world[2]=level['z'];px,_=project(world)
                symbol_x=x+w+4
                comp.niveles.append(NivelItem(x_mm=symbol_x,y_mm=label_y,ax_mm=px-symbol_x,ay_mm=py-label_y,
                    text=level['name']+' {z}',z_m=level['z'],datum_m=cfg['datum'],decimals=3,size_mm=2.4,line_mm=16,
                    anchor_uid=frame.uid,a_world=world,z=20,locked=True,group_id='thai_bim_reference'))
        text(18,17,pw-36,options['name']+' | '+code+' | '+s['title'],12,True)
        text(18,28,pw-36,'MODEL-BASED COORDINATION DRAWING | 1:50 | Dimensions: mm / Levels: m',8)
        text(18,ph-67,pw-36,'Automatic dimensions: grid spacing and source model extents. Add member/opening dimensions in Composer.',7.5)
        text(18,ph-61,pw-36,'Grid/levels: user project input. Model edits require explicit sheet review and update. Print at 100% actual size.',7.5)
        if any((b-a)*20<8 for vals in (cfg['grid_x'],cfg['grid_y']) for a,b in zip(vals,vals[1:])):
            text(18,ph-55,pw-36,'Close grid dimensions omitted to keep labels legible; add staggered dimensions manually.',7.5)
        comp.cajetin=Cajetin(x_mm=pw-212,y_mm=ph-43,w_mm=202,h_mm=33,columns=2,
            campos=[['PROJECT',options['name']],['DRAWING',s['title']],['SHEET',code],['SCALE','1:50 @ '+cfg['paper']],
                ['DATE',options['date']],['REVISION',options['revision']],['AUTHOR',options['author']],['STATUS','FOR COORDINATION']])
        comp.scalebars.append(BarraEscala(x_mm=18,y_mm=ph-22,scale_n=50,segments=4,z=20,locked=True))
        text(18,ph-34,170,'Scale check: 1 m = 20 mm on paper',8)
        comps.append(comp)
    return (comps,views,sections),cfg

class DrawingSet(Command):
    def __init__(self,scene,groups,options,expected):
        self.scene=scene;self.groups=list(groups);self.info=source_info(scene,groups)
        if self.info['stamp']!=expected:raise ValueError('Sources changed after preview')
        self.before=(list(scene.compositions),list(scene.saved_views),list(scene.section_planes),copy.deepcopy(scene.plugin_data))
        self.before_hash=presentation_hash(self.before[:3])
        old=(scene.plugin_data.get('thai_bim') or {}).get('drawing_set');old_parts=([],[],[])
        if old:
            old_parts=owned(scene,old)
            if presentation_hash(old_parts)!=old['presentation_hash']:raise ValueError('Edited sheet set will not be overwritten; preserve or undo manual edits first')
        uid=old['id'] if old else uuid.uuid4().hex
        opts=copy.deepcopy(options);opts['bounds']=self.info['bounds'];self.parts,self.layout=create_parts(scene,groups,opts,uid)
        remaining=[[x for x in seq if x not in removed] for seq,removed in zip(self.before[:3],old_parts)]
        if any(v.name==n.name for v in remaining[1] for n in self.parts[1]):raise ValueError('Saved-view name collision')
        data=copy.deepcopy(self.before[3]);project=data.setdefault('thai_bim',{})
        project['drawing_set']=dict(schema=1,id=uid,options=opts,source_uids=self.info['source_uids'],source_stamp=self.info['stamp'],
            frame_uids=[f.uid for c in self.parts[0] for f in c.frames],view_names=[v.name for v in self.parts[1]],
            section_uids=[s.uid for s in self.parts[2]],presentation_hash=presentation_hash(self.parts),render_hash=render_hash(self.parts))
        self.after=tuple(a+b for a,b in zip(remaining,self.parts))+(data,)
    def do(self,scene):
        if scene is not self.scene or source_info(scene,self.groups)['stamp']!=self.info['stamp']:raise ValueError('Drawing source changed before commit')
        if any(list(now)!=old for now,old in zip((scene.compositions,scene.saved_views,scene.section_planes),self.before[:3])) or scene.plugin_data!=self.before[3] or presentation_hash((scene.compositions,scene.saved_views,scene.section_planes))!=self.before_hash:raise ValueError('Document changed before sheet commit')
        scene.compositions,scene.saved_views,scene.section_planes=map(list,self.after[:3]);scene.plugin_data=copy.deepcopy(self.after[3])
    def undo(self,scene):
        scene.compositions,scene.saved_views,scene.section_planes=map(list,self.before[:3]);scene.plugin_data=copy.deepcopy(self.before[3])

def composer(panel):
    c=panel.app.window._ensure_composer()
    if not getattr(c,'_tbim_visibility_guard',False):
        original=c._with_frame_camera
        def guarded(frame,fn):
            scene=panel.app.scene;keep=[(g,g.hidden) for g in scene.groups_by_uid().values()]
            flags=(scene.show_hidden_objects,scene.show_hidden_geometry)
            # Native Composer shares geometry between views; selected objects and cuts can differ.
            c._invalidate_geometry_caches()
            try:return original(frame,fn)
            finally:
                for g,hidden in keep:g.hidden=hidden
                scene.show_hidden_objects,scene.show_hidden_geometry=flags
                scene._bounds_cache=None
        c._with_frame_camera=guarded;c._tbim_visibility_guard=True
        original_project=c._reproject_anchored_cotas
        def reference_project():
            comp=c.comp;all_dims=comp.cotas;all_levels=comp.niveles
            refs=[v for v in all_dims+all_levels if v.group_id=='thai_bim_reference']
            comp.cotas=[v for v in all_dims if v not in refs];comp.niveles=[v for v in all_levels if v not in refs]
            try:original_project()
            finally:comp.cotas=all_dims;comp.niveles=all_levels
            frames={f.uid:f for f in comp.frames}
            for v in refs:
                f=frames.get(v.anchor_uid)
                if f is None:continue
                if isinstance(v,CotaItem):
                    a,b=c._frame_world_to_page(f,[v.a_world,v.b_world])
                    v.x_mm,v.y_mm=a;v.dx_mm=b[0]-a[0];v.dy_mm=b[1]-a[1];v.scale_n=f.scale_n
                else:
                    a,=c._frame_world_to_page(f,[v.a_world]);v.x_mm=a[0]-v.ax_mm;v.y_mm=a[1]-v.ay_mm
        # Grids/levels are explicit project references, never nearby geometry snaps.
        c._reproject_anchored_cotas=reference_project
    return c

def show_set(panel):
    parts,_=validate_set(panel.app.scene);c=composer(panel);c._reload_comp_combo()
    c.show_sheet(panel.app.scene.compositions.index(parts[0][0]));panel.app.window._refresh_sheet_tabs();return c

def export_set(panel,path):
    scene=panel.app.scene;parts,_=validate_set(scene);c=composer(panel);path=Path(path).with_suffix('.pdf')
    if not path.parent.exists():raise ValueError('Export folder does not exist')
    handle,temp=tempfile.mkstemp(suffix='.pdf',prefix='thai-bim-',dir=path.parent);os.close(handle)
    keep=scene.compositions;old=c.comp
    try:
        scene.compositions=parts[0]
        for comp in parts[0]:
            c.comp=comp;c._reproject_anchored_cotas()
        errors=c.export_all_pdf(temp)
        if errors or Path(temp).stat().st_size<100:raise ValueError('PDF render failed: '+', '.join(errors))
        os.replace(temp,path)
    finally:
        scene.compositions=keep;c.comp=old
        if Path(temp).exists():Path(temp).unlink()
    return path

class PaperPreview(QWidget):
    def __init__(self):super().__init__();self.layout=None;self.setMinimumSize(500,330)
    def paintEvent(self,event):
        p=QPainter(self);p.fillRect(self.rect(),QColor('#132a3b'))
        if self.layout:
            pw,ph=self.layout['paper_size'];k=min((self.width()-30)/pw,(self.height()-30)/ph)
            p.translate(15,15);p.scale(k,k);p.fillRect(0,0,pw,ph,QColor('white'));p.setPen(QPen(QColor('#333333'),.6))
            p.drawRect(10,10,pw-20,ph-20);x,y,w,h=self.layout['sheets'][0]['frame'];p.drawRect(x,y,w,h)
            p.drawText(18,25,self.layout['sheets'][0]['title']+' | 1:50');p.drawRect(pw-212,ph-43,202,33)
            p.drawText(pw-205,ph-24,'PROJECT / SHEET / SCALE / REVISION');p.drawText(18,ph-60,'Paper layout preview - open Composer for actual model lines')
        p.end()

class DrawingDialog(QDialog):
    def __init__(self,panel):
        super().__init__(panel.app.window);self.panel=panel;self.reviewed=None;self.setWindowTitle('Thai BIM '+E.VERSION+' - Sheets 1:50');self.resize(1120,740)
        main=QVBoxLayout(self);row=QHBoxLayout();main.addLayout(row);form=QFormLayout();row.addLayout(form);self.preview=PaperPreview();row.addWidget(self.preview,1)
        self.fields={}
        for key,label,value in [('name','โครงการ',panel.name.text()),('author','ผู้จัดทำ',''),('revision','Revision','01'),
            ('date','วันที่บนแบบ (แก้ได้)',datetime.now(timezone(timedelta(hours=7))).date().isoformat()),('grid_x','Grid X (m)',panel.gx.text()),('grid_y','Grid Y (m)',panel.gy.text())]:
            self.fields[key]=QLineEdit(value);form.addRow(label,self.fields[key])
        self.levels=QPlainTextEdit(panel.lv.toPlainText());self.levels.setMaximumHeight(120);form.addRow('Level: ชื่อ=เมตร',self.levels)
        self.scope=QComboBox();self.scope.addItems(['ชิ้นที่เลือก','ทั้งหมดที่มี BIM metadata (ไม่รวมเหล็ก)']);self.scope.setCurrentIndex(0 if panel.app.scene.selection else 1);form.addRow('ขอบเขตแบบ',self.scope)
        self.paper=QComboBox();self.paper.addItems(list(L.PAPERS));form.addRow('กระดาษ Landscape / 1:50',self.paper)
        self.style=QComboBox();self.style.addItems(['Technical (large models)','Vector (small models)']);form.addRow('เส้นแบบ',self.style)
        self.cut=QDoubleSpinBox();self.cut.setRange(-1000,1000);self.cut.setDecimals(3);self.cut.setValue(1.5);form.addRow('ระดับตัดแปลน (m)',self.cut)
        self.section=QDoubleSpinBox();self.section.setRange(-1000,1000);self.section.setDecimals(3);form.addRow('ตำแหน่งรูปตัด X (m)',self.section)
        self.datum=QDoubleSpinBox();self.datum.setRange(-1000,1000);self.datum.setDecimals(3);form.addRow('Datum ระดับอ้างอิง (m)',self.datum)
        self.views={}
        for key,(_,title,_,_) in L.VIEWS.items():
            w=QCheckBox(title);w.setChecked(True);self.views[key]=w;form.addRow(w)
        self.report=QLabel('กำหนด Grid/Level และขอบเขต แล้วตรวจพรีวิวก่อนสร้าง; มิติอัตโนมัติเป็นระยะ Grid/ขอบเขตโมเดล\nSheet ตั้งต้นสำหรับประสานแบบ; เพิ่มมิติผนัง/ช่องเปิด/รายละเอียดเฉพาะใน Composer');self.report.setWordWrap(True);main.addWidget(self.report)
        for label,fn in [('ตรวจพรีวิว / ขนาดกระดาษ',self.review),('สร้าง / อัปเดตชุด Sheet ที่ตรวจแล้ว',self.build),('เปิดชุดแบบใน Composer',lambda:show_set(panel)),('ส่งออกชุดนี้ PDF…',self.export)]:
            b=QPushButton(label);b.clicked.connect(lambda checked=False,fn=fn:panel.guard(fn));main.addWidget(b)
        old=(panel.app.scene.plugin_data.get('thai_bim') or {}).get('drawing_set')
        if old:
            opts=old['options']
            for key in self.fields:
                if key in opts and key not in ('grid_x','grid_y'):self.fields[key].setText(str(opts[key]))
            self.paper.setCurrentText(opts['paper']);self.section.setValue(opts['section_x']);self.cut.setValue(opts['cut_z']);self.datum.setValue(opts.get('datum',0))
            self.style.setCurrentIndex(int(opts['style']=='vectorial'))
            for key,w in self.views.items():w.setChecked(key in opts['views'])
        else:
            try:info=source_info(panel.app.scene,sources(panel.app.scene,self.scope.currentIndex()==0));self.section.setValue(sum(v[0] for v in info['bounds'])/2)
            except ValueError:pass
    def options(self):
        opts={key:w.text().strip() for key,w in self.fields.items()}
        if not opts['name'] or len(opts['name'])>60 or any(len(opts[k])>40 for k in ('author','revision','date')):raise ValueError('Project 1–60 characters; author/revision/date <=40')
        opts.update(grid_x=E.coordinates(opts['grid_x']),grid_y=E.coordinates(opts['grid_y']),levels=E.levels(self.levels.toPlainText()),
            paper=self.paper.currentText(),cut_z=self.cut.value(),section_x=self.section.value(),datum=self.datum.value(),
            views=[key for key,w in self.views.items() if w.isChecked()],style='vectorial' if self.style.currentIndex() else 'tecnico',scope=self.scope.currentIndex())
        return opts
    def review(self):
        scene=self.panel.app.scene;groups=sources(scene,self.scope.currentIndex()==0);info=source_info(scene,groups);opts=self.options()
        if opts['style']=='vectorial' and info['faces']>5000:raise ValueError('Vector HLR limited to 5000 faces here; use Technical or select fewer objects')
        opts['bounds']=info['bounds'];cfg=L.config(info['bounds'],opts['grid_x'],opts['grid_y'],opts['levels'],opts['paper'],opts['cut_z'],opts['section_x'],opts['views'],opts['datum'])
        for s in cfg['sheets']:
            if s['key'] not in ('plan','roof'):L.level_positions(s,cfg['levels'])
        self.reviewed=(scene,groups,info,opts);self.preview.layout=cfg;self.preview.update()
        self.report.setText(f"ตรวจแล้ว {len(groups)} ชิ้น / {info['faces']:,} faces / {len(cfg['sheets'])} Sheets / {opts['paper']} / 1:50\n1 m = 20 mm บนกระดาษ; โมเดลเปลี่ยนต้องอัปเดต Sheet ก่อนส่งออก")
    def build(self):
        if not self.reviewed:raise ValueError('ตรวจพรีวิวก่อนสร้าง')
        scene,groups,info,opts=self.reviewed
        if scene is not self.panel.app.scene or self.options()!= {k:v for k,v in opts.items() if k!='bounds'} or [g.uid for g in sources(scene,self.scope.currentIndex()==0)]!=[g.uid for g in groups]:raise ValueError('Options / selection / document changed; review again')
        cmd=DrawingSet(scene,groups,opts,info['stamp']);self.panel.execute(cmd);self.report.setText('สร้างชุด Sheet แล้ว; เปิดใน Composer หรือส่งออก PDF ได้')
    def export(self):
        validate_set(self.panel.app.scene)
        path,_=QFileDialog.getSaveFileName(self,'ส่งออกชุดแบบ 1:50','Thai-BIM-drawings.pdf','PDF (*.pdf)')
        if path:self.report.setText('ส่งออกแล้ว: '+str(export_set(self.panel,path)))

def open_dialog(panel):
    selected=panel.app.scene.selection
    if len(selected)==1 and next(iter(selected)).ext.get('thai_bim',{}).get('kind') in ('Footing','Column','Beam','Slab'):
        from .member_drawings import open_dialog as member_dialog
        return member_dialog(panel)
    if len(selected)==1 and next(iter(selected)).ext.get('thai_bim',{}).get('stair_params',{}).get('stair_schema')==2:
        from .stair_drawings import open_dialog as stair_dialog
        return stair_dialog(panel)
    old=getattr(panel,'drawing_dialog',None)
    if old:old.close();old.deleteLater()
    d=DrawingDialog(panel);panel.drawing_dialog=d;d.show();return d

def install(panel):
    if getattr(panel,'_drawing_tools',False):return
    from .builders import icon
    panel._drawing_tools=True;a=panel.toolbar.addAction(icon('Sheet'),'Sheets 1:50 / Grid / Level / Dimensions')
    a.triggered.connect(lambda checked=False:panel.guard(lambda:open_dialog(panel)))
