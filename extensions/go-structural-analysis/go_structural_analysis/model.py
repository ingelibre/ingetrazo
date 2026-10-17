"""JSON schema and validation. Units: m, kN, kN/m2, m2, m4."""
import json
import math

class ModelError(ValueError):
    pass

def benchmark():
    return {'schema':1,'self_weight':False,'nodes':[{'id':'N1','x':0.,'z':0.,'support':'Pin'},{'id':'N2','x':6.,'z':0.,'support':'Roller'}],
            'materials':[{'id':'Steel','E':200000000.,'G':76923076.923,'nu':0.3,'rho':76.98}],
            'sections':[{'id':'S1','A':0.01,'Iy':0.00008,'Iz':0.00008,'J':0.00001}],
            'members':[{'id':'B1','i':'N1','j':'N2','type':'Beam','material':'Steel','section':'S1'}],
            'cases':['LC1'],'point_loads':[], 'distributed_loads':[{'member':'B1','direction':'FZ','w1':-10.,'w2':-10.,'case':'LC1'}]}

def validate(data):
    if __package__: from .thai_code import validate_combinations
    else: from thai_code import validate_combinations
    try: validate_combinations(data)
    except (ValueError,KeyError,TypeError) as exc: raise ModelError(str(exc)) from exc
    if isinstance(data,dict) and data.get('schema')==2:
        if __package__: from .model3d import validate3d
        else: from model3d import validate3d
        return validate3d(data)
    try:
        d=json.loads(json.dumps(data,allow_nan=False))
        if d.get('schema')!=1: raise ModelError('Unsupported schema; expected 1')
        if not isinstance(d.get('self_weight',False),bool): raise ModelError('self_weight must be boolean')
        registries={}
        def num(value,label,positive=False):
            if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or (positive and value<=0):
                raise ModelError(f'{label}: expected finite '+('positive ' if positive else '')+'number')
        for key in ['nodes','members','materials','sections']:
            rows=d[key]; ids=[r['id'] for r in rows]
            if len(ids)!=len(set(ids)) or any(not isinstance(i,str) or not i for i in ids): raise ModelError(f'{key}: duplicate/invalid IDs')
            registries[key]={r['id']:r for r in rows}
        if not d['nodes'] or not d['members']: raise ModelError('At least two nodes and one member required')
        cases=d['cases']
        if not cases or len(cases)!=len(set(cases)) or any(not isinstance(c,str) or not c for c in cases): raise ModelError('Invalid load cases')
        for n in d['nodes']:
            num(n['x'],'x'); num(n['z'],'z')
            if n.get('support','Free') not in ['Free','Fixed','Pin','Roller','RollerX']: raise ModelError('Unknown support')
        positions=[(n['x'],n['z']) for n in d['nodes']]
        if len(positions)!=len(set(positions)): raise ModelError('Coincident nodes; merge them explicitly')
        for m in d['materials']:
            for k in ['E','G']: num(m[k],k,True)
            num(m.get('rho',0),'rho')
            num(m.get('nu',0.3),'nu')
            if not -1<m.get('nu',0.3)<0.5 or m.get('rho',0)<0: raise ModelError('Invalid nu/rho')
        for s in d['sections']:
            for k in ['A','Iy','Iz','J']: num(s[k],k,True)
        lengths={}
        for m in d['members']:
            if m['type'] not in ['Beam','Frame','Truss']: raise ModelError('Unknown member type')
            for key in ('release_i','release_j'):
                if key in m and not isinstance(m[key],bool): raise ModelError('Member releases must be boolean')
            a,b=registries['nodes'][m['i']],registries['nodes'][m['j']]
            registries['materials'][m['material']]; registries['sections'][m['section']]
            lengths[m['id']]=math.hypot(b['x']-a['x'],b['z']-a['z'])
            if lengths[m['id']]<1e-8: raise ModelError('Zero length member')
        for p in d.get('point_loads',[]):
            if ('node' in p)==('member' in p): raise ModelError('Point load needs exactly one node or member target')
            if p['case'] not in cases or p['direction'] not in ['FX','FZ','MY']: raise ModelError('Invalid point load case/direction')
            num(p['value'],'point load')
            if 'node' in p:
                node=registries['nodes'][p['node']]
                incident=[m for m in d['members'] if p['node'] in (m['i'],m['j'])]
                if p['direction']=='MY' and p['value']!=0 and node.get('support','Free')!='Fixed' and all(m['type']=='Truss' or m.get('release_i' if p['node']==m['i'] else 'release_j',False) for m in incident):
                    raise ModelError('Nodal moment at a fully released rotation cannot be transmitted')
            else:
                L=lengths[p['member']]; num(p['x'],'load position')
                if not 0<=p['x']<=L: raise ModelError('Point load outside member')
                if registries['members'][p['member']]['type']=='Truss': raise ModelError('Apply truss loads at nodes')
        for p in d.get('distributed_loads',[]):
            L=lengths[p['member']]
            if p['case'] not in cases or p['direction'] not in ['FX','FZ']: raise ModelError('Invalid distributed load case/direction')
            for k in ['w1','w2']: num(p[k],k)
            for v in [p.get('x1',0),p.get('x2',L)]: num(v,'load extent')
            if not 0<=p.get('x1',0)<p.get('x2',L)<=L: raise ModelError('Invalid distributed load extent')
            if registries['members'][p['member']]['type']=='Truss': raise ModelError('Apply truss loads at nodes')
        return d
    except (KeyError,TypeError,ValueError) as exc:
        if isinstance(exc,ModelError): raise
        raise ModelError(f'Invalid model: {exc}') from exc
