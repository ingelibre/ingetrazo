"""User-specified slab detailing. Exact line clipping against boundary capsules.

All coordinates are Host-local metres. No design, anchorage or slab-classification
calculation. Wire quantities are net installed wires, not purchased mesh sheets.
"""
import math
from . import engine as E,detailing as D,path_geometry as PG,steel as C

MODES=('One-way','Two-way','Precast')
def defaults():
    return dict(mode='One-way',axis='X',mats=1,cover=.025,diameter_a=.012,diameter_b=.006,
        spacing_a=.15,spacing_b=.2,steel_a=None,steel_b=None,representation='Centreline',
        topping=.08,wire_a=.004,wire_b=.004,wire_spacing_a=.15,wire_spacing_b=.15,
        wire_name='User-specified welded mesh',dowels=False,dowel_ends='Both',
        dowel_diameter=.012,dowel_spacing=.2,dowel_embed=.3,dowel_extension=.2,
        dowel_shape='Straight',dowel_leg=.08,dowel_radius=.024,dowel_cover=.01,dowel_steel=None)

def boundary(host):
    if host.get('shape')=='polygon':return PG.outline(host['footprint'])
    x,y,w,d=(E.finite(host[k]) for k in ('x','y','width','depth'))
    return PG.outline([(x,y),(x+w,y),(x+w,y+d),(x,y+d)])

def inside(point,polygon):
    x,y=point;odd=False
    for a,b in zip(polygon,polygon[1:]+polygon[:1]):
        if (a[1]>y)!=(b[1]>y) and x<(b[0]-a[0])*(y-a[1])/(b[1]-a[1])+a[0]:odd=not odd
    return odd

def _subtract(intervals,cut):
    lo,hi=cut;out=[]
    for a,b in intervals:
        if hi<=a or lo>=b:out.append((a,b))
        else:
            if lo>a:out.append((a,lo))
            if hi<b:out.append((hi,b))
    return out

def _band(base,slope,lo,hi):
    if abs(slope)<1e-12:return (-math.inf,math.inf) if lo<=base<=hi else None
    a,b=(lo-base)/slope,(hi-base)/slope
    return min(a,b),max(a,b)

def clipped(polygon,direction,row,clearance):
    """Intervals t for p=t*u+row*v at least clearance from every edge.

    Polygon interior intervals are cut by exact segment capsules (strip + endpoint
    circles). Concave re-entrant corners can therefore produce multiple bars.
    """
    clearance=max(0,clearance-1e-10)
    ux,uy=direction;v=(-uy,ux);origin=(row*v[0],row*v[1]);cuts=[]
    for a,b in zip(polygon,polygon[1:]+polygon[:1]):
        sa=a[0]*v[0]+a[1]*v[1];sb=b[0]*v[0]+b[1]*v[1]
        if (sa>row)!=(sb>row):
            f=(row-sa)/(sb-sa);cuts.append((a[0]+f*(b[0]-a[0]))*ux+(a[1]+f*(b[1]-a[1]))*uy)
    cuts.sort();intervals=[(a,b) for a,b in zip(cuts[::2],cuts[1::2]) if b-a>1e-9]
    return clear_edges(intervals,polygon,direction,row,clearance)

def clear_edges(intervals,polygon,direction,row,clearance):
    ux,uy=direction;v=(-uy,ux);origin=(row*v[0],row*v[1])
    for a,b in zip(polygon,polygon[1:]+polygon[:1]):
        dx,dy=b[0]-a[0],b[1]-a[1];length=math.hypot(dx,dy);ex,ey=dx/length,dy/length
        rx,ry=origin[0]-a[0],origin[1]-a[1]
        along=_band(rx*ex+ry*ey,ux*ex+uy*ey,0,length)
        across=_band(-rx*ey+ry*ex,-ux*ey+uy*ex,-clearance,clearance)
        if along and across:
            lo,hi=max(along[0],across[0]),min(along[1],across[1])
            if hi>lo:intervals=_subtract(intervals,(lo,hi))
        for point in (a,b):
            t=point[0]*ux+point[1]*uy;s=point[0]*v[0]+point[1]*v[1]
            square=clearance**2-(s-row)**2
            if square>0:
                delta=math.sqrt(square);intervals=_subtract(intervals,(t-delta,t+delta))
    return [(a,b) for a,b in intervals if b-a>1e-8]

