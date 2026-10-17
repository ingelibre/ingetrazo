"""Explicit user detailing. Analytic centreline lengths; no design-code sizing."""
import hashlib,json,math
from . import engine as E
from . import structures as S


def bent_bar(slot,points,diameter,inside_radius=.012,shape='Straight',density=7850,representation='Full',wire=False):
    pts=[tuple(map(E.finite,p)) for p in points];db=E.finite(diameter)
    inside=E.finite(inside_radius);rho=E.finite(density);radius=inside+db/2
    if not (.002 if wire else .004)<=db<=(.012 if wire else .06) or not db/2<=inside<=.25 or not 1000<=rho<=20000:
        raise ValueError('Diameter 4–60 mm; inside radius >= diameter/2; density 1000–20000 kg/m3')
    if representation not in ('Full','Lightweight','Centreline'):raise ValueError('Unknown bar representation')
    pairs=list(zip(pts,pts[1:]));lengths=[E.norm(E.sub(b,a)) for a,b in pairs]
    if not lengths or min(lengths)<=1e-8:raise ValueError('Zero-length bar segment')
    dirs=[E.unit(E.sub(b,a)) for a,b in pairs];corners={};normal=None
    for i in range(1,len(pts)-1):
        dot=max(-1,min(1,E.dot(dirs[i-1],dirs[i])));angle=math.acos(dot)
        if angle<1e-8:continue
        if angle>math.pi-1e-6:raise ValueError('180-degree reversal: specify a U bend with two corners')
        n=E.unit(E.cross(dirs[i-1],dirs[i]))
        if normal is None:normal=n
        if abs(E.dot(normal,n))<.999999:raise ValueError('Bar shape must be planar')
        setback=radius*math.tan(angle/2)
        entry=E.sub(pts[i],E.mul(dirs[i-1],setback));exit=E.add(pts[i],E.mul(dirs[i],setback))
        centre=E.add(entry,E.mul(E.cross(n,dirs[i-1]),radius))
        corners[i]=(entry,exit,centre,n,angle,setback)
    straight=[l-corners.get(i,(0,)*6)[5]-corners.get(i+1,(0,)*6)[5] for i,l in enumerate(lengths)]
    if min(straight)<db-1e-8:raise ValueError('Bend radius / hook length does not fit: retain at least one diameter between bends')
    normal=normal or E.unit(E.cross(dirs[0],(0,0,1) if abs(dirs[0][2])<.9 else (0,1,0)))
    path=[pts[0]];tangents=[dirs[0]]
    for i in range(1,len(pts)-1):
        if i not in corners:path.append(pts[i]);tangents.append(dirs[i]);continue
        entry,exit,centre,n,angle,_=corners[i];path.append(entry);tangents.append(dirs[i-1])
        radial=E.sub(entry,centre);side=E.cross(n,radial)
        count=max(2,math.ceil(math.degrees(angle)/(30 if representation=='Lightweight' else 10)))
        for j in range(1,count+1):
            a=angle*j/count;v=E.add(E.mul(radial,math.cos(a)),E.mul(side,math.sin(a)))
            path.append(E.add(centre,v));tangents.append(E.unit(E.cross(n,v)))
    path.append(pts[-1]);tangents.append(dirs[-1])
    rings=[];sides=6 if representation=='Lightweight' else 12
    for point,tangent in zip(path,tangents) if representation!='Centreline' else []:
        side=E.unit(E.cross(normal,tangent))
        rings.append([E.add(point,E.add(E.mul(side,db/2*math.cos(j*2*math.pi/sides)),E.mul(normal,db/2*math.sin(j*2*math.pi/sides)))) for j in range(sides)])
    faces=[list(reversed(rings[0]))] if rings else []
    for a,b in zip(rings,rings[1:]):faces.extend([[a[j],a[(j+1)%sides],b[(j+1)%sides],b[j]] for j in range(sides)])
    if rings:faces.append(rings[-1])
    angles=[math.degrees(c[4]) for c in corners.values()]
    length=sum(straight)+sum(radius*c[4] for c in corners.values())
    descriptor=dict(shape=shape,diameter_mm=round(db*1000,6),inside_radius_mm=round(inside*1000,6),
        straight_mm=[round(v*1000,6) for v in straight],bend_degrees=[round(a,6) for a in angles],density=rho)
    mark='B-'+hashlib.sha256(json.dumps(descriptor,sort_keys=True).encode()).hexdigest()[:12].upper()
    bbs=dict(schema=1,mark=mark,**descriptor,length_m=length,unit_mass_kg_m=math.pi*db*db/4*rho,
        mass_kg=length*math.pi*db*db/4*rho,basis='Analytic tangent straights + centreline radius × bend angle')
    return dict(slot=slot,kind='Rebar',ifc='IfcReinforcingBar',faces=faces,color=(.68,.26,.16),discipline='Structure',
        item=f'Rebar D{db*1000:g} {shape}',unit='m',quantity=length,bar_path=path,bar_diameter=db,bar_closed=False,
        bbs=bbs,representation=representation,note='Explicit user detailing; nominal diameter mass; no design-code certification')


