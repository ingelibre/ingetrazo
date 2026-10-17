import sys
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).parents[1]/'go_structural_analysis'))
from worker import solve
from model3d import cantilever3d

def test_truss_joint_rotational_spring_can_carry_nodal_moment():
    d=cantilever3d(); d['members'][0]['type']='Truss'; d['nodes'][1].update(support='Custom',restraints=['UY','UZ'],springs={'RX':200})
    d['point_loads']=[dict(node='N2',direction='MX',value=10,case='DL')]
    r=solve(d)['cases']['DL']; assert r['nodes']['N2']['rx']==pytest.approx(.05)
    assert r['nodes']['N2']['Mx']==pytest.approx(-10)

def test_truss_joint_moment_without_restraint_rejected():
    d=cantilever3d(); d['members'][0]['type']='Truss'; d['nodes'][1].update(support='Custom',restraints=['UY','UZ'])
    d['point_loads']=[dict(node='N2',direction='MX',value=10,case='DL')]
    with pytest.raises(Exception,match='cannot be transmitted'): solve(d)
