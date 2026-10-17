"""Geometry and rigid-body screening; not a substitute for solver stiffness checks."""
import math
from .model3d import restraints

def rank(rows):
    a=[list(map(float,r)) for r in rows]; k=0
    for j in range(len(a[0]) if a else 0):
        pivot=max(range(k,len(a)),key=lambda i:abs(a[i][j]),default=None)
        if pivot is None or abs(a[pivot][j])<1e-10: continue
        a[k],a[pivot]=a[pivot],a[k]; v=a[k][j]; a[k]=[x/v for x in a[k]]
        for i in range(k+1,len(a)):
            v=a[i][j]; a[i]=[x-v*y for x,y in zip(a[i],a[k])]
        k+=1
    return k

def inspect_model(model,tolerance=1e-6):
    if not math.isfinite(tolerance) or tolerance<=0: raise ValueError('Tolerance must be positive [m]')
    issues=[]; nodes=model.get('nodes',[]); members=model.get('members',[]); is3d=model.get('schema')==2
    def issue(severity,code,ids,detail): issues.append(dict(severity=severity,code=code,entities=ids,detail=detail))
    ns={}; points={}; adj={}; segments=[]
    for n in nodes:
        ident=n.get('id','?'); p=[n.get('x',0),n.get('y',0) if is3d else 0,n.get('z',0)]
        if ident in ns: issue('Error','duplicate_node_id',['node:'+ident],'Repeated node ID')
        if not all(isinstance(v,(int,float)) and math.isfinite(v) for v in p):
            issue('Error','invalid_coordinate',['node:'+ident],'Non-finite/invalid coordinates'); continue
        for other,q in points.items():
            if math.dist(p,q)<=tolerance: issue('Error','coincident_nodes',['node:'+other,'node:'+ident],f'Distance {math.dist(p,q):.6g} m <= tolerance')
        ns[ident]=n; points[ident]=p; adj[ident]=set()
    seen=set(); pairs={}
    for m in members:
        ident=m.get('id','?'); i,j=m.get('i'),m.get('j')
        if ident in seen: issue('Error','duplicate_member_id',[ident],'Repeated member ID')
        seen.add(ident)
        if i not in points or j not in points:
            issue('Error','missing_node',[ident],'Member references an unknown/invalid node'); continue
        a,b=points[i],points[j]; length=math.dist(a,b)
        if length<=tolerance: issue('Error','zero_length',[ident],'Member length <= tolerance'); continue
        pair=tuple(sorted((i,j)))
        if pair in pairs: issue('Error','duplicate_member',[pairs[pair],ident],'Same endpoint nodes (including reversed direction)')
        pairs[pair]=ident; adj[i].add(j); adj[j].add(i); segments.append((m,a,b,length))
        if is3d and any(k in m.get('release_i',[]) and k in m.get('release_j',[]) for k in ('UX','RX')):
            issue('Error','unstable_release',[ident],'Axial/torsion release at both ends')
    def sub(a,b): return [x-y for x,y in zip(a,b)]
    def dot(a,b): return sum(x*y for x,y in zip(a,b))
    def on_segment(p,a,b,L):
        v=sub(b,a); t=dot(sub(p,a),v)/(L*L); q=[a[k]+t*v[k] for k in range(3)]
        return t,math.dist(p,q)
    for index,(m,a,b,L) in enumerate(segments):
        lower=[min(a[k],b[k])-tolerance for k in range(3)]; upper=[max(a[k],b[k])+tolerance for k in range(3)]
        for nid,p in points.items():
            if nid in (m['i'],m['j']): continue
            if any(p[k]<lower[k] or p[k]>upper[k] for k in range(3)): continue
            t,d=on_segment(p,a,b,L)
            if tolerance/L<t<1-tolerance/L and d<=tolerance:
                issue('Warning','node_on_member',['node:'+nid,m['id']],'Node lies inside member without an analytical joint; split/connect if intended')
        for other,c,d,K in segments[index+1:]:
            if any(max(c[k],d[k])<lower[k] or min(c[k],d[k])>upper[k] for k in range(3)): continue
            t0,h0=on_segment(c,a,b,L); t1,h1=on_segment(d,a,b,L)
            if max(h0,h1)<=tolerance:
                overlap=(min(1,max(t0,t1))-max(0,min(t0,t1)))*L
                if overlap>tolerance and tuple(sorted((m['i'],m['j'])))!=tuple(sorted((other['i'],other['j']))):
                    issue('Error','member_overlap',[m['id'],other['id']],f'Collinear overlap {overlap:.6g} m')
                continue
            if {m['i'],m['j']} & {other['i'],other['j']}: continue
            u,v,w=sub(b,a),sub(d,c),sub(a,c); uv=dot(u,v); den=L*L*K*K-uv*uv
            if den<=1e-12*L*L*K*K: continue
            t=(uv*dot(v,w)-K*K*dot(u,w))/den; s=(L*L*dot(v,w)-uv*dot(u,w))/den
            if 0<=t<=1 and 0<=s<=1 and math.dist([a[k]+t*u[k] for k in range(3)],[c[k]+s*v[k] for k in range(3)])<=tolerance:
                issue('Warning','unconnected_crossing',[m['id'],other['id']],'Members intersect without a shared node; connect only if a physical joint is intended')
    remaining=set(ns); components=0
    while remaining:
        group=set(); stack=[min(remaining)]
        while stack:
            nid=stack.pop()
            if nid in group: continue
            group.add(nid); stack.extend(adj[nid]-group)
        remaining-=group; components+=1
        if len(group)==1 and not adj[next(iter(group))]:
            issue('Error','orphan_node',['node:'+next(iter(group))],'Node has no connected member'); continue
        center=[sum(points[n][k] for n in group)/len(group) for k in range(3)]
        scale=max((math.dist(points[n],center) for n in group),default=1) or 1
        truss=all(m['type']=='Truss' for m,_,_,_ in segments if m['i'] in group)
        all_rows=[]; supported=[]
        for nid in sorted(group):
            x,y,z=[(points[nid][k]-center[k])/scale for k in range(3)]; n=ns[nid]
            rows=({'UX':[1,0,0,0,z,-y],'UY':[0,1,0,-z,0,x],'UZ':[0,0,1,y,-x,0],'RX':[0,0,0,1,0,0],'RY':[0,0,0,0,1,0],'RZ':[0,0,0,0,0,1]} if is3d else {'UX':[1,0,z],'UZ':[0,1,-x],'RY':[0,0,1]})
            flags=restraints(n) if is3d else {'Free':[],'Fixed':['UX','UZ','RY'],'Pin':['UX','UZ'],'Roller':['UZ'],'RollerX':['UX']}.get(n.get('support','Free'),[])
            flags=set(flags)|{dof for dof,value in n.get('springs',{}).items() if isinstance(value,(int,float)) and value>0}
            for dof,row in rows.items():
                if truss and dof.startswith('R'): continue
                all_rows.append(row)
                if dof in flags: supported.append(row)
        missing=rank(all_rows)-rank(supported)
        if missing: issue('Error','rigid_body_modes',['node:'+n for n in sorted(group)],f'{missing} observable rigid-body mode(s) not restrained; internal mechanisms require solver stiffness check')
    return dict(tolerance_m=tolerance,node_count=len(nodes),member_count=len(members),components=components,issues=issues,errors=sum(i['severity']=='Error' for i in issues),warnings=sum(i['severity']=='Warning' for i in issues),internal_stiffness='Not Checked',capacity='Not Available')