def reinforcement(kind,host,cover=.04,diameter=.012,tie_diameter=.006,spacing=.15,count_x=3,count_y=3,layers=1,
                  inside_radius=.024,tie_inside_radius=.012,hook_length=0,hook_ends=2,tie_hook_length=.04,
                  lap_length=0,extension_start=0,extension_end=0,density=7850,representation='Full',main_steel=None,tie_steel=None):
    from . import steel as C
    main_steel=C.validate(main_steel,diameter*1000) if main_steel else None
    tie_steel=C.validate(tie_steel,tie_diameter*1000) if tie_steel else None
    # Only paths are needed for detailed hosts; never build a cage twice.
    detailed=kind in ('Footing','Column','Beam','Slab','Stair')
    base=S.reinforcement(kind,host,cover,diameter,tie_diameter,spacing,count_x,count_y,layers,'Centreline' if detailed else representation)
    hook,lap,e0,e1,tail=map(E.finite,(hook_length,lap_length,extension_start,extension_end,tie_hook_length))
    if min(hook,lap,e0,e1)<0 or max(hook,lap,e0,e1)>3 or not .01<=tail<=.5 or hook_ends not in (1,2):
        raise ValueError('Hook / lap / extension 0–3000 mm; tie tail 10–500 mm; hook ends 1 or 2')
    if not detailed:
        if hook or lap or e0 or e1:raise ValueError('Detailed hooks / splices currently support Footing, Column and Beam')
        return [C.tag(s,main_steel) for s in base]
    if kind in ('Footing','Slab') and (lap or e0 or e1):raise ValueError('Footing / Slab: use end hooks; anchorage extensions are for Column, Beam and stair main bars')
    if kind=='Stair' and lap:raise ValueError('Stair lap is not supported; specify a continuous main bar')
    if kind=='Stair' and hook and (e0 or e1):raise ValueError('Stair: choose in-flight hooks or sloping anchorage extensions, not both')
    if kind in ('Column','Beam') and hook:raise ValueError('Column / Beam use straight anchorage extensions')
    out=[];main=[]
    for source in base:
        pts=source['bar_path'];db=source['bar_diameter'];slot=source['slot']
        if source['bar_closed']:
            # Two 135-degree tails, separated along the final side. No closed/welded loop.
            a,b,c,d=pts;u=E.unit(E.sub(b,a));v=E.unit(E.sub(d,a));r=tie_inside_radius+db/2
            setback=r*math.tan(math.radians(67.5));leg=setback+tail
            gap=max(4*r,3*db);start=E.add(a,E.mul(E.unit(E.add(u,v)),leg));last=E.add(a,E.mul(v,gap))
            end=E.add(last,E.mul(E.unit(E.add(u,v)),leg))
            sp=bent_bar(slot,[start,a,b,c,d,last,end],db,tie_inside_radius,'Tie-135',density,representation)
            C.tag(sp,tie_steel)
            out.append(sp)
        else:
            a,b=pts;direction=E.unit(E.sub(b,a));stair_main=kind=='Stair' and abs(direction[0])>1e-8
            if kind!='Stair' or stair_main:
                a=E.sub(a,E.mul(direction,e0));b=E.add(b,E.mul(direction,e1))
            if kind in ('Footing','Slab') and hook:
                centre_z=host['z']+host['height']/2;sign=1 if (a[2]+b[2])/2<centre_z else -1
                r=inside_radius+db/2;leg=hook+r;offset=(0,0,sign*leg)
                shape='U-90' if hook_ends==2 else 'L-90'
                path=[E.add(a,offset),a,b]+([E.add(b,offset)] if hook_ends==2 else [])
                main.append(bent_bar(slot,path,db,inside_radius,shape,density,representation))
            elif stair_main and hook:
                # Vertical end legs; unequal bend angles follow the actual flight slope.
                # Hook length is the straight tail AFTER each tangent point.
                angle=math.acos(max(-1,min(1,direction[2])))
                r=inside_radius+db/2
                leg0=hook+r*math.tan((math.pi-angle)/2)
                leg1=hook+r*math.tan(angle/2)
                path=[E.add(a,(0,0,leg0)),a,b]+([E.add(b,(0,0,leg1))] if hook_ends==2 else [])
                main.append(bent_bar(slot,path,db,inside_radius,'Stair-U' if hook_ends==2 else 'Stair-L',density,representation))
            elif lap:
                length=E.norm(E.sub(b,a))
                if lap>=length-4*db:raise ValueError('Lap is too long for the available longitudinal bar')
                mid=E.mul(E.add(a,b),.5);lo=E.sub(mid,E.mul(direction,lap/2));hi=E.add(mid,E.mul(direction,lap/2))
                transverse=0 if kind=='Column' else 1;offset=[0.,0.,0.]
                centre=host['x' if transverse==0 else 'y']+host['width' if transverse==0 else 'depth']/2
                offset[transverse]=1.5*db*(1 if a[transverse]<centre else -1)
                main.extend([bent_bar(slot+'-splice-a',[a,hi],db,inside_radius,'Straight-splice',density,representation),
                    bent_bar(slot+'-splice-b',[E.add(lo,offset),E.add(b,offset)],db,inside_radius,'Straight-splice',density,representation)])
            else:main.append(bent_bar(slot,[a,b],db,inside_radius,'Straight',density,representation))
    for sp in main:C.tag(sp,main_steel)
    out=main+out
    if lap:
        for i,a in enumerate(main):
            a0,a1=a['bar_path'][0],a['bar_path'][-1];direction=E.unit(E.sub(a1,a0));length=E.norm(E.sub(a1,a0))
            for b in main[i+1:]:
                b0,b1=b['bar_path'][0],b['bar_path'][-1]
                along0=E.dot(E.sub(b0,a0),direction);along1=E.dot(E.sub(b1,a0),direction)
                if min(length,along1)<=max(0,along0)+1e-8:continue
                transverse=E.norm(E.sub(E.sub(b0,a0),E.mul(direction,along0)))
                if transverse<diameter-1e-8:raise ValueError('Offset lap collides with another main bar: reduce count / enlarge section')
    # Reject detailing that escapes cover in transverse directions. Extensions deliberately cross host ends.
    axes=(0,1,2) if kind in ('Footing','Slab') else ((0,1) if kind=='Column' else (1,2))
    bounds=[(host['x'],host.get('width',0)),(host['y'],host.get('depth',0)),(host['z'],host['height'])]
    if kind=='Stair':
        axes=(1,);bounds[1]=(host['y'],host['width'])
        slope=host['height']/host['risers']/host['going'];cos=1/math.sqrt(1+slope*slope)
        length=(host['risers']-1)*host['going']
        for sp in out:
            for p in sp['bar_path']:
                # End extensions outside the flight require adjacent landing review.
                distance=(p[2]-host['z']-slope*(p[0]-host['x']))*cos+host['waist']
                radius=sp['bar_diameter']/2
                if not cover+radius-1e-7<=distance<=host['waist']-cover-radius+1e-7:
                    raise ValueError('Stair bar / hook does not fit normal soffit cover and waist thickness')
                if not (e0 or e1) and not host['x']+cover+radius-1e-7<=p[0]<=host['x']+length-cover-radius+1e-7:
                    raise ValueError('Stair hook does not fit flight end cover')
    for sp in out:
        if sp.get('representation')=='Centreline':
            for p in sp['bar_path']:
                for axis in axes:
                    low,size=bounds[axis];radius=sp['bar_diameter']/2
                    if not low+cover+radius-1e-7<=p[axis]<=low+size-cover-radius+1e-7:raise ValueError('Bar path / nominal radius does not fit inside host cover')
        for face in sp['faces']:
            for p in face:
                for axis in axes:
                    low,size=bounds[axis]
                    if not low+cover-1e-7<=p[axis]<=low+size-cover+1e-7:raise ValueError('Hook / bend does not fit inside host cover; reduce detailing or enlarge host')
    if len(out)>1500:raise ValueError('More than 1500 detailed bars; split the assembly')
    return out


