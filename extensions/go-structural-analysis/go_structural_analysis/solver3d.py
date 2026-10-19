"""PyNite 3.2 adapter. Proper rotation: solver (X,Y,Z) = host (X,Z,-Y)."""
import math
from importlib.metadata import version
import numpy as np
if __package__:
    from .model3d import validate3d,xyz,axes,restraints,weight_density,DOFS,cross
    from .results import model_hash,evaluate
    from .solver_results import check_stiffness
else:
    from model3d import validate3d,xyz,axes,restraints,weight_density,DOFS,cross
    from results import model_hash,evaluate
    from solver_results import check_stiffness

FORCES=('N','Vy','Vz','T','My','Mz')
QUANTITIES=FORCES+('u','dy','dz','D')
DOF_MAP={'UX':'DX','UY':'DZ','UZ':'DY','RX':'RX','RY':'RZ','RZ':'RY'}
def mapped(direction):
    if direction[1].islower(): return direction,1
    mapping={'FX':('FX',1),'FY':('FZ',-1),'FZ':('FY',1),'MX':('MX',1),'MY':('MZ',-1),'MZ':('MY',1)}
    return mapping[direction]
def to_host(v): return [float(v[0]),-float(v[2]),float(v[1])]

def member_result(member,case):
    segments=[]; offset=0.; subs=list(member.sub_members.values())
    for sub in subs:
        sub.deflection('dy',0,case)
        for sz,sy,sx in zip(sub.SegmentsZ,sub.SegmentsY,sub.SegmentsX):
            h=sz.x2-sz.x1; wz=(sz.w2-sz.w1)/h; wy=(sy.w2-sy.w1)/h; dp=(sz.p2-sz.p1)/h
            co={'N':[sz.P1,sz.p1,dp/2], 'Vy':[sz.V1,sz.w1,wz/2], 'Mz':[sz.M1,-sz.V1,-sz.w1/2,-wz/6],
                'Vz':[sy.V1,sy.w1,wy/2], 'My':[-sy.M1,-sy.V1,-sy.w1/2,-wy/6], 'T':[sx.T1],
                'u':[sz.delta_x1,-sz.P1/sz.EA,-sz.p1/(2*sz.EA),-dp/(6*sz.EA)],
                'dy':[sz.delta1,sz.theta1,-sz.M1/(2*sz.EI),sz.V1/(6*sz.EI),sz.w1/(24*sz.EI),wz/(120*sz.EI)],
                'dz':[sy.delta1,-sy.theta1,sy.M1/(2*sy.EI),sy.V1/(6*sy.EI),sy.w1/(24*sy.EI),wy/(120*sy.EI)]}
            segments.append(dict(x1=float(offset+sz.x1),x2=float(offset+sz.x2),coefficients={k:[float(v) for v in c] for k,c in co.items()}))
        offset+=sub.L()
    basis=[to_host(v) for v in member.T()[:3,:3]]
    out=dict(L=float(member.L()),basis=basis,segments=segments,extrema={},plot=[])
    for key in QUANTITIES:
        candidates=[]
        for s in segments:
            h=s['x2']-s['x1']; P=np.polynomial.Polynomial
            poly=sum((P(s['coefficients'][k])**2 for k in ('u','dy','dz')),P([0])) if key=='D' else P(s['coefficients'][key])
            xs=[0.,h]+[float(v.real) for v in poly.deriv().roots() if abs(v.imag)<1e-8 and 0<v.real<h]
            for x in xs:
                value=float(math.sqrt(max(0,poly(x)))) if key=='D' else float(poly(x))
                candidates.append(dict(x=s['x1']+x,value=value,side='left' if x==h else 'right'))
        out['extrema'][key]={'min':min(candidates,key=lambda p:p['value']),'max':max(candidates,key=lambda p:p['value'])}
    for s in segments:
        xs=set(float(v) for v in np.linspace(s['x1'],s['x2'],25))
        for e in out['extrema'].values():
            for p in e.values():
                if s['x1']<p['x']<s['x2']: xs.add(p['x'])
        for x in sorted(xs):
            side='left' if abs(x-s['x2'])<1e-10 else 'right'; p=evaluate(out,x,side); p['side']=side; out['plot'].append(p)
    fi,fj=subs[0].f(case).flatten()[:6],subs[-1].f(case).flatten()[6:]
    order=('N','Vy','Vz','T','My','Mz')
    out['end_forces']={end:{k:float(v) for k,v in zip(order,values)} for end,values in (('i',fi),('j',fj))}
    return out

