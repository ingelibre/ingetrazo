"""Editable house teaching model, based on supplied Phetnaray HTML geometry.

Centerline idealization with explicit assumed rigid joints, fixed bases, RHS roof
sections and equivalent nodal actions. This is not an as-built/design model.
"""
import math
from .house_reference import REFERENCE

BUILDING_CATALOG = [(
    '3d_house_phetnaray', 'House Phetnaray / บ้านเพชรนารายณ์ — RC + steel roof',
    'Two-storey teaching model: concrete beams/columns and simplified hip steel roof. '
    'Geometry adapted from supplied HTML; loads, roof sections and joints are assumed.')]

def rectangle(name,b,h):
    a,c=min(b,h),max(b,h)
    # For horizontal members, local y is vertical: h lies along local y.
    return dict(id=name,A=b*h,Iy=h*b**3/12,Iz=b*h**3/12,
                J=c*a**3*(1/3-.21*a/c*(1-a**4/(12*c**4))))

def rhs(name,b,h,t):
    bi,hi=b-2*t,h-2*t
    # Uniform thin-wall closed-section torsion; rounded corners omitted.
    bm,hm=b-t,h-t
    return dict(id=name,A=b*h-bi*hi,Iy=(h*b**3-hi*bi**3)/12,
                Iz=(b*h**3-bi*hi**3)/12,J=4*(bm*hm)**2/(2*(bm+hm)/t))

