"""Native editable stair sheets, actual-cage BBS, source status and safe updates."""
import copy,json,math,uuid,os,tempfile
from pathlib import Path
from datetime import datetime
from PySide6.QtCore import Qt,QPointF
from PySide6.QtGui import QPainter,QPen,QColor,QVector3D
from PySide6.QtWidgets import QDialog,QWidget,QVBoxLayout,QHBoxLayout,QFormLayout,QLabel,QComboBox,QLineEdit,QDoubleSpinBox,QPushButton,QTableWidget,QTableWidgetItem,QCheckBox,QFileDialog
from core.history import Command
from core.group import world_mesh
from core.composition import Composicion,TextoItem,FormaItem,CotaItem,NivelItem,BarraEscala
from . import stair_drawing_geometry as G,stair_connection_ui as C,workflow as W,placement as P,drawings as D,analytical as A,engine as E,detailing as B
KEY='thai_bim_stair_drawing_sets'
REASONS={'Drawing generator version changed':'รุ่นเครื่องมือเปลี่ยน ต้องอัปเดต','Sheet missing':'Sheet ถูกลบ','Generated items edited: update will archive a full copy':'แก้ส่วนอัตโนมัติ: อัปเดตจะเก็บสำเนาเดิม','Concrete / placement / levels changed':'คอนกรีต/ตำแหน่ง/ระดับเปลี่ยน','Cage / Bar Marks / BBS changed':'เหล็ก/Bar Mark/BBS เปลี่ยน','Preserved manual details require review':'ต้องตรวจรายละเอียดที่คงไว้'}
def steel_label(b):
    s=b.get('steel') or {}
    return ' '.join(str(s.get(k,'')) for k in ('catalogue','size','grade')).strip() or 'Nominal diameter; grade unspecified'

LISTS=('frames','texts','images','scalebars','nortes','leyendas','shapes','cotas','cotas_ang','cotas_rad','etiquetas','perfiles','niveles','llamadas')

def local(p,m):return tuple(sum(m[j*4+i]*(p[j]-m[j*4+3]) for j in range(3)) for i in range(3))
def source(scene,uid,steel=True):
    g=C.host(scene,uid);m=P.rigid_matrix(W.pose(g))
    if any(abs(m[i]-v)>1e-5 for i,v in zip((2,6,8,9,10),(0,0,0,0,1))):raise ValueError('Stair sheets require upright Stair (yaw/translation only); tilted stairs need an explicit drawing frame')
    mesh=world_mesh(g);faces=[[local(v.toTuple(),m) for v in f.vertices] for f in mesh.faces]
    triangles=[[local(p.toTuple(),m) for p in tri] for f in mesh.faces for tri in f.triangulate()]
    if len(triangles)>12000:raise ValueError('Stair sheet source limited to 12000 concrete triangles')
    bars=[]
    if steel:
        byuid={b.uid:b for b in scene.groups}
        for row in C.bars(scene,g,'Actual'):
            b=byuid[row['bar_uid']];r=b.ext['thai_bim'];bbs=copy.deepcopy(r['bbs'])
            if abs(E.finite(bbs['length_m'])-E.finite(r['quantity']))>1e-8:raise ValueError('Actual cage has inconsistent cut length')
            bars.append(dict(uid=b.uid,bbs=bbs,path=[local(p,m) for p in row['path']]))
        if sum(len(b['path']) for b in bars)>150000:raise ValueError('Stair bar paths too large for detailing sheets')
    geom=A.digest(dict(token=W.host_token(g),name=g.name,faces=faces,triangles=triangles))
    barstamp=A.digest(bars)
    return dict(uid=g.uid,name=g.name,params=copy.deepcopy(g.ext['thai_bim']['stair_params']),pose=m,base_z=m[11],faces=faces,triangles=triangles,bars=bars,geom=geom,bars_stamp=barstamp,stamp=A.digest([geom,barstamp]))

def marker(setid,key):return 'TBIM-STAIR-SHEET:'+setid+':'+key

def auto_hash(comp,tag):
    d=comp.to_dict();out={k:copy.deepcopy(getattr(comp,k)) for k in ('name','paper','landscape','margin_mm','border','border_mm','border_color','border_style','border_radius_mm')}
    for k in LISTS:out[k]=[v for v in d.get(k,[]) if v.get('group_id')==tag]
    if d.get('cajetin',{}):out['cajetin']=d['cajetin'] if d['cajetin'].get('group_id')==tag else None
    return D.digest(out)

