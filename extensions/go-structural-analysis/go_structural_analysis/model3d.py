"""Schema 2: right-handed XYZ, global Z up, kN/m/rad; no solver/Qt dependency."""
import copy
import json
import math

DOFS=('UX','UY','UZ','RX','RY','RZ')
GLOBAL=('FX','FY','FZ','MX','MY','MZ')
LOCAL=('Fx','Fy','Fz','Mx','My','Mz')

def xyz(node): return [node[k] for k in ('x','y','z')]
def cantilever3d():
    if __package__: from .model import benchmark
    else: from model import benchmark
    d=benchmark(); d.update(schema=2,dimension='3D',cases=['DL','LL','WX','WY'],combinations={},self_weight_case='DL',distributed_loads=[])
    d['nodes']=[dict(id='N1',x=0,y=0,z=0,support='Fixed'),dict(id='N2',x=4,y=0,z=0,support='Free')]
    d['point_loads']=[dict(node='N2',direction='FY',value=10,case='LL'),dict(node='N2',direction='FZ',value=-15,case='DL')]
    return d
def cross(a,b): return [a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]]
def unit(v):
    length=math.sqrt(sum(x*x for x in v))
    if length<1e-10: raise ValueError('Zero length vector')
    return [x/length for x in v]
def axes(a,b,rotation=0):
    """PyNite default axes in a Z-up global frame (solver X,Y,Z = X,Z,-Y)."""
    p,q=[a[0],a[2],-a[1]],[b[0],b[2],-b[1]]
    x=unit([q[i]-p[i] for i in range(3)])
    if math.isclose(p[0],q[0]) and math.isclose(p[2],q[2]):
        y=[-1 if q[1]>p[1] else 1,0,0]; z=[0,0,1]
    elif math.isclose(p[1],q[1]):
        y=[0,1,0]; z=unit(cross(x,y))
    else:
        proj=[q[0]-p[0],0,q[2]-p[2]]
        z=unit(cross(proj,x) if q[1]>p[1] else cross(x,proj)); y=unit(cross(z,x))
    theta=math.radians(rotation); c,s=math.cos(theta),math.sin(theta)
    def rotate(v):
        cv=cross(x,v); dot=sum(x[i]*v[i] for i in range(3))
        return [v[i]*c+cv[i]*s+x[i]*dot*(1-c) for i in range(3)]
    return [[v[0],-v[2],v[1]] for v in (x,rotate(y),rotate(z))]

def restraints(node):
    presets={'Free':[], 'Fixed':list(DOFS),'Pin':list(DOFS[:3]),'Roller':['UZ'],'RollerX':['UX'],'RollerY':['UY'],'Custom':[],'Spring':[]}
    return node.get('restraints',presets[node.get('support','Free')])

def weight_density(material):
    if 'mass_density' in material:
        if 'rho' in material: raise ValueError('Choose mass_density [kg/m3] OR rho weight density [kN/m3], not both')
        return material['mass_density']*9.80665/1000
    return material.get('rho',0)

