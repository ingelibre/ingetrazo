"""Solver-independent centreline graph. No Qt, geometry mutations or strength solver."""
import copy,hashlib,json,math,uuid
from . import placement as P,engine as E

SCHEMA='thai-bim-analytical/1'
def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
def identity(prefix,value):return prefix+'-'+digest(value)[:24]
def point(value):
    if len(value)!=3:raise ValueError('Analytical point requires XYZ')
    return tuple(0. if abs(E.finite(v))<1e-9 else round(E.finite(v),9) for v in value)
def project(p,a,b):
    delta=E.sub(b,a);length2=E.dot(delta,delta);t=E.dot(E.sub(p,a),delta)/length2
    q=E.add(a,E.mul(delta,max(0.,min(1.,t))))
    return t,q,math.dist(p,q)

def member(record):
    kind=record['kind'];p=record['params'];m=P.rigid_matrix(record.get('pose'))
    if kind not in ('Beam','Column'):raise ValueError('Analytical conversion currently supports Beam / Column only')
    for key in ('width','depth','height'):
        if E.finite(p[key])<=0:raise ValueError('Member dimensions must be positive')
    x,y,z=(E.finite(p[k]) for k in ('x','y','z'))
    if kind=='Beam':a=(x,y+p['depth']/2,z+p['height']/2);b=(x+p['width'],a[1],a[2]);reference=(0,1,0);w,h=p['depth'],p['height']
    else:a=(x+p['width']/2,y+p['depth']/2,z);b=(a[0],a[1],z+p['height']);reference=(1,0,0);w,h=p['width'],p['depth']
    a,b=point(P.point(m,a)),point(P.point(m,b));axis=E.unit(E.sub(b,a))
    origin=P.point(m,(0,0,0));local_y=E.unit(E.sub(P.point(m,reference),origin));local_z=E.cross(axis,local_y)
    if math.dist(a,b)<1e-6:raise ValueError('Zero length analytical member')
    return dict(id=identity('member',record['id']),source_id=record['id'],source_native_uid=record['native_uid'],
        name=record['name'],kind=kind,axis=[list(a),list(b)],local_axes=dict(x=list(axis),y=list(local_y),z=list(local_z)),
        section=dict(shape='rectangle',width_m=w,depth_m=h,area_m2=w*h,iy_m4=w*h**3/12,iz_m4=h*w**3/12,torsion_m4=None),
        material_id=None,releases=None,offsets=None,basis='Geometric centroid; verify connection offsets and modelling assumptions')

