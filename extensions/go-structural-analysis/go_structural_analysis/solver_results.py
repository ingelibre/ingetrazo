"""PyNite 3.2 continuous-segment adapter; polynomial roots, never sampled extrema."""
import math
import numpy as np
if __package__:
    from .results import evaluate
else:
    from results import evaluate

def check_stiffness(model,case):
    """Reject tiny release-condensation pivots that a residual-only solve can miss.

    Compare sparse LU pivots to floating-point roundoff of the active stiffness.
    This also tests unloaded mechanisms, whose equilibrium residual is zero.
    """
    from scipy.sparse.linalg import splu
    flags=('support_DX','support_DY','support_DZ','support_RX','support_RY','support_RZ')
    active=[n.ID*6+i for n in model.nodes.values() for i,name in enumerate(flags) if not getattr(n,name)]
    if not active: return
    matrix=model.Ke(case,check_stability=False,sparse=True).tocsr()[active,:][:,active].tocsc()
    try: lu=splu(matrix)
    except RuntimeError as exc: raise RuntimeError('Structural stiffness is singular: unstable mechanism') from exc
    scale=max(abs(matrix.data),default=0.)
    tolerance=np.finfo(float).eps*max(1,len(active))*scale
    if np.min(np.abs(lu.U.diagonal()))<=tolerance:
        raise RuntimeError('Structural stiffness is numerically singular: unstable mechanism after member releases or inadequate restraints')

def extract_member(m,case):
    segments=[]; subs=list(m.sub_members.values()); offset=0.
    for sub in subs:
        sub.deflection('dy',0,case)  # asks PyNite to populate segments for this case
        for s in sub.SegmentsZ:
            h=s.x2-s.x1; dw=(s.w2-s.w1)/h; dp=(s.p2-s.p1)/h
            coefficients={
                'N':[s.P1,s.p1,dp/2], 'V':[s.V1,s.w1,dw/2],
                'M':[s.M1,-s.V1,-s.w1/2,-dw/6],
                'd':[s.delta1,s.theta1,-s.M1/(2*s.EI),s.V1/(6*s.EI),s.w1/(24*s.EI),dw/(120*s.EI)],
                'u':[s.delta_x1,-s.P1/s.EA,-s.p1/(2*s.EA),-dp/(6*s.EA)]}
            segments.append({'x1':float(offset+s.x1),'x2':float(offset+s.x2),'coefficients':{k:[float(v) for v in a] for k,a in coefficients.items()}})
        offset+=sub.L()
    rotation=m.T()[:3,:3]; basis=[[float(rotation[i,0]),float(rotation[i,1])] for i in range(2)]
    member={'L':float(m.L()),'basis':basis,'segments':segments,'extrema':{},'plot':[]}
    for key in ('N','V','M','d'):
        candidates=[]
        for s in segments:
            h=s['x2']-s['x1']; poly=np.polynomial.Polynomial(s['coefficients'][key])
            xs=[0.,h]+[float(r.real) for r in poly.deriv().roots() if abs(r.imag)<1e-8 and 0<r.real<h]
            for x in xs:
                candidates.append({'x':float(s['x1']+x),'value':float(poly(x)),'side':'left' if x==h else 'right'})
        member['extrema'][key]={'min':min(candidates,key=lambda p:p['value']),'max':max(candidates,key=lambda p:p['value'])}
    # Plot vertices include all load jumps, segment boundaries and exact extrema.
    for s in segments:
        xs=set(float(x) for x in np.linspace(s['x1'],s['x2'],31))
        for extrema in member['extrema'].values():
            for p in extrema.values():
                if s['x1']<p['x']<s['x2']: xs.add(p['x'])
        for x in sorted(xs):
            side='left' if abs(x-s['x2'])<1e-10 else 'right'
            p=evaluate(member,x,side); p['side']=side; member['plot'].append(p)
    first=subs[0].f(case).flatten(); last=subs[-1].f(case).flatten()
    member['end_forces']={'i':{'N':float(first[0]),'V':float(first[1]),'M':float(first[5])},'j':{'N':float(last[6]),'V':float(last[7]),'M':float(last[11])}}
    return member

def equilibrium(model,nodes,case):
    import copy
    factors=model.get('combinations',{}).get(case,{case:1.})
    model=copy.deepcopy(model)
    for field,keys in [('point_loads',('value',)),('distributed_loads',('w1','w2'))]:
        rows=[]
        for p in model.get(field,[]):
            if p['case'] not in factors: continue
            p=copy.deepcopy(p)
            for key in keys: p[key]*=factors[p['case']]
            p['case']=case; rows.append(p)
        model[field]=rows
    sw_factor=factors.get(model['self_weight_case'],0) if model.get('self_weight_case') else sum(factors.values())
    ns={n['id']:n for n in model['nodes']}; ms={m['id']:m for m in model['members']}
    load=[0.,0.,0.]
    def add(x,z,fx=0.,fz=0.,moment=0.):
        load[0]+=fx; load[1]+=fz; load[2]+=x*fz-z*fx+moment
    for p in model.get('point_loads',[]):
        if p['case']!=case: continue
        if 'node' in p: n=ns[p['node']]; x,z=n['x'],n['z']
        else:
            m=ms[p['member']]; a,b=ns[m['i']],ns[m['j']]; L=math.hypot(b['x']-a['x'],b['z']-a['z']); t=p['x']/L; x=a['x']+t*(b['x']-a['x']); z=a['z']+t*(b['z']-a['z'])
        add(x,z,fx=p['value'] if p['direction']=='FX' else 0.,fz=p['value'] if p['direction']=='FZ' else 0.,moment=p['value'] if p['direction']=='MY' else 0.)
    loads=[p for p in model.get('distributed_loads',[]) if p['case']==case]
    if model.get('self_weight',False):
        materials={v['id']:v for v in model['materials']}; sections={v['id']:v for v in model['sections']}
        loads+= [{'member':m['id'],'direction':'FZ','w1':-materials[m['material']].get('rho',0)*sections[m['section']]['A']*sw_factor,'w2':-materials[m['material']].get('rho',0)*sections[m['section']]['A']*sw_factor} for m in model['members']]
    for p in loads:
        m=ms[p['member']]; a,b=ns[m['i']],ns[m['j']]; L=math.hypot(b['x']-a['x'],b['z']-a['z']); x1=p.get('x1',0.); h=p.get('x2',L)-x1
        resultant=h*(p['w1']+p['w2'])/2; first_moment=x1*resultant+h*h*(p['w1']+2*p['w2'])/6
        moment_x=a['x']*resultant+(b['x']-a['x'])/L*first_moment; moment_z=a['z']*resultant+(b['z']-a['z'])/L*first_moment
        if p['direction']=='FX': load[0]+=resultant; load[2]-=moment_z
        else: load[1]+=resultant; load[2]+=moment_x
    reaction=[sum(n['Rx'] for n in nodes.values()),sum(n['Rz'] for n in nodes.values()),sum(n['My']+ns[k]['x']*n['Rz']-ns[k]['z']*n['Rx'] for k,n in nodes.items())]
    residual=[load[i]+reaction[i] for i in range(3)]; tolerance=[1e-7*max(1.,abs(load[i]),abs(reaction[i])) for i in range(3)]
    return {'applied':load,'reaction':reaction,'residual':residual,'tolerance':tolerance,'passed':all(abs(v)<=t for v,t in zip(residual,tolerance))}
