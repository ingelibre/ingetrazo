"""One request on stdin, one response on stdout. No Qt or host imports."""
import contextlib
import io
import json
import sys
import traceback
from pathlib import Path
if __package__:
    from .model import validate
    from .results import model_hash
    from .solver_results import extract_member,equilibrium,check_stiffness
else:
    sys.path.insert(0,str(Path(__file__).parent))
    from model import validate
    from results import model_hash
    from solver_results import extract_member,equilibrium,check_stiffness

def solve(data):
    if isinstance(data,dict) and data.get('schema')==2:
        if __package__: from .solver3d import solve3d
        else: from solver3d import solve3d
        return solve3d(data)
    from Pynite import FEModel3D
    from importlib.metadata import version
    if version('PyNiteFEA')!='3.2.0': raise RuntimeError('Solver must be PyNiteFEA 3.2.0')
    import numpy as np
    d=validate(data); f=FEModel3D()
    # host X,Z -> solver X,Y; solver Z is out of plane. Iz governs 2D bending.
    directions={'FX':'FX','FZ':'FY','MY':'MZ'}
    truss_nodes={n['id'] for n in d['nodes'] if all(m['type']=='Truss' or m.get('release_i' if n['id']==m['i'] else 'release_j',False) for m in d['members'] if n['id'] in (m['i'],m['j']))}
    for n in d['nodes']:
        f.add_node(n['id'],n['x'],n['z'],0)
        s=n.get('support','Free')
        f.def_support(n['id'],s in ['Fixed','Pin','RollerX'],s in ['Fixed','Pin','Roller'],True,True,True,s=='Fixed' or n['id'] in truss_nodes)
    for m in d['materials']: f.add_material(m['id'],m['E'],m['G'],m.get('nu',0.3),m.get('rho',0))
    for s in d['sections']: f.add_section(s['id'],s['A'],s['Iy'],s['Iz'],s['J'])
    for m in d['members']:
        f.add_member(m['id'],m['i'],m['j'],m['material'],m['section'])
        f.def_releases(m['id'],Rzi=m['type']=='Truss' or m.get('release_i',False),Rzj=m['type']=='Truss' or m.get('release_j',False))
    for c in d['cases']: f.add_load_combo(c,{c:1.0})
    for c,factors in d.get('combinations',{}).items(): f.add_load_combo(c,factors)
    for p in d.get('point_loads',[]):
        if 'node' in p: f.add_node_load(p['node'],directions[p['direction']],p['value'],p['case'])
        else: f.add_member_pt_load(p['member'],directions[p['direction']],p['value'],p['x'],p['case'])
    for p in d.get('distributed_loads',[]):
        f.add_member_dist_load(p['member'],directions[p['direction']],p['w1'],p['w2'],p.get('x1',0),p.get('x2'),p['case'])
    if d.get('self_weight',False):
        materials={m['id']:m for m in d['materials']}; sections={s['id']:s for s in d['sections']}
        nodes={n['id']:n for n in d['nodes']}
        for c in ([d['self_weight_case']] if d.get('self_weight_case') else d['cases']):
            for m in d['members']:
                if m['type']=='Truss':
                    a,b=nodes[m['i']],nodes[m['j']]
                    weight=materials[m['material']].get('rho',0)*sections[m['section']]['A']*((b['x']-a['x'])**2+(b['z']-a['z'])**2)**0.5
                    for n in (m['i'],m['j']): f.add_node_load(n,'FY',-weight/2,c)
                else:
                    weight=materials[m['material']].get('rho',0)*sections[m['section']]['A']
                    f.add_member_dist_load(m['id'],'FY',-weight,-weight,case=c)
    f.analyze_linear(check_stability=True,check_statics=True)
    check_stiffness(f,d['cases'][0])
    result={'solver':'PyNiteFEA','version':version('PyNiteFEA'),'extension_version':'0.2.4','result_schema':2,'model_hash':model_hash(d),'units':'m,kN','cases':{}}
    for c in list(d['cases'])+list(d.get('combinations',{})):
        nodes={n:{'ux':float(v.DX[c]),'uz':float(v.DY[c]),'rotation':float(v.RZ[c]),'Rx':float(v.RxnFX[c]),'Rz':float(v.RxnFY[c]),'My':float(v.RxnMZ[c])} for n,v in f.nodes.items()}
        members={}
        for mid,m in f.members.items():
            samples=[]; rotation=m.T()[:3,:3]
            for x in np.linspace(0,m.L(),61):
                local=np.array([m.deflection('dx',x,c),m.deflection('dy',x,c),m.deflection('dz',x,c)])
                global_d=rotation.T@local
                samples.append({'x':float(x),'N':float(m.axial(x,c)),'V':float(m.shear('Fy',x,c)),'M':float(m.moment('Mz',x,c)),
                                'd':float(m.deflection('dy',x,c)),'ux':float(global_d[0]),'uz':float(global_d[1])})
            members[mid]=extract_member(m,c); members[mid]['samples']=samples
        balance=equilibrium(d,nodes,c)
        if not balance['passed']: raise RuntimeError(f'Equilibrium verification failed in {c}: residual {balance["residual"]}; structure may be unstable or numerically ill-conditioned')
        result['cases'][c]={'nodes':nodes,'members':members,'equilibrium':balance}
    json.dumps(result,allow_nan=False)
    if __package__: from .safety import seal,envelope_groups
    else: from safety import seal,envelope_groups
    return seal(d,envelope_groups(result,d))

def main():
    try:
        request=json.load(sys.stdin)
        if request.get('protocol')!=1: raise ValueError('Unsupported worker protocol')
        with contextlib.redirect_stdout(io.StringIO()): result=solve(request['model'])
        reply={'protocol':1,'ok':True,'result':result}
    except Exception as exc:
        traceback.print_exc(file=sys.stderr)
        reply={'protocol':1,'ok':False,'error':{'type':type(exc).__name__,'message':str(exc)}}
    print(json.dumps(reply,allow_nan=False))
    return 0 if reply['ok'] else 1

if __name__=='__main__': sys.exit(main())