def rows(lo,hi,spacing):
    if hi<lo:return []
    n=max(1,math.ceil((hi-lo)/spacing))
    if n>2000:raise ValueError('Too many rows; increase spacing or split the Host')
    return [lo+(hi-lo)*i/n for i in range(n+1)] if hi>lo+1e-8 else [lo]

def generate(host,settings):
    p=defaults();unknown=set(settings)-set(p)
    if unknown:raise ValueError('Unknown slab settings: '+str(sorted(unknown)))
    p.update(settings);poly=boundary(host);z=E.finite(host['z']);h=E.finite(host['height'])
    from .shape_geometry import validated_holes
    holes=validated_holes(poly,host.get('holes',[]))
    if p['mode'] not in MODES or p['axis'] not in ('X','Y') or p['mats'] not in (1,2):raise ValueError('Invalid slab mode / span axis / mat count')
    if p['representation'] not in ('Full','Lightweight','Centreline'):raise ValueError('Unknown representation')
    if not isinstance(p['wire_name'],str) or not 1<=len(p['wire_name'].strip())<=120:raise ValueError('Specify mesh name / product (1–120 characters)')
    numbers=('cover','diameter_a','diameter_b','spacing_a','spacing_b','topping','wire_a','wire_b','wire_spacing_a','wire_spacing_b','dowel_diameter','dowel_spacing','dowel_embed','dowel_extension','dowel_leg','dowel_radius','dowel_cover')
    for k in numbers:p[k]=E.finite(p[k])
    if not .005<=p['cover']<=.1:raise ValueError('Cover must be 5–100 mm (to steel surface)')
    for k in ('spacing_a','spacing_b','wire_spacing_a','wire_spacing_b','dowel_spacing'):
        if not .025<=p[k]<=1:raise ValueError('Spacing must be 25–1000 mm')
    for k in ('diameter_a','diameter_b','dowel_diameter'):
        if not .004<=p[k]<=.06:raise ValueError('Rebar diameter must be 4–60 mm')
    for k in ('wire_a','wire_b'):
        if not .002<=p[k]<=.012:raise ValueError('Mesh wire diameter must be 2–12 mm')
    for role in ('a','b'):
        if p['steel_'+role]:C.validate(p['steel_'+role],p['diameter_'+role]*1000)
    if p['dowel_steel']:C.validate(p['dowel_steel'],p['dowel_diameter']*1000)
    if p['mode']!='Precast' and p['dowels']:raise ValueError('End dowels are available only in Precast mode')
    u=(1,0) if p['axis']=='X' else (0,1);v=(-u[1],u[0]);specs=[]
    def bar(slot,points,db,role,wire=False,steel=None,shape='Straight'):
        s=D.bent_bar(slot,points,db,inside_radius=max(db/2,p['dowel_radius']) if shape!='Straight' else db/2,
            shape=shape,representation=p['representation'],wire=wire)
        C.tag(s,steel);s['item']=role+' • '+(s['item'] if not wire else f"{p['wire_name']} D{db*1000:g}")
        s['bbs'].update(slab_role=role,slab_mode=p['mode'],wire=wire)
        if wire:s['bbs']['mesh_specification']=p['wire_name']
        # Keep different roles distinct in BBS grouping, even with identical shapes.
        import hashlib
        s['bbs']['mark']='B-'+hashlib.sha256((s['bbs']['mark']+role).encode()).hexdigest()[:12].upper()
        specs.append(s)
        if len(specs)>5000:raise ValueError('Slab limit: 5000 bars; split the Host or increase spacing')
    def mat(direction,level,db,spacing,role,slot,wire=False,steel=None):
        normal=(-direction[1],direction[0]);r=p['cover']+db/2
        transverse=[a*normal[0]+b*normal[1] for a,b in poly]
        for i,row in enumerate(rows(min(transverse)+r,max(transverse)-r,spacing)):
            intervals=clipped(poly,direction,row,r)
            for hole in holes:
                for cut in clipped(hole,direction,row,0):intervals=_subtract(intervals,cut)
                intervals=clear_edges(intervals,hole,direction,row,r)
            for j,(a,b) in enumerate(intervals):
                if b-a<db:continue
                pts=[(t*direction[0]+row*normal[0],t*direction[1]+row*normal[1],level) for t in (a,b)]
                bar(f'{slot}-{i}-{j}',pts,db,role,wire,steel)
    if p['mode']=='Precast':
        da,db=p['wire_a'],p['wire_b'];top=z+h-p['cover'];bottom=top-da-db
        if not .01<=p['topping']<=h or bottom<z+h-p['topping']+p['cover']-1e-9:raise ValueError('Mesh and top/bottom cover do not fit specified topping inside Host')
        mat(u,top-da/2,da,p['wire_spacing_a'],'Wire mesh A','mesh-a',True)
        mat(v,top-da-db/2,db,p['wire_spacing_b'],'Wire mesh B','mesh-b',True)
        if p['dowels']:
            if holes:raise ValueError('Precast end dowels with slab openings require separate detailing; mesh without dowels supported')
            if host.get('shape')=='polygon':raise ValueError('Precast end dowels currently require a rectangular Host; mesh alone supports polygons')
            if p['dowel_ends'] not in ('Start','End','Both') or p['dowel_shape'] not in ('Straight','L'):raise ValueError('Unknown dowel end / shape')
            d=p['dowel_diameter'];c=p['dowel_cover']
            if not .005<=c<=.1 or not .05<=p['dowel_embed']<=3 or not .01<=p['dowel_extension']<=3:raise ValueError('Specify dowel cover 5–100, embed 50–3000 and outside extension 10–3000 mm')
            if not d/2<=p['dowel_radius']<=.25:raise ValueError('Dowel inside bend radius must be at least half its diameter')
            span=[a*u[0]+b*u[1] for a,b in poly];cross=[a*v[0]+b*v[1] for a,b in poly]
            if p['dowel_embed']>max(span)-min(span)-c-d/2:raise ValueError('Dowel embed exceeds the Host span')
            if p['dowel_ends']=='Both' and 2*p['dowel_embed']+d>max(span)-min(span):raise ValueError('Opposing end dowels overlap; reduce embed or detail separately')
            level=z+h-p['topping']+c+d/2
            if level+d/2>bottom-1e-9:raise ValueError('Dowel and mesh overlap vertically; change topping / cover / diameter')
            if p['dowel_shape']=='L' and (not .01<=p['dowel_leg']<=3 or level+p['dowel_leg']+d/2>top):raise ValueError('L dowel upward leg does not fit topping cover')
            for end in ('Start','End') if p['dowel_ends']=='Both' else (p['dowel_ends'],):
                t=min(span) if end=='Start' else max(span);sign=1 if end=='Start' else -1
                for i,row in enumerate(rows(min(cross)+c+d/2,max(cross)-c-d/2,p['dowel_spacing'])):
                    def point(t,zv):return (t*u[0]+row*v[0],t*u[1]+row*v[1],zv)
                    pts=[point(t-sign*p['dowel_extension'],level),point(t+sign*p['dowel_embed'],level)]
                    if p['dowel_shape']=='L':pts.append(point(t+sign*p['dowel_embed'],level+p['dowel_leg']))
                    bar(f'dowel-{end}-{i}',pts,d,'End dowel '+end,steel=p['dowel_steel'],shape=p['dowel_shape'])
    else:
        da,db=p['diameter_a'],p['diameter_b'];c=p['cover'];thick=da+db
        if h<2*c+thick*(2 if p['mats']==2 else 1)+(.005 if p['mats']==2 else 0):raise ValueError('Selected mats / cover / diameters do not fit slab thickness')
        for name in ('Bottom','Top') if p['mats']==2 else ('Bottom',):
            za=z+c+da/2 if name=='Bottom' else z+h-c-da/2
            zb=za+(da+db)/2 if name=='Bottom' else za-(da+db)/2
            rolea='Main' if p['mode']=='One-way' else 'Two-way A';roleb='Distribution' if p['mode']=='One-way' else 'Two-way B'
            mat(u,za,da,p['spacing_a'],rolea+' '+name,'rc-a-'+name,steel=p['steel_a'])
            mat(v,zb,db,p['spacing_b'],roleb+' '+name,'rc-b-'+name,steel=p['steel_b'])
    if not specs:raise ValueError('No bars fit Host and cover')
    return specs
