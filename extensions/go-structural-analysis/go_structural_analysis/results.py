"""Solver-independent exact result evaluation, freshness, hit tests and CSV."""
import csv
import hashlib
import json
import math
from pathlib import Path

VERSION='0.2.4'
UNITS={'N':'kN','V':'kN','M':'kN.m','d':'m','ux':'m','uz':'m'}
UNITS.update(Vy='kN',Vz='kN',T='kN.m',My='kN.m',Mz='kN.m',dy='m',dz='m',u='m',D='m',uy='m')

def model_hash(model):
    return hashlib.sha256(json.dumps(model,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()

def is_current(model,result):
    if __package__: from .safety import current
    else: from safety import current
    return current(model,result)

def polynomial(coeff,x):
    value=0.0
    for c in reversed(coeff): value=value*x+c
    return value

def evaluate(member,x,side='right'):
    if side not in ('left','right'): raise ValueError('Inspector side must be left or right')
    L=member['L']
    if not math.isfinite(x) or x < -1e-10 or x>L+1e-10: raise ValueError('Inspector x outside member')
    x=max(0.,min(L,float(x))); segments=member['segments']
    matches=[s for s in segments if s['x1']-1e-10<=x<=s['x2']+1e-10]
    if not matches: raise ValueError('Missing result segment')
    s=matches[0] if side=='left' else matches[-1]; t=max(0.,min(s['x2']-s['x1'],x-s['x1']))
    out={key:polynomial(c,t) for key,c in s['coefficients'].items()}; out['x']=x
    if len(member['basis'])==3:
        displacement=[sum(member['basis'][i][j]*out[k] for i,k in enumerate(('u','dy','dz'))) for j in range(3)]
        out.update(zip(('ux','uy','uz'),displacement)); out['D']=math.sqrt(sum(v*v for v in displacement))
        return out
    bx,by=member['basis'][0],member['basis'][1]
    out['ux']=bx[0]*out['u']+by[0]*out['d']; out['uz']=bx[1]*out['u']+by[1]*out['d']
    return out

def distance_to_segment(px,py,a,b):
    dx=b[0]-a[0]; dy=b[1]-a[1]; denom=dx*dx+dy*dy
    t=max(0.,min(1.,((px-a[0])*dx+(py-a[1])*dy)/denom)) if denom else 0.
    return math.hypot(px-a[0]-t*dx,py-a[1]-t*dy),t

def pick_member(px,py,projected,tolerance=9):
    hits=[]
    for mid,a,b in projected:
        distance,t=distance_to_segment(px,py,a,b)
        if distance<=tolerance: hits.append((distance,mid,t))
    return min(hits,key=lambda h:h[0])[1:] if hits else None

def _export_csv(directory,model,result,case):
    if not is_current(model,result): raise ValueError('Results out of date; Run Analysis before exporting')
    if case not in result['cases']: raise ValueError('Unknown load case')
    if model.get('schema')==2:
        root=Path(directory); root.mkdir(parents=True,exist_ok=True); paths=[]
        for name,(headers,rows) in tables3d(model,result,case).items():
            path=root/(name.lower().replace(' / ','_').replace(' ','_')+'.csv')
            with path.open('w',encoding='utf-8-sig',newline='') as stream:
                writer=csv.writer(stream); writer.writerow(['Case / Envelope']+headers); writer.writerows([[case]+row for row in rows])
            paths.append(str(path))
        return paths
    root=Path(directory); root.mkdir(parents=True,exist_ok=True); r=result['cases'][case]; paths=[]
    def write(name,headers,rows):
        path=root/(name+'.csv')
        with path.open('w',encoding='utf-8-sig',newline='') as stream:
            writer=csv.writer(stream); writer.writerow(headers); writer.writerows(rows)
        paths.append(str(path))
    write('node_displacements',['Case','Node','UX [m]','UZ [m]','Rotation [rad]'],[[case,n,v['ux'],v['uz'],v['rotation']] for n,v in r['nodes'].items()])
    supports={n['id'] for n in model['nodes'] if n.get('support','Free')!='Free'}
    write('support_reactions',['Case','Node','RX [kN]','RZ [kN]','M_plane [kN.m]'],[[case,n,v['Rx'],v['Rz'],v['My']] for n,v in r['nodes'].items() if n in supports])
    write('member_end_forces',['Case','Member','End','FX_local [kN]','FY_local [kN]','MZ_local [kN.m]'],[[case,mid,end,v['N'],v['V'],v['M']] for mid,m in r['members'].items() for end,v in m['end_forces'].items()])
    write('member_extrema',['Case','Member','Quantity','Unit','Extremum','x [m]','x/L [-]','Side','Value'],[[case,mid,k,UNITS[k],kind,v['x'],v['x']/m['L'],v['side'],v['value']] for mid,m in r['members'].items() for k,e in m['extrema'].items() for kind,v in e.items()])
    write('member_diagrams',['Case','Member','x [m]','Side','N [kN]','V [kN]','M [kN.m]','D_local [m]','UX [m]','UZ [m]'],[[case,mid,p['x'],p.get('side','right'),p['N'],p['V'],p['M'],p['d'],p['ux'],p['uz']] for mid,m in r['members'].items() for p in m['plot']])
    return paths

def tables3d(model,result,case):
    r=result['cases'][case]; dofs=('ux','uy','uz','rx','ry','rz'); reactions=('Fx','Fy','Fz','Mx','My','Mz'); forces=('N','Vy','Vz','T','My','Mz')
    supports={n['id'] for n in model['nodes'] if n.get('support','Free')!='Free' or n.get('restraints') or n.get('springs')}
    out={
        'Node Displacements':(['Node']+[k.upper()+(' [m]' if k.startswith('u') else ' [rad]') for k in dofs]+['Magnitude [m]'],[[n]+[v[k] for k in dofs]+[v['D']] for n,v in r['nodes'].items()]),
        'Support Reactions':(['Node']+[k+(' [kN]' if k.startswith('F') else ' [kN.m]') for k in reactions],[[n]+[v[k] for k in reactions] for n,v in r['nodes'].items() if n in supports]),
        'Member End Forces':(['Member','End']+[k+' ['+UNITS[k]+']' for k in forces],[[mid,end]+[v[k] for k in forces] for mid,m in r['members'].items() for end,v in m['end_forces'].items()]),
        'Max / Min':(['Member','Quantity','Unit','Type','Value','x [m]','x/L','Side'],[[mid,k,UNITS[k],kind,v['value'],v['x'],v['x']/m['L'],v['side']] for mid,m in r['members'].items() for k,e in m['extrema'].items() for kind,v in e.items()]),
        'Member Force Envelope':(['Member','Quantity','Unit','Type','Value','x [m]','Side','Governing combination'],[[mid,k,UNITS[k],kind,v['value'],v['x'],v['side'],v['combination']] for mid,m in result['envelope']['members'].items() for k,e in m.items() for kind,v in e.items()]),
        'Member Diagrams':(['Member','x [m]','Side']+[k+' ['+UNITS[k]+']' for k in forces+('ux','uy','uz','D')],[[mid,p['x'],p['side']]+[p[k] for k in forces+('ux','uy','uz','D')] for mid,m in r['members'].items() for p in m['plot']])}
    return out

def export_csv(directory,model,result,case,archived=False):
    if __package__: from .safety import ensure_exportable
    else: from safety import ensure_exportable
    snapshot=ensure_exportable(model,result,archived)
    export_result=result
    if archived:
        export_result=dict(result,safety=dict(result.get('safety',{}),invalidated_by_failure=False,running=False))
    paths=_export_csv(directory,snapshot,export_result,case)
    status='Archived/Stale' if archived else 'Current'
    if archived:
        changed=[]
        for name in paths:
            p=Path(name)
            with p.open(encoding='utf-8-sig',newline='') as stream: rows=list(csv.reader(stream))
            p.replace(p.with_name('ARCHIVED_'+p.name)); p=p.with_name('ARCHIVED_'+p.name)
            with p.open('w',encoding='utf-8-sig',newline='') as stream:
                writer=csv.writer(stream); writer.writerow(['Result Status','Input Fingerprint']+rows[0])
                writer.writerows([[status,result['model_hash']]+row for row in rows[1:]])
            changed.append(str(p))
        paths=changed
    Path(directory,'ARCHIVED_metadata.json' if archived else 'results_metadata.json').write_text(json.dumps(dict(status=status,input_fingerprint=result['model_hash'],solver=result['version'],capacity='Not Available',code_compliance='Not Available'),indent=2),encoding='utf-8')
    return paths

def export_report(path,model,result,archived=False):
    if __package__: from .safety import ensure_exportable
    else: from safety import ensure_exportable
    snapshot=ensure_exportable(model,result,archived)
    report=dict(title='Engineering Analysis Report',status='Archived/Stale' if archived else 'Current',
        input_fingerprint=result['model_hash'],input_model=snapshot,results=result,
        capacity='Not Available',code_compliance='Not Available',serviceability='Not Available')
    Path(path).write_text(json.dumps(report,indent=2,allow_nan=False),encoding='utf-8')
    return str(path)