def build(records,tolerance=.01,previous=None):
    tolerance=E.finite(tolerance)
    if not .000001<=tolerance<=.1:raise ValueError('Inspection tolerance must be 0.001–100 mm')
    records=sorted(copy.deepcopy(records),key=lambda r:r['id'])
    if not records:raise ValueError('No Thai BIM Beam / Column in this document')
    if len(records)>1000:raise ValueError('Initial analytical preview is limited to 1000 source members')
    if len({r['id'] for r in records})!=len(records):raise ValueError('Duplicate source IDs; repair copies before conversion')
    members=[member(r) for r in records];issues=[];cuts={m['id']:[(0.,point(m['axis'][0])),(1.,point(m['axis'][1]))] for m in members}
    # Only exact endpoint-to-axis joints connect automatically. Near contacts remain separate.
    for i,m in enumerate(members):
        for n in members[i+1:]:
            if {tuple(p) for p in m['axis']}=={tuple(p) for p in n['axis']}:issues.append(dict(code='duplicate_axis',members=[m['id'],n['id']],message='Coincident members require review'))
            for first,second in ((m,n),(n,m)):
                for end,p in enumerate(first['axis']):
                    t,q,distance=project(p,*second['axis'])
                    if distance<=1e-8 and -1e-9<=t<=1+1e-9:cuts[second['id']].append((max(0.,min(1.,t)),point(p)))
                    elif distance<=tolerance:issues.append(dict(code='near_joint',members=[first['id'],second['id']],point=p,gap_m=distance,message='Near contact; not merged automatically'))
            # Interior crossings are flagged, but do not imply a structural joint.
            a,b=m['axis'];c,d=n['axis'];u,v=E.sub(b,a),E.sub(d,c);w=E.sub(a,c)
            uu,vv,uv=E.dot(u,u),E.dot(v,v),E.dot(u,v);den=uu*vv-uv*uv
            if den>1e-12*uu*vv:
                t=(uv*E.dot(v,w)-vv*E.dot(u,w))/den;s=(uu*E.dot(v,w)-uv*E.dot(u,w))/den
                if 1e-9<t<1-1e-9 and 1e-9<s<1-1e-9:
                    gap=math.dist(E.add(a,E.mul(u,t)),E.add(c,E.mul(v,s)))
                    if gap<=tolerance:issues.append(dict(code='interior_crossing',members=[m['id'],n['id']],gap_m=gap,message='Interior crossing / near crossing; not connected automatically'))
            else:
                t0=E.dot(E.sub(c,a),u)/uu;t1=E.dot(E.sub(d,a),u)/uu
                perpendicular=E.norm(E.sub(E.sub(c,a),E.mul(u,t0)))
                if perpendicular<=tolerance and min(1.,max(t0,t1))-max(0.,min(t0,t1))>1e-9:
                    issues.append(dict(code='overlapping_axes',members=[m['id'],n['id']],message='Parallel overlapping member axes require review; members retained separately'))
    nodes={};elements=[]
    for m in members:
        values=sorted(set(cuts[m['id']]))
        for (t0,p0),(t1,p1) in zip(values,values[1:]):
            coords=[p0,p1]
            if math.dist(*coords)<1e-8:continue
            ids=[]
            for xyz in coords:
                uid=identity('node',xyz);nodes.setdefault(uid,dict(id=uid,xyz_m=list(xyz)));ids.append(uid)
            elements.append(dict(id=identity('element',[m['id'],ids]),member_id=m['id'],node_i=ids[0],node_j=ids[1],type='frame',range=[t0,t1]))
    adjacency={n:set() for n in nodes};degrees={n:0 for n in nodes}
    for e in elements:
        a,b=e['node_i'],e['node_j'];adjacency[a].add(b);adjacency[b].add(a);degrees[a]+=1;degrees[b]+=1
    remaining=set(nodes);components=[]
    while remaining:
        pending=[min(remaining)];group=set()
        while pending:
            n=pending.pop()
            if n in group:continue
            group.add(n);pending.extend(adjacency[n]-group)
        remaining-=group;components.append(sorted(group))
    if len(components)>1:issues.append(dict(code='disconnected_components',count=len(components),message='Multiple independent connectivity components; review intended separation'))
    for n,d in degrees.items():
        if d==1:issues.append(dict(code='free_endpoint',node_id=n,message='Endpoint has one element; may be support or free end. Support not inferred'))
    result=dict(schema=SCHEMA,id=(previous or {}).get('id') or str(uuid.uuid4()),revision=(previous or {}).get('revision',0)+1,
        units=dict(length='m',force='kN',mass='tonne',stress='kN/m2'),source_digest=digest(records),sources=records,
        inspection_tolerance_m=tolerance,nodes=sorted(nodes.values(),key=lambda n:n['id']),members=members,elements=elements,
        components=components,issues=issues,materials=[],supports=[],load_cases=[],load_combinations=[],
        state='review_required',solver_ready=False,limitations=['Geometric graph only; no stiffness assembly or solver',
        'Interior-to-interior crossings are not connected automatically; inspect visually',
        'Supports, materials, releases, offsets and loads are unspecified; no analysis readiness inferred'])
    return result

def validate(model):
    if not isinstance(model,dict) or model.get('schema')!=SCHEMA:raise ValueError('Unsupported analytical schema')
    # This initial contract is generated data; validate by deterministic reconstruction.
    expected=build(model['sources'],model['inspection_tolerance_m'],dict(id=model['id'],revision=model['revision']-1))
    if model!=expected:raise ValueError('Analytical snapshot is inconsistent with its source records')
    return copy.deepcopy(expected)
