"""RC stair forms and explicit detailing; steel systems are reserved, not built.

Schema 2 uses a full last tread at the upper datum. Curved quantities refer to
the tessellated closed concrete shell; helical bar lengths are analytic.
"""
import copy,hashlib,json,math
from . import engine as E,detailing as D,slab_rebar as SL,steel as C
LAYOUTS=('Straight','L','U','Spiral','Circular','Floating')

def defaults():
    return dict(stair_schema=2,material_system='RC',layout='Straight',width=1.,height=3.,going=.28,risers=18,waist=.15,
        first_risers=9,landing_depth=1.2,landing_thickness=.2,gap=.15,bottom_landing=True,top_landing=True,
        inner_radius=.2,sweep=360.,hand='Left',tread_thickness=.12)
def rebar_defaults():
    return dict(cover=.025,diameter=.012,distribution_diameter=.006,spacing=.15,distribution_spacing=.2,
        inside_radius=.024,connection=.2,mats=1,representation='Centreline',main_steel=None,distribution_steel=None,extra_connections=[])
def validated(values):
    p=defaults()
    if set(values)-set(p):raise ValueError('Unknown stair parameters')
    p.update(values)
    if p['stair_schema']!=2 or p['material_system']!='RC':raise ValueError('Schema 2 supports RC only; structural steel module is not implemented')
    if p['layout'] not in LAYOUTS or p['hand'] not in ('Left','Right'):raise ValueError('Unknown stair layout / turning hand')
    for k in ('width','height','going','waist','landing_depth','landing_thickness','gap','inner_radius','sweep','tread_thickness'):p[k]=E.finite(p[k])
    for k in ('risers','first_risers'):
        v=E.finite(p[k])
        if int(v)!=v:raise ValueError('Riser counts must be integers')
        p[k]=int(v)
    if not 2<=p['risers']<=60 or not .5<=p['width']<=3 or not .2<=p['height']<=8 or not .15<=p['going']<=.6 or not .08<=p['waist']<=.5:raise ValueError('Invalid stair dimensions: width 0.5–3 m, height 0.2–8 m, going 0.15–0.6 m, waist 0.08–0.5 m, risers 2–60')
    if p['layout'] in ('L','U') and not 2<=p['first_risers']<=p['risers']-2:raise ValueError('Each L/U flight requires at least two risers')
    if not p['width']<=p['landing_depth']<=5 or not .08<=p['landing_thickness']<=.5 or not .05<=p['gap']<=2:raise ValueError('Landing depth must be >= stair width; thickness 80–500 mm; U gap 50–2000 mm')
    if not .1<=p['inner_radius']<=10 or not 30<=p['sweep']<=540 or not .06<=p['tread_thickness']<=.5:raise ValueError('Inner radius 0.1–10 m, sweep 30–540 degrees, tread thickness 60–500 mm')
    r=p['height']/p['risers'];vertical=p['waist']*math.sqrt(1+(r/p['going'])**2)
    if p['layout'] in ('Straight','L','U') and (p['bottom_landing'] or p['top_landing'] or p['layout']!='Straight') and p['landing_thickness']<vertical:raise ValueError('Landing thickness must be >= vertical flight waist thickness for this connection geometry')
    if p['layout']=='U' and p['first_risers']!=p['risers']-p['first_risers']:raise ValueError('This U layout requires equal flight riser counts so the runs align')
    if p['layout'] in ('Spiral','Circular') and p['sweep']>360:
        if p['height']*360/p['sweep']<=vertical+r:raise ValueError('Successive revolutions overlap; increase height or reduce sweep')
    return p

def volume(faces):
    return abs(sum(E.dot(face[0],E.cross(face[i],face[i+1]))/6 for face in faces for i in range(1,len(face)-1)))
def _map(point,origin,direction):
    x,y,z=point;u=direction;v=(-u[1],u[0]);return (origin[0]+u[0]*x+v[0]*y,origin[1]+u[1]*x+v[1]*y,origin[2]+z)
def _flight(n,p,origin,direction,name):
    r=p['height']/p['risers'];g=p['going'];w=p['width'];t=p['waist'];vertical=t*math.sqrt(1+(r/g)**2);run=n*g
    top=[(0,r)]
    for i in range(1,n):top.extend([(i*g,i*r),(i*g,(i+1)*r)])
    top.append((run,n*r));profile=top+[(run,n*r-vertical),(0,-vertical)]
    faces=E.extrusion([(x,0,z) for x,z in profile],(0,w,0));faces=[[_map(pt,origin,direction) for pt in f] for f in faces]
    return dict(role=name,kind='Flight',faces=faces,origin=origin,direction=direction,risers=n,run=run,rise=n*r,vertical=vertical)
