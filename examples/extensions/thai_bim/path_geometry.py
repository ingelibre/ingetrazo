"""Horizontal two-point beams, slabs and directed straight stairs."""
import copy,math
from . import engine as E,placement as P,structures as S

def xy(point):return tuple(E.finite(v) for v in point[:2])
def direction(a,b):
    a,b=xy(a),xy(b);dx,dy=b[0]-a[0],b[1]-a[1];length=math.hypot(dx,dy)
    if length<.05 or length>100:raise ValueError('Point span must be 0.05–100 m')
    return length,math.degrees(math.atan2(dy,dx))

def beam(a,b,z,p):
    length,yaw=direction(a,b);sp=E.box_spec('Beam',0,-p['depth']/2,0,length,p['depth'],p['height'])
    return sp,P.matrix((*xy(a),E.finite(z)),yaw)

def rectangle(a,b,z,p):
    a,b=xy(a),xy(b);x,y=min(a[0],b[0]),min(a[1],b[1]);w,d=abs(a[0]-b[0]),abs(a[1]-b[1])
    if min(w,d)<.05:raise ValueError('Rectangle sides must be at least 0.05 m')
    return E.box_spec('Slab',0,0,0,w,d,p['height']),P.matrix((x,y,E.finite(z)))

def outline(points):
    pts=[xy(p) for p in points]
    if len(pts)>1 and pts[0]==pts[-1]:pts.pop()
    if not 3<=len(pts)<=100:raise ValueError('Polygon requires 3–100 points')
    pairs=list(zip(pts,pts[1:]+pts[:1]))
    if min(math.dist(a,b) for a,b in pairs)<.002:raise ValueError('Duplicate or too-close polygon points')
    def cross(a,b,c):return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])
    def on(a,b,p):return abs(cross(a,b,p))<1e-9 and min(a[0],b[0])-1e-9<=p[0]<=max(a[0],b[0])+1e-9 and min(a[1],b[1])-1e-9<=p[1]<=max(a[1],b[1])+1e-9
    for i,(a,b) in enumerate(pairs):
        prev=pts[i-1]
        if abs(cross(prev,a,b))<1e-9:raise ValueError('Remove collinear polygon corners')
        for j,(c,d) in enumerate(pairs):
            if j<=i or j==i+1 or (i==0 and j==len(pairs)-1):continue
            if cross(a,b,c)*cross(a,b,d)<0 and cross(c,d,a)*cross(c,d,b)<0 or any((on(a,b,c),on(a,b,d),on(c,d,a),on(c,d,b))):
                raise ValueError('Polygon self-intersects or touches itself')
    signed=sum(a[0]*b[1]-b[0]*a[1] for a,b in pairs)/2
    if abs(signed)<.0025:raise ValueError('Polygon area too small')
    return pts if signed>0 else list(reversed(pts))

def polygon(points,z,p):
    pts=outline(points);x,y=pts[0];local=[(a-x,b-y) for a,b in pts]
    w=max(a for a,b in local)-min(a for a,b in local);d=max(b for a,b in local)-min(b for a,b in local)
    sp=E.box_spec('Slab',min(a for a,b in local),min(b for a,b in local),0,w,d,p['height'])
    sp['faces']=E.extrusion([(a,b,0) for a,b in local],(0,0,p['height']))
    sp['quantity']=E.area(local)*p['height'];sp['params'].update(footprint=local,shape='polygon')
    sp['note']='Horizontal polygon slab; no holes; gross volume; polygon reinforcement not implemented'
    return sp,P.matrix((x,y,E.finite(z)))

def stair(a,b,z,p):
    _,yaw=direction(a,b);return S.stair_spec(**{k:p[k] for k in ('width','height','going','risers','waist')}),P.matrix((*xy(a),E.finite(z)),yaw)

def build(mode,points,z,p):
    if mode=='beam':return beam(*points,z,p)
    if mode=='rectangle':return rectangle(*points,z,p)
    if mode=='polygon':return polygon(points,z,p)
    if mode=='stair':return stair(*points,z,p)
    if mode=='point':return P.member_spec(p['kind'],p['width'],p['depth'],p['height']),P.matrix((*xy(points[0]),z),p.get('yaw',0))
    raise ValueError('Unknown placement mode')
