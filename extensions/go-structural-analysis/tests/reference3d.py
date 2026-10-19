"""Independent textbook space-frame stiffness, no Pynite/production model imports.

Nodal loads only, prismatic unreleased Euler-Bernoulli members. Trusses have
3 translational DOFs; frames have 6. Used for portal/multibay/tripod benchmarks.
"""
import numpy as np
import math

def basis(a,b,rotation):
    x=np.array(b)-a; x=x/np.linalg.norm(x)
    if np.linalg.norm(np.cross(x,[0,0,1]))<1e-10:
        y=np.array([-1 if x[2]>0 else 1,0,0]); z=np.cross(x,y)
    else:
        z=np.cross(x,[0,0,1]); z/=np.linalg.norm(z); y=np.cross(z,x)
    c,s=math.cos(math.radians(rotation)),math.sin(math.radians(rotation))
    return np.array([x,c*y+s*z,-s*y+c*z])

def reference3d(d,case):
    ns={n['id']:n for n in d['nodes']}; ids=list(ns); mats={m['id']:m for m in d['materials']}; secs={s['id']:s for s in d['sections']}
    truss=all(m['type']=='Truss' for m in d['members']); nd=3 if truss else 6; K=np.zeros((len(ids)*nd,len(ids)*nd)); F=np.zeros(len(K)); elements={}
    for m in d['members']:
        a,b=[[ns[node][k] for k in ('x','y','z')] for node in (m['i'],m['j'])]; L=math.dist(a,b); mat=mats[m['material']]; sec=secs[m['section']]; R=basis(a,b,m.get('rotation',0))
        if truss:
            g=mat['E']*sec['A']/L*np.outer(R[0],R[0]); k=np.block([[g,-g],[-g,g]]); T=np.eye(6)
        else:
            k=np.zeros((12,12)); T=np.zeros((12,12))
            for i in (0,3,6,9): T[i:i+3,i:i+3]=R
            for indices,value in (([0,6],mat['E']*sec['A']/L),([3,9],mat['G']*sec['J']/L)):
                k[np.ix_(indices,indices)]+=value*np.array([[1,-1],[-1,1]])
            block=np.array([[12,6*L,-12,6*L],[6*L,4*L*L,-6*L,2*L*L],[-12,-6*L,12,-6*L],[6*L,2*L*L,-6*L,4*L*L]])
            for indices,I,signs in (([1,5,7,11],sec['Iz'],[1,1,1,1]),([2,4,8,10],sec['Iy'],[1,-1,1,-1])):
                k[np.ix_(indices,indices)]+=mat['E']*I/L**3*block*np.outer(signs,signs)
        index=[ids.index(node)*nd+j for node in (m['i'],m['j']) for j in range(nd)]
        K[np.ix_(index,index)]+=T.T@k@T; elements[m['id']]=(index,T,k)
    factors=d.get('combinations',{}).get(case,{case:1})
    for p in d['point_loads']:
        if p['case'] in factors:
            assert 'node' in p and p['direction'].isupper()
            F[ids.index(p['node'])*nd+('FX','FY','FZ','MX','MY','MZ').index(p['direction'])]+=p['value']*factors[p['case']]
    fixed=[]
    for i,n in enumerate(d['nodes']):
        flags=n.get('restraints',{'Fixed':['UX','UY','UZ','RX','RY','RZ'],'Pin':['UX','UY','UZ'],'Free':[]}[n.get('support','Free')])
        fixed.extend(i*nd+j for j,k in enumerate(('UX','UY','UZ','RX','RY','RZ')[:nd]) if k in flags)
    free=[i for i in range(len(F)) if i not in fixed]; u=np.zeros(len(F)); u[free]=np.linalg.solve(K[np.ix_(free,free)],F[free]); reactions=K@u-F
    nodes={n:{k:float(u[i*nd+j]) for j,k in enumerate(('ux','uy','uz','rx','ry','rz')[:nd])} for i,n in enumerate(ids)}
    for i,n in enumerate(ids): nodes[n].update({k:float(reactions[i*nd+j]) for j,k in enumerate(('Fx','Fy','Fz','Mx','My','Mz')[:nd])})
    ends={mid:(T@u[index] if truss else k@T@u[index]) for mid,(index,T,k) in elements.items()}
    return nodes,ends
