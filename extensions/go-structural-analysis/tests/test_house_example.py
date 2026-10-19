import copy
import math
from pathlib import Path
import sys
import pytest

ROOT=Path(__file__).parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'go_structural_analysis'))
from go_structural_analysis.house_example import house_model,rectangle
from go_structural_analysis.examples3d import example3d
from go_structural_analysis.model3d import validate3d
from worker import solve
from reference3d import reference3d

def test_geometry_connected_and_editable():
    sec=rectangle('B',.2,.4)
    assert sec['Iz']==pytest.approx(.2*.4**3/12)
    assert sec['Iy']==pytest.approx(.4*.2**3/12)
    d=validate3d(house_model())
    assert len([n for n in d['nodes'] if n['support']=='Fixed'])==12
    assert {m['material'] for m in d['members']}=={'Concrete','Steel'}
    assert max(n['z'] for n in d['nodes'])==8.7
    adjacency={n['id']:set() for n in d['nodes']}
    for m in d['members']:
        adjacency[m['i']].add(m['j']); adjacency[m['j']].add(m['i'])
    reached=set(); todo=[d['nodes'][0]['id']]
    while todo:
        node=todo.pop()
        if node in reached: continue
        reached.add(node); todo.extend(adjacency[node]-reached)
    assert len(reached)==len(d['nodes'])
    d['nodes'][0]['x']=99
    assert example3d('3d_house_phetnaray')['nodes'][0]['x']!=99

@pytest.fixture(scope='module')
def analyzed():
    d=house_model()
    return d,solve(d)

def test_all_cases_equilibrium_selfweight_and_superposition(analyzed):
    d,r=analyzed
    assert set(r['cases'])==set(d['cases'])|set(d['combinations'])
    assert all(c['equilibrium']['passed'] for c in r['cases'].values())
    ns={n['id']:n for n in d['nodes']}
    mats={m['id']:m for m in d['materials']}; secs={s['id']:s for s in d['sections']}
    weight=sum(mats[m['material']]['rho']*secs[m['section']]['A']*
        math.dist([ns[m['i']][k] for k in ('x','y','z')],[ns[m['j']][k] for k in ('x','y','z')]) for m in d['members'])
    extra=-sum(p['value'] for p in d['point_loads'] if p['case']=='DL' and p['direction']=='FZ')
    reaction=sum(n['Fz'] for n in r['cases']['DL']['nodes'].values())
    assert reaction==pytest.approx(weight+extra,rel=1e-7,abs=1e-7)
    for nid,values in r['cases']['DEMO Gravity']['nodes'].items():
        for component in ('ux','uy','uz','rx','ry','rz','Fx','Fy','Fz','Mx','My','Mz'):
            assert values[component]==pytest.approx(sum(r['cases'][c]['nodes'][nid][component] for c in ('DL','LL','RL')),rel=1e-6,abs=1e-7)

def test_independent_space_frame_reference():
    d=house_model(); d['self_weight']=False
    r=solve(d); reference,_=reference3d(d,'LL')
    for nid,values in reference.items():
        for component,value in values.items():
            assert r['cases']['LL']['nodes'][nid][component]==pytest.approx(value,rel=1e-6,abs=1e-7)
