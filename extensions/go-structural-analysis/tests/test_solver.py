import copy
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
import pytest
ROOT=Path(__file__).parents[1]
sys.path.insert(0,str(ROOT/'go_structural_analysis'))
from model import benchmark, validate, ModelError
from worker import solve
from client import analyze

def test_udl_closed_form():
    d=benchmark(); r=solve(d)['cases']['LC1']; mid=r['members']['B1']['samples'][30]
    assert r['nodes']['N1']['Rz']==pytest.approx(30,abs=1e-8)
    assert r['nodes']['N2']['Rz']==pytest.approx(30,abs=1e-8)
    assert abs(mid['M'])==pytest.approx(45,abs=1e-8)
    theory=5*10*6**4/(384*200000000*0.00008)
    assert abs(mid['d'])==pytest.approx(theory,rel=1e-8)
    assert mid['uz']==pytest.approx(-theory,rel=1e-8)

def test_cantilever_point_load():
    d=benchmark(); d['nodes'][0]['support']='Fixed'; d['nodes'][1]['support']='Free'; d['distributed_loads']=[]
    d['point_loads']=[{'node':'N2','direction':'FZ','value':-10,'case':'LC1'}]
    r=solve(d)['cases']['LC1']; assert r['nodes']['N1']['Rz']==pytest.approx(10)
    assert abs(r['nodes']['N1']['My'])==pytest.approx(60)
    assert r['nodes']['N2']['uz']==pytest.approx(-10*6**3/(3*200000000*0.00008))

def test_frame_multi_case_and_selfweight():
    d=benchmark(); d['members'][0]['type']='Frame'; d['cases'].append('LC2'); d['self_weight']=True
    r=solve(d)['cases']; assert sum(n['Rz'] for n in r['LC2']['nodes'].values())==pytest.approx(76.98*0.01*6)
    assert sum(n['Rz'] for n in r['LC1']['nodes'].values())==pytest.approx(60+76.98*0.01*6)

def test_member_point_load():
    d=benchmark(); d['distributed_loads']=[]
    d['point_loads']=[{'member':'B1','direction':'FZ','value':-20,'x':3,'case':'LC1'}]
    r=solve(d)['cases']['LC1']; p=r['members']['B1']['samples'][30]
    assert r['nodes']['N1']['Rz']==pytest.approx(10)
    assert abs(p['M'])==pytest.approx(30)
    assert p['uz']==pytest.approx(-20*6**3/(48*200000000*0.00008))

def test_inclined_frame_equilibrium():
    d=benchmark(); d['nodes'][0]['support']='Fixed'; d['nodes'][1].update(z=4,support='Free'); d['distributed_loads']=[]
    d['members'][0]['type']='Frame'; d['point_loads']=[{'node':'N2','direction':'FX','value':5,'case':'LC1'},{'node':'N2','direction':'FZ','value':-10,'case':'LC1'}]
    r=solve(d)['cases']['LC1']; n=r['nodes']['N1']
    assert n['Rx']==pytest.approx(-5); assert n['Rz']==pytest.approx(10); assert abs(n['My'])==pytest.approx(80)
    end=r['members']['B1']['samples'][-1]
    assert end['ux']==pytest.approx(r['nodes']['N2']['ux']); assert end['uz']==pytest.approx(r['nodes']['N2']['uz'])

def test_truss():
    d=benchmark(); d['nodes'].append({'id':'N3','x':3,'z':3,'support':'Free'}); d['distributed_loads']=[]
    base=d['members'][0]; base['type']='Truss'
    d['members'] += [dict(base,id='T2',i='N1',j='N3'),dict(base,id='T3',i='N3',j='N2')]
    d['point_loads']=[{'node':'N3','direction':'FZ','value':-10,'case':'LC1'}]
    r=solve(d)['cases']['LC1']; assert r['nodes']['N1']['Rz']==pytest.approx(5); assert r['nodes']['N2']['Rz']==pytest.approx(5)
    assert all(abs(p['M'])<1e-7 for m in r['members'].values() for p in m['samples'])

@pytest.mark.parametrize('mutation',[
 lambda d:d['nodes'].append(copy.deepcopy(d['nodes'][0])),
 lambda d:d['sections'][0].update(A=-1),
 lambda d:d['materials'][0].update(E=float('nan')),
 lambda d:d['members'][0].update(i='Missing'),
 lambda d:d['distributed_loads'][0].update(x2=7),
 lambda d:d.update(schema=99),
 lambda d:d['members'][0].update(type='Truss')])
def test_invalid(mutation):
    d=benchmark(); mutation(d)
    with pytest.raises(ModelError): validate(d)

def test_unstable():
    d=benchmark()
    for n in d['nodes']: n['support']='Free'
    with pytest.raises(Exception): solve(d)

def test_json_worker():
    r=analyze(benchmark(),sys.executable); assert r['solver']=='PyNiteFEA'

def test_worker_invalid_protocol():
    p=subprocess.run([sys.executable,str(ROOT/'go_structural_analysis'/'worker.py')],input='{"protocol":9}',text=True,capture_output=True)
    r=json.loads(p.stdout); assert not r['ok']; assert p.returncode==1

def test_missing_runtime():
    with pytest.raises(RuntimeError,match='missing'): analyze(benchmark(),'Z:/missing/python.exe')

def test_timeout():
    with pytest.raises(RuntimeError,match='timeout'): analyze(benchmark(),sys.executable,timeout=0.001)

def test_schema_roundtrip():
    d=benchmark(); assert validate(json.loads(json.dumps(d)))==d
