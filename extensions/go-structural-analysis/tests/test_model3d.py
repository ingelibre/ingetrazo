import copy
import sys
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).parents[1]/'go_structural_analysis'))
from model import benchmark,validate,ModelError
from model3d import migrate2d,axes,cross,weight_density,from_lines

def test_migration_no_mutation():
    d=benchmark(); before=copy.deepcopy(d); new=migrate2d(d)
    assert d==before and new['schema']==2
    assert new['nodes'][0]['y']==0 and 'UY' in new['nodes'][0]['restraints']

@pytest.mark.parametrize('a,b,rotation', [([0,0,0],[0,0,3],0),([0,0,0],[3,2,4],37),([0,0,0],[0,3,0],90),([0,0,0],[0,0,-3],0)])
def test_right_handed_axes(a,b,rotation):
    x,y,z=axes(a,b,rotation)
    assert cross(x,y)==pytest.approx(z,abs=1e-12)
    assert sum(v*v for v in y)==pytest.approx(1)

@pytest.mark.parametrize('kind', ['duplicate','orphan','release','case','density','spring'])
def test_model_guards(kind):
    d=migrate2d(benchmark())
    if kind=='duplicate': d['nodes'][1].update(x=0)
    if kind=='orphan': d['nodes'].append(dict(id='N3',x=9,y=1,z=1))
    if kind=='release': d['members'][0].update(release_i=['RX'],release_j=['RX'])
    if kind=='case': d['combinations']={'C':{'unknown':1}}
    if kind=='density': d['materials'][0]['mass_density']=7850
    if kind=='spring': d['nodes'][0]['springs']={'UX':100}
    with pytest.raises(ModelError): validate(d)

def test_density_conversion(): assert weight_density({'mass_density':1000})==pytest.approx(9.80665)

def test_geometry_preview_merges_but_does_not_store():
    d=from_lines([([0,0,0],[3,0,0]),([3,0,0],[3,0,4]),([0,0,0],[3,0,0])],migrate2d(benchmark()))
    assert len(d['nodes'])==3 and len(d['members'])==2
    with pytest.raises(ModelError,match='Unrestrained'): validate(d)