def find_sheet(scene,row):
    candidates=[c for c in scene.compositions if any(getattr(i,'group_id','')==row['marker'] for i in c.all_items()) or c.name==row['name']]
    exact=[c for c in candidates if c.name==row['name']]
    if len(exact)==1:return exact[0]
    if len(candidates)>1:raise ValueError('Ambiguous copied stair sheet; rename/detach the copied managed items')
    return candidates[0] if candidates else None

def manual_items(comp,tag):return [v for v in comp.all_items() if getattr(v,'group_id','')!=tag]

def status(scene,uid,backend=None):
    backend=backend or STAIR_BACKEND;key=backend.key
    meta=(scene.plugin_data.get(key) or {}).get(uid)
    if not meta:return []
    try:info=backend.source(scene,uid,meta['steel']);failure=None
    except ValueError as e:info=None;failure=str(e)
    out=[]
    for row in meta['sheets']:
        comp=find_sheet(scene,row);reasons=[]
        if meta.get('generator_version')!=E.VERSION:reasons.append('Drawing generator version changed')
        if comp is None:reasons.append('Sheet missing')
        elif auto_hash(comp,row['marker'])!=row['auto_hash']:reasons.append('Generated items edited: update will archive a full copy')
        if info is None:reasons.append(failure)
        else:
            if info['geom']!=meta['geom']:reasons.append('Concrete / placement / levels changed')
            if row['steel'] and info['bars_stamp']!=meta['bars_stamp']:reasons.append('Cage / Bar Marks / BBS changed')
        if row.get('manual_pending'):reasons.append('Preserved manual details require review')
        out.append(dict(key=row['key'],name=row['name'],reasons=reasons,manual=len(manual_items(comp,row['marker'])) if comp else 0))
    return out

def validate(scene,uid,backend=None):
    backend=backend or STAIR_BACKEND
    rows=status(scene,uid,backend)
    if not rows:raise ValueError('Create Stair sheets first')
    bad=[r for r in rows if r['reasons']]
    if bad:raise ValueError('Review/update before export: '+'; '.join(r['key']+': '+', '.join(r['reasons']) for r in bad))
    meta=scene.plugin_data[backend.key][uid];return [find_sheet(scene,r) for r in meta['sheets']],meta

