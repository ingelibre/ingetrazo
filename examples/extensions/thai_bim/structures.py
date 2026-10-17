"""User-dimensioned assemblies; geometry detailing, no strength design."""
import math
from . import engine as E


def roof_planes(kind, x=0,y=0,z=3,width=6,depth=4,pitch=30,overhang=.4):
    x,y,z=map(E.finite,(x,y,z));w,d=map(E.finite,(width,depth));p=E.finite(pitch);e=E.finite(overhang)
    if not 1<=w<=40 or not 1<=d<=40 or not 5<=p<=60 or not 0<=e<=2:
        raise ValueError('กว้าง/ลึก 1–40 m; มุม 5–60°; ชายคา 0–2 m')
    a=x-e;b=x+w+e;c=y-e;f=y+d+e;t=math.tan(math.radians(p));low=z-e*t
    if kind=='Shed':
        rings=[[(a,c,low),(b,c,z+(w+e)*t),(b,f,z+(w+e)*t),(a,f,low)]]
    elif kind=='Gable':
        q=x+w/2;high=z+w/2*t
        rings=[[(a,c,low),(q,c,high),(q,f,high),(a,f,low)],
               [(q,c,high),(b,c,low),(b,f,low),(q,f,high)]]
    elif kind=='Hip':
        # Equal pitch hip; ridge follows the longer plan dimension.
        A=(a,c,low);B=(b,c,low);C=(b,f,low);D=(a,f,low)
        if w>=d:
            P=(x+d/2,y+d/2,z+d/2*t);Q=(x+w-d/2,y+d/2,z+d/2*t)
        else:
            P=(x+w/2,y+w/2,z+w/2*t);Q=(x+w/2,y+d-w/2,z+w/2*t)
        rings=([ [A,B,Q,P],[B,C,Q],[C,D,P,Q],[D,A,P] ] if w>=d else
               [ [A,B,P],[B,C,Q,P],[C,D,Q],[D,A,P,Q] ])
        rings=[[point for i,point in enumerate(ring) if i==0 or E.norm(E.sub(point,ring[i-1]))>1e-8] for ring in rings]
        rings=[ring[:-1] if E.norm(E.sub(ring[0],ring[-1]))<1e-8 else ring for ring in rings]
    else:raise ValueError('ชนิดหลังคาไม่รองรับ')
    return [dict(id='plane-'+str(i),vertices=ring) for i,ring in enumerate(rings)]


def roof_assembly(kind, **params):
    params=dict(params);cover=params.pop('cover',.06)
    rs=params.pop('rafter_spacing',1);bs=params.pop('batten_spacing',.3)
    if not .005<=E.finite(cover)<=.2:raise ValueError('ความหนาหลังคา 5–200 mm')
    planes=roof_planes(kind,**params);specs=[]
    edges={}
    for plane in planes:
        pts=plane['vertices'];_,_,_,n=E.plane_geometry(pts)
        specs.append(dict(slot='cover-'+plane['id'],kind='Roof cover',ifc='IfcRoof',
            faces=E.extrusion(pts,E.mul(n,-cover)),color=(.36,.22,.14),discipline='Architecture',
            item=kind+' roof gross area',unit='m2',quantity=E.area(pts)/n[2],note='Gross slope area; no tile overlaps/accessories'))
        for a,b in zip(pts,pts[1:]+pts[:1]):
            key=tuple(sorted((tuple(round(v,8) for v in a),tuple(round(v,8) for v in b))))
            edges.setdefault(key,[]).append((a,b,n))
    specs+=E.plane_roof_specs(planes,rafter_spacing=rs,batten_spacing=bs,
        rafter_offset=cover+.0895,batten_offset=cover+.027)
    for edge_index,(key,shared) in enumerate(edges.items()):
        if len(shared)!=2:continue
        a,b,n=shared[0];normal=E.unit(E.add(n,shared[1][2]))
        offset=E.mul(normal,-cover-.0895)
        role='Ridge' if abs(a[2]-b[2])<1e-7 else 'Hip'
        sp=E.section_spec('support-'+str(edge_index),E.add(a,offset),E.add(b,offset),normal,E.c_profile(),'C125x50x20x3.2 '+role)
        sp['kind']=role;sp['note']='User section; connection/strength design excluded';specs.append(sp)
    return planes,specs


