"""Independent Gazette factor table + closed-form cantilever responses."""
import pytest
from test_thai_code_v024 import GOLDEN
from go_structural_analysis.model import benchmark
from go_structural_analysis.model3d import cantilever3d
from go_structural_analysis.thai_code import presets,apply_manager
from go_structural_analysis.worker import solve

@pytest.mark.parametrize('dimension',[2,3])
@pytest.mark.parametrize('index',range(18))
def test_all_statutory_formulas_solver(index,dimension):
    d=cantilever3d() if dimension==3 else benchmark()
    if dimension==2:
        d['nodes']=[dict(id='N1',x=0,z=0,support='Fixed'),dict(id='N2',x=4,z=0,support='Free')]
    vectors={'DL':(0,0,-15),'LL':(0,0,-10),'WX+':(7,0,0),'WX-':(-7,0,0),'EX+':(9,0,0),'EX-':(-9,0,0),'H':(0,0,-3),'F':(0,0,-2),'T':(0,0,1)}
    if dimension==3: vectors.update({'WY+':(0,3,0),'WY-':(0,-3,0),'EY+':(0,4,0),'EY-':(0,-4,0)})
    bindings=dict(D=['DL'],L=['LL'],W=[c for c in vectors if c.startswith('W')],E=[c for c in vectors if c.startswith('E')],H=['H'],F=['F'],T=['T'])
    d.update(cases=list(vectors),point_loads=[],distributed_loads=[])
    for case,vector in vectors.items():
        for axis,value in zip(('FX','FY','FZ'),vector):
            if value: d['point_loads'].append(dict(node='N2',direction=axis,value=value,case=case))
    row=presets()[index]
    config=dict(method=row['method'],bindings=bindings,enabled=[row['id']],custom={},action_verification={a:dict(verified_action=True,equivalent_force_model=True,reference='independent prescribed nodal action') for a in 'EHFT'})
    d=apply_manager(d,config); result=solve(d)
    E=d['materials'][0]['E']; A=d['sections'][0]['A']; Iy=d['sections'][0]['Iy']; Iz=d['sections'][0]['Iz']; L=4
    for name in d['combinations']:
        info=d['combination_metadata'][name]; reference=[0.,0.,0.]
        for action,factor in GOLDEN[index].items():
            cases=[info['directions'][action]] if action in ('W','E') else bindings[action]
            for case in cases:
                for j,value in enumerate(vectors[case]): reference[j]+=factor*value
        fx,fy,fz=reference; fixed=result['cases'][name]['nodes']['N1']; free=result['cases'][name]['nodes']['N2']
        assert fixed['Fx' if dimension==3 else 'Rx']==pytest.approx(-fx,abs=1e-8)
        assert fixed['Fz' if dimension==3 else 'Rz']==pytest.approx(-fz,abs=1e-8)
        assert fixed['My']==pytest.approx(fz*L if dimension==3 else -fz*L,abs=1e-8)
        assert free['ux']==pytest.approx(fx*L/(E*A),abs=1e-10)
        assert free['uz']==pytest.approx(fz*L**3/(3*E*Iz),abs=1e-10)
        if dimension==3:
            assert fixed['Fy']==pytest.approx(-fy,abs=1e-8)
            assert free['uy']==pytest.approx(fy*L**3/(3*E*Iy),abs=1e-10)
        assert result['cases'][name]['equilibrium']['passed']

@pytest.mark.parametrize('dimension',[2,3])
def test_statutory_selfweight_not_repeated(dimension):
    d=cantilever3d() if dimension==3 else benchmark()
    d.update(cases=['DL','LL'],point_loads=[],distributed_loads=[],self_weight=True,self_weight_case='DL')
    c=dict(method='LRFD',bindings={'D':['DL'],'L':['LL']},enabled=['TH2566-LRFD-01'],custom={})
    r=solve(apply_manager(d,c)); key='Fz' if dimension==3 else 'Rz'
    total=sum(n[key] for n in r['cases']['TH2566-LRFD-01']['nodes'].values())
    length=4 if dimension==3 else 6
    assert total==pytest.approx(1.4*d['materials'][0]['rho']*d['sections'][0]['A']*length)
