"""Continuous stationing and exact result projection onto a reviewed common frame.

PyNite section forces use the i-side cut: reversing x reverses the cut normal.
The result adapter stores bending My with the opposite sign to the moment vector.
Hence moments are transformed as (T, -My, Mz), then converted back. Displacements
are vectors, without a cut-normal reversal. No solver inputs/results are changed.
"""
import math
from .member_geometry import collinear_members
from .results import polynomial

def dot(a,b): return sum(x*y for x,y in zip(a,b))

def chain_layout(model,members,identifier,tolerance=1e-7):
    ids=collinear_members(model,identifier); reference=members[identifier]['basis']
    axis=reference[0] if len(reference)==3 else [reference[0][0],0,reference[0][1]]
    nodes={n['id']:[n.get(k,0.) for k in ('x','y','z')] for n in model['nodes']}
    definitions={m['id']:m for m in model['members']}; records=[]
    for mid in ids:
        m=definitions[mid]; a,b=(dot(nodes[m[end]],axis) for end in ('i','j'))
        records.append(dict(id=mid,start=min(a,b),end=max(a,b),forward=b>a,
                            left_node=m['i'] if b>a else m['j'],right_node=m['j'] if b>a else m['i']))
    records.sort(key=lambda r:(r['start'],r['end'],r['id']))
    origin=records[0]['start']
    for index,row in enumerate(records):
        row['start']-=origin; row['end']-=origin
        if index:
            previous=records[index-1]
            if abs(previous['end']-row['start'])>tolerance or previous['right_node']!=row['left_node']:
                raise ValueError('Cannot join overlapping or branched members into one continuous beam. Check Model first.')
    return records,reference

def weights(member,reference,quantity):
    basis=member['basis']; orientation=1 if dot(basis[0],reference[0])>=0 else -1
    if len(basis)==2:
        if quantity=='M':
            determinant=lambda b:b[0][0]*b[1][1]-b[0][1]*b[1][0]
            return {'M':orientation*determinant(basis)*determinant(reference)}
        if quantity=='d': return {'u':dot(reference[1],basis[0]),'d':dot(reference[1],basis[1])}
        row=reference[0 if quantity=='N' else 1]
        return {k:orientation*dot(row,basis[i]) for i,k in enumerate(('N','V'))}
    if quantity=='D': return None
    if quantity in ('N','Vy','Vz'):
        row=reference[('N','Vy','Vz').index(quantity)]
        return {k:orientation*dot(row,basis[i]) for i,k in enumerate(('N','Vy','Vz'))}
    row=reference[('T','My','Mz').index(quantity)]; output_sign=-1 if quantity=='My' else 1
    return {k:output_sign*orientation*dot(row,basis[i])*(-1 if k=='My' else 1) for i,k in enumerate(('T','My','Mz'))}

def coefficients(segment,projection):
    size=max(len(segment['coefficients'][k]) for k in projection)
    out=[0.]*size
    for key,factor in projection.items():
        for i,value in enumerate(segment['coefficients'][key]): out[i]+=factor*value
    return out

def station(record,member,x):
    return record['start']+(x if record['forward'] else member['L']-x)

def graph_data(model,members,identifier,quantity):
    """One axis/scale, separate polynomial intervals and true (unsmoothed) jumps."""
    import numpy as np
    P=np.polynomial.Polynomial
    records,reference=chain_layout(model,members,identifier); series=[]; extrema=[]
    for record in records:
        member=members[record['id']]; projection=weights(member,reference,quantity)
        intervals=member['segments'] if record['forward'] else list(reversed(member['segments']))
        for segment in intervals:
            h=segment['x2']-segment['x1']
            poly=P(coefficients(segment,projection)) if projection is not None else sum((P(segment['coefficients'][k])**2 for k in ('u','dy','dz')),P([0]))
            roots=[float(r.real) for r in poly.deriv().roots() if abs(r.imag)<1e-8 and 0<r.real<h]
            value=lambda t:float(poly(t)) if projection is not None else math.sqrt(max(0.,float(poly(t))))
            for t in [0.,h]+roots:
                x=segment['x1']+t; side='left' if t==h else 'right'
                extrema.append(dict(value=value(t),x=station(record,member,x),member=record['id'],local_x=x,side=side))
            ts=sorted(set([h*i/48 for i in range(49)]+roots),reverse=not record['forward'])
            series.append([(station(record,member,segment['x1']+t),value(t)) for t in ts])
    return dict(records=records,reference=reference,L=records[-1]['end'],series=series,
                extrema={'min':min(extrema,key=lambda e:e['value']),'max':max(extrema,key=lambda e:e['value'])})

def inspect_chain(member,reference,quantity,x,side='right'):
    from .results import evaluate
    values=evaluate(member,x,side); projection=weights(member,reference,quantity)
    return values['D'] if projection is None else sum(values[k]*factor for k,factor in projection.items())
