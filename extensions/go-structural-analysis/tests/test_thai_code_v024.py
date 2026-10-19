"""Golden factors transcribed independently from Gazette pages 7-8, clauses 6-7."""
import copy
import pytest
from go_structural_analysis.thai_code import presets,derive,apply_manager,clone_custom,PACK
from go_structural_analysis.model3d import cantilever3d
from go_structural_analysis.model import validate

GOLDEN=[
 {'D':1,'L':1},{'D':1,'L':.75,'W':.75},{'D':.6,'W':1},
 {'D':1,'E':.7},{'D':1,'E':.525,'L':.75},{'D':.6,'E':.7},
 {'D':1,'L':1,'H':1,'F':1,'T':1},
 {'D':1.4,'L':1.7},{'D':1.05,'L':1.275,'W':1.6},{'D':.9,'W':1.6},
 {'D':1.05,'L':1.275,'E':1},{'D':.9,'E':1},
 {'D':1.4,'L':1.7,'H':1.7},{'D':.9,'H':1.7},
 {'D':1.4,'L':1.7,'F':1.4},{'D':.9,'F':1.4},
 {'D':1.05,'T':1.05,'L':1.275},{'D':1.4,'T':1.4},
]
@pytest.mark.parametrize('index',range(18))
def test_independent_golden_factors(index):
    row=presets()[index]
    assert row['factors']==GOLDEN[index]
    assert row['clause'].startswith('6' if index<7 else '7')
    assert row['code_pack']['source_sha256']==PACK['source_sha256']
    row['factors']['D']=123
    assert presets()[index]['factors']==GOLDEN[index]

def inputs(method='ASD'):
    m=cantilever3d(); m['cases']=['DL','LL','WX+','WX-','WY+','WY-','EX+','EX-','EY+','EY-','H','F','T']
    c=dict(method=method,bindings={'D':['DL'],'L':['LL'],'W':m['cases'][2:6],'E':m['cases'][6:10],'H':['H'],'F':['F'],'T':['T']},
        action_verification={a:dict(equivalent_force_model=True,verified_action=True,reference='independent verified action model') for a in 'EHFT'},enabled=[],custom={})
    return m,c

@pytest.mark.parametrize('action,index',[('W',1),('E',3)])
def test_directional_not_simultaneous(action,index):
    m,c=inputs(); rows,warnings=derive(presets()[index],m,c)
    assert not warnings and len(rows)==4
    assert all(len(set(r['factors'])&set(c['bindings'][action]))==1 for r in rows)
    assert all(r['origin']=='Derived directional combination' for r in rows)

@pytest.mark.parametrize('action,index',[('D',0),('W',1),('E',3),('H',6),('F',6),('T',6)])
def test_missing_and_unsupported(action,index):
    m,c=inputs(); c['bindings'][action]=[]
    assert not derive(presets()[index],m,c)[0]
    assert 'Missing Input: '+action in derive(presets()[index],m,c)[1]
    m,c=inputs()
    if action in 'EHFT':
        c['action_verification'].pop(action)
        assert any('Disabled' in w for w in derive(presets()[index],m,c)[1])

def test_protection_method_and_clone():
    m,c=inputs(); c['enabled']=[presets('ASD')[0]['id']]; m=apply_manager(m,c); validate(m)
    changed=copy.deepcopy(m); changed['combinations'][c['enabled'][0]]['DL']=7
    with pytest.raises(ValueError,match='Protected'): validate(changed)
    c['custom']['My custom']=clone_custom(presets()[0],'My custom',{'DL':.8,'LL':-1})
    m=apply_manager(m,c); assert m['combination_metadata']['My custom']['method']=='Custom'
    c['enabled'].append(presets('LRFD')[0]['id'])
    with pytest.raises(ValueError,match='method'): apply_manager(m,c)

def test_self_weight_once_and_duplicate():
    m,c=inputs(); m['self_weight']=True; m['self_weight_case']='DL'
    assert not derive(presets()[0],m,c)[1]
    m['self_weight_case']='LL'
    assert any('Self-weight' in w for w in derive(presets()[0],m,c)[1])
    m['self_weight_case']='DL'; m['point_loads'][0]['source']='self_weight'
    assert any('duplication' in w for w in derive(presets()[0],m,c)[1])

def test_disabled_custom_combination():
    m,c=inputs(); c['custom']={'Disabled custom':dict(factors={'DL':2},enabled=False)}
    assert not apply_manager(m,c)['combinations']