def parts(values):
    p=validated(values);w=p['width'];r=p['height']/p['risers'];n=p['risers'];layout=p['layout'];out=[]
    def landing(x,y,z,width,depth,name):
        s=E.box_spec('Slab',x,y,z-p['landing_thickness'],width,depth,p['landing_thickness']);out.append(dict(role=name,kind='Landing',faces=s['faces'],params=s['params']))
    if layout in ('Spiral','Circular'):
        rin=p['inner_radius'];rout=rin+w;angle=math.radians(p['sweep']);delta=angle/n;k=p['height']/angle;t=p['waist'];faces=[]
        # One shell: tread caps, helical soffit, inner/outer walls and riser faces.
        def point(rad,a,z):return (rad*math.cos(a),rad*math.sin(a),z)
        def bottom(rad,a):return point(rad,a,k*a-t*math.sqrt(1+(k/rad)**2))
        def quad(a,b,c,d):faces.extend([[a,b,c],[a,c,d]])
        for step in range(n):
            count=max(1,math.ceil(math.degrees(delta)/2));top=(step+1)*r
            for j in range(count):
                a=step*delta+delta*j/count;b=step*delta+delta*(j+1)/count
                ai=point(rin,a,top);ao=point(rout,a,top);bi=point(rin,b,top);bo=point(rout,b,top)
                di=bottom(rin,a);do=bottom(rout,a);ei=bottom(rin,b);eo=bottom(rout,b)
                quad(ai,ao,bo,bi);quad(di,ei,eo,do)
                outer=[ao]+([point(rout,a,top-r)] if j==0 and step else [])+[do,eo,bo]
                inner=[ai,bi,ei,di]+([point(rin,a,top-r)] if j==0 and step else [])
                faces.extend([outer,inner])
            a=step*delta
            if step==0:quad(point(rin,0,r),bottom(rin,0),bottom(rout,0),point(rout,0,r))
            else:quad(point(rin,a,top),point(rin,a,top-r),point(rout,a,top-r),point(rout,a,top))
        quad(point(rin,angle,p['height']),point(rout,angle,p['height']),bottom(rout,angle),bottom(rin,angle))
        out.append(dict(role=layout+' flight',kind='Curved',faces=faces,inner=rin,outer=rout,angle=angle,k=k))
        for end,enabled in (('Bottom',p['bottom_landing']),('Top',p['top_landing'])):
            if not enabled:continue
            a=0 if end=='Bottom' else angle;z=0 if end=='Bottom' else p['height'];origin=(rout*math.cos(a),rout*math.sin(a),z);direction=(-math.sin(a),math.cos(a))
            sp=E.box_spec('Slab',-p['landing_depth'] if end=='Bottom' else 0,0,-p['landing_thickness'],p['landing_depth'],w,p['landing_thickness'])
            out.append(dict(role=end+' landing',kind='Landing',faces=[[_map(pt,origin,direction) for pt in f] for f in sp['faces']],params=sp['params'],origin=origin,direction=direction))
    elif layout=='Floating':
        for i in range(n):
            s=E.box_spec('Slab',i*p['going'],0,(i+1)*r-p['tread_thickness'],p['going']*.9,w,p['tread_thickness']);out.append(dict(role=f'Tread {i+1}',kind='Tread',faces=s['faces'],params=s['params']))
        if p['tread_thickness']>=r:raise ValueError('Floating tread thickness must be less than rise to preserve gaps')
    else:
        n1=n if layout=='Straight' else p['first_risers'];a=_flight(n1,p,(0,0,0),(1,0),'Flight 1');out.append(a);run=a['run'];depth=p['landing_depth'];mid=n1*r
        if p['bottom_landing']:landing(-depth,0,0,depth,w,'Bottom landing')
        if layout=='Straight':
            if p['top_landing']:landing(run,0,p['height'],depth,w,'Top landing')
        else:
            landing(run,0,mid,depth,w if layout=='L' else 2*w+p['gap'],'Intermediate landing')
            if layout=='L':origin=(run+w,w,mid);direction=(0,1)
            else:origin=(run,2*w+p['gap'],mid);direction=(-1,0)
            b=_flight(n-n1,p,origin,direction,'Flight 2');out.append(b)
            if p['top_landing']:
                if layout=='L':landing(run,w+b['run'],p['height'],w,depth,'Top landing')
                else:landing(-depth,w+p['gap'],p['height'],depth,w,'Top landing')
    if p['hand']=='Right':
        for part in out:
            part['faces']=[[(x,-y,z) for x,y,z in reversed(f)] for f in part['faces']]
            # Detailing is generated in left-handed layout, reflected once at end.
    return out