def stair_spec(x=0,y=0,z=0,width=1,height=3,going=.28,risers=18,waist=.15):
    x,y,z,w,h,g,t=map(E.finite,(x,y,z,width,height,going,waist))
    n=E.finite(risers)
    if int(n)!=n or not 2<=n<=60:raise ValueError('ลูกตั้งต้องเป็นจำนวนเต็ม 2–60 ขั้น')
    if not .5<=w<=5 or not .2<=h<=8 or not .15<=g<=.6 or not .06<=t<=.5:
        raise ValueError('ขนาดบันไดอยู่นอกช่วงที่รองรับ')
    n=int(n);r=h/n;L=(n-1)*g;slope=r/g;vertical=t*math.sqrt(1+slope*slope)
    top=[(0,r)]
    for i in range(1,n):top.extend([(i*g,i*r),(i*g,(i+1)*r)])
    profile=top+[(L,h-r-vertical),(0,-vertical)]
    ring=[(x+u,y,z+v) for u,v in profile]
    volume=L*vertical*w + (n-1)*g*r*w/2
    p=dict(x=x,y=y,z=z,width=w,height=h,going=g,risers=n,waist=t)
    return dict(slot='stair-host',kind='Stair',ifc='IfcStairFlight',faces=E.extrusion(ring,(0,w,0)),
        color=(.58,.61,.63),discipline='Structure',item='RC straight stair',unit='m3',quantity=volume,
        stair_params=p,note='Straight RC flight; upper floor is last riser; waist normal to slope; supports/landings excluded')


def bar_spec(slot, points, diameter, closed=False, note='', representation='Full'):
    """Miter sweep of a centreline. Closed polygon ties have no hooks/lap."""
    pts=[tuple(map(E.finite,p)) for p in points];dia=E.finite(diameter)
    if not .004<=dia<=.06 or len(pts)<2:raise ValueError('เหล็กเส้น 4–60 mm และแนวอย่างน้อย 2 จุด')
    if closed and len(pts)<3:raise ValueError('ปลอกต้องอย่างน้อย 3 จุด')
    pairs=list(zip(pts,pts[1:]+pts[:1])) if closed else list(zip(pts,pts[1:]))
    lengths=[E.norm(E.sub(b,a)) for a,b in pairs]
    if min(lengths)<dia*2:raise ValueError('แนวเหล็กสั้นเกินสำหรับหน้าตัด')
    directions=[E.unit(E.sub(b,a)) for a,b in pairs]
    # All supported bent paths are planar rectangular ties.
    plane_normal=E.unit(E.cross(directions[0],directions[1])) if closed else E.unit(E.cross(directions[0],(0,0,1) if abs(directions[0][2])<.9 else (0,1,0)))
    if representation not in ('Full','Lightweight','Centreline'):raise ValueError('Unknown bar representation')
    rings=[];radius=dia/2;segments=6 if representation=='Lightweight' else 12
    for i,p in enumerate(pts if representation!='Centreline' else []):
        incoming=directions[i-1] if i or closed else directions[0]
        outgoing=directions[i] if i<len(directions) else directions[-1]
        tangent=E.unit(E.add(incoming,outgoing));side=E.unit(E.cross(plane_normal,tangent))
        # A miter section projects to the same round section on both segments.
        factor=1/max(.1,E.dot(tangent,outgoing))
        rings.append([E.add(p,E.add(E.mul(side,radius*factor*math.cos(j*2*math.pi/segments)),E.mul(plane_normal,radius*math.sin(j*2*math.pi/segments)))) for j in range(segments)])
    faces=[]
    for i in range(len(rings) if closed else len(rings)-1):
        a,b=rings[i],rings[(i+1)%len(rings)]
        faces.extend([[a[j],a[(j+1)%segments],b[(j+1)%segments],b[j]] for j in range(segments)])
    if not closed and rings:faces=[list(reversed(rings[0]))]+faces+[rings[-1]]
    length=sum(lengths)
    return dict(slot=slot,kind='Rebar',ifc='IfcReinforcingBar',faces=faces,color=(.68,.26,.16),
        discipline='Structure',item=f'Rebar D{dia*1000:g}'+(' geometric tie' if closed else ''),unit='m',quantity=length,
        bar_path=pts,bar_diameter=dia,bar_closed=closed,representation=representation,axis=[pts[0],pts[-1]] if not closed else None,
        note=note or 'Net model centreline; no hooks/laps/anchorage, no strength design')