def validate3d(data):
    if __package__: from .model import ModelError
    else: from model import ModelError
    try:
        if __package__: from .thai_code import validate_combinations
        else: from thai_code import validate_combinations
        validate_combinations(data)
        d=json.loads(json.dumps(data,allow_nan=False))
        if d.get('schema')!=2 or d.get('dimension')!='3D': raise ValueError('Expected schema 2 / dimension 3D')
        if not isinstance(d.get('self_weight',False),bool): raise ValueError('self_weight must be boolean')
        def number(v,label,positive=False):
            if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or (positive and v<=0): raise ValueError(label+': expected finite '+('positive ' if positive else '')+'number')
        reg={}
        for name in ('nodes','members','materials','sections'):
            rows=d[name]; ids=[r['id'] for r in rows]
            if not rows or any(not isinstance(i,str) or not i.strip() for i in ids) or len(ids)!=len(set(ids)): raise ValueError(name+': empty/duplicate/invalid IDs')
            reg[name]={r['id']:r for r in rows}
        cases=d['cases']
        if not cases or any(not isinstance(c,str) or not c.strip() for c in cases) or len(cases)!=len(set(cases)): raise ValueError('Invalid load cases')
        for c,factors in d.get('combinations',{}).items():
            if not c or c in cases or not factors: raise ValueError('Combination name must be unique and contain factors')
            for case,factor in factors.items():
                if case not in cases: raise ValueError('Unknown combination load case')
                number(factor,'factor')
        if d.get('self_weight',False) and d.get('self_weight_case') not in cases: raise ValueError('Choose one self_weight_case; self-weight is never automatically added to every 3D case')
        for n in d['nodes']:
            for k in ('x','y','z'): number(n[k],k)
            if n.get('support','Free') not in ('Free','Fixed','Pin','Roller','RollerX','RollerY','Custom','Spring'): raise ValueError('Unknown support')
            flags=restraints(n)
            if not isinstance(flags,list) or len(flags)!=len(set(flags)) or any(k not in DOFS for k in flags): raise ValueError('Invalid support DOFs')
            for k,v in n.get('springs',{}).items():
                if k not in DOFS or k in flags: raise ValueError('Spring DOF invalid or also fixed')
                number(v,'spring stiffness',True)
        for i,a in enumerate(d['nodes']):
            for b in d['nodes'][i+1:]:
                if math.dist(xyz(a),xyz(b))<1e-8: raise ValueError('Coincident nodes; merge explicitly')
        for material in d['materials']:
            for k in ('E','G'): number(material[k],k,True)
            number(material.get('nu',.3),'nu'); number(weight_density(material),'weight density')
            if not -1<material.get('nu',.3)<.5 or weight_density(material)<0: raise ValueError('Invalid material nu/density')
        for section in d['sections']:
            for k in ('A','Iy','Iz','J'): number(section[k],k,True)
        lengths={}; used=set(); pairs=set(); adj={n['id']:set() for n in d['nodes']}
        for m in d['members']:
            a,b=reg['nodes'][m['i']],reg['nodes'][m['j']]
            lengths[m['id']]=math.dist(xyz(a),xyz(b))
            if lengths[m['id']]<1e-8: raise ValueError('Zero length member')
            if m['type'] not in ('Beam','Column','Frame','Truss'): raise ValueError('Unknown member type')
            reg['materials'][m['material']]; reg['sections'][m['section']]; number(m.get('rotation',0),'section rotation')
            pair=tuple(sorted((m['i'],m['j'])))
            if pair in pairs: raise ValueError('Duplicate member connectivity')
            pairs.add(pair); used.update(pair); adj[m['i']].add(m['j']); adj[m['j']].add(m['i'])
            for end in ('release_i','release_j'):
                flags=m.get(end,[])
                if not isinstance(flags,list) or len(flags)!=len(set(flags)) or any(k not in DOFS for k in flags): raise ValueError('Release must list local DOFs')
            if any(k in m.get('release_i',[]) and k in m.get('release_j',[]) for k in ('UX','RX')): raise ValueError('Axial/torsion release at both ends is unstable')
        if used!=set(reg['nodes']): raise ValueError('Disconnected/orphan nodes')
        remaining=set(used)
        while remaining:
            component=set(); stack=[next(iter(remaining))]
            while stack:
                n=stack.pop()
                if n in component: continue
                component.add(n); stack.extend(adj[n]-component)
            remaining-=component
            if not any(restraints(reg['nodes'][n]) or reg['nodes'][n].get('springs') for n in component): raise ValueError('Unrestrained connected component')
        for p in d.get('point_loads',[]):
            if ('node' in p)==('member' in p): raise ValueError('Exactly one point load target required')
            if p['case'] not in cases or p['direction'] not in (GLOBAL if 'node' in p else GLOBAL+LOCAL): raise ValueError('Invalid point direction/case')
            number(p['value'],'load')
            if 'node' in p: reg['nodes'][p['node']]
            else:
                number(p['x'],'position')
                if not 0<=p['x']<=lengths[p['member']]: raise ValueError('Point load outside member')
                if reg['members'][p['member']]['type']=='Truss': raise ValueError('Apply truss loads at nodes')
        for p in d.get('distributed_loads',[]):
            L=lengths[p['member']]
            if p['case'] not in cases or p['direction'] not in GLOBAL[:3]+LOCAL[:3]: raise ValueError('Invalid distributed direction/case')
            for k in ('w1','w2'): number(p[k],k)
            for v in (p.get('x1',0),p.get('x2',L)): number(v,'load extent')
            if not 0<=p.get('x1',0)<p.get('x2',L)<=L: raise ValueError('Invalid distributed extent')
            if reg['members'][p['member']]['type']=='Truss': raise ValueError('Apply truss loads at nodes')
            if p.get('source')=='self_weight' and d.get('self_weight',False): raise ValueError('Self-weight already explicit; disable automatic self-weight')
        return d
    except (KeyError,ValueError,TypeError) as exc:
        raise ModelError('Invalid 3D model: '+str(exc)) from exc

