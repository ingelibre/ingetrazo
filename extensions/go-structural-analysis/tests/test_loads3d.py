import copy
import csv
import sys
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).parents[1]/'go_structural_analysis'))
from model3d import cantilever3d
from model import validate,ModelError
from worker import solve
from results import evaluate,export_csv,is_current

def test_combinations_superposition_and_governing_envelope():
    d=cantilever3d(); d['combinations']={'ULS':{'DL':1.4,'LL':1.7},'Reverse':{'DL':-.8,'LL':-2}}
    result=solve(d)
    for case,factors in d['combinations'].items():
        for n in ('N1','N2'):
            for key in ('ux','uy','uz','rx','ry','rz','Fx','Fy','Fz','Mx','My','Mz'):
                ref=sum(factor*result['cases'][c]['nodes'][n][key] for c,factor in factors.items())
                assert result['cases'][case]['nodes'][n][key]==pytest.approx(ref,abs=1e-10)
        for x in (0,1.371,4):
            combined=evaluate(result['cases'][case]['members']['B1'],x)
            for key in ('N','Vy','Vz','T','My','Mz','u','dy','dz'):
                assert combined[key]==pytest.approx(sum(factor*evaluate(result['cases'][c]['members']['B1'],x)[key] for c,factor in factors.items()),abs=1e-9)
    e=result['envelope']['members']['B1']['My']
    assert {e['min']['combination'],e['max']['combination']}=={'ULS','Reverse'}

def test_selfweight_only_dl_and_not_double_in_combo():
    d=cantilever3d(); d.update(self_weight=True,combinations={'C':{'DL':1.4,'LL':1.7}},point_loads=[])
    result=solve(d); weight=76.98*.01*4
    assert result['cases']['DL']['nodes']['N1']['Fz']==pytest.approx(weight)
    assert result['cases']['LL']['nodes']['N1']['Fz']==pytest.approx(0,abs=1e-12)
    assert result['cases']['C']['nodes']['N1']['Fz']==pytest.approx(1.4*weight)
    d['self_weight']=False; assert solve(d)['cases']['DL']['nodes']['N1']['Fz']==0

def test_mass_density_selfweight():
    d=cantilever3d(); d.update(self_weight=True,point_loads=[]); d['materials'][0].pop('rho'); d['materials'][0]['mass_density']=1000
    assert solve(d)['cases']['DL']['nodes']['N1']['Fz']==pytest.approx(9.80665*.01*4)

@pytest.mark.parametrize('direction', ['Fx','Fy','Fz','MX','MY','MZ'])
def test_rotated_member_point_local_global_equilibrium(direction):
    d=cantilever3d(); d['nodes'][1].update(x=3,y=2,z=4); d['members'][0]['rotation']=33
    d['point_loads']=[dict(member='B1',direction=direction,value=7,x=2.173,case='DL')]
    r=solve(d)['cases']['DL']; assert r['equilibrium']['passed']
    # Moment/force discontinuities are evaluated one-sided at the exact point.
    assert len(r['members']['B1']['segments'])==2

@pytest.mark.parametrize('direction', ['Fx','Fy','Fz','FX','FY','FZ'])
def test_varying_local_global_distributed_equilibrium(direction):
    d=cantilever3d(); d['nodes'][1].update(x=3,y=2,z=4); d['members'][0]['rotation']=67; d['point_loads']=[]
    d['distributed_loads']=[dict(member='B1',direction=direction,w1=3,w2=-7,x1=.13,x2=4.7,case='DL')]
    assert solve(d)['cases']['DL']['equilibrium']['passed']

def test_selfweight_guard_and_csv(tmp_path):
    d=cantilever3d(); d['self_weight']=True; d['distributed_loads']=[dict(member='B1',direction='FZ',w1=-1,w2=-1,case='DL',source='self_weight')]
    with pytest.raises(ModelError,match='already explicit'): validate(d)
    d['distributed_loads']=[]; r=solve(d); paths=export_csv(tmp_path,d,r,'DL'); assert len(paths)==6
    with open(paths[0],encoding='utf-8-sig') as stream: assert 'UY [m]' in next(csv.reader(stream))
    d['nodes'][1]['y']=1
    assert not is_current(d,r)
    with pytest.raises(ValueError,match='out of date'): export_csv(tmp_path,d,r,'DL')