def spec(**values):
    p=validated(values);ps=parts(p);faces=[f for part in ps for f in part['faces']]
    return dict(slot='stair-host',kind='Stair',ifc='IfcStair',faces=faces,components=ps,color=(.58,.61,.63),discipline='Structure',item='RC '+p['layout']+' stair',unit='m3',quantity=volume(faces),stair_params=p,
        note='Schema 2: full final tread at upper datum; gross modeled concrete; RC user detailing, no strength/support/headroom design')

def _curve_bar(slot,path,db,length,role,rep,shape):
    """Moving round frames; helical paths do not have planar bend shape codes."""
    sides=6 if rep=='Lightweight' else 12;rings=[]
    for i,pt in enumerate(path) if rep!='Centreline' else []:
        a=path[max(0,i-1)];b=path[min(len(path)-1,i+1)];t=E.unit(E.sub(b,a));ref=(0,0,1) if abs(t[2])<.95 else (1,0,0);u=E.unit(E.cross(t,ref));v=E.cross(t,u)
        rings.append([E.add(pt,E.add(E.mul(u,db/2*math.cos(j*math.tau/sides)),E.mul(v,db/2*math.sin(j*math.tau/sides)))) for j in range(sides)])
    faces=[list(reversed(rings[0]))] if rings else []
    for a,b in zip(rings,rings[1:]):faces.extend([[a[j],a[(j+1)%sides],b[(j+1)%sides],b[j]] for j in range(sides)])
    if rings:faces.append(rings[-1])
    bbs=dict(schema=1,shape=shape,diameter_mm=db*1000,inside_radius_mm=0,straight_mm=[],bend_degrees=[],density=7850,length_m=length,unit_mass_kg_m=math.pi*db**2/4*7850,mass_kg=length*math.pi*db**2/4*7850,basis='Analytic helix length; 2-degree geometry tessellation; no planar bend-code certification')
    bbs['mark']='B-'+hashlib.sha256(json.dumps([bbs,role],sort_keys=True).encode()).hexdigest()[:12].upper()
    return dict(slot=slot,kind='Rebar',ifc='IfcReinforcingBar',faces=faces,color=(.68,.26,.16),discipline='Structure',item=role,unit='m',quantity=length,bar_path=path,bar_diameter=db,bar_closed=False,bbs=bbs,representation=rep,note=bbs['basis'])

