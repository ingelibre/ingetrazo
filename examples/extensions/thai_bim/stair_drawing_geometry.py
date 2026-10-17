"""Pure local stair drawing geometry in metres and exact-scale paper layouts."""
import math,copy
from . import engine as E,stairs as S
PAPERS={'A3':(420,297),'A2':(594,420),'A1':(841,594),'A0':(1189,841)}
SCALES=(20,25,50)
EPS=1e-7

def frame(origin,u,v):return dict(origin=list(origin),u=list(E.unit(u)),v=list(E.unit(v)))
def project(f,p):return (E.dot(E.sub(p,f['origin']),f['u']),E.dot(E.sub(p,f['origin']),f['v']))
def reflect(p,hand):return (p[0],-p[1] if hand=='Right' else p[1],p[2])
def edges(faces):
    out={}
    for face in faces:
        normal=None
        for i in range(1,len(face)-1):
            n=E.cross(E.sub(face[i],face[0]),E.sub(face[i+1],face[0]))
            if E.norm(n)>EPS:normal=E.unit(n);break
        if normal is None:continue
        for a,b in zip(face,face[1:]+face[:1]):
            key=tuple(sorted(tuple(round(x,7) for x in p) for p in (a,b)))
            if math.dist(a,b)>EPS:out.setdefault(key,[]).append((a,b,normal))
    # Coplanar triangulation edges are not visible construction outlines.
    return [(pairs[0][0],pairs[0][1]) for pairs in out.values() if len(pairs)==1 or not all(abs(E.dot(pairs[0][2],v[2]))>.999999 for v in pairs[1:])]
def slice_triangles(triangles,f):
    n=E.cross(f['u'],f['v']);out={}
    for t in triangles:
        ds=[E.dot(E.sub(p,f['origin']),n) for p in t];points=[]
        if all(abs(d)<EPS for d in ds):continue # coplanar cap is outlined by adjoining triangles
        for i in range(3):
            a,b=t[i],t[(i+1)%3];da,db=ds[i],ds[(i+1)%3]
            if abs(da)<EPS:points.append(a)
            if da*db<-EPS*EPS:points.append(E.add(a,E.mul(E.sub(b,a),da/(da-db))))
        unique={tuple(round(x,7) for x in p):p for p in points};points=list(unique.values())
        if len(points)>=2:
            a,b=max(((a,b) for i,a in enumerate(points) for b in points[i+1:]),key=lambda ab:math.dist(*ab))
            if math.dist(a,b)>EPS:
                pair=[project(f,a),project(f,b)];key=tuple(sorted(tuple(round(x,7) for x in p) for p in pair));out[key]=pair
    return list(out.values())
def section_frames(values,angle=90):
    p=S.validated(values);hand=p['hand'];out=[]
    if p['layout'] in ('Spiral','Circular'):
        a=math.radians(E.finite(angle));u=reflect((math.cos(a),math.sin(a),0),hand)
        out.append(('SEC-R','Radial section '+str(angle)+' deg',frame((0,0,0),u,(0,0,1))))
    elif p['layout']=='Floating':out.append(('SEC-A','Section A-A',frame(reflect((0,p['width']/2,0),hand),(1,0,0),(0,0,1))))
    else:
        for i,part in enumerate(q for q in S.parts(dict(p,hand='Left')) if q['kind']=='Flight'):
            o=part['origin'];d=part['direction'];o=(o[0]-d[1]*p['width']/2,o[1]+d[0]*p['width']/2,o[2]);u=reflect((*d,0),hand)
            out.append(('SEC-'+chr(65+i),'Section '+chr(65+i)+'-'+chr(65+i),frame(reflect(o,hand),u,(0,0,1))))
    return out