def sheet(view,opts,setid,key):
    paper,pp=G.paper_view(view,opts);pw,ph=paper['paper_size'];tag=marker(setid,key)
    c=Composicion(name='TBIM '+view.get('sheet_family','Stair')+' '+setid[:8]+' '+key,paper=opts['paper'],landscape=True,margin_mm=10,border=True)
    def text(x,y,w,value,size=8,bold=False,align='left'):
        c.texts.append(TextoItem(x_mm=x,y_mm=y,w_mm=w,text=str(value),size_pt=size,bold=bold,align=align,family='Arial',z=25,locked=True,group_id=tag))
    def line(a,b,weight=.18,color='#202020',arrow=False):
        ax,ay=a;bx,by=b
        if math.dist(a,b)<1e-5:return
        c.shapes.append(FormaItem(kind='linea',x_mm=min(ax,bx),y_mm=min(ay,by),w_mm=abs(bx-ax),h_mm=abs(by-ay),invert=(bx-ax)*(by-ay)<0,stroke_mm=weight,color=color,z=10 if weight<.2 else 15,locked=True,group_id=tag))
    for l in sorted(paper['lines'],key=lambda l:l.get('weight',.18)):
        a,b=l['a'],l['b'];weight=l.get('weight',.18);color=l.get('color','#202020');length=math.dist(a,b)
        if l.get('dash') and length:
            for step in range(math.ceil(length/4)):
                lo=step*4;hi=min(lo+2.6,length)
                line(tuple(a[i]+(b[i]-a[i])*lo/length for i in range(2)),tuple(a[i]+(b[i]-a[i])*hi/length for i in range(2)),weight,color)
        else:line(a,b,weight,color)
        if l.get('arrow') and length:
            ux,uy=(b[0]-a[0])/length,(b[1]-a[1])/length
            for sign in (-1,1):line(b,(b[0]-3*ux+sign*1.1*uy,b[1]-3*uy-sign*1.1*ux),weight,color)
    for t in paper['texts']:text(t['point'][0]-3,t['point'][1]-1.5,6,t['text'],t.get('size',6),align='center')
    for d in paper['dims']:
        a,b=d['a'],d['b'];c.cotas.append(CotaItem(x_mm=a[0],y_mm=a[1],dx_mm=b[0]-a[0],dy_mm=b[1]-a[1],scale_n=opts['scale'],sep_mm=d['offset'],offset_mm=1.5,text=d['text'],text_mm=2.2,units='mm',decimals=1,ends='tick',stroke_mm=.18,text_bg='#ffffff',locked=True,group_id=tag,z=30))
    for l in paper['levels']:
        x,y=l['point'];sx=pw-91
        c.niveles.append(NivelItem(x_mm=sx,y_mm=y,ax_mm=x-sx,ay_mm=0,z_m=l['z'],datum_m=opts['datum'],text=l['name']+' {z}',decimals=3,size_mm=2.4,line_mm=16,locked=True,group_id=tag,z=30))
    text(18,17,pw-36,opts['name']+' | '+key+' | '+view['title'],12,True)
    text(18,28,pw-36,f"MODEL DETAIL | 1:{opts['scale']} | Dimensions mm / levels m | local {view.get('sheet_family','Stair')} view / actual cage",8)
    for i,label in enumerate(view.get('labels',[])):
        pos=pp(label['point']);tx,ty=pw-108,51+i*10
        line(pos,(tx-2,ty+2),.15,'#8c301b');text(tx,ty,88,label['text'],6.8)
    if view.get('bar'):
        row=view['bar'];b=row['bbs'];steel=steel_label(b)
        texts=[f"BAR MARK {row['mark']} | QTY {len(row['uids'])} | Diameter {b['diameter_mm']:g} mm",'ROLE: '+', '.join(row['roles']),f"Cut length {b['length_m']*1000:.3f} mm | Inside bend radius {b.get('inside_radius_mm',0):g} mm",'Straight tangent lengths mm: '+', '.join(f'{v:.2f}' for v in b.get('straight_mm',[])),'Bend angles deg: '+', '.join(f'{v:g}' for v in b.get('bend_degrees',[])),'Steel: '+steel,'BBS basis: '+b.get('basis','')]
        if 'helix_radius_m' in b:texts.insert(4,f"Helix radius {b['helix_radius_m']*1000:.2f} mm; sweep {math.degrees(b['helix_angle_rad']):.2f} deg; rise/rad {b['helix_rise_per_radian']*1000:.2f} mm")
        # Long descriptors are wrapped to avoid going beyond page margins.
        yy=ph-83
        for s in texts:
            text(18,yy,pw-36,s,7);yy+=4.2
        if view.get('spatial'):text(pw-108,53,87,'SPATIAL BAR\nOrthographic projection;\nuse analytic BBS cut length.',7,True)
    else:
        text(18,ph-78,pw-36,view.get('summary','Rise '+str(view.get('rise_text','')))+' | '+view.get('note','Dimensions from verified schema-2 concrete; heavy = cut, grey = projected context'),7)
        text(18,ph-72,pw-36,view.get('reinforcement_note','Representative bars shown by role; full quantities / all Bar Marks are in BBS. Curved bars are sampled centrelines.'),7)
    # Generated title grid is ordinary tagged shapes/texts: native user title blocks remain independent.
    x,y,w,h=pw-215,ph-43,205,33
    for a,b in [((x,y),(x+w,y)),((x,y+h),(x+w,y+h)),((x,y),(x,y+h)),((x+w,y),(x+w,y+h)),((x+w/2,y),(x+w/2,y+h))]:line(a,b,.3)
    fields=[('PROJECT',opts['name']),('SHEET',key),('SCALE',f"1:{opts['scale']} @ {opts['paper']}"),('STATUS','MODEL DETAIL / REVIEW'),('DATE',opts['date']),('REV',opts['revision']),('AUTHOR',opts['author']),('MODEL',view.get('layout','RC Stair'))]
    for i,(lab,val) in enumerate(fields):
        col,row=i//4,i%4;xx=x+col*w/2;yy=y+row*h/4
        if row:line((xx,yy),(xx+w/2,yy),.15)
        text(xx+2,yy+1,w/2-4,lab+': '+val,6.8)
    c.scalebars.append(BarraEscala(x_mm=18,y_mm=ph-22,scale_n=opts['scale'],segments=3,locked=True,group_id=tag,z=25))
    text(18,ph-34,160,f"Scale check: 1 m = {1000/opts['scale']:g} mm; print at 100%",7)
    return c

