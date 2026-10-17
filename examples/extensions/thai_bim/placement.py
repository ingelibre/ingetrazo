"""Rigid placement and projection helpers, independent of the host/Qt."""
import copy,math
from . import engine as E

IDENTITY=[1.,0.,0.,0.,0.,1.,0.,0.,0.,0.,1.,0.,0.,0.,0.,1.]

def rigid_matrix(values=None):
    m=list(IDENTITY) if values is None else [E.finite(v) for v in values]
    if len(m)!=16:raise ValueError('Placement matrix requires 16 values')
    if any(abs(m[12+i]-IDENTITY[12+i])>1e-6 for i in range(4)):raise ValueError('Perspective placement is unsupported')
    cols=[tuple(m[i*4+j] for i in range(3)) for j in range(3)]
    for i,a in enumerate(cols):
        for j,b in enumerate(cols):
            if abs(E.dot(a,b)-(1 if i==j else 0))>1e-5:raise ValueError('Scale / shear is unsupported; use parametric dimensions')
    if E.dot(cols[0],E.cross(cols[1],cols[2]))<.99999:raise ValueError('Mirrored placement is unsupported')
    return m

def same_pose(a,b):return all(abs(x-y)<=1e-6 for x,y in zip(rigid_matrix(a),rigid_matrix(b)))

def matrix(anchor,yaw=0):
    x,y,z=map(E.finite,anchor);angle=math.radians(E.finite(yaw));c=math.cos(angle);s=math.sin(angle)
    return [c,-s,0,x,s,c,0,y,0,0,1,z,0,0,0,1]

def point(m,p):
    m=rigid_matrix(m);p=tuple(map(E.finite,p))
    return _point(m,p)

def _point(m,p):
    return tuple(sum(m[i*4+j]*p[j] for j in range(3))+m[i*4+3] for i in range(3))

def member_spec(kind,width,depth,height):
    if kind not in ('Footing','Column','Beam','Slab'):raise ValueError('Placement supports Footing, Column, Beam and Slab')
    centred=kind in ('Footing','Column')
    return E.box_spec(kind,-width/2 if centred else 0,-depth/2 if centred else 0,0,width,depth,height)

def world_specs(specs,pose=None):
    m=rigid_matrix(pose);result=[]
    for spec in specs:
        s=copy.deepcopy(spec);s['faces']=[[_point(m,v) for v in face] for face in s['faces']]
        for key in ('bar_path','axis'):
            if s.get(key):s[key]=[_point(m,v) for v in s[key]]
        result.append(s)
    return result

def grid_points(xs,ys,z):
    if not xs or not ys or len(xs)*len(ys)>400:raise ValueError('Grid must contain 1–400 intersections')
    return [(E.finite(x),E.finite(y),E.finite(z)) for x in xs for y in ys]

NAMED_SNAPS={'axis','reference','close','endpoint','intersection','midpoint','origin','on_edge','on_face','centre','center','tangent'}

def nearest_grid(points,pixels,front,cursor,kind='none',radius=9):
    if kind in NAMED_SNAPS:return None
    candidates=[((xy[0]-cursor[0])**2+(xy[1]-cursor[1])**2,i) for i,xy in enumerate(pixels) if front[i]]
    if not candidates:return None
    distance,index=min(candidates)
    return points[index] if distance<=radius*radius else None
