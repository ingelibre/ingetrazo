import copy
import pytest
from go_structural_analysis.model3d import cantilever3d
from go_structural_analysis.member_geometry import member_length,collinear_members
from go_structural_analysis.thai_code import apply_manager,compile_manager

def configuration():
    return dict(method='ASD',methods=['ASD','LRFD'],bindings={'D':['DL'],'L':['LL']},enabled=['TH2566-ASD-01','TH2566-LRFD-01'],custom={'Service':{'factors':{'DL':1.,'LL':.5}}})

def test_mixed_methods_preserve_independent_factors_groups_and_custom():
    m=cantilever3d(); original=copy.deepcopy(m); out=apply_manager(m,configuration())
    assert out['combinations']=={'TH2566-ASD-01':{'DL':1.,'LL':1.},'TH2566-LRFD-01':{'DL':1.4,'LL':1.7},'Service':{'DL':1.,'LL':.5}}
    assert {v['group'] for v in out['combination_metadata'].values()}=={'ASD','LRFD','Custom'}
    assert m==original

def test_legacy_single_method_still_rejects_wrong_preset():
    config=configuration(); del config['methods']
    with pytest.raises(ValueError,match='design method'): compile_manager(cantilever3d(),config)

@pytest.mark.parametrize('methods',[['ASD','ASD'],['ASD','Wrong'],'ASD'])
def test_invalid_method_groups(methods):
    config=configuration(); config['methods']=methods
    with pytest.raises(ValueError,match='design methods'): compile_manager(cantilever3d(),config)

def geometry():
    return dict(nodes=[dict(id=str(i),x=x,y=y,z=z) for i,(x,y,z) in enumerate([(0,0,0),(3,4,0),(6,8,0),(9,12,0),(3,4,4),(0,1,0),(3,5,0),(12,16,0),(15,20,0)])],members=[dict(id=mid,i=i,j=j) for mid,i,j in [('A','0','1'),('B','2','1'),('C','2','3'),('Column','1','4'),('Parallel','5','6'),('Disconnected','7','8')]])

def test_length_and_chain_reversed_diagonal_disconnected_parallel():
    m=geometry(); before=copy.deepcopy(m)
    assert member_length(m,'A')==5
    assert collinear_members(m,'A')==['A','B','C']
    assert collinear_members(m,'Column')==['Column']
    assert m==before

def test_coincident_different_node_is_not_connected():
    m=geometry(); m['nodes'].append(dict(id='coincident',x=3,y=4,z=0)); m['members'][1]['j']='coincident'
    assert collinear_members(m,'A')==['A']