def build_parts(info,opts,setid,steel=True):
    p=info['params'];views=G.concrete_views(p,info['faces'],info['triangles'],opts['angle'],info['base_z']);rows=G.grouped_bars(info['bars']) if steel else []
    representatives={}
    for row in rows:
        role=row['roles'][0]
        if role not in representatives:representatives[role]=row
    for v in views:
        v['layout']=p['layout'];v['rise_text']=f"{p['risers']} x {p['height']/p['risers']*1000:.3f} = {p['height']*1000:g} mm";v['labels']=[]
        for role,row in list(representatives.items())[:max(1,int((G.PAPERS[opts['paper']][1]-150)/10))]:
            pts=[G.project(v['frame'],pt) for pt in row['path']]
            v['lines'] += [dict(a=a,b=b,weight=.25,color='#8c301b') for a,b in zip(pts,pts[1:]) if math.dist(a,b)>G.EPS]
            v['labels'].append(dict(point=pts[len(pts)//2],text=row['mark']+'\n'+role))
        if len(representatives)>max(1,int((G.PAPERS[opts['paper']][1]-150)/10)):v['note']='Representative callouts limited to available sidebar; all roles in BBS/detail pages'
    return render_parts(views,rows,opts,setid,p['layout'],steel=steel)

def render_parts(views,rows,opts,setid,layout,family='Stair',steel=True):
    details=G.detail_views(rows)
    for v in views+details:v['layout']=layout;v['sheet_family']=family
    parts=[];entries=[]
    for i,v in enumerate(views+details,1):
        key=('S'+str(i).zfill(3));c=sheet(v,opts,setid,key);parts.append(c);entries.append(dict(key=key,title=v['title'],name=c.name,marker=marker(setid,key),steel=steel,auto_hash=auto_hash(c,marker(setid,key))))
    # Vector BBS table. No scale implied for table text; title explicitly says schedule.
    for start in range(0,len(rows),22):
        subset=rows[start:start+22];key='BBS'+str(start//22+1).zfill(2);tag=marker(setid,key);pw,ph=G.PAPERS[opts['paper']]
        v=dict(title='Bar bending schedule',lines=[dict(a=(0,0),b=(1,0),weight=.01)],dims=[],texts=[],levels=[],layout=layout,sheet_family=family)
        c=sheet(v,opts,setid,key);c.shapes=[s for s in c.shapes if s.stroke_mm!=.01]
        def text(x,y,w,value,size=7,bold=False):c.texts.append(TextoItem(x_mm=x,y_mm=y,w_mm=w,text=str(value),size_pt=size,bold=bold,family='Arial',locked=True,group_id=tag,z=35))
        columns=[('BAR MARK',.20),('ROLE / STEEL',.35),('D mm',.07),('QTY',.06),('CUT m',.10),('TOTAL m',.11),('MASS kg',.11)];x=18;width=pw-36;xs=[]
        for lab,fraction in columns:xs.append((x,width*fraction));text(x,44,width*fraction,lab,8,True);x+=width*fraction
        for j,row in enumerate(subset):
            b=row['bbs'];n=len(row['uids']);steelname=steel_label(b)
            vals=[row['mark'],', '.join(row['roles'])+' '+steelname,f"{b['diameter_mm']:g}",n,f"{b['length_m']:.3f}",f"{n*b['length_m']:.3f}",f"{n*b['mass_kg']:.3f}"]
            for value,(x,w) in zip(vals,xs):text(x,52+j*5.8,w,str(value),7)
        text(18,ph-86,pw-36,'Counts and analytic cut lengths match actual-cage BBS Bar Marks; no procurement waste / laps inferred.',7)
        c.name='TBIM '+family+' '+setid[:8]+' '+key
        c.scalebars=[];c.texts=[t for t in c.texts if not t.text.startswith(('Scale check:','Rise ','Representative bars'))]
        for t in c.texts:
            if t.text.startswith('MODEL DETAIL |'):t.text='BBS SCHEDULE | Table NTS | Actual-cage marks and analytic cut lengths'
            if t.text.startswith('SCALE:'):t.text='SCALE: NTS / table'
        parts.append(c);entries.append(dict(key=key,title='BBS',name=c.name,marker=tag,steel=True,auto_hash=auto_hash(c,tag)))
    return parts,entries,rows

class StairBackend:
    key=KEY;title='Stair';selection_label='Stair ที่เลือก';dialog_attr='stair_drawing_dialog'
    source=staticmethod(source);build_parts=staticmethod(build_parts);host=staticmethod(C.host)
    @staticmethod
    def summary(g):return g.ext['thai_bim']['stair_params']['layout']

STAIR_BACKEND=StairBackend()

class StairSheetSet(Command):
    def __init__(self,scene,uid,opts,steel,expected,backend=None):
        self.backend=backend or STAIR_BACKEND;self.key=self.backend.key
        self.scene=scene;self.info=self.backend.source(scene,uid,steel)
        if self.info['stamp']!=expected:raise ValueError('Stair/cage changed after preview; review again')
        self.before=(list(scene.compositions),copy.deepcopy(scene.plugin_data));self.before_hash=D.digest([c.to_dict() for c in scene.compositions]);old=(scene.plugin_data.get(self.key) or {}).get(uid);setid=old['id'] if old else uuid.uuid4().hex
        self.parts,entries,self.rows=self.backend.build_parts(self.info,opts,setid,steel);prior={r['key']:r for r in old['sheets']} if old else {};removed=[];archives=[]
        source_changed=bool(old and (old['geom']!=self.info['geom'] or old['bars_stamp']!=self.info['bars_stamp'] or old['options']!=opts or old['steel']!=steel or old.get('generator_version')!=E.VERSION))
        for c,row in zip(self.parts,entries):
            before=prior.get(row['key']);previous=find_sheet(scene,before) if before else None
            if previous:
                removed.append(previous);edited=auto_hash(previous,before['marker'])!=before['auto_hash']
                if edited or (manual_items(previous,before['marker']) and source_changed):
                    archived=copy.deepcopy(previous);archived.name=previous.name+' / MANUAL '+uuid.uuid4().hex[:6]
                    for item in archived.all_items():item.group_id=''
                    archives.append(archived)
                for key in LISTS:getattr(c,key).extend(copy.deepcopy([v for v in getattr(previous,key) if getattr(v,'group_id','')!=before['marker']]))
                if previous.cajetin and previous.cajetin.group_id!=before['marker']:c.cajetin=copy.deepcopy(previous.cajetin)
                c.guides_v=copy.deepcopy(previous.guides_v);c.guides_h=copy.deepcopy(previous.guides_h)
                row['manual_pending']=bool(manual_items(c,row['marker']) and (source_changed or before.get('manual_pending'))) or edited
            else:row['manual_pending']=False
        # Pages no longer needed (changed marks/layout) are retained as detached manual snapshots.
        for row in prior.values():
            prev=find_sheet(scene,row)
            if prev and prev not in removed:
                removed.append(prev);archive=copy.deepcopy(prev);archive.name=prev.name+' / RETIRED '+uuid.uuid4().hex[:6]
                for item in archive.all_items():item.group_id=''
                archives.append(archive)
        data=copy.deepcopy(self.before[1]);store=data.setdefault(self.key,{})
        if len(store)>=200 and uid not in store:raise ValueError('Limit 200 stair sheet sets per document')
        store[uid]=dict(schema=1,generator_version=E.VERSION,id=setid,uid=uid,geom=self.info['geom'],bars_stamp=self.info['bars_stamp'],options=copy.deepcopy(opts),steel=steel,sheets=entries,archives=[c.name for c in archives])
        self.after=([c for c in self.before[0] if c not in removed]+archives+self.parts,data)
    def do(self,scene):
        if scene is not self.scene or self.backend.source(scene,self.info['uid'],self.after[1][self.key][self.info['uid']]['steel'])['stamp']!=self.info['stamp'] or scene.plugin_data!=self.before[1] or D.digest([c.to_dict() for c in scene.compositions])!=self.before_hash:raise ValueError('Source/sheets/document changed before commit')
        scene.compositions=list(self.after[0]);scene.plugin_data=copy.deepcopy(self.after[1])
    def undo(self,scene):scene.compositions=list(self.before[0]);scene.plugin_data=copy.deepcopy(self.before[1])

class ReviewManual(Command):
    def __init__(self,scene,uid,backend=None):
        self.backend=backend or STAIR_BACKEND;self.key=self.backend.key
        self.scene=scene;self.before=copy.deepcopy(scene.plugin_data);self.hash=D.digest([c.to_dict() for c in scene.compositions]);self.uid=uid;self.after=copy.deepcopy(self.before);self.source_stamp=self.backend.source(scene,uid,self.before[self.key][uid]['steel'])['stamp']
        rows=status(scene,uid,self.backend)
        if not rows or any(any(r!='Preserved manual details require review' for r in row['reasons']) for row in rows):raise ValueError('Update all stale/edited sheets before acknowledging preserved details')
        for row in self.after[self.key][uid]['sheets']:row['manual_pending']=False
    def do(self,scene):
        if scene is not self.scene or scene.plugin_data!=self.before or D.digest([c.to_dict() for c in scene.compositions])!=self.hash or self.backend.source(scene,self.uid,self.before[self.key][self.uid]['steel'])['stamp']!=self.source_stamp:raise ValueError('Sheets changed during manual review')
        scene.plugin_data=copy.deepcopy(self.after)
    def undo(self,scene):scene.plugin_data=copy.deepcopy(self.before)

def export_pdf(panel,uid,path,backend=None):
    scene=panel.app.scene;parts,meta=validate(scene,uid,backend);path=Path(path).with_suffix('.pdf');comp=D.composer(panel)
    fd,temp=tempfile.mkstemp(prefix='tbim-stair-',suffix='.pdf',dir=path.parent);os.close(fd);before=scene.compositions;active=comp.comp
    try:
        scene.compositions=parts;errors=comp.export_all_pdf(temp)
        if errors or Path(temp).stat().st_size<100:raise ValueError('Stair PDF failed: '+str(errors))
        os.replace(temp,path)
    finally:
        scene.compositions=before;comp.comp=active
        if Path(temp).exists():Path(temp).unlink()
    return path

def export_bbs(scene,uid,path,backend=None):
    backend=backend or STAIR_BACKEND
    _,meta=validate(scene,uid,backend)
    if not meta['steel']:raise ValueError('This set excludes reinforcement')
    info=backend.source(scene,uid,True);records=[dict(id=b['uid'],host_uid=uid,host_name=info['name'],bbs=b['bbs']) for b in info['bars']]
    E.write_xlsx(path,tables=B.tables(records));return Path(path)

class SheetPreview(QWidget):
    def __init__(self):super().__init__();self.comp=None;self.setMinimumSize(540,350)
    def paintEvent(self,event):
        p=QPainter(self);p.fillRect(self.rect(),QColor('#142a3b'))
        if self.comp:
            pw,ph=self.comp.page_size_mm();k=min((self.width()-24)/pw,(self.height()-24)/ph);p.translate((self.width()-pw*k)/2,(self.height()-ph*k)/2);p.scale(k,k);p.fillRect(0,0,pw,ph,QColor('white'))
            for s in sorted(self.comp.shapes,key=lambda x:x.z):
                if s.kind not in ('linea','flecha'):continue
                p.setPen(QPen(QColor(s.color),s.stroke_mm));a=QPointF(s.x_mm,s.y_mm+s.h_mm if s.invert else s.y_mm);b=QPointF(s.x_mm+s.w_mm,s.y_mm if s.invert else s.y_mm+s.h_mm);p.drawLine(a,b)
            p.setPen(QPen(QColor('#202020'),.18))
            font=p.font();font.setPointSizeF(7/2.835);p.setFont(font)
            for d in self.comp.cotas:
                a=(d.x_mm,d.y_mm);b=(d.x_mm+d.dx_mm,d.y_mm+d.dy_mm);length=math.dist(a,b)
                if length<1e-6:continue
                nx,ny=-(b[1]-a[1])/length,(b[0]-a[0])/length;aa=(a[0]+nx*d.sep_mm,a[1]+ny*d.sep_mm);bb=(b[0]+nx*d.sep_mm,b[1]+ny*d.sep_mm)
                for u,v in ((a,aa),(b,bb),(aa,bb)):p.drawLine(QPointF(*u),QPointF(*v))
                label=d.text or f'{d.real_distance_m()*1000:.1f} mm';p.drawText(QPointF((aa[0]+bb[0])/2-6,(aa[1]+bb[1])/2-1),label)
            for n in self.comp.niveles:
                p.drawLine(QPointF(n.x_mm+n.ax_mm,n.y_mm+n.ay_mm),QPointF(n.x_mm+n.line_mm,n.y_mm));p.drawText(QPointF(n.x_mm,n.y_mm-1),n.text.replace('{z}',f'{n.level_m():+.3f}'))
            p.setPen(QColor('#202020'))
            for t in self.comp.texts:
                font=p.font();font.setPointSizeF(t.size_pt/2.835);p.setFont(font);p.drawText(QPointF(t.x_mm,t.y_mm+2.5),t.text)
        p.end()

class StairDrawingDialog(QDialog):
    def __init__(self,panel,backend=None):
        self.backend=backend or STAIR_BACKEND;self.key=self.backend.key
        super().__init__(panel.app.window);self.panel=panel;self.scene=panel.app.scene;self.uid=None;self.review=None;self.preview_parts=[]
        self.setWindowTitle('Thai BIM '+E.VERSION+' — '+self.backend.title+' plan / sections / bars / BBS / Sheets');self.resize(1350,880)
        lay=QVBoxLayout(self);self.note=QLabel('เลือกบันได → อ่าน Stair → ตรวจพรีวิว → สร้าง/อัปเดต Sheet\nเหล็กต้องสร้างจริงและตรง Host • แก้ส่วนอัตโนมัติจะเก็บสำเนาเดิม • รายละเอียดเพิ่มเองคงไว้และต้องตรวจหลังอัปเดต');self.note.setWordWrap(True);self.note.setMaximumHeight(65);lay.addWidget(self.note)
        row=QHBoxLayout();lay.addLayout(row,1);form=QFormLayout();form.setFormAlignment(Qt.AlignTop);row.addLayout(form)
        self.fields={}
        for key,label,value in [('name','โครงการ','Thai BIM Stair'),('revision','Revision','01'),('author','ผู้เขียนแบบ',''),('date','วันที่',datetime.now().strftime('%Y-%m-%d'))]:self.fields[key]=QLineEdit(value if key!='name' else 'Thai BIM '+self.backend.title);form.addRow(label,self.fields[key])
        self.paper=QComboBox();self.paper.addItems(G.PAPERS);form.addRow('กระดาษแนวนอน',self.paper)
        self.scale=QComboBox();self.scale.addItems(['20','25','50']);self.scale.setCurrentText('50');form.addRow('มาตราส่วน 1:',self.scale)
        self.angle=QDoubleSpinBox();self.angle.setRange(-360,720);self.angle.setValue(90);form.addRow('มุมรูปตัดรัศมี วน/โค้ง (deg)',self.angle);self.angle.setEnabled(self.backend.title=='Stair')
        if self.backend.title!='Stair':self.angle.hide();form.labelForField(self.angle).hide()
        self.datum=QDoubleSpinBox();self.datum.setRange(-10000,10000);self.datum.setDecimals(3);form.addRow('Datum ระดับ (m)',self.datum)
        self.steel=QCheckBox('รวมเหล็กจริง + รายละเอียด Bar Mark + BBS');self.steel.setChecked(True);form.addRow(self.steel)
        self.pages=QComboBox();form.addRow('หน้าพรีวิว',self.pages);self.pages.currentIndexChanged.connect(self.page_changed)
        self.preview=SheetPreview();row.addWidget(self.preview,1)
        panel.app.viewport.sceneVersionChanged.connect(self.model_changed)
        self.table=QTableWidget(0,4);self.table.setHorizontalHeaderLabels(['Sheet','ชื่อ','รายละเอียดเพิ่มเอง','สถานะ / ต้องอัปเดต']);self.table.setEditTriggers(QTableWidget.NoEditTriggers);self.table.setMaximumHeight(200);lay.addWidget(self.table)
        for labels in [[('อ่าน '+self.backend.selection_label,self.read),('ตรวจพรีวิวทุกหน้า',self.prepare),('สร้าง/อัปเดต Sheet',self.build),('ตรวจสถานะแบบ',self.refresh)], [('เปิดแบบใน Composer',self.show_composer),('ตรวจรายละเอียดที่คงไว้แล้ว',self.acknowledge),('ส่งออก PDF…',self.export),('ส่งออก BBS XLSX…',self.bbs)]]:
            buttons=QHBoxLayout();lay.addLayout(buttons)
            for label,fn in labels:
                b=QPushButton(label);b.clicked.connect(lambda checked=False,fn=fn:panel.guard(fn));buttons.addWidget(b)
    def model_changed(self,*_):
        if self.isVisible() and self.uid:self.panel.guard(self.refresh)
    def check(self):
        if self.scene is not self.panel.app.scene:raise ValueError('Document changed; reopen Stair Sheets')
        if self.scene.mesh is not self.scene.loose_mesh:raise ValueError('Exit group editing before Stair Sheets')
    def options(self):return G.options(paper=self.paper.currentText(),scale=int(self.scale.currentText()),angle=self.angle.value(),datum=self.datum.value(),**{k:w.text() for k,w in self.fields.items()})
    def read(self):
        self.check()
        if len(self.scene.selection)!=1:raise ValueError('Select one '+self.backend.title)
        g=self.backend.host(self.scene,next(iter(self.scene.selection)).uid);self.uid=g.uid;self.review=None;self.note.setText('อ่าน '+g.name+' • '+self.backend.summary(g));meta=(self.scene.plugin_data.get(self.key) or {}).get(self.uid)
        if meta:
            for k,w in self.fields.items():w.setText(meta['options'][k])
            self.paper.setCurrentText(meta['options']['paper']);self.scale.setCurrentText(str(meta['options']['scale']));self.angle.setValue(meta['options']['angle']);self.datum.setValue(meta['options']['datum']);self.steel.setChecked(meta['steel'])
        self.refresh()
    def prepare(self):
        self.check();info=self.backend.source(self.scene,self.uid,self.steel.isChecked());opts=self.options();meta=(self.scene.plugin_data.get(self.key) or {}).get(self.uid);self.preview_parts,_,_=self.backend.build_parts(info,opts,meta['id'] if meta else 'preview',self.steel.isChecked());self.review=(info['stamp'],opts,self.steel.isChecked());self.pages.clear();self.pages.addItems([c.name for c in self.preview_parts]);self.page_changed(0);self.note.setText('ตรวจแล้ว '+str(len(self.preview_parts))+' หน้า • '+opts['paper']+' • 1:'+str(opts['scale'])+' • 1 m = '+str(1000/opts['scale'])+' mm บนกระดาษ')
    def page_changed(self,index):self.preview.comp=self.preview_parts[index] if 0<=index<len(self.preview_parts) else None;self.preview.update()
    def build(self):
        self.check()
        if not self.review or self.review[1]!=self.options() or self.review[2]!=self.steel.isChecked():raise ValueError('Inputs changed; review all pages first')
        cmd=StairSheetSet(self.scene,self.uid,self.options(),self.steel.isChecked(),self.review[0],self.backend);self.panel.execute(cmd);self.refresh();self.note.setText('สร้าง/อัปเดตแล้ว '+str(len(cmd.parts))+' หน้า • รายละเอียดเพิ่มเองคงไว้; ตรวจสถานะก่อนส่งออก')
    def refresh(self):
        self.check();rows=status(self.scene,self.uid,self.backend) if self.uid else [];self.table.setRowCount(len(rows))
        for i,row in enumerate(rows):
            for j,value in enumerate((row['key'],row['name'],row['manual'],'ปัจจุบัน' if not row['reasons'] else ' | '.join(REASONS.get(v,v) for v in row['reasons']))):self.table.setItem(i,j,QTableWidgetItem(str(value)))
        self.table.resizeColumnsToContents();return rows
    def show_composer(self):
        self.check();meta=(self.scene.plugin_data.get(self.key) or {}).get(self.uid)
        if not meta:raise ValueError('Create Stair sheets first')
        c=find_sheet(self.scene,meta['sheets'][0])
        if c is None:raise ValueError('Sheet missing; update')
        composer=D.composer(self.panel);composer._reload_comp_combo();composer.show_sheet(self.scene.compositions.index(c));self.panel.app.window._refresh_sheet_tabs();return composer
    def acknowledge(self):self.check();self.panel.execute(ReviewManual(self.scene,self.uid,self.backend));self.refresh()
    def export_current(self):
        self.check();_,meta=validate(self.scene,self.uid,self.backend)
        if self.options()!=meta['options'] or self.steel.isChecked()!=meta['steel']:raise ValueError('Dialog options differ from saved sheets; review and update before export')
    def export(self):
        self.export_current();path,_=QFileDialog.getSaveFileName(self,'Stair detail PDF','Thai-BIM-Stair.pdf','PDF (*.pdf)')
        if path:self.note.setText('ส่งออก '+str(export_pdf(self.panel,self.uid,path,self.backend)))
    def bbs(self):
        self.export_current();path,_=QFileDialog.getSaveFileName(self,'Actual stair BBS','Thai-BIM-Stair-BBS.xlsx','Excel (*.xlsx)')
        if path:export_bbs(self.scene,self.uid,path,self.backend);self.note.setText('ส่งออก BBS '+path)

def open_dialog(panel):
    old=getattr(panel,'stair_drawing_dialog',None)
    if old:old.close();old.deleteLater()
    d=StairDrawingDialog(panel);panel.stair_drawing_dialog=d
    if len(panel.app.scene.selection)==1 and next(iter(panel.app.scene.selection)).ext.get('thai_bim',{}).get('stair_params',{}).get('stair_schema')==2:d.read()
    d.show();return d