def reinforcement(values,settings):
    p=validated(values);q=rebar_defaults()
    if set(settings)-set(q):raise ValueError('Unknown stair reinforcement setting')
    q.update(settings)
    for key in ('cover','diameter','distribution_diameter','spacing','distribution_spacing','inside_radius','connection'):q[key]=E.finite(q[key])
    c=q['cover'];da=q['diameter'];db=q['distribution_diameter'];rad=q['inside_radius'];conn=q['connection'];rep=q['representation'];w=p['width']
    if not .015<=c<=.1 or not .004<=da<=.06 or not .004<=db<=.06 or not .05<=q['spacing']<=.6 or not .05<=q['distribution_spacing']<=.6 or not da/2<=rad<=.25 or not 0<=conn<=1:raise ValueError('Invalid cover / diameter / spacing / inside bend radius / connection embed')
    if rep not in ('Full','Lightweight','Centreline') or q['mats'] not in (1,2):raise ValueError('Invalid representation / mat count')
    if q['main_steel']:C.validate(q['main_steel'],da*1000)
    if q['distribution_steel']:C.validate(q['distribution_steel'],db*1000)
    out=[];left=dict(p,hand='Left');ps=parts(left);margin=c+da/2+(rad+da/2 if conn and p['layout'] in ('Straight','L','U') else 0)
    if p['waist']<2*margin+(da+db)*q['mats']+(.005 if q['mats']==2 else 0) and p['layout']!='Floating':raise ValueError('Waist too thin for cover, connection bend allowance and bars')
    if p['layout']=='Floating' and q['mats']!=1:raise ValueError('Floating tread template uses top cantilever main and bottom distribution; select one set')
    def add(s,role,steel):
        C.tag(s,steel);s['item']=role+' • '+s['item'];s['bbs'].update(stair_layout=p['layout'],stair_role=role)
        s['bbs']['mark']='B-'+hashlib.sha256((s['bbs']['mark']+role).encode()).hexdigest()[:12].upper();out.append(s)
        if len(out)>3000:raise ValueError('Stair limit: 3000 bars; increase spacing')
    def bar(slot,pts,d,role,steel=None):add(D.bent_bar(slot,pts,d,inside_radius=max(rad,d/2),representation=rep,shape='Stair connection' if len(pts)>2 else 'Straight'),role,steel)
    if p['layout'] in ('Straight','L','U'):
        if conn>p['landing_depth']-c-da/2 or conn>w-c-da/2:raise ValueError('Connection embed exceeds landing depth / turning landing width')
        for part in ps:
            if part['kind']=='Landing':
                hp=part['params'];cfg=SL.defaults();cfg.update(mode='Two-way',mats=q['mats'],cover=c,diameter_a=da,diameter_b=db,spacing_a=q['spacing'],spacing_b=q['distribution_spacing'],steel_a=q['main_steel'],steel_b=q['distribution_steel'],representation=rep)
                for s in SL.generate(hp,cfg):s['slot']=part['role']+'-'+s['slot'];add(s,part['role']+' '+s['bbs']['slab_role'],None)
            else:
                n=part['risers'];L=part['run'];slope=part['rise']/L;cos=1/math.sqrt(1+slope*slope);origin=part['origin'];u=part['direction'];v=part['vertical'];offset=margin/cos
                # Full final tread permits planar cranked main bars into landings.
                before=p['bottom_landing'] if part['role']=='Flight 1' else True
                after=p['top_landing'] if part['role']==('Flight 1' if p['layout']=='Straight' else 'Flight 2') else True
                for mat in ('Bottom','Top') if q['mats']==2 else ('Bottom',):
                    base=-v+offset if mat=='Bottom' else -margin/cos
                    for i,y in enumerate(SL.rows(c+da/2,w-c-da/2,q['spacing'])):
                        start=0 if before and conn else c+da/2;end=L if after and conn else L-c-da/2
                        local=[(start,y,slope*start+base),(end,y,slope*end+base)]
                        if before and conn:local.insert(0,(-conn,y,base))
                        if after and conn:local.append((L+conn,y,part['rise']+base))
                        bar(part['role']+f'-main-{mat}-{i}',[_map(pt,origin,u) for pt in local],da,part['role']+' Main '+mat,q['main_steel'])
                    level=base+(da+db)/2/cos if mat=='Bottom' else base-(da+db)/2/cos
                    for i,x in enumerate(SL.rows(c+db/2,L-c-db/2,q['distribution_spacing'])):
                        bar(part['role']+f'-distribution-{mat}-{i}',[_map((x,y,slope*x+level),origin,u) for y in (c+db/2,w-c-db/2)],db,part['role']+' Distribution '+mat,q['distribution_steel'])
                if conn:
                    z0=origin[2]+base;zend=origin[2]+part['rise']+base
                    if before and not origin[2]-p['landing_thickness']+c+da/2<=z0<=origin[2]-c-da/2:raise ValueError('Bottom connection elevation does not fit landing cover')
                    if after and not origin[2]+part['rise']-p['landing_thickness']+c+da/2<=zend<=origin[2]+part['rise']-c-da/2:raise ValueError('Top connection elevation does not fit landing cover')
    elif p['layout'] in ('Spiral','Circular'):
        part=ps[0];angle=part['angle'];k=part['k'];rin=part['inner'];rout=part['outer'];t=p['waist']
        if conn:raise ValueError('Curved stairs: set connection=0; adjacent landing connection needs a separate designer detail')
        for mat in ('Bottom','Top') if q['mats']==2 else ('Bottom',):
            for i,radius in enumerate(SL.rows(rin+c+da/2,rout-c-da/2,q['spacing'])):
                f=math.sqrt(1+(k/radius)**2);off=-(t-c-da/2)*f if mat=='Bottom' else -(c+da/2)*f;trim=math.asin((c+da/2)/radius)
                count=max(2,math.ceil(math.degrees(angle-2*trim)/2));angles=[trim+(angle-2*trim)*j/count for j in range(count+1)];path=[(radius*math.cos(a),radius*math.sin(a),k*a+off) for a in angles]
                s=_curve_bar(f'helix-{mat}-{i}',path,da,(angle-2*trim)*math.sqrt(radius**2+k**2),'Helical main '+mat,rep,'3D helix');s['bbs'].update(helix_radius_m=radius,helix_rise_per_radian=k,helix_angle_rad=angle-2*trim);add(s,'Helical main '+mat,q['main_steel'])
            # Radial straight bars at one elevation must fit normal cover at BOTH radii.
            fmin=math.sqrt(1+(k/(rout-c-db/2))**2);fmax=math.sqrt(1+(k/(rin+c+db/2))**2)
            low=-(t-c-db/2-da)*fmin;high=-(c+db/2+da)*fmax
            if low>high:raise ValueError('Radial distribution bars do not fit curved waist; increase waist / inner radius')
            offset=low if mat=='Bottom' else high;trim=math.asin((c+db/2)/(rin+c+db/2))
            for j,a in enumerate(SL.rows(trim,angle-trim,q['distribution_spacing']/rout)):
                bar(f'radial-{mat}-{j}',[(radius*math.cos(a),radius*math.sin(a),k*a+offset) for radius in (rin+c+db/2,rout-c-db/2)],db,'Radial distribution '+mat,q['distribution_steel'])
        for part in ps[1:]:
            cfg=SL.defaults();cfg.update(mode='Two-way',mats=q['mats'],cover=c,diameter_a=da,diameter_b=db,spacing_a=q['spacing'],spacing_b=q['distribution_spacing'],steel_a=q['main_steel'],steel_b=q['distribution_steel'],representation=rep)
            for s in SL.generate(part['params'],cfg):
                s['slot']=part['role']+'-'+s['slot'];s['bar_path']=[_map(pt,part['origin'],part['direction']) for pt in s['bar_path']];s['faces']=[[_map(pt,part['origin'],part['direction']) for pt in f] for f in s['faces']];add(s,part['role']+' '+s['bbs']['slab_role'],None)
    else:
        if p['tread_thickness']<2*c+da+db:raise ValueError('Floating tread too thin for top/main and bottom/distribution bars')
        for part in ps:
            hp=part['params'];x=hp['x'];z=hp['z'];g=hp['width'];h=hp['height'];role=part['role']
            for j,xx in enumerate(SL.rows(x+c+da/2,x+g-c-da/2,q['spacing'])):
                bar(role+f'-main-{j}',[(xx,-conn,z+h-c-da/2),(xx,w-c-da/2,z+h-c-da/2)],da,role+' Cantilever main / wall embed',q['main_steel'])
            for j,y in enumerate(SL.rows(c+db/2,w-c-db/2,q['distribution_spacing'])):
                bar(role+f'-distribution-{j}',[(xx,y,z+c+db/2) for xx in (x+c+db/2,x+g-c-db/2)],db,role+' Bottom distribution',q['distribution_steel'])
    extra=q['extra_connections']
    if not isinstance(extra,list) or len(extra)>30:raise ValueError('Maximum 30 explicit connection patterns')
    for index,row in enumerate(extra):
        if set(row)!=set(('name','x','y','z','angle','length','leg','count','spacing')):raise ValueError('Invalid explicit connection pattern fields')
        name=str(row['name']).strip()
        if not name or len(name)>80:raise ValueError('Connection name 1–80 characters')
        vals={k:E.finite(v) for k,v in row.items() if k!='name'};count=vals['count']
        if count!=int(count) or not 1<=count<=40 or not .05<=vals['length']<=3 or not -1<=vals['leg']<=1 or not .025<=vals['spacing']<=1:raise ValueError('Explicit connection: count 1–40, length 50–3000 mm, leg ±1000 mm, spacing 25–1000 mm')
        a=math.radians(vals['angle']);u=(math.cos(a),math.sin(a));v=(-u[1],u[0])
        for j in range(int(count)):
            origin=(vals['x']+j*vals['spacing']*v[0],vals['y']+j*vals['spacing']*v[1],vals['z']);end=E.add(origin,(u[0]*vals['length'],u[1]*vals['length'],0));path=[origin,end]
            if vals['leg']:path.append(E.add(end,(0,0,vals['leg'])))
            bar(f'explicit-connection-{index}-{j}',path,da,'Explicit connection '+name,q['main_steel']);out[-1]['note']='Designer-specified connection coordinates; adjacent support / anchorage and clash checks not automatic'
    if p['hand']=='Right':
        for s in out:s['bar_path']=[(x,-y,z) for x,y,z in s['bar_path']];s['faces']=[[(x,-y,z) for x,y,z in reversed(f)] for f in s['faces']]
    return out
