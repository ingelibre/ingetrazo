"""Concrete member sheets share the guarded Composer workflow with stair sheets."""
import copy,math
from core.group import world_mesh
from . import member_drawing_geometry as G,stair_drawings as S,workflow as W,placement as P,analytical as A,engine as E
KEY='thai_bim_member_drawing_sets'

def host(scene,uid):
    from . import identity_issues
    if identity_issues(scene):raise ValueError('Repair copied / missing Thai BIM IDs before member drawings')
    g=next((g for g in scene.groups if g.uid==uid),None)
    if g is None:raise ValueError('Concrete member no longer exists')
    W.host_token(g)
    if g.ext['thai_bim'].get('kind') not in G.KINDS:raise ValueError('Select one Thai BIM Footing / Column / Beam / Slab')
    return g

def role(record):
    if record['bbs'].get('slab_role'):return record['bbs']['slab_role']
    slot=record.get('slot','')
    if 'tie' in slot.lower():return 'Links / ties'
    p=record['bar_path'];span=[max(v[i] for v in p)-min(v[i] for v in p) for i in range(3)]
    return 'Main local '+'XYZ'[max(range(3),key=lambda i:span[i])]

def source(scene,uid,steel=True):
    g=host(scene,uid);m=P.rigid_matrix(W.pose(g))
    if any(abs(m[i]-v)>1e-5 for i,v in zip((2,6,8,9,10),(0,0,0,0,1))):raise ValueError('Member drawings require upright members (yaw / translation only)')
    mesh=world_mesh(g);faces=[[S.local(p.toTuple(),m) for p in f.vertices] for f in mesh.faces]
    for f in mesh.faces:faces.extend([[S.local(p.toTuple(),m) for p in hole] for hole in f.holes])
    triangles=[[S.local(p.toTuple(),m) for p in tri] for f in mesh.faces for tri in f.triangulate()]
    if len(triangles)>12000:raise ValueError('Member drawings limited to 12000 concrete triangles')
    bars=[];cache={uid:W.host_token(g)}
    if steel:
        for b in scene.groups:
            r=(b.ext or {}).get('thai_bim',{})
            if r.get('host_uid')!=uid:continue
            if not W.host_matches(b,g,cache):raise ValueError('Actual member cage is stale / moved / edited; review and rebuild first')
            bbs=copy.deepcopy(r.get('bbs') or {});path=r.get('bar_path')
            if not bbs or not path or r.get('bar_closed'):raise ValueError('Detailed actual cage with analytic BBS required; rebuild legacy bars')
            if abs(E.finite(bbs['length_m'])-E.finite(r['quantity']))>1e-8:raise ValueError('Actual cage cut length inconsistent')
            if len(path)<2 or not all(len(p)==3 and all(math.isfinite(float(x)) for x in p) for p in path):raise ValueError('Invalid actual bar path')
            bm=P.rigid_matrix(W.pose(b))
            bars.append(dict(uid=b.uid,bbs=bbs,role=role(r),path=[S.local(P._point(bm,p),m) for p in path]))
        if not bars:raise ValueError('Build and review actual reinforcement first, or uncheck reinforcement for concrete-only sheets')
        if sum(len(b['path']) for b in bars)>150000:raise ValueError('Member bar paths too large')
    geom=A.digest(dict(token=W.host_token(g),name=g.name,faces=faces,triangles=triangles))
    barstamp=A.digest(bars)
    return dict(uid=uid,name=g.name,kind=g.ext['thai_bim']['kind'],params=copy.deepcopy(g.ext['thai_bim']['params']),pose=m,base_z=m[11],faces=faces,triangles=triangles,bars=bars,geom=geom,bars_stamp=barstamp,stamp=A.digest([geom,barstamp]))

def build_parts(info,opts,setid,steel=True):
    rows=S.G.grouped_bars(info['bars']) if steel else []
    views=G.concrete_views(info['kind'],info['faces'],info['triangles'],info['base_z'])
    G.add_representatives(views,rows,opts['paper'],info['bars'])
    for view in views:view['reinforcement_note']='Actual cage projected in red; leaders identify representative roles. All marks, counts and cut lengths in details / BBS.'
    return S.render_parts(views,rows,opts,setid,info['kind'],'Member',steel)

class MemberBackend:
    key=KEY;title='Concrete Member';selection_label='ฐานราก / เสา / คาน / พื้นที่เลือก';dialog_attr='member_drawing_dialog'
    host=staticmethod(host);source=staticmethod(source);build_parts=staticmethod(build_parts)
    @staticmethod
    def summary(g):return g.ext['thai_bim']['kind']
BACKEND=MemberBackend()

def status(scene,uid):return S.status(scene,uid,BACKEND)
def validate(scene,uid):return S.validate(scene,uid,BACKEND)
def export_pdf(panel,uid,path):return S.export_pdf(panel,uid,path,BACKEND)
def export_bbs(scene,uid,path):return S.export_bbs(scene,uid,path,BACKEND)
class MemberSheetSet(S.StairSheetSet):
    def __init__(self,scene,uid,opts,steel,expected):super().__init__(scene,uid,opts,steel,expected,BACKEND)
class ReviewManual(S.ReviewManual):
    def __init__(self,scene,uid):super().__init__(scene,uid,BACKEND)

def open_dialog(panel):
    old=getattr(panel,'member_drawing_dialog',None)
    if old:old.close();old.deleteLater()
    d=S.StairDrawingDialog(panel,BACKEND);panel.member_drawing_dialog=d
    for field in d.fields.values():field.setMinimumWidth(190)
    d.note.setText('เลือกฐานราก / เสา / คาน / พื้น → อ่านชิ้นงาน → ตรวจพรีวิว → สร้าง/อัปเดต Sheet\nใช้เหล็กจริงและ BBS เดิม • แบบชิ้นงาน local axes • รายละเอียดเพิ่มเองคงไว้และต้องตรวจหลังอัปเดต')
    if len(panel.app.scene.selection)==1:d.read()
    d.show();return d
