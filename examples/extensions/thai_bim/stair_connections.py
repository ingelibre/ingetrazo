"""Centreline/closed-support intersections; geometry only, no anchorage design."""
import math
from . import engine as E

EPS=1e-8
def prepare(triangles):
    if not 4<=len(triangles)<=5000:raise ValueError('Support requires 4–5000 triangles')
    result=[];edges={}
    for triangle in triangles:
        if len(triangle)!=3:raise ValueError('Support triangle requires three vertices')
        t=[tuple(E.finite(v) for v in p) for p in triangle]
        if any(len(p)!=3 for p in t) or E.norm(E.cross(E.sub(t[1],t[0]),E.sub(t[2],t[0])))<1e-12:raise ValueError('Degenerate support triangle')
        result.append(t)
        for a,b in zip(t,t[1:]+t[:1]):
            key=tuple(sorted((a,b)));edges[key]=edges.get(key,0)+1
    if any(n!=2 for n in edges.values()):raise ValueError('Support triangulation must be a closed two-manifold shell')
    return result

def ray(p,d,t):
    a,b,c=t;e1=E.sub(b,a);e2=E.sub(c,a);h=E.cross(d,e2);det=E.dot(e1,h)
    if abs(det)<1e-12:return None
    s=E.sub(p,a);u=E.dot(s,h)/det
    if u<-EPS or u>1+EPS:return None
    q=E.cross(s,e1);v=E.dot(d,q)/det
    if v<-EPS or u+v>1+EPS:return None
    return E.dot(e2,q)/det

def on_triangle(p,t):
    a,b,c=t;u=E.sub(b,a);v=E.sub(c,a);w=E.sub(p,a);n=E.cross(u,v);nn=E.dot(n,n)
    if abs(E.dot(w,n))>EPS*math.sqrt(nn):return False
    uu=E.dot(u,u);uv=E.dot(u,v);vv=E.dot(v,v);wu=E.dot(w,u);wv=E.dot(w,v);den=uu*vv-uv*uv
    x=(vv*wu-uv*wv)/den;y=(uu*wv-uv*wu)/den
    return x>=-EPS and y>=-EPS and x+y<=1+EPS

def unique(values):
    out=[]
    for value in sorted(values):
        if not out or abs(value-out[-1])>EPS:out.append(value)
    return out

def classify(p,triangles):
    if any(on_triangle(p,t) for t in triangles):return 'boundary'
    direction=(.719,.437,.541);hits=unique(x for t in triangles if (x:=ray(p,direction,t)) is not None and x>EPS)
    return 'inside' if len(hits)%2 else 'outside'

def spans(a,b,triangles):
    delta=E.sub(b,a);length=E.norm(delta)
    if length<EPS:return []
    cuts=unique([0.,1.]+[max(0.,min(1.,x)) for t in triangles if (x:=ray(a,delta,t)) is not None and -EPS<=x<=1+EPS])
    out=[]
    for lo,hi in zip(cuts,cuts[1:]):
        state=classify(E.add(a,E.mul(delta,(lo+hi)/2)),triangles)
        out.append((lo*length,hi*length,state))
    return out

def segment(a,b,triangles):
    ranges=spans(a,b,triangles)
    return sum(hi-lo for lo,hi,s in ranges if s=='inside'),sum(hi-lo for lo,hi,s in ranges if s=='boundary')

def inspect(paths,triangles,required=None):
    triangles=prepare(triangles)
    if not 1<=len(paths)<=200:raise ValueError('Select a role containing 1–200 bars')
    if len(triangles)*sum(len(r['path']) for r in paths)>500000:raise ValueError('Inspection scope too large; choose fewer bars or a simpler support')
    if required is not None:
        required=E.finite(required)
        if not 0<required<=3:raise ValueError('User-required geometric length must be >0 and <=3 m')
    lower=[min(p[i] for t in triangles for p in t) for i in range(3)];upper=[max(p[i] for t in triangles for p in t) for i in range(3)];out=[]
    for record in paths:
        points=[tuple(E.finite(v) for v in p) for p in record['path']]
        if len(points)<2 or any(len(p)!=3 for p in points):raise ValueError('Bar path requires at least two XYZ points')
        overlap=all(max(p[i] for p in points)>=lower[i]-EPS and min(p[i] for p in points)<=upper[i]+EPS for i in range(3))
        length=boundary=distance=0.;intervals=[]
        if overlap:
            for a,b in zip(points,points[1:]):
                for lo,hi,state in spans(a,b,triangles):
                    if state=='inside':
                        length+=hi-lo;start,end=distance+lo,distance+hi
                        if intervals and abs(intervals[-1][1]-start)<EPS:intervals[-1][1]=end
                        else:intervals.append([start,end])
                    elif state=='boundary':boundary+=hi-lo
                distance+=math.dist(a,b)
        longest=max((hi-lo for lo,hi in intervals),default=0.)
        contact=overlap and (boundary>EPS or any(classify(p,triangles)=='boundary' for p in points))
        state='no_entry' if length<EPS else 'requirement_missing' if required is None else 'geometry_length_met' if longest+EPS>=required else 'geometry_length_short'
        if length<EPS and contact:state='surface_contact_only'
        out.append(dict(slot=str(record['slot']),inside_length_m=length,longest_inside_m=longest,inside_intervals_m=intervals,boundary_length_m=boundary,required_m=required,state=state,path=[list(p) for p in points]))
    return dict(schema=1,rows=out,required_m=required,design_verified=False,
        basis='Longest continuous model centreline interval strictly inside selected closed support compared with user input; total also reported; boundary excluded; sampled curves; not anchorage design',
        limitations=['No strength, bond/development length, cover, bar diameter envelope, splice, concrete-to-concrete contact or whole-model clash check',
                     'Designer must verify support role, actual bar shape and detailing; curved centreline is tessellated',
                     'Support shells must be closed and non-intersecting; overlapping shells and self-intersections are unsupported'])
