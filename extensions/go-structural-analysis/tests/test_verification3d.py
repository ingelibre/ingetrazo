import copy
import importlib.util
import json
import math
from pathlib import Path
import sys
import numpy as np
import pytest
ROOT=Path(__file__).parents[1]; sys.path.insert(0,str(ROOT/'go_structural_analysis'))
# Load examples without importing the Qt-dependent plugin entry point.
import types
if 'go_test_examples' not in sys.modules:
    package=types.ModuleType('go_test_examples'); package.__path__=[str(ROOT/'go_structural_analysis')]; sys.modules['go_test_examples']=package
from go_test_examples.examples3d import example3d,CATALOG3D
from worker import solve
from results import evaluate
from reference3d import reference3d,basis
CHECKS=[]

def compare(name,actual,expected,rel=1e-7,abs_tol=1e-9):
    tol=max(abs_tol,rel*abs(expected)); error=abs(actual-expected)
    CHECKS.append(dict(name=name,actual=float(actual),reference=float(expected),absolute_error=float(error),tolerance=float(tol),status='Passed' if error<=tol else 'Failed'))
    assert error<=tol,f'{name}: {actual} vs {expected}'

@pytest.fixture(scope='module',autouse=True)
def evidence():
    yield
    root=ROOT/'artifacts'/'v0.2'; root.mkdir(parents=True,exist_ok=True)
    (root/'engineering-checks.json').write_text(json.dumps(CHECKS,indent=2),encoding='utf-8')

@pytest.mark.parametrize('key',[c[0] for c in CATALOG3D])
def test_all_benchmarks(key):
    d=example3d(key)
    if key=='3d_unstable':
        with pytest.raises(Exception,match='[Ss]ingular|[Ss]tability|unstable'): solve(d)
        return
    result=solve(d)
    for case,r in result['cases'].items():
        for label,value,tol in zip(r['equilibrium']['components'],r['equilibrium']['residual'],r['equilibrium']['tolerance']): compare(key+' '+case+' equilibrium '+label,value,0,abs_tol=tol)
    r=result['cases']['DL']; E=200e6; G=76923076.923; L=4; s=d['sections'][0]
    if key=='3d_cantilever':
        compare('Cantilever UZ PL3/3EI',r['nodes']['N2']['uz'],-15*L**3/(3*E*s['Iz']))
        compare('Cantilever UY PL3/3EI',result['cases']['LL']['nodes']['N2']['uy'],10*L**3/(3*E*s['Iy']))
    elif key=='3d_torsion':
        compare('Twist TL/GJ',r['nodes']['N2']['rx'],8*L/(G*s['J']))
        compare('Internal T negative for positive applied tip MX',evaluate(r['members']['B1'],2)['T'],-8)
    elif key=='3d_axial':
        compare('Axial PL/EA',r['nodes']['N2']['ux'],25*L/(E*s['A']))
        compare('Tension N is negative',evaluate(r['members']['B1'],2)['N'],-25)
    elif key in ('3d_portal','3d_multibay','3d_truss'):
        for case in d['cases']:
            ref,ends=reference3d(d,case)
            for node,values in ref.items():
                for k,v in values.items(): compare(key+' '+case+' '+node+' '+k,result['cases'][case]['nodes'][node][k],v)
            if key!='3d_truss':
                for mid,values in ends.items():
                    for end,offset in (('i',0),('j',6)):
                        for j,k in enumerate(('N','Vy','Vz','T','My','Mz')): compare(key+' '+case+' '+mid+' '+end+' '+k,result['cases'][case]['members'][mid]['end_forces'][end][k],values[offset+j])
            else:
                for m in d['members']:
                    a,b=[[next(n for n in d['nodes'] if n['id']==node)[k] for k in ('x','y','z')] for node in (m['i'],m['j'])]
                    direction=np.array(b,dtype=float)-a; length=np.linalg.norm(direction); direction/=length
                    du=np.array([ref[m['j']][k]-ref[m['i']][k] for k in ('ux','uy','uz')])
                    compare('Truss '+case+' '+m['id']+' axial',evaluate(result['cases'][case]['members'][m['id']],length/2)['N'],-E*s['A']/length*(direction@du))
                    for k in ('Vy','Vz','T','My','Mz'): compare('Truss '+case+' '+m['id']+' '+k,evaluate(result['cases'][case]['members'][m['id']],length/2)[k],0,abs_tol=1e-8)
    elif key=='3d_rotation':
        R=basis([0,0,0],[4,0,0],37); load=np.array([0,0,-15]); local=R@load
        displacement=R.T@np.array([0,local[1]*L**3/(3*E*s['Iz']),local[2]*L**3/(3*E*s['Iy'])])
        for k,v in zip(('ux','uy','uz'),displacement): compare('Rotated cantilever '+k,r['nodes']['N2'][k],v)
    elif key=='3d_release': compare('Released end Mz',r['members']['B1']['end_forces']['j']['Mz'],0)
    elif key=='3d_selfweight':
        compare('Self weight reaction',r['nodes']['N1']['Fz'],76.98*s['A']*L)
        compare('Self weight cantilever deflection wL4/8EI',r['nodes']['N2']['uz'],-76.98*s['A']*L**4/(8*E*s['Iz']))
        off=copy.deepcopy(d); off['self_weight']=False; compare('Self weight OFF',solve(off)['cases']['DL']['nodes']['N1']['Fz'],0)
    elif key=='3d_combo':
        for k in ('ux','uy','uz','rx','ry','rz'): compare('Combo linear '+k,result['cases']['ULS']['nodes']['N2'][k],1.4*r['nodes']['N2'][k]+1.7*result['cases']['LL']['nodes']['N2'][k])

def test_off_grid_extrema_not_sampling():
    d=example3d('3d_cantilever'); d['point_loads']=[]
    d['distributed_loads']=[dict(member='B1',direction='FZ',w1=-1,w2=3,case='DL')]
    r=solve(d)['cases']['DL']; m=r['members']['B1']; e=m['extrema']['Vy']['min']
    compare('Off-grid shear stationary point',e['x'],1,abs_tol=1e-10)
    compare('Off-grid shear derivative zero',-1+e['x'],0)
