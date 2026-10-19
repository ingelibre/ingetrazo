"""True mesh sections and dimensioned local views of concrete members (metres)."""
import math
from . import stair_drawing_geometry as G
KINDS=('Footing','Column','Beam','Slab')

def extents(faces):
    pts=[p for f in faces for p in f]
    if not pts:raise ValueError('Empty concrete mesh')
    lo=tuple(min(p[i] for p in pts) for i in range(3));hi=tuple(max(p[i] for p in pts) for i in range(3))
    if any(b-a<G.EPS for a,b in zip(lo,hi)):raise ValueError('Concrete mesh has zero extent')
    return lo,hi

def concrete_views(kind,faces,triangles,base_z=0):
    if kind not in KINDS:raise ValueError('Choose Footing / Column / Beam / Slab')
    lo,hi=extents(faces);mid=tuple((a+b)/2 for a,b in zip(lo,hi));outline=G.edges(faces)
    frames=[('PLAN',kind+' plan',G.frame((0,0,mid[2]),(1,0,0),(0,1,0))),
            ('SEC-A','Section A-A / local X',G.frame((0,mid[1],0),(1,0,0),(0,0,1))),
            ('SEC-B','Section B-B / local Y',G.frame((mid[0],0,0),(0,1,0),(0,0,1)))]
    views=[]
    for code,title,f in frames:
        cuts=G.slice_triangles(triangles,f)
        if not cuts:raise ValueError('Concrete section misses source mesh')
        lines=[dict(a=a,b=b,weight=.4) for a,b in cuts]
        if code!='PLAN':lines += [dict(a=G.project(f,a),b=G.project(f,b),weight=.1,color='#aaaaaa') for a,b in outline if math.dist(G.project(f,a),G.project(f,b))>G.EPS]
        # Overall extents are mesh measurements. Polygon slab dimensions are explicitly bounding extents.
        pts=[p for l in lines for p in (l['a'],l['b'])];a=tuple(min(p[i] for p in pts) for i in range(2));b=tuple(max(p[i] for p in pts) for i in range(2))
        dims=[dict(a=a,b=(b[0],a[1]),offset=14,text=''),dict(a=a,b=(a[0],b[1]),offset=-14,text='')]
        levels=[] if code=='PLAN' else [dict(point=(b[0],z),z=base_z+z,name=name) for name,z in (('BOTTOM',lo[2]),('TOP',hi[2]))]
        v=dict(key=code,title=title,frame=f,lines=lines,dims=dims,texts=[],levels=levels,cut=True,layout=kind,
               summary=f'{kind} mesh extents {1000*(hi[0]-lo[0]):g} x {1000*(hi[1]-lo[1]):g} x {1000*(hi[2]-lo[2]):g} mm',
               note='Actual concrete section; heavy = cut, grey = projected context; overall dimensions are local mesh extents.')
        views.append(v)
    plan=views[0]
    for index,axis in enumerate((0,1),2):
        other=1-axis;a=[lo[0]-.2,lo[1]-.2];b=[hi[0]+.2,hi[1]+.2];a[other]=b[other]=mid[other]
        plan['lines'].append(dict(a=tuple(a),b=tuple(b),weight=.25,dash=True))
        for pt in (a,b):plan['texts'].append(dict(point=tuple(pt),text=f'SEC-{chr(63+index)} / S{index:03}',size=6))
    return views

def add_representatives(views,rows,paper,bars=()):
    reps={}
    bymark={row['mark']:row for row in rows}
    for bar in bars:
        row=bymark[bar['bbs']['mark']];reps.setdefault(bar['role'],dict(row,path=bar['path']))
    if not bars:
        for row in rows:
            for role in row['roles']:reps.setdefault(role,row)
    limit=max(1,int((G.PAPERS[paper][1]-150)/10))
    for v in views:
        v['labels']=[]
        projected_lines={}
        # Draw the complete actual cage, deduplicating coincident orthographic projections.
        for bar in bars or [dict(path=r['path'],bbs=r['bbs']) for r in rows]:
            pts=[G.project(v['frame'],p) for p in bar['path']]
            projected=[dict(a=a,b=b,weight=.25,color='#8c301b') for a,b in zip(pts,pts[1:]) if math.dist(a,b)>G.EPS]
            if not projected:
                x,y=pts[0];r=bar['bbs']['diameter_mm']/2000
                ring=[(x+r*math.cos(j*math.pi/6),y+r*math.sin(j*math.pi/6)) for j in range(13)]
                projected=[dict(a=a,b=b,weight=.25,color='#8c301b') for a,b in zip(ring,ring[1:])]
            for line in projected:
                key=tuple(sorted(tuple(round(x,7) for x in line[k]) for k in ('a','b')));projected_lines.setdefault(key,line)
        v['lines']+=list(projected_lines.values())
        v['note']+=' Red = complete actual cage projection (coincident paths overlaid).'
        for role,row in list(reps.items())[:limit]:
            pts=[G.project(v['frame'],p) for p in row['path']]
            v['labels'].append(dict(point=pts[len(pts)//2],text=row['mark']+'\n'+role+' / MARK QTY '+str(len(row['uids']))+' / D'+str(row['bbs']['diameter_mm'])))
        if len(reps)>limit:v['note']+=' Sidebar roles limited; all marks in details/BBS.'
    return views