def tables(records,issues=()):
    grouped={}
    for record in records:
        b=record['bbs'];key=(record['host_uid'],b['mark']);entry=grouped.setdefault(key,[record,b,0]);entry[2]+=1
    summary=[['Host','Mark','Shape (Thai BIM internal)','Diameter mm','Count','Cut length m','Total m','Unit mass kg/m','Total kg','Inside radius mm','Tangent straights mm','Bend angles deg','Density kg/m3','Host UID']]
    for (host,mark),(record,b,n) in sorted(grouped.items()):
        summary.append([record.get('host_name',host),mark,b['shape'],b['diameter_mm'],n,b['length_m'],n*b['length_m'],b['unit_mass_kg_m'],n*b['mass_kg'],b['inside_radius_mm'],', '.join(f'{v:.3f}' for v in b['straight_mm']),', '.join(f'{v:g}' for v in b['bend_degrees']),b['density'],host])
    detail=[['Bar UID','Host UID','Mark','Cut length m','Mass kg']]+[[r['id'],r['host_uid'],r['bbs']['mark'],r['bbs']['length_m'],r['bbs']['mass_kg']] for r in records]
    summary[0].extend(['Specified standard / unit system','Bar size','Surface','Specified grade'])
    for row,(_,(_,b,_)) in zip(summary[1:],sorted(grouped.items())):
        steel=b.get('steel',{});row.extend([steel.get(k,'Unspecified') for k in ('catalogue','size','surface','grade')])
    detail[0].extend(['Specified standard / unit system','Bar size','Surface','Specified grade'])
    for row,r in zip(detail[1:],records):
        steel=r['bbs'].get('steel',{});row.extend([steel.get(k,'Unspecified') for k in ('catalogue','size','surface','grade')])
    if any(r['bbs'].get('slab_mode') for r in records):
        headers=['Slab system','Slab role','Mesh specification'];summary[0].extend(headers);detail[0].extend(headers)
        for row,(_,(_,b,_)) in zip(summary[1:],sorted(grouped.items())):
            row.extend([b.get(k,'') for k in ('slab_mode','slab_role','mesh_specification')])
        for row,r in zip(detail[1:],records):row.extend([r['bbs'].get(k,'') for k in ('slab_mode','slab_role','mesh_specification')])
    if any(r['bbs'].get('stair_layout') for r in records):
        summary[0].extend(['Stair layout','Stair role','Length basis']);detail[0].extend(['Stair layout','Stair role','Length basis'])
        for row,(_,(_,b,_)) in zip(summary[1:],sorted(grouped.items())):row.extend([b.get(k,'') for k in ('stair_layout','stair_role','basis')])
        for row,r in zip(detail[1:],records):row.extend([r['bbs'].get(k,'') for k in ('stair_layout','stair_role','basis')])
    notes=[['Basis / excluded items'],['Internal shape names; designer supplies dimensions, radius, hooks, lap and anchorage.'],['Cut length = tangent straight lengths + (inside radius + diameter/2) × angle in radians.'],['Lap is represented by two offset bars; extensions project beyond host ends and require adjacent-host review.'],['Nominal circular diameter × input density; mesh facets are a visual approximation.'],['Legacy bars and changed/missing hosts are excluded.']]+[[v] for v in issues]
    return [('BBS',summary),('Bars',detail),('Basis and issues',notes)]
