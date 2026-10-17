"""Model metres to paper millimetres; no GUI or guessed building dimensions."""
import math
from . import engine as E

PAPERS={'A3':(420,297),'A2':(594,420),'A1':(841,594),'A0':(1189,841)}
VIEWS={'plan':('A101','Floor plan',-math.pi/2,math.pi/2),
       'roof':('A102','Roof plan',-math.pi/2,math.pi/2),
       'front':('A201','Front elevation',-math.pi/2,0),
       'side':('A202','Side elevation',0,0),
       'section':('A301','Section A-A',0,0)}

def grid_label(i):
    out='';i+=1
    while i: i,r=divmod(i-1,26);out=chr(65+r)+out
    return out

def config(bounds,grid_x,grid_y,levels,paper='A3',cut_z=1.5,section_x=None,views=('plan','roof','front','side','section'),datum=0):
    if paper not in PAPERS:raise ValueError('Paper must be A3, A2, A1 or A0 landscape')
    lo,hi=[tuple(E.finite(v) for v in p) for p in bounds]
    if len(lo)!=3 or len(hi)!=3 or any(hi[i]-lo[i]<=1e-6 for i in range(3)):raise ValueError('Select a nonzero 3D model extent')
    gx=sorted(set(E.finite(v) for v in grid_x));gy=sorted(set(E.finite(v) for v in grid_y))
    if not 2<=len(gx)<=20 or not 2<=len(gy)<=20:raise ValueError('Supply 2–20 project grids per axis; grids are not inferred from geometry')
    ls=[dict(name=str(v['name']).strip(),z=E.finite(v['z'])) for v in levels]
    if not ls or len(ls)>20 or any(not v['name'] or len(v['name'])>30 for v in ls):raise ValueError('Supply 1–20 named project levels, name length <=30')
    if len({v['name'] for v in ls})!=len(ls):raise ValueError('Duplicate level names')
    cut=E.finite(cut_z);sx=E.finite(section_x if section_x is not None else (lo[0]+hi[0])/2)
    views=list(views)
    if not views or len(views)!=len(set(views)) or any(v not in VIEWS for v in views):raise ValueError('Select unique supported sheet views')
    if 'plan' in views and not lo[2]<cut<hi[2]:raise ValueError('Plan cut must lie within model vertical extent')
    if 'section' in views and not lo[0]<sx<hi[0]:raise ValueError('Section X must lie inside model extent')
    pw,ph=PAPERS[paper];frame=(45,45,pw-125,ph-125)
    extlo=[min(lo[0],min(gx)),min(lo[1],min(gy)),min(lo[2],*(l['z'] for l in ls))]
    exthi=[max(hi[0],max(gx)),max(hi[1],max(gy)),max(hi[2],*(l['z'] for l in ls))]
    centre=tuple((a+b)/2 for a,b in zip(extlo,exthi));out=[]
    for key in views:
        code,title,yaw,pitch=VIEWS[key];axes=(0,1) if key in ('plan','roof') else ((0,2) if key=='front' else (1,2))
        mw,mh=[(exthi[a]-extlo[a])*20 for a in axes]
        if mw+30>frame[2] or mh+30>frame[3]:raise ValueError(f'{title} will clip at 1:50 on {paper}; choose a larger paper')
        target=list(centre)
        if key=='plan':target[2]=cut
        if key=='section':target[0]=sx
        out.append(dict(key=key,code=code,title=title,frame=frame,target=target,yaw=yaw,pitch=pitch,axes=axes))
    return dict(bounds=[lo,hi],grid_x=gx,grid_y=gy,levels=ls,paper=paper,paper_size=(pw,ph),scale=50,
                cut_z=cut,section_x=sx,datum=E.finite(datum),sheets=out)

def project(sheet,point):
    x,y,w,h=sheet['frame'];t=sheet['target'];key=sheet['key']
    if key in ('plan','roof'):u,v=point[0]-t[0],point[1]-t[1]
    elif key=='front':u,v=point[0]-t[0],point[2]-t[2]
    else:u,v=point[1]-t[1],point[2]-t[2]
    return x+w/2+20*u,y+h/2-20*v

def level_positions(sheet,levels):
    """Separate close level labels while preserving leaders to their exact Z."""
    last=-math.inf;out=[]
    for level in sorted(levels,key=lambda l:l['z'],reverse=True):
        p=list(sheet['target']);p[2]=level['z'];py=project(sheet,p)[1]
        label_y=max(py,last+7);last=label_y;out.append((level,py,label_y))
    if out and out[-1][2]>sheet['frame'][1]+sheet['frame'][3]+12:raise ValueError('Too many close level labels for this paper')
    return out
