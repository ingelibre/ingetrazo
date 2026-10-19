"""Two-point RC stair placement: lower entrance midpoint and initial ascent."""
import math
from . import stairs as S,placement as P,engine as E

def entrance(params):
    p=S.validated(params);hand=1 if p['hand']=='Left' else -1
    return (p['inner_radius']+p['width']/2,0,0) if p['layout'] in ('Spiral','Circular') else (0,hand*p['width']/2,0)

def ascent(params):
    p=S.validated(params)
    return (0,1 if p['hand']=='Left' else -1,0) if p['layout'] in ('Spiral','Circular') else (1,0,0)

def pose(params,a,b,z):
    p=S.validated(params);a=tuple(E.finite(v) for v in a);b=tuple(E.finite(v) for v in b)
    if len(a)!=3 or len(b)!=3:raise ValueError('Placement requires two 3D points')
    dx,dy=b[0]-a[0],b[1]-a[1];length=math.hypot(dx,dy)
    if not .05<=length<=100:raise ValueError('Direction points must be 0.05–100 m apart in XY')
    u=ascent(p);yaw=math.degrees(math.atan2(dy,dx)-math.atan2(u[1],u[0]));m=P.matrix((0,0,0),yaw)
    x,y,_=P.point(m,entrance(p));m[3]=a[0]-x;m[7]=a[1]-y;m[11]=E.finite(z)
    return m

def edges(spec):
    unique={}
    for face in spec['faces']:
        for a,b in zip(face,face[1:]+face[:1]):
            a,b=tuple(a),tuple(b);key=tuple(sorted((a,b)))
            if a!=b:unique.setdefault(key,(a,b))
    return list(unique.values())