def applied_loads(d,case):
    """Independent global wrench integration, including varying/local loads."""
    ns={n['id']:n for n in d['nodes']}; ms={m['id']:m for m in d['members']}
    factors=d.get('combinations',{}).get(case,{case:1}); total=np.zeros(6); absolute=np.zeros(6)
    def add(point,force,moment):
        wrench=np.r_[force,np.asarray(cross(point,force))+moment]; total[:]+=wrench; absolute[:]+=np.abs(wrench)
    def vector(direction,value,member=None):
        vec=np.zeros(3); index='xyz'.index(direction[1].lower())
        if direction[1].islower():
            basis=axes(xyz(ns[member['i']]),xyz(ns[member['j']]),member.get('rotation',0)); vec=np.array(basis[index])*value
        else: vec[index]=value
        return vec
    for p in d.get('point_loads',[]):
        factor=factors.get(p['case'],0)
        if not factor: continue
        m=ms.get(p.get('member')); point=np.asarray(xyz(ns[p['node']])) if 'node' in p else np.asarray(xyz(ns[m['i']]))+np.array(axes(xyz(ns[m['i']]),xyz(ns[m['j']]))[0])*p['x']
        v=vector(p['direction'],p['value']*factor,m); add(point,v if p['direction'][0]=='F' else np.zeros(3),v if p['direction'][0]=='M' else np.zeros(3))
    distributed=list(d.get('distributed_loads',[]))
    if d.get('self_weight'):
        mats={m['id']:m for m in d['materials']}; secs={s['id']:s for s in d['sections']}
        for m in d['members']:
            w=-weight_density(mats[m['material']])*secs[m['section']]['A']
            distributed.append(dict(member=m['id'],direction='FZ',w1=w,w2=w,case=d['self_weight_case']))
    for p in distributed:
        factor=factors.get(p['case'],0)
        if not factor: continue
        m=ms[p['member']]; a,b=xyz(ns[m['i']]),xyz(ns[m['j']]); L=math.dist(a,b); x1=p.get('x1',0); h=p.get('x2',L)-x1
        force=vector(p['direction'],factor*h*(p['w1']+p['w2'])/2,m)
        first=vector(p['direction'],factor*(x1*h*(p['w1']+p['w2'])/2+h*h*(p['w1']+2*p['w2'])/6),m)
        arm=np.array(axes(a,b)[0]); moment=np.array(cross(a,force))+np.array(cross(arm,first))
        wrench=np.r_[force,moment]; total+=wrench; absolute+=np.abs(wrench)
    return total,absolute

def equilibrium3d(d,nodes,case):
    applied,absolute=applied_loads(d,case); reaction=np.zeros(6); ns={n['id']:n for n in d['nodes']}
    for n,v in nodes.items():
        force=np.array([v[k] for k in ('Fx','Fy','Fz')]); moment=np.array([v[k] for k in ('Mx','My','Mz')])+cross(xyz(ns[n]),force)
        wrench=np.r_[force,moment]; reaction+=wrench; absolute+=np.abs(wrench)
    residual=applied+reaction; tolerance=1e-7*np.maximum(1,absolute)
    return dict(components=['Fx','Fy','Fz','Mx','My','Mz'],applied=applied.tolist(),reaction=reaction.tolist(),residual=residual.tolist(),tolerance=tolerance.tolist(),passed=bool(np.all(np.abs(residual)<=tolerance)))

def envelopes(cases,names):
    """Exact extrema across combinations, retaining governing name/x/side."""
    out={'combinations':names,'members':{},'nodes':{}}
    if not names: return out
    for mid in cases[names[0]]['members']:
        out['members'][mid]={}
        for key in QUANTITIES:
            candidates=[dict(v,combination=c) for c in names for v in cases[c]['members'][mid]['extrema'][key].values()]
            out['members'][mid][key]={'min':min(candidates,key=lambda v:v['value']),'max':max(candidates,key=lambda v:v['value'])}
    for node in cases[names[0]]['nodes']:
        out['nodes'][node]={}
        for key in ('ux','uy','uz','rx','ry','rz','Fx','Fy','Fz','Mx','My','Mz'):
            values=[dict(value=cases[c]['nodes'][node][key],combination=c) for c in names]
            out['nodes'][node][key]={'min':min(values,key=lambda v:v['value']),'max':max(values,key=lambda v:v['value'])}
    return out

