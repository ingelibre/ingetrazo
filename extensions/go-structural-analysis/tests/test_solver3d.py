import copy
import math
import sys
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).parents[1]/'go_structural_analysis'))
from model3d import cantilever3d,migrate2d
from model import benchmark
from worker import solve
from results import evaluate
from client import analyze
import importlib.util

@pytest.mark.parametrize('direction,displacement,expected',[
    ('FX','ux',10*4/(200e6*.01)),
    ('FY','uy',10*4**3/(3*200e6*.00008)),
    ('FZ','uz',10*4**3/(3*200e6*.00008)),
    ('MX','rx',10*4/(76923076.923*.00001)),
    ('MY','ry',10*4/(200e6*.00008)),
    ('MZ','rz',10*4/(200e6*.00008))])
def test_cantilever_six_dof(direction,displacement,expected):
    d=cantilever3d(); d['point_loads']=[dict(node='N2',direction=direction,value=10,case='DL')]
    r=solve(d)['cases']['DL']
    assert r['nodes']['N2'][displacement]==pytest.approx(expected,rel=1e-9,abs=1e-12)
    assert r['equilibrium']['passed']
    assert evaluate(r['members']['B1'],4)['D']==pytest.approx(r['nodes']['N2']['D'],abs=1e-12)

def test_migrated_udl_matches_legacy():
    d=benchmark(); old=solve(d)['cases']['LC1']; new=solve(migrate2d(d))['cases']['LC1']
    for node in old['nodes']:
        for key in ('ux','uz'): assert new['nodes'][node][key]==pytest.approx(old['nodes'][node][key],abs=1e-11)
        assert new['nodes'][node]['Fz']==pytest.approx(old['nodes'][node]['Rz'])
    for x in (0,1.37,3,5.21,6):
        a=evaluate(old['members']['B1'],x); b=evaluate(new['members']['B1'],x)
        for legacy,k in [('N','N'),('V','Vy'),('M','Mz'),('d','dy')]: assert b[k]==pytest.approx(a[legacy],abs=1e-9)

def test_unloaded_translational_mechanism_rejected():
    d=cantilever3d(); d['nodes'][0]['support']='Pin'; d['point_loads']=[]
    with pytest.raises(Exception,match='[Ss]ingular|[Ss]tability|unstable'): solve(d)

def test_worker_protocol3d():
    r=analyze(cantilever3d(),python=sys.executable)
    assert r['result_schema']==3 and r['version']=='3.2.0'

def test_spring_axial_closed_form():
    d=cantilever3d(); d['nodes'][0].update(support='Custom',restraints=['UY','UZ','RX','RY','RZ'],springs={'UX':1000})
    d['point_loads']=[dict(node='N2',direction='FX',value=10,case='DL')]
    r=solve(d)['cases']['DL']; assert r['nodes']['N2']['ux']==pytest.approx(.01+10*4/(200e6*.01))
    assert r['nodes']['N1']['Fx']==pytest.approx(-10)

def test_all_legacy_example_migrations():
    path=Path(__file__).parents[1]/'go_structural_analysis/examples.py'
    spec=importlib.util.spec_from_file_location('legacy_examples',path); module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    for key,_,_ in module.CATALOG:
        if key.startswith('unstable'): continue
        d=module.example(key)
        try: old=solve(d)
        except Exception:
            with pytest.raises(Exception): solve(migrate2d(d))
            continue
        new=solve(migrate2d(d))
        for case in d['cases']:
            for node in old['cases'][case]['nodes']:
                a,b=old['cases'][case]['nodes'][node],new['cases'][case]['nodes'][node]
                for old_key,new_key,sign in (('ux','ux',1),('uz','uz',1),('rotation','ry',-1),('Rx','Fx',1),('Rz','Fz',1),('My','My',-1)):
                    assert b[new_key]==pytest.approx(sign*a[old_key],rel=1e-7,abs=1e-8),key+' '+case+' '+node+' '+old_key
