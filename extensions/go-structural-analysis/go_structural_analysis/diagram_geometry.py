"""Qt-free display geometry; coordinates and signs never alter solver values."""
import math


def reaction_components(rx,rz):
    """Independent global X/Z components; never a resultant vector."""
    return [(name,fx,fz,value) for name,fx,fz,value in
            [('Rx',rx,0.,rx),('Rz',0.,rz,rz)] if abs(value)>1e-10]


def moment_geometry(center,value,radius=24.):
    """Positive is CCW in X-right/Z-up; screen coordinates have Y down."""
    if abs(value)<=1e-10: return None
    sign=1 if value>0 else -1
    start=math.radians(-40.)
    angles=[start+sign*math.radians(280.)*i/40 for i in range(41)]
    points=[(center[0]+radius*math.cos(a),center[1]-radius*math.sin(a)) for a in angles]
    angle=angles[-1]
    head=arrow_geometry(points[-1],(-sign*math.sin(angle),-sign*math.cos(angle)),head=8.,half_width=4.)
    return points,head[1:]


def arrow_geometry(tip, direction, length=40., head=9., half_width=4.):
    magnitude=math.hypot(*direction)
    if magnitude<1e-12: return None
    ux,uy=direction[0]/magnitude,direction[1]/magnitude
    x,y=tip
    return ((x-ux*length,y-uy*length),tip,
            (x-ux*head+uy*half_width,y-uy*head-ux*half_width),
            (x-ux*head-uy*half_width,y-uy*head+ux*half_width))


def signed_cells(samples,key):
    """Split plotted strips at zero; skip duplicate-x load discontinuities."""
    for a,b in zip(samples,samples[1:]):
        x0,x1=a['x'],b['x']; y0,y1=a[key],b[key]
        if x1<=x0 or (y0==0 and y1==0): continue
        if y0*y1<0:
            zero=x0+(x1-x0)*(-y0)/(y1-y0)
            yield (1 if y0>0 else -1),[(x0,0.),(x0,y0),(zero,0.)]
            yield (1 if y1>0 else -1),[(zero,0.),(x1,y1),(x1,0.)]
        else:
              yield (1 if (y0 or y1)>0 else -1),[(x0,0.),(x0,y0),(x1,y1),(x1,0.)]

def signed_regions(samples,key):
    """Merge adjacent strips with identical sign; retain zero/jump boundaries.

    The plotted curve and enclosed area are identical to signed_cells, while a
    constant-sign member needs one filled polygon rather than 60 painter calls.
    """
    sign=None; start=None; end=None; top=[]
    for s,cell in signed_cells(samples,key):
        if len(cell)==4: curve=cell[1:3]
        elif cell[0][0]==cell[1][0]: curve=cell[1:]
        else: curve=cell[:2]
        if sign==s and end==cell[0] and top[-1]==curve[0]:
            top.extend(curve[1:]); end=cell[-1]
        else:
            if top: yield sign,[start,*top,end]
            sign=s; start=cell[0]; end=cell[-1]; top=list(curve)
    if top: yield sign,[start,*top,end]