def reinforcement(kind, host, cover=.04, diameter=.012, tie_diameter=.006, spacing=.15, count_x=3,count_y=3, layers=1, representation='Full'):
    """RC cages from dimensions in the host's original local coordinates."""
    c,db,dt,spacing=map(E.finite,(cover,diameter,tie_diameter,spacing))
    nx,ny,layer=map(E.finite,(count_x,count_y,layers))
    if not .015<=c<=.15 or not .004<=db<=.06 or not .004<=dt<=.06 or not .04<=spacing<=1:
        raise ValueError('cover/ขนาดเหล็ก/ระยะ อยู่นอกช่วงรองรับ')
    if int(nx)!=nx or int(ny)!=ny or not 2<=nx<=30 or not 2<=ny<=30 or layer not in (1,2):
        raise ValueError('จำนวนเหล็กตามด้านเป็นจำนวนเต็ม 2–30; ชั้นตะแกรง 1 หรือ 2')
    nx,ny,layer=int(nx),int(ny),int(layer);specs=[]
    x,y,z=[E.finite(host[k]) for k in ('x','y','z')]
    w=E.finite(host['width']);h=E.finite(host['height']);d=E.finite(host.get('depth',0))
    def bars(a,b):specs.append(bar_spec('bar-'+str(len(specs)),[a,b],db,representation=representation))
    def between(lo,hi,n):return [lo+(hi-lo)*i/(n-1) for i in range(n)]
    def spaced(lo,hi,diameter=db):
        values=between(lo,hi,max(2,math.ceil((hi-lo)/spacing)+1))
        if values[1]-values[0]<diameter-1e-8:raise ValueError('ระยะที่จัดจริงทำให้เหล็กซ้อนกัน: เพิ่มระยะ/ปรับหน้าตัด')
        return values
    if kind in ('Footing','Slab'):
        q=c+db/2
        if min(w,d)<=2*q+db or h<2*c+(4 if layer==2 else 2)*db:
            raise ValueError('หน้าตัด/ความหนาไม่พอ cover และชั้นเหล็กไขว้')
        for top in range(layer):
            zz=z+(h-q if top else q);sign=-1 if top else 1
            for yy in spaced(y+q,y+d-q):bars((x+q,yy,zz),(x+w-q,yy,zz))
            for xx in spaced(x+q,x+w-q):bars((xx,y+q,zz+sign*db),(xx,y+d-q,zz+sign*db))
    elif kind in ('Column','Beam'):
        # Beam runs along local X. Column runs along local Z.
        sizes=(w,d,h) if kind=='Column' else (d,h,w)
        if min(sizes[:2])<=2*(c+dt+db)+.01 or sizes[2]<=2*(c+db):
            raise ValueError('หน้าตัดเล็กเกิน cage/cover หรือแนวหลักสั้นเกิน')
        outer=c+dt/2;inner=c+dt+db/2
        us=between(inner,sizes[0]-inner,nx);vs=between(inner,sizes[1]-inner,ny)
        if min(us[1]-us[0],vs[1]-vs[0])<db-1e-8:raise ValueError('จำนวนเหล็กหลักมากเกินหน้าตัด: เส้นทับกัน')
        def point(u,v,l):return (x+u,y+v,z+l) if kind=='Column' else (x+l,y+u,z+v)
        positions={(u,v) for u in us for v in (vs[0],vs[-1])}|{(u,v) for u in (us[0],us[-1]) for v in vs}
        for u,v in sorted(positions):bars(point(u,v,c+db/2),point(u,v,sizes[2]-c-db/2))
        for l in spaced(c+dt/2,sizes[2]-c-dt/2,dt):
            path=[point(u,v,l) for u,v in [(outer,outer),(sizes[0]-outer,outer),(sizes[0]-outer,sizes[1]-outer),(outer,sizes[1]-outer)]]
            specs.append(bar_spec('tie-'+str(len(specs)),path,dt,True,
                'Geometric closed tie with miter bends; hooks, bend radii, laps excluded; not a fabrication shape',representation))
    elif kind=='Stair':
        n=int(host['risers']);going=E.finite(host['going']);waist=E.finite(host['waist']);r=h/n;L=(n-1)*going
        slope=r/going;cos=1/math.sqrt(1+slope*slope);q=c+db/2
        if w<=2*q+db or waist<2*c+2*db:raise ValueError('บันไดไม่พอ cover/เหล็กไขว้')
        if layer!=1:raise ValueError('บันไดรุ่นนี้รองรับตะแกรงล่างหนึ่งชั้น')
        def zz(u):return z-waist/cos+q/cos+u*slope
        for yy in spaced(y+q,y+w-q):bars((x+q,yy,zz(q)),(x+L-q,yy,zz(L-q)))
        for u in between(q,L-q,max(2,math.ceil((L-2*q)/cos/spacing)+1)):
            bars((x+u,y+q,zz(u)+db/cos),(x+u,y+w-q,zz(u)+db/cos))
    else:raise ValueError('Host ไม่รองรับ')
    if len(specs)>1500:raise ValueError('เกิน 1,500 เส้นต่อชุด; แบ่งงานก่อนสร้าง')
    return specs