def migrate2d(data):
    """Explicit copy; legacy screen-CCW MY becomes physical global -MY."""
    if __package__: from .model import validate
    else: from model import validate
    d=copy.deepcopy(validate(data))
    if d['schema']==2: return d
    d.update(schema=2,dimension='3D',combinations=d.get('combinations',{}))
    for n in d['nodes']:
        n['y']=0
        plane={'Free':[],'Fixed':['UX','UZ','RY'],'Pin':['UX','UZ'],'Roller':['UZ'],'RollerX':['UX']}[n.get('support','Free')]
        n['restraints']=plane+['UY','RX','RZ']; n['support']='Custom'
    for m in d['members']:
        for end in ('release_i','release_j'): m[end]=['RZ'] if m.get(end,False) else []
        # Legacy local y is in-plane; section rotation is zero in this mapping.
    for p in d.get('point_loads',[]):
        if p['direction']=='MY': p['value']=-p['value']
    # Preserve legacy self-weight-in-every-case with explicit loads, not a changed policy.
    if d.get('self_weight'):
        mats={m['id']:m for m in d['materials']}; secs={s['id']:s for s in d['sections']}; ns={n['id']:n for n in d['nodes']}
        for case in ([d['self_weight_case']] if d.get('self_weight_case') else d['cases']):
            for m in d['members']:
                w=weight_density(mats[m['material']])*secs[m['section']]['A']
                if m['type']=='Truss':
                    half=w*math.dist(xyz(ns[m['i']]),xyz(ns[m['j']]))/2
                    for node in (m['i'],m['j']): d['point_loads'].append({'node':node,'direction':'FZ','value':-half,'case':case,'source':'self_weight'})
                else: d['distributed_loads'].append({'member':m['id'],'direction':'FZ','w1':-w,'w2':-w,'case':case,'source':'self_weight'})
        d['self_weight']=False
    return validate3d(d)

def from_lines(lines,template,tolerance=1e-7):
    """Preview only: caller must show the editor before storing in a document."""
    d=copy.deepcopy(template); d.update(schema=2,dimension='3D',nodes=[],members=[],point_loads=[],distributed_loads=[],self_weight=False)
    def node(point):
        if len(point)!=3 or not all(isinstance(v,(int,float)) and math.isfinite(v) for v in point): raise ValueError('Geometry must provide finite XYZ points')
        for n in d['nodes']:
            if math.dist(point,xyz(n))<=tolerance: return n['id']
        name='N'+str(len(d['nodes'])+1); d['nodes'].append(dict(id=name,x=point[0],y=point[1],z=point[2],support='Free')); return name
    pairs=set()
    for a,b in lines:
        i,j=node(a),node(b); pair=tuple(sorted((i,j)))
        if i==j or pair in pairs: continue
        pairs.add(pair); d['members'].append(dict(id='M'+str(len(d['members'])+1),i=i,j=j,type='Frame',material=d['materials'][0]['id'],section=d['sections'][0]['id']))
    return d