def solve3d(data):
    from Pynite import FEModel3D
    if version('PyNiteFEA')!='3.2.0': raise RuntimeError('Solver must be PyNiteFEA 3.2.0')
    d=validate3d(data); f=FEModel3D(); ns={n['id']:n for n in d['nodes']}
    for n in d['nodes']:
        f.add_node(n['id'],n['x'],n['z'],-n['y']); flags=restraints(n)
        truss_only=all(m['type']=='Truss' for m in d['members'] if n['id'] in (m['i'],m['j']))
        if truss_only:
            for p in d.get('point_loads',[]):
                if p.get('node')==n['id'] and p['direction'].startswith('M') and p['value']!=0 and 'R'+p['direction'][1] not in flags and 'R'+p['direction'][1] not in n.get('springs',{}): raise ValueError('Nodal moment cannot be transmitted by a truss joint')
        flags=set(flags)| (set(DOFS[3:])-set(n.get('springs',{})) if truss_only else set())
        f.def_support(n['id'],*[k in {DOF_MAP[v] for v in flags} for k in ('DX','DY','DZ','RX','RY','RZ')])
        for k,v in n.get('springs',{}).items(): f.def_support_spring(n['id'],DOF_MAP[k],v)
    for m in d['materials']: f.add_material(m['id'],m['E'],m['G'],m.get('nu',.3),weight_density(m))
    for s in d['sections']: f.add_section(s['id'],s['A'],s['Iy'],s['Iz'],s['J'])
    for m in d['members']:
        f.add_member(m['id'],m['i'],m['j'],m['material'],m['section'],rotation=m.get('rotation',0))
        releases={}
        for end in ('i','j'):
            flags=set(m.get('release_'+end,[]))
            if m['type']=='Truss': flags|={'RY','RZ'}|({'RX'} if end=='i' else set())
            for dof in flags: releases[{'UX':'Dx','UY':'Dy','UZ':'Dz','RX':'Rx','RY':'Ry','RZ':'Rz'}[dof]+end]=True
        f.def_releases(m['id'],**releases)
        # Fail explicitly if UI basis and actual solver transformation diverge.
        actual=np.array([to_host(v) for v in f.members[m['id']].T()[:3,:3]])
        if not np.allclose(actual,axes(xyz(ns[m['i']]),xyz(ns[m['j']]),m.get('rotation',0)),atol=1e-10): raise RuntimeError('Local/global transformation mismatch')
    for c in d['cases']: f.add_load_combo(c,{c:1})
    for c,factors in d.get('combinations',{}).items(): f.add_load_combo(c,factors)
    for p in d.get('point_loads',[]):
        direction,sign=mapped(p['direction'])
        if 'node' in p: f.add_node_load(p['node'],direction,sign*p['value'],p['case'])
        else: f.add_member_pt_load(p['member'],direction,sign*p['value'],p['x'],p['case'])
    for p in d.get('distributed_loads',[]):
        direction,sign=mapped(p['direction']); f.add_member_dist_load(p['member'],direction,sign*p['w1'],sign*p['w2'],p.get('x1',0),p.get('x2'),p['case'])
    if d.get('self_weight'):
        mats={m['id']:m for m in d['materials']}; secs={s['id']:s for s in d['sections']}; case=d['self_weight_case']
        for m in d['members']:
            w=weight_density(mats[m['material']])*secs[m['section']]['A']
            if m['type']=='Truss':
                half=w*math.dist(xyz(ns[m['i']]),xyz(ns[m['j']]))/2
                for node in (m['i'],m['j']): f.add_node_load(node,'FY',-half,case)
            else: f.add_member_dist_load(m['id'],'FY',-w,-w,case=case)
    f.analyze_linear(check_stability=True,check_statics=False)
    check_stiffness(f,d['cases'][0])
    result=dict(solver='PyNiteFEA',version=version('PyNiteFEA'),extension_version='0.2.4',result_schema=3,dimension='3D',model_hash=model_hash(d),units='kN,m,rad',cases={})
    for c in list(d['cases'])+list(d.get('combinations',{})):
        nodes={}
        for name,n in f.nodes.items():
            values=to_host([n.DX[c],n.DY[c],n.DZ[c]])+to_host([n.RX[c],n.RY[c],n.RZ[c]])+to_host([n.RxnFX[c],n.RxnFY[c],n.RxnFZ[c]])+to_host([n.RxnMX[c],n.RxnMY[c],n.RxnMZ[c]])
            nodes[name]=dict(zip(('ux','uy','uz','rx','ry','rz','Fx','Fy','Fz','Mx','My','Mz'),values))
            nodes[name]['D']=math.sqrt(sum(v*v for v in values[:3]))
        members={mid:member_result(m,c) for mid,m in f.members.items()}
        balance=equilibrium3d(d,nodes,c)
        if not balance['passed']: raise RuntimeError('3D equilibrium failed: '+str(balance['residual']))
        result['cases'][c]=dict(nodes=nodes,members=members,equilibrium=balance)
    result['envelope']=envelopes(result['cases'],list(d.get('combinations',{})) or list(d['cases']))
    if __package__: from .safety import seal,envelope_groups
    else: from safety import seal,envelope_groups
    return seal(d,envelope_groups(result,d))
