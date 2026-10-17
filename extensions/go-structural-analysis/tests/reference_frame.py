"""Independent textbook 2D direct-stiffness reference (no PyNite imports).

Prismatic Euler-Bernoulli element, global X/Z, positive CCW rotation.
Consistent nodal load vector for uniform global loads. Used as a reference
solution for portals and continuous beams, alongside closed-form benchmarks.
"""
import math
import numpy as np

def reference(model,case='LC1'):
    ids=[n['id'] for n in model['nodes']]; ns={n['id']:n for n in model['nodes']}; mats={m['id']:m for m in model['materials']}; sections={s['id']:s for s in model['sections']}
    K=np.zeros((3*len(ids),3*len(ids))); F=np.zeros(3*len(ids)); elements={}
    for m in model['members']:
        a,b=ns[m['i']],ns[m['j']]; L=math.hypot(b['x']-a['x'],b['z']-a['z']); c=(b['x']-a['x'])/L; s=(b['z']-a['z'])/L
        E=mats[m['material']]['E']; A=sections[m['section']]['A']; I=sections[m['section']]['Iz']; ea=E*A/L; v=E*I/L**3
        k=np.array([[ea,0,0,-ea,0,0],[0,12*v,6*L*v,0,-12*v,6*L*v],[0,6*L*v,4*L*L*v,0,-6*L*v,2*L*L*v],[-ea,0,0,ea,0,0],[0,-12*v,-6*L*v,0,12*v,-6*L*v],[0,6*L*v,2*L*L*v,0,-6*L*v,4*L*L*v]])
        T=np.zeros((6,6)); R=np.array([[c,s,0],[-s,c,0],[0,0,1]])
        T[:3,:3]=R; T[3:,3:]=R
        dofs=[3*ids.index(m['i'])+i for i in range(3)]+[3*ids.index(m['j'])+i for i in range(3)]
        q=np.zeros(6)
        for load in model.get('distributed_loads',[]):
            if load['case']!=case or load['member']!=m['id']: continue
            assert load['w1']==load['w2'] and not load.get('x1') and load.get('x2',L)==L
            gx=load['w1'] if load['direction']=='FX' else 0; gz=load['w1'] if load['direction']=='FZ' else 0
            qx=c*gx+s*gz; qy=-s*gx+c*gz
            q+=np.array([qx*L/2,qy*L/2,qy*L*L/12,qx*L/2,qy*L/2,-qy*L*L/12])
        K[np.ix_(dofs,dofs)]+=T.T@k@T; F[dofs]+=T.T@q; elements[m['id']]=(L,k,T,dofs,q)
    for p in model.get('point_loads',[]):
        if p['case']==case:
            assert 'node' in p
            F[3*ids.index(p['node'])+{'FX':0,'FZ':1,'MY':2}[p['direction']]]+=p['value']
    fixed=[]
    for i,n in enumerate(model['nodes']):
        support=n.get('support','Free')
        if support in ['Fixed','Pin','RollerX']: fixed.append(3*i)
        if support in ['Fixed','Pin','Roller']: fixed.append(3*i+1)
        if support=='Fixed': fixed.append(3*i+2)
    free=[i for i in range(len(F)) if i not in fixed]; u=np.zeros(len(F)); u[free]=np.linalg.solve(K[np.ix_(free,free)],F[free]); reaction=K@u-F
    out={n:{'ux':u[3*i],'uz':u[3*i+1],'rotation':u[3*i+2],'Rx':reaction[3*i],'Rz':reaction[3*i+1],'My':reaction[3*i+2]} for i,n in enumerate(ids)}
    return out,elements,u

def uniform_beam_displacement(model,member_id,x,solution):
    _,elements,u=solution; L,k,T,dofs,q=elements[member_id]; d=T@u[dofs]; t=x/L
    hermite=np.array([1-3*t*t+2*t**3,L*(t-2*t*t+t**3),3*t*t-2*t**3,L*(-t*t+t**3)])
    m=next(m for m in model['members'] if m['id']==member_id); E=next(v for v in model['materials'] if v['id']==m['material'])['E']; I=next(v for v in model['sections'] if v['id']==m['section'])['Iz']
    qy=2*q[1]/L
    return float(hermite@d[[1,2,4,5]]+qy*x*x*(L-x)**2/(24*E*I))
