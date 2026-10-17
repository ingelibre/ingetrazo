"""Selected-member plan shape edits, bounded slab openings and landing handles."""
import copy,math
from . import engine as E,path_geometry as PG,placement as P,stairs as S

def inverse(m,p):
    return tuple(sum(m[j*4+i]*(p[j]-m[j*4+3]) for j in range(3)) for i in range(3))
def upright(pose):
    m=P.rigid_matrix(pose)
    if any(abs(m[i]-v)>1e-5 for i,v in zip((2,6,8,9,10),(0,0,0,0,1))):raise ValueError('Plan editing requires upright yaw / translation only')
    return m
def inside(p,poly):
    x,y=p;odd=False
    for a,b in zip(poly,poly[1:]+poly[:1]):
        if (a[1]>y)!=(b[1]>y) and x<(b[0]-a[0])*(y-a[1])/(b[1]-a[1])+a[0]:odd=not odd
    return odd
def distance(p,a,b):
    d=E.sub(b,a);t=max(0,min(1,E.dot(E.sub(p,a),d)/E.dot(d,d)));return math.dist(p,E.add(a,E.mul(d,t)))
def separated(a,b):
    # Polygon overlap, crossing or touching is invalid for opening boundaries.
    if any(inside(p,b) for p in a) or any(inside(p,a) for p in b):return False
    def cross(a,b,c):return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])
    for x,y in zip(a,a[1:]+a[:1]):
        for u,v in zip(b,b[1:]+b[:1]):
            if cross(x,y,u)*cross(x,y,v)<0 and cross(u,v,x)*cross(u,v,y)<0:return False
            if min(distance(x,u,v),distance(y,u,v),distance(u,x,y),distance(v,x,y))<.002:return False
    return True
def outline(params):
    if params.get('shape')=='polygon':return PG.outline(params['footprint'])
    x,y,w,d=[params[k] for k in ('x','y','width','depth')];return PG.outline([(x,y),(x+w,y),(x+w,y+d),(x,y+d)])
def validated_holes(poly,holes):
    if len(holes)>20:raise ValueError('Limit 20 openings per slab')
    if len(poly)+sum(len(h) for h in holes)>300:raise ValueError('Limit 300 total boundary vertices per edited slab')
    out=[]
    for hole in holes:
        h=PG.outline(hole)
        if not all(inside(v,poly) for v in h):raise ValueError('Opening must be strictly inside slab boundary')
        # Check edges too: corners inside a concave slab alone are insufficient.
        for a,b in zip(h,h[1:]+h[:1]):
            for c,d in zip(poly,poly[1:]+poly[:1]):
                def cr(a,b,c):return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])
                if cr(a,b,c)*cr(a,b,d)<0 and cr(c,d,a)*cr(c,d,b)<0 or min(distance(a,c,d),distance(b,c,d),distance(c,a,b),distance(d,a,b))<.002:raise ValueError('Opening intersects / touches slab boundary')
        if any(not separated(h,prior) for prior in out):raise ValueError('Openings overlap / nest / touch')
        out.append(h)
    return out
def slab_spec(params,poly=None,holes=None):
    p=copy.deepcopy(params);poly=PG.outline(poly if poly is not None else outline(p));holes=validated_holes(poly,p.get('holes',[]) if holes is None else holes)
    z,h=E.finite(p['z']),E.positive(p['height'],'Slab thickness');lo=[min(v[i] for v in poly) for i in range(2)];hi=[max(v[i] for v in poly) for i in range(2)]
    sp=E.box_spec('Slab',*lo,z,hi[0]-lo[0],hi[1]-lo[1],h);sp['faces']=E.extrusion([(x,y,z) for x,y in poly],(0,0,h))
    sp['face_holes']={0:[[(x,y,z) for x,y in hole] for hole in holes],1:[[(x,y,z+h) for x,y in reversed(hole)] for hole in holes]}
    for hole in holes:sp['faces'].extend([list(reversed(f)) for f in E.extrusion([(x,y,z) for x,y in hole],(0,0,h))[2:]])
    sp['quantity']=(E.area(poly)-sum(E.area(hole) for hole in holes))*h
    sp['params'].update(shape='polygon',footprint=poly,holes=holes)
    sp['note']='Net modeled concrete with bounded through openings; reinforcement requires explicit review / rebuilding'
    return sp
