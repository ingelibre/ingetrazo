import contextlib
import io
from pathlib import Path
import sys
import pytest
sys.path.insert(0,str(Path(__file__).parents[1]/'go_structural_analysis'))
from materials import material_preset
from model import benchmark
from worker import solve

@pytest.mark.parametrize('name',['Concrete','Aluminium','Wood'])
def test_material_solver_and_selfweight(name):
    d=benchmark(); original_E=d['materials'][0]['E']; material=material_preset(name)
    d['materials'].append(material); d['members'][0]['material']=name
    with contextlib.redirect_stdout(io.StringIO()): r=solve(d)['cases']['LC1']
    assert r['nodes']['N1']['Rz']==pytest.approx(30.)
    assert r['members']['B1']['extrema']['d']['min']['value']==pytest.approx(-.010546875*original_E/material['E'])
    d['self_weight']=True
    with contextlib.redirect_stdout(io.StringIO()): r=solve(d)['cases']['LC1']
    assert sum(n['Rz'] for n in r['nodes'].values())==pytest.approx(60.+material['rho']*.01*6.)

def test_presets_independent_and_weight_units():
    wood=material_preset('Wood'); wood['E']=1
    assert material_preset('Wood')['E']==11000000.
    assert material_preset('Aluminium')['rho']==pytest.approx(26.477955)
    assert material_preset('Wood')['rho']==pytest.approx(4.118793)