def house_model():
    raw=[]
    def member(name,a,b,section,material='Concrete',kind='Beam',level='',status='ADAPTED'):
        raw.append(dict(id=name,a=tuple(a),b=tuple(b),section=section,
                        material=material,type=kind,level=level,source_status=status))
    sections=[rectangle(name,*size) for name,size in REFERENCE['sections'].items()]
    sections += [rectangle('C200',.2,.2),rectangle('C250',.25,.25),
                 rhs('RHS100',.1,.1,.003),rhs('RHS75',.075,.075,.003)]
    for f in REFERENCE['foundation_nodes']:
        for level,z0,z1 in [('SUB',-1,.55),('L0',.55,3.75),('L1',3.75,6.8)]:
            if level=='L1' and f['grid'] in ('1-B','1-C'): continue
            member('COL-'+level+'-'+f['grid'],(f['x'],f['y'],z0),(f['x'],f['y'],z1),
                   'C250' if level=='SUB' and f['column_type']=='C2' else 'C200',
                   kind='Column',level=level)
    for i,b in enumerate(REFERENCE['beams']):
        z={'L0':.55,'L1':3.75,'RF':6.8}[b['level']]
        member('BM-'+b['level']+'-'+str(i+1),(*b['p1'],z),(*b['p2'],z),b['section'],level=b['level'])
    # Source uses a four-face apex hip roof within these limits. Fewer purlins
    # than the HTML visual model: deliberate analytical demonstration only.
    x0,x1,y0,y1=-.1,10.4,-1.05,9.35
    apex=(5.15,4.15,8.7)
    corners=[(x0,y0,6.8),(x1,y0,6.8),(x1,y1,6.8),(x0,y1,6.8)]
    def mix(a,b,t): return tuple(a[k]+(b[k]-a[k])*t for k in range(3))
    def roof(name,a,b,section='RHS100'):
        member(name,a,b,section,'Steel','Frame','RF','ASSUMED_SIMPLIFIED')
    for side in range(4):
        a,b=corners[side],corners[(side+1)%4]
        roof('HIP-'+str(side+1),a,apex)
        roof('EAVE-'+str(side+1),a,b)
        for k in (1,2,3):
            # Rafters from the eave to a common apex; coarser than source framing.
            roof('RAF-'+str(side+1)+'-'+str(k),mix(a,b,k/4),apex)
        for k,t in enumerate((.35,.7)):
            roof('PURL-'+str(side+1)+'-'+str(k+1),mix(a,apex,t),mix(b,apex,t),'RHS75')
    roof('POST-RF',(5.2,4.15,6.8),apex)
    for f in REFERENCE['foundation_nodes']:
        if f['grid'] in ('1-B','1-C'): continue
        p=(f['x'],f['y'],6.8)
        choices=[(x0,p[1],6.8),(x1,p[1],6.8),(p[0],y0,6.8),(p[0],y1,6.8)]
        roof('BEARING-'+f['grid'],p,min(choices,key=lambda q:math.dist(p,q)))

    # Split at all intersections before assigning nodes. Merely crossing lines
    # must not leave a floating roof/column; coincident intervals counted once.
    cuts=[{0.,1.} for _ in raw]
    def dot(a,b): return sum(x*y for x,y in zip(a,b))
    def sub(a,b): return tuple(x-y for x,y in zip(a,b))
    def parameter(p,a,b):
        v=sub(b,a); t=dot(sub(p,a),v)/dot(v,v)
        return t if -1e-8<=t<=1+1e-8 and math.dist(p,mix(a,b,t))<1e-7 else None
    for i,m in enumerate(raw):
        for j,n in enumerate(raw[:i]):
            for p in (n['a'],n['b']):
                t=parameter(p,m['a'],m['b'])
                if t is not None: cuts[i].add(max(0.,min(1.,t)))
            for p in (m['a'],m['b']):
                t=parameter(p,n['a'],n['b'])
                if t is not None: cuts[j].add(max(0.,min(1.,t)))
            u,v,w=sub(m['b'],m['a']),sub(n['b'],n['a']),sub(m['a'],n['a'])
            aa,bb,cc,dd,ee=dot(u,u),dot(u,v),dot(v,v),dot(u,w),dot(v,w)
            det=aa*cc-bb*bb
            if abs(det)<1e-12*aa*cc: continue
            t,s=(bb*ee-cc*dd)/det,(aa*ee-bb*dd)/det
            if 0<=t<=1 and 0<=s<=1 and math.dist(mix(m['a'],m['b'],t),mix(n['a'],n['b'],s))<1e-7:
                cuts[i].add(t); cuts[j].add(s)
    nodes={}; members=[]; pairs=set()
    fixed={(f['x'],f['y'],-1.) for f in REFERENCE['foundation_nodes']}
    def node(p):
        p=tuple(round(v,7) for v in p)
        if p not in nodes:
            nodes[p]=dict(id='N'+str(len(nodes)+1),x=p[0],y=p[1],z=p[2],
                          support='Fixed' if p in fixed else 'Free')
        return nodes[p]['id']
    for m,points in zip(raw,cuts):
        points=sorted(points)
        for k,(t,s) in enumerate(zip(points,points[1:])):
            a,b=mix(m['a'],m['b'],t),mix(m['a'],m['b'],s)
            if math.dist(a,b)<1e-6: continue
            ni,nj=node(a),node(b); pair=tuple(sorted((ni,nj)))
            if pair in pairs: continue
            pairs.add(pair)
            members.append({k:v for k,v in m.items() if k not in ('a','b','id')}|
                           dict(id=m['id']+'-'+str(k+1),parent=m['id'],i=ni,j=nj,rotation=0))
    loads=[]; floor_area=9.3*8.3; roof_area=(x1-x0)*(y1-y0)
    for z in (.55,3.75):
        targets=[n for p,n in nodes.items() if p in {(f['x'],f['y'],z) for f in REFERENCE['foundation_nodes']}]
        for n in targets:
            for case,q in [('DL',1.5),('LL',2.)]:
                loads.append(dict(node=n['id'],direction='FZ',value=-q*floor_area/len(targets),case=case))
    roof_nodes=[n for n in nodes.values() if n['z']>=6.8]
    for n in roof_nodes:
        for case,q in [('DL',.6),('RL',.25)]:
            loads.append(dict(node=n['id'],direction='FZ',value=-q*roof_area/len(roof_nodes),case=case))
    for z in (3.75,6.8):
        targets=[n for p,n in nodes.items() if p in {(f['x'],f['y'],z) for f in REFERENCE['foundation_nodes']}]
        for n in targets:
            for case,direction,value in [('WX+','FX',10),('WX-','FX',-10),('WY+','FY',10),('WY-','FY',-10)]:
                loads.append(dict(node=n['id'],direction=direction,value=value/len(targets),case=case))
    return dict(schema=2,dimension='3D',self_weight=True,self_weight_case='DL',
        nodes=list(nodes.values()),members=members,sections=sections,
        materials=[dict(id='Concrete',E=25e6,G=25e6/2.4,nu=.2,rho=24),
                   dict(id='Steel',E=200e6,G=200e6/2.6,nu=.3,rho=76.98)],
        cases=['DL','LL','RL','WX+','WX-','WY+','WY-'],point_loads=loads,distributed_loads=[],
        combinations={'DEMO Gravity':{'DL':1,'LL':1,'RL':1},
                      'DEMO Wind X+':{'DL':1,'WX+':1},'DEMO Wind X-':{'DL':1,'WX-':1}},
        example_metadata=dict(name='บ้านเพชรนารายณ์ / Phetnaray',purpose='TEACHING_ONLY',
            source_file=REFERENCE['source_file'],source_sha256=REFERENCE['source_sha256'],
            assumptions=['HTML geometry adapted to centerlines at SSL +0.55/+3.75 and eave +6.80 m.',
              'Fixed bases at -1.00 m; no soil/pile flexibility or floor diaphragm.',
              'Gross uncracked concrete sections; assumed E=25 GPa, not derived from concrete strength.',
              'Simplified apex rafters, two purlin tiers and RHS steel; not original C-section framing.',
              'All crossings/roof bearing connections assumed rigid; no connection design.',
              'Floor area 9.3x8.3 per level with equal equivalent column-node loads.',
              'Additional DL=1.5 kPa floor, 0.6 kPa roof; LL=2 kPa floor; RL=0.25 kPa roof.',
              'Wind +/-10 kN per upper level per direction is illustrative, not a code wind calculation.',
              'Member self-weight counted once in DL; walls/stairs/slab stiffness excluded.',
              'DEMO combinations are custom unfactored teaching cases, not statutory design presets.']))