def concrete_views(values,faces,triangles,angle=90,base_z=0):
    p=S.validated(values);hand=p['hand'];outline=edges(faces)
    plan=dict(key='PLAN',title='Stair plan / all levels',frame=frame((0,0,0),(1,0,0),(0,1,0)),lines=[],dims=[],texts=[],levels=[],cut=False)
    top_faces=[f for f in faces if all(abs(p[2]-f[0][2])<EPS for p in f) and any(E.cross(E.sub(f[i],f[0]),E.sub(f[i+1],f[0]))[2]>EPS for i in range(1,len(f)-1))]
    plan['lines']=[dict(a=project(plan['frame'],a),b=project(plan['frame'],b),weight=.18) for a,b in edges(top_faces) if math.dist(project(plan['frame'],a),project(plan['frame'],b))>EPS]
    views=[plan]
    for code,title,f in section_frames(p,angle):
        cuts=slice_triangles(triangles,f)
        if not cuts:raise ValueError('Section plane does not intersect concrete; change radial section angle')
        v=dict(key=code,title=title,frame=f,lines=[dict(a=a,b=b,weight=.4) for a,b in cuts],dims=[],texts=[],levels=[],cut=True)
        # Draw projected outlines lightly for stair context; cut remains explicit heavy lines.
        v['lines'] += [dict(a=project(f,a),b=project(f,b),weight=.1,color='#aaaaaa') for a,b in outline if math.dist(project(f,a),project(f,b))>EPS]
        # Actual absolute datums; dimension height is geometry vertical extent between floor datums.
        allpts=[pt for line in v['lines'] for pt in (line['a'],line['b'])];right=max(pt[0] for pt in allpts)
        for name,z in [('LOWER',0),('UPPER',p['height'])]+([('LANDING',p['first_risers']*p['height']/p['risers'])] if p['layout'] in ('L','U') else []):
            localz=z-f['origin'][2];v['levels'].append(dict(point=(right,localz),z=base_z+z,name=name))
        v['dims'].append(dict(a=(right, -f['origin'][2]),b=(right,p['height']-f['origin'][2]),offset=-18,text=''))
        views.append(v)
    # Parametric dimensions and step numbering refer to verified schema-2 geometry.
    flights=[q for q in S.parts(dict(p,hand='Left')) if q['kind']=='Flight']
    if p['layout']=='Floating':flights=[dict(origin=(0,0,0),direction=(1,0),risers=p['risers'],run=p['risers']*p['going'],role='Floating')]
    r=p['height']/p['risers'];step=0
    for index,part in enumerate(flights):
        o=part['origin'];dx,dy=part['direction'];n=part['risers'];u=(dx,dy,0);v=(-dy,dx,0)
        def pt(x,y,z=0):return reflect(E.add(o,E.add(E.mul(u,x),E.add(E.mul(v,y),(0,0,z)))),hand)
        for a,b,offset,label in [(pt(0,0),pt(0,p['width']),14,''),(pt(0,0),pt(part['run'],0),-14,f"{n} x {p['going']*1000:g} = {part['run']*1000:g} mm")]:
            plan['dims'].append(dict(a=project(plan['frame'],a),b=project(plan['frame'],b),offset=offset,text=label))
        for j in range(n):
            step+=1;pos=project(plan['frame'],pt((j+.5)*p['going'],p['width']*.25));plan['texts'].append(dict(point=pos,text=str(step),size=6))
        a,b=project(plan['frame'],pt(p['going']*.5,p['width']/2)),project(plan['frame'],pt(max(p['going'],part['run']-.5*p['going']),p['width']/2))
        plan['lines'].append(dict(a=a,b=b,weight=.3,arrow=True));plan['texts'].append(dict(point=a,text='UP',size=7))
        if index+1<len(views):
            sec=views[index+1];f=sec['frame'];a,b=project(f,pt(0,0)),project(f,pt(part['run'],0));sec['dims'].append(dict(a=a,b=b,offset=15,text=f"{n} x {p['going']*1000:g} mm"))
            # Individual going and riser at first step; no eye-estimated dimension.
            for a,b in [(pt(0,0,r),pt(p['going'],0,r)),(pt(0,0,0),pt(0,0,r))]:sec['dims'].append(dict(a=project(f,a),b=project(f,b),offset=-8,text=''))
    if not flights:
        rin=p['inner_radius'];rout=rin+p['width'];a=math.radians(p['sweep']);mid=(rin+rout)/2
        plan['dims'].append(dict(a=reflect((rin,0,0),hand)[:2],b=reflect((rout,0,0),hand)[:2],offset=14,text=''))
        for j in range(p['risers']):
            t=(j+.5)*a/p['risers'];pos=reflect(((rin+p['width']*.25)*math.cos(t),(rin+p['width']*.25)*math.sin(t),0),hand)[:2];plan['texts'].append(dict(point=pos,text=str(j+1),size=6))
        # Curved going is a walking-line arc, not a horizontal chord.
        plan['note']=f"WALKING radius {mid*1000:.1f} mm; arc going {mid*a/p['risers']*1000:.1f} mm; sweep {p['sweep']:g} deg"
    # Dimension each landing using actual generated local outline extents.
    for part in S.parts(p):
        if part['kind']!='Landing':continue
        pts=[pt for f in part['faces'] for pt in f];z=max(pt[2] for pt in pts)
        # Measure two adjacent edges from top face rather than bounding boxes of rotated landings.
        top=next((f for f in part['faces'] if all(abs(pt[2]-z)<EPS for pt in f)),None)
        if top:
            for i in (0,1):
                if abs(math.dist(top[i],top[i+1])-p['width'])>EPS:plan['dims'].append(dict(a=top[i][:2],b=top[i+1][:2],offset=8,text=''))
    if not flights:
        arc=[reflect((mid*math.cos(t),mid*math.sin(t),0),hand)[:2] for t in [a*j/60 for j in range(61)]]
        for i,(s,e) in enumerate(zip(arc,arc[1:])):plan['lines'].append(dict(a=s,b=e,weight=.3,arrow=i==59))
        plan['texts'].append(dict(point=arc[0],text='UP',size=7))
    # Section traces on the plan are tied to the exact local cutting planes.
    allpts=[pt for face in faces for pt in face]
    for index,(code,title,f) in enumerate(section_frames(p,angle),2):
        xs=[project(f,pt)[0] for pt in allpts];ends=[E.add(f['origin'],E.mul(f['u'],x)) for x in (min(xs)-.25,max(xs)+.25)]
        a,b=[project(plan['frame'],pt) for pt in ends];plan['lines'].append(dict(a=a,b=b,weight=.25,dash=True))
        for point in (a,b):plan['texts'].append(dict(point=point,text=code+' / S'+str(index).zfill(3),size=6))
    return views

