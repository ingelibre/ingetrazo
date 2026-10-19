"""Analytical member lengths and connected collinear selections (no mesh mutation)."""
import math

def member_length(model, identifier):
    nodes={n['id']:n for n in model['nodes']}
    member=next(m for m in model['members'] if m['id']==identifier)
    return math.sqrt(sum((float(nodes[member['j']].get(k,0))-float(nodes[member['i']].get(k,0)))**2 for k in ('x','y','z')))

def collinear_members(model, identifier, tolerance=1e-7):
    nodes={n['id']:tuple(float(n.get(k,0)) for k in ('x','y','z')) for n in model['nodes']}
    members={m['id']:m for m in model['members']}
    selected=members[identifier]; origin=nodes[selected['i']]
    direction=tuple(b-a for a,b in zip(origin,nodes[selected['j']]))
    length=math.sqrt(sum(v*v for v in direction))
    if length<=tolerance: return [identifier]
    axis=tuple(v/length for v in direction)
    def on_line(node):
        d=tuple(v-o for v,o in zip(nodes[node],origin)); dot=sum(a*b for a,b in zip(d,axis))
        return math.sqrt(sum((v-dot*a)**2 for v,a in zip(d,axis)))<=tolerance
    eligible={mid:m for mid,m in members.items() if on_line(m['i']) and on_line(m['j']) and member_length(model,mid)>tolerance}
    found={identifier}; connected={selected['i'],selected['j']}
    while True:
        added={mid for mid,m in eligible.items() if mid not in found and connected.intersection((m['i'],m['j']))}
        if not added: break
        found.update(added)
        for mid in added: connected.update((members[mid]['i'],members[mid]['j']))
    def position(mid):
        return min(sum((v-o)*a for v,o,a in zip(nodes[members[mid][end]],origin,axis)) for end in ('i','j'))
    return sorted(found,key=lambda mid:(position(mid),mid))