def landing_handle(params):
    p=S.validated(params);parts=S.parts(dict(p,hand='Left'));landings=[part for part in parts if part['kind']=='Landing']
    if not landings:raise ValueError('Stair has no landing; enable landing in Stair dialog first')
    part=next((part for part in landings if part['role']=='Intermediate landing'),landings[-1]);name=part['role'];q=part['params']
    if p['layout'] in ('Spiral','Circular'):
        u=(*part['direction'],0);v=(-u[1],u[0],0);origin=E.add(part['origin'],E.mul(v,p['width']/2));axis=E.mul(u,-1 if name.startswith('Bottom') else 1)
    elif p['layout']=='L' and name=='Top landing':origin=(q['x']+q['width']/2,q['y'],q['z']+q['height']);axis=(0,1,0)
    elif name=='Bottom landing' or p['layout']=='U' and name=='Top landing':origin=(q['x']+q['width'],q['y']+q['depth']/2,q['z']+q['height']);axis=(-1,0,0)
    else:origin=(q['x'],q['y']+q['depth']/2,q['z']+q['height']);axis=(1,0,0)
    def reflect(v):return (v[0],-v[1] if p['hand']=='Right' else v[1],v[2])
    origin,axis=reflect(origin),reflect(axis);return dict(key=('landing',0),point=E.add(origin,E.mul(axis,p['landing_depth'])),origin=origin,axis=axis,label='Landing depth (all landings)')
def handles(record):
    kind=record['kind'];p=record.get('params') or record.get('stair_params')
    if kind=='Beam':return [dict(key=('beam',i),point=(p['x']+i*p['width'],p['y']+p['depth']/2,p['z']),label='Start' if not i else 'End') for i in (0,1)]
    if kind=='Stair' and p.get('stair_schema')==2:return [landing_handle(p)]
    if kind!='Slab':raise ValueError('Shape editing supports Beam / Slab / schema-2 Stair landing')
    rings=[outline(p)]+p.get('holes',[]);out=[]
    for r,poly in enumerate(rings):
        for i,a in enumerate(poly):
            b=poly[(i+1)%len(poly)];out.append(dict(key=('vertex',r,i),point=(*a,p['z']+p['height']),label=('V' if not r else 'H'+str(r)+' V')+str(i+1)))
            out.append(dict(key=('edge',r,i),point=(*[(x+y)/2 for x,y in zip(a,b)],p['z']+p['height']),label=('E' if not r else 'H'+str(r)+' E')+str(i+1)))
    return out
def change(record,pose,key,world):
    m=upright(pose);p=copy.deepcopy(record.get('params') or record.get('stair_params'));point=inverse(m,world);kind=record['kind']
    if key[0]=='beam' and kind=='Beam':
        ends=[(p['x']+i*p['width'],p['y']+p['depth']/2,p['z']) for i in (0,1)];ends[key[1]]=(point[0],point[1],p['z']);a,b=[P._point(m,v) for v in ends]
        return PG.beam(a,b,a[2],p)
    if key[0]=='landing' and kind=='Stair':
        handle=landing_handle(p);p['landing_depth']=E.dot(E.sub(point,handle['origin']),handle['axis']);return S.spec(**p),m
    if kind!='Slab':raise ValueError('Unsupported shape handle')
    rings=[outline(p)]+copy.deepcopy(p.get('holes',[]));ring,index=key[1:];poly=rings[ring];target=point[:2]
    if key[0]=='vertex':poly[index]=target
    elif key[0]=='edge':
        nxt=(index+1)%len(poly);mid=tuple((a+b)/2 for a,b in zip(poly[index],poly[nxt]));delta=E.sub(target,mid);poly[index]=E.add(poly[index],delta);poly[nxt]=E.add(poly[nxt],delta)
    else:raise ValueError('Unsupported shape edit')
    return slab_spec(p,rings[0],rings[1:]),m
def add_opening(record,pose,a,b):
    if record['kind']!='Slab':raise ValueError('Opening requires Slab')
    m=upright(pose);a,b=inverse(m,a),inverse(m,b);lo=(min(a[0],b[0]),min(a[1],b[1]));hi=(max(a[0],b[0]),max(a[1],b[1]));hole=[lo,(hi[0],lo[1]),hi,(lo[0],hi[1])]
    p=record['params'];return slab_spec(p,holes=p.get('holes',[])+[hole]),m