def same_descriptor(a,b):
    def value(v):
        if isinstance(v,float):return round(v,9)
        if isinstance(v,dict):return {k:value(x) for k,x in v.items()}
        if isinstance(v,(list,tuple)):return [value(x) for x in v]
        return v
    return value(a)==value(b)
def grouped_bars(bars):
    out={}
    for b in bars:
        mark=b['bbs']['mark'];row=out.setdefault(mark,dict(mark=mark,bbs=copy.deepcopy(b['bbs']),path=copy.deepcopy(b['path']),uids=[],roles=[]))
        # Same mark must not silently hide a different fabrication descriptor.
        if not same_descriptor(row['bbs'],b['bbs']):raise ValueError('Conflicting BBS descriptors share one Bar Mark')
        row['uids'].append(b['uid']);role=b.get('role',b['bbs'].get('stair_role',b['bbs'].get('slab_role','')))
        if role not in row['roles']:row['roles'].append(role)
    if len(out)>120:raise ValueError('More than 120 Bar Marks; split stair detailing scope')
    return sorted(out.values(),key=lambda r:r['mark'])

def detail_views(rows):
    out=[]
    for row in rows:
        path=row['path'];curved=row['bbs'].get('shape')=='3D helix' or 'helix' in row['bbs'].get('shape','').lower()
        # Planar shapes use an orthonormal plane so straight lengths are not foreshortened.
        u=E.unit(E.sub(path[-1],path[0])) if math.dist(path[-1],path[0])>EPS else E.unit(E.sub(path[1],path[0]));n=None
        for p in path[1:]:
            cross=E.cross(u,E.sub(p,path[0]))
            if E.norm(cross)>EPS:n=E.unit(cross);break
        n=n or E.unit(E.cross(u,(0,0,1) if abs(u[2])<.9 else (0,1,0)));v=E.unit(E.cross(n,u))
        planar=all(abs(E.dot(E.sub(p,path[0]),n))<1e-5 for p in path)
        fs=[('Shape plane',frame(path[0],u,v))] if planar else [('Plan projection',frame((0,0,0),(1,0,0),(0,1,0))),('Elevation projection',frame((0,0,0),(1,0,0),(0,0,1)))]
        for suffix,f in fs:
            pts=[project(f,p) for p in path]
            out.append(dict(key='BAR-'+row['mark']+'-'+suffix,title=row['mark']+' / '+suffix,frame=f,lines=[dict(a=a,b=b,weight=.4,color='#8c301b') for a,b in zip(pts,pts[1:]) if math.dist(a,b)>EPS],dims=[],texts=[],levels=[],bar=row,cut=False,spatial=not planar))
    return out

def options(paper='A3',scale=50,angle=90,datum=0,name='Thai BIM Stair',revision='01',author='',date=''):
    if paper not in PAPERS or scale not in SCALES:raise ValueError('Choose A3/A2/A1/A0 and 1:20, 1:25 or 1:50')
    vals={k:str(v).strip() for k,v in dict(name=name,revision=revision,author=author,date=date).items()}
    if not vals['name'] or any(len(v)>80 for v in vals.values()):raise ValueError('Drawing fields require project name and <=80 characters')
    return dict(paper=paper,scale=scale,angle=E.finite(angle),datum=E.finite(datum),**vals)
def paper_view(view,opts):
    pw,ph=PAPERS[opts['paper']];k=1000/opts['scale'];box=(38,45,pw-155,ph-125)
    pts=[pt for l in view['lines'] for pt in (l['a'],l['b'])]+[d[p] for d in view['dims'] for p in ('a','b')]
    if not pts:raise ValueError('Empty drawing geometry')
    lo=[min(p[i] for p in pts) for i in range(2)];hi=[max(p[i] for p in pts) for i in range(2)]
    if (hi[0]-lo[0])*k>box[2]-55 or (hi[1]-lo[1])*k>box[3]-45:raise ValueError(view['title']+' clips at 1:'+str(opts['scale'])+' on '+opts['paper']+'; choose larger paper or smaller drawing scale')
    centre=[(a+b)/2 for a,b in zip(lo,hi)]
    def pp(p):return (box[0]+box[2]/2+(p[0]-centre[0])*k,box[1]+box[3]/2-(p[1]-centre[1])*k)
    out=copy.deepcopy(view);out.update(paper_size=(pw,ph),scale=opts['scale'],box=box)
    out['lines']=[dict(l,a=pp(l['a']),b=pp(l['b'])) for l in view['lines']]
    out['dims']=[dict(d,a=pp(d['a']),b=pp(d['b'])) for d in view['dims']]
    out['texts']=[dict(t,point=pp(t['point'])) for t in view['texts']]
    out['levels']=[dict(l,point=pp(l['point'])) for l in view['levels']]
    return out,pp
